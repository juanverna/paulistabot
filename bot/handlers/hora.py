"""
hora.py
-------
Selector de hora con botones (formato 24 hs), para que no haya confusión de AM/PM.

El operario toca la hora (00 a 23) y después los minutos (de 5 en 5). También puede
escribirla (ej: 14:30), como antes. Botones: "hora:<campo>:h:<HH>", "hora:<campo>:m:<HH>:<MM>"
y "hora:<campo>:volver"; campo es "inicio" o "fin".
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

PREGUNTAS = {
    "inicio": "🕒 ¿A qué hora empezaste el trabajo?",
    "fin":    "🕒 ¿A qué hora terminaste el trabajo?",
}
AYUDA = "Tocá la hora y después los minutos (formato 24 hs), o escribila (ej: 14:30)."
ETIQUETAS = {"inicio": "Hora de inicio", "fin": "Hora de finalización"}


def texto_pregunta(campo: str) -> str:
    return f"{PREGUNTAS[campo]}\n{AYUDA}"


def _filas(botones: list, por_fila: int) -> list:
    return [botones[i:i + por_fila] for i in range(0, len(botones), por_fila)]


def teclado_horas(campo: str, con_atras: bool = True) -> InlineKeyboardMarkup:
    botones = [InlineKeyboardButton(f"{h:02d}", callback_data=f"hora:{campo}:h:{h:02d}") for h in range(24)]
    filas = _filas(botones, 6)
    if con_atras:
        filas.append([InlineKeyboardButton("ATRAS", callback_data="back")])
    return InlineKeyboardMarkup(filas)


def teclado_minutos(campo: str, hora: str) -> InlineKeyboardMarkup:
    botones = [InlineKeyboardButton(f"{hora}:{m:02d}", callback_data=f"hora:{campo}:m:{hora}:{m:02d}")
               for m in range(0, 60, 5)]
    filas = _filas(botones, 4)
    filas.append([InlineKeyboardButton("← Cambiar la hora", callback_data=f"hora:{campo}:volver")])
    return InlineKeyboardMarkup(filas)


def leer_boton(data: str):
    """("inicio"|"fin", "h"|"m"|"volver", hora, minutos) o None si el botón no es válido."""
    partes = (data or "").split(":")
    if len(partes) < 3 or partes[0] != "hora" or partes[1] not in PREGUNTAS:
        return None
    campo, accion = partes[1], partes[2]
    if accion == "volver":
        return campo, "volver", None, None
    if accion == "h" and len(partes) == 4 and partes[3].isdigit() and int(partes[3]) < 24:
        return campo, "h", partes[3], None
    if accion == "m" and len(partes) == 5 and partes[3].isdigit() and partes[4].isdigit() \
            and int(partes[3]) < 24 and int(partes[4]) < 60:
        return campo, "m", partes[3], partes[4]
    return None
