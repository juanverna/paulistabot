"""
voice_service.py
----------------
Maneja el flujo de nota de voz para Limpieza y Reparación de Tanques:
  1. Descarga el audio de Telegram
  2. Transcribe con Whisper
  3. Extrae y valida campos con GPT-4o
  4. Devuelve campos encontrados y faltantes
"""

import os
import json
import logging
import tempfile
from typing import Optional
from io import BytesIO

from openai import OpenAI
from telegram import Update
from telegram.ext import CallbackContext

logger = logging.getLogger(__name__)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# =============================================================================
# Prompt de extracción
# =============================================================================
def _build_extraction_prompt(selected: str, alt1: str, alt2: str) -> str:
    return f"""
Sos un asistente que procesa reportes de operarios de limpieza de tanques de agua en Argentina.
Los operarios hablan de manera coloquial — interpretá lo que dicen con sentido común.

Tanque principal: {selected}. Tanques alternativos: {alt1} y {alt2}.

Extraé la información y devolvé un JSON. Solo dejá null si realmente no se mencionó.
No inventes datos, pero interpretá con criterio cualquier forma de expresión coloquial.

Campos a extraer:
- hora_inicio: hora en que empezó el trabajo. Puede venir como "empecé a las 8", "arranqué 9 y media", etc.
  Formato de salida: "HH:MM"
- hora_fin: hora en que terminó el trabajo. Puede venir como "terminé a las 13", "salí a las 2 de la tarde", etc.
  Formato de salida: "HH:MM"
- medida_{selected.lower()}: medidas alto, ancho, profundo. Puede venir como "2 por 2 por 2",
  "uno cuarenta por dos por dos cincuenta", en palabras, con comas, como sea.
  Formato de salida: "X.XX, X.XX, X.XX"
- tapas_inspeccion_{selected.lower()}: medida/s de tapas de inspección
- tapas_acceso_{selected.lower()}: medida/s de tapas de acceso
- sellado_{selected.lower()}: material usado para sellar (masilla, burlete, silicona, etc.)
- reparaciones_{selected.lower()}: reparaciones a realizar (OPCIONAL — puede ser null)
- sugerencias_{selected.lower()}: sugerencias para la próxima limpieza

Si menciona {alt1}, extraé los mismos campos con sufijo _{alt1.lower()}.
Si menciona {alt2}, extraé los mismos campos con sufijo _{alt2.lower()}.

- contacto: nombre y teléfono del encargado

Devolvé SOLO el JSON, sin markdown ni explicaciones.

Texto del operario:
"""

# =============================================================================
# Prompt para re-extracción de múltiples campos faltantes
# =============================================================================
def _build_reprompt_extraction(missing_fields: list, selected: str, alt1: str, alt2: str) -> str:
    fields_str = "\n".join(f"- {f}" for f in missing_fields)
    return f"""
Sos un asistente que procesa respuestas de operarios de limpieza de tanques de agua en Argentina.

El operario está respondiendo a preguntas sobre campos faltantes de su reporte.
Los campos que debe completar son:
{fields_str}

REGLAS:
- Los operarios hablan coloquialmente. "Por" separa medidas: "2 por 2 por 2" = "2, 2, 2"
- Números en palabras son válidos: "dos" = 2, "cincuenta" = 50
- Extraé solo lo que realmente dijo. No inventes.
- Para campos de medida: formato "X.XX, X.XX, X.XX"
- Devolvé SOLO el JSON con los campos que pudiste extraer, null para los que no encontraste.
- Sin markdown, sin explicaciones.

Texto del operario:
"""

# =============================================================================
# Etiquetas legibles para cada campo
# =============================================================================
FIELD_LABELS = {
    "hora_inicio":      "Hora de inicio del trabajo (ej: 08:00)",
    "hora_fin":         "Hora de finalización del trabajo (ej: 13:00)",
    "medida":           "Medida (ALTO, ANCHO, PROFUNDO en metros, ej: 1.40, 2.40, 2.50)",
    "tapas_inspeccion": "Tapas de inspección (ej: 50, 30, 80)",
    "tapas_acceso":     "Tapas de acceso (ej: 54, 56)",
    "sellado":          "Sellado (ej: masilla, burlete, silicona)",
    "reparaciones":     "Reparaciones (si no hay, escribí 'ninguna')",
    "sugerencias":      "Sugerencias para la próxima limpieza",
    "contacto":         "Nombre y teléfono del encargado",
}

def get_label_for_field(field_key: str, tank_name: str) -> str:
    for key, label in FIELD_LABELS.items():
        if field_key.startswith(key):
            if field_key == "contacto":
                return label
            return f"{label} — tanque {tank_name.capitalize()}"
    return field_key

def get_tank_for_field(field_key: str, selected: str, alt1: str, alt2: str) -> str:
    if field_key.endswith(selected.lower()):
        return selected
    if field_key.endswith(alt1.lower()):
        return alt1
    if field_key.endswith(alt2.lower()):
        return alt2
    return selected

# =============================================================================
# Campos requeridos y opcionales
# =============================================================================
def get_required_fields(selected: str) -> list:
    s = selected.lower()
    return [
        "hora_inicio",
        "hora_fin",
        f"medida_{s}",
        f"tapas_inspeccion_{s}",
        f"tapas_acceso_{s}",
        f"sellado_{s}",
        f"sugerencias_{s}",
        "contacto",
    ]

# =============================================================================
# Transcripción con Whisper
# =============================================================================
def transcribe_audio(file_bytes: bytes) -> Optional[str]:
    try:
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        with open(tmp_path, "rb") as audio_file:
            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="es",
            )
        os.unlink(tmp_path)
        logger.info("Transcripción OK: %s", response.text[:100])
        return response.text
    except Exception as e:
        logger.error("Error transcribiendo audio: %s", e)
        return None

# =============================================================================
# Extracción de campos con GPT-4o
# =============================================================================
def extract_fields(transcript: str, selected: str, alt1: str, alt2: str) -> dict:
    prompt = _build_extraction_prompt(selected, alt1, alt2)
    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": transcript},
            ],
            temperature=0,
        )
        raw = response.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        fields = json.loads(raw)
        logger.info("Campos extraídos: %s", fields)
        return fields
    except Exception as e:
        logger.error("Error extrayendo campos: %s", e)
        return {}

def extract_missing_from_text(text: str, missing_fields: list,
                               selected: str, alt1: str, alt2: str) -> dict:
    """Extrae múltiples campos faltantes de una respuesta libre."""
    prompt = _build_reprompt_extraction(missing_fields, selected, alt1, alt2)
    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": text},
            ],
            temperature=0,
        )
        raw = response.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except Exception as e:
        logger.error("Error extrayendo campos faltantes: %s", e)
        return {}

# =============================================================================
# Construir resumen para mostrar al operario
# =============================================================================
def _clean_contact(raw: str) -> str:
    """Convierte JSON/dict de contacto a texto legible si viene mal formateado."""
    import re, json as _json
    if not raw:
        return raw
    # Si viene como dict string: {'nombre': 'Carlos', 'telefono': '11-35-45-60-67'}
    try:
        cleaned = raw.replace("'", '"')
        data = _json.loads(cleaned)
        if isinstance(data, dict):
            nombre = data.get("nombre", data.get("name", ""))
            tel = data.get("telefono", data.get("telefono", data.get("phone", data.get("tel", ""))))
            return f"{nombre} {tel}".strip()
    except Exception:
        pass
    return raw


def build_summary(fields: dict, selected: str, alt1: str, alt2: str) -> str:
    lines = ["📋 *Esto es lo que entendí de tu nota de voz:*\n"]

    # Horas al principio como bullets generales
    if fields.get("hora_inicio"):
        lines.append(f"  • Hora de inicio: {fields['hora_inicio']}")
    if fields.get("hora_fin"):
        lines.append(f"  • Hora de finalización: {fields['hora_fin']}")

    def add_tank_section(tank: str):
        t = tank.lower()
        field_map = {
            f"medida_{t}":            "Medida",
            f"tapas_inspeccion_{t}":  "Tapas inspección",
            f"tapas_acceso_{t}":      "Tapas acceso",
            f"sellado_{t}":           "Sellado",
            f"reparaciones_{t}":      "Reparaciones",
            f"sugerencias_{t}":       "Sugerencias",
        }
        section = [(label, fields[key]) for key, label in field_map.items() if fields.get(key)]
        if section:
            lines.append("")
            lines.append(f"*{tank.capitalize()}:*")
            for label, val in section:
                lines.append(f"  • {label}: {val}")

    add_tank_section(selected)
    add_tank_section(alt1)
    add_tank_section(alt2)

    # Contacto como bullet al final
    contacto_raw = fields.get("contacto")
    if contacto_raw:
        contacto = _clean_contact(str(contacto_raw))
        lines.append(f"  • Contacto: {contacto}")

    return "\n".join(lines)

# =============================================================================
# Determinar campos faltantes
# =============================================================================
def get_missing_fields(fields: dict, selected: str, alt1: str, alt2: str) -> list:
    missing = []

    for field in get_required_fields(selected):
        if not fields.get(field):
            missing.append(field)

    for alt in [alt1, alt2]:
        t = alt.lower()
        alt_keys = [f"medida_{t}", f"tapas_inspeccion_{t}", f"tapas_acceso_{t}",
                    f"sellado_{t}", f"sugerencias_{t}"]
        if any(fields.get(f) for f in alt_keys):
            for field in alt_keys:
                if not fields.get(field) and field not in missing:
                    missing.append(field)

    return missing

# =============================================================================
# Descargar audio de Telegram
# =============================================================================
def download_voice(update: Update, context: CallbackContext) -> Optional[bytes]:
    try:
        if update.message.voice:
            file_obj = context.bot.get_file(update.message.voice.file_id)
        elif update.message.audio:
            file_obj = context.bot.get_file(update.message.audio.file_id)
        else:
            return None
        bio = BytesIO()
        file_obj.download(out=bio)
        return bio.getvalue()
    except Exception as e:
        logger.error("Error descargando audio: %s", e)
        return None
