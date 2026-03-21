import logging
from telegram import Update, ParseMode
from telegram.ext import CallbackContext, ConversationHandler

from bot.states import *
from bot.utils.helpers import apply_bold_keywords, is_valid_time
from bot.handlers.common import push_state, back_handler, check_special_commands
from bot.services.email_service import send_email

logger = logging.getLogger(__name__)


def fumigation_data(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data["fumigated_units"] = text
    push_state(context, FUMIGATION)
    update.message.reply_text(
        apply_bold_keywords("Marque las observaciones para la próxima visita:"),
        parse_mode=ParseMode.HTML,
    )
    context.user_data["current_state"] = FUM_OBS
    return FUM_OBS


def get_fum_obs(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data["fum_obs"] = text
    push_state(context, FUM_OBS)
    update.message.reply_text(
        apply_bold_keywords("Ingrese el nombre y teléfono del encargado:"),
        parse_mode=ParseMode.HTML,
    )
    context.user_data["current_state"] = CONTACT
    return CONTACT


def handle_fum_photos(update: Update, context: CallbackContext) -> int:
    """Fumigaciones requiere exactamente 3 fotos."""
    if update.message.text:
        txt = update.message.text.lower().replace("á", "a").strip()
        if txt == "atras":
            return back_handler(update, context)
        update.message.reply_text(
            apply_bold_keywords("Por favor, adjunte una imagen válida."),
            parse_mode=ParseMode.HTML,
        )
        return PHOTOS

    if not update.message.photo:
        update.message.reply_text(
            apply_bold_keywords("Por favor, adjunte una imagen válida."),
            parse_mode=ParseMode.HTML,
        )
        return PHOTOS

    photos = context.user_data.get("photos", [])
    photos.append(update.message.photo[-1].file_id)
    context.user_data["photos"] = photos

    if len(photos) < 3:
        update.message.reply_text(
            apply_bold_keywords(f"Foto recibida. Por favor cargue la foto número {len(photos) + 1}."),
            parse_mode=ParseMode.HTML,
        )
        return PHOTOS

    send_email(context.user_data, update, context)
    return ConversationHandler.END
