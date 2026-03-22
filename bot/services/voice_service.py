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
Sos un asistente que procesa reportes de operarios de limpieza de tanques de agua.
El operario seleccionó como tanque principal: {selected}.
Los otros tanques posibles son: {alt1} y {alt2}.

Tu tarea es extraer del texto los siguientes campos y devolver un JSON.

CAMPOS REQUERIDOS para el tanque {selected}:
- medida_{selected.lower()}: Tres números separados por coma representando ALTO, ANCHO y PROFUNDO en metros. Ejemplo válido: "1.40, 2.40, 2.50". Si no son tres números, dejarlo null.
- tapas_inspeccion_{selected.lower()}: Uno o más números que representen medidas de tapas de inspección. Ejemplo válido: "50" o "2 TI 30". Si no hay números, dejarlo null.
- tapas_acceso_{selected.lower()}: Uno o más números que representen medidas de tapas de acceso. Ejemplo válido: "54" o "2 TA 56". Si no hay números, dejarlo null.
- sellado_{selected.lower()}: Material usado para sellar. Ejemplos válidos: "masilla", "burlete", "silicona". Si no es un material concreto, dejarlo null.
- reparaciones_{selected.lower()}: Reparaciones a realizar. ESTE CAMPO ES OPCIONAL, puede quedar null si no se menciona.
- sugerencias_{selected.lower()}: Sugerencias para la próxima limpieza. Ejemplos: "desagotar con manga corta". Si no se menciona nada, dejarlo null.

CAMPOS OPCIONALES (solo si el operario los menciona):
- medida_{alt1.lower()}: igual que arriba pero para {alt1}
- tapas_inspeccion_{alt1.lower()}: igual
- tapas_acceso_{alt1.lower()}: igual
- sellado_{alt1.lower()}: igual
- reparaciones_{alt1.lower()}: igual (opcional)
- sugerencias_{alt1.lower()}: igual
- medida_{alt2.lower()}: igual que arriba pero para {alt2}
- tapas_inspeccion_{alt2.lower()}: igual
- tapas_acceso_{alt2.lower()}: igual
- sellado_{alt2.lower()}: igual
- reparaciones_{alt2.lower()}: igual (opcional)
- sugerencias_{alt2.lower()}: igual

CAMPO SIEMPRE REQUERIDO:
- contacto: Nombre y teléfono del encargado. Ejemplo: "Marcelo 1158472093". Si no se menciona, dejarlo null.

REGLAS IMPORTANTES:
- Solo extraé lo que el operario realmente dijo. No inventes datos.
- Si un valor no tiene sentido para el campo (ej: una palabra random donde debería haber una medida), dejalo null.
- Devolvé SOLO el JSON, sin texto adicional, sin markdown, sin explicaciones.

Texto del operario:
"""

# =============================================================================
# Campos requeridos y opcionales
# =============================================================================
def get_required_fields(selected: str) -> list:
    s = selected.lower()
    return [
        f"medida_{s}",
        f"tapas_inspeccion_{s}",
        f"tapas_acceso_{s}",
        f"sellado_{s}",
        f"sugerencias_{s}",
        "contacto",
    ]

def get_optional_fields(selected: str) -> list:
    s = selected.lower()
    return [f"reparaciones_{s}"]

FIELD_QUESTIONS = {
    "medida": "¿Cuál es la medida del tanque de {tank}? (ALTO, ANCHO, PROFUNDO en metros, ej: 1.40, 2.40, 2.50)",
    "tapas_inspeccion": "¿Cuál es la medida de las tapas de inspección de {tank}? (ej: 50, 30, 80)",
    "tapas_acceso": "¿Cuál es la medida de las tapas de acceso de {tank}? (ej: 54, 56)",
    "sellado": "¿Con qué selló el tanque de {tank}? (ej: masilla, burlete, silicona)",
    "reparaciones": "¿Hay reparaciones a realizar en {tank}? Si no hay ninguna, escribí 'ninguna'.",
    "sugerencias": "¿Qué sugerencias tenés para la próxima limpieza de {tank}? (ej: desagotar con manga corta)",
    "contacto": "¿Cuál es el nombre y teléfono del encargado?",
}

def get_question_for_field(field_key: str, tank_name: str) -> str:
    """Devuelve la pregunta correspondiente a un campo faltante."""
    for key, question in FIELD_QUESTIONS.items():
        if field_key.startswith(key):
            return question.format(tank=tank_name.capitalize())
    return f"¿Podés completar el campo '{field_key}'?"

def get_tank_for_field(field_key: str, selected: str, alt1: str, alt2: str) -> str:
    """Devuelve el nombre del tanque al que pertenece el campo."""
    if field_key.endswith(selected.lower()):
        return selected
    if field_key.endswith(alt1.lower()):
        return alt1
    if field_key.endswith(alt2.lower()):
        return alt2
    return selected

# =============================================================================
# Transcripción con Whisper
# =============================================================================
def transcribe_audio(file_bytes: bytes, filename: str = "audio.ogg") -> Optional[str]:
    """Transcribe audio usando Whisper."""
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
    """Extrae campos del texto transcripto usando GPT-4o."""
    prompt = _build_extraction_prompt(selected, alt1, alt2)
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": transcript},
            ],
            temperature=0,
        )
        raw = response.choices[0].message.content.strip()
        # Limpiar posibles markdown fences
        raw = raw.replace("```json", "").replace("```", "").strip()
        fields = json.loads(raw)
        logger.info("Campos extraídos: %s", fields)
        return fields
    except Exception as e:
        logger.error("Error extrayendo campos: %s", e)
        return {}

# =============================================================================
# Construir resumen para mostrar al operario
# =============================================================================
def build_summary(fields: dict, selected: str, alt1: str, alt2: str) -> str:
    lines = ["📋 *Esto es lo que entendí de tu nota de voz:*\n"]

    def add_tank_section(tank: str):
        t = tank.lower()
        section = []
        field_map = {
            f"medida_{t}":            "Medida",
            f"tapas_inspeccion_{t}":  "Tapas inspección",
            f"tapas_acceso_{t}":      "Tapas acceso",
            f"sellado_{t}":           "Sellado",
            f"reparaciones_{t}":      "Reparaciones",
            f"sugerencias_{t}":       "Sugerencias",
        }
        for key, label in field_map.items():
            val = fields.get(key)
            if val:
                section.append(f"  • {label}: {val}")
        if section:
            lines.append(f"*{tank.capitalize()}:*")
            lines.extend(section)
            lines.append("")

    add_tank_section(selected)
    add_tank_section(alt1)
    add_tank_section(alt2)

    contacto = fields.get("contacto")
    if contacto:
        lines.append(f"*Contacto:* {contacto}")

    return "\n".join(lines)

# =============================================================================
# Determinar campos faltantes
# =============================================================================
def get_missing_fields(fields: dict, selected: str, alt1: str, alt2: str) -> list:
    """
    Devuelve lista de campos faltantes.
    - Siempre verifica los campos requeridos del tanque principal.
    - Para alt1 y alt2: si se mencionó algún campo, verifica todos los requeridos de ese tanque.
    """
    missing = []

    # Tanque principal — siempre requerido
    for field in get_required_fields(selected):
        if not fields.get(field):
            missing.append(field)

    # Contacto
    if not fields.get("contacto"):
        if "contacto" not in missing:
            missing.append("contacto")

    # Tanques alternativos — solo si se mencionó algo de ese tanque
    for alt in [alt1, alt2]:
        t = alt.lower()
        alt_fields = [f"medida_{t}", f"tapas_inspeccion_{t}", f"tapas_acceso_{t}",
                      f"sellado_{t}", f"sugerencias_{t}"]
        mentioned = any(fields.get(f) for f in alt_fields)
        if mentioned:
            for field in alt_fields:
                if not fields.get(field) and field not in missing:
                    missing.append(field)

    return missing

# =============================================================================
# Descargar audio de Telegram
# =============================================================================
def download_voice(update: Update, context: CallbackContext) -> Optional[bytes]:
    """Descarga audio de voz o archivo de audio de Telegram."""
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
