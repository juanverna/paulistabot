import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.ext import CallbackContext, ConversationHandler

from bot.states import *
from bot.utils.helpers import apply_bold_keywords
from bot.handlers.common import (push_state, back_handler, check_special_commands, terminar_edicion,
                                 teclado_atras)
from bot.services.email_service import send_email
from bot.handlers.fotos_reparaciones import necesita_fotos, pedir_fotos
from bot.handlers.campos_tanque import preguntar_medida, preguntar_contacto

logger = logging.getLogger(__name__)


# =============================================================================
# Tipo de tanque
# =============================================================================
def handle_tank_type(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    if query.data.lower() == "back":
        query.answer()
        return back_handler(update, context)
    if query.data not in ("CISTERNA", "RESERVA", "INTERMEDIARIO"):
        query.answer("Ese paso ya terminó.")
        return TANK_TYPE
    query.answer()

    push_state(context, TANK_TYPE)
    selected     = query.data
    alternatives = [x for x in ["CISTERNA", "RESERVA", "INTERMEDIARIO"] if x != selected]
    context.user_data.update({
        "selected_category": selected,
        "alternative_1":     alternatives[0],
        "alternative_2":     alternatives[1],
        "modo_ingreso":      "MANUAL",
    })
    query.edit_message_text(
        apply_bold_keywords(f"Tipo de tanque seleccionado: {selected.capitalize()}"),
        parse_mode=ParseMode.HTML,
    )
    # La hora ya se pidió antes (después del QR, o de la dirección en Presupuestos)
    return preguntar_medida(update, context, "main")


# =============================================================================
# Helper interno
# =============================================================================
def _text_step(update, context, save_key, current_state, next_state, next_question):
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        context.user_data.pop(save_key, None)
        return back_handler(update, context)
    context.user_data[save_key] = text
    push_state(context, current_state)
    update.message.reply_text(
        apply_bold_keywords(next_question),
        parse_mode=ParseMode.HTML,
    )
    context.user_data["current_state"] = next_state
    return next_state


# Las reparaciones de la carga manual se eligen con un menú (campos_tanque.boton_reparaciones).
# get_repair_* quedan para cargarlas como texto: los tests del paso de fotos las usan.
def _repair_step(update, context, save_key, current_state, sufijo, next_state, next_question):
    """Como _text_step, pero si hay reparaciones pide sus fotos antes de seguir."""
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        context.user_data.pop(save_key, None)
        return back_handler(update, context)
    if not necesita_fotos(text):
        context.user_data.get("fotos_reparaciones", {}).pop(sufijo, None)
        return _text_step(update, context, save_key, current_state, next_state, next_question)
    context.user_data[save_key] = text
    push_state(context, current_state)
    return pedir_fotos(update, context, sufijo, "manual")


# =============================================================================
# Tanque principal
# =============================================================================
def get_repair_main(update: Update, context: CallbackContext) -> int:
    selected = context.user_data.get("selected_category", "").capitalize()
    return _repair_step(update, context, "repairs", REPAIR_MAIN, "main",
                        SUGGESTIONS_MAIN,
                        f"Indique sugerencias p/ la próx limpieza para {selected}:")

def get_suggestions_main(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data["suggestions"] = text
    push_state(context, SUGGESTIONS_MAIN)
    fin = terminar_edicion(update, context)
    if fin is not None:
        return fin
    alt1 = context.user_data.get("alternative_1", "").capitalize()
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Si", callback_data="si"),
         InlineKeyboardButton("No", callback_data="no")],
        [InlineKeyboardButton("ATRAS", callback_data="back")],
    ])
    update.message.reply_text(
        apply_bold_keywords(f"¿Quiere comentar algo sobre {alt1}?"),
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )
    context.user_data["current_state"] = ASK_SECOND
    return ASK_SECOND


# =============================================================================
# Alternativa 1
# =============================================================================
def handle_ask_second(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    if query.data.lower() == "back":
        return back_handler(update, context)
    alt1 = context.user_data.get("alternative_1", "").capitalize()
    alt2 = context.user_data.get("alternative_2", "").capitalize()
    if query.data.lower() == "si":
        query.edit_message_text(apply_bold_keywords(f"¿Quiere comentar algo sobre {alt1}? Sí"),
                                parse_mode=ParseMode.HTML)
        return preguntar_medida(update, context, "alt1")
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Si", callback_data="si"),
             InlineKeyboardButton("No", callback_data="no")],
            [InlineKeyboardButton("ATRAS", callback_data="back")],
        ])
        query.edit_message_text(
            apply_bold_keywords(f"¿Quiere comentar algo sobre {alt2}?"),
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )
        context.user_data["current_state"] = ASK_THIRD
        return ASK_THIRD

def get_repair_alt1(update: Update, context: CallbackContext) -> int:
    alt1 = context.user_data.get("alternative_1", "").capitalize()
    return _repair_step(update, context, "repair_alt1", REPAIR_ALT1, "alt1",
                        SUGGESTIONS_ALT1,
                        f"Indique sugerencias p/ la próx limpieza para {alt1}:")

def get_suggestions_alt1(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data["suggestions_alt1"] = text
    push_state(context, SUGGESTIONS_ALT1)
    fin = terminar_edicion(update, context)
    if fin is not None:
        return fin
    alt2 = context.user_data.get("alternative_2", "").capitalize()
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Si", callback_data="si"),
         InlineKeyboardButton("No", callback_data="no")],
        [InlineKeyboardButton("ATRAS", callback_data="back")],
    ])
    update.message.reply_text(
        apply_bold_keywords(f"¿Quiere comentar algo sobre {alt2}?"),
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )
    context.user_data["current_state"] = ASK_THIRD
    return ASK_THIRD


# =============================================================================
# Alternativa 2
# =============================================================================
def handle_ask_third(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    if query.data.lower() == "back":
        return back_handler(update, context)
    alt2 = context.user_data.get("alternative_2", "").capitalize()
    if query.data.lower() == "si":
        query.edit_message_text(apply_bold_keywords(f"¿Quiere comentar algo sobre {alt2}? Sí"),
                                parse_mode=ParseMode.HTML)
        return preguntar_medida(update, context, "alt2")
    else:
        query.edit_message_text(apply_bold_keywords(f"¿Quiere comentar algo sobre {alt2}? No"),
                                parse_mode=ParseMode.HTML)
        return preguntar_contacto(update, context)

def get_repair_alt2(update: Update, context: CallbackContext) -> int:
    alt2 = context.user_data.get("alternative_2", "").capitalize()
    return _repair_step(update, context, "repair_alt2", REPAIR_ALT2, "alt2",
                        SUGGESTIONS_ALT2,
                        f"Indique sugerencias p/ la próx limpieza para {alt2}:")

def get_suggestions_alt2(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data["suggestions_alt2"] = text
    push_state(context, SUGGESTIONS_ALT2)
    fin = terminar_edicion(update, context)
    if fin is not None:
        return fin
    return preguntar_contacto(update, context)


# =============================================================================
# Fotos (Limpieza / Presupuestos) — mínimo 3, ilimitadas hasta "Listo"
# Acepta fotos comprimidas y archivos.
# =============================================================================
def handle_tank_photos(update: Update, context: CallbackContext) -> int:
    from bot.handlers.final_summary import show_final_summary
    from bot.states import FINAL_SUMMARY

    if update.message.text:
        txt = update.message.text.lower().replace("á", "a").strip()
        if txt == "atras":
            return back_handler(update, context)
        if txt == "listo":
            photos = context.user_data.get("photos", [])
            if len(photos) < 3:
                # Mínimo 3 fotos — no lo decimos explícitamente
                update.message.reply_text(
                    apply_bold_keywords("Agregá más fotos antes de finalizar."),
                    parse_mode=ParseMode.HTML,
                )
                return PHOTOS
            # Ir al resumen final
            return show_final_summary(update, context)
        update.message.reply_text(
            apply_bold_keywords("Por favor, envíe una foto o escriba <b>Listo</b> para finalizar."),
            parse_mode=ParseMode.HTML,
        )
        return PHOTOS

    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        photos = context.user_data.get("photos", [])
        photos.append(file_id)
        context.user_data["photos"] = photos
        update.message.reply_text(
            apply_bold_keywords(f"✅ Foto recibida (total: {len(photos)}). Enviá más o escribí <b>Listo</b>."),
            parse_mode=ParseMode.HTML,
        )
        return PHOTOS

    if update.message.document:
        file_id = update.message.document.file_id
        photos = context.user_data.get("photos", [])
        photos.append(file_id)
        context.user_data["photos"] = photos
        update.message.reply_text(
            apply_bold_keywords(f"✅ Archivo recibido (total: {len(photos)}). Enviá más o escribí <b>Listo</b>."),
            parse_mode=ParseMode.HTML,
        )
        return PHOTOS

    update.message.reply_text(
        apply_bold_keywords("Por favor, envíe una foto o escriba <b>Listo</b> para finalizar."),
        parse_mode=ParseMode.HTML,
    )
    return PHOTOS
