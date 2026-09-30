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

logger = logging.getLogger(__name__)

VISION_ACTIVA    = os.getenv("VISION_ACTIVA", "1").strip().lower() not in ("0", "false", "no")
VISION_MODEL     = os.getenv("VISION_MODEL", "gpt-6-luna")
VISION_TIMEOUT_S = float(os.getenv("VISION_TIMEOUT_S", "20"))
VISION_REASONING = os.getenv("VISION_REASONING", "low")
LADO_MAXIMO_PX   = 1280  # las fotos se achican antes de mandarlas (menos tokens, mismo detalle útil)
MAX_FOTOS_GRUPO  = 6     # tope de fotos por llamada de agrupar_objetos

ELEMENTOS = ["tapa_acceso", "tapa_inspeccion", "marco", "pared_revoque", "piso", "otro"]
ESTADOS   = ["bueno", "regular", "malo"]
CALIDADES = ["buena", "borrosa", "oscura", "muy_lejos"]

# Structured Outputs: el modelo tiene que devolver exactamente este JSON
_SCHEMA_FOTO = {
    "type": "object",
    "additionalProperties": False,
    "required": ["elemento_detectado", "tipo_tapa_seguro", "coincide_con_lo_declarado", "estado",
                 "danos_visibles", "respalda_la_reparacion", "requiere_revoque", "calidad_foto",
                 "comentario"],
    "properties": {
        "elemento_detectado":        {"type": "string", "enum": ELEMENTOS},
        "tipo_tapa_seguro":          {"type": "boolean"},
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

_PROMPT_FOTO = """Sos inspector de tanques de agua (cisternas, reservas e intermediarios) en edificios de Argentina.
El operario dice que esta foto es del tanque {tanque}. Escribió estas reparaciones: "{reparacion}".
Ítems que declaró y que hay que respaldar con fotos: {items}.

Cómo reconocer cada elemento:
- tapa_acceso: tapa grande (47 a 65 cm) por donde entra una persona al tanque. Puede ser cuadrada,
  octagonal con parantes, de punta recortada o de 12 agujeros. Suele ir apoyada sobre un marco.
- tapa_inspeccion: tapa chica (30 a 80 cm) para mirar adentro, sin entrar. Puede ser de entrada de
  agua (con la bajada o el caño de entrada) o ciega.
- marco: el borde metálico o de hormigón donde apoya la tapa de acceso (sin la tapa, o la unión tapa-marco).
- pared_revoque: paredes o techo interior del tanque (revoque, cemento, azulejo).
- piso: fondo del tanque.
Las tapas de inspección grandes (60 u 80 cm) pueden medir lo mismo que una de acceso. Si es una tapa
pero no podés distinguir con seguridad si es de acceso o de inspección, poné tipo_tapa_seguro = false.
Si no es una tapa, tipo_tapa_seguro = true.

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


def achicar_imagen(data: bytes) -> Optional[bytes]:
    """JPEG con el lado mayor en LADO_MAXIMO_PX. None si no es una imagen que se pueda abrir."""
    from PIL import Image, ImageOps
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception as e:
        logger.warning("No se pudo abrir la imagen: %s", e)
        return None
    img.thumbnail((LADO_MAXIMO_PX, LADO_MAXIMO_PX))
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


def _llamar(prompt: str, imagenes: list, nombre: str, schema: dict) -> Optional[str]:
    """Una llamada al modelo con imágenes JPEG. None si está apagado o falla."""
    if not VISION_ACTIVA or not os.getenv("OPENAI_API_KEY"):
        return None
    contenido = [{"type": "text", "text": prompt}]
    for jpeg in imagenes:
        contenido.append({"type": "image_url", "image_url": {
            "url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode(), "detail": "high"}})
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
    prompt = _PROMPT_FOTO.format(tanque=tanque, reparacion=(reparacion or "").strip()[:500],
                                 items=items or "no especificados")
    texto = _llamar(prompt, [jpeg], "analisis_foto", _SCHEMA_FOTO)
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
    texto = _llamar(prompt, jpegs, "objetos_por_foto", _SCHEMA_GRUPOS)
    if texto is None:
        return None
    grupos = parsear_grupos(texto, len(jpegs))
    if grupos is None:
        logger.warning("Visión: agrupación ilegible: %r", texto[:200])
    return grupos
