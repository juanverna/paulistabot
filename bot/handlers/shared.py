import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.ext import CallbackContext, ConversationHandler

from bot.states import *
from bot.utils.helpers import apply_bold_keywords, is_valid_time
from bot.handlers.common import push_state, back_handler, check_special_commands

logger = logging.getLogger(__name__)


def get_code(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    if not text.isdigit():
        update.message.reply_text(
            apply_bold_keywords("El código debe ser numérico. Intentá de nuevo:"),
            parse_mode=ParseMode.HTML,
        )
        return CODE
    context.user_data["code"] = text
    push_state(context, CODE)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Fumigaciones",                     callback_data="Fumigaciones"),
         InlineKeyboardButton("Limpieza y Reparacion de Tanques", callback_data="Limpieza y Reparacion de Tanques")],
        [InlineKeyboardButton("Presupuestos", callback_data="Presupuestos"),
         InlineKeyboardButton("Avisos",        callback_data="Avisos")],
        [InlineKeyboardButton("ATRAS",         callback_data="back")],
    ])
    update.message.reply_text(
        apply_bold_keywords("¿Qué servicio se realizó?"),
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )
    context.user_data["current_state"] = SERVICE
    return SERVICE


def service_selection(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    if query.data.lower() == "back":
        return back_handler(update, context)

    push_state(context, SERVICE)
    service = query.data
    context.user_data["service"] = service
    query.edit_message_text(
        apply_bold_keywords(f"Servicio seleccionado: {service}"),
        parse_mode=ParseMode.HTML,
    )
    chat_id = query.message.chat.id

    if service == "Fumigaciones":
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords("📷 Por favor, envíe la foto del código QR:"),
            parse_mode=ParseMode.HTML,
        )
        context.user_data["current_state"] = SCAN_QR
        return SCAN_QR

    elif service == "Limpieza y Reparacion de Tanques":
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords("📷 Por favor, envíe la foto del código QR de la orden:"),
            parse_mode=ParseMode.HTML,
        )
        context.user_data["current_state"] = SCAN_QR
        return SCAN_QR

    elif service == "Presupuestos":
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords("Ingrese la dirección:"),
            parse_mode=ParseMode.HTML,
        )
        context.user_data["current_state"] = ADDRESS
        return ADDRESS

    elif service == "Avisos":
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords("Indique dirección/es donde se entregaron avisos:"),
            parse_mode=ParseMode.HTML,
        )
        context.user_data["current_state"] = AVISOS_ADDRESS
        return AVISOS_ADDRESS


def get_order(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    if not text.isdigit() or len(text) != 7:
        update.message.reply_text(
            apply_bold_keywords("El número de orden debe ser numérico y tener 7 dígitos. Intentá de nuevo:"),
            parse_mode=ParseMode.HTML,
        )
        return ORDER
    context.user_data["order"] = text
    push_state(context, ORDER)
    update.message.reply_text(
        apply_bold_keywords("Ingrese la dirección:"),
        parse_mode=ParseMode.HTML,
    )
    context.user_data["current_state"] = ADDRESS
    return ADDRESS


def get_address(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data["address"] = text
    push_state(context, ADDRESS)
    service = context.user_data.get("service")
    # Presupuestos → pide hora (no tiene QR ni nota de voz)
    if service == "Presupuestos":
        update.message.reply_text(
            apply_bold_keywords("¿A qué hora empezaste el trabajo? (HH:MM)"),
            parse_mode=ParseMode.HTML,
        )
        context.user_data["current_state"] = START_TIME
        return START_TIME
    # Otros → no debería llegar acá, pero por las dudas
    update.message.reply_text(
        apply_bold_keywords("¿A qué hora empezaste el trabajo? (HH:MM)"),
        parse_mode=ParseMode.HTML,
    )
    context.user_data["current_state"] = START_TIME
    return START_TIME


def get_start_time(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    if not is_valid_time(text):
        update.message.reply_text(
            apply_bold_keywords("Formato inválido. Usá HH:MM, por ejemplo 14:30."),
            parse_mode=ParseMode.HTML,
        )
        return START_TIME
    context.user_data["start_time"] = text.strip()
    push_state(context, START_TIME)
    update.message.reply_text(
        apply_bold_keywords("¿A qué hora terminaste el trabajo? (HH:MM)"),
        parse_mode=ParseMode.HTML,
    )
    context.user_data["current_state"] = END_TIME
    return END_TIME


def get_end_time(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    if not is_valid_time(text):
        update.message.reply_text(
            apply_bold_keywords("Formato inválido. Usá HH:MM, por ejemplo 14:30."),
            parse_mode=ParseMode.HTML,
        )
        return END_TIME
    context.user_data["end_time"] = text.strip()
    push_state(context, END_TIME)
    service = context.user_data.get("service")
    if service == "Fumigaciones":
        update.message.reply_text(
            apply_bold_keywords("¿Qué unidades contienen insectos?"),
            parse_mode=ParseMode.HTML,
        )
        context.user_data["current_state"] = FUMIGATION
        return FUMIGATION
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("CISTERNA",      callback_data="CISTERNA"),
             InlineKeyboardButton("RESERVA",       callback_data="RESERVA"),
             InlineKeyboardButton("INTERMEDIARIO", callback_data="INTERMEDIARIO")],
            [InlineKeyboardButton("ATRAS",         callback_data="back")],
        ])
        update.message.reply_text(
            apply_bold_keywords("Seleccione el tipo de tanque:"),
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )
        context.user_data["current_state"] = TANK_TYPE
        return TANK_TYPE


def get_contact(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data["contact"] = text
    push_state(context, CONTACT)
    service = context.user_data.get("service")
    if service == "Fumigaciones":
        update.message.reply_text(
            apply_bold_keywords("Adjunte fotos de ORDEN DE TRABAJO, LISTADO y PORTERO ELECTRICO:"),
            parse_mode=ParseMode.HTML,
        )
    elif service == "Avisos":
        update.message.reply_text(
            apply_bold_keywords(
                "Adjunte las fotos de los avisos junto a la chapa del edificio.\n"
                "Cuando termine, escriba 'Listo'."
            ),
            parse_mode=ParseMode.HTML,
        )
    else:
        update.message.reply_text(
            apply_bold_keywords(
                "📎 Adjunte fotos de ORDEN DE TRABAJO, FICHA y TANQUES.\n"
                "Envielas como <b>Archivo</b> para conservar la fecha original.\n"
                "Cuando termine, escriba 'Listo'."
            ),
            parse_mode=ParseMode.HTML,
        )
    context.user_data["current_state"] = PHOTOS
    return PHOTOS
