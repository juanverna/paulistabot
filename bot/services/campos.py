"""
campos.py
---------
Formato estándar de los datos que el operario carga a mano, para que la calculadora y el
informe reciban siempre lo mismo:

- Medida: metros con 2 decimales, "alto, ancho, profundo" -> "1.80, 2.00, 1.50" (igual que la
  nota de voz). Varios tanques: "2 tanques: 1.80, ..." o "Tanque 1: ... | Tanque 2: ...".
  En litros: "2000 lts (plástico)".
- Tapas: códigos del CSV de artículos + medida -> "TITCEA 60, TATCC 56.5", o "No tiene".
- Sellado: "Masilla", "Masilla y burlete", "No tiene"...
- Teléfono: 10 dígitos con código de área, sin espacios -> "1135456067".
"""

import re

LETRA_TANQUE = {"CISTERNA": "C", "RESERVA": "R", "INTERMEDIARIO": "H"}
PREFIJO_TAPA = {"insp": "TIT", "acceso": "TAT"}
VARIANTES = {"EA": "entrada de agua", "C": "ciego"}

# Medidas que aparecen en el CSV de artículos y en la pregunta que se usaba antes
MEDIDAS_TAPA = {
    "insp":   ["30", "40", "50", "60", "80"],
    "acceso": ["47", "48", "49", "49.5", "50", "51.5", "52", "53.5", "54", "56",
               "56.5", "58", "60", "62", "65", "4789", "50125"],
}

SELLADOS = {"masilla": "Masilla", "burlete": "Burlete", "silicona": "Silicona"}
NO_TIENE = "No tiene"

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


def codigo_tapa(campo: str, tanque: str, variante: str, medida: str) -> str:
    """('insp', 'CISTERNA', 'EA', '60') -> 'TITCEA 60'."""
    return f"{PREFIJO_TAPA[campo]}{LETRA_TANQUE[tanque.upper()]}{variante} {medida}"


def medida_tapa_escrita(texto: str):
    """Medida de tapa escrita a mano ('51,5' -> '51.5'), o None si no es un número."""
    t = (texto or "").strip().lower().replace("cm", "").strip().replace(",", ".")
    return t if re.fullmatch(r"\d{2,5}(?:\.\d)?", t) else None


def texto_sellado(elegidos: list, otro: str = "") -> str:
    """['masilla', 'burlete'] -> 'Masilla y burlete'."""
    partes = [SELLADOS[e] for e in SELLADOS if e in elegidos]
    if otro:
        partes.append(otro.strip())
    if not partes:
        return NO_TIENE
    partes = [partes[0]] + [p[0].lower() + p[1:] for p in partes[1:]]
    return partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " y " + partes[-1]


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
