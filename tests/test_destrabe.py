import os
import unittest
from unittest.mock import patch

from tests import entorno
entorno.preparar()

from bot.services import destrabe


@patch.dict(os.environ, {"ADMIN_DAILY_CODE": "4821"})
class TestDestrabe(unittest.TestCase):

    def test_mensaje_trabado(self):
        self.assertEqual(
            destrabe.mensaje_trabado("Falta la foto de las reparaciones de Cisterna"),
            "Falta la foto de las reparaciones de Cisterna. Si tenés otra foto del mismo lugar "
            "en tu galería, mandala. Si no tenés, comunicate con el encargado para ver cómo seguimos.",
        )

    def test_parece_codigo(self):
        for texto in ("4821", " 48 21 ", "1234"):
            self.assertTrue(destrabe.parece_codigo(texto), texto)
        for texto in ("listo", "no tengo", "12a4", "", "5"):
            self.assertFalse(destrabe.parece_codigo(texto), texto)

    def test_codigo_correcto(self):
        self.assertEqual(destrabe.intentar_destrabe({}, "4821"), destrabe.OK)
        self.assertEqual(destrabe.intentar_destrabe({}, "48 21"), destrabe.OK)

    def test_codigo_incorrecto(self):
        self.assertEqual(destrabe.intentar_destrabe({}, "1111"), destrabe.INCORRECTO)

    def test_bloqueo_tras_varios_intentos(self):
        user_data = {}
        for _ in range(destrabe.MAX_INTENTOS - 1):
            self.assertEqual(destrabe.intentar_destrabe(user_data, "1111"), destrabe.INCORRECTO)
        self.assertEqual(destrabe.intentar_destrabe(user_data, "1111"), destrabe.BLOQUEADO)
        # Bloqueado: ni el código correcto pasa hasta que venza el bloqueo
        self.assertEqual(destrabe.intentar_destrabe(user_data, "4821"), destrabe.BLOQUEADO)

    def test_sin_codigo_configurado_no_destraba(self):
        with patch.dict(os.environ, {"ADMIN_DAILY_CODE": ""}):
            self.assertEqual(destrabe.intentar_destrabe({}, "4821"), destrabe.INCORRECTO)

    def test_registrar(self):
        user_data = {}
        reg = destrabe.registrar_destrabe(user_data, "Cisterna", "reparaciones",
                                          destrabe.MOTIVO_FOTO_FALTANTE)
        self.assertEqual(user_data["destrabes"], [reg])
        self.assertEqual(reg["tanque"], "Cisterna")
        self.assertEqual(reg["motivo"], "foto faltante")
        self.assertRegex(reg["fecha"], r"^\d{2}/\d{2}/\d{4}$")
        self.assertRegex(reg["hora"], r"^\d{2}:\d{2}$")


if __name__ == "__main__":
    unittest.main()
