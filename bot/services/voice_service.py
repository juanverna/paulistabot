"""
voice_service.py
----------------
Maneja el flujo de nota de voz para Limpieza y Reparación de Tanques.
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
# Prompt de extracción principal
# =============================================================================
def _build_extraction_prompt(selected: str, alt1: str, alt2: str) -> str:
    from bot.services.articles_service import get_articles_context
    articles = get_articles_context()

    return f"""
Sos un asistente que procesa reportes de operarios de limpieza de tanques de agua en Argentina.
Los operarios hablan de manera coloquial — interpretá lo que dicen con sentido común.
Este es un contexto de trabajo técnico de fontanería/plomería. Si el operario dice algo completamente fuera de ese contexto (insultos, texto aleatorio, cosas sin sentido), marcá el campo como "FUERA_DE_CONTEXTO" en vez de null.

Tanque principal: {selected}. Tanques alternativos: {alt1} y {alt2}.

REGLAS DE EXTRACCIÓN:

HORAS:
- Extraé hora de inicio y fin del servicio (son únicas para todo el trabajo, no por tanque)
- Convertí siempre a formato HH:MM en 24 horas
- Ejemplos: "empecé a las 8" → "08:00", "arranqué 9 y media" → "09:30", "terminé a las 2 de la tarde" → "14:00", "salí a las 13" → "13:00"

MEDIDAS:
- Convertí siempre a metros con decimales (2 cifras decimales)
- Si vienen en centímetros (números grandes como 150, 230, 180), convertí dividiendo por 100
- Ejemplos: "2 por 2 por 2" → "2.00, 2.00, 2.00" | "150 230 180" → "1.50, 2.30, 1.80" | "uno cuarenta por dos por dos cincuenta" → "1.40, 2.00, 2.50"
- Si menciona cantidad de tanques: "2 tanques de 1.80 1.80 1.80" → "2 tanques: 1.80, 1.80, 1.80"
- Si hay tanques con diferentes medidas: "uno de 1.80 1.80 1.80 y otro de 1.40 1.40 1.40" → "Tanque 1: 1.80, 1.80, 1.80 | Tanque 2: 1.40, 1.40, 1.40"
- Si menciona litros SIN aclarar material → devolvé el valor con prefijo "LITROS_SIN_MATERIAL:" (ej: "LITROS_SIN_MATERIAL:2000")
- Si menciona litros Y aclara material (plástico, cilíndrico, acero inoxidable) → aceptalo tal cual

CONOCIMIENTO TÉCNICO — USALO PARA RAZONAR:
Tenés conocimiento sobre tanques de agua en edificios de Argentina. Usalo para inferir datos cuando el contexto lo permite:
- Los tanques cilíndricos, de plástico o de acero inoxidable generalmente solo tienen tapa de inspección, no de acceso, y por ende no se sellan
- Si el operario dice "no tiene tapa de acceso" o "no tiene sellado" → esos campos son "No tiene" (válido, no faltante)
- Si no aclara si la tapa es de entrada de agua (EA) o ciego (C), asumí entrada de agua por ser la más común, salvo que el contexto indique lo contrario
- Si hay un solo tanque en el edificio y dice que tiene una sola tapa de inspección, es de entrada de agua
- Cualquier respuesta explícita como "no tiene", "ninguna", "no aplica" es válida y NO es un campo faltante

TAPAS DE INSPECCIÓN Y ACCESO — IMPORTANTE:
Tenés que asociar lo que dijo el operario con el código más parecido de esta lista de artículos:
{articles}

Reglas para asociar:
- Identificá el tipo de tapa (inspección o acceso), el tipo de tanque (cisterna, reserva, intermediario), si es entrada de agua (EA) o ciego (C), y el tamaño
- Si no aclara EA o ciego → asumí EA (entrada de agua)
- Devolvé el CÓDIGO del artículo más cercano, no la descripción
- Si menciona "EXA" o "entrada" → es entrada de agua. Si menciona "ciego" o "CC" → es ciego
- Si dice un tamaño que no existe exactamente, usá el más cercano
- Si no podés asociar con ningún código → devolvé lo que dijo textualmente
- Si dice "no tiene" → devolvé "No tiene" (es una respuesta válida)
- Ejemplos: "tapa de inspección de 30 entrada agua cisterna" → "TITCEA30" | "tapa acceso 49 reserva" → "TATREA" | "tmtcea 49" → "TMTCEA" | "ti 50 ciego reserva" → "TITRC50"

REPARACIONES:
- Igual que tapas: si mencionan códigos o descripciones de artículos, asocialos con el código correcto de la lista
- Es texto libre, aceptá cualquier descripción técnica del rubro
- Si no se puede asociar, dejalo como texto libre
- "No", "ninguna", "nada" son respuestas válidas

SELLADO:
- Texto libre corto: masilla, burlete, silicona, etc.
- "M" = masilla, "B" = burlete
- "No tiene", "no se selló", "no aplica" son respuestas válidas (tanques sin tapa de acceso no se sellan)
- Aceptá cualquier material de sellado

SUGERENCIAS:
- Texto libre completamente
- Aceptá cualquier descripción operativa

CONTACTO:
- Nombre y teléfono del encargado
- Devolvé como texto plano: "Nombre Teléfono"

CONTENIDO FUERA DE CONTEXTO:
- Si un campo contiene información que claramente no tiene nada que ver con limpieza de tanques, plomería, medidas, o trabajo técnico → marcalo como "FUERA_DE_CONTEXTO"
- No marques como FUERA_DE_CONTEXTO cosas técnicas aunque sean abreviadas o coloquiales

Campos a devolver en el JSON:
- hora_inicio, hora_fin
- medida_{selected.lower()}, tapas_inspeccion_{selected.lower()}, tapas_acceso_{selected.lower()}, sellado_{selected.lower()}, reparaciones_{selected.lower()}, sugerencias_{selected.lower()}
- Si menciona {alt1}: mismos campos con sufijo _{alt1.lower()}
- Si menciona {alt2}: mismos campos con sufijo _{alt2.lower()}
- contacto

Devolvé SOLO el JSON, sin markdown ni explicaciones.

Texto del operario:
"""


# =============================================================================
# Prompt para re-extracción de campos faltantes
# =============================================================================
def _build_reprompt_extraction(missing_fields: list, selected: str, alt1: str, alt2: str) -> str:
    from bot.services.articles_service import get_articles_context
    articles = get_articles_context()
    fields_str = "\n".join(f"- {f}" for f in missing_fields)
    return f"""
Sos un asistente que procesa respuestas de operarios de limpieza de tanques en Argentina.
Contexto técnico de fontanería/plomería.

Campos a completar:
{fields_str}

Lista de artículos para asociar tapas y reparaciones:
{articles}

REGLAS:
- Horas → siempre HH:MM en 24hs
- Medidas → siempre metros con decimales. Centímetros → dividir por 100
- Tapas y reparaciones → asociar con código de la lista si es posible
- Contenido sin sentido o fuera de contexto → "FUERA_DE_CONTEXTO"
- Devolvé SOLO el JSON, null para lo que no encontraste.

Texto del operario:
"""


# =============================================================================
# Etiquetas legibles
# =============================================================================
FIELD_LABELS = {
    "hora_inicio":      "Hora de inicio del trabajo (ej: 08:00)",
    "hora_fin":         "Hora de finalización del trabajo (ej: 13:00)",
    "medida":           "Medida del tanque (alto, ancho, profundo en metros)",
    "tapas_inspeccion": "Tapas de inspección",
    "tapas_acceso":     "Tapas de acceso",
    "sellado":          "Sellado (ej: masilla, burlete)",
    "reparaciones":     "Reparaciones a realizar",
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
# Campos requeridos
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

def get_required_alt_fields(tank: str) -> list:
    t = tank.lower()
    return [
        f"medida_{t}",
        f"tapas_inspeccion_{t}",
        f"tapas_acceso_{t}",
        f"sellado_{t}",
        f"sugerencias_{t}",
    ]


# =============================================================================
# Detectar campos con problemas
# =============================================================================
def has_out_of_context(fields: dict) -> list:
    """Devuelve lista de campos marcados como FUERA_DE_CONTEXTO."""
    return [k for k, v in fields.items() if v == "FUERA_DE_CONTEXTO"]

def has_liters_without_material(fields: dict) -> list:
    """Devuelve lista de campos con medidas en litros sin material especificado."""
    return [k for k, v in fields.items()
            if isinstance(v, str) and v.startswith("LITROS_SIN_MATERIAL:")]


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
# Extracción de campos con GPT-4.1-mini
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
# Construir resumen
# =============================================================================
def _clean_contact(raw: str) -> str:
    import re
    if not raw:
        return raw
    try:
        cleaned = raw.replace("'", '"')
        import json as _json
        data = _json.loads(cleaned)
        if isinstance(data, dict):
            nombre = data.get("nombre", data.get("name", ""))
            tel = data.get("telefono", data.get("phone", data.get("tel", "")))
            return f"{nombre} {tel}".strip()
    except Exception:
        pass
    return raw


def build_summary(fields: dict, selected: str, alt1: str, alt2: str) -> str:
    lines = ["📋 *Esto es lo que entendí de tu nota de voz:*\n"]

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
        section = [(label, fields[key]) for key, label in field_map.items()
                   if fields.get(key) and fields[key] not in ("FUERA_DE_CONTEXTO",)]
        if section:
            lines.append("")
            lines.append(f"*{tank.capitalize()}:*")
            for label, val in section:
                display = val
                if isinstance(val, str) and val.startswith("LITROS_SIN_MATERIAL:"):
                    display = f"⚠️ {val.replace('LITROS_SIN_MATERIAL:', '')} lts (falta aclarar material)"
                lines.append(f"  • {label}: {display}")

    add_tank_section(selected)
    add_tank_section(alt1)
    add_tank_section(alt2)

    contacto_raw = fields.get("contacto")
    if contacto_raw and contacto_raw != "FUERA_DE_CONTEXTO":
        contacto = _clean_contact(str(contacto_raw))
        lines.append(f"  • Contacto: {contacto}")

    return "\n".join(lines)


# =============================================================================
# Campos faltantes
# =============================================================================
def _is_missing(val) -> bool:
    """Determina si un valor de campo se considera faltante."""
    if not val:
        return True
    if val == "FUERA_DE_CONTEXTO":
        return True
    if isinstance(val, str) and val.startswith("LITROS_SIN_MATERIAL:"):
        return True
    # Respuestas explícitas válidas de "no tiene" no son faltantes
    val_lower = str(val).lower().strip()
    no_tiene = {"no tiene", "no aplica", "ninguna", "ninguno", "no", "nada", "no se selló",
                "no se sello", "no lo selle", "no lo selló", "sin sellado", "-", "."}
    if val_lower in no_tiene:
        return False  # es una respuesta válida
    return False


def get_missing_fields(fields: dict, selected: str, alt1: str, alt2: str,
                        only_main: bool = False) -> list:
    missing = []
    for field in get_required_fields(selected):
        val = fields.get(field)
        if not val or val == "FUERA_DE_CONTEXTO" or (isinstance(val, str) and val.startswith("LITROS_SIN_MATERIAL:")):
            missing.append(field)

    if only_main:
        return missing

    for alt in [alt1, alt2]:
        alt_keys = get_required_alt_fields(alt)
        if any(fields.get(f) for f in alt_keys):
            for field in alt_keys:
                val = fields.get(field)
                if not val or val == "FUERA_DE_CONTEXTO" or (isinstance(val, str) and val.startswith("LITROS_SIN_MATERIAL:")):
                    if field not in missing:
                        missing.append(field)

    return missing


# =============================================================================
# Descargar audio
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
