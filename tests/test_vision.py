import io
import hashlib
import os
import json
import threading
import unittest
from unittest.mock import patch, MagicMock

from tests import entorno
entorno.preparar()

from PIL import Image

from bot.states import REPAIR_PHOTOS, SUGGESTIONS_MAIN
from bot.services import vision_service, revision_fotos
from bot.handlers import fotos_reparaciones as fr
from bot.handlers.tanques import get_repair_main
from bot.services.email_service import _build_body, _photo_attachments


def analisis(**cambios):
    base = {"elemento_detectado": "tapa_acceso", "tipo_tapa_seguro": True, "tapa_faltante": False,
            "coincide_con_lo_declarado": True, "estado": "malo", "danos_visibles": ["óxido con nódulos"],
            "respalda_la_reparacion": True, "requiere_revoque": False,
            "calidad_foto": "buena", "comentario": "Tapa muy corroída"}
    base.update(cambios)
    return base


INSPECCION = dict(elemento_detectado="tapa_inspeccion")


def huella_fija(data: bytes) -> int:
    return int.from_bytes(hashlib.sha256(data).digest()[:8], "big")


def jpeg(ancho=100, alto=80, color=(120, 80, 40), rayas=False) -> bytes:
    img = Image.new("RGB", (ancho, alto), color)
    if rayas:
        for x in range(0, ancho, 10):
            for y in range(alto):
                img.putpixel((x, y), (255, 255, 255))
    out = io.BytesIO()
    img.save(out, format="JPEG")
    return out.getvalue()


class TestParsearJson(unittest.TestCase):

    def test_json_limpio(self):
        self.assertEqual(vision_service.parsear_json(json.dumps(analisis())), analisis())

    def test_con_backticks(self):
        texto = "```json\n" + json.dumps(analisis()) + "\n```"
        self.assertEqual(vision_service.parsear_json(texto), analisis())
        self.assertEqual(vision_service.parsear_json("```" + json.dumps(analisis()) + "```"), analisis())

    def test_invalido(self):
        for texto in ("", None, "no es json", "[1, 2]", '{"calidad_foto": "buena"}'):
            self.assertIsNone(vision_service.parsear_json(texto), repr(texto))

    def test_respuesta_vieja_sin_tapa_faltante(self):
        viejo = analisis()
        del viejo["tapa_faltante"]
        self.assertFalse(vision_service.parsear_json(json.dumps(viejo))["tapa_faltante"])

    def test_valores_desconocidos(self):
        a = vision_service.parsear_json(json.dumps(analisis(calidad_foto="rara", elemento_detectado="caño")))
        self.assertEqual((a["calidad_foto"], a["elemento_detectado"]), ("buena", "otro"))

    def test_grupos(self):
        p = vision_service.parsear_grupos
        self.assertEqual(p('{"objeto_por_foto": [0, 1, 0], "comentario": ""}', 3), [0, 1, 0])
        self.assertEqual(p('```json\n{"objeto_por_foto": [0, 0]}\n```', 2), [0, 0])
        for texto in ('{"objeto_por_foto": [0, 1]}', '{"objeto_por_foto": [0, -1, 0]}',
                      '{"objeto_por_foto": [true, 0, 1]}', "basura", '{"otra": 1}'):
            self.assertIsNone(p(texto, 3), texto)


class TestHuella(unittest.TestCase):

    def test_casi_iguales_y_distintas(self):
        a = vision_service.huella(jpeg(200, 150, rayas=True))
        b = vision_service.huella(jpeg(400, 300, rayas=True))   # misma foto, otro tamaño
        c = vision_service.huella(jpeg(200, 150, color=(10, 200, 30)))
        self.assertLessEqual(vision_service.distancia(a, b), revision_fotos.UMBRAL_HUELLA)
        self.assertGreater(vision_service.distancia(a, c), revision_fotos.UMBRAL_HUELLA)
        self.assertIsNone(vision_service.huella(b"no es imagen"))


class TestClasificar(unittest.TestCase):
    ACCESO = {"tapa_acceso": {"cantidad": 1}}
    AMBAS  = {"tapa_acceso": {"cantidad": 1}, "tapa_inspeccion": {"cantidad": 1}}

    def test_estados(self):
        c = lambda a, items=self.ACCESO: (lambda r: (r["estado"], r["calidad"], r["candidatos"]))(
            revision_fotos.clasificar(a, items))
        self.assertEqual(c(None), ("sin_validar", None, None))
        self.assertEqual(c(analisis(calidad_foto="oscura")), ("calidad", "oscura", ["tapa_acceso"]))
        self.assertEqual(c(analisis(elemento_detectado="piso")), ("no_corresponde", None, []))
        self.assertEqual(c(analisis(respalda_la_reparacion=False)), ("no_respalda", None, ["tapa_acceso"]))
        self.assertEqual(c(analisis()), ("validada", None, ["tapa_acceso"]))

    def test_tapa_de_otro_tipo_que_el_declarado(self):
        # La IA está segura de que es de inspección y solo se declaró la de acceso: no corresponde
        r = revision_fotos.clasificar(analisis(**INSPECCION), self.ACCESO)
        self.assertEqual(r["estado"], "no_corresponde")
        # La IA duda: no se adivina, pregunta al operario
        r = revision_fotos.clasificar(analisis(tipo_tapa_seguro=False, **INSPECCION), self.ACCESO)
        self.assertEqual((r["estado"], r["candidatos"]), ("a_confirmar", ["tapa_acceso"]))

    def test_tapa_y_marco_se_respalda_con_la_foto_de_la_tapa_de_acceso(self):
        # "TMTCEA 56": en la foto de la tapa de acceso se ve el marco, alcanza con esa
        r = revision_fotos.clasificar(analisis(), {"tapa_marco": {"cantidad": 1}})
        self.assertEqual((r["estado"], r["candidatos"]), ("validada", ["tapa_marco"]))
        r = revision_fotos.clasificar(analisis(elemento_detectado="marco"), {"tapa_marco": {"cantidad": 1}})
        self.assertEqual((r["estado"], r["candidatos"]), ("validada", ["tapa_marco"]))

    def test_tapa_a_secas_no_pregunta(self):
        r = revision_fotos.clasificar(analisis(tipo_tapa_seguro=False), {"tapa": {"cantidad": 1}})
        self.assertEqual((r["estado"], r["candidatos"]), ("validada", ["tapa"]))

    def test_los_dos_tipos_y_la_ia_duda_pregunta(self):
        r = revision_fotos.clasificar(analisis(tipo_tapa_seguro=False), self.AMBAS)
        self.assertEqual(r["estado"], "a_confirmar")
        r = revision_fotos.clasificar(analisis(**INSPECCION), self.AMBAS)
        self.assertEqual((r["estado"], r["candidatos"]), ("validada", ["tapa_inspeccion"]))

    def test_otras_reparaciones(self):
        otras = {"otras": {"cantidad": 1}}
        self.assertEqual(revision_fotos.clasificar(analisis(elemento_detectado="otro"), otras)["estado"],
                         "validada")
        self.assertEqual(revision_fotos.clasificar(
            analisis(elemento_detectado="otro", coincide_con_lo_declarado=False), otras)["estado"],
            "no_corresponde")


class TestAnalizarFoto(unittest.TestCase):

    def _respuesta(self, contenido):
        resp = MagicMock()
        resp.choices[0].message.content = contenido
        return resp

    def test_apagada_no_llama_a_la_api(self):
        with patch.object(vision_service, "_cliente") as cliente:
            self.assertIsNone(vision_service.analizar_foto(jpeg(), "Cisterna", "cambiar tapa"))
            self.assertIsNone(vision_service.agrupar_objetos([jpeg(), jpeg()], "Tapa de acceso", "Cisterna", 2))
            cliente.assert_not_called()

    @patch.object(vision_service, "_referencias", [])  # sin fotos de referencia
    @patch.object(vision_service, "VISION_ACTIVA", True)
    def test_pedido_y_respuesta(self):
        with patch.object(vision_service, "_cliente") as cliente:
            cliente.return_value.chat.completions.create.return_value = self._respuesta(json.dumps(analisis()))
            self.assertEqual(vision_service.analizar_foto(jpeg(), "Cisterna", "cambiar tapa",
                                                          "Tapa de acceso (x2)"), analisis())
            kwargs = cliente.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], vision_service.VISION_MODEL)
        self.assertEqual(kwargs["response_format"]["type"], "json_schema")
        fijo, caso, imagen = kwargs["messages"][0]["content"]
        self.assertIn("Sos inspector de tanques", fijo["text"])
        self.assertIn('"cambiar tapa"', caso["text"])
        self.assertIn("Tapa de acceso (x2)", caso["text"])
        self.assertEqual(imagen["image_url"]["detail"], "high")
        self.assertTrue(imagen["image_url"]["url"].startswith("data:image/jpeg;base64,"))

    @patch.object(vision_service, "VISION_ACTIVA", True)
    def test_agrupar_objetos(self):
        with patch.object(vision_service, "_cliente") as cliente:
            cliente.return_value.chat.completions.create.return_value = self._respuesta(
                '{"objeto_por_foto": [0, 1], "comentario": "EA y ciego"}')
            self.assertEqual(vision_service.agrupar_objetos([jpeg(), jpeg()], "Tapa de acceso", "Cisterna", 2),
                             [0, 1])
            contenido = cliente.return_value.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        self.assertEqual(len(contenido), 3)  # texto + 2 fotos

    @patch.object(vision_service, "VISION_ACTIVA", True)
    def test_error_o_timeout_queda_sin_validar(self):
        with patch.object(vision_service, "_cliente") as cliente:
            cliente.return_value.chat.completions.create.side_effect = TimeoutError("tardó")
            self.assertIsNone(vision_service.analizar_foto(jpeg(), "Cisterna", "cambiar tapa"))
            self.assertIsNone(vision_service.agrupar_objetos([jpeg(), jpeg()], "Tapa", "Cisterna", 2))
            cliente.return_value.chat.completions.create.side_effect = None
            cliente.return_value.chat.completions.create.return_value = self._respuesta("basura")
            self.assertIsNone(vision_service.analizar_foto(jpeg(), "Cisterna", "cambiar tapa"))

    @patch.object(vision_service, "VISION_ACTIVA", True)
    def test_archivo_que_no_es_imagen_queda_sin_validar(self):
        with patch.object(vision_service, "_cliente") as cliente:
            self.assertIsNone(vision_service.analizar_foto(b"no soy una imagen", "Cisterna", "x"))
            cliente.assert_not_called()

    def test_achicar_imagen(self):
        grande = Image.open(io.BytesIO(vision_service.achicar_imagen(jpeg(3000, 2000))))
        self.assertEqual(max(grande.size), vision_service.LADO_MAXIMO_PX)
        chica = Image.open(io.BytesIO(vision_service.achicar_imagen(jpeg(640, 480))))
        self.assertEqual(chica.size, (640, 480))


class FlujoConIA(unittest.TestCase):
    """Base: flujo de fotos de reparaciones con la IA simulada por file_id."""
    REPARACIONES = "cambiar tapa de acceso"

    def setUp(self):
        self.respuestas, self.objetos = {}, None
        for nombre, efecto in (("analizar_foto", self._analizar), ("agrupar_objetos", self._agrupar)):
            parche = patch.object(vision_service, nombre, side_effect=efecto)
            parche.start()
            self.addCleanup(parche.stop)
        # Huella distinta por foto, salvo que el test diga otra cosa. Fija (sha256), no hash():
        # hash() cambia en cada ejecución y a veces dejaba dos fotos a menos de UMBRAL_HUELLA.
        parche = patch.object(vision_service, "huella", side_effect=huella_fija)
        self.huella = parche.start()
        self.addCleanup(parche.stop)
        self.ctx = entorno.contexto({"selected_category": "CISTERNA", "alternative_1": "RESERVA",
                                     "alternative_2": "INTERMEDIARIO", "state_stack": []})
        get_repair_main(entorno.update_texto(self.REPARACIONES), self.ctx)
        # get_file(file_id).download() escribe el file_id: así _analizar sabe qué foto es
        self.ctx.bot.get_file.side_effect = lambda fid: MagicMock(
            download=lambda out: out.write(fid.encode()))

    def _analizar(self, data, tanque, reparacion, items=""):
        return self.respuestas.get(data.decode())

    def _agrupar(self, fotos, etiqueta, tanque, cantidad):
        self.agrupadas = [f.decode() for f in fotos]
        return self.objetos

    def _foto(self, file_id, resultado, message_id=10):
        self.respuestas[file_id] = resultado
        upd = entorno.update_foto(file_id)
        upd.message.message_id = message_id
        self.assertEqual(fr.handle_repair_photos(upd, self.ctx), REPAIR_PHOTOS)
        entorno.esperar_revisiones(self._fotos())

    def _fotos(self):
        return self.ctx.user_data["fotos_reparaciones"]["main"]

    def _pid(self, file_id):
        fotos = self._fotos() + self.ctx.user_data.get("fotos_descartadas", [])
        return next(f["pid"] for f in fotos if f["file_id"] == file_id)

    def _boton(self, data):
        upd = MagicMock()
        upd.callback_query.data = data
        return upd, fr.handle_repair_photo_button(upd, self.ctx)

    def _enviados(self):
        return [c.kwargs for c in self.ctx.bot.send_message.call_args_list]

    def _textos(self):
        return "\n".join(k.get("text", "") for k in self._enviados())

    def _listo(self):
        self.ultimo_listo = entorno.update_texto("Listo")
        return fr.handle_repair_photos(self.ultimo_listo, self.ctx)


class TestUnItem(FlujoConIA):

    def test_foto_validada_sigue(self):
        self._foto("f1", analisis(), message_id=55)
        aviso = self._enviados()[-1]
        self.assertIn("📷 Tapa de acceso ✅", aviso["text"])
        self.assertEqual(aviso["reply_to_message_id"], 55)
        self.assertEqual(self._listo(), SUGGESTIONS_MAIN)
        [foto] = self._fotos()
        self.assertEqual((foto["estado"], foto["grupo"], foto["analisis"]["estado"]),
                         ("validada", "tapa_acceso", "malo"))

    def test_foto_que_no_coincide_se_saca_del_apartado(self):
        self._foto("ok", analisis())
        self._foto("piso", analisis(elemento_detectado="piso", coincide_con_lo_declarado=False),
                   message_id=77)
        self.assertEqual(entorno.ids(self._fotos()), ["ok"])
        [descartada] = self.ctx.user_data["fotos_descartadas"]
        self.assertEqual((descartada["file_id"], descartada["sufijo"]), ("piso", "main"))
        aviso = self._enviados()[-1]
        self.assertIn("parece el piso del tanque y eso no está en las reparaciones que pusiste para <b>Cisterna</b>",
                      aviso["text"])
        self.assertIn("mandala después con las fotos generales", aviso["text"])
        self.assertEqual(aviso["reply_to_message_id"], 77)
        self.assertNotIn("piso", [fid for fid, _ in _photo_attachments(self.ctx.user_data)])
        self.assertIn("Fotos descartadas por no coincidir Cisterna: 1", _build_body(self.ctx.user_data))
        self.assertEqual(self._listo(), SUGGESTIONS_MAIN)

    def test_descartada_se_recupera_con_el_boton(self):
        self._foto("f1", analisis(elemento_detectado="otro", coincide_con_lo_declarado=False))
        self.assertEqual(self._listo(), REPAIR_PHOTOS)
        pid = self._pid("f1")
        upd, _ = self._boton(f"rf:main:{pid}:c")
        upd.callback_query.edit_message_reply_markup.assert_called_once()
        self._boton(f"rf:main:{pid}:g:tapa_acceso")
        self.assertEqual(entorno.ids(self._fotos()), ["f1"])
        self.assertEqual(self.ctx.user_data["fotos_descartadas"], [])
        self.assertTrue(self._fotos()[0]["corregida"])
        self.assertEqual(self._listo(), SUGGESTIONS_MAIN)

    def test_solo_fotos_que_no_coinciden_traba_por_falta_de_foto(self):
        self._foto("piso", analisis(elemento_detectado="piso", coincide_con_lo_declarado=False))
        self.assertEqual(self._listo(), REPAIR_PHOTOS)
        self.assertIn("Falta la foto de la tapa de acceso. Si tenés otra foto", self._enviados()[-1]["text"])

    @patch.dict(os.environ, {"ADMIN_DAILY_CODE": "4821"})
    def test_foto_oscura_traba_y_se_destraba_con_codigo(self):
        self._foto("f1", analisis(calidad_foto="oscura"))
        self.assertIn("Esta foto de la tapa de acceso salió oscura", self._enviados()[-1]["text"])
        self.assertEqual(self._listo(), REPAIR_PHOTOS)
        self.assertIn("La foto de la tapa de acceso salió oscura. Si tenés otra foto del mismo lugar",
                      self._enviados()[-1]["text"])
        self.assertEqual(fr.handle_repair_photos(entorno.update_texto("4821"), self.ctx), SUGGESTIONS_MAIN)
        [reg] = self.ctx.user_data["destrabes"]
        self.assertEqual((reg["item"], reg["motivo"]), ("Tapa de acceso", "foto de calidad baja"))

    @patch.dict(os.environ, {"ADMIN_DAILY_CODE": "4821"})
    def test_foto_que_no_respalda_traba(self):
        self._foto("f1", analisis(respalda_la_reparacion=False, estado="bueno"))
        self.assertEqual(self._listo(), REPAIR_PHOTOS)
        self.assertIn("La foto no muestra bien el daño de la tapa de acceso", self._enviados()[-1]["text"])
        fr.handle_repair_photos(entorno.update_texto("4821"), self.ctx)
        self.assertEqual(self.ctx.user_data["destrabes"][0]["motivo"], "foto no respalda la reparación")

    def test_trabado_y_llega_una_foto_que_sirve(self):
        self._foto("f1", analisis(calidad_foto="borrosa"))
        self._listo()
        self._foto("f2", analisis())
        self.assertIn("Escribí <b>Listo</b> para seguir", self._enviados()[-1]["text"])
        self.assertEqual(self._listo(), SUGGESTIONS_MAIN)
        self.assertNotIn("destrabes", self.ctx.user_data)

    def test_una_buena_y_una_mala_sigue(self):
        self._foto("f1", analisis(calidad_foto="muy_lejos"))
        self._foto("f2", analisis())
        self.assertEqual(self._listo(), SUGGESTIONS_MAIN)
        self.assertIn("(validadas por IA: 1, de calidad baja: 1)", _build_body(self.ctx.user_data))

    def test_ia_caida_no_traba(self):
        self._foto("f1", None)
        self.assertEqual(self._listo(), SUGGESTIONS_MAIN)
        self.assertEqual(self._fotos()[0]["estado"], "sin_validar")

    def test_ia_que_tarda_demasiado_no_traba(self):
        liberar = threading.Event()
        self.respuestas["lenta"] = analisis(elemento_detectado="piso")

        def lenta(data, tanque, reparacion, items=""):
            liberar.wait(5)
            return self.respuestas.get(data.decode())

        vision_service.analizar_foto.side_effect = lenta
        self.addCleanup(liberar.set)
        fr.handle_repair_photos(entorno.update_foto("lenta"), self.ctx)
        # _cerrar_paso espera VISION_TIMEOUT_S + 10: lo bajamos a 0.2 s para el test
        with patch.object(fr.vision_service, "VISION_TIMEOUT_S", -9.8):
            self.assertEqual(self._listo(), SUGGESTIONS_MAIN)
        liberar.set()
        entorno.esperar_revisiones()
        # El resultado que llegó tarde se ignora: la foto queda sin validar y en su apartado
        [foto] = self._fotos()
        self.assertEqual(foto["estado"], "sin_validar")
        self.assertNotIn("fotos_descartadas", self.ctx.user_data)

    def test_boton_de_un_paso_que_ya_termino(self):
        self._foto("f1", analisis())
        pid = self._pid("f1")
        self._listo()
        upd, _ = self._boton(f"rf:main:{pid}:c")
        upd.callback_query.answer.assert_called_with("Ese paso ya terminó.")
        upd.callback_query.edit_message_reply_markup.assert_not_called()


class TestDosTiposDeTapa(FlujoConIA):
    REPARACIONES = "cambiar tapa de inspeccion y tapa de acceso"

    def test_pide_las_dos(self):
        texto = self.ctx.bot.send_message.call_args_list[0].kwargs["text"]
        self.assertIn("• Tapa de inspección", texto)
        self.assertIn("• Tapa de acceso", texto)

    def test_dos_fotos_de_la_misma_tapa_y_ninguna_de_la_otra(self):
        """El caso del dueño: 2 fotos de un ítem y 0 del otro."""
        self._foto("i1", analisis(**INSPECCION))
        self._foto("i2", analisis(**INSPECCION))
        self.assertEqual(self._listo(), REPAIR_PHOTOS)
        textos = self._textos()
        self.assertIn("✅ Tapa de inspección (2 foto(s))", textos)
        self.assertIn("❌ Tapa de acceso: 0 de 1", textos)
        self.assertIn("Falta la foto de la tapa de acceso. Si tenés otra foto", textos)
        # Una de las dos era en realidad la de acceso: la corrige con [Cambiar], sin mandar nada
        self._boton(f"rf:main:{self._pid('i2')}:g:tapa_acceso")
        self.assertEqual(self._listo(), SUGGESTIONS_MAIN)
        grupos = {f["file_id"]: f["grupo"] for f in self._fotos()}
        self.assertEqual(grupos, {"i1": "tapa_inspeccion", "i2": "tapa_acceso"})
        self.assertEqual(self.ctx.user_data["items_reparacion"]["main"]["estado"]["tapa_acceso"]["distintas"], 1)

    def test_la_ia_duda_y_pregunta_cual_tapa_es(self):
        self._foto("t1", analisis(tipo_tapa_seguro=False))
        pregunta = self._enviados()[-1]
        self.assertIn("No estoy seguro de qué tapa es esta foto", pregunta["text"])
        botones = [b.callback_data for fila in pregunta["reply_markup"].inline_keyboard for b in fila]
        pid = self._pid("t1")
        self.assertEqual(botones, [f"rf:main:{pid}:g:tapa_inspeccion", f"rf:main:{pid}:g:tapa_acceso",
                                   f"rf:main:{pid}:g:otra"])
        self._foto("i1", analisis(**INSPECCION))
        # Sin responder no se puede cerrar el paso
        self.assertEqual(self._listo(), REPAIR_PHOTOS)
        self.assertIn("decime de cuál tapa es", self.ultimo_listo.message.reply_text.call_args.args[0])
        self._boton(f"rf:main:{pid}:g:tapa_acceso")
        self.assertEqual(self._listo(), SUGGESTIONS_MAIN)

    @patch.dict(os.environ, {"ADMIN_DAILY_CODE": "4821"})
    def test_destrabe_registra_cada_item_que_falta(self):
        self._listo()
        fr.handle_repair_photos(entorno.update_texto("4821"), self.ctx)
        self.assertEqual(sorted(d["item"] for d in self.ctx.user_data["destrabes"]),
                         ["Tapa de acceso", "Tapa de inspección"])


class TestDosTapasDeAcceso(FlujoConIA):
    """Hay que cambiar 2 tapas de acceso (entrada de agua y ciego): 2 fotos de 2 tapas distintas."""
    REPARACIONES = "TATCEA 56 y TATCC 56"

    def test_pide_una_de_cada_una(self):
        self.assertIn("Tapa de acceso: entrada de agua y ciego, una foto de cada una",
                      self.ctx.bot.send_message.call_args_list[0].kwargs["text"])

    def test_una_sola_foto_no_alcanza(self):
        self._foto("a1", analisis())
        self.assertEqual(self._listo(), REPAIR_PHOTOS)
        self.assertIn("Faltan 1 foto(s) de tapa de acceso (pusiste 2 distintas)", self._textos())

    def test_dos_fotos_de_la_misma_tapa_no_alcanzan(self):
        self._foto("a1", analisis())
        self._foto("a2", analisis())
        self.objetos = [0, 0]  # la IA dice que es la misma tapa desde otro ángulo
        self.assertEqual(self._listo(), REPAIR_PHOTOS)
        self.assertEqual(self.agrupadas, ["a1", "a2"])
        self.assertIn("pero las fotos muestran 1: falta la foto de la otra", self._textos())
        # Manda la del ciego
        self._foto("a3", analisis())
        self.objetos = [0, 0, 1]
        self.assertEqual(self._listo(), SUGGESTIONS_MAIN)
        estado = self.ctx.user_data["items_reparacion"]["main"]["estado"]["tapa_acceso"]
        self.assertEqual((estado["distintas"], estado["requeridas"], estado["verificado"]), (2, 2, True))

    def test_foto_repetida_no_cuenta_dos_veces_ni_llama_a_la_ia(self):
        self.huella.side_effect = lambda data: 12345  # misma huella: la misma foto dos veces
        self._foto("a1", analisis())
        self._foto("a2", analisis())
        self.assertEqual(self._listo(), REPAIR_PHOTOS)
        self.assertFalse(hasattr(self, "agrupadas"))

    def test_las_huellas_de_prueba_son_distintas(self):
        nombres = ["a1", "a2", "a3", "ea", "ciego", "i1", "i2", "t1", "f1", "f2", "ok", "piso"]
        for x in nombres:
            for y in nombres:
                if x < y:
                    self.assertGreater(vision_service.distancia(huella_fija(x.encode()), huella_fija(y.encode())),
                                       revision_fotos.UMBRAL_HUELLA, (x, y))

    def test_dos_tapas_distintas_sigue(self):
        self._foto("ea", analisis())
        self._foto("ciego", analisis())
        self.objetos = [0, 1]
        self.assertEqual(self._listo(), SUGGESTIONS_MAIN)
        self.assertIn("✅ Tapa de acceso (2 de 2, 2 foto(s))", self._textos())

    def test_si_la_ia_no_puede_comparar_no_traba(self):
        self._foto("ea", analisis())
        self._foto("ciego", analisis())
        self.objetos = None
        self.assertEqual(self._listo(), SUGGESTIONS_MAIN)
        self.assertIn("Tapa de acceso 2/2 sin verificar", _build_body(self.ctx.user_data))

class TestCasoRealTapaDeAccesoComoInspeccion(FlujoConIA):
    """Caso real del 30/09: "Tapa de inspeccion y TMTCEA56" y una foto de la tapa de acceso que la
    IA toma como de inspección sin estar segura. Antes pasaba como tapa de inspección ✅."""
    REPARACIONES = "Tapa de inspeccion y TMTCEA56"

    def test_pide_las_dos_y_pregunta_la_tapa_dudosa(self):
        texto = self.ctx.bot.send_message.call_args_list[0].kwargs["text"]
        self.assertIn("• Tapa de inspección", texto)
        self.assertIn("• Tapa y marco de acceso", texto)
        self._foto("acceso", analisis(tipo_tapa_seguro=False, **INSPECCION))
        self.assertIn("No estoy seguro de qué tapa es esta foto", self._enviados()[-1]["text"])
        # El operario dice que es la tapa y marco de acceso
        self._boton(f"rf:main:{self._pid('acceso')}:g:tapa_marco")
        # Falta la de inspección: se traba por eso, no pasa como si fuera la de inspección
        self.assertEqual(self._listo(), REPAIR_PHOTOS)
        self.assertIn("✅ Tapa y marco de acceso (1 foto(s))", self._textos())
        self.assertIn("Falta la foto de la tapa de inspección", self._textos())
        [foto] = self._fotos()
        self.assertEqual((foto["grupo"], foto["corregida"]), ("tapa_marco", True))

    def test_si_confirma_una_tapa_sin_dano_no_respalda(self):
        self._foto("acceso", analisis(tipo_tapa_seguro=False, respalda_la_reparacion=False, **INSPECCION))
        self._boton(f"rf:main:{self._pid('acceso')}:g:tapa_marco")
        self.assertEqual(self._fotos()[0]["estado"], "no_respalda")


class TestTapaFaltante(FlujoConIA):
    """Donde debería haber una tapa de inspección y solo está el agujero."""
    REPARACIONES = "colocar tapa de inspeccion"

    def test_el_agujero_respalda_colocar_la_tapa(self):
        self._foto("agujero", analisis(tapa_faltante=True, **INSPECCION))
        self.assertIn("📷 Tapa de inspección (falta la tapa propiamente dicha) ✅", self._enviados()[-1]["text"])
        self.assertEqual(self._listo(), SUGGESTIONS_MAIN)


class TestReferencias(unittest.TestCase):
    """Fotos de ejemplo en bot/referencias/<elemento>/ que se le muestran a la IA."""

    def setUp(self):
        import shutil
        import tempfile
        from pathlib import Path
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        for elemento, n in (("tapa_acceso", 3), ("tapa_inspeccion", 2), ("tapa_inspeccion_faltante", 1)):
            (self.dir / elemento).mkdir()
            for i in range(n):
                (self.dir / elemento / f"{i}.jpg").write_bytes(jpeg(2000, 1500))
        (self.dir / "tapa_acceso" / "notas.txt").write_text("no es una foto")
        (self.dir / "carpeta_desconocida").mkdir()
        for nombre, valor in (("REFERENCIAS_DIR", self.dir), ("_referencias", None), ("VISION_ACTIVA", True)):
            parche = patch.object(vision_service, nombre, valor)
            parche.start()
            self.addCleanup(parche.stop)

    def test_carga_por_elemento_achicadas(self):
        refs = vision_service.referencias()
        self.assertEqual([(e, len(j)) for e, j in refs],
                         [("tapa_acceso", 3), ("tapa_inspeccion", 2), ("tapa_inspeccion_faltante", 1)])
        img = Image.open(io.BytesIO(refs[0][1][0]))
        self.assertEqual(max(img.size), vision_service.LADO_REFERENCIA_PX)
        self.assertIs(vision_service.referencias(), refs)  # se leen una sola vez

    def test_tope_por_elemento(self):
        with patch.object(vision_service, "VISION_MAX_REF", 2):
            self.assertEqual([len(j) for _, j in vision_service.referencias()], [2, 2, 1])

    def test_van_en_el_pedido_antes_de_la_foto(self):
        with patch.object(vision_service, "_cliente") as cliente:
            resp = MagicMock()
            resp.choices[0].message.content = json.dumps(analisis())
            cliente.return_value.chat.completions.create.return_value = resp
            vision_service.analizar_foto(jpeg(), "Cisterna", "cambiar tapa", "Tapa de acceso")
            contenido = cliente.return_value.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        textos = [c["text"] for c in contenido if c["type"] == "text"]
        self.assertIn("Ejemplos de tapas de acceso (elemento_detectado = tapa_acceso):", textos)
        self.assertIn("Ejemplos de tapas de inspección (elemento_detectado = tapa_inspeccion):", textos)
        self.assertTrue(any("solo está el agujero" in t and "tapa_faltante = true" in t for t in textos))
        imagenes = [c["image_url"]["detail"] for c in contenido if c["type"] == "image_url"]
        self.assertEqual(imagenes, ["low"] * 6 + ["high"])  # 6 referencias y al final la foto
        self.assertTrue(contenido[-2]["text"].startswith("FOTO A ANALIZAR"))

    def test_sin_carpeta_no_hay_referencias(self):
        with patch.object(vision_service, "REFERENCIAS_DIR", self.dir / "no_existe"):
            self.assertEqual(vision_service.referencias(), [])


if __name__ == "__main__":
    unittest.main()
