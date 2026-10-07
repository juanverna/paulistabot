import unittest
from unittest.mock import MagicMock

from tests import entorno
entorno.preparar()

from bot.services import campos
from bot.services.items_reparacion import detectar_items, problemas_de_reparaciones
from bot.states import (MEASURE_MAIN, TAPAS_INSPECCION_MAIN, TAPAS_ACCESO_MAIN, SEALING_MAIN,
                        REPAIR_MAIN, REPAIR_PHOTOS, SUGGESTIONS_MAIN, MEASURE_ALT1,
                        TAPAS_INSPECCION_ALT1, CONTACT, CONTACT_PHONE, PHOTOS)
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
        self.assertEqual(campos.reparacion("rev", variante="EA", cara="frente"),
                         "revoque frente entrada de agua completo")
        self.assertEqual(campos.reparacion("rev", variante="C", cara="li", parche="1.50x1.50"),
                         "revoque lateral izquierdo ciego parche 1.50x1.50 m")
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
        for cara in campos.CARAS_REVOQUE:
            for cuba in campos.CUBAS:
                for parche in ("", "2.00x2.00"):
                    texto = campos.reparacion("rev", variante=cuba, cara=cara, parche=parche)
                    self.assertIsNone(problemas_de_reparaciones(texto, "CISTERNA"), texto)
                    self.assertEqual(list(detectar_items(texto)), ["revoque"], texto)

    def test_cubas_del_revoque_no_duplican_la_tapa(self):
        # "entrada de agua" y "ciego" de dos revoques no son dos tapas de acceso
        texto = ("TATCEA 47x47, revoque frente entrada de agua completo, "
                 "revoque piso ciego parche 1.00x1.00 m")
        self.assertEqual(detectar_items(texto)["tapa_acceso"]["cantidad"], 1)
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
        estado = ct.recibir_medida("main")(entorno.update_texto("180 200 150"), ctx)
        self.assertEqual(estado, TAPAS_INSPECCION_MAIN)
        self.assertEqual(ctx.user_data["measure_main"], "1.80, 2.00, 1.50")
        self.assertIn("Indique TAPAS INSPECCIÓN (30 40 50 60 80):", _enviados(ctx))

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

    def test_tapas_y_sellado_como_antes(self):
        ctx = entorno.contexto(_datos())
        self.assertEqual(ct.recibir_texto("main", "insp")(entorno.update_texto("60"), ctx), TAPAS_ACCESO_MAIN)
        self.assertEqual(ct.recibir_texto("main", "acceso")(entorno.update_texto("56,5"), ctx), SEALING_MAIN)
        self.assertEqual(ct.recibir_texto("main", "sellado")(entorno.update_texto("masilla"), ctx), REPAIR_MAIN)
        self.assertEqual(ctx.user_data["tapas_inspeccion_main"], "60")
        self.assertEqual(ctx.user_data["tapas_acceso_main"], "56.5")  # la coma decimal se normaliza
        self.assertEqual(ctx.user_data["sealing_main"], "masilla")
        enviados = _enviados(ctx)
        self.assertIn("Indique TAPAS ACCESO (4789/50125/49.5 56 56.5 58 54 51.5 62 65):", enviados)
        self.assertIn("Indique cómo selló el tanque de <b>Cisterna</b> (EJ: masilla, burlete):", enviados)
        self.assertIn("Reparaciones de <b>Cisterna</b>", enviados)
        self.assertEqual(ctx.user_data["state_stack"], [TAPAS_INSPECCION_MAIN, TAPAS_ACCESO_MAIN, SEALING_MAIN])

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
        upd = entorno.update_texto("4789")
        self.assertEqual(ct.recibir_texto("main", "acceso")(upd, ctx), TAPAS_ACCESO_MAIN)
        self.assertNotIn("tapas_acceso_main", ctx.user_data)
        self.assertIn("4789 no es una medida válida", entorno.mensajes_enviados(ctx, upd))

    def test_todas_las_preguntas_tienen_atras(self):
        ctx = entorno.contexto(_datos())
        ct.preguntar_medida(entorno.update_texto(None), ctx, "main")
        ct.preguntar_texto(entorno.update_texto(None), ctx, "main", "insp")
        ct.preguntar_texto(entorno.update_texto(None), ctx, "main", "sellado")
        ct.preguntar_reparaciones(entorno.update_texto(None), ctx, "main")
        ct.preguntar_contacto(entorno.update_texto(None), ctx)
        ct.preguntar_telefono(entorno.update_texto(None), ctx)
        for llamada in ctx.bot.send_message.call_args_list:
            markup = llamada.kwargs["reply_markup"]
            datos = [b.callback_data for fila in markup.inline_keyboard for b in fila]
            self.assertIn("back", datos, llamada.kwargs["text"])

    def test_boton_atras_generico(self):
        from bot.handlers.common import atras_boton
        ctx = entorno.contexto(_datos(state_stack=[MEASURE_MAIN], current_state=TAPAS_INSPECCION_MAIN))
        self.assertEqual(atras_boton(boton("back"), ctx), MEASURE_MAIN)
        self.assertIn("Medida del tanque", _enviados(ctx))

    def test_atras_desde_tapas_vuelve_a_la_medida(self):
        ctx = entorno.contexto(_datos(state_stack=[MEASURE_MAIN], current_state=TAPAS_INSPECCION_MAIN,
                                      measure_main="1.80, 2.00, 1.50"))
        self.assertEqual(ct.recibir_texto("main", "insp")(entorno.update_texto("atrás"), ctx), MEASURE_MAIN)
        self.assertIn("Medida del tanque", _enviados(ctx))


class TestMenuDeReparaciones(unittest.TestCase):

    def _ctx(self):
        return entorno.contexto(_datos(current_state=REPAIR_MAIN, state_stack=[SEALING_MAIN]))

    def test_carga_completa_y_pasa_a_las_fotos(self):
        ctx = self._ctx()
        rep = ct.boton_reparaciones("main")
        pasos = ("g:tit", "m:60x60", "v:EA",                  # tapa de inspección
                 "g:tat", "t:oct", "m:53.5x56.5", "v:C",      # tapa de acceso octogonal
                 "g:tat", "t:pun", "v:EA",                    # punta recortada: una sola medida
                 "g:tmt", "m:48x48", "v:EA",                  # marco y tapa
                 "g:mat", "m:52", "v:C",                      # marco solo
                 "g:rev", "cara:li", "cuba:EA", "ext:completo",  # revoque lateral izquierdo completo
                 "g:flo", "g:aut", "g:aut", "borrar",
                 "g:tat", "volver")                           # se arrepintió
        for paso in pasos:
            self.assertEqual(rep(boton(f"rp:main:{paso}"), ctx), REPAIR_MAIN, paso)
        self.assertEqual(rep(boton("rp:main:listo"), ctx), REPAIR_PHOTOS)
        self.assertEqual(ctx.user_data["repairs"],
                         "TITCEA 60x60, TATCC octogonal con parantes 53.5x56.5, "
                         "TATCEA punta recortada con parantes 54, TMTCEA 48x48, MATCC 52, "
                         "revoque lateral izquierdo entrada de agua completo, flotante, automático")
        self.assertEqual(ctx.user_data["state_stack"], [SEALING_MAIN, REPAIR_MAIN])
        self.assertIn("Mandá una foto de cada reparación", _enviados(ctx))
        self.assertNotIn("reparaciones_en_curso", ctx.user_data)

    def test_sin_reparaciones_va_a_sugerencias(self):
        ctx = self._ctx()
        ctx.user_data["fotos_reparaciones"] = {"main": ["vieja"]}
        rep = ct.boton_reparaciones("main")
        self.assertEqual(rep(boton("rp:main:listo"), ctx), REPAIR_MAIN)  # sin nada cargado no avanza
        self.assertEqual(rep(boton("rp:main:no"), ctx), SUGGESTIONS_MAIN)
        self.assertEqual(ctx.user_data["repairs"], "No")
        self.assertNotIn("main", ctx.user_data["fotos_reparaciones"])

    def test_medida_de_otro_tipo_no_se_toma(self):
        ctx = self._ctx()
        rep = ct.boton_reparaciones("main")
        rep(boton("rp:main:g:tat"), ctx)
        rep(boton("rp:main:t:com"), ctx)
        rep(boton("rp:main:m:69"), ctx)  # 69 es de evita marco, no de las comunes
        self.assertIsNone(ctx.user_data["reparaciones_en_curso"]["medida"])

    def test_revoque_con_parche(self):
        ctx = self._ctx()
        rep = ct.boton_reparaciones("main")
        for paso in ("g:rev", "cara:ld", "cuba:C", "ext:parche"):
            self.assertEqual(rep(boton(f"rp:main:{paso}"), ctx), REPAIR_MAIN, paso)
        texto = ct.texto_reparaciones("main")
        upd = entorno.update_texto("grande")
        self.assertEqual(texto(upd, ctx), REPAIR_MAIN)  # medidas inválidas: se vuelven a pedir
        self.assertEqual(ctx.user_data["reparaciones_en_curso"]["lista"], [])
        self.assertIn("2 medidas del parche", entorno.mensajes_enviados(ctx, upd))
        self.assertEqual(texto(entorno.update_texto("1,5 x 1,5"), ctx), REPAIR_MAIN)
        self.assertEqual(ctx.user_data["reparaciones_en_curso"]["lista"],
                         ["revoque lateral derecho ciego parche 1.50x1.50 m"])
        menu = ctx.bot.send_message.call_args.kwargs["text"]  # vuelve al menú, con lo cargado en palabras
        self.assertIn("✅ Agregado: Revoque lateral derecho (ciego): parche de 1.50 x 1.50 m", menu)
        self.assertIn("• Revoque lateral derecho (ciego): parche de 1.50 x 1.50 m", menu)

    def test_revoque_pide_entrada_de_agua_si_hay_una_sola_cuba(self):
        ctx = self._ctx()
        rep = ct.boton_reparaciones("main")
        rep(boton("rp:main:g:rev"), ctx)
        upd = boton("rp:main:cara:frente")
        rep(upd, ctx)
        texto = upd.callback_query.edit_message_text.call_args.args[0]
        self.assertIn("una sola cuba", texto)
        self.assertIn("Entrada de agua", texto)

    def test_pantalla_del_parche_es_clara_y_sin_la_lista(self):
        ctx = self._ctx()
        rep = ct.boton_reparaciones("main")
        for paso in ("g:tit", "m:30x30", "v:EA", "g:rev", "cara:li", "cuba:EA"):
            rep(boton(f"rp:main:{paso}"), ctx)
        upd = boton("rp:main:ext:parche")
        rep(upd, ctx)
        texto = upd.callback_query.edit_message_text.call_args.args[0]
        self.assertIn("Revoque lateral izquierdo (entrada de agua)", texto)
        self.assertIn("<b>📏 ¿Cuánto mide el parche?</b>", texto)
        self.assertIn("Escribilo abajo", texto)
        self.assertNotIn("TITCEA", texto)       # lo cargado no se mezcla con la pregunta
        self.assertNotIn("Ya cargaste", texto)

    def test_menu_muestra_lo_cargado_en_palabras(self):
        ctx = self._ctx()
        rep = ct.boton_reparaciones("main")
        for paso in ("g:tit", "m:30x30", "v:EA", "g:tat", "t:oct", "m:54x54", "v:C"):
            rep(boton(f"rp:main:{paso}"), ctx)
        upd = boton("rp:main:borrar")
        rep(upd, ctx)
        texto = upd.callback_query.edit_message_text.call_args.args[0]
        self.assertIn("↩️ Borrada: Tapa de acceso octogonal con parantes 54x54 (ciego)", texto)
        self.assertIn("• Tapa de inspección 30x30 (entrada de agua)", texto)
        self.assertNotIn("TITCEA", texto)
        self.assertEqual(ctx.user_data["reparaciones_en_curso"]["lista"], ["TITCEA 30x30"])  # se guarda en código

    def test_legible(self):
        self.assertEqual(campos.legible("TMTRC 48x48"), "Tapa y marco de acceso 48x48 (ciego)")
        self.assertEqual(campos.legible("MATCEA 50"), "Marco solo 50 (entrada de agua)")
        self.assertEqual(campos.legible("revoque piso entrada de agua completo"),
                         "Revoque piso (entrada de agua): completo")
        self.assertEqual(campos.legible("flotante"), "Flotante")

    def test_revoque_saltear_pasos_no_agrega_nada(self):
        ctx = self._ctx()
        rep = ct.boton_reparaciones("main")
        rep(boton("rp:main:g:rev"), ctx)
        rep(boton("rp:main:ext:completo"), ctx)  # sin cara ni cuba
        self.assertEqual(ctx.user_data["reparaciones_en_curso"]["lista"], [])

    def test_boton_de_otro_tanque_no_se_toma(self):
        ctx = self._ctx()
        upd = boton("rp:alt1:g:flo")
        self.assertEqual(ct.boton_reparaciones("main")(upd, ctx), REPAIR_MAIN)
        upd.callback_query.answer.assert_called_with("Ese paso ya terminó.")
        self.assertNotIn("reparaciones_en_curso", ctx.user_data)

    def test_las_reparaciones_no_se_escriben(self):
        ctx = self._ctx()
        upd = entorno.update_texto("cambiar tapa de acceso")
        self.assertEqual(ct.texto_reparaciones("main")(upd, ctx), REPAIR_MAIN)
        self.assertNotIn("repairs", ctx.user_data)
        self.assertIn("se cargan con los botones", _enviados(ctx))

    def test_volver_de_las_fotos_conserva_lo_cargado(self):
        ctx = self._ctx()
        ctx.user_data["repairs"] = "TITCEA 60x60, flotante"
        ct.preguntar_reparaciones(entorno.update_texto(None), ctx, "main")
        self.assertEqual(ctx.user_data["reparaciones_en_curso"]["lista"], ["TITCEA 60x60", "flotante"])

    def test_botones_del_menu_con_emoji_y_uno_por_fila(self):
        ctx = self._ctx()
        _, botones = ct._rep_pantalla(ctx, "main")
        textos = [fila[0].text for fila in botones.inline_keyboard[:8]]
        self.assertEqual(textos, ["🚫 Sin reparaciones",  # arriba de todo
                                  "🔍 Tapa de inspección", "🚪 Tapa de acceso", "🔲 Tapa y marco de acceso",
                                  "🖼 Marco solo", "🧱 Revoque", "🛟 Flotante", "⚡ Automático"])
        self.assertTrue(all(len(fila) == 1 for fila in botones.inline_keyboard[:8]))

    def test_sin_reparaciones_no_aparece_con_algo_cargado(self):
        ctx = self._ctx()
        ct.boton_reparaciones("main")(boton("rp:main:g:flo"), ctx)
        _, botones = ct._rep_pantalla(ctx, "main")
        datos = [b.callback_data for fila in botones.inline_keyboard for b in fila]
        self.assertNotIn("rp:main:no", datos)
        self.assertEqual(botones.inline_keyboard[0][0].text, "🔍 Tapa de inspección")
        self.assertEqual(ct.boton_reparaciones("main")(boton("rp:main:no"), ctx), REPAIR_MAIN)  # botón viejo
        self.assertEqual(ctx.user_data["reparaciones_en_curso"]["lista"], ["flotante"])

    def test_atras_en_el_pedido_de_fotos_vuelve_al_menu(self):
        from bot.handlers.fotos_reparaciones import handle_repair_photos_atras
        ctx = self._ctx()
        rep = ct.boton_reparaciones("main")
        rep(boton("rp:main:g:flo"), ctx)
        self.assertEqual(rep(boton("rp:main:listo"), ctx), REPAIR_PHOTOS)
        self.assertEqual(handle_repair_photos_atras(boton("back"), ctx), REPAIR_MAIN)
        self.assertEqual(ctx.user_data["reparaciones_en_curso"]["lista"], ["flotante"])  # conserva lo cargado
        self.assertNotIn("rep_fotos", ctx.user_data)

    def test_atras_vuelve_al_sellado(self):
        ctx = self._ctx()
        self.assertEqual(ct.boton_reparaciones("main")(boton("back"), ctx), SEALING_MAIN)
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
        fallback = handler.fallbacks[0]  # botones vencidos (el otro es ATRAS)
        for data in ("rp:main:g:tit", "md:main:plastico", "ct:sin", "tp:main:insp:m:60x60"):
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

    def test_despues_del_tanque_va_a_la_medida(self):
        from bot.handlers.tanques import handle_tank_type
        ctx = entorno.contexto({"state_stack": [], "service": "Limpieza y Reparacion de Tanques",
                                "start_time": "08:00", "end_time": "10:00"})
        self.assertEqual(handle_tank_type(boton("RESERVA"), ctx), MEASURE_MAIN)
        self.assertEqual(ctx.user_data["selected_category"], "RESERVA")
        self.assertEqual(ctx.user_data["modo_ingreso"], "MANUAL")
        self.assertNotIn("NOTA DE VOZ", _enviados(ctx))

    def test_boton_viejo_de_voz_no_es_un_tanque(self):
        from bot.handlers.tanques import handle_tank_type
        from bot.states import TANK_TYPE
        ctx = entorno.contexto({"state_stack": []})
        upd = boton("input_voice")
        self.assertEqual(handle_tank_type(upd, ctx), TANK_TYPE)
        self.assertNotIn("selected_category", ctx.user_data)


class TestModificarAlgo(unittest.TestCase):

    def _ctx(self):
        from bot.states import FINAL_SUMMARY, PHOTOS as FOTOS
        return entorno.contexto(_datos(
            current_state=FINAL_SUMMARY, state_stack=[MEASURE_MAIN, SEALING_MAIN, FOTOS],
            measure_main="1.80, 2.00, 1.50", sealing_main="masilla", repairs="TITCEA 60x60",
            suggestions="nada", contact="Daniel 1135456067", start_time="08:00", end_time="10:00",
            photos=["a", "b", "c"]))

    def _boton(self, data, ctx):
        from bot.handlers.final_summary import handle_final_summary_callback
        return handle_final_summary_callback(boton(data), ctx)

    def test_menu_muestra_los_tanques_cargados(self):
        from bot.handlers.final_summary import _menu
        _, botones = _menu(self._ctx().user_data, "menu")
        datos = [b.callback_data for fila in botones.inline_keyboard for b in fila]
        self.assertIn("ed:t:main", datos)
        self.assertNotIn("ed:t:alt1", datos)  # Reserva no se cargó

    def test_modificar_la_medida_vuelve_al_resumen(self):
        from bot.states import FINAL_SUMMARY
        ctx = self._ctx()
        self.assertEqual(self._boton("final_edit", ctx), FINAL_SUMMARY)
        self.assertEqual(self._boton("ed:t:main", ctx), FINAL_SUMMARY)
        self.assertEqual(self._boton("ed:f:main:medida", ctx), MEASURE_MAIN)
        self.assertEqual(ct.recibir_medida("main")(entorno.update_texto("grande"), ctx), MEASURE_MAIN)  # sigue validando
        self.assertEqual(ct.recibir_medida("main")(entorno.update_texto("150 150 150"), ctx), FINAL_SUMMARY)
        self.assertEqual(ctx.user_data["measure_main"], "1.50, 1.50, 1.50")
        self.assertNotIn("editando", ctx.user_data)
        self.assertIn("RESUMEN COMPLETO", _enviados(ctx))

    def test_modificar_reparaciones_usa_el_menu_y_las_fotos(self):
        from bot.states import FINAL_SUMMARY
        ctx = self._ctx()
        self.assertEqual(self._boton("ed:f:main:reparaciones", ctx), REPAIR_MAIN)
        rep = ct.boton_reparaciones("main")
        self.assertEqual(ctx.user_data["reparaciones_en_curso"]["lista"], ["TITCEA 60x60"])  # arranca con lo cargado
        rep(boton("rp:main:g:flo"), ctx)
        self.assertEqual(rep(boton("rp:main:listo"), ctx), REPAIR_PHOTOS)
        self.assertEqual(ctx.user_data["repairs"], "TITCEA 60x60, flotante")

    def test_modificar_reparaciones_a_ninguna_vuelve_al_resumen(self):
        from bot.states import FINAL_SUMMARY
        ctx = self._ctx()
        self._boton("ed:f:main:reparaciones", ctx)
        self.assertEqual(ct.boton_reparaciones("main")(boton("rp:main:no"), ctx), FINAL_SUMMARY)
        self.assertEqual(ctx.user_data["repairs"], "No")

    def test_atras_en_la_primera_pregunta_vuelve_al_resumen_sin_borrar(self):
        from bot.states import FINAL_SUMMARY
        ctx = self._ctx()
        self._boton("ed:f:main:sellado", ctx)
        self.assertEqual(ct.recibir_texto("main", "sellado")(entorno.update_texto("atras"), ctx), FINAL_SUMMARY)
        self.assertEqual(ctx.user_data["sealing_main"], "masilla")

    def test_modificar_sugerencias_y_contacto(self):
        from bot.states import FINAL_SUMMARY
        from bot.handlers.tanques import get_suggestions_main
        ctx = self._ctx()
        self.assertEqual(self._boton("ed:f:main:sugerencias", ctx), SUGGESTIONS_MAIN)
        self.assertEqual(get_suggestions_main(entorno.update_texto("limpiar antes"), ctx), FINAL_SUMMARY)
        self.assertEqual(ctx.user_data["suggestions"], "limpiar antes")
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

    def test_texto_en_el_resumen_pide_usar_los_botones(self):
        from bot.states import FINAL_SUMMARY
        from bot.handlers.final_summary import handle_final_text
        ctx = self._ctx()
        upd = entorno.update_texto("cambiar sellado a burlete")
        self.assertEqual(handle_final_text(upd, ctx), FINAL_SUMMARY)
        self.assertEqual(ctx.user_data["sealing_main"], "masilla")


if __name__ == "__main__":
    unittest.main()
