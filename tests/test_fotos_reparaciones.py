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
                      "sin reparaciones", "-", "N/A", "no aplica", "  ", "", None,
                      # Errores de tipeo (caso real: "Ningana")
                      "Ningana", "ningua", "nimguna", "ningunaa", "nadaa", "Ninguno."):
            self.assertFalse(fr.necesita_fotos(texto), repr(texto))

    def test_con_reparaciones(self):
        for texto in ("cambiar tapa de acceso", "revocar pared norte", "TATCEA 56.5",
                      "no cierra la tapa, cambiarla", "marco oxidado",
                      "tapa", "marco", "nueva tapa", "no tiene tapa", "no hay tapa", "TATCEA",
                      "flotante", "automatico", "revoque"):
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
        texto = ctx.bot.send_message.call_args.kwargs["text"]
        self.assertIn("Mandá una foto de cada reparación de <b>Cisterna</b>", texto)
        self.assertIn("• Tapa de acceso", texto)

    def test_varias_fotos_y_listo(self):
        ctx, _ = self._hasta_fotos()
        self.assertEqual(fr.handle_repair_photos(entorno.update_foto("f1"), ctx), REPAIR_PHOTOS)
        self.assertEqual(fr.handle_repair_photos(entorno.update_foto("f2"), ctx), REPAIR_PHOTOS)
        self.assertEqual(fr.handle_repair_photos(entorno.update_texto("Listo"), ctx), SUGGESTIONS_MAIN)
        self.assertEqual(entorno.ids(ctx.user_data["fotos_reparaciones"]["main"]), ["f1", "f2"])
        self.assertEqual(ctx.user_data["state_stack"], [REPAIR_MAIN, REPAIR_PHOTOS])
        self.assertNotIn("destrabes", ctx.user_data)

    def test_album_responde_una_vez(self):
        ctx, _ = self._hasta_fotos()
        u1, u2 = entorno.update_foto("f1", album="A"), entorno.update_foto("f2", album="A")
        fr.handle_repair_photos(u1, ctx)
        fr.handle_repair_photos(u2, ctx)
        self.assertEqual(u1.message.reply_text.call_count, 1)
        self.assertEqual(u2.message.reply_text.call_count, 0)
        self.assertEqual(entorno.ids(ctx.user_data["fotos_reparaciones"]["main"]), ["f1", "f2"])

    def test_documento_imagen_se_acepta_y_otro_no(self):
        ctx, _ = self._hasta_fotos()
        fr.handle_repair_photos(entorno.update_documento("d1", "image/jpeg"), ctx)
        fr.handle_repair_photos(entorno.update_documento("d2", "application/pdf"), ctx)
        self.assertEqual(entorno.ids(ctx.user_data["fotos_reparaciones"]["main"]), ["d1"])

    def test_listo_sin_fotos_traba(self):
        ctx, _ = self._hasta_fotos()
        for texto in ("Listo", "no tengo"):
            upd = entorno.update_texto(texto)
            self.assertEqual(fr.handle_repair_photos(upd, ctx), REPAIR_PHOTOS)
            self.assertIn("Falta la foto de la tapa de acceso. Si tenés otra foto",
                          ctx.bot.send_message.call_args.kwargs["text"])
        self.assertTrue(ctx.user_data["rep_fotos"]["trabado"])

    def test_no_con_el_paso_trabado_explica_el_codigo(self):
        # Caso real: trabado, el operario escribe "No" (no tiene otra foto)
        ctx, _ = self._hasta_fotos()
        fr.handle_repair_photos(entorno.update_texto("Listo"), ctx)
        self.assertIn("pedile al encargado el código de hoy y escribilo acá",
                      ctx.bot.send_message.call_args.kwargs["text"])
        upd = entorno.update_texto("No")
        self.assertEqual(fr.handle_repair_photos(upd, ctx), REPAIR_PHOTOS)
        self.assertIn("pedile al encargado el código de hoy y escribilo acá", upd.message.reply_text.call_args.args[0])

    def test_trabado_se_destraba_con_foto(self):
        ctx, _ = self._hasta_fotos()
        fr.handle_repair_photos(entorno.update_texto("Listo"), ctx)
        fr.handle_repair_photos(entorno.update_foto("f1"), ctx)
        # Sigue trabado hasta el próximo "Listo" (ahí se mira si la foto sirve; con la IA apagada, sí)
        self.assertTrue(ctx.user_data["rep_fotos"]["trabado"])
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
                         ("Cisterna", "Tapa de acceso", "foto faltante"))

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
        self.assertEqual(entorno.ids(ctx.user_data["fotos_reparaciones"]["alt1"]), ["r1"])
        self.assertEqual(ctx.user_data["state_stack"], [REPAIR_ALT1, REPAIR_PHOTOS])


class TestCodigoDeOtroTanque(unittest.TestCase):
    """Caso real: "TITREA40 TMTCEA49" en la cisterna. No sigue hasta que se corrija."""

    def setUp(self):
        self.ctx = entorno.contexto(_datos_base())
        self.assertEqual(get_repair_main(entorno.update_texto("TITREA40 TMTCEA49"), self.ctx), REPAIR_PHOTOS)

    def _ultimo(self):
        return self.ctx.bot.send_message.call_args.kwargs["text"]

    def test_pide_corregir_y_no_acepta_fotos_ni_listo(self):
        self.assertIn("TITREA40 es de <b>Reserva</b>, no de <b>Cisterna</b>.", self._ultimo())
        upd = entorno.update_foto("f1")
        fr.handle_repair_photos(upd, self.ctx)
        self.assertIn("Primero corregí el código", upd.message.reply_text.call_args.args[0])
        self.assertEqual(self.ctx.user_data.get("fotos_reparaciones", {}).get("main", []), [])
        upd = entorno.update_texto("Listo")
        self.assertEqual(fr.handle_repair_photos(upd, self.ctx), REPAIR_PHOTOS)
        self.assertEqual(self.ctx.user_data["repairs"], "TITREA40 TMTCEA49")

    def test_no_despues_de_un_rechazo(self):
        # Caso real: "Ningana" (rechazado antes del arreglo) y después "No": tiene que seguir
        ctx = entorno.contexto(_datos_base())
        self.assertEqual(get_repair_main(entorno.update_texto("pintar la puerta"), ctx), REPAIR_PHOTOS)
        self.assertEqual(fr.handle_repair_photos(entorno.update_texto("No"), ctx), SUGGESTIONS_MAIN)
        self.assertEqual(ctx.user_data["repairs"], "No")

    def test_ningana_no_pide_fotos(self):
        ctx = entorno.contexto(_datos_base())
        self.assertEqual(get_repair_main(entorno.update_texto("Ningana"), ctx), SUGGESTIONS_MAIN)

    def test_codigo_mal_escrito_no_deja_seguir(self):
        # Caso real: "taticea30"
        ctx = entorno.contexto(_datos_base())
        self.assertEqual(get_repair_main(entorno.update_texto("taticea30"), ctx), REPAIR_PHOTOS)
        self.assertIn("no es un código válido", ctx.bot.send_message.call_args.kwargs["text"])
        fr.handle_repair_photos(entorno.update_texto("TATCEA30"), ctx)
        self.assertEqual(ctx.user_data["repairs"], "TATCEA30")
        self.assertIn("• Tapa de acceso", ctx.bot.send_message.call_args.kwargs["text"])

    def test_sigue_mal_y_despues_bien(self):
        fr.handle_repair_photos(entorno.update_texto("TITRC40 TMTCEA49"), self.ctx)
        self.assertIn("TITRC40 es de <b>Reserva</b>", self._ultimo())
        self.assertEqual(fr.handle_repair_photos(entorno.update_texto("TITCEA40 TMTCEA49"), self.ctx),
                         REPAIR_PHOTOS)
        self.assertEqual(self.ctx.user_data["repairs"], "TITCEA40 TMTCEA49")
        self.assertIn("Mandá una foto de cada reparación", self._ultimo())
        self.assertNotIn("corregir_codigos", self.ctx.user_data["rep_fotos"])
        fr.handle_repair_photos(entorno.update_foto("f1"), self.ctx)
        self.assertEqual(entorno.ids(self.ctx.user_data["fotos_reparaciones"]["main"]), ["f1"])


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
        fotos = ctx.user_data["fotos_reparaciones"]
        self.assertEqual((entorno.ids(fotos["main"]), entorno.ids(fotos["alt2"])), (["m1"], ["i1"]))

    def test_con_contacto_va_a_fotos_generales(self):
        ctx = entorno.contexto(_datos_base(contact="Juan 1122334455"))
        self.assertEqual(_go_to_contact(entorno.update_texto(""), ctx), PHOTOS)

    def test_atras_no_se_permite_en_voz(self):
        ctx = entorno.contexto(_datos_base(repairs="cambiar tapa"))
        _go_to_contact(entorno.update_texto(""), ctx)
        self.assertEqual(fr.handle_repair_photos(entorno.update_texto("atras"), ctx), REPAIR_PHOTOS)


if __name__ == "__main__":
    unittest.main()
