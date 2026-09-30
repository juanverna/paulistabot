import os
import base64
import unittest
from pathlib import Path
from email import message_from_bytes
from email.header import decode_header, make_header

from tests import entorno
entorno.preparar()

from bot.services.email_service import armar_mensaje
from bot.services.informe_html import armar_informe, alertas

REFS = Path(__file__).resolve().parent.parent / "bot" / "referencias"

# Fotos de prueba: las de referencia del repo, por file_id
FOTOS = {
    "acceso1":  REFS / "tapa_acceso" / "04.jpg",
    "insp1":    REFS / "tapa_inspeccion" / "07.jpg",
    "insp2":    REFS / "tapa_inspeccion" / "12.jpg",
    "revoque1": REFS / "pared_revoque" / "08.jpg",
    "gral1":    REFS / "tapa_acceso" / "01.jpg",
    "gral2":    REFS / "pared_revoque" / "09.jpg",
    "gral3":    REFS / "tapa_inspeccion" / "02.jpg",
}


def descargar(file_id: str) -> bytes:
    return FOTOS[file_id].read_bytes()


def analisis(**cambios):
    base = {"elemento_detectado": "tapa_acceso", "tipo_tapa_seguro": True, "tapa_faltante": False,
            "coincide_con_lo_declarado": True, "estado": "malo", "danos_visibles": ["óxido con nódulos"],
            "respalda_la_reparacion": True, "requiere_revoque": False, "calidad_foto": "buena",
            "comentario": "Tapa muy corroída."}
    base.update(cambios)
    return base


def reporte():
    """Un servicio completo: cisterna con 3 ítems (uno destrabado) y reserva con revoque."""
    return {
        "service": "Limpieza y Reparacion de Tanques", "code": "42", "order": "1234567",
        "address": "Av. Corrientes 1234 <b>", "codigo_interno": "C-778", "numero_evento": "1234567",
        "start_time": "08:00", "end_time": "12:30", "contact": "Daniel 1135456067",
        "modo_ingreso": "MANUAL",
        "selected_category": "CISTERNA", "alternative_1": "RESERVA", "alternative_2": "INTERMEDIARIO",
        "measure_main": "2.00, 2.00, 1.80", "tapas_inspeccion_main": "TITCEA 40", "tapas_acceso_main": "TATCEA 56",
        "sealing_main": "masilla", "suggestions": "llevar escalera", "repairs": "TMTCEA 49, TITCEA 40 y TITCC 40",
        "measure_alt1": "1.50, 1.50, 1.50", "sealing_alt1": "burlete", "repair_alt1": "revocar paredes",
        "items_reparacion": {
            "main": {"items": {
                "tapa_marco": {"cantidad": 1, "variantes": ["EA"], "codigos": ["TMTCEA 49"]},
                "tapa_inspeccion": {"cantidad": 2, "variantes": ["EA", "C"], "codigos": ["TITCEA 40", "TITCC 40"]},
            }, "estado": {
                "tapa_marco": {"requeridas": 1, "distintas": 1, "fotos": 1, "verificado": True, "ok": True},
                "tapa_inspeccion": {"requeridas": 2, "distintas": 1, "fotos": 2, "verificado": True, "ok": False},
            }},
            "alt1": {"items": {"revoque": {"cantidad": 1, "variantes": [], "codigos": []}},
                     "estado": {"revoque": {"requeridas": 1, "distintas": 1, "fotos": 1, "verificado": True,
                                            "ok": True}}},
        },
        "fotos_reparaciones": {
            "main": [
                {"pid": 1, "file_id": "acceso1", "estado": "validada", "grupo": "tapa_marco", "analisis": analisis()},
                {"pid": 2, "file_id": "insp1", "estado": "validada", "grupo": "tapa_inspeccion", "corregida": True,
                 "analisis": analisis(elemento_detectado="tapa_inspeccion", requiere_revoque=True,
                                      comentario="Tapa de inspección oxidada.")},
                {"pid": 3, "file_id": "insp2", "estado": "validada", "grupo": "tapa_inspeccion",
                 "analisis": analisis(elemento_detectado="tapa_inspeccion", estado="regular")},
            ],
            "alt1": [{"pid": 4, "file_id": "revoque1", "estado": "validada", "grupo": "revoque",
                      "analisis": analisis(elemento_detectado="pared_revoque", requiere_revoque=True,
                                           danos_visibles=["placas desprendidas"],
                                           comentario="Revoque desprendido en varias paredes.")}],
        },
        "fotos_descartadas": [{"pid": 5, "file_id": "x", "sufijo": "main", "estado": "no_corresponde"}],
        "destrabes": [{"tanque": "Cisterna", "item": "Tapa de inspección", "motivo": "foto faltante",
                       "fecha": "30/09/2026", "hora": "15:10"}],
        "photos": ["gral1", "gral2", "gral3"],
    }


class TestMail(unittest.TestCase):

    def test_estructura_compatible_con_extract_reports(self):
        msg = message_from_bytes(armar_mensaje(reporte(), descargar).as_bytes())
        self.assertEqual(msg.get_content_type(), "multipart/alternative")
        plano, related = msg.get_payload()
        # extract_reports.py busca text/plain en el primer nivel de partes
        self.assertEqual(plano.get_content_type(), "text/plain")
        texto = plano.get_payload(decode=True).decode()
        self.assertIn("Reparaciones CISTERNA: TMTCEA 49, TITCEA 40 y TITCC 40", texto)
        self.assertEqual(related.get_content_type(), "multipart/related")
        partes = related.get_payload()
        self.assertEqual(partes[0].get_content_type(), "text/html")
        html = partes[0].get_payload(decode=True).decode()
        imagenes = partes[1:]
        self.assertEqual(len(imagenes), 7)  # 4 de reparaciones + 3 generales
        for img in imagenes:
            cid = img["Content-ID"].strip("<>")
            self.assertIn(f"cid:{cid}", html)
            self.assertLess(len(img.get_payload(decode=True)), 450_000)
            # Adjunto (se abre grande desde la lista de adjuntos de Gmail)
            self.assertEqual(img.get_content_disposition(), "attachment")
        self.assertEqual([i.get_filename() for i in imagenes],
                         ["01_cisterna_tapa_marco.jpg", "02_cisterna_tapa_inspeccion.jpg",
                          "03_cisterna_tapa_inspeccion.jpg", "04_reserva_revoque.jpg",
                          "05_general.jpg", "06_general.jpg", "07_general.jpg"])
        self.assertIn("📎 Foto 1 · ampliar en adjuntos", html)
        self.assertIn("📎 Foto 7 · ampliar en adjuntos", html)
        self.assertLess(len(msg.as_bytes()), 5_000_000)

    def test_asunto(self):
        msg = message_from_bytes(armar_mensaje(reporte(), descargar).as_bytes())
        asunto = str(make_header(decode_header(msg["Subject"])))
        self.assertTrue(asunto.startswith("Reporte de Servicio: Limpieza y Reparacion de Tanques"))
        self.assertIn("Av. Corrientes 1234", asunto)

    def test_fumigaciones_sigue_igual(self):
        datos = {"service": "Fumigaciones", "code": "1", "photos": ["gral1"]}
        msg = message_from_bytes(armar_mensaje(datos, descargar).as_bytes())
        self.assertEqual(msg.get_content_type(), "multipart/mixed")
        plano, foto = msg.get_payload()
        self.assertEqual(plano.get_content_type(), "text/plain")
        self.assertEqual(foto.get_filename(), "foto_1.jpeg")

    def test_si_el_html_falla_sale_en_texto_plano(self):
        from unittest.mock import patch
        with patch("bot.services.informe_html.armar_informe", side_effect=ValueError("roto")):
            msg = message_from_bytes(armar_mensaje(reporte(), descargar).as_bytes())
        self.assertEqual(msg.get_content_type(), "multipart/mixed")
        self.assertEqual(msg.get_payload()[0].get_content_type(), "text/plain")

    def test_foto_que_no_se_puede_bajar(self):
        def falla(file_id):
            if file_id == "insp2":
                raise OSError("Telegram no responde")
            return descargar(file_id)
        html, imagenes = armar_informe(reporte(), falla)
        self.assertEqual(len(imagenes), 6)


class TestContenido(unittest.TestCase):

    def setUp(self):
        self.html, self.imagenes = armar_informe(reporte(), descargar)

    def test_encabezado(self):
        for texto in ("Av. Corrientes 1234 &lt;b&gt;", "1234567", "C-778", "08:00 a 12:30",
                      "Daniel 1135456067"):
            self.assertIn(texto, self.html)
        self.assertNotIn("1234 <b>", self.html)  # escapado

    def test_alertas(self):
        textos = [t for _, t in alertas(reporte())]
        self.assertIn("Cisterna · Tapa de inspección: destrabado por el encargado (foto faltante) "
                      "el 30/09/2026 a las 15:10", textos)
        self.assertIn("Cisterna: 1 foto(s) no coincidían con las reparaciones y se sacaron", textos)
        self.assertIn("Cisterna: 1 foto(s) asignadas a mano por el operario (la IA vio otra cosa)", textos)
        self.assertIn("Cisterna: la IA vio revoque dañado y no está en las reparaciones "
                      "(posible trabajo sin cotizar)", textos)
        # El ítem destrabado no se reporta además como "falta foto"
        self.assertFalse(any("falta foto" in t for t in textos))
        # En la reserva el revoque sí está declarado: no hay alerta de revoque sin cotizar
        self.assertFalse(any(t.startswith("Reserva: la IA vio revoque") for t in textos))
        self.assertIn("⚠ Alertas (4)", self.html)

    def test_cada_item_con_su_foto_y_estado(self):
        self.assertIn("🛢 CISTERNA", self.html)
        self.assertIn("🛢 RESERVA", self.html)
        self.assertIn("Tapa y marco de acceso", self.html)
        self.assertIn("TITCEA 40, TITCC 40 · 2 unidades (entrada de agua y ciego)", self.html)
        self.assertIn("🔓 Destrabado por encargado", self.html)
        self.assertIn("✔ Validado", self.html)
        self.assertIn("➜", self.html)
        self.assertIn("Revoque desprendido en varias paredes.", self.html)
        self.assertIn("📷 Fotos generales", self.html)

    def test_sin_alertas(self):
        datos = reporte()
        for clave in ("destrabes", "fotos_descartadas"):
            del datos[clave]
        datos["fotos_reparaciones"]["main"] = datos["fotos_reparaciones"]["main"][:1]
        datos["fotos_reparaciones"]["main"][0]["analisis"]["requiere_revoque"] = False
        datos["items_reparacion"]["main"] = {
            "items": {"tapa_marco": {"cantidad": 1, "variantes": [], "codigos": ["TMTCEA 49"]}},
            "estado": {"tapa_marco": {"requeridas": 1, "distintas": 1, "fotos": 1, "verificado": True, "ok": True}}}
        html, _ = armar_informe(datos, descargar)
        self.assertIn("Sin alertas", html)

    def test_reporte_viejo_sin_items(self):
        datos = {"service": "Presupuestos", "selected_category": "CISTERNA", "repairs": "cambiar flotante",
                 "fotos_reparaciones": {"main": ["acceso1"]}, "photos": []}
        html, imagenes = armar_informe(datos, descargar)
        self.assertEqual(len(imagenes), 1)
        self.assertIn("Otras reparaciones", html)

    @unittest.skipUnless(os.getenv("INFORME_PREVIEW"), "INFORME_PREVIEW=<archivo.html> para ver el mail")
    def test_vista_previa(self):
        """Guarda el informe con las fotos en línea para abrirlo en el navegador."""
        html = self.html
        for cid, jpeg, _ in self.imagenes:
            html = html.replace(f"cid:{cid}", "data:image/jpeg;base64," + base64.b64encode(jpeg).decode())
        Path(os.environ["INFORME_PREVIEW"]).write_text(html, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
