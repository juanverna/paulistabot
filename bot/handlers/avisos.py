import logging
from telegram import Update, ParseMode
from telegram.ext import CallbackContext, ConversationHandler

from bot.states import *
from bot.utils.helpers import apply_bold_keywords
from bot.handlers.common import push_state, back_handler, check_special_commands
from bot.services.email_service import send_email

logger = logging.getLogger(__name__)


def get_avisos_address(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data["avisos_address"] = text
    push_state(context, AVISOS_ADDRESS)
    update.message.reply_text(
        apply_bold_keywords("¿A qué hora empezaste el trabajo? (HH:MM)"),
        parse_mode=ParseMode.HTML,
    )
    context.user_data["current_state"] = START_TIME
    return START_TIME


def handle_avisos_photos(update: Update, context: CallbackContext) -> int:
    if update.message.text:
        txt = update.message.text.lower().replace("á", "a").strip()
        if txt == "atras":
            return back_handler(update, context)
        if txt == "listo":
            if not context.user_data.get("photos"):
                update.message.reply_text(
                    apply_bold_keywords("Debe cargar al menos una foto antes de escribir 'Listo'."),
                    parse_mode=ParseMode.HTML,
                )
                return PHOTOS
            send_email(context.user_data, update, context)
            return ConversationHandler.END
        update.message.reply_text(
            apply_bold_keywords("Por favor, envíe una foto o escriba 'Listo' para continuar."),
            parse_mode=ParseMode.HTML,
        )
        return PHOTOS

    if update.message.photo:
        photos = context.user_data.get("photos", [])
        photos.append(update.message.photo[-1].file_id)
        context.user_data["photos"] = photos
        update.message.reply_text(
            apply_bold_keywords("Foto recibida. Puede enviar más o escriba 'Listo' para continuar."),
            parse_mode=ParseMode.HTML,
        )
        return PHOTOS

    update.message.reply_text(
        apply_bold_keywords("Por favor, envíe una foto o escriba 'Listo' para continuar."),
        parse_mode=ParseMode.HTML,
    )
    return PHOTOS
