import os
import json
import unittest
from unittest.mock import patch, MagicMock

from tests import entorno
entorno.preparar()

from bot.services import dataset_fotos


def _datos():
    return {
        "service": "Limpieza y Reparacion de Tanques", "order": "1234567", "code": "42",
        "address": "Av. Siempreviva 742", "contact": "Daniel 1135456067",
        "selected_category": "CISTERNA", "repairs": "TATCEA 56 y tapa de inspección",
        "items_reparacion": {"main": {"items": {
            "tapa_acceso": {"cantidad": 1, "variantes": ["EA"], "codigos": ["TATCEA 56"]},
            "tapa_inspeccion": {"cantidad": 1, "variantes": [], "codigos": []}}, "estado": {}}},
        "fotos_reparaciones": {"main": [
            {"file_id": "f1", "estado": "validada", "grupo_ia": "tapa_inspeccion", "grupo": "tapa_acceso",
             "corregida": True, "analisis": {"elemento_detectado": "tapa_inspeccion", "tipo_tapa_seguro": True,
                                             "tapa_faltante": False, "estado": "malo", "calidad_foto": "buena",
                                             "respalda_la_reparacion": True, "requiere_revoque": False,
                                             "danos_visibles": ["óxido", "perforación"], "comentario": "x"}},
            {"file_id": "f2", "estado": "sin_validar", "grupo": "tapa_inspeccion", "analisis": None},
        ]},
        "fotos_descartadas": [{"file_id": "f3", "sufijo": "main", "estado": "no_corresponde",
                               "grupo_ia": None, "analisis": {"elemento_detectado": "piso"}}],
    }


class TestDataset(unittest.TestCase):

    def test_filas(self):
        filas = dataset_fotos.filas(_datos())
        self.assertEqual(len(filas), 3)
        fila = dict(zip(dataset_fotos.COLUMNAS, filas[0]))
        self.assertEqual(fila["orden"], "1234567")
        self.assertEqual(fila["tanque"], "CISTERNA")
        self.assertEqual(fila["items_declarados"], "tapa_acceso x1 [TATCEA 56]; tapa_inspeccion x1")
        self.assertEqual((fila["grupo_ia"], fila["grupo_final"], fila["corregida_por_operario"]),
                         ("tapa_inspeccion", "tapa_acceso", "sí"))
        self.assertEqual(fila["danos_visibles"], "óxido; perforación")
        self.assertEqual(fila["modelo"], "gpt-6-luna")
        sin_ia = dict(zip(dataset_fotos.COLUMNAS, filas[1]))
        self.assertEqual((sin_ia["estado"], sin_ia["modelo"], sin_ia["respalda_la_reparacion"]),
                         ("sin_validar", "", ""))
        descartada = dict(zip(dataset_fotos.COLUMNAS, filas[2]))
        self.assertEqual((descartada["descartada"], descartada["grupo_final"]), ("sí", ""))
        # Sin datos personales: ni dirección ni contacto
        todo = json.dumps(filas, ensure_ascii=False)
        self.assertNotIn("Siempreviva", todo)
        self.assertNotIn("1135456067", todo)

    def test_sin_configurar_no_hace_nada(self):
        with patch.object(dataset_fotos, "_executor") as executor:
            dataset_fotos.registrar(_datos())
            executor.submit.assert_not_called()

    @patch.dict(os.environ, {"DATASET_SHEET_ID": "hoja123", "GOOGLE_SERVICE_ACCOUNT_JSON": "{}"})
    def test_agrega_encabezado_si_la_hoja_esta_vacia(self):
        sesion = MagicMock()
        sesion.get.return_value.json.return_value = {}
        with patch.object(dataset_fotos, "_sesion", return_value=sesion), \
                patch.object(dataset_fotos, "_encabezado_ok", False):
            dataset_fotos._agregar([["fila"]])
        url = sesion.post.call_args.args[0]
        self.assertIn("/spreadsheets/hoja123/values/Fotos!A1:append", url)
        self.assertEqual(sesion.post.call_args.kwargs["json"]["values"], [dataset_fotos.COLUMNAS, ["fila"]])

    @patch.dict(os.environ, {"DATASET_SHEET_ID": "hoja123", "GOOGLE_SERVICE_ACCOUNT_JSON": "{}"})
    def test_un_error_de_google_no_rompe_nada(self):
        with patch.object(dataset_fotos, "_sesion", side_effect=ValueError("credencial inválida")):
            dataset_fotos._agregar([["fila"]])  # solo loguea


if __name__ == "__main__":
    unittest.main()
