import unittest
from unittest.mock import MagicMock, patch

from tests import entorno
entorno.preparar()

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import ExtBot

from bot.utils import bot_atras
from bot.handlers.common import teclado_atras


def _mensaje(chat_id: int, message_id: int) -> MagicMock:
    return MagicMock(chat_id=chat_id, message_id=message_id)


class TestAtrasUnico(unittest.TestCase):

    def setUp(self):
        bot_atras._ultima.clear()

    def test_tiene_atras(self):
        self.assertTrue(bot_atras.tiene_atras(teclado_atras()))
        otro = InlineKeyboardMarkup([[InlineKeyboardButton("Si", callback_data="si")]])
        self.assertFalse(bot_atras.tiene_atras(otro))
        self.assertFalse(bot_atras.tiene_atras(None))

    def test_la_pregunta_nueva_le_saca_el_atras_a_la_anterior(self):
        bot = BotEnPrueba()
        with patch.object(ExtBot, "send_message", side_effect=[_mensaje(1, 10), _mensaje(1, 11)]):
            bot.send_message(chat_id=1, text="Medida", reply_markup=teclado_atras())
            bot.edit_message_reply_markup.assert_not_called()
            bot.send_message(chat_id=1, text="Tapas", reply_markup=teclado_atras())
        bot.edit_message_reply_markup.assert_called_once_with(chat_id=1, message_id=10, reply_markup=None)

    def test_mensajes_sin_atras_no_cuentan(self):
        bot = BotEnPrueba()
        with patch.object(ExtBot, "send_message", side_effect=[_mensaje(1, 10), _mensaje(1, 11)]):
            bot.send_message(chat_id=1, text="Medida", reply_markup=teclado_atras())
            bot.send_message(chat_id=1, text="✅ Foto recibida")  # la pregunta sigue con su ATRAS
        bot.edit_message_reply_markup.assert_not_called()
        self.assertEqual(bot_atras._ultima[1], 10)

    def test_cada_chat_por_separado(self):
        bot = BotEnPrueba()
        with patch.object(ExtBot, "send_message", side_effect=[_mensaje(1, 10), _mensaje(2, 20)]):
            bot.send_message(chat_id=1, text="A", reply_markup=teclado_atras())
            bot.send_message(chat_id=2, text="B", reply_markup=teclado_atras())
        bot.edit_message_reply_markup.assert_not_called()

    def test_error_al_editar_no_rompe_nada(self):
        bot = MagicMock()
        bot.edit_message_reply_markup.side_effect = BadRequest("Message is not modified")
        bot_atras.registrar(bot, 1, 10)
        bot_atras.registrar(bot, 1, 11)
        self.assertEqual(bot_atras._ultima[1], 11)

    def test_main_usa_este_bot(self):
        import main
        updater = main.crear_updater("123:test")
        self.assertIsInstance(updater.bot, bot_atras.BotConAtrasUnico)


class BotEnPrueba(bot_atras.BotConAtrasUnico):
    """El bot de verdad, sin red: send_message de Telegram se simula y la edición se registra."""

    def __init__(self):
        super().__init__("123:test")
        self.edit_message_reply_markup = MagicMock()


if __name__ == "__main__":
    unittest.main()
