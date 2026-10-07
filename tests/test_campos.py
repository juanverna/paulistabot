import unittest
from unittest.mock import MagicMock

from tests import entorno
entorno.preparar()

from bot.services import campos
from bot.states import (MEASURE_MAIN, TAPAS_INSPECCION_MAIN, TAPAS_ACCESO_MAIN, SEALING_MAIN,
                        REPAIR_MAIN, MEASURE_ALT1, TAPAS_INSPECCION_ALT1, CONTACT, CONTACT_PHONE,
                        PHOTOS)
from bot.handlers import campos_tanque as ct


def boton(data: str) -> MagicMock:
    upd = MagicMock()
    upd.effective_chat.id = 1
    upd.message = None
    upd.callback_query.data = data
    return upd


def _datos(**extra) -> dict:
    datos = {"selected_category": "CISTERNA", "alternative_1": "RESERVA",
             "alternative_2": "INTERMEDIARIO", "service": "Limpieza y Reparacion de Tanques",
             "state_stack": []}
    datos.update(extra)
    return datos


class TestMedida(unittest.TestCase):

    def test_formatos_que_escriben_los_operarios(self):
        for escrito in ("1.80 2 1.50", "180 200 150", "1,80 x 2 x 1,5", "180x200x150",
                        "alto 1.80 ancho 2 profundo 1.50", "1.8 por 2 por 1.5"):
            self.assertEqual(campos.normalizar_medida(escrito), ("1.80, 2.00, 1.50", None), escrito)

    def test_varios_tanques(self):
        self.assertEqual(campos.normalizar_medida("2 tanques 1.80 1.80 1.80")[0], "2 tanques: 1.80, 1.80, 1.80")
        self.assertEqual(campos.normalizar_medida("1.80 1.80 1.80 y 1.40 1.40 1.40")[0],
                         "Tanque 1: 1.80, 1.80, 1.80 | Tanque 2: 1.40, 1.40, 1.40")

    def test_litros(self):
        self.assertEqual(campos.normalizar_medida("1000 litros")[0], "LITROS:1000")
        self.assertEqual(campos.normalizar_medida("1000 litros plástico")[0], "1000 lts (plástico)")
        self.assertEqual(campos.normalizar_medida("2000 lts acero inoxidable")[0], "2000 lts (acero inoxidable)")

    def test_rechaza_lo_que_no_es_medida(self):
        for escrito in ("grande", "1.80 2", "1.80 2 1.50 3", "0 0 0", "1.80 2 5000"):
            valor, problema = campos.normalizar_medida(escrito)
            self.assertIsNone(valor, escrito)
            self.assertTrue(problema)


class TestTelefonoYSellado(unittest.TestCase):

    def test_telefono(self):
        for escrito in ("1135456067", "11 3545-6067", "011 3545 6067", "+54 9 11 3545 6067", "54 11 3545 6067"):
            self.assertEqual(campos.normalizar_telefono(escrito), "1135456067", escrito)
        for escrito in ("4567890", "113545606799", "no tiene"):
            self.assertIsNone(campos.normalizar_telefono(escrito), escrito)

    def test_nombre_y_telefono_juntos(self):
        self.assertEqual(campos.separar_nombre_telefono("Daniel 11 3545 6067"), ("Daniel", "1135456067"))
        self.assertEqual(campos.separar_nombre_telefono("Daniel"), ("Daniel", None))

    def test_sellado(self):
        self.assertEqual(campos.texto_sellado(["burlete", "masilla"]), "Masilla y burlete")
        self.assertEqual(campos.texto_sellado(["masilla"], "Cinta"), "Masilla y cinta")
        self.assertEqual(campos.texto_sellado([]), "No tiene")

    def test_medidas_de_acceso_sin_abreviaturas(self):
        medidas = campos.MEDIDAS_TAPA["acceso"]
        for m in ("47", "48", "49", "50", "51", "52", "55"):
            self.assertIn(m, medidas)
        self.assertNotIn("4789", medidas)
        self.assertNotIn("50125", medidas)

    def test_codigo_tapa(self):
        self.assertEqual(campos.codigo_tapa("insp", "CISTERNA", "EA", "60"), "TITCEA 60")
        self.assertEqual(campos.codigo_tapa("acceso", "INTERMEDIARIO", "C", "56.5"), "TATHC 56.5")


class TestPasosConBotones(unittest.TestCase):

    def test_medida_valida_pasa_a_tapas(self):
        ctx = entorno.contexto(_datos())
        estado = ct.recibir_medida("main")(entorno.update_texto("180 200 150"), ctx)
        self.assertEqual(estado, TAPAS_INSPECCION_MAIN)
        self.assertEqual(ctx.user_data["measure_main"], "1.80, 2.00, 1.50")
        self.assertEqual(ctx.user_data["state_stack"], [MEASURE_MAIN])

    def test_medida_invalida_se_vuelve_a_pedir(self):
        ctx = entorno.contexto(_datos())
        upd = entorno.update_texto("grande")
        self.assertEqual(ct.recibir_medida("main")(upd, ctx), MEASURE_MAIN)
        self.assertNotIn("measure_main", ctx.user_data)
        self.assertIn("3 medidas", entorno.mensajes_enviados(ctx, upd))

    def test_litros_pregunta_el_material(self):
        ctx = entorno.contexto(_datos())
        self.assertEqual(ct.recibir_medida("alt1")(entorno.update_texto("1000 litros"), ctx), MEASURE_ALT1)
        self.assertEqual(ct.boton_material("alt1")(boton("md:alt1:plastico"), ctx), TAPAS_INSPECCION_ALT1)
        self.assertEqual(ctx.user_data["measure_alt1"], "1000 lts (plástico)")

    def test_tapas_con_botones(self):
        ctx = entorno.contexto(_datos())
        insp = ct.boton_tapas("main", "insp")
        for data in ("tp:main:insp:m:60", "tp:main:insp:v:EA", "tp:main:insp:m:30", "tp:main:insp:v:C"):
            self.assertEqual(insp(boton(data), ctx), TAPAS_INSPECCION_MAIN)
        self.assertEqual(insp(boton("tp:main:insp:listo"), ctx), TAPAS_ACCESO_MAIN)
        self.assertEqual(ctx.user_data["tapas_inspeccion_main"], "TITCEA 60, TITCC 30")

        acceso = ct.boton_tapas("main", "acceso")
        acceso(boton("tp:main:acceso:otra"), ctx)
        ct.texto_tapas("main", "acceso")(entorno.update_texto("57,5"), ctx)
        acceso(boton("tp:main:acceso:v:EA"), ctx)
        acceso(boton("tp:main:acceso:m:56.5"), ctx)
        acceso(boton("tp:main:acceso:v:C"), ctx)
        acceso(boton("tp:main:acceso:borrar"), ctx)
        self.assertEqual(acceso(boton("tp:main:acceso:listo"), ctx), SEALING_MAIN)
        self.assertEqual(ctx.user_data["tapas_acceso_main"], "TATCEA 57.5")

    def test_no_tiene_y_listo_vacio(self):
        ctx = entorno.contexto(_datos())
        insp = ct.boton_tapas("main", "insp")
        self.assertEqual(insp(boton("tp:main:insp:listo"), ctx), TAPAS_INSPECCION_MAIN)  # sin tapas: no avanza
        self.assertEqual(insp(boton("tp:main:insp:no"), ctx), TAPAS_ACCESO_MAIN)
        self.assertEqual(ctx.user_data["tapas_inspeccion_main"], "No tiene")

    def test_boton_de_otro_paso_no_se_toma(self):
        ctx = entorno.contexto(_datos())
        upd = boton("tp:main:insp:m:60")
        self.assertEqual(ct.boton_tapas("main", "acceso")(upd, ctx), TAPAS_ACCESO_MAIN)
        upd.callback_query.answer.assert_called_with("Ese paso ya terminó.")
        self.assertNotIn("tapas_en_curso", ctx.user_data)

    def test_texto_en_tapas_reenvia_los_botones(self):
        ctx = entorno.contexto(_datos())
        upd = entorno.update_texto("TITCEA 60")
        self.assertEqual(ct.texto_tapas("main", "insp")(upd, ctx), TAPAS_INSPECCION_MAIN)
        self.assertIn("Usá los botones", entorno.mensajes_enviados(ctx, upd))

    def test_sellado(self):
        ctx = entorno.contexto(_datos())
        sellado = ct.boton_sellado("main")
        sellado(boton("se:main:burlete"), ctx)
        sellado(boton("se:main:masilla"), ctx)
        sellado(boton("se:main:silicona"), ctx)
        sellado(boton("se:main:silicona"), ctx)  # la desmarca
        self.assertEqual(sellado(boton("se:main:listo"), ctx), REPAIR_MAIN)
        self.assertEqual(ctx.user_data["sealing_main"], "Masilla y burlete")

    def test_sellado_otro_escrito(self):
        ctx = entorno.contexto(_datos())
        ct.boton_sellado("main")(boton("se:main:otro"), ctx)
        self.assertEqual(ct.texto_sellado("main")(entorno.update_texto("cinta"), ctx), REPAIR_MAIN)
        self.assertEqual(ctx.user_data["sealing_main"], "cinta")

    def test_atras_desde_tapas_vuelve_a_la_medida(self):
        ctx = entorno.contexto(_datos(state_stack=[MEASURE_MAIN], current_state=TAPAS_INSPECCION_MAIN,
                                      measure_main="1.80, 2.00, 1.50"))
        upd = boton("back")
        self.assertEqual(ct.boton_tapas("main", "insp")(upd, ctx), MEASURE_MAIN)
        enviados = [c.kwargs["text"] for c in ctx.bot.send_message.call_args_list]
        self.assertTrue(any("Medida del tanque" in t for t in enviados), enviados)


class TestContacto(unittest.TestCase):

    def test_nombre_y_despues_telefono(self):
        ctx = entorno.contexto(_datos(current_state=CONTACT))
        self.assertEqual(ct.recibir_nombre(entorno.update_texto("Daniel"), ctx), CONTACT_PHONE)
        upd = entorno.update_texto("11 3545")
        self.assertEqual(ct.recibir_telefono(upd, ctx), CONTACT_PHONE)  # incompleto
        self.assertEqual(ct.recibir_telefono(entorno.update_texto("11 3545 6067"), ctx), PHOTOS)
        self.assertEqual(ctx.user_data["contact"], "Daniel 1135456067")

    def test_juntos_como_antes(self):
        ctx = entorno.contexto(_datos(current_state=CONTACT))
        self.assertEqual(ct.recibir_nombre(entorno.update_texto("Daniel 1135456067"), ctx), PHOTOS)
        self.assertEqual(ctx.user_data["contact"], "Daniel 1135456067")

    def test_solo_numeros_no_es_nombre(self):
        ctx = entorno.contexto(_datos(current_state=CONTACT))
        self.assertEqual(ct.recibir_nombre(entorno.update_texto("1135456067"), ctx), CONTACT)

    def test_sin_encargado_y_sin_telefono(self):
        ctx = entorno.contexto(_datos(current_state=CONTACT))
        self.assertEqual(ct.boton_contacto(boton("ct:sin"), ctx), PHOTOS)
        self.assertEqual(ctx.user_data["contact"], "Sin encargado")

        ctx = entorno.contexto(_datos(current_state=CONTACT))
        ct.recibir_nombre(entorno.update_texto("Daniel"), ctx)
        self.assertEqual(ct.boton_contacto(boton("ct:sintel"), ctx), PHOTOS)
        self.assertEqual(ctx.user_data["contact"], "Daniel (sin teléfono)")


class TestConversacion(unittest.TestCase):

    def test_botones_nuevos_no_se_toman_como_tanque(self):
        from telegram import Update
        from telegram.ext import CallbackQueryHandler
        from bot.conversation import build_conversation_handler
        from bot.states import TANK_TYPE
        handler = build_conversation_handler()
        update = MagicMock(spec=Update)
        [fallback] = handler.fallbacks
        for data in ("tp:main:insp:m:60", "se:main:listo", "md:main:plastico", "ct:sin"):
            update.callback_query.data = data
            for h in handler.states[TANK_TYPE]:
                if isinstance(h, CallbackQueryHandler):
                    self.assertFalse(h.check_update(update), data)
            self.assertTrue(fallback.check_update(update), data)


if __name__ == "__main__":
    unittest.main()
