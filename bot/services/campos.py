"""
campos.py
---------
Formato estándar de los datos que el operario carga a mano, para que la calculadora y el
informe reciban siempre lo mismo:

- Medida: metros con 2 decimales, "alto, ancho, profundo" -> "1.80, 2.00, 1.50". Varios tanques: "2 tanques: 1.80, ..." o "Tanque 1: ... | Tanque 2: ...".
  En litros: "2000 lts (plástico)".
- Reparaciones: código del CSV de artículos + tipo y medida del catálogo, separadas por coma
  -> "TITCEA 60x60, TATCC 12 agujeros punta recortada 56.5, revoque frente y piso, flotante",
  o "No".
- Teléfono: 10 dígitos con código de área, sin espacios -> "1135456067".
"""

import re

_NUMERO = re.compile(r"\d+(?:[.,]\d+)?")

LETRA_TANQUE = {"CISTERNA": "C", "RESERVA": "R", "INTERMEDIARIO": "H"}
VARIANTES = {"EA": "entrada de agua", "C": "ciego"}
SIN_REPARACIONES = "No"
NO_TIENE = "No tiene"

# Catálogo de reparaciones (planilla del dueño, 2026-10-07). El operario elige de acá; no se
# escribe nada. {grupo: (botón, prefijo del código, {tipo: (botón, descripción, medidas)})}.
# Los grupos sin prefijo no llevan código ni medida (revoque, flotante, automático).
CATALOGO_REPARACIONES = {
    "tit": ("Tapa de inspección", "TIT", {
        "ins": ("", "", ["30x30", "40x40", "50x50", "60x60", "80x80"]),
    }),
    "tat": ("Tapa de acceso", "TAT", {
        "com": ("Comunes (47 a 52)", "", ["47x47", "48x48", "49x49", "50x50", "52x52"]),
        "est": ("39x49 / 54 / 60", "", ["39x49", "54", "60"]),
        "oct": ("Octogonal con parantes", "octogonal con parantes", ["53.5x56.5", "54x54"]),
        "pun": ("Punta recortada con parantes", "punta recortada con parantes", ["54"]),
        "12a": ("12 agujeros punta recortada", "12 agujeros punta recortada", ["49.5", "56", "56.5", "58"]),
        "evi": ("Evita marco", "evita marco", ["62", "69"]),
    }),
    "tmt": ("Tapa y marco de acceso", "TMT", {
        "tm": ("", "", ["48x48", "49x49", "50x50", "52x52", "54x54", "60x60"]),
    }),
    "mat": ("Marco solo", "MAT", {
        "ma": ("", "", ["48", "49", "50", "52", "54", "60"]),
    }),
    "rev": ("Revoque", None, {}),
    "flo": ("Flotante", None, {}),
    "aut": ("Automático", None, {}),
}
# Emoji de cada botón del menú, para distinguirlos de un vistazo
EMOJI_REPARACION = {"tit": "🔍", "tat": "🚪", "tmt": "🔲", "mat": "🖼", "rev": "🧱", "flo": "🛟", "aut": "⚡"}
# Revoque: un ítem por cara, con la nomenclatura del dueño (2026-10-07):
#   T + tanque (C/R/H) + cuba (EA/C), espacio, pared (F, CF, LI, LD, P), espacio, COMP o PARC,
#   y si es parche, espacio y la medida en metros:  "TCEA F COMP", "TRC LI PARC 1.50x1.50".
# Si el tanque tiene una sola cuba, va EA.
CARAS_REVOQUE = {"F": "frente", "CF": "contrafrente", "LI": "lateral izquierdo",
                 "LD": "lateral derecho", "P": "piso"}
CUBAS = {"EA": "entrada de agua", "C": "ciego"}
RE_CODIGO_REVOQUE = re.compile(r"\bT([CRH])(EA|C) (F|CF|LI|LD|P) (COMP|PARC)(?: (\d+(?:\.\d+)?)x(\d+(?:\.\d+)?))?\b")


def reparacion(grupo: str, tanque: str = "", variante: str = "", tipo: str = "", medida: str = "",
               cara: str = "", parche: str = "") -> str:
    """
    Texto estándar de una reparación del catálogo (sin comas: las reparaciones se separan con coma):
    ('tat', 'CISTERNA', 'EA', 'oct', '54x54')        -> 'TATCEA octogonal con parantes 54x54'
    ('rev', 'CISTERNA', 'EA', cara='F')              -> 'TCEA F COMP'
    ('rev', 'RESERVA', 'C', cara='LI', parche='1.50x1.50')
                                                     -> 'TRC LI PARC 1.50x1.50'
    ('flo',)                                         -> 'flotante'
    """
    boton, prefijo, tipos = CATALOGO_REPARACIONES[grupo]
    if grupo == "rev":
        extension = f"PARC {parche}" if parche else "COMP"
        return f"T{LETRA_TANQUE[tanque.upper()]}{variante} {cara} {extension}"
    if prefijo is None:
        return boton.lower()
    descripcion = tipos[tipo][1]
    return f"{prefijo}{LETRA_TANQUE[tanque.upper()]}{variante} {descripcion} {medida}".replace("  ", " ")


def es_revoque(descripcion: str) -> bool:
    """Para extract_reports.py: revoque en código ("TCEA F COMP") o escrito ("revoque lateral...")."""
    d = (descripcion or "").strip()
    return d.lower().startswith("revoque") or bool(RE_CODIGO_REVOQUE.match(d.upper()))


def medidas_tanque_m(texto: str) -> list:
    """
    Para extract_reports.py: alto, ancho y profundo en metros. El bot las manda "1.80, 2.00, 1.50";
    en reportes viejos pueden venir en centímetros ("180 200 150"): más de 15 se toma como cm.
    """
    numeros = [float(n.replace(",", ".")) for n in _NUMERO.findall(texto or "")]
    return [n / 100 if n > _MAX_M else n for n in numeros[:3]]


def medida_del_tanque(report: dict, subtanque: str) -> str:
    """
    Para extract_reports.py: "Medida <tanque>" del mail (sin importar mayúsculas), ej. "Medida
    Reserva 2 (fondo)". En reportes viejos, "Medida principal" era la del primer tanque.
    """
    buscada = f"medida {subtanque}".lower()
    for k, v in report.items():
        if k.lower() == buscada:
            return v
    return report.get("Medida principal", "")


NOMBRE_CODIGO = {"TIT": "Tapa de inspección", "TAT": "Tapa de acceso", "TMT": "Tapa y marco de acceso",
                 "MAT": "Marco solo"}
_RE_ITEM_CODIGO = re.compile(r"^(TIT|TAT|TMT|MAT)[CRH](EA|C) (.+)$")



def legible(item: str) -> str:
    """
    Una reparación guardada, en palabras para el operario:
    'TITCEA 30x30' -> 'Tapa de inspección 30x30 (entrada de agua)'
    'TRC LI PARC 1.50x1.00' -> 'Revoque lateral izquierdo (ciego): parche de 1.50 x 1.00 m'
    """
    m = _RE_ITEM_CODIGO.match(item)
    if m:
        return f"{NOMBRE_CODIGO[m.group(1)]} {m.group(3)} ({CUBAS[m.group(2)]})"
    m = RE_CODIGO_REVOQUE.fullmatch(item)
    if m:
        extension = f"parche de {m.group(5)} x {m.group(6)} m" if m.group(4) == "PARC" else "completo"
        return f"Revoque {CARAS_REVOQUE[m.group(3)]} ({CUBAS[m.group(2)]}): {extension}"
    return item[:1].upper() + item[1:]


_PARCHE_MAX_M = 15.0


def normalizar_parche(texto: str):
    """
    Medidas de un parche de revoque en metros: '2x2' -> '2.00x2.00'; '1,5 x 1,5' -> '1.50x1.50'.
    (valor, None), o (None, motivo) si no son 2 medidas razonables.
    """
    numeros = _NUMERO.findall((texto or "").lower())
    if len(numeros) != 2:
        return None, ("Escribí las 2 medidas del parche en metros, largo x alto "
                      "(ej: 2x2 o 1,5 x 1,5).")
    metros = [float(n.replace(",", ".")) for n in numeros]
    if not all(0 < m <= _PARCHE_MAX_M for m in metros):
        return None, "Las medidas del parche van en metros, entre 0.01 y 15 (ej: 2x2 o 1,5 x 1,5)."
    return f"{metros[0]:.2f}x{metros[1]:.2f}", None


# Tapas (texto, con la ayuda de siempre en la pregunta): solo se aceptan estas medidas.
# En la ayuda de acceso "4789" abrevia 47, 48 y 49, y "50125" abrevia 50, 51, 52 y 55.
# 39x49, 53.5, 60 y 69 vienen de la planilla del dueño (no están en la ayuda).
MEDIDAS_TAPAS = {
    "insp":   ["30", "40", "50", "60", "80"],
    "acceso": ["39x49", "47", "48", "49", "49.5", "50", "51", "51.5", "52", "53.5", "54", "55",
               "56", "56.5", "58", "60", "62", "65", "69"],
}
_SIN_TAPAS = re.compile(r"(no|no tiene|no hay|ninguna|ninguno|nada|sin tapas?|0|-)")
# Medida de tapa: "39x49", o entero o ",5"/".5" ("49,50" son dos tapas: 49 y 50)
_MEDIDA_TAPA = re.compile(r"\d+(?:[.,]5)?\s*x\s*\d+(?:[.,]5)?|\d+(?:[.,]5(?!\d))?")


def _medida_tapa(escrita: str) -> str:
    """'49,5' -> '49.5'; '39 x 49' -> '39x49'; lado igual ('60x60') -> '60'."""
    medida = re.sub(r"\s+", "", escrita).replace(",", ".")
    lados = medida.split("x")
    return lados[0] if len(lados) == 2 and lados[0] == lados[1] else medida


def normalizar_tapas(campo: str, texto: str):
    """
    (valor, None) con las medidas separadas por coma ("30, 60") o "No tiene"; (None, motivo) si
    hay algo que no es una de las medidas aceptadas.
    """
    t = (texto or "").lower().strip().strip(".")
    if _SIN_TAPAS.fullmatch(t):
        return NO_TIENE, None
    medidas = [_medida_tapa(m) for m in _MEDIDA_TAPA.findall(t)]
    sobra = _MEDIDA_TAPA.sub(" ", t)
    validas = MEDIDAS_TAPAS[campo]
    ayuda = (f"Solo se aceptan estas medidas: {' '.join(validas)}. Escribí la medida de cada "
             "tapa (ej: " + ("30 60" if campo == "insp" else "47 56.5") + "), o «No tiene».")
    if not medidas or re.search(r"[^\s,;/\-y]", sobra):
        return None, ayuda
    invalidas = [m for m in medidas if m not in validas]
    if invalidas:
        return None, f"{', '.join(invalidas)} no es una medida válida. {ayuda}"
    return ", ".join(medidas), None


def normalizar_una_tapa(campo: str, texto: str, acepta_no_tiene: bool = False):
    """
    Una sola tapa por respuesta (se pregunta de a una): (medida o "No tiene", None) o (None, motivo).
    campo: "insp" o "acceso".
    """
    valor, problema = normalizar_tapas(campo, texto)
    if problema:
        return None, problema.replace("Escribí la medida de cada tapa", "Escribí la medida de esta tapa")
    if valor == NO_TIENE and not acepta_no_tiene:
        return None, f"Escribí la medida de esta tapa ({' '.join(MEDIDAS_TAPAS[campo])})."
    if ", " in valor:
        return None, "Escribí una sola medida: después te pregunto por la siguiente tapa."
    return valor, None


MATERIALES = {"plastico": "plástico", "cilindrico": "cilíndrico", "acero": "acero inoxidable"}

AYUDA_MEDIDA = ("Escribí las 3 medidas: alto, ancho y profundo, en metros o en centímetros.\n"
                "Ej: 1.80 2 1.50  o  180 200 150.\n"
                "Si son varios tanques iguales: 2 tanques 1.80 1.80 1.80.\n"
                "Si es de plástico o cilíndrico: 1000 litros.")

_MIN_M, _MAX_M = 0.2, 15.0


def _a_metros(numero: str):
    """'1,8' -> 1.8 ; '180' -> 1.8 (más de 15 se toma como centímetros). None si no es razonable."""
    valor = float(numero.replace(",", "."))
    if valor > _MAX_M:
        valor /= 100
    return valor if _MIN_M <= valor <= _MAX_M else None


def _tres_medidas(numeros: list):
    metros = [_a_metros(n) for n in numeros]
    if None in metros:
        return None
    return ", ".join(f"{m:.2f}" for m in metros)


def normalizar_medida(texto: str):
    """
    (valor, None) con la medida en el formato estándar, o (None, motivo) si no se entiende.
    Los litros sin material devuelven ("LITROS:<n>", None): hay que preguntar el material.
    """
    t = (texto or "").lower().strip()
    numeros = _NUMERO.findall(t)

    if "litro" in t or re.search(r"\d\s*lts?\b", t):
        if len(numeros) != 1:
            return None, "Indicá un solo número de litros (ej: 1000 litros)."
        litros = numeros[0].replace(",", ".")
        for clave, nombre in MATERIALES.items():
            if clave in t.replace("á", "a").replace("í", "i"):
                return f"{litros} lts ({nombre})", None
        return f"LITROS:{litros}", None

    # "2 tanques 1.80 1.80 1.80": la cantidad va primero
    m = re.match(r"^\s*(\d+)\s*tanques?\b", t)
    if m and len(numeros) == 4:
        valor = _tres_medidas(numeros[1:])
        if valor and int(m.group(1)) >= 1:
            return (valor if int(m.group(1)) == 1 else f"{m.group(1)} tanques: {valor}"), None

    if len(numeros) == 3:
        valor = _tres_medidas(numeros)
        if valor:
            return valor, None
        return None, "Alguna medida no es razonable (tienen que estar entre 0.20 y 15 metros)."

    # Varios tanques con medidas distintas: de a 3 números
    if len(numeros) > 3 and len(numeros) % 3 == 0:
        grupos = [_tres_medidas(numeros[i:i + 3]) for i in range(0, len(numeros), 3)]
        if None not in grupos:
            return " | ".join(f"Tanque {i}: {g}" for i, g in enumerate(grupos, 1)), None

    return None, f"Necesito 3 medidas por tanque y encontré {len(numeros)}."


def normalizar_telefono(texto: str):
    """Teléfono argentino de 10 dígitos ('011 3545-6067', '+54 9 11 3545 6067' -> '1135456067')."""
    digitos = re.sub(r"\D", "", texto or "")
    if digitos.startswith("54") and len(digitos) in (12, 13):
        digitos = digitos[2:]
        if len(digitos) == 11 and digitos.startswith("9"):
            digitos = digitos[1:]
    if len(digitos) == 11 and digitos.startswith("0"):
        digitos = digitos[1:]
    return digitos if len(digitos) == 10 else None


def separar_nombre_telefono(texto: str):
    """'Daniel 11 3545 6067' -> ('Daniel', '1135456067'); teléfono None si no hay uno válido."""
    t = (texto or "").strip()
    m = re.search(r"[+\d][\d\s\-().]{7,}\d", t)
    if not m:
        return t, None
    nombre = (t[:m.start()] + " " + t[m.end():]).strip(" ,;-:")
    return re.sub(r"\s+", " ", nombre), normalizar_telefono(m.group(0))


# Respuestas para esquivar el nombre del encargado (es obligatorio)
_SIN_NOMBRE = re.compile(r"(no|nadie|ninguno|ninguna|n/?a|no (habia|hay|estaba|tiene|se|sabe|dio|dijo)\b.*"
                         r"|sin (encargado|nombre|dato)s?|desconocido|no se sabe|-+|\.+)")


def nombre_valido(nombre: str) -> bool:
    t = (nombre or "").strip()
    sin_tildes = t.lower().translate(str.maketrans("áéíóú", "aeiou"))
    if _SIN_NOMBRE.fullmatch(sin_tildes):
        return False
    return bool(re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{2,}", t)) and len(t) <= 60
