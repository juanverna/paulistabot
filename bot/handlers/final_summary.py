"""
final_summary.py
----------------
Muestra un resumen completo del formulario antes de enviarlo.
Permite editar cualquier campo antes de confirmar.
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.ext import CallbackContext, ConversationHandler

from bot.states import FINAL_SUMMARY, PHOTOS
from bot.utils.helpers import apply_bold_keywords
from bot.services.email_service import send_email
from bot.services.voice_service import transcribe_audio, download_voice

logger = logging.getLogger(__name__)

# Campos editables con su etiqueta legible
EDITABLE_FIELDS = {
    "start_time":            "Hora de inicio",
    "end_time":              "Hora de finalización",
    "measure_main":          "Medida {selected}",
    "tapas_inspeccion_main": "Tapas inspección {selected}",
    "tapas_acceso_main":     "Tapas acceso {selected}",
    "sealing_main":          "Sellado {selected}",
    "repairs":               "Reparaciones {selected}",
    "suggestions":           "Sugerencias {selected}",
    "measure_alt1":          "Medida {alt1}",
    "tapas_inspeccion_alt1": "Tapas inspección {alt1}",
    "tapas_acceso_alt1":     "Tapas acceso {alt1}",
    "sealing_alt1":          "Sellado {alt1}",
    "repair_alt1":           "Reparaciones {alt1}",
    "suggestions_alt1":      "Sugerencias {alt1}",
    "measure_alt2":          "Medida {alt2}",
    "tapas_inspeccion_alt2": "Tapas inspección {alt2}",
    "tapas_acceso_alt2":     "Tapas acceso {alt2}",
    "sealing_alt2":          "Sellado {alt2}",
    "repair_alt2":           "Reparaciones {alt2}",
    "suggestions_alt2":      "Sugerencias {alt2}",
    "contact":               "Contacto",
}


def _get_label(field: str, user_data: dict) -> str:
    selected = user_data.get("selected_category", "").capitalize()
    alt1     = user_data.get("alternative_1", "").capitalize()
    alt2     = user_data.get("alternative_2", "").capitalize()
    label = EDITABLE_FIELDS.get(field, field)
    return label.format(selected=selected, alt1=alt1, alt2=alt2)


def build_full_summary(user_data: dict) -> str:
    """Construye el resumen completo del formulario."""
    selected = user_data.get("selected_category", "").capitalize()
    alt1     = user_data.get("alternative_1", "").capitalize()
    alt2     = user_data.get("alternative_2", "").capitalize()

    lines = ["📋 *RESUMEN COMPLETO DEL REPORTE*\n"]

    # Datos generales
    lines.append("*Datos generales:*")
    if user_data.get("numero_evento"):
        lines.append(f"  • Orden: {user_data['numero_evento']}")
    if user_data.get("direccion_qr"):
        lines.append(f"  • Dirección: {user_data['direccion_qr']}")
    if user_data.get("start_time"):
        lines.append(f"  • Hora inicio: {user_data['start_time']}")
    if user_data.get("end_time"):
        lines.append(f"  • Hora fin: {user_data['end_time']}")
    if user_data.get("contact"):
        lines.append(f"  • Contacto: {user_data['contact']}")
    lines.append("")

    # Tanque principal
    def add_tank(name: str, suffix: str):
        fields = {
            f"measure_{suffix}":          "Medida",
            f"tapas_inspeccion_{suffix}":  "Tapas inspección",
            f"tapas_acceso_{suffix}":      "Tapas acceso",
            f"sealing_{suffix}":           "Sellado",
        }
        # Para main los keys son distintos
        if suffix == "main":
            fields = {
                "measure_main":          "Medida",
                "tapas_inspeccion_main": "Tapas inspección",
                "tapas_acceso_main":     "Tapas acceso",
                "sealing_main":          "Sellado",
                "repairs":               "Reparaciones",
                "suggestions":           "Sugerencias",
            }
        elif suffix == "alt1":
            fields = {
                "measure_alt1":          "Medida",
                "tapas_inspeccion_alt1": "Tapas inspección",
                "tapas_acceso_alt1":     "Tapas acceso",
                "sealing_alt1":          "Sellado",
                "repair_alt1":           "Reparaciones",
                "suggestions_alt1":      "Sugerencias",
            }
        elif suffix == "alt2":
            fields = {
                "measure_alt2":          "Medida",
                "tapas_inspeccion_alt2": "Tapas inspección",
                "tapas_acceso_alt2":     "Tapas acceso",
                "sealing_alt2":          "Sellado",
                "repair_alt2":           "Reparaciones",
                "suggestions_alt2":      "Sugerencias",
            }

        section = [(label, user_data[key]) for key, label in fields.items()
                   if user_data.get(key)]
        if section:
            lines.append(f"*{name}:*")
            for label, val in section:
                lines.append(f"  • {label}: {val}")
            lines.append("")

    add_tank(selected, "main")

    if any(user_data.get(k) for k in ["measure_alt1", "tapas_inspeccion_alt1",
                                        "tapas_acceso_alt1", "sealing_alt1"]):
        add_tank(alt1, "alt1")

    if any(user_data.get(k) for k in ["measure_alt2", "tapas_inspeccion_alt2",
                                        "tapas_acceso_alt2", "sealing_alt2"]):
        add_tank(alt2, "alt2")

    total_fotos = len(user_data.get("photos", []))
    lines.append(f"*Fotos adjuntas:* {total_fotos}")

    return "\n".join(lines)


def show_final_summary(update: Update, context: CallbackContext) -> int:
    """Muestra el resumen final con botones Enviar / Modificar."""
    summary = build_full_summary(context.user_data)

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Enviar reporte", callback_data="final_send"),
        InlineKeyboardButton("✏️ Modificar algo", callback_data="final_edit"),
    ]])

    chat_id = update.effective_chat.id
    context.bot.send_message(
        chat_id=chat_id,
        text=summary,
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN,
    )
    context.user_data["current_state"] = FINAL_SUMMARY
    return FINAL_SUMMARY


def handle_final_summary_callback(update: Update, context: CallbackContext) -> int:
    """Maneja los botones del resumen final."""
    query = update.callback_query
    query.answer()

    if query.data == "final_send":
        query.edit_message_text("✅ Enviando reporte...", parse_mode=ParseMode.HTML)
        send_email(context.user_data, update, context)
        return ConversationHandler.END

    if query.data == "final_edit":
        query.edit_message_text(
            apply_bold_keywords(
                "✏️ Decime qué campo querés cambiar y el nuevo valor.\n\n"
                "Podés escribirlo o mandarlo por nota de voz.\n"
                "Ejemplo: <i>\"cambiar sellado cisterna a burlete\"</i>\n"
                "Ejemplo: <i>\"hora de inicio 9:30\"</i>"
            ),
            parse_mode=ParseMode.HTML,
        )
        context.user_data["final_edit_mode"] = True
        return FINAL_SUMMARY

    return FINAL_SUMMARY


def handle_final_edit_response(update: Update, context: CallbackContext) -> int:
    """Recibe la corrección del operario y actualiza el campo correspondiente."""
    if not context.user_data.get("final_edit_mode"):
        return FINAL_SUMMARY

    # Obtener texto (escrito o audio)
    answer_text = None
    if update.message.text:
        answer_text = update.message.text.strip()
    elif update.message.voice or update.message.audio:
        processing = context.bot.send_message(
            chat_id=update.effective_chat.id, text="⏳ Procesando..."
        )
        audio_bytes = download_voice(update, context)
        processing.delete()
        if audio_bytes:
            answer_text = transcribe_audio(audio_bytes)

    if not answer_text:
        update.message.reply_text("❌ No pude procesar. Intentá de nuevo.")
        return FINAL_SUMMARY

    # Usar GPT para extraer qué campo cambiar y el nuevo valor
    updated = _extract_edit_from_text(answer_text, context.user_data)

    if not updated:
        update.message.reply_text(
            apply_bold_keywords(
                "❓ No entendí qué campo querés cambiar. Intentá ser más específico.\n"
                "Ejemplo: <i>\"cambiar sellado cisterna a masilla\"</i>"
            ),
            parse_mode=ParseMode.HTML,
        )
        return FINAL_SUMMARY

    # Aplicar cambios
    for key, value in updated.items():
        context.user_data[key] = value
        logger.info("Campo editado: %s = %s", key, value)

    context.user_data["final_edit_mode"] = False
    update.message.reply_text("✅ Actualizado.", parse_mode=ParseMode.HTML)

    # Mostrar resumen actualizado
    return show_final_summary(update, context)


def _extract_edit_from_text(text: str, user_data: dict) -> dict:
    """Usa GPT para extraer qué campo cambiar y el nuevo valor."""
    import os, json
    from openai import OpenAI

    selected = user_data.get("selected_category", "CISTERNA").lower()
    alt1     = user_data.get("alternative_1", "RESERVA").lower()
    alt2     = user_data.get("alternative_2", "INTERMEDIARIO").lower()

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    prompt = f"""
Sos un asistente que procesa correcciones de operarios de limpieza de tanques.
El operario quiere cambiar un campo del reporte.

Campos disponibles y sus claves:
- start_time: hora de inicio (formato HH:MM)
- end_time: hora de finalización (formato HH:MM)
- measure_main: medida del tanque {selected}
- tapas_inspeccion_main: tapas inspección {selected}
- tapas_acceso_main: tapas acceso {selected}
- sealing_main: sellado {selected}
- repairs: reparaciones {selected}
- suggestions: sugerencias {selected}
- measure_alt1: medida {alt1}
- tapas_inspeccion_alt1: tapas inspección {alt1}
- tapas_acceso_alt1: tapas acceso {alt1}
- sealing_alt1: sellado {alt1}
- repair_alt1: reparaciones {alt1}
- suggestions_alt1: sugerencias {alt1}
- measure_alt2: medida {alt2}
- tapas_inspeccion_alt2: tapas inspección {alt2}
- tapas_acceso_alt2: tapas acceso {alt2}
- sealing_alt2: sellado {alt2}
- repair_alt2: reparaciones {alt2}
- suggestions_alt2: sugerencias {alt2}
- contact: nombre y teléfono del encargado

Extraé qué campo quiere cambiar y el nuevo valor.
Devolvé SOLO un JSON con el formato: {{"clave": "nuevo_valor"}}
Si no podés identificar el campo, devolvé {{}}

Texto del operario: {text}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = response.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except Exception as e:
        logger.error("Error extrayendo edición: %s", e)
        return {}
