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
    has_out_of_context, has_liters_without_material,
)
from bot.services.admin_code_service import validate_code

logger = logging.getLogger(__name__)

VOICE_WAITING      = "voice_waiting"
VOICE_CONFIRM      = "voice_confirm"
VOICE_REPROMPT     = "voice_reprompt"
VOICE_ASK_ALT      = "voice_ask_alt"
VOICE_ALT_REPROMPT = "voice_alt_reprompt"
VOICE_OOC          = "voice_out_of_context"      # fuera de contexto
VOICE_ADMIN_CODE   = "voice_admin_code"          # esperando código de admin
VOICE_LITROS       = "voice_litros_sin_material" # esperando tipo de material


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

    # Verificar litros sin material antes del resumen
    litros_fields = has_liters_without_material(fields)
    if litros_fields:
        context.user_data["voice_litros_fields"] = litros_fields
        context.user_data["voice_litros_index"] = 0
        context.user_data["voice_flow_state"] = VOICE_LITROS
        return _ask_litros_material(update, context)

    summary = build_summary(fields, selected, alt1, alt2)

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

        # Validar TODOS los campos faltantes (tanque principal + alternativos mencionados)
        all_missing = get_missing_fields(fields, selected, alt1, alt2, only_main=False)

        if all_missing:
            context.user_data["voice_missing"] = all_missing
            context.user_data["voice_flow_state"] = VOICE_REPROMPT
            query.edit_message_text(
                apply_bold_keywords("✅ Confirmado. Completá los datos que faltaron."),
                parse_mode=ParseMode.HTML,
            )
            return _ask_all_missing(update, context)
        else:
            query.edit_message_text(apply_bold_keywords("✅ Datos completos."), parse_mode=ParseMode.HTML)
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
    """Respuesta a campos faltantes — también enruta admin code y alt reprompt."""
    voice_state = context.user_data.get("voice_flow_state")

    # Enrutamiento según estado
    if voice_state == VOICE_ADMIN_CODE:
        return handle_admin_code_response(update, context)
    if voice_state == VOICE_ALT_REPROMPT:
        return handle_alt_reprompt_response(update, context)
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

    # Verificar si hay campos fuera de contexto en la respuesta
    ooc = has_out_of_context(fields)
    ooc_attempt = context.user_data.get("voice_ooc_attempt", 1)
    if ooc:
        return _handle_out_of_context(update, context, ooc, ooc_attempt)

    still_missing = get_missing_fields(fields, selected, alt1, alt2, only_main=False)
    if still_missing:
        if update.message:
            update.message.reply_text("✅ Guardado lo que pude extraer.", parse_mode=ParseMode.HTML)
        context.user_data["voice_missing"] = still_missing
        return _ask_all_missing(update, context)
    else:
        if update.message:
            update.message.reply_text("✅ ¡Todo completo!", parse_mode=ParseMode.HTML)
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
# Litros sin material especificado
# =============================================================================
def _ask_litros_material(update: Update, context: CallbackContext) -> int:
    """Pregunta el tipo de material cuando el operario dijo litros sin aclararlo."""
    litros_fields = context.user_data.get("voice_litros_fields", [])
    idx = context.user_data.get("voice_litros_index", 0)

    if idx >= len(litros_fields):
        # Terminó de aclarar todos → continuar al resumen
        context.user_data.pop("voice_litros_fields", None)
        context.user_data.pop("voice_litros_index", None)
        return _show_summary(update, context)

    field = litros_fields[idx]
    fields = context.user_data.get("voice_fields", {})
    litros_val = fields.get(field, "").replace("LITROS_SIN_MATERIAL:", "")

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Plástico",           callback_data="mat_plastico"),
        InlineKeyboardButton("Cilíndrico",         callback_data="mat_cilindrico"),
        InlineKeyboardButton("Acero inoxidable",   callback_data="mat_acero"),
    ]])
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=apply_bold_keywords(
            f"Mencionaste un tanque de <b>{litros_val} litros</b>. ¿De qué material es?"
        ),
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )
    context.user_data["voice_current_litros_field"] = field
    return TANK_TYPE


def handle_litros_material(update: Update, context: CallbackContext) -> int:
    """Recibe la selección de material para tanques en litros."""
    query = update.callback_query
    query.answer()

    material_map = {
        "mat_plastico":   "plástico",
        "mat_cilindrico": "cilíndrico",
        "mat_acero":      "acero inoxidable",
    }
    material = material_map.get(query.data, "")
    if not material:
        return TANK_TYPE

    field = context.user_data.get("voice_current_litros_field", "")
    fields = context.user_data.get("voice_fields", {})
    litros_val = fields.get(field, "").replace("LITROS_SIN_MATERIAL:", "")
    fields[field] = f"{litros_val} lts ({material})"
    context.user_data["voice_fields"] = fields

    # Siguiente campo de litros si hay más
    idx = context.user_data.get("voice_litros_index", 0) + 1
    context.user_data["voice_litros_index"] = idx
    query.edit_message_text(
        apply_bold_keywords(f"✅ Guardado: {litros_val} lts ({material})"),
        parse_mode=ParseMode.HTML,
    )
    return _ask_litros_material(update, context)


def _show_summary(update: Update, context: CallbackContext) -> int:
    """Muestra el resumen después de resolver litros."""
    fields   = context.user_data.get("voice_fields", {})
    selected = context.user_data.get("selected_category", "CISTERNA")
    alt1     = context.user_data.get("alternative_1", "RESERVA")
    alt2     = context.user_data.get("alternative_2", "INTERMEDIARIO")

    summary = build_summary(fields, selected, alt1, alt2)

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
# Fuera de contexto → re-pregunta → código de admin
# =============================================================================
def _handle_out_of_context(update: Update, context: CallbackContext,
                            ooc_fields: list, attempt: int = 1) -> int:
    """Avisa al operario que hubo contenido fuera de contexto y re-pregunta."""
    selected = context.user_data.get("selected_category", "CISTERNA")
    alt1     = context.user_data.get("alternative_1", "RESERVA")
    alt2     = context.user_data.get("alternative_2", "INTERMEDIARIO")

    labels = []
    for f in ooc_fields:
        tank  = get_tank_for_field(f, selected, alt1, alt2)
        label = get_label_for_field(f, tank)
        labels.append(f"  • {label}")

    if attempt == 1:
        msg = (
            "⚠️ Algunos campos tienen información que no corresponde al trabajo. "
            "Por favor respondé de nuevo solo esos campos:\n\n" +
            "\n".join(labels)
        )
        context.user_data["voice_flow_state"] = VOICE_REPROMPT
        context.user_data["voice_missing"] = ooc_fields
        context.user_data["voice_ooc_attempt"] = 2
    else:
        # Segundo intento fallido → pedir código de admin
        msg = (
            "⛔ El contenido sigue siendo inválido.\n\n"
            "Si querés enviar el reporte igual, pedile el código de hoy al administrador "
            "e ingresalo acá (texto o nota de voz):"
        )
        context.user_data["voice_flow_state"] = VOICE_ADMIN_CODE
        context.user_data["voice_ooc_fields"] = ooc_fields

    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=apply_bold_keywords(msg),
        parse_mode=ParseMode.HTML,
    )
    return TANK_TYPE


def handle_admin_code_response(update: Update, context: CallbackContext) -> int:
    """Valida el código de administrador ingresado por el operario."""
    voice_state = context.user_data.get("voice_flow_state")
    if voice_state != VOICE_ADMIN_CODE:
        return TANK_TYPE

    # Obtener el código — texto o audio
    code_text = None
    if update.message and update.message.text:
        code_text = update.message.text.strip()
    elif update.message and (update.message.voice or update.message.audio):
        processing = context.bot.send_message(
            chat_id=update.effective_chat.id, text="⏳ Procesando..."
        )
        audio_bytes = download_voice(update, context)
        processing.delete()
        if audio_bytes:
            transcribed = transcribe_audio(audio_bytes)
            if transcribed:
                # Extraer solo números de la transcripción
                import re
                nums = re.findall(r'[0-9]+', transcribed)
                code_text = "".join(nums)[:4] if nums else None

    if not code_text:
        update.message.reply_text("❌ No pude leer el código. Intentá de nuevo.")
        return TANK_TYPE

    if validate_code(code_text):
        # Código correcto → limpiar campos fuera de contexto y continuar
        ooc_fields = context.user_data.get("voice_ooc_fields", [])
        fields = context.user_data.get("voice_fields", {})
        for f in ooc_fields:
            fields[f] = None  # los deja vacíos pero no bloquea
        context.user_data["voice_fields"] = fields
        context.user_data["voice_flow_state"] = VOICE_CONFIRM
        update.message.reply_text("✅ Código correcto. Continuando con el reporte.")
        context.user_data["voice_alts_pending"] = [
            context.user_data.get("alternative_1", "RESERVA"),
            context.user_data.get("alternative_2", "INTERMEDIARIO"),
        ]
        _save_voice_fields(context)
        return _go_to_contact(update, context)
    else:
        update.message.reply_text(
            "❌ Código incorrecto. Pedile el código de hoy al administrador e intentá de nuevo."
        )
        return TANK_TYPE


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
            "📎 Adjunte las fotos de <b>ORDEN DE TRABAJO, FICHA y TANQUES</b>.\n"
            "Cuando termine, escriba <b>Listo</b>."
        ),
        parse_mode=ParseMode.HTML,
    )
    context.user_data["current_state"] = PHOTOS
    return PHOTOS
