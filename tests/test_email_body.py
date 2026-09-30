import unittest

from tests import entorno
entorno.preparar()

from bot.services.email_service import _build_body, _photo_attachments


def parse_report(text: str) -> dict:
    """Copia de extract_reports.parse_report (ese módulo necesita pandas/gspread para importarse)."""
    report, current = {}, None
    for line in text.splitlines():
        l = line.strip()
        if not l: continue
        if ':' in l:
            k, v = l.split(':', 1)
            report[k.strip()] = v.strip()
            current = k.strip()
        elif current:
            report[current] += ' ' + l
    return report


def _datos():
    return {
        "service": "Limpieza y Reparacion de Tanques",
        "order": "1234567", "address": "Av. Siempreviva 742",
        "selected_category": "CISTERNA", "alternative_1": "RESERVA",
        "alternative_2": "INTERMEDIARIO",
        "repairs": "cambiar tapa de acceso", "repair_alt1": "revocar",
        "contact": "Daniel 1135456067",
        "fotos_reparaciones": {"main": ["m1", "m2"], "alt1": ["r1"]},
        "destrabes": [{"tanque": "Reserva", "item": "reparaciones", "motivo": "foto faltante",
                       "fecha": "29/09/2026", "hora": "14:30"}],
        "photos": ["g1", "g2", "g3"],
    }


class TestCuerpoMail(unittest.TestCase):

    def test_lineas_nuevas(self):
        body = _build_body(_datos())
        self.assertIn("Fotos reparaciones Cisterna: 2", body)
        self.assertIn("Fotos reparaciones Reserva: 1", body)
        self.assertIn("Destrabado por encargado (Reserva, reparaciones): "
                      "foto faltante - 29/09/2026 14:30", body)

    def test_extract_reports_sigue_viendo_solo_las_reparaciones(self):
        report = parse_report(_build_body(_datos()))
        reparaciones = {k: v for k, v in report.items() if k.lower().startswith("reparaciones")}
        self.assertEqual(reparaciones, {"Reparaciones CISTERNA": "cambiar tapa de acceso",
                                        "Reparaciones RESERVA": "revocar"})

    def test_mail_sin_fotos_de_reparaciones_no_cambia(self):
        datos = _datos()
        del datos["fotos_reparaciones"], datos["destrabes"]
        body = _build_body(datos)
        self.assertNotIn("Fotos reparaciones", body)
        self.assertNotIn("Destrabado", body)

    def test_adjuntos_con_nombre_por_tanque(self):
        nombres = [n for _, n in _photo_attachments(_datos())]
        self.assertEqual(nombres, ["reparaciones_cisterna_foto_1", "reparaciones_cisterna_foto_2",
                                   "reparaciones_reserva_foto_1", "foto_1", "foto_2", "foto_3"])

    def test_adjuntos_con_nombre_por_item(self):
        datos = _datos()
        datos["fotos_reparaciones"] = {"main": [
            {"file_id": "a", "grupo": "tapa_acceso"}, {"file_id": "b", "grupo": "tapa_acceso"},
            {"file_id": "c", "grupo": "tapa_inspeccion"}]}
        nombres = [n for _, n in _photo_attachments(datos)][:3]
        self.assertEqual(nombres, ["reparaciones_cisterna_tapa_acceso_1", "reparaciones_cisterna_tapa_acceso_2",
                                   "reparaciones_cisterna_tapa_inspeccion_1"])

    def test_estado_de_los_items_y_corregidas(self):
        datos = _datos()
        datos["fotos_reparaciones"] = {"main": [
            {"file_id": "a", "estado": "validada", "corregida": True}, {"file_id": "b", "estado": "validada"}]}
        datos["items_reparacion"] = {"main": {"items": {}, "estado": {
            "tapa_acceso": {"requeridas": 2, "distintas": 2, "verificado": True},
            "marco": {"requeridas": 1, "distintas": 0, "verificado": True}}}}
        body = _build_body(datos)
        self.assertIn("Fotos reparaciones Cisterna: 2 (validadas por IA: 2, corregidas por el operario: 1)", body)
        self.assertIn("Ítems con foto Cisterna: Tapa de acceso 2/2, Marco 0/1", body)


if __name__ == "__main__":
    unittest.main()
