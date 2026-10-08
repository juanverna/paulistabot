import unittest
from unittest.mock import MagicMock

from tests import entorno
entorno.preparar()

from bot.services import campos
from bot.services.items_reparacion import detectar_items, problemas_de_reparaciones
from bot.states import (MEASURE, TAPAS_INSPECCION, TAPAS_ACCESO, SEALING, REPAIR, REPAIR_PHOTOS,
                        SUGGESTIONS, CONTACT, CONTACT_PHONE, PHOTOS, CUERPOS, TANK_TYPE, TANK_CUERPO,
                        OTRO_TANQUE, FINAL_SUMMARY, TANK_CUBAS)
from bot.handlers import campos_tanque as ct
from bot.handlers.common import atras_boton


def boton(data: str) -> MagicMock:
    upd = MagicMock()
    upd.effective_chat.id = 1
    upd.message = None
    upd.callback_query.data = data
    return upd


def _datos(**extra) -> dict:
    datos = {"tanques": [{"id": "t1", "tipo": "CISTERNA", "cuerpo": None},
                         {"id": "t2", "tipo": "RESERVA", "cuerpo": None}],
             "tanque_actual": "t1", "service": "Limpieza y Reparacion de Tanques", "state_stack": []}
    datos.update(extra)
    return datos


def _enviados(ctx) -> str:
    return "\n".join(c.kwargs.get("text", "") for c in ctx.bot.send_message.call_args_list)


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


class TestTelefono(unittest.TestCase):

    def test_telefono(self):
        for escrito in ("1135456067", "11 3545-6067", "011 3545 6067", "+54 9 11 3545 6067", "54 11 3545 6067"):
            self.assertEqual(campos.normalizar_telefono(escrito), "1135456067", escrito)
        for escrito in ("4567890", "113545606799", "no tiene"):
            self.assertIsNone(campos.normalizar_telefono(escrito), escrito)

    def test_nombre_y_telefono_juntos(self):
        self.assertEqual(campos.separar_nombre_telefono("Daniel 11 3545 6067"), ("Daniel", "1135456067"))
        self.assertEqual(campos.separar_nombre_telefono("Daniel"), ("Daniel", None))


class TestCatalogo(unittest.TestCase):

    def test_catalogo_del_dueno(self):
        cat = campos.CATALOGO_REPARACIONES
        self.assertEqual(cat["tit"][2]["ins"][2], ["30x30", "40x40", "50x50", "60x60", "80x80"])
        acceso = cat["tat"][2]
        self.assertEqual(acceso["com"][2], ["47x47", "48x48", "49x49", "50x50", "52x52"])
        self.assertEqual(acceso["est"][2], ["39x49", "54", "60"])
        self.assertEqual(acceso["oct"][2], ["53.5x56.5", "54x54"])
        self.assertEqual(acceso["pun"][2], ["54"])
        self.assertEqual(acceso["12a"][2], ["49.5", "56", "56.5", "58"])
        self.assertEqual(acceso["evi"][2], ["62", "69"])
        self.assertEqual(cat["tmt"][2]["tm"][2], ["48x48", "49x49", "50x50", "52x52", "54x54", "60x60"])
        self.assertEqual(cat["mat"][2]["ma"][2], ["48", "49", "50", "52", "54", "60"])

    def test_texto_de_cada_reparacion(self):
        self.assertEqual(campos.reparacion("tit", "CISTERNA", "EA", "ins", "60x60"), "TITCEA 60x60")
        self.assertEqual(campos.reparacion("tat", "INTERMEDIARIO", "C", "12a", "56.5"),
                         "TATHC 12 agujeros punta recortada 56.5")
        self.assertEqual(campos.reparacion("tmt", "RESERVA", "EA", "tm", "48x48"), "TMTREA 48x48")
        self.assertEqual(campos.reparacion("mat", "RESERVA", "C", "ma", "50"), "MATRC 50")
        # Revoque: nomenclatura del dueño (tanque + cuba, pared, COMP/PARC y medida del parche)
        self.assertEqual(campos.reparacion("rev", "CISTERNA", "EA", cara="F"), "TCEA F COMP")
        self.assertEqual(campos.reparacion("rev", "RESERVA", "C", cara="LI", parche="1.50x1.50"),
                         "TRC LI PARC 1.50x1.50")
        self.assertEqual(campos.reparacion("rev", "INTERMEDIARIO", "EA", cara="CF"), "THEA CF COMP")
        self.assertEqual(campos.reparacion("rev", "CISTERNA", "C", cara="P", parche="2.00x0.50"),
                         "TCC P PARC 2.00x0.50")
        self.assertEqual(campos.reparacion("flo"), "flotante")
        self.assertEqual(campos.reparacion("aut"), "automático")

    def test_todo_el_catalogo_pasa_el_control_y_pide_la_foto_correcta(self):
        # Lo que arma el menú tiene que entrar al paso de fotos sin que el bot pida corregirlo
        grupo_foto = {"tit": "tapa_inspeccion", "tat": "tapa_acceso", "tmt": "tapa_marco", "mat": "marco"}
        for tanque in ("CISTERNA", "RESERVA", "INTERMEDIARIO"):
            for grupo, (_, prefijo, tipos) in campos.CATALOGO_REPARACIONES.items():
                if prefijo is None:
                    continue
                for tipo, (_, _, medidas) in tipos.items():
                    for medida in medidas:
                        for variante in ("EA", "C"):
                            texto = campos.reparacion(grupo, tanque, variante, tipo, medida)
                            self.assertIsNone(problemas_de_reparaciones(texto, tanque), texto)
                            items = detectar_items(texto)
                            self.assertEqual(list(items), [grupo_foto[grupo]], texto)
                            self.assertEqual(items[grupo_foto[grupo]]["cantidad"], 1, texto)
        for grupo, foto in (("flo", "flotante"), ("aut", "automatico")):
            self.assertEqual(list(detectar_items(campos.reparacion(grupo))), [foto])
        for tanque in ("CISTERNA", "RESERVA", "INTERMEDIARIO"):
            for cara in campos.CARAS_REVOQUE:
                for cuba in campos.CUBAS:
                    for parche in ("", "2.00x2.00"):
                        texto = campos.reparacion("rev", tanque, cuba, cara=cara, parche=parche)
                        self.assertIsNone(problemas_de_reparaciones(texto, tanque), texto)
                        self.assertEqual(list(detectar_items(texto)), ["revoque"], texto)

    def test_cubas_del_revoque_no_duplican_la_tapa(self):
        # "entrada de agua" y "ciego" de dos revoques no son dos tapas de acceso
        texto = "TATCEA 47x47, TCEA F COMP, TCC P PARC 1.00x1.00"
        items = detectar_items(texto)
        self.assertEqual(items["tapa_acceso"]["cantidad"], 1)
        self.assertEqual(items["revoque"]["cantidad"], 1)
        self.assertIsNone(problemas_de_reparaciones(texto, "CISTERNA"))
        # el texto escrito a mano de antes sigue contando 2
        self.assertEqual(detectar_items("tapa de acceso de entrada de agua y ciego")["tapa_acceso"]["cantidad"], 2)

    def test_medidas_del_parche(self):
        for escrito, esperado in (("2x2", "2.00x2.00"), ("1,5 x 1,5", "1.50x1.50"), ("2 por 0.5", "2.00x0.50")):
            self.assertEqual(campos.normalizar_parche(escrito), (esperado, None), escrito)
        for escrito in ("grande", "2", "2x2x2", "0x1", "20x1"):
            valor, problema = campos.normalizar_parche(escrito)
            self.assertIsNone(valor, escrito)
            self.assertTrue(problema)

    def test_varias_reparaciones_juntas(self):
        texto = "TATCEA evita marco 62, TATCC 47x47, MATCEA 50, revoque lateral, flotante"
        self.assertIsNone(problemas_de_reparaciones(texto, "CISTERNA"))
        items = detectar_items(texto)
        self.assertEqual(items["tapa_acceso"]["cantidad"], 2)
        self.assertEqual(items["marco"]["cantidad"], 1)  # "evita marco" no cuenta como marco
        self.assertIn("revoque", items)
        self.assertIn("flotante", items)


class TestPasosDelTanque(unittest.TestCase):

    def test_medida_valida_pasa_a_tapas_en_texto(self):
        ctx = entorno.contexto(_datos())
        estado = ct.recibir_medida(entorno.update_texto("180 200 150"), ctx)
        self.assertEqual(estado, TAPAS_INSPECCION)
        self.assertEqual(ctx.user_data["measure_t1"], "1.80, 2.00, 1.50")
        self.assertIn("¿Cuántas tapas de <b>INSPECCIÓN</b> tiene el tanque de <b>Cisterna</b>?", _enviados(ctx))

    def test_medida_invalida_se_vuelve_a_pedir(self):
        ctx = entorno.contexto(_datos())
        upd = entorno.update_texto("grande")
        self.assertEqual(ct.recibir_medida(upd, ctx), MEASURE)
        self.assertNotIn("measure_t1", ctx.user_data)
        self.assertIn("3 medidas", entorno.mensajes_enviados(ctx, upd))

    def test_litros_pregunta_el_material(self):
        ctx = entorno.contexto(_datos())
        ctx.user_data["tanque_actual"] = "t2"
        self.assertEqual(ct.recibir_medida(entorno.update_texto("1000 litros"), ctx), MEASURE)
        self.assertEqual(ct.boton_material(boton("md:t1:plastico"), ctx), MEASURE)  # botón de otro tanque
        self.assertEqual(ct.boton_material(boton("md:t2:plastico"), ctx), TAPAS_INSPECCION)
        self.assertEqual(ctx.user_data["measure_t2"], "1000 lts (plástico)")

    def _ctx_tapas(self, cubas=2):
        ctx = entorno.contexto(_datos(current_state=TAPAS_INSPECCION))
        ctx.user_data["tanques"][0]["cubas"] = cubas
        return ctx

    def test_dos_tapas_de_inspeccion_de_distinta_medida_y_acceso_por_cuba(self):
        ctx = self._ctx_tapas(cubas=2)
        ct.preguntar_texto(entorno.update_texto(None), ctx, "tapas_inspeccion")
        self.assertEqual(ct.boton_cantidad_tapas(boton("ti:2"), ctx), TAPAS_INSPECCION)
        insp = ct.recibir_tapa("tapas_inspeccion")
        self.assertIn("Tapa de inspección 1 de 2: ¿qué medida tiene? (30 40 50 60 80)", _enviados(ctx))
        self.assertEqual(insp(entorno.update_texto("30"), ctx), TAPAS_INSPECCION)
        self.assertIn("Tapa de inspección 2 de 2", _enviados(ctx))
        self.assertEqual(insp(entorno.update_texto("60"), ctx), TAPAS_ACCESO)
        self.assertEqual(ctx.user_data["tapas_inspeccion_t1"], "30, 60")
        acc = ct.recibir_tapa("tapas_acceso")
        self.assertIn("Tapa de <b>ACCESO</b> de la cuba de <b>ENTRADA DE AGUA</b>", _enviados(ctx))
        self.assertEqual(acc(entorno.update_texto("47"), ctx), TAPAS_ACCESO)
        self.assertIn("Tapa de <b>ACCESO</b> de la cuba del <b>CIEGO</b>", _enviados(ctx))
        self.assertEqual(acc(entorno.update_texto("56,5"), ctx), SEALING)
        self.assertEqual(ctx.user_data["tapas_acceso_t1"], "EA 47, C 56.5")
        self.assertEqual(ctx.user_data["state_stack"], [TAPAS_INSPECCION, TAPAS_ACCESO])

    def test_una_cuba_una_sola_tapa_de_acceso(self):
        ctx = self._ctx_tapas(cubas=1)
        ct.preguntar_texto(entorno.update_texto(None), ctx, "tapas_inspeccion")
        self.assertEqual(ct.boton_cantidad_tapas(boton("ti:0"), ctx), TAPAS_ACCESO)  # no tiene
        self.assertEqual(ctx.user_data["tapas_inspeccion_t1"], "No tiene")
        self.assertEqual(ct.recibir_tapa("tapas_acceso")(entorno.update_texto("48"), ctx), SEALING)
        self.assertEqual(ctx.user_data["tapas_acceso_t1"], "EA 48")
        self.assertNotIn("CIEGO", _enviados(ctx))

    def test_acceso_sin_tapa_en_una_o_en_las_dos_cubas(self):
        ctx = self._ctx_tapas(cubas=2)
        ct.preguntar_texto(entorno.update_texto(None), ctx, "tapas_acceso")
        ctx.user_data["current_state"] = TAPAS_ACCESO
        acc = ct.recibir_tapa("tapas_acceso")
        acc(entorno.update_texto("No tiene"), ctx)
        acc(entorno.update_texto("47"), ctx)
        self.assertEqual(ctx.user_data["tapas_acceso_t1"], "EA No tiene, C 47")
        ct.preguntar_texto(entorno.update_texto(None), ctx, "tapas_acceso")
        acc(entorno.update_texto("no"), ctx)
        acc(entorno.update_texto("ninguna"), ctx)
        self.assertEqual(ctx.user_data["tapas_acceso_t1"], "No tiene")

    def test_una_medida_por_respuesta(self):
        ctx = self._ctx_tapas()
        ct.preguntar_texto(entorno.update_texto(None), ctx, "tapas_inspeccion")
        insp = ct.recibir_tapa("tapas_inspeccion")
        upd = entorno.update_texto("30")
        self.assertEqual(insp(upd, ctx), TAPAS_INSPECCION)  # primero cuántas
        self.assertIn("Primero tocá cuántas", entorno.mensajes_enviados(ctx, upd))
        ct.boton_cantidad_tapas(boton("ti:2"), ctx)
        for escrito in ("30 60", "35", "no tiene"):
            upd = entorno.update_texto(escrito)
            self.assertEqual(insp(upd, ctx), TAPAS_INSPECCION, escrito)
        self.assertEqual(ctx.user_data["tapas_en_curso"]["medidas"], [])

    def test_atras_a_mitad_de_las_tapas_vuelve_a_empezar_el_paso(self):
        ctx = self._ctx_tapas()
        ctx.user_data["state_stack"] = [MEASURE]
        ct.preguntar_texto(entorno.update_texto(None), ctx, "tapas_inspeccion")
        ct.boton_cantidad_tapas(boton("ti:2"), ctx)
        ct.recibir_tapa("tapas_inspeccion")(entorno.update_texto("30"), ctx)
        self.assertEqual(ct.atras_tapas(boton("back"), ctx), TAPAS_INSPECCION)  # vuelve a "¿cuántas?"
        curso = ctx.user_data["tapas_en_curso"]
        self.assertEqual((curso["total"], curso["medidas"]), (None, []))  # lo cargado se descartó
        self.assertEqual(ct.atras_tapas(boton("back"), ctx), MEASURE)  # y de ahí, a la medida

    def test_sellado_y_despues_reparaciones(self):
        ctx = entorno.contexto(_datos(current_state=SEALING))
        self.assertEqual(ct.recibir_sellado(entorno.update_texto("masilla"), ctx), REPAIR)
        self.assertEqual(ctx.user_data["sealing_t1"], "masilla")
        self.assertIn("Reparaciones de <b>Cisterna</b>", _enviados(ctx))

    def test_tapas_solo_con_las_medidas_de_la_ayuda(self):
        ok = {("insp", "30 60"): "30, 60", ("insp", "30, 30"): "30, 30", ("insp", "No tiene"): "No tiene",
              ("insp", "ninguna"): "No tiene", ("acceso", "47 48 y 49"): "47, 48, 49",
              ("acceso", "49,5 / 56.5"): "49.5, 56.5", ("acceso", "49,50"): "49, 50",
              ("acceso", "55"): "55", ("acceso", "65"): "65",
              # de la planilla del dueño
              ("acceso", "39x49"): "39x49", ("acceso", "39 x 49 y 53,5"): "39x49, 53.5",
              ("acceso", "60 69"): "60, 69", ("acceso", "54x54"): "54", ("insp", "60x60"): "60"}
        for (campo, escrito), esperado in ok.items():
            self.assertEqual(campos.normalizar_tapas(campo, escrito), (esperado, None), escrito)
        for campo, escrito in (("insp", "35"), ("insp", "una de 60"), ("insp", "TITCEA 60"),
                               ("acceso", "4789"), ("acceso", "50125"), ("acceso", "57"),
                               ("acceso", "56.7"), ("acceso", "punta recortada 54"), ("insp", ""),
                               ("acceso", "40x50"), ("insp", "69")):
            valor, problema = campos.normalizar_tapas(campo, escrito)
            self.assertIsNone(valor, escrito)
            self.assertIn("Solo se aceptan", problema)

    def test_tapa_invalida_se_vuelve_a_pedir(self):
        ctx = entorno.contexto(_datos())
        ctx.user_data["current_state"] = TAPAS_ACCESO
        upd = entorno.update_texto("4789")
        self.assertEqual(ct.recibir_tapa("tapas_acceso")(upd, ctx), TAPAS_ACCESO)
        self.assertNotIn("tapas_acceso_t1", ctx.user_data)
        self.assertIn("4789 no es una medida válida", entorno.mensajes_enviados(ctx, upd))

    def test_todas_las_preguntas_tienen_atras(self):
        ctx = entorno.contexto(_datos())
        ct.preguntar_medida(entorno.update_texto(None), ctx)
        ct.preguntar_texto(entorno.update_texto(None), ctx, "tapas_inspeccion")
        ct.preguntar_texto(entorno.update_texto(None), ctx, "sealing")
        ct.preguntar_reparaciones(entorno.update_texto(None), ctx)
        ct.preguntar_contacto(entorno.update_texto(None), ctx)
        ct.preguntar_telefono(entorno.update_texto(None), ctx)
        for llamada in ctx.bot.send_message.call_args_list:
            markup = llamada.kwargs["reply_markup"]
            datos = [b.callback_data for fila in markup.inline_keyboard for b in fila]
            self.assertIn("back", datos, llamada.kwargs["text"])

    def test_boton_atras_generico(self):
        from bot.handlers.common import atras_boton
        ctx = entorno.contexto(_datos(state_stack=[MEASURE], current_state=TAPAS_INSPECCION))
        self.assertEqual(atras_boton(boton("back"), ctx), MEASURE)
        self.assertIn("Medida del tanque", _enviados(ctx))

    def test_atras_desde_tapas_vuelve_a_la_medida(self):
        ctx = entorno.contexto(_datos(state_stack=[MEASURE], current_state=TAPAS_INSPECCION,
                                      measure_t1="1.80, 2.00, 1.50"))
        self.assertEqual(ct.recibir_tapa("tapas_inspeccion")(entorno.update_texto("atrás"), ctx), MEASURE)
        self.assertIn("Medida del tanque", _enviados(ctx))


class TestMenuDeReparaciones(unittest.TestCase):

    def _ctx(self):
        return entorno.contexto(_datos(current_state=REPAIR, state_stack=[SEALING]))

    def test_carga_completa_y_pasa_a_las_fotos(self):
        ctx = self._ctx()
        rep = ct.boton_reparaciones
        pasos = ("g:tit", "m:60x60", "v:EA",                  # tapa de inspección
                 "g:tat", "t:oct", "m:53.5x56.5", "v:C",      # tapa de acceso octogonal
                 "g:tat", "t:pun", "v:EA",                    # punta recortada: una sola medida
                 "g:tmt", "m:48x48", "v:EA",                  # marco y tapa
                 "g:mat", "m:52", "v:C",                      # marco solo
                 "g:rev", "cara:LI", "cuba:EA", "ext:completo",  # revoque lateral izquierdo completo
                 "g:flo", "g:aut", "g:aut", "borrar",
                 "g:tat", "volver")                           # se arrepintió
        for paso in pasos:
            self.assertEqual(rep(boton(f"rp:t1:{paso}"), ctx), REPAIR, paso)
        self.assertEqual(rep(boton("rp:t1:listo"), ctx), REPAIR_PHOTOS)
        self.assertEqual(ctx.user_data["repairs_t1"],
                         "TITCEA 60x60, TATCC octogonal con parantes 53.5x56.5, "
                         "TATCEA punta recortada con parantes 54, TMTCEA 48x48, MATCC 52, "
                         "TCEA LI COMP, flotante, automático")
        self.assertEqual(ctx.user_data["state_stack"], [SEALING, REPAIR])
        self.assertIn("Mandá una foto de cada reparación", _enviados(ctx))
        self.assertNotIn("reparaciones_en_curso", ctx.user_data)

    def test_sin_reparaciones_va_a_sugerencias(self):
        ctx = self._ctx()
        ctx.user_data["fotos_reparaciones"] = {"t1": ["vieja"]}
        rep = ct.boton_reparaciones
        self.assertEqual(rep(boton("rp:t1:listo"), ctx), REPAIR)  # sin nada cargado no avanza
        self.assertEqual(rep(boton("rp:t1:no"), ctx), SUGGESTIONS)
        self.assertEqual(ctx.user_data["repairs_t1"], "No")
        self.assertNotIn("t1", ctx.user_data["fotos_reparaciones"])

    def test_medida_de_otro_tipo_no_se_toma(self):
        ctx = self._ctx()
        rep = ct.boton_reparaciones
        rep(boton("rp:t1:g:tat"), ctx)
        rep(boton("rp:t1:t:com"), ctx)
        rep(boton("rp:t1:m:69"), ctx)  # 69 es de evita marco, no de las comunes
        self.assertIsNone(ctx.user_data["reparaciones_en_curso"]["medida"])

    def test_revoque_con_parche(self):
        ctx = self._ctx()
        rep = ct.boton_reparaciones
        for paso in ("g:rev", "cara:LD", "cuba:C", "ext:parche"):
            self.assertEqual(rep(boton(f"rp:t1:{paso}"), ctx), REPAIR, paso)
        texto = ct.texto_reparaciones
        upd = entorno.update_texto("grande")
        self.assertEqual(texto(upd, ctx), REPAIR)  # medidas inválidas: se vuelven a pedir
        self.assertEqual(ctx.user_data["reparaciones_en_curso"]["lista"], [])
        self.assertIn("2 medidas del parche", entorno.mensajes_enviados(ctx, upd))
        self.assertEqual(texto(entorno.update_texto("1,5 x 1,5"), ctx), REPAIR)
        self.assertEqual(ctx.user_data["reparaciones_en_curso"]["lista"], ["TCC LD PARC 1.50x1.50"])
        menu = ctx.bot.send_message.call_args.kwargs["text"]  # vuelve al menú, con lo cargado en palabras
        self.assertIn("✅ Agregado: Revoque lateral derecho (ciego): parche de 1.50 x 1.50 m", menu)
        self.assertIn("• Revoque lateral derecho (ciego): parche de 1.50 x 1.50 m", menu)

    def test_revoque_pide_entrada_de_agua_si_hay_una_sola_cuba(self):
        ctx = self._ctx()
        rep = ct.boton_reparaciones
        rep(boton("rp:t1:g:rev"), ctx)
        upd = boton("rp:t1:cara:F")
        rep(upd, ctx)
        texto = upd.callback_query.edit_message_text.call_args.args[0]
        self.assertIn("una sola cuba", texto)
        self.assertIn("Entrada de agua", texto)

    def test_pantalla_del_parche_es_clara_y_sin_la_lista(self):
        ctx = self._ctx()
        rep = ct.boton_reparaciones
        for paso in ("g:tit", "m:30x30", "v:EA", "g:rev", "cara:LI", "cuba:EA"):
            rep(boton(f"rp:t1:{paso}"), ctx)
        upd = boton("rp:t1:ext:parche")
        rep(upd, ctx)
        texto = upd.callback_query.edit_message_text.call_args.args[0]
        self.assertIn("Revoque lateral izquierdo (entrada de agua)", texto)
        self.assertIn("<b>📏 ¿Cuánto mide el parche?</b>", texto)
        self.assertIn("Escribilo abajo", texto)
        self.assertNotIn("TITCEA", texto)       # lo cargado no se mezcla con la pregunta
        self.assertNotIn("Ya cargaste", texto)

    def test_menu_muestra_lo_cargado_en_palabras(self):
        ctx = self._ctx()
        rep = ct.boton_reparaciones
        for paso in ("g:tit", "m:30x30", "v:EA", "g:tat", "t:oct", "m:54x54", "v:C"):
            rep(boton(f"rp:t1:{paso}"), ctx)
        upd = boton("rp:t1:borrar")
        rep(upd, ctx)
        texto = upd.callback_query.edit_message_text.call_args.args[0]
        self.assertIn("↩️ Borrada: Tapa de acceso octogonal con parantes 54x54 (ciego)", texto)
        self.assertIn("• Tapa de inspección 30x30 (entrada de agua)", texto)
        self.assertNotIn("TITCEA", texto)
        self.assertEqual(ctx.user_data["reparaciones_en_curso"]["lista"], ["TITCEA 30x30"])  # se guarda en código

    def test_funciones_para_extract_reports(self):
        for d in ("TCEA F COMP", "TRC LI PARC 1.50x1.50", "THEA CF COMP", "tcc p parc 2.00x0.50",
                  "revoque lateral derecho"):
            self.assertTrue(campos.es_revoque(d), d)
        for d in ("TITCEA 30x30", "TATCC 47x47", "flotante", "MATCEA 50"):
            self.assertFalse(campos.es_revoque(d), d)
        self.assertEqual(campos.medidas_tanque_m("1.80, 2.00, 1.50"), [1.8, 2.0, 1.5])  # formato del bot
        self.assertEqual(campos.medidas_tanque_m("180 200 150"), [1.8, 2.0, 1.5])       # viejos, en cm
        self.assertEqual(campos.medidas_tanque_m(""), [])

    def test_legible(self):
        self.assertEqual(campos.legible("TMTRC 48x48"), "Tapa y marco de acceso 48x48 (ciego)")
        self.assertEqual(campos.legible("MATCEA 50"), "Marco solo 50 (entrada de agua)")
        self.assertEqual(campos.legible("TCEA P COMP"), "Revoque piso (entrada de agua): completo")
        self.assertEqual(campos.legible("TRC CF PARC 1.50x2.00"),
                         "Revoque contrafrente (ciego): parche de 1.50 x 2.00 m")
        self.assertEqual(campos.legible("flotante"), "Flotante")

    def test_revoque_saltear_pasos_no_agrega_nada(self):
        ctx = self._ctx()
        rep = ct.boton_reparaciones
        rep(boton("rp:t1:g:rev"), ctx)
        rep(boton("rp:t1:ext:completo"), ctx)  # sin cara ni cuba
        self.assertEqual(ctx.user_data["reparaciones_en_curso"]["lista"], [])

    def test_boton_de_otro_tanque_no_se_toma(self):
        ctx = self._ctx()
        upd = boton("rp:t2:g:flo")
        self.assertEqual(ct.boton_reparaciones(upd, ctx), REPAIR)
        upd.callback_query.answer.assert_called_with("Ese paso ya terminó.")
        self.assertNotIn("reparaciones_en_curso", ctx.user_data)

    def test_las_reparaciones_no_se_escriben(self):
        ctx = self._ctx()
        upd = entorno.update_texto("cambiar tapa de acceso")
        self.assertEqual(ct.texto_reparaciones(upd, ctx), REPAIR)
        self.assertNotIn("repairs_t1", ctx.user_data)
        self.assertIn("se cargan con los botones", _enviados(ctx))

    def test_volver_de_las_fotos_conserva_lo_cargado(self):
        ctx = self._ctx()
        ctx.user_data["repairs_t1"] = "TITCEA 60x60, flotante"
        ct.preguntar_reparaciones(entorno.update_texto(None), ctx)
        self.assertEqual(ctx.user_data["reparaciones_en_curso"]["lista"], ["TITCEA 60x60", "flotante"])

    def test_botones_del_menu_con_emoji_y_uno_por_fila(self):
        ctx = self._ctx()
        _, botones = ct._rep_pantalla(ctx)
        textos = [fila[0].text for fila in botones.inline_keyboard[:8]]
        self.assertEqual(textos, ["🚫 Sin reparaciones",  # arriba de todo
                                  "🔍 Tapa de inspección", "🚪 Tapa de acceso", "🔲 Tapa y marco de acceso",
                                  "🖼 Marco solo", "🧱 Revoque", "🛟 Flotante", "⚡ Automático"])
        self.assertTrue(all(len(fila) == 1 for fila in botones.inline_keyboard[:8]))

    def test_sin_reparaciones_no_aparece_con_algo_cargado(self):
        ctx = self._ctx()
        ct.boton_reparaciones(boton("rp:t1:g:flo"), ctx)
        _, botones = ct._rep_pantalla(ctx)
        datos = [b.callback_data for fila in botones.inline_keyboard for b in fila]
        self.assertNotIn("rp:t1:no", datos)
        self.assertEqual(botones.inline_keyboard[0][0].text, "🔍 Tapa de inspección")
        self.assertEqual(ct.boton_reparaciones(boton("rp:t1:no"), ctx), REPAIR)  # botón viejo
        self.assertEqual(ctx.user_data["reparaciones_en_curso"]["lista"], ["flotante"])

    def test_atras_en_el_pedido_de_fotos_vuelve_al_menu(self):
        from bot.handlers.fotos_reparaciones import handle_repair_photos_atras
        ctx = self._ctx()
        rep = ct.boton_reparaciones
        rep(boton("rp:t1:g:flo"), ctx)
        self.assertEqual(rep(boton("rp:t1:listo"), ctx), REPAIR_PHOTOS)
        self.assertEqual(handle_repair_photos_atras(boton("back"), ctx), REPAIR)
        self.assertEqual(ctx.user_data["reparaciones_en_curso"]["lista"], ["flotante"])  # conserva lo cargado
        self.assertNotIn("rep_fotos", ctx.user_data)

    def test_atras_vuelve_al_sellado(self):
        ctx = self._ctx()
        self.assertEqual(ct.boton_reparaciones(boton("back"), ctx), SEALING)
        self.assertIn("Indique cómo selló el tanque de <b>Cisterna</b>", _enviados(ctx))


class TestContacto(unittest.TestCase):

    def test_nombre_y_despues_telefono(self):
        ctx = entorno.contexto(_datos(current_state=CONTACT))
        self.assertEqual(ct.recibir_nombre(entorno.update_texto("Daniel"), ctx), CONTACT_PHONE)
        self.assertEqual(ct.recibir_telefono(entorno.update_texto("11 3545"), ctx), CONTACT_PHONE)  # incompleto
        self.assertEqual(ct.recibir_telefono(entorno.update_texto("11 3545 6067"), ctx), PHOTOS)
        self.assertEqual(ctx.user_data["contact"], "Daniel 1135456067")

    def test_juntos_como_antes(self):
        ctx = entorno.contexto(_datos(current_state=CONTACT))
        self.assertEqual(ct.recibir_nombre(entorno.update_texto("Daniel 1135456067"), ctx), PHOTOS)
        self.assertEqual(ctx.user_data["contact"], "Daniel 1135456067")

    def test_solo_numeros_no_es_nombre(self):
        ctx = entorno.contexto(_datos(current_state=CONTACT))
        self.assertEqual(ct.recibir_nombre(entorno.update_texto("1135456067"), ctx), CONTACT)

    def test_nombre_y_telefono_son_obligatorios(self):
        ctx = entorno.contexto(_datos(current_state=CONTACT))
        ct.preguntar_contacto(entorno.update_texto(None), ctx)
        markup = ctx.bot.send_message.call_args.kwargs["reply_markup"]
        datos = [b.callback_data for fila in markup.inline_keyboard for b in fila]
        self.assertEqual(datos, ["back"])  # sin "No había encargado"
        for escrito in ("no había", "-", "no"):
            self.assertEqual(ct.recibir_nombre(entorno.update_texto(escrito), ctx), CONTACT, escrito)
        self.assertEqual(ct.recibir_nombre(entorno.update_texto("Daniel"), ctx), CONTACT_PHONE)
        ct.preguntar_telefono(entorno.update_texto(None), ctx)
        markup = ctx.bot.send_message.call_args.kwargs["reply_markup"]
        self.assertEqual([b.callback_data for fila in markup.inline_keyboard for b in fila], ["back"])
        for escrito in ("no tiene", "no lo dio", "123"):
            self.assertEqual(ct.recibir_telefono(entorno.update_texto(escrito), ctx), CONTACT_PHONE, escrito)
        self.assertNotIn("contact", ctx.user_data)


class TestConversacion(unittest.TestCase):

    def test_botones_nuevos_no_se_toman_como_tanque(self):
        from telegram import Update
        from telegram.ext import CallbackQueryHandler
        from bot.conversation import build_conversation_handler
        from bot.states import TANK_TYPE
        handler = build_conversation_handler()
        update = MagicMock(spec=Update)
        fallback = handler.fallbacks[0]  # botones vencidos (el otro es ATRAS)
        for data in ("rp:t1:g:tit", "md:main:plastico", "ct:sin", "tp:main:insp:m:60x60"):
            update.callback_query.data = data
            for h in handler.states[TANK_TYPE]:
                if isinstance(h, CallbackQueryHandler):
                    self.assertFalse(h.check_update(update), data)
            self.assertTrue(fallback.check_update(update), data)


class TestElegirTanque(unittest.TestCase):

    def test_qr_pide_primero_la_hora(self):
        from unittest.mock import patch
        from bot.services import qr_service
        from bot.states import START_TIME
        ctx = entorno.contexto({"state_stack": [], "service": "Limpieza y Reparacion de Tanques"})
        upd = entorno.update_foto("qr")
        with patch.object(qr_service, "_decode_qr_opencv", return_value="1234567|Av. Siempre Viva 1|99|LIMPIEZA"):
            self.assertEqual(qr_service.scan_qr(upd, ctx), START_TIME)
        self.assertIn("¿A qué hora empezaste el trabajo?", _enviados(ctx))

    def test_despues_de_la_hora_pregunta_los_cuerpos(self):
        from bot.handlers.shared import guardar_hora_fin
        ctx = entorno.contexto({"state_stack": [], "service": "Limpieza y Reparacion de Tanques",
                                "start_time": "08:00"})
        self.assertEqual(guardar_hora_fin(entorno.update_texto("10:00"), ctx, "10:00"), CUERPOS)
        self.assertIn("¿Cuántos cuerpos tiene el edificio?", _enviados(ctx))

    def test_boton_viejo_no_es_un_tanque(self):
        ctx = entorno.contexto({"state_stack": [], "current_state": TANK_TYPE})
        for data in ("input_voice", "RESERVA", "tq:PILETA"):
            upd = boton(data)
            self.assertEqual(ct.boton_tipo_tanque(upd, ctx), TANK_TYPE, data)
            upd.callback_query.answer.assert_called_with("Ese paso ya terminó.")
        self.assertEqual(ctx.user_data.get("tanques", []), [])


class TestVariosTanques(unittest.TestCase):
    """Edificios de más de un cuerpo y con más de un tanque del mismo tipo."""

    def setUp(self):
        self.ctx = entorno.contexto({"state_stack": [], "service": "Limpieza y Reparacion de Tanques",
                                     "start_time": "08:00", "end_time": "10:00", "current_state": CUERPOS})

    def _toca(self, data, handler):
        return handler(boton(data), self.ctx)

    def _escribe(self, texto, handler):
        return handler(entorno.update_texto(texto), self.ctx)

    def _cargar_tanque(self, tipo, cuerpo=None, reparaciones=("g:flo",), medida="1.80 2 1.50", cubas=2):
        """Elige el tipo (el cuerpo y las cubas), carga los pasos y llega a "¿hay otro tanque?"."""
        self.assertEqual(self._toca(f"tq:{tipo}", ct.boton_tipo_tanque), TANK_CUERPO if cuerpo else TANK_CUBAS)
        if cuerpo:
            self.assertEqual(self._toca(f"cp:{cuerpo}", ct.boton_cuerpo_tanque), TANK_CUBAS)
        self.assertEqual(self._toca(f"cb:{cubas}", ct.boton_cubas), MEASURE)
        tid = self.ctx.user_data["tanque_actual"]
        self._escribe(medida, ct.recibir_medida)
        self._toca("ti:1", ct.boton_cantidad_tapas)
        self._escribe("60", ct.recibir_tapa("tapas_inspeccion"))
        for _ in range(cubas):  # una tapa de acceso por cuba
            self._escribe("No tiene", ct.recibir_tapa("tapas_acceso"))
        self.assertEqual(self._escribe("masilla", ct.recibir_sellado), REPAIR)
        for paso in reparaciones:
            self._toca(f"rp:{tid}:{paso}", ct.boton_reparaciones)
        self._toca(f"rp:{tid}:no" if not reparaciones else f"rp:{tid}:listo", ct.boton_reparaciones)
        if reparaciones:  # pide las fotos: se saltean acá (las prueba test_fotos_reparaciones)
            from bot.handlers import fotos_reparaciones as fr
            fr._continuar(entorno.update_texto(None), self.ctx)
        self.assertEqual(self._escribe("nada", ct.recibir_sugerencias), OTRO_TANQUE)
        return tid

    def test_un_cuerpo_cisterna_y_dos_reservas(self):
        from bot.services import tanques_reporte as tq
        self.assertEqual(self._toca("cu:1", ct.boton_cuerpos), TANK_TYPE)
        t1 = self._cargar_tanque("CISTERNA")
        self.assertEqual(self._toca("ot:si", ct.boton_otro_tanque), TANK_TYPE)
        t2 = self._cargar_tanque("RESERVA", reparaciones=("g:rev", "cara:LI", "cuba:EA", "ext:completo"))
        self._toca("ot:si", ct.boton_otro_tanque)
        t3 = self._cargar_tanque("RESERVA", reparaciones=())
        self.assertEqual(self._toca("ot:no", ct.boton_otro_tanque), CONTACT)
        ud = self.ctx.user_data
        self.assertEqual([tq.nombre(ud, t) for t in (t1, t2, t3)], ["Cisterna", "Reserva 1", "Reserva 2"])
        self.assertEqual(ud[f"repairs_{t2}"], "TREA LI COMP")  # el código usa el tipo del tanque
        self.assertEqual(ud[f"repairs_{t3}"], "No")
        self.assertEqual(ud[f"measure_{t3}"], "1.80, 2.00, 1.50")

    def test_dos_cuerpos_cisterna_compartida_y_una_reserva_en_cada_uno(self):
        from bot.services import tanques_reporte as tq
        from bot.services.email_service import _build_body
        self.assertEqual(self._toca("cu:2", ct.boton_cuerpos), TANK_TYPE)
        self._cargar_tanque("CISTERNA", "frente", reparaciones=("g:rev", "cara:P", "cuba:EA", "ext:completo"))
        self._toca("ot:si", ct.boton_otro_tanque)
        self._cargar_tanque("RESERVA", "frente")
        self._toca("ot:si", ct.boton_otro_tanque)
        self._cargar_tanque("RESERVA", "fondo", reparaciones=("g:tat", "t:com", "m:47x47", "v:C"))
        self._toca("ot:no", ct.boton_otro_tanque)
        ud = self.ctx.user_data
        nombres = [tq.nombre(ud, t["id"]) for t in tq.lista(ud)]
        self.assertEqual(nombres, ["Cisterna (frente)", "Reserva 1 (frente)", "Reserva 2 (fondo)"])
        body = _build_body(ud)
        self.assertIn("Cuerpos del edificio: 2", body)
        self.assertIn("Reparaciones Cisterna (frente): TCEA P COMP", body)
        self.assertIn("Reparaciones Reserva 1 (frente): flotante", body)
        self.assertIn("Reparaciones Reserva 2 (fondo): TATRC 47x47", body)

    def test_dos_cisternas(self):
        from bot.services import tanques_reporte as tq
        self._toca("cu:1", ct.boton_cuerpos)
        self._cargar_tanque("CISTERNA")
        self._toca("ot:si", ct.boton_otro_tanque)
        self._cargar_tanque("CISTERNA")
        ud = self.ctx.user_data
        self.assertEqual([tq.nombre(ud, t["id"]) for t in tq.lista(ud)], ["Cisterna 1", "Cisterna 2"])

    def test_atras_desde_la_medida_del_segundo_tanque_lo_descarta(self):
        from bot.services import tanques_reporte as tq
        self._toca("cu:2", ct.boton_cuerpos)
        t1 = self._cargar_tanque("CISTERNA", "frente")
        self._toca("ot:si", ct.boton_otro_tanque)
        self._toca("tq:RESERVA", ct.boton_tipo_tanque)
        self._toca("cp:fondo", ct.boton_cuerpo_tanque)
        self._toca("cb:2", ct.boton_cubas)
        self.assertEqual(len(tq.lista(self.ctx.user_data)), 2)
        # ATRAS desde la medida de la reserva: vuelve a las cubas, y la reserva vacía se descarta
        self.assertEqual(self._escribe("atrás", ct.recibir_medida), TANK_CUBAS)
        self.assertEqual([t["id"] for t in tq.lista(self.ctx.user_data)], [t1])
        self.assertIn("¿Cuántas cubas tiene este tanque de <b>Reserva</b> (fondo)?", _enviados(self.ctx))
        self.assertEqual(self._toca("back", atras_boton), TANK_CUERPO)
        self.assertEqual(self._toca("back", atras_boton),
                         TANK_TYPE)
        self.assertEqual(self._toca("back", atras_boton),
                         OTRO_TANQUE)
        # ATRAS otra vez: a las sugerencias de la cisterna, en la cisterna
        self.assertEqual(self._toca("back", atras_boton),
                         SUGGESTIONS)
        self.assertEqual(self.ctx.user_data["tanque_actual"], t1)
        self.assertIn("sugerencias p/ la próx limpieza para <b>Cisterna</b> (frente)", _enviados(self.ctx))
        self.assertNotIn("este tanque de ?", _enviados(self.ctx))

    def test_un_cuerpo_no_pregunta_el_cuerpo(self):
        self._toca("cu:1", ct.boton_cuerpos)
        self.assertEqual(self._toca("tq:RESERVA", ct.boton_tipo_tanque), TANK_CUBAS)
        self.assertNotIn("¿De qué cuerpo", _enviados(self.ctx))

    def test_una_cuba_no_pregunta_entrada_de_agua_o_ciego(self):
        self._toca("cu:1", ct.boton_cuerpos)
        tid = self._cargar_tanque("RESERVA", cubas=1, reparaciones=(
            "g:tit", "m:60x60",                     # tapa de inspección: sin preguntar EA/ciego
            "g:tat", "t:pun",                       # punta recortada (una sola medida)
            "g:rev", "cara:F", "ext:completo"))     # revoque: sin preguntar la cuba
        self.assertEqual(self.ctx.user_data[f"repairs_{tid}"],
                         "TITREA 60x60, TATREA punta recortada con parantes 54, TREA F COMP")
        enviados = _enviados(self.ctx)
        self.assertNotIn("¿Es la de la entrada de agua o la del ciego?", enviados)

    def test_dos_cubas_pregunta_entrada_de_agua_o_ciego(self):
        self._toca("cu:1", ct.boton_cuerpos)
        tid = self._cargar_tanque("CISTERNA", cubas=2, reparaciones=("g:tit", "m:60x60", "v:C"))
        self.assertEqual(self.ctx.user_data[f"repairs_{tid}"], "TITCC 60x60")

    def test_cubas_en_el_mail_y_en_el_resumen(self):
        from bot.services.email_service import _build_body
        from bot.handlers.final_summary import build_full_summary
        self._toca("cu:1", ct.boton_cuerpos)
        self._cargar_tanque("CISTERNA", cubas=2)
        self._toca("ot:si", ct.boton_otro_tanque)
        self._cargar_tanque("RESERVA", cubas=1)
        body = _build_body(self.ctx.user_data)
        self.assertIn("Cubas Cisterna: 2", body)
        self.assertIn("Cubas Reserva: 1", body)
        self.assertIn("• Cubas: 1", build_full_summary(self.ctx.user_data))

    def test_boton_de_cubas_viejo_no_crea_tanques(self):
        from bot.services import tanques_reporte as tq
        self._toca("cu:1", ct.boton_cuerpos)
        self._cargar_tanque("CISTERNA")
        upd = boton("cb:1")
        self.assertEqual(ct.boton_cubas(upd, self.ctx), OTRO_TANQUE)
        upd.callback_query.answer.assert_called_with("Ese paso ya terminó.")
        self.assertEqual(len(tq.lista(self.ctx.user_data)), 1)

    def test_cuerpos_con_los_nombres_del_dueno(self):
        self._toca("cu:3", ct.boton_cuerpos)
        self._toca("tq:RESERVA", ct.boton_tipo_tanque)
        markup = self.ctx.bot.send_message.call_args.kwargs["reply_markup"]
        textos = [b.text for fila in markup.inline_keyboard for b in fila]
        self.assertEqual(textos, ["Frente", "Fondo", "Izquierda", "Derecha", "⬅️ ATRAS"])


class TestModificarAlgo(unittest.TestCase):

    def _ctx(self):
        from bot.states import FINAL_SUMMARY, PHOTOS as FOTOS
        return entorno.contexto(_datos(
            current_state=FINAL_SUMMARY, state_stack=[MEASURE, SEALING, FOTOS],
            tanques=[{"id": "t1", "tipo": "CISTERNA", "cuerpo": None}],
            measure_t1="1.80, 2.00, 1.50", sealing_t1="masilla", repairs_t1="TITCEA 60x60",
            suggestions_t1="nada", contact="Daniel 1135456067", start_time="08:00", end_time="10:00",
            photos=["a", "b", "c"]))

    def _boton(self, data, ctx):
        from bot.handlers.final_summary import handle_final_summary_callback
        return handle_final_summary_callback(boton(data), ctx)

    def test_menu_muestra_los_tanques_cargados(self):
        from bot.handlers.final_summary import _menu
        _, botones = _menu(self._ctx().user_data, "menu")
        datos = [b.callback_data for fila in botones.inline_keyboard for b in fila]
        self.assertIn("ed:t:t1", datos)
        self.assertNotIn("ed:t:t2", datos)  # Reserva no se cargó

    def test_modificar_la_medida_vuelve_al_resumen(self):
        from bot.states import FINAL_SUMMARY
        ctx = self._ctx()
        self.assertEqual(self._boton("final_edit", ctx), FINAL_SUMMARY)
        self.assertEqual(self._boton("ed:t:t1", ctx), FINAL_SUMMARY)
        self.assertEqual(self._boton("ed:f:t1:measure", ctx), MEASURE)
        self.assertEqual(ct.recibir_medida(entorno.update_texto("grande"), ctx), MEASURE)  # sigue validando
        self.assertEqual(ct.recibir_medida(entorno.update_texto("150 150 150"), ctx), FINAL_SUMMARY)
        self.assertEqual(ctx.user_data["measure_t1"], "1.50, 1.50, 1.50")
        self.assertNotIn("editando", ctx.user_data)
        self.assertIn("RESUMEN COMPLETO", _enviados(ctx))

    def test_modificar_reparaciones_usa_el_menu_y_las_fotos(self):
        from bot.states import FINAL_SUMMARY
        ctx = self._ctx()
        self.assertEqual(self._boton("ed:f:t1:repairs", ctx), REPAIR)
        rep = ct.boton_reparaciones
        self.assertEqual(ctx.user_data["reparaciones_en_curso"]["lista"], ["TITCEA 60x60"])  # arranca con lo cargado
        rep(boton("rp:t1:g:flo"), ctx)
        self.assertEqual(rep(boton("rp:t1:listo"), ctx), REPAIR_PHOTOS)
        self.assertEqual(ctx.user_data["repairs_t1"], "TITCEA 60x60, flotante")

    def test_modificar_reparaciones_a_ninguna_vuelve_al_resumen(self):
        from bot.states import FINAL_SUMMARY
        ctx = self._ctx()
        self._boton("ed:f:t1:repairs", ctx)  # arranca con "TITCEA 60x60" cargada
        rep = ct.boton_reparaciones
        self.assertEqual(rep(boton("rp:t1:no"), ctx), REPAIR)  # no borra lo cargado de golpe
        rep(boton("rp:t1:borrar"), ctx)
        self.assertEqual(rep(boton("rp:t1:no"), ctx), FINAL_SUMMARY)
        self.assertEqual(ctx.user_data["repairs_t1"], "No")

    def test_atras_en_la_primera_pregunta_vuelve_al_resumen_sin_borrar(self):
        from bot.states import FINAL_SUMMARY
        ctx = self._ctx()
        self._boton("ed:f:t1:sealing", ctx)
        self.assertEqual(ct.recibir_sellado(entorno.update_texto("atras"), ctx), FINAL_SUMMARY)
        self.assertEqual(ctx.user_data["sealing_t1"], "masilla")

    def test_modificar_sugerencias_y_contacto(self):
        from bot.states import FINAL_SUMMARY
        get_suggestions_main = ct.recibir_sugerencias
        ctx = self._ctx()
        self.assertEqual(self._boton("ed:f:t1:suggestions", ctx), SUGGESTIONS)
        self.assertEqual(get_suggestions_main(entorno.update_texto("limpiar antes"), ctx), FINAL_SUMMARY)
        self.assertEqual(ctx.user_data["suggestions_t1"], "limpiar antes")
        self.assertEqual(self._boton("ed:c", ctx), CONTACT)
        self.assertEqual(ct.recibir_nombre(entorno.update_texto("Ana"), ctx), CONTACT_PHONE)
        self.assertEqual(ct.recibir_telefono(entorno.update_texto("2214567890"), ctx), FINAL_SUMMARY)
        self.assertEqual(ctx.user_data["contact"], "Ana 2214567890")

    def test_modificar_la_hora_con_los_botones(self):
        from bot.states import FINAL_SUMMARY, START_TIME
        from bot.handlers.shared import handle_hora_boton
        ctx = self._ctx()
        self.assertEqual(self._boton("ed:h:inicio", ctx), START_TIME)
        handle_hora_boton(boton("hora:inicio:h:09"), ctx)
        self.assertEqual(handle_hora_boton(boton("hora:inicio:m:09:15"), ctx), FINAL_SUMMARY)
        self.assertEqual(ctx.user_data["start_time"], "09:15")
        self.assertEqual(ctx.user_data["end_time"], "10:00")

    def test_modificar_las_cubas(self):
        ctx = self._ctx()
        self.assertEqual(self._boton("ed:cb:t1", ctx), TANK_CUBAS)
        self.assertIn("¿Cuántas cubas tiene este tanque de <b>Cisterna</b>?", _enviados(ctx))
        self.assertEqual(ct.boton_cubas(boton("cb:1"), ctx), FINAL_SUMMARY)
        self.assertEqual(ctx.user_data["tanques"][0]["cubas"], 1)
        self.assertEqual(len(ctx.user_data["tanques"]), 1)  # no crea otro tanque

    def test_texto_en_el_resumen_pide_usar_los_botones(self):
        from bot.states import FINAL_SUMMARY
        from bot.handlers.final_summary import handle_final_text
        ctx = self._ctx()
        upd = entorno.update_texto("cambiar sellado a burlete")
        self.assertEqual(handle_final_text(upd, ctx), FINAL_SUMMARY)
        self.assertEqual(ctx.user_data["sealing_t1"], "masilla")


if __name__ == "__main__":
    unittest.main()
