import unittest

from tests import entorno
entorno.preparar()

from bot.states import REPAIR_PHOTOS, STATE_KEYS
from bot.conversation import build_conversation_handler


class TestConversacion(unittest.TestCase):

    def test_arma_el_handler_con_el_paso_de_fotos(self):
        handler = build_conversation_handler()
        self.assertIn(REPAIR_PHOTOS, handler.states)
        self.assertIn(REPAIR_PHOTOS, STATE_KEYS)

    def test_boton_viejo_de_una_foto_no_se_toma_como_si_no(self):
        # En las preguntas de los tanques un "rf:..." o "hora:..." no lo agarra el handler del
        # paso, sino el fallback que responde "Ese paso ya terminó"
        from unittest.mock import MagicMock
        from telegram import Update
        from telegram.ext import CallbackQueryHandler
        from bot.states import CUERPOS, TANK_TYPE, TANK_CUERPO, OTRO_TANQUE, REPAIR
        handler = build_conversation_handler()
        update = MagicMock(spec=Update)
        fallback = handler.fallbacks[0]  # botones vencidos (el otro es ATRAS)
        for data in ("rf:t1:3:c", "hora:inicio:h:08", "rp:t1:g:flo", "tq:RESERVA"):
            update.callback_query.data = data
            for estado in (CUERPOS, TANK_TYPE, TANK_CUERPO, OTRO_TANQUE, REPAIR):
                for h in handler.states[estado]:
                    propio = (estado == REPAIR and data.startswith("rp:")) or (estado == TANK_TYPE and data.startswith("tq:"))
                    if isinstance(h, CallbackQueryHandler) and not propio:
                        self.assertFalse(h.check_update(update), (data, estado, h.callback.__name__))
            self.assertTrue(fallback.check_update(update), data)


if __name__ == "__main__":
    unittest.main()
