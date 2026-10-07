"""
campos.py
---------
Formato estándar de los datos que el operario carga a mano, para que la calculadora y el
informe reciban siempre lo mismo:

- Medida: metros con 2 decimales, "alto, ancho, profundo" -> "1.80, 2.00, 1.50" (igual que la
  nota de voz). Varios tanques: "2 tanques: 1.80, ..." o "Tanque 1: ... | Tanque 2: ...".
  En litros: "2000 lts (plástico)".
- Reparaciones: código del CSV de artículos + tipo y medida del catálogo, separadas por coma
  -> "TITCEA 60x60, TATCC 12 agujeros punta recortada 56.5, revoque frente y piso, flotante",
  o "No".
- Teléfono: 10 dígitos con código de área, sin espacios -> "1135456067".
"""

import re

LETRA_TANQUE = {"CISTERNA": "C", "RESERVA": "R", "INTERMEDIARIO": "H"}
VARIANTES = {"EA": "entrada de agua", "C": "ciego"}
SIN_REPARACIONES = "No"

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
    "tmt": ("Cambio de marco y tapa de acceso", "TMT", {
        "tm": ("", "", ["48x48", "49x49", "50x50", "52x52", "54x54", "60x60"]),
    }),
    "mat": ("Cambio de marco solo", "MAT", {
        "ma": ("", "", ["48", "49", "50", "52", "54", "60"]),
    }),
    "rev": ("Revoque", None, {}),
    "flo": ("Flotante", None, {}),
    "aut": ("Automático", None, {}),
}
# Caras del tanque para el revoque (extract_reports.py busca frente, lateral y piso)
CARAS_REVOQUE = {"frente": "frente", "lateral": "lateral", "piso": "piso"}


def reparacion(grupo: str, tanque: str = "", variante: str = "", tipo: str = "", medida: str = "",
               caras: list = None) -> str:
    """
    Texto estándar de una reparación del catálogo:
    ('tat', 'CISTERNA', 'EA', 'oct', '54x54') -> 'TATCEA octogonal con parantes 54x54'
    ('rev', caras=['frente', 'piso'])          -> 'revoque frente y piso'
    ('flo',)                                   -> 'flotante'
    """
    boton, prefijo, tipos = CATALOGO_REPARACIONES[grupo]
    if prefijo is None:
        texto = boton.lower()
        if grupo == "rev" and caras:
            nombres = [CARAS_REVOQUE[c] for c in CARAS_REVOQUE if c in caras]
            texto += " " + (nombres[0] if len(nombres) == 1 else ", ".join(nombres[:-1]) + " y " + nombres[-1])
        return texto
    descripcion = tipos[tipo][1]
    return f"{prefijo}{LETRA_TANQUE[tanque.upper()]}{variante} {descripcion} {medida}".replace("  ", " ")


MATERIALES = {"plastico": "plástico", "cilindrico": "cilíndrico", "acero": "acero inoxidable"}

AYUDA_MEDIDA = ("Escribí las 3 medidas: alto, ancho y profundo, en metros o en centímetros.\n"
                "Ej: 1.80 2 1.50  o  180 200 150.\n"
                "Si son varios tanques iguales: 2 tanques 1.80 1.80 1.80.\n"
                "Si es de plástico o cilíndrico: 1000 litros.")

_NUMERO = re.compile(r"\d+(?:[.,]\d+)?")
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


def nombre_valido(nombre: str) -> bool:
    return bool(re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{2,}", nombre or "")) and len(nombre) <= 60
