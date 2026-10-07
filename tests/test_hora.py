import unittest
from unittest.mock import MagicMock

from tests import entorno
entorno.preparar()

from bot.states import START_TIME, END_TIME, MEASURE_MAIN, TANK_TYPE, FUMIGATION
from bot.handlers import hora
from bot.handlers.shared import pedir_hora, handle_hora_boton, get_start_time


def boton(data: str) -> MagicMock:
    upd = MagicMock()
    upd.effective_chat.id = 1
    upd.callback_query.data = data
    return upd


def botones(markup) -> list:
    return [b.callback_data for fila in markup.inline_keyboard for b in fila]


class TestTeclados(unittest.TestCase):

    def test_horas_24(self):
        datos = botones(hora.teclado_horas("inicio"))
        self.assertEqual(datos[:24], [f"hora:inicio:h:{h:02d}" for h in range(24)])
        self.assertEqual(datos[-1], "back")

    def test_minutos(self):
        datos = botones(hora.teclado_minutos("fin", "13"))
        self.assertEqual(datos[:12], [f"hora:fin:m:13:{m:02d}" for m in range(0, 60, 5)])
        self.assertEqual(datos[-1], "hora:fin:volver")

    def test_leer_boton(self):
        self.assertEqual(hora.leer_boton("hora:inicio:h:08"), ("inicio", "h", "08", None))
        self.assertEqual(hora.leer_boton("hora:fin:m:13:05"), ("fin", "m", "13", "05"))
        self.assertEqual(hora.leer_boton("hora:fin:volver"), ("fin", "volver", None, None))
        for malo in ("hora:inicio:h:24", "hora:otro:h:08", "hora:fin:m:13:60", "rf:main:1:c", "", None):
            self.assertIsNone(hora.leer_boton(malo), malo)


class TestFlujo(unittest.TestCase):

    def setUp(self):
        self.ctx = entorno.contexto({"service": "Limpieza y Reparacion de Tanques", "state_stack": []})
        self.assertEqual(pedir_hora(entorno.update_texto(""), self.ctx, "inicio"), START_TIME)

    def _ultimo(self):
        return self.ctx.bot.send_message.call_args.kwargs

    def test_pregunta_con_teclado(self):
        enviado = self._ultimo()
        self.assertIn("¿A qué hora empezaste el trabajo?", enviado["text"])
        self.assertIn("formato 24 hs", enviado["text"])
        self.assertEqual(botones(enviado["reply_markup"])[0], "hora:inicio:h:00")

    def test_hora_y_minutos_con_botones(self):
        upd = boton("hora:inicio:h:08")
        self.assertEqual(handle_hora_boton(upd, self.ctx), START_TIME)
        markup = upd.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        self.assertIn("hora:inicio:m:08:30", botones(markup))
        upd = boton("hora:inicio:m:08:30")
        self.assertEqual(handle_hora_boton(upd, self.ctx), END_TIME)
        self.assertEqual(self.ctx.user_data["start_time"], "08:30")
        upd.callback_query.edit_message_text.assert_called_with("✅ Hora de inicio: 08:30")
        self.assertIn("¿A qué hora terminaste el trabajo?", self._ultimo()["text"])
        # Fin: después de la hora (que va primero, apenas se lee el QR) se elige el tanque
        self.assertEqual(handle_hora_boton(boton("hora:fin:m:13:05"), self.ctx), TANK_TYPE)
        self.assertEqual(self.ctx.user_data["end_time"], "13:05")
        self.assertEqual(self.ctx.user_data["state_stack"], [START_TIME, END_TIME])

    def test_volver_a_elegir_la_hora(self):
        handle_hora_boton(boton("hora:inicio:h:08"), self.ctx)
        upd = boton("hora:inicio:volver")
        self.assertEqual(handle_hora_boton(upd, self.ctx), START_TIME)
        markup = upd.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        self.assertEqual(botones(markup)[0], "hora:inicio:h:00")
        self.assertNotIn("start_time", self.ctx.user_data)

    def test_boton_de_otro_paso_no_hace_nada(self):
        upd = boton("hora:fin:m:13:05")
        self.assertEqual(handle_hora_boton(upd, self.ctx), START_TIME)
        upd.callback_query.answer.assert_called_with("Ese paso ya terminó.")
        self.assertNotIn("end_time", self.ctx.user_data)

    def test_escrita_sigue_funcionando(self):
        self.assertEqual(get_start_time(entorno.update_texto("14:30"), self.ctx), END_TIME)
        self.assertEqual(self.ctx.user_data["start_time"], "14:30")

    def test_escrita_invalida(self):
        upd = entorno.update_texto("2 pm")
        self.assertEqual(get_start_time(upd, self.ctx), START_TIME)
        self.assertIn("24 hs", upd.message.reply_text.call_args.args[0])

    def test_despues_de_la_hora_tanque_o_fumigacion(self):
        handle_hora_boton(boton("hora:inicio:m:08:00"), self.ctx)
        self.assertEqual(handle_hora_boton(boton("hora:fin:m:12:00"), self.ctx), TANK_TYPE)
        self.ctx.user_data["service"] = "Fumigaciones"
        self.ctx.user_data["current_state"] = END_TIME
        self.assertEqual(handle_hora_boton(boton("hora:fin:m:12:00"), self.ctx), FUMIGATION)


if __name__ == "__main__":
    unittest.main()
