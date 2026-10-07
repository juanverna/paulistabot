"""
bot_atras.py
------------
Solo la última pregunta del chat tiene el botón ATRAS.

Cada pregunta llega con ⬅️ ATRAS, y el botón retrocede un paso desde donde está la conversación,
no desde la pregunta donde se tocó. Si las preguntas ya contestadas conservaran el botón, tocar
el ATRAS de una pregunta vieja llevaría a otra parte. Por eso, cuando el bot manda una pregunta
nueva con ATRAS, le saca los botones a la anterior (ya está contestada).

Se hace al mandar el mensaje (BotConAtrasUnico.send_message, que también usa reply_text), así
ningún paso tiene que acordarse de hacerlo.
"""

import logging
import threading

from telegram import InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import ExtBot

logger = logging.getLogger(__name__)

# chat_id -> message_id de la última pregunta con ATRAS
_ultima = {}
_lock = threading.Lock()


def tiene_atras(markup) -> bool:
    if not isinstance(markup, InlineKeyboardMarkup):
        return False
    return any(boton.callback_data == "back" for fila in markup.inline_keyboard for boton in fila)


def registrar(bot, chat_id: int, message_id: int) -> None:
    """Anota la pregunta nueva y le saca los botones a la anterior del mismo chat."""
    with _lock:
        anterior = _ultima.get(chat_id)
        _ultima[chat_id] = message_id
    if anterior is None or anterior == message_id:
        return
    try:
        bot.edit_message_reply_markup(chat_id=chat_id, message_id=anterior, reply_markup=None)
    except TelegramError:  # ya no tenía botones, o es muy viejo para editarlo: no importa
        pass


class BotConAtrasUnico(ExtBot):
    def send_message(self, *args, **kwargs):
        mensaje = super().send_message(*args, **kwargs)
        # reply_markup es el 7º argumento (chat_id, text, parse_mode, ..., reply_to_message_id)
        markup = kwargs.get("reply_markup", args[6] if len(args) > 6 else None)
        if mensaje is not None and tiene_atras(markup):
            registrar(self, mensaje.chat_id, mensaje.message_id)
        return mensaje
