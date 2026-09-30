"""
items_reparacion.py
-------------------
Saca del texto de reparaciones de un tanque los ítems que necesitan foto.

Reconoce los códigos del CSV de artículos (TIT, TAT, MAT, TMT + tanque C/R/H + EA/C;
la medida se ignora) y el texto escrito tal cual ("tapa de inspección", "2 tapas de
acceso", "revocar"...). Cada ítem tiene una cantidad: si hay que cambiar 2 tapas de
acceso (por ejemplo la de entrada de agua y la del ciego), hacen falta 2 fotos de 2 tapas
distintas.

Resultado: {grupo: {"cantidad": n, "variantes": [...], "codigos": [...]}} y, si no se
reconoce ningún ítem, el grupo "otras" con todo el texto.
"""

import re
import unicodedata

ETIQUETAS = {
    "tapa_inspeccion": "Tapa de inspección",
    "tapa_acceso":     "Tapa de acceso",
    "tapa_marco":      "Tapa y marco de acceso",
    "marco":           "Marco",
    "tapa":            "Tapa",
    "revoque":         "Revoque",
    "otras":           "Otras reparaciones",
}

VARIANTES = {"EA": "entrada de agua", "C": "ciego"}

# Código del CSV → grupo
_PREFIJOS = {"TIT": "tapa_inspeccion", "TAT": "tapa_acceso", "MAT": "marco", "TMT": "tapa_marco"}
_TANQUE_CODIGO = {"C": "CISTERNA", "R": "RESERVA", "H": "INTERMEDIARIO"}
# Sin \b al final: la medida puede venir pegada al código ("TMTCEA56")
_RE_CODIGO = re.compile(r"\b(TIT|TAT|MAT|TMT)([CRH])(EA|C)(?![A-Za-z])(\s*\d+(?:[.,]\d+)?)?", re.IGNORECASE)

_NUMEROS = {"un": 1, "una": 1, "dos": 2, "ambas": 2, "ambos": 2, "tres": 3, "cuatro": 4}
_CANT = r"\b(?:(\d+|una?|dos|tres|cuatro|ambas|ambos|las dos|los dos)\s+)?"

# Texto → grupo. Se buscan en orden y lo encontrado se saca del texto (así "tapa y marco"
# no cuenta también como "tapa" y "marco").
_PATRONES = [
    ("tapa_marco",      re.compile(_CANT + r"tapas?\s+y\s+marcos?(?:\s+de\s+acceso)?")),
    ("tapa_inspeccion", re.compile(_CANT + r"tapas?\s+(?:de\s+)?insp\w*\.?")),
    ("tapa_acceso",     re.compile(_CANT + r"tapas?\s+(?:de\s+)?acceso")),
    ("marco",           re.compile(_CANT + r"marcos?\b")),
    ("revoque",         re.compile(r"\w*(?:revoqu|revoca|revocar|mamposter|fisura|desprendi)\w*")),
    ("tapa",            re.compile(_CANT + r"tapas?\b")),
]


def _normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sin_tildes.lower()


def _cantidad(match) -> int:
    palabra = (match.group(1) or "").strip()
    if not palabra:
        # "tapas" en plural sin número: al menos 2
        return 2 if re.search(r"tapas|marcos", match.group(0)) else 1
    if palabra.isdigit():
        return max(1, int(palabra))
    return _NUMEROS.get(palabra.replace("las ", "").replace("los ", ""), 2)


def detectar_items(texto: str) -> dict:
    """Ítems que necesitan foto en el texto de reparaciones de un tanque."""
    if not texto or not texto.strip():
        return {}
    items = {}

    # 1) Códigos del CSV (cada código es una unidad; la medida se ignora)
    for m in _RE_CODIGO.finditer(texto):
        grupo = _PREFIJOS[m.group(1).upper()]
        item = items.setdefault(grupo, {"cantidad": 0, "variantes": [], "codigos": []})
        item["cantidad"] += 1
        item["variantes"].append(m.group(3).upper())
        item["codigos"].append(m.group(0).strip().upper())
    resto = _normalizar(_RE_CODIGO.sub(" ", texto))

    # 2) Texto libre: la cantidad de un grupo es el máximo entre códigos y texto
    #    ("cambiar tapa de acceso TATCEA 56" es una sola tapa)
    for grupo, patron in _PATRONES:
        cantidad = 0
        for m in patron.finditer(resto):
            cantidad += 1 if grupo == "revoque" else _cantidad(m)
        if not cantidad:
            continue
        resto = patron.sub(" ", resto)
        if grupo == "revoque":
            cantidad = 1  # el revoque se cotiza por m2: una foto que lo muestre alcanza
        if grupo == "tapa" and ({"tapa_inspeccion", "tapa_acceso", "tapa_marco"} & items.keys()):
            continue  # "tapa" suelta junto a una tapa ya identificada: es la misma
        item = items.setdefault(grupo, {"cantidad": 0, "variantes": [], "codigos": []})
        item["cantidad"] = max(item["cantidad"], cantidad)

    # "tapa de acceso de entrada de agua y ciego": dos unidades (solo si hay un único tipo de tapa/marco)
    fisicos = [g for g in items if g in ("tapa_inspeccion", "tapa_acceso", "tapa_marco", "marco", "tapa")]
    if len(fisicos) == 1 and "entrada de agua" in resto and "ciego" in resto:
        items[fisicos[0]]["cantidad"] = max(items[fisicos[0]]["cantidad"], 2)

    # 3) Si no se reconoció ningún ítem, todo el texto es "otras reparaciones" (una foto).
    #    Si hubo ítems, el resto del texto se toma como descripción (no pide fotos de más).
    if not items:
        items["otras"] = {"cantidad": 1, "variantes": [], "codigos": [], "texto": texto.strip()}
    return items


def codigos_de_otro_tanque(texto: str, tanque: str) -> list:
    """Códigos del texto que son de otro tanque (ej: TATREA escrito en la cisterna)."""
    tanque = (tanque or "").upper()
    return [m.group(0).strip().upper() for m in _RE_CODIGO.finditer(texto or "")
            if _TANQUE_CODIGO[m.group(2).upper()] != tanque]


def mensaje_codigos_de_otro_tanque(texto: str, tanque: str):
    """
    Si el texto tiene códigos de otro tanque, el mensaje para que el operario los corrija.
    None si están todos bien.
    """
    tanque = (tanque or "").upper()
    lineas = []
    for m in _RE_CODIGO.finditer(texto or ""):
        de = _TANQUE_CODIGO[m.group(2).upper()]
        if de == tanque:
            continue
        codigo = m.group(0).strip().upper()
        lineas.append(f"• {codigo} es de {de.capitalize()}, no de {tanque.capitalize()}.")
    if not lineas:
        return None
    return ("⛔ Hay códigos que no son de este tanque:\n" + "\n".join(lineas) +
            f"\n\nEscribí de nuevo las reparaciones de {tanque.capitalize()} con el código correcto.")


# Los 24 códigos del CSV de artículos: prefijo + tanque + entrada de agua (EA) o ciego (C)
CODIGOS_VALIDOS = sorted(p + t + v for p in _PREFIJOS for t in _TANQUE_CODIGO for v in ("EA", "C"))

# Algo con forma de código aunque esté mal escrito: termina en tanque + EA/C ("taticea30"),
# empieza con un prefijo del CSV ("TMTCXA"), o es una palabra corta pegada a una medida
# ("TMTCXA49"). Palabras comunes (tapa, marco, masilla, materiales...) no entran.
_RE_PARECE_CODIGO = re.compile(
    r"\b([TM][A-Z]{1,6}[CRH](?:EA|C)|(?:TIT|TAT|MAT|TMT)[A-Z]{2,4}|[TM][A-Z]{3,6}(?=\d))"
    r"(\s*\d+(?:[.,]\d+)?)?\b", re.IGNORECASE)

AYUDA_CODIGOS = ("Usá los códigos establecidos (ej: TITCEA 30, TATCEA 56, TMTCEA 49, MATCEA 50) "
                 "o escribí: tapa de inspección, tapa de acceso, tapa y marco, marco o revocar. "
                 "Si no hay reparaciones, escribí No.")


def codigos_invalidos(texto: str) -> list:
    """Lo escrito de cada código mal escrito del texto (no se sugiere cuál quiso poner)."""
    return [m.group(0).strip() for m in _RE_PARECE_CODIGO.finditer(texto or "")
            if m.group(1).upper() not in CODIGOS_VALIDOS]


def problemas_de_reparaciones(texto: str, tanque: str):
    """
    Mensaje para que el operario corrija las reparaciones, o None si se entienden.
    No se aceptan: códigos mal escritos, códigos de otro tanque, ni texto que no corresponda a
    ningún ítem conocido (hay que usar los códigos establecidos o nombrar la tapa, marco o revoque).
    """
    import html
    lineas = [f"\"{html.escape(escrito)}\" no es un código válido." for escrito in codigos_invalidos(texto)]
    otro_tanque = mensaje_codigos_de_otro_tanque(texto, tanque)
    if otro_tanque:
        lineas += [l[2:] for l in otro_tanque.splitlines() if l.startswith("• ")]
    if not lineas and set(detectar_items(texto)) == {"otras"}:
        corto = texto.strip() if len(texto.strip()) <= 60 else texto.strip()[:57] + "..."
        lineas.append(f"No entiendo a qué reparación te referís con \"{html.escape(corto)}\".")
    if not lineas:
        return None
    problemas = lineas[0] if len(lineas) == 1 else "\n".join(f"• {l}" for l in lineas)
    return (f"⚠️ {problemas}\n\n{AYUDA_CODIGOS}"
            f"\n\nEscribí de nuevo las reparaciones de {(tanque or '').capitalize()}.")


def etiqueta(grupo: str, cantidad: int = 1) -> str:
    base = ETIQUETAS.get(grupo, grupo)
    return f"{base} (x{cantidad})" if cantidad > 1 else base


def lista_para_operario(items: dict) -> str:
    """Viñetas de lo que tiene que fotografiar, para el mensaje del bot."""
    lineas = []
    for grupo, item in items.items():
        detalle = ""
        variantes = [VARIANTES[v] for v in item.get("variantes", []) if v in VARIANTES]
        if item["cantidad"] > 1 and len(set(variantes)) > 1:
            detalle = f": {' y '.join(dict.fromkeys(variantes))}, una foto de cada una"
        elif item["cantidad"] > 1:
            detalle = f": {item['cantidad']} distintas, una foto de cada una"
        lineas.append(f"• {etiqueta(grupo)}{detalle}")
    return "\n".join(lineas)
