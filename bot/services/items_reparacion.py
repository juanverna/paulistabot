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
