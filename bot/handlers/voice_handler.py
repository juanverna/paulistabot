"""
voice_handler.py
----------------
Maneja el flujo de nota de voz dentro de Limpieza y Reparación de Tanques.

Estados nuevos que usa:
  VOICE_WAITING   → esperando que el operario mande el audio
  VOICE_CONFIRM   → mostrando resumen, esperando confirmación
  VOICE_REPROMPT  → re-preguntando campos faltantes uno por uno
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.ext import CallbackContext, ConversationHandler

from bot.states import PHOTOS, CONTACT
from bot.utils.helpers import apply_bold_keywords
from bot.handlers.common import push_state, back_handler
from bot.services.voice_service import (
    transcribe_audio, extract_fields, build_summary,
    get_missing_fields, get_question_for_field, get_tank_for_field,
    download_voice,
)

logger = logging.getLogger(__name__)

# Estados locales del flujo de voz (se guardan en user_data, no en ConversationHandler)
VOICE_WAITING  = "voice_waiting"
VOICE_CONFIRM  = "voice_confirm"
VOICE_REPROMPT = "voice_reprompt"


# =============================================================================
# Punto de entrada — después de seleccionar tipo de tanque
# =============================================================================
def ask_input_method(update: Update, context: CallbackContext) -> int:
    """
    Muestra botones MANUAL / NOTA DE VOZ al operario.
    Llamar después de que el operario ingresó la dirección en el flujo de tanques.
    """
    from bot.states import TANK_TYPE
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✍️ MANUAL",      callback_data="input_manual"),
            InlineKeyboardButton("🎤 NOTA DE VOZ", callback_data="input_voice"),
        ]
    ])
    if update.message:
        update.message.reply_text(
            apply_bold_keywords(
                "¿Cómo querés completar el reporte del tanque?\n\n"
                "• <b>MANUAL</b>: el bot te va preguntando de a uno\n"
                "• <b>NOTA DE VOZ</b>: mandás un audio contando todo y la IA lo procesa"
            ),
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )
    else:
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=apply_bold_keywords(
                "¿Cómo querés completar el reporte del tanque?\n\n"
                "• <b>MANUAL</b>: el bot te va preguntando de a uno\n"
                "• <b>NOTA DE VOZ</b>: mandás un audio contando todo y la IA lo procesa"
            ),
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )
    # Guardamos en qué sub-estado estamos dentro del flujo de voz
    context.user_data["voice_flow_state"] = "choosing"
    from bot.states import TANK_TYPE
    return TANK_TYPE  # Reutilizamos el estado TANK_TYPE como "esperando elección"


# =============================================================================
# Callback: el operario eligió MANUAL o NOTA DE VOZ
# =============================================================================
def handle_input_method(update: Update, context: CallbackContext) -> int:
    """Callback handler para los botones MANUAL / NOTA DE VOZ."""
    from bot.states import MEASURE_MAIN, TANK_TYPE
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
        query.edit_message_text(
            apply_bold_keywords(
                f"🎤 Enviá una nota de voz contando todo sobre el trabajo:\n\n"
                f"• Medidas del tanque <b>{selected}</b> (alto, ancho, profundo)\n"
                f"• Tapas de inspección y acceso\n"
                f"• Cómo sellaste\n"
                f"• Reparaciones necesarias (si hay)\n"
                f"• Sugerencias para la próxima visita\n"
                f"• Si trabajaste con otros tanques (Reserva/Intermediario), mencionalo\n"
                f"• Nombre y teléfono del encargado\n\n"
                f"Tomá tu tiempo, podés hablar con naturalidad."
            ),
            parse_mode=ParseMode.HTML,
        )
        context.user_data["current_state"] = TANK_TYPE
        return TANK_TYPE


# =============================================================================
# Recibir el audio
# =============================================================================
def handle_voice_message(update: Update, context: CallbackContext) -> int:
    """Recibe el audio, transcribe, extrae campos y muestra resumen."""
    from bot.states import TANK_TYPE

    voice_state = context.user_data.get("voice_flow_state")
    if voice_state != VOICE_WAITING:
        return TANK_TYPE

    selected = context.user_data.get("selected_category", "CISTERNA")
    alt1     = context.user_data.get("alternative_1", "RESERVA")
    alt2     = context.user_data.get("alternative_2", "INTERMEDIARIO")

    # Indicador de procesamiento
    processing_msg = context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="⏳ Procesando tu nota de voz...",
    )

    # 1. Descargar audio
    audio_bytes = download_voice(update, context)
    if not audio_bytes:
        processing_msg.delete()
        update.message.reply_text(
            "❌ No pude descargar el audio. Por favor intentá de nuevo.",
            parse_mode=ParseMode.HTML,
        )
        return TANK_TYPE

    # 2. Transcribir
    transcript = transcribe_audio(audio_bytes)
    if not transcript:
        processing_msg.delete()
        update.message.reply_text(
            "❌ No pude transcribir el audio. Por favor intentá de nuevo o usá el modo MANUAL.",
            parse_mode=ParseMode.HTML,
        )
        return TANK_TYPE

    context.user_data["voice_transcript"] = transcript

    # 3. Extraer campos
    fields = extract_fields(transcript, selected, alt1, alt2)
    context.user_data["voice_fields"] = fields

    # 4. Mostrar resumen y pedir confirmación
    processing_msg.delete()
    summary = build_summary(fields, selected, alt1, alt2)
    missing = get_missing_fields(fields, selected, alt1, alt2)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirmar", callback_data="voice_confirm"),
            InlineKeyboardButton("🔄 Grabar de nuevo", callback_data="voice_retry"),
        ]
    ])

    if missing:
        missing_names = ", ".join(missing)
        summary += f"\n\n⚠️ Faltan algunos datos: te voy a preguntar después de que confirmes."

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
    """El operario confirma el resumen o pide grabar de nuevo."""
    from bot.states import TANK_TYPE
    query = update.callback_query
    query.answer()

    if query.data == "voice_retry":
        context.user_data["voice_flow_state"] = VOICE_WAITING
        context.user_data.pop("voice_fields", None)
        selected = context.user_data.get("selected_category", "").capitalize()
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
            # Guardar lista de pendientes y arrancar re-preguntas
            context.user_data["voice_missing"] = missing
            context.user_data["voice_flow_state"] = VOICE_REPROMPT
            query.edit_message_text(
                apply_bold_keywords("✅ Confirmado. Ahora te voy a preguntar los datos que faltaron."),
                parse_mode=ParseMode.HTML,
            )
            return _ask_next_missing(update, context)
        else:
            # Todo completo — guardar en user_data y continuar
            query.edit_message_text(
                apply_bold_keywords("✅ ¡Todo completo!"),
                parse_mode=ParseMode.HTML,
            )
            _save_voice_fields(context)
            return _go_to_photos(update, context)

    return TANK_TYPE


# =============================================================================
# Re-preguntar campos faltantes
# =============================================================================
def _ask_next_missing(update: Update, context: CallbackContext) -> int:
    """Pregunta el siguiente campo faltante."""
    from bot.states import TANK_TYPE
    missing  = context.user_data.get("voice_missing", [])
    selected = context.user_data.get("selected_category", "CISTERNA")
    alt1     = context.user_data.get("alternative_1", "RESERVA")
    alt2     = context.user_data.get("alternative_2", "INTERMEDIARIO")

    if not missing:
        _save_voice_fields(context)
        return _go_to_photos(update, context)

    next_field = missing[0]
    context.user_data["voice_current_missing"] = next_field
    tank_name = get_tank_for_field(next_field, selected, alt1, alt2)
    question  = get_question_for_field(next_field, tank_name)

    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=apply_bold_keywords(f"❓ {question}\n\nPodés responder con texto o nota de voz."),
        parse_mode=ParseMode.HTML,
    )
    return TANK_TYPE


def handle_reprompt_response(update: Update, context: CallbackContext) -> int:
    """Recibe la respuesta a una re-pregunta (texto o audio)."""
    from bot.states import TANK_TYPE

    voice_state = context.user_data.get("voice_flow_state")
    if voice_state != VOICE_REPROMPT:
        return TANK_TYPE

    current_field = context.user_data.get("voice_current_missing")
    if not current_field:
        return TANK_TYPE

    # Obtener respuesta: texto o audio
    answer = None
    if update.message.text:
        answer = update.message.text.strip()
    elif update.message.voice or update.message.audio:
        audio_bytes = download_voice(update, context)
        if audio_bytes:
            answer = transcribe_audio(audio_bytes)

    if not answer:
        update.message.reply_text(
            apply_bold_keywords("❌ No pude procesar tu respuesta. Por favor intentá de nuevo."),
            parse_mode=ParseMode.HTML,
        )
        return TANK_TYPE

    # Validar que la respuesta tenga sentido para el campo
    if not _is_valid_answer(current_field, answer):
        update.message.reply_text(
            apply_bold_keywords(
                f"⚠️ Esa respuesta no parece correcta para este campo.\n"
                f"Por favor revisá e intentá de nuevo."
            ),
            parse_mode=ParseMode.HTML,
        )
        return TANK_TYPE

    # Guardar respuesta
    fields = context.user_data.get("voice_fields", {})
    fields[current_field] = answer
    context.user_data["voice_fields"] = fields

    # Sacar de pendientes y seguir
    missing = context.user_data.get("voice_missing", [])
    missing.pop(0)
    context.user_data["voice_missing"] = missing

    update.message.reply_text("✅ Guardado.", parse_mode=ParseMode.HTML)
    return _ask_next_missing(update, context)


# =============================================================================
# Validación simple por tipo de campo
# =============================================================================
def _is_valid_answer(field_key: str, answer: str) -> bool:
    """Valida que la respuesta tenga sentido para el campo."""
    import re
    answer = answer.strip().lower()

    if field_key.startswith("medida_"):
        # Debe contener al menos 3 números
        numbers = re.findall(r'\d+[.,]?\d*', answer)
        return len(numbers) >= 3

    if field_key.startswith("tapas_inspeccion_"):
        # Debe contener al menos un número
        return bool(re.search(r'\d+', answer))

    if field_key.startswith("tapas_acceso_"):
        # Debe contener al menos un número
        return bool(re.search(r'\d+', answer))

    if field_key.startswith("sellado_"):
        # Debe ser texto con al menos 3 caracteres y no solo números
        return len(answer) >= 3 and not answer.isdigit()

    if field_key.startswith("sugerencias_"):
        return len(answer) >= 3

    if field_key == "contacto":
        # Debe tener texto y al menos un número (teléfono)
        return bool(re.search(r'\d+', answer)) and len(answer) >= 5

    # Reparaciones es opcional — cualquier respuesta es válida
    if field_key.startswith("reparaciones_"):
        return True

    return len(answer) >= 1


# =============================================================================
# Guardar campos de voz en user_data (formato compatible con email)
# =============================================================================
def _save_voice_fields(context: CallbackContext) -> None:
    """Mapea los campos extraídos por la IA al formato que usa send_email."""
    fields   = context.user_data.get("voice_fields", {})
    selected = context.user_data.get("selected_category", "CISTERNA").lower()
    alt1     = context.user_data.get("alternative_1", "RESERVA").lower()
    alt2     = context.user_data.get("alternative_2", "INTERMEDIARIO").lower()

    # Tanque principal
    _map_tank_fields(context, fields, selected, is_main=True)
    # Tanques alternativos (solo si tienen datos)
    _map_tank_fields(context, fields, alt1, is_main=False, alt_index=1)
    _map_tank_fields(context, fields, alt2, is_main=False, alt_index=2)

    # Contacto
    if fields.get("contacto"):
        context.user_data["contact"] = fields["contacto"]

    # Limpiar datos temporales de voz
    for key in ["voice_fields", "voice_missing", "voice_current_missing",
                "voice_flow_state", "voice_transcript"]:
        context.user_data.pop(key, None)


def _map_tank_fields(context, fields, tank, is_main=True, alt_index=None):
    t = tank.lower()
    has_data = any(fields.get(f"{k}_{t}") for k in
                   ["medida", "tapas_inspeccion", "tapas_acceso", "sellado", "sugerencias"])
    if not has_data and not is_main:
        return

    if is_main:
        context.user_data["measure_main"]          = fields.get(f"medida_{t}", "")
        context.user_data["tapas_inspeccion_main"] = fields.get(f"tapas_inspeccion_{t}", "")
        context.user_data["tapas_acceso_main"]     = fields.get(f"tapas_acceso_{t}", "")
        context.user_data["sealing_main"]          = fields.get(f"sellado_{t}", "")
        context.user_data["repairs"]               = fields.get(f"reparaciones_{t}", "")
        context.user_data["suggestions"]           = fields.get(f"sugerencias_{t}", "")
    elif alt_index == 1:
        context.user_data["measure_alt1"]          = fields.get(f"medida_{t}", "")
        context.user_data["tapas_inspeccion_alt1"] = fields.get(f"tapas_inspeccion_{t}", "")
        context.user_data["tapas_acceso_alt1"]     = fields.get(f"tapas_acceso_{t}", "")
        context.user_data["sealing_alt1"]          = fields.get(f"sellado_{t}", "")
        context.user_data["repair_alt1"]           = fields.get(f"reparaciones_{t}", "")
        context.user_data["suggestions_alt1"]      = fields.get(f"sugerencias_{t}", "")
    elif alt_index == 2:
        context.user_data["measure_alt2"]          = fields.get(f"medida_{t}", "")
        context.user_data["tapas_inspeccion_alt2"] = fields.get(f"tapas_inspeccion_{t}", "")
        context.user_data["tapas_acceso_alt2"]     = fields.get(f"tapas_acceso_{t}", "")
        context.user_data["sealing_alt2"]          = fields.get(f"sellado_{t}", "")
        context.user_data["repair_alt2"]           = fields.get(f"reparaciones_{t}", "")
        context.user_data["suggestions_alt2"]      = fields.get(f"sugerencias_{t}", "")


# =============================================================================
# Ir a fotos
# =============================================================================
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
