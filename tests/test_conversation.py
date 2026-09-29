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


if __name__ == "__main__":
    unittest.main()
