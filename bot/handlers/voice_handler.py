"""
voice_handler.py
----------------
Maneja el flujo de nota de voz dentro de Limpieza y Reparación de Tanques.

Flujo:
1. Operario elige NOTA DE VOZ
2. Manda audio → Whisper transcribe → GPT extrae campos
3. Se muestra resumen + confirmación
4. Se completan campos faltantes del tanque principal
5. Para cada tanque alternativo:
   - Si tiene datos completos → skip
   - Si tiene datos incompletos → re-pregunta faltantes
   - Si no tiene nada → botonera "¿Querés comentar sobre X?" Sí/No
6. Contacto (si no lo extrajo la IA)
7. Fotos
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.ext import CallbackContext, ConversationHandler

from bot.states import PHOTOS, CONTACT, TANK_TYPE
from bot.utils.helpers import apply_bold_keywords
from bot.handlers.common import back_handler
from bot.services.voice_service import (
    transcribe_audio, extract_fields, extract_missing_from_text,
    build_summary, get_missing_fields, get_required_alt_fields,
    get_label_for_field, get_tank_for_field, download_voice, _clean_contact,
)

logger = logging.getLogger(__name__)

VOICE_WAITING     = "voice_waiting"
VOICE_CONFIRM     = "voice_confirm"
VOICE_REPROMPT    = "voice_reprompt"
VOICE_ASK_ALT     = "voice_ask_alt"
VOICE_ALT_REPROMPT = "voice_alt_reprompt"


# =============================================================================
# Callback: MANUAL o NOTA DE VOZ
# =============================================================================
def handle_input_method(update: Update, context: CallbackContext) -> int:
    from bot.states import MEASURE_MAIN
    query = update.callback_query
    query.answer()

    if query.data == "input_manual":
        context.user_data.pop("voice_flow_state", None)
        selected = context.user_data.get("selected_category", "").capitalize()
        query.edit_message_text(
            apply_bold_keywords(f"Indique la medida del tanque de {selected} (ALTO, ANCHO, PROFUNDO):"),
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
                f"• Hora de inicio y hora de finalización del servicio\n"
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
# Recibir audio principal
# =============================================================================
def handle_voice_message(update: Update, context: CallbackContext) -> int:
    voice_state = context.user_data.get("voice_flow_state")

    if voice_state == VOICE_REPROMPT:
        return handle_reprompt_response(update, context)
    if voice_state == VOICE_ALT_REPROMPT:
        return handle_alt_reprompt_response(update, context)
    if voice_state != VOICE_WAITING:
        return TANK_TYPE

    selected = context.user_data.get("selected_category", "CISTERNA")
    alt1     = context.user_data.get("alternative_1", "RESERVA")
    alt2     = context.user_data.get("alternative_2", "INTERMEDIARIO")

    processing_msg = context.bot.send_message(
        chat_id=update.effective_chat.id, text="⏳ Procesando tu nota de voz...",
    )

    audio_bytes = download_voice(update, context)
    if not audio_bytes:
        processing_msg.delete()
        update.message.reply_text("❌ No pude descargar el audio. Intentá de nuevo.")
        return TANK_TYPE

    transcript = transcribe_audio(audio_bytes)
    if not transcript:
        processing_msg.delete()
        update.message.reply_text("❌ No pude transcribir el audio. Intentá de nuevo o usá MANUAL.")
        return TANK_TYPE

    context.user_data["voice_transcript"] = transcript
    fields = extract_fields(transcript, selected, alt1, alt2)
    context.user_data["voice_fields"] = fields
    processing_msg.delete()

    summary = build_summary(fields, selected, alt1, alt2)
    missing_main = get_missing_fields(fields, selected, alt1, alt2, only_main=True)

    if missing_main:
        summary += f"\n\n⚠️ *Datos faltantes del tanque principal:*\n"
        summary += "\n".join(f"  • {get_label_for_field(f, selected)}" for f in missing_main)

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirmar", callback_data="voice_confirm"),
        InlineKeyboardButton("🔄 Grabar de nuevo", callback_data="voice_retry"),
    ]])

    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=summary,
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN,
    )
    context.user_data["voice_flow_state"] = VOICE_CONFIRM
    return TANK_TYPE


# =============================================================================
# Confirmar o reintentar
# =============================================================================
def handle_voice_confirm(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()

    if query.data == "voice_retry":
        context.user_data["voice_flow_state"] = VOICE_WAITING
        context.user_data.pop("voice_fields", None)
        query.edit_message_text(apply_bold_keywords("🎤 Enviá una nueva nota de voz:"), parse_mode=ParseMode.HTML)
        return TANK_TYPE

    if query.data == "voice_confirm":
        fields   = context.user_data.get("voice_fields", {})
        selected = context.user_data.get("selected_category", "CISTERNA")
        alt1     = context.user_data.get("alternative_1", "RESERVA")
        alt2     = context.user_data.get("alternative_2", "INTERMEDIARIO")

        missing_main = get_missing_fields(fields, selected, alt1, alt2, only_main=True)

        if missing_main:
            context.user_data["voice_missing"] = missing_main
            context.user_data["voice_flow_state"] = VOICE_REPROMPT
            query.edit_message_text(
                apply_bold_keywords("✅ Confirmado. Completá los datos que faltaron del tanque principal."),
                parse_mode=ParseMode.HTML,
            )
            return _ask_all_missing(update, context)
        else:
            query.edit_message_text(apply_bold_keywords("✅ Datos del tanque principal completos."), parse_mode=ParseMode.HTML)
            # Pasar a verificar tanques alternativos
            context.user_data["voice_alts_pending"] = [alt1, alt2]
            return _check_next_alt(update, context)

    # Respuesta a botonera de tanque alternativo
    if query.data == "voice_alt_si":
        alt = context.user_data.get("voice_current_alt", "")
        query.edit_message_text(
            apply_bold_keywords(f"🎤 Contame sobre el tanque <b>{alt.capitalize()}</b>. Podés mandar audio o escribir."),
            parse_mode=ParseMode.HTML,
        )
        context.user_data["voice_flow_state"] = VOICE_ALT_REPROMPT
        fields = context.user_data.get("voice_fields", {})
        alt_missing = get_required_alt_fields(alt)
        missing = [f for f in alt_missing if not fields.get(f)]
        context.user_data["voice_missing"] = missing
        return TANK_TYPE

    if query.data == "voice_alt_no":
        query.edit_message_text(
            apply_bold_keywords(f"OK, sin datos para {context.user_data.get('voice_current_alt','').capitalize()}."),
            parse_mode=ParseMode.HTML,
        )
        return _check_next_alt(update, context)

    return TANK_TYPE


# =============================================================================
# Campos faltantes del tanque principal
# =============================================================================
def _ask_all_missing(update: Update, context: CallbackContext) -> int:
    missing  = context.user_data.get("voice_missing", [])
    selected = context.user_data.get("selected_category", "CISTERNA")
    alt1     = context.user_data.get("alternative_1", "RESERVA")
    alt2     = context.user_data.get("alternative_2", "INTERMEDIARIO")

    if not missing:
        context.user_data["voice_alts_pending"] = [alt1, alt2]
        return _check_next_alt(update, context)

    lines = ["❓ *Faltan estos datos. Respondelos juntos en un mensaje o nota de voz:*\n"]
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
    """Respuesta a campos faltantes del tanque principal."""
    voice_state = context.user_data.get("voice_flow_state")
    if voice_state != VOICE_REPROMPT:
        return TANK_TYPE

    missing  = context.user_data.get("voice_missing", [])
    selected = context.user_data.get("selected_category", "CISTERNA")
    alt1     = context.user_data.get("alternative_1", "RESERVA")
    alt2     = context.user_data.get("alternative_2", "INTERMEDIARIO")

    answer_text = _get_answer_text(update, context)
    if not answer_text:
        return TANK_TYPE

    extracted = extract_missing_from_text(answer_text, missing, selected, alt1, alt2)
    fields = context.user_data.get("voice_fields", {})
    for field in missing:
        if extracted.get(field):
            fields[field] = extracted[field]
    context.user_data["voice_fields"] = fields

    still_missing = get_missing_fields(fields, selected, alt1, alt2, only_main=True)
    if still_missing:
        if update.message:
            update.message.reply_text("✅ Guardado lo que pude extraer.", parse_mode=ParseMode.HTML)
        context.user_data["voice_missing"] = still_missing
        return _ask_all_missing(update, context)
    else:
        if update.message:
            update.message.reply_text("✅ Tanque principal completo.", parse_mode=ParseMode.HTML)
        context.user_data["voice_alts_pending"] = [alt1, alt2]
        return _check_next_alt(update, context)


# =============================================================================
# Verificar tanques alternativos uno por uno
# =============================================================================
def _check_next_alt(update: Update, context: CallbackContext) -> int:
    """Revisa el próximo tanque alternativo pendiente."""
    pending = context.user_data.get("voice_alts_pending", [])
    fields  = context.user_data.get("voice_fields", {})

    while pending:
        alt = pending.pop(0)
        context.user_data["voice_alts_pending"] = pending
        alt_required = get_required_alt_fields(alt)
        has_any  = any(fields.get(f) for f in alt_required)
        missing  = [f for f in alt_required if not fields.get(f)]

        if has_any and missing:
            # Tiene datos pero incompletos → re-preguntar faltantes
            context.user_data["voice_current_alt"] = alt
            context.user_data["voice_missing"] = missing
            context.user_data["voice_flow_state"] = VOICE_ALT_REPROMPT
            lines = [f"❓ *Faltan datos del tanque {alt.capitalize()}. Respondelos juntos:*\n"]
            for i, field in enumerate(missing, 1):
                label = get_label_for_field(field, alt)
                lines.append(f"{i}. {label}")
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="\n".join(lines),
                parse_mode=ParseMode.MARKDOWN,
            )
            return TANK_TYPE

        elif not has_any:
            # No mencionó nada → botonera Sí/No
            context.user_data["voice_current_alt"] = alt
            context.user_data["voice_flow_state"] = VOICE_ASK_ALT
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Sí", callback_data="voice_alt_si"),
                InlineKeyboardButton("❌ No", callback_data="voice_alt_no"),
            ]])
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=apply_bold_keywords(f"¿Querés comentar algo sobre el tanque <b>{alt.capitalize()}</b>?"),
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
            )
            return TANK_TYPE
        # Si tiene datos completos → siguiente

    # Todos los tanques procesados
    _save_voice_fields(context)
    return _go_to_contact(update, context)


def handle_alt_reprompt_response(update: Update, context: CallbackContext) -> int:
    """Respuesta a campos faltantes de un tanque alternativo."""
    voice_state = context.user_data.get("voice_flow_state")
    if voice_state != VOICE_ALT_REPROMPT:
        return TANK_TYPE

    alt      = context.user_data.get("voice_current_alt", "")
    missing  = context.user_data.get("voice_missing", [])
    selected = context.user_data.get("selected_category", "CISTERNA")
    alt1     = context.user_data.get("alternative_1", "RESERVA")
    alt2     = context.user_data.get("alternative_2", "INTERMEDIARIO")

    answer_text = _get_answer_text(update, context)
    if not answer_text:
        return TANK_TYPE

    extracted = extract_missing_from_text(answer_text, missing, selected, alt1, alt2)
    fields = context.user_data.get("voice_fields", {})
    for field in missing:
        if extracted.get(field):
            fields[field] = extracted[field]
    context.user_data["voice_fields"] = fields

    still_missing = [f for f in get_required_alt_fields(alt) if not fields.get(f)]
    if still_missing:
        if update.message:
            update.message.reply_text("✅ Guardado lo que pude extraer.", parse_mode=ParseMode.HTML)
        context.user_data["voice_missing"] = still_missing
        lines = [f"❓ *Todavía faltan datos de {alt.capitalize()}:*\n"]
        for i, field in enumerate(still_missing, 1):
            lines.append(f"{i}. {get_label_for_field(field, alt)}")
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="\n".join(lines),
            parse_mode=ParseMode.MARKDOWN,
        )
        return TANK_TYPE
    else:
        if update.message:
            update.message.reply_text(f"✅ {alt.capitalize()} completo.", parse_mode=ParseMode.HTML)
        return _check_next_alt(update, context)


# =============================================================================
# Helpers
# =============================================================================
def _get_answer_text(update: Update, context: CallbackContext):
    """Obtiene texto de un mensaje o transcribe audio."""
    if update.message.text:
        return update.message.text.strip()
    elif update.message.voice or update.message.audio:
        processing = context.bot.send_message(
            chat_id=update.effective_chat.id, text="⏳ Procesando tu respuesta...",
        )
        audio_bytes = download_voice(update, context)
        processing.delete()
        if audio_bytes:
            return transcribe_audio(audio_bytes)
    if update.message:
        update.message.reply_text("❌ No pude procesar tu respuesta. Intentá de nuevo.")
    return None


# =============================================================================
# Guardar campos en user_data
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
        context.user_data["contact"] = _clean_contact(str(fields["contacto"]))
    if fields.get("hora_inicio"):
        context.user_data["start_time"] = fields["hora_inicio"]
    if fields.get("hora_fin"):
        context.user_data["end_time"] = fields["hora_fin"]

    for key in ["voice_fields", "voice_missing", "voice_flow_state", "voice_transcript",
                "voice_alts_pending", "voice_current_alt"]:
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
# Contacto y fotos
# =============================================================================
def _go_to_contact(update: Update, context: CallbackContext) -> int:
    if context.user_data.get("contact"):
        return _go_to_photos(update, context)
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
            "📎 Adjunte las fotos de <b>ORDEN DE TRABAJO, FICHA y TANQUES</b> como Archivo:\n\n"
            "1. Tocá el sujetapapeles 📎\n"
            "2. Seleccioná <b>Archivo</b>\n"
            "3. Elegí la foto desde tu galería\n\n"
            "Cuando termine, escriba <b>Listo</b>."
        ),
        parse_mode=ParseMode.HTML,
    )
    context.user_data["current_state"] = PHOTOS
    return PHOTOS
