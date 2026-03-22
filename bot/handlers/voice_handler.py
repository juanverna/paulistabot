"""
voice_handler.py
----------------
Maneja el flujo de nota de voz dentro de Limpieza y Reparación de Tanques.
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.ext import CallbackContext, ConversationHandler

from bot.states import PHOTOS, CONTACT, TANK_TYPE
from bot.utils.helpers import apply_bold_keywords
from bot.handlers.common import back_handler
from bot.services.voice_service import (
    transcribe_audio, extract_fields, extract_missing_from_text,
    build_summary, get_missing_fields, get_label_for_field,
    get_tank_for_field, download_voice,
)

logger = logging.getLogger(__name__)

VOICE_WAITING  = "voice_waiting"
VOICE_CONFIRM  = "voice_confirm"
VOICE_REPROMPT = "voice_reprompt"


# =============================================================================
# Callback: el operario eligió MANUAL o NOTA DE VOZ
# =============================================================================
def handle_input_method(update: Update, context: CallbackContext) -> int:
    from bot.states import MEASURE_MAIN
    query = update.callback_query
    query.answer()

    if query.data == "input_manual":
        context.user_data.pop("voice_flow_state", None)
        selected = context.user_data.get("selected_category", "").capitalize()
        query.edit_message_text(
            apply_bold_keywords(
                f"Indique la medida del tanque de {selected} (ALTO, ANCHO, PROFUNDO):"
            ),
            parse_mode=ParseMode.HTML,
        )
        context.user_data["current_state"] = MEASURE_MAIN
        return MEASURE_MAIN

    elif query.data == "input_voice":
        context.user_data["voice_flow_state"] = VOICE_WAITING
        selected = context.user_data.get("selected_category", "").capitalize()
        alt1 = context.user_data.get("alternative_1", "").capitalize()
        alt2 = context.user_data.get("alternative_2", "").capitalize()
        query.edit_message_text(
            apply_bold_keywords(
                f"🎤 Enviá una nota de voz contando todo sobre el trabajo.\n\n"
                f"Incluí:\n"
                f"• Medidas del tanque <b>{selected}</b> (alto, ancho, profundo)\n"
                f"• Tapas de inspección y acceso\n"
                f"• Cómo sellaste\n"
                f"• Reparaciones (si hay)\n"
                f"• Sugerencias para la próxima visita\n"
                f"• Si trabajaste también con <b>{alt1}</b> o <b>{alt2}</b>, mencionalo\n"
                f"• Nombre y teléfono del encargado\n\n"
                f"Hablá con naturalidad, la IA entiende."
            ),
            parse_mode=ParseMode.HTML,
        )
        context.user_data["current_state"] = TANK_TYPE
        return TANK_TYPE


# =============================================================================
# Recibir el audio principal
# =============================================================================
def handle_voice_message(update: Update, context: CallbackContext) -> int:
    voice_state = context.user_data.get("voice_flow_state")
    if voice_state != VOICE_WAITING:
        # Si está en re-pregunta, procesar como respuesta
        if voice_state == VOICE_REPROMPT:
            return handle_reprompt_response(update, context)
        return TANK_TYPE

    selected = context.user_data.get("selected_category", "CISTERNA")
    alt1     = context.user_data.get("alternative_1", "RESERVA")
    alt2     = context.user_data.get("alternative_2", "INTERMEDIARIO")

    processing_msg = context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="⏳ Procesando tu nota de voz...",
    )

    audio_bytes = download_voice(update, context)
    if not audio_bytes:
        processing_msg.delete()
        update.message.reply_text(
            "❌ No pude descargar el audio. Intentá de nuevo.",
            parse_mode=ParseMode.HTML,
        )
        return TANK_TYPE

    transcript = transcribe_audio(audio_bytes)
    if not transcript:
        processing_msg.delete()
        update.message.reply_text(
            "❌ No pude transcribir el audio. Intentá de nuevo o usá el modo MANUAL.",
            parse_mode=ParseMode.HTML,
        )
        return TANK_TYPE

    context.user_data["voice_transcript"] = transcript
    fields = extract_fields(transcript, selected, alt1, alt2)
    context.user_data["voice_fields"] = fields

    processing_msg.delete()

    summary = build_summary(fields, selected, alt1, alt2)
    missing = get_missing_fields(fields, selected, alt1, alt2)

    if missing:
        missing_list = _format_missing_list(missing, selected, alt1, alt2)
        summary += f"\n\n⚠️ *Datos faltantes:*\n{missing_list}"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirmar", callback_data="voice_confirm"),
            InlineKeyboardButton("🔄 Grabar de nuevo", callback_data="voice_retry"),
        ]
    ])

    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=summary,
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN,
    )

    context.user_data["voice_flow_state"] = VOICE_CONFIRM
    return TANK_TYPE


def _format_missing_list(missing: list, selected: str, alt1: str, alt2: str) -> str:
    """Formatea la lista de campos faltantes de forma legible."""
    lines = []
    for field in missing:
        tank = get_tank_for_field(field, selected, alt1, alt2)
        label = get_label_for_field(field, tank)
        lines.append(f"  • {label}")
    return "\n".join(lines)


# =============================================================================
# Confirmar o reintentar
# =============================================================================
def handle_voice_confirm(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()

    if query.data == "voice_retry":
        context.user_data["voice_flow_state"] = VOICE_WAITING
        context.user_data.pop("voice_fields", None)
        query.edit_message_text(
            apply_bold_keywords("🎤 Enviá una nueva nota de voz:"),
            parse_mode=ParseMode.HTML,
        )
        return TANK_TYPE

    if query.data == "voice_confirm":
        fields   = context.user_data.get("voice_fields", {})
        selected = context.user_data.get("selected_category", "CISTERNA")
        alt1     = context.user_data.get("alternative_1", "RESERVA")
        alt2     = context.user_data.get("alternative_2", "INTERMEDIARIO")
        missing  = get_missing_fields(fields, selected, alt1, alt2)

        if missing:
            context.user_data["voice_missing"] = missing
            context.user_data["voice_flow_state"] = VOICE_REPROMPT
            query.edit_message_text(
                apply_bold_keywords("✅ Confirmado. Ahora completá los datos que faltaron."),
                parse_mode=ParseMode.HTML,
            )
            return _ask_all_missing(update, context)
        else:
            query.edit_message_text(
                apply_bold_keywords("✅ ¡Todo completo!"),
                parse_mode=ParseMode.HTML,
            )
            _save_voice_fields(context)
            return _go_to_contact(update, context)

    return TANK_TYPE


# =============================================================================
# Re-preguntar TODOS los campos faltantes de una sola vez
# =============================================================================
def _ask_all_missing(update: Update, context: CallbackContext) -> int:
    """Muestra todos los campos faltantes en un solo mensaje."""
    missing  = context.user_data.get("voice_missing", [])
    selected = context.user_data.get("selected_category", "CISTERNA")
    alt1     = context.user_data.get("alternative_1", "RESERVA")
    alt2     = context.user_data.get("alternative_2", "INTERMEDIARIO")

    if not missing:
        _save_voice_fields(context)
        return _go_to_contact(update, context)

    lines = ["❓ *Faltan estos datos. Respondelos todos juntos en un mensaje o nota de voz:*\n"]
    for i, field in enumerate(missing, 1):
        tank  = get_tank_for_field(field, selected, alt1, alt2)
        label = get_label_for_field(field, tank)
        lines.append(f"{i}. {label}")

    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
    )
    return TANK_TYPE


def handle_reprompt_response(update: Update, context: CallbackContext) -> int:
    """Recibe la respuesta a los campos faltantes (texto o audio) y extrae todo de una."""
    voice_state = context.user_data.get("voice_flow_state")
    if voice_state != VOICE_REPROMPT:
        return TANK_TYPE

    missing  = context.user_data.get("voice_missing", [])
    selected = context.user_data.get("selected_category", "CISTERNA")
    alt1     = context.user_data.get("alternative_1", "RESERVA")
    alt2     = context.user_data.get("alternative_2", "INTERMEDIARIO")

    # Obtener texto de la respuesta
    answer_text = None
    if update.message.text:
        answer_text = update.message.text.strip()
    elif update.message.voice or update.message.audio:
        processing = context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⏳ Procesando tu respuesta...",
        )
        audio_bytes = download_voice(update, context)
        processing.delete()
        if audio_bytes:
            answer_text = transcribe_audio(audio_bytes)

    if not answer_text:
        update.message.reply_text(
            "❌ No pude procesar tu respuesta. Por favor intentá de nuevo.",
            parse_mode=ParseMode.HTML,
        )
        return TANK_TYPE

    # Extraer campos faltantes del texto
    extracted = extract_missing_from_text(answer_text, missing, selected, alt1, alt2)

    # Actualizar campos con lo que se encontró
    fields = context.user_data.get("voice_fields", {})
    for field in missing:
        if extracted.get(field):
            fields[field] = extracted[field]
    context.user_data["voice_fields"] = fields

    # Ver qué todavía falta
    still_missing = get_missing_fields(fields, selected, alt1, alt2)

    if still_missing:
        # Mostrar qué se guardó y qué todavía falta
        saved = [f for f in missing if f not in still_missing]
        if saved:
            update.message.reply_text("✅ Guardado lo que pude extraer.", parse_mode=ParseMode.HTML)

        context.user_data["voice_missing"] = still_missing
        return _ask_all_missing(update, context)
    else:
        update.message.reply_text("✅ ¡Todo completo!", parse_mode=ParseMode.HTML)
        _save_voice_fields(context)
        return _go_to_contact(update, context)


# =============================================================================
# Guardar campos en user_data (formato compatible con email)
# =============================================================================
def _save_voice_fields(context: CallbackContext) -> None:
    fields   = context.user_data.get("voice_fields", {})
    selected = context.user_data.get("selected_category", "CISTERNA").lower()
    alt1     = context.user_data.get("alternative_1", "RESERVA").lower()
    alt2     = context.user_data.get("alternative_2", "INTERMEDIARIO").lower()

    _map_tank(context, fields, selected, "main")
    _map_tank(context, fields, alt1, "alt1")
    _map_tank(context, fields, alt2, "alt2")

    if fields.get("contacto"):
        context.user_data["contact"] = fields["contacto"]

    for key in ["voice_fields", "voice_missing", "voice_flow_state", "voice_transcript"]:
        context.user_data.pop(key, None)


def _map_tank(context, fields, tank, suffix):
    t = tank.lower()
    has_data = any(fields.get(f"{k}_{t}") for k in
                   ["medida", "tapas_inspeccion", "tapas_acceso", "sellado", "sugerencias"])
    if not has_data and suffix != "main":
        return

    mapping = {
        "main": {
            "measure_main":          f"medida_{t}",
            "tapas_inspeccion_main": f"tapas_inspeccion_{t}",
            "tapas_acceso_main":     f"tapas_acceso_{t}",
            "sealing_main":          f"sellado_{t}",
            "repairs":               f"reparaciones_{t}",
            "suggestions":           f"sugerencias_{t}",
        },
        "alt1": {
            "measure_alt1":          f"medida_{t}",
            "tapas_inspeccion_alt1": f"tapas_inspeccion_{t}",
            "tapas_acceso_alt1":     f"tapas_acceso_{t}",
            "sealing_alt1":          f"sellado_{t}",
            "repair_alt1":           f"reparaciones_{t}",
            "suggestions_alt1":      f"sugerencias_{t}",
        },
        "alt2": {
            "measure_alt2":          f"medida_{t}",
            "tapas_inspeccion_alt2": f"tapas_inspeccion_{t}",
            "tapas_acceso_alt2":     f"tapas_acceso_{t}",
            "sealing_alt2":          f"sellado_{t}",
            "repair_alt2":           f"reparaciones_{t}",
            "suggestions_alt2":      f"sugerencias_{t}",
        },
    }
    for dest_key, src_key in mapping[suffix].items():
        context.user_data[dest_key] = fields.get(src_key, "")


# =============================================================================
# Ir a contacto (en modo voz el contacto lo guardó la IA, pero si faltó lo pide)
# =============================================================================
def _go_to_contact(update: Update, context: CallbackContext) -> int:
    # Si el contacto ya fue extraído por la IA, ir directo a fotos
    if context.user_data.get("contact"):
        return _go_to_photos(update, context)

    # Si no, pedirlo
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=apply_bold_keywords("Ingrese el nombre y teléfono del encargado:"),
        parse_mode=ParseMode.HTML,
    )
    context.user_data["current_state"] = CONTACT
    return CONTACT


def _go_to_photos(update: Update, context: CallbackContext) -> int:
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=apply_bold_keywords(
            "📎 Adjunte fotos de ORDEN DE TRABAJO, FICHA y TANQUES.\n"
            "Envielas como <b>Archivo</b> para conservar la fecha original.\n"
            "Cuando termine, escriba <b>Listo</b>."
        ),
        parse_mode=ParseMode.HTML,
    )
    context.user_data["current_state"] = PHOTOS
    return PHOTOS
