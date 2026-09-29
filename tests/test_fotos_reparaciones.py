import os
import unittest
from unittest.mock import patch

from tests import entorno
entorno.preparar()

from bot.states import (REPAIR_MAIN, REPAIR_ALT1, REPAIR_PHOTOS, SUGGESTIONS_MAIN,
                        SUGGESTIONS_ALT1, CONTACT, PHOTOS)
from bot.handlers import fotos_reparaciones as fr
from bot.handlers.tanques import get_repair_main, get_repair_alt1, get_suggestions_main
from bot.handlers.voice_handler import _go_to_contact


def _datos_base(**extra):
    datos = {"selected_category": "CISTERNA", "alternative_1": "RESERVA",
             "alternative_2": "INTERMEDIARIO", "state_stack": []}
    datos.update(extra)
    return datos


class TestNecesitaFotos(unittest.TestCase):

    def test_sin_reparaciones(self):
        for texto in ("no", "No.", "ninguna", "Nada", "no tiene", "No hay reparaciones",
                      "sin reparaciones", "-", "N/A", "no aplica", "  ", "", None):
            self.assertFalse(fr.necesita_fotos(texto), repr(texto))

    def test_con_reparaciones(self):
        for texto in ("cambiar tapa de acceso", "revocar pared norte", "TATCEA 56.5",
                      "no cierra la tapa, cambiarla", "marco oxidado"):
            self.assertTrue(fr.necesita_fotos(texto), texto)


class TestFlujoManual(unittest.TestCase):

    def _hasta_fotos(self, texto="cambiar tapa de acceso"):
        ctx = entorno.contexto(_datos_base())
        estado = get_repair_main(entorno.update_texto(texto), ctx)
        return ctx, estado

    def test_sin_reparaciones_sigue_a_sugerencias(self):
        ctx, estado = self._hasta_fotos("ninguna")
        self.assertEqual(estado, SUGGESTIONS_MAIN)
        self.assertNotIn("rep_fotos", ctx.user_data)

    def test_con_reparaciones_pide_fotos(self):
        ctx, estado = self._hasta_fotos()
        self.assertEqual(estado, REPAIR_PHOTOS)
        self.assertEqual(ctx.user_data["repairs"], "cambiar tapa de acceso")
        self.assertIn("fotos de las reparaciones de <b>Cisterna</b>",
                      ctx.bot.send_message.call_args.kwargs["text"])

    def test_varias_fotos_y_listo(self):
        ctx, _ = self._hasta_fotos()
        self.assertEqual(fr.handle_repair_photos(entorno.update_foto("f1"), ctx), REPAIR_PHOTOS)
        self.assertEqual(fr.handle_repair_photos(entorno.update_foto("f2"), ctx), REPAIR_PHOTOS)
        self.assertEqual(fr.handle_repair_photos(entorno.update_texto("Listo"), ctx), SUGGESTIONS_MAIN)
        self.assertEqual(ctx.user_data["fotos_reparaciones"]["main"], ["f1", "f2"])
        self.assertEqual(ctx.user_data["state_stack"], [REPAIR_MAIN, REPAIR_PHOTOS])
        self.assertNotIn("destrabes", ctx.user_data)

    def test_album_responde_una_vez(self):
        ctx, _ = self._hasta_fotos()
        u1, u2 = entorno.update_foto("f1", album="A"), entorno.update_foto("f2", album="A")
        fr.handle_repair_photos(u1, ctx)
        fr.handle_repair_photos(u2, ctx)
        self.assertEqual(u1.message.reply_text.call_count, 1)
        self.assertEqual(u2.message.reply_text.call_count, 0)
        self.assertEqual(ctx.user_data["fotos_reparaciones"]["main"], ["f1", "f2"])

    def test_documento_imagen_se_acepta_y_otro_no(self):
        ctx, _ = self._hasta_fotos()
        fr.handle_repair_photos(entorno.update_documento("d1", "image/jpeg"), ctx)
        fr.handle_repair_photos(entorno.update_documento("d2", "application/pdf"), ctx)
        self.assertEqual(ctx.user_data["fotos_reparaciones"]["main"], ["d1"])

    def test_listo_sin_fotos_traba(self):
        ctx, _ = self._hasta_fotos()
        for texto in ("Listo", "no tengo"):
            upd = entorno.update_texto(texto)
            self.assertEqual(fr.handle_repair_photos(upd, ctx), REPAIR_PHOTOS)
            self.assertIn("Falta la foto de las reparaciones de <b>Cisterna</b>. Si tenés otra foto",
                          ctx.bot.send_message.call_args.kwargs["text"])
        self.assertTrue(ctx.user_data["rep_fotos"]["trabado"])

    def test_trabado_se_destraba_con_foto(self):
        ctx, _ = self._hasta_fotos()
        fr.handle_repair_photos(entorno.update_texto("Listo"), ctx)
        fr.handle_repair_photos(entorno.update_foto("f1"), ctx)
        self.assertFalse(ctx.user_data["rep_fotos"]["trabado"])
        self.assertEqual(fr.handle_repair_photos(entorno.update_texto("Listo"), ctx), SUGGESTIONS_MAIN)
        self.assertNotIn("destrabes", ctx.user_data)

    @patch.dict(os.environ, {"ADMIN_DAILY_CODE": "4821"})
    def test_trabado_se_destraba_con_codigo(self):
        ctx, _ = self._hasta_fotos()
        fr.handle_repair_photos(entorno.update_texto("Listo"), ctx)
        self.assertEqual(fr.handle_repair_photos(entorno.update_texto("1111"), ctx), REPAIR_PHOTOS)
        self.assertEqual(fr.handle_repair_photos(entorno.update_texto("4821"), ctx), SUGGESTIONS_MAIN)
        [reg] = ctx.user_data["destrabes"]
        self.assertEqual((reg["tanque"], reg["item"], reg["motivo"]),
                         ("Cisterna", "reparaciones", "foto faltante"))

    @patch.dict(os.environ, {"ADMIN_DAILY_CODE": "4821"})
    def test_codigo_sin_estar_trabado_no_hace_nada(self):
        ctx, _ = self._hasta_fotos()
        self.assertEqual(fr.handle_repair_photos(entorno.update_texto("4821"), ctx), REPAIR_PHOTOS)
        self.assertNotIn("destrabes", ctx.user_data)

    def test_atras_vuelve_a_reparaciones_y_descarta_fotos(self):
        ctx, _ = self._hasta_fotos()
        fr.handle_repair_photos(entorno.update_foto("f1"), ctx)
        self.assertEqual(fr.handle_repair_photos(entorno.update_texto("atrás"), ctx), REPAIR_MAIN)
        self.assertNotIn("main", ctx.user_data["fotos_reparaciones"])

    def test_atras_desde_sugerencias_vuelve_a_fotos(self):
        ctx, _ = self._hasta_fotos()
        fr.handle_repair_photos(entorno.update_foto("f1"), ctx)
        fr.handle_repair_photos(entorno.update_texto("Listo"), ctx)
        self.assertEqual(get_suggestions_main(entorno.update_texto("atras"), ctx), REPAIR_PHOTOS)
        self.assertEqual(ctx.user_data["rep_fotos"]["sufijo"], "main")
        self.assertEqual(fr.handle_repair_photos(entorno.update_texto("Listo"), ctx), SUGGESTIONS_MAIN)

    def test_tanque_alternativo(self):
        ctx = entorno.contexto(_datos_base())
        self.assertEqual(get_repair_alt1(entorno.update_texto("revocar"), ctx), REPAIR_PHOTOS)
        fr.handle_repair_photos(entorno.update_foto("r1"), ctx)
        self.assertEqual(fr.handle_repair_photos(entorno.update_texto("listo"), ctx), SUGGESTIONS_ALT1)
        self.assertEqual(ctx.user_data["fotos_reparaciones"]["alt1"], ["r1"])
        self.assertEqual(ctx.user_data["state_stack"], [REPAIR_ALT1, REPAIR_PHOTOS])


class TestFlujoVoz(unittest.TestCase):

    def test_pide_fotos_de_cada_tanque_con_reparaciones_y_despues_contacto(self):
        ctx = entorno.contexto(_datos_base(repairs="cambiar tapa", repair_alt1="no",
                                           repair_alt2="revocar paredes"))
        upd = entorno.update_texto("")
        self.assertEqual(_go_to_contact(upd, ctx), REPAIR_PHOTOS)
        self.assertEqual(ctx.user_data["rep_fotos"]["sufijo"], "main")
        fr.handle_repair_photos(entorno.update_foto("m1"), ctx)
        self.assertEqual(fr.handle_repair_photos(entorno.update_texto("Listo"), ctx), REPAIR_PHOTOS)
        self.assertEqual(ctx.user_data["rep_fotos"]["sufijo"], "alt2")
        fr.handle_repair_photos(entorno.update_foto("i1"), ctx)
        self.assertEqual(fr.handle_repair_photos(entorno.update_texto("Listo"), ctx), CONTACT)
        self.assertEqual(ctx.user_data["fotos_reparaciones"], {"main": ["m1"], "alt2": ["i1"]})

    def test_con_contacto_va_a_fotos_generales(self):
        ctx = entorno.contexto(_datos_base(contact="Juan 1122334455"))
        self.assertEqual(_go_to_contact(entorno.update_texto(""), ctx), PHOTOS)

    def test_atras_no_se_permite_en_voz(self):
        ctx = entorno.contexto(_datos_base(repairs="cambiar tapa"))
        _go_to_contact(entorno.update_texto(""), ctx)
        self.assertEqual(fr.handle_repair_photos(entorno.update_texto("atras"), ctx), REPAIR_PHOTOS)


if __name__ == "__main__":
    unittest.main()
