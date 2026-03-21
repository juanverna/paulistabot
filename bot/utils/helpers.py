import re

def apply_bold_keywords(text: str) -> str:
    """Pone en negrita HTML las palabras clave del negocio."""
    pattern = r"(?i)\b(CISTERNA|RESERVA|INTERMEDIARIO)\b"
    return re.sub(pattern, lambda m: f"<b>{m.group(0)}</b>", text)

def is_valid_time(text: str) -> bool:
    """Valida formato HH:MM en 24 hs (00:00 a 23:59)."""
    pattern = r"^([01]\d|2[0-3]):([0-5]\d)$"
    return bool(re.match(pattern, text.strip()))
