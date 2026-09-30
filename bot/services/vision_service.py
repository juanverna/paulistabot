"""
vision_service.py
-----------------
Revisión con IA (OpenAI, modelo con visión) de las fotos de reparaciones.

- analizar_foto: qué muestra una foto, en qué estado está, si respalda la reparación y si
  la foto es usable.
- agrupar_objetos: dadas varias fotos del mismo ítem (ej: 2 tapas de acceso), cuántos
  objetos físicos distintos muestran (la de entrada de agua y la del ciego, no la misma
  tapa dos veces).

Si la API falla, tarda más de VISION_TIMEOUT_S o responde algo que no se puede leer, el
resultado es None ("sin validar") y el flujo sigue: nunca se traba al operario por la IA.
"""

import os
import io
import json
import base64
import logging
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)

VISION_ACTIVA    = os.getenv("VISION_ACTIVA", "1").strip().lower() not in ("0", "false", "no")
VISION_MODEL     = os.getenv("VISION_MODEL", "gpt-6-luna")
VISION_TIMEOUT_S = float(os.getenv("VISION_TIMEOUT_S", "30"))
# medium: con low la IA a veces se equivocaba "segura" entre tapa de acceso e inspección (0 de 18 con
# medium, 1 de 18 con low, sobre las fotos de referencia); cuesta ~0,015 centavos más por foto.
VISION_REASONING = os.getenv("VISION_REASONING", "medium")
LADO_MAXIMO_PX   = 1280  # las fotos se achican antes de mandarlas (menos tokens, mismo detalle útil)
MAX_FOTOS_GRUPO  = 6     # tope de fotos por llamada de agrupar_objetos

# Fotos de referencia (ejemplos reales de la empresa): bot/referencias/<elemento>/*.jpg
# Se le muestran a la IA junto a cada foto para que reconozca cada tipo de tapa, marco, revoque...
REFERENCIAS_DIR  = Path(__file__).resolve().parent.parent / "referencias"
VISION_MAX_REF   = int(os.getenv("VISION_MAX_REF", "10"))        # por elemento
VISION_REF_DETAIL = os.getenv("VISION_REF_DETAIL", "low")        # low: menos tokens por ejemplo
LADO_REFERENCIA_PX = 768

ELEMENTOS = ["tapa_acceso", "tapa_inspeccion", "marco", "pared_revoque", "piso", "otro"]
ESTADOS   = ["bueno", "regular", "malo"]
CALIDADES = ["buena", "borrosa", "oscura", "muy_lejos"]

# Structured Outputs: el modelo tiene que devolver exactamente este JSON
_SCHEMA_FOTO = {
    "type": "object",
    "additionalProperties": False,
    "required": ["elemento_detectado", "tipo_tapa_seguro", "tapa_faltante", "coincide_con_lo_declarado",
                 "estado", "danos_visibles", "respalda_la_reparacion", "requiere_revoque", "calidad_foto",
                 "comentario"],
    "properties": {
        "elemento_detectado":        {"type": "string", "enum": ELEMENTOS},
        "tipo_tapa_seguro":          {"type": "boolean"},
        "tapa_faltante":             {"type": "boolean"},
        "coincide_con_lo_declarado": {"type": "boolean"},
        "estado":                    {"type": "string", "enum": ESTADOS},
        "danos_visibles":            {"type": "array", "items": {"type": "string"}},
        "respalda_la_reparacion":    {"type": "boolean"},
        "requiere_revoque":          {"type": "boolean"},
        "calidad_foto":              {"type": "string", "enum": CALIDADES},
        "comentario":                {"type": "string"},
    },
}

_SCHEMA_GRUPOS = {
    "type": "object",
    "additionalProperties": False,
    "required": ["objeto_por_foto", "comentario"],
    "properties": {
        "objeto_por_foto": {"type": "array", "items": {"type": "integer"}},
        "comentario":      {"type": "string"},
    },
}

# Parte fija del pedido (igual en todas las llamadas: OpenAI la cachea junto con las referencias)
_PROMPT_FOTO = """Sos inspector de tanques de agua (cisternas, reservas e intermediarios) en edificios de Argentina.
Vas a analizar la foto de una reparación que manda un operario.

Cómo reconocer cada elemento:
- tapa_acceso: tapa grande (47 a 65 cm) por donde entra una persona al tanque. Casi siempre está en
  una PARED del tanque (vertical), muchas veces sujeta con planchuelas o parantes atornillados. Puede
  ser cuadrada, de punta recortada o de 12 agujeros. Las tapas OCTOGONALES son siempre de acceso.
  Las cuadradas con PERNOS (espárragos) que sobresalen cerca de las esquinas, para atornillar los
  parantes o planchuelas, también son de acceso, aunque estén sacadas o sin los parantes puestos.
  Suele ir apoyada sobre un marco.
- tapa_inspeccion: tapa para mirar adentro, sin entrar. Casi siempre está ARRIBA, en la losa o techo
  del tanque (horizontal, se ve desde arriba). Suelen ser cuadradas metálicas (a veces de chapa con
  relieve o dibujo), plásticas, o circulares chicas. Puede ser de entrada de agua (con la bajada o el
  caño de entrada) o ciega.
- marco: el borde metálico o de hormigón donde apoya la tapa de acceso (sin la tapa, o la unión tapa-marco).
- pared_revoque: revoque de las paredes, el techo o el piso interior del tanque (cemento, azulejo).
  Si se ven placas de revoque desprendidas en el piso, también es pared_revoque.
- piso: fondo del tanque, cuando lo que se muestra no es el revoque (ej: suciedad, desagüe).
Para decidir entre acceso e inspección pesan más la ubicación (pared vertical = acceso; losa de
arriba, horizontal = inspección) y la forma (octogonal = acceso; plástica o circular = inspección)
que el tamaño aparente en la foto.
Ojo: si la tapa está SACADA (apoyada en el piso, contra una pared o sostenida con la mano), la
ubicación no sirve: una tapa apoyada en el piso siempre se ve horizontal y eso NO indica que sea de
inspección. Decidí por la forma, el tamaño y si tiene pernos, planchuelas o parantes; si igual no
estás seguro, tipo_tapa_seguro = false.
Las tapas de inspección grandes (60 u 80 cm) pueden medir lo mismo que una de acceso. Si es una tapa
pero no podés distinguir con seguridad si es de acceso o de inspección, poné tipo_tapa_seguro = false.
Si no es una tapa, tipo_tapa_seguro = true.
Si hay fotos de referencia de la empresa, comparala con ellas para decidir qué elemento es: si se
parece claramente a los ejemplos de un tipo de tapa, tipo_tapa_seguro = true.

Tapa faltante: a veces donde debería haber una tapa (casi siempre de inspección) no hay una tapa
propiamente dicha: solo está el agujero o la abertura, o está tapado con algo improvisado y sin marco
(una losa de hormigón con hierros para moverla, una madera, una chapa suelta). En ese caso
elemento_detectado es el tipo de tapa que falta (tapa_inspeccion, o tapa_acceso si la abertura es
para entrar), tapa_faltante = true, estado = "malo" y respalda_la_reparacion = true (hay que colocar
una tapa de verdad). Si hay una tapa metálica con su marco, tapa_faltante = false.

Criterios de estado:
- Tapa o marco en mal estado: óxido con nódulos, perforaciones, deformación, bordes deteriorados.
- Revoque en mal estado (requiere_revoque = true): placas desprendidas, fisuras, sectores huecos o
  sueltos, hierro expuesto.

Respondé:
- coincide_con_lo_declarado: true si la foto muestra alguno de los ítems declarados.
- respalda_la_reparacion: true si en la foto se ve un daño que justifica la reparación de ese elemento.
- calidad_foto: "borrosa", "oscura" o "muy_lejos" solo si eso impide evaluar el elemento; si no, "buena".
- danos_visibles: lista corta de daños que se ven (vacía si no hay).
- comentario: una frase breve en español.
Respondé SOLO en JSON."""

_PROMPT_CASO = """FOTO A ANALIZAR. El operario dice que es del tanque {tanque}.
Escribió estas reparaciones: "{reparacion}".
Ítems que declaró y que hay que respaldar con fotos: {items}."""

# Carpeta de bot/referencias/ → cómo se le presentan esos ejemplos a la IA
REFERENCIAS_CATEGORIAS = {
    "tapa_acceso":              "tapas de acceso (elemento_detectado = tapa_acceso)",
    "tapa_inspeccion":          "tapas de inspección (elemento_detectado = tapa_inspeccion)",
    "tapa_inspeccion_faltante": ("lugares donde falta una tapa de inspección propiamente dicha: "
                                 "solo el agujero, o tapado con algo improvisado y sin marco, como una "
                                 "losa de hormigón con hierros "
                                 "(elemento_detectado = tapa_inspeccion, tapa_faltante = true)"),
    "marco":                    "marcos (elemento_detectado = marco)",
    "pared_revoque":            "revoques dañados de paredes y piso (elemento_detectado = pared_revoque)",
    "piso":                     "pisos (elemento_detectado = piso)",
}

_PROMPT_GRUPOS = """Sos inspector de tanques de agua en edificios de Argentina.
Estas {n} fotos son de "{etiqueta}" del tanque {tanque}. El operario dice que hay {cantidad} distintas
(por ejemplo, la de la cuba de entrada de agua y la de la cuba ciega). Puede haber varias fotos del
mismo objeto desde distintos ángulos o distancias.

Para cada foto, en orden, indicá a qué objeto físico corresponde con un número (0, 1, 2...): dos fotos
del mismo objeto llevan el mismo número. Distinguí los objetos por el entorno (caños de entrada de
agua, bajadas, paredes, posición), la forma, las marcas y el patrón de óxido o daño; no por el
ángulo ni la luz. Si no podés asegurar que son distintos, usá el mismo número.
Respondé SOLO en JSON."""


def _limpiar_json(texto: str):
    if not texto:
        return None
    limpio = texto.strip()
    if limpio.startswith("```"):
        limpio = limpio.strip("`").strip()
        if limpio.lower().startswith("json"):
            limpio = limpio[4:]
    try:
        return json.loads(limpio)
    except (ValueError, TypeError):
        return None


def parsear_json(texto: str) -> Optional[dict]:
    """Parsea el análisis de una foto de forma segura (saca ``` y valida campos y tipos)."""
    datos = _limpiar_json(texto)
    if not isinstance(datos, dict):
        return None
    try:
        resultado = {
            "elemento_detectado":        str(datos["elemento_detectado"]),
            "tipo_tapa_seguro":          bool(datos.get("tipo_tapa_seguro", True)),
            "tapa_faltante":             bool(datos.get("tapa_faltante", False)),
            "coincide_con_lo_declarado": bool(datos["coincide_con_lo_declarado"]),
            "estado":                    str(datos["estado"]),
            "danos_visibles":            [str(d) for d in datos.get("danos_visibles") or []],
            "respalda_la_reparacion":    bool(datos["respalda_la_reparacion"]),
            "requiere_revoque":          bool(datos.get("requiere_revoque", False)),
            "calidad_foto":              str(datos["calidad_foto"]),
            "comentario":                str(datos.get("comentario", "")),
        }
    except (KeyError, TypeError):
        return None
    if resultado["elemento_detectado"] not in ELEMENTOS:
        resultado["elemento_detectado"] = "otro"
    if resultado["calidad_foto"] not in CALIDADES:
        resultado["calidad_foto"] = "buena"
    return resultado


def parsear_grupos(texto: str, n: int) -> Optional[list]:
    """Parsea la respuesta de agrupar_objetos: un número de objeto por foto."""
    datos = _limpiar_json(texto)
    if not isinstance(datos, dict):
        return None
    grupos = datos.get("objeto_por_foto")
    if not isinstance(grupos, list) or len(grupos) != n:
        return None
    if not all(isinstance(g, int) and not isinstance(g, bool) and g >= 0 for g in grupos):
        return None
    return grupos


def achicar_imagen(data: bytes, lado: int = LADO_MAXIMO_PX) -> Optional[bytes]:
    """JPEG (sin EXIF) con el lado mayor en `lado` px. None si no es una imagen que se pueda abrir."""
    from PIL import Image, ImageOps
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception as e:
        logger.warning("No se pudo abrir la imagen: %s", e)
        return None
    img.thumbnail((lado, lado))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)
    return out.getvalue()


def huella(data: bytes) -> Optional[int]:
    """dHash de 64 bits: dos fotos casi idénticas (reenviada, ráfaga) tienen huellas cercanas."""
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(data)).convert("L").resize((9, 8))
    except Exception:
        return None
    pix = list(img.getdata())
    bits = 0
    for fila in range(8):
        for col in range(8):
            bits = (bits << 1) | (pix[fila * 9 + col] > pix[fila * 9 + col + 1])
    return bits


def distancia(h1: int, h2: int) -> int:
    return bin(h1 ^ h2).count("1")


_client = None


def _cliente():
    global _client
    if _client is None:
        from openai import OpenAI
        # max_retries=0: un reintento duplicaría la espera del operario; si falla, queda "sin validar"
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=VISION_TIMEOUT_S, max_retries=0)
    return _client


def _imagen(jpeg: bytes, detalle: str = "high") -> dict:
    return {"type": "image_url", "image_url": {
        "url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode(), "detail": detalle}}


_referencias = None


def referencias() -> list:
    """[(elemento, [jpeg, ...])] de bot/referencias/. Se leen una vez; sin carpeta, lista vacía."""
    global _referencias
    if _referencias is None:
        cargadas = []
        for elemento in REFERENCIAS_CATEGORIAS:
            carpeta = REFERENCIAS_DIR / elemento
            if not carpeta.is_dir():
                continue
            archivos = sorted(p for p in carpeta.iterdir()
                              if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))[:VISION_MAX_REF]
            jpegs = [j for j in (achicar_imagen(p.read_bytes(), LADO_REFERENCIA_PX) for p in archivos) if j]
            if jpegs:
                cargadas.append((elemento, jpegs))
        _referencias = cargadas
        logger.info("Visión: referencias cargadas: %s",
                    {e: len(j) for e, j in cargadas} or "ninguna")
    return _referencias


def _contenido_referencias() -> list:
    refs = referencias()
    if not refs:
        return []
    contenido = [{"type": "text", "text": "FOTOS DE REFERENCIA (ejemplos reales de la empresa, ya clasificados):"}]
    for elemento, jpegs in refs:
        contenido.append({"type": "text", "text": f"Ejemplos de {REFERENCIAS_CATEGORIAS[elemento]}:"})
        contenido += [_imagen(j, VISION_REF_DETAIL) for j in jpegs]
    return contenido


def _llamar(contenido: list, nombre: str, schema: dict) -> Optional[str]:
    """Una llamada al modelo (texto + imágenes). None si está apagado o falla."""
    if not VISION_ACTIVA or not os.getenv("OPENAI_API_KEY"):
        return None
    try:
        respuesta = _cliente().chat.completions.create(
            model=VISION_MODEL,
            reasoning_effort=VISION_REASONING,
            response_format={"type": "json_schema",
                             "json_schema": {"name": nombre, "strict": True, "schema": schema}},
            messages=[{"role": "user", "content": contenido}],
        )
        return respuesta.choices[0].message.content
    except Exception as e:
        logger.warning("Visión: sin validar (%s: %s)", type(e).__name__, e)
        return None


def analizar_foto(data: bytes, tanque: str, reparacion: str, items: str = "") -> Optional[dict]:
    """Analiza una foto de reparación. None = sin validar (IA apagada, error, timeout o respuesta inválida)."""
    if not VISION_ACTIVA:
        return None
    jpeg = achicar_imagen(data)
    if jpeg is None:
        return None
    caso = _PROMPT_CASO.format(tanque=tanque, reparacion=(reparacion or "").strip()[:500],
                               items=items or "no especificados")
    contenido = ([{"type": "text", "text": _PROMPT_FOTO}] + _contenido_referencias()
                 + [{"type": "text", "text": caso}, _imagen(jpeg)])
    texto = _llamar(contenido, "analisis_foto", _SCHEMA_FOTO)
    if texto is None:
        return None
    resultado = parsear_json(texto)
    if resultado is None:
        logger.warning("Visión: respuesta ilegible: %r", texto[:200])
    return resultado


def agrupar_objetos(fotos: list, etiqueta: str, tanque: str, cantidad: int) -> Optional[list]:
    """
    fotos: bytes de cada foto. Devuelve un número de objeto por foto (mismo número = mismo
    objeto físico), o None si no se pudo determinar.
    """
    if not VISION_ACTIVA or len(fotos) < 2:
        return None
    jpegs = [achicar_imagen(f) for f in fotos[:MAX_FOTOS_GRUPO]]
    if any(j is None for j in jpegs):
        return None
    prompt = _PROMPT_GRUPOS.format(n=len(jpegs), etiqueta=etiqueta, tanque=tanque, cantidad=cantidad)
    texto = _llamar([{"type": "text", "text": prompt}] + [_imagen(j) for j in jpegs],
                    "objetos_por_foto", _SCHEMA_GRUPOS)
    if texto is None:
        return None
    grupos = parsear_grupos(texto, len(jpegs))
    if grupos is None:
        logger.warning("Visión: agrupación ilegible: %r", texto[:200])
    return grupos
