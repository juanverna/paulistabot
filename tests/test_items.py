import unittest

from tests import entorno
entorno.preparar()

from bot.services.items_reparacion import (detectar_items, codigos_de_otro_tanque, lista_para_operario,
                                           mensaje_codigos_de_otro_tanque)


def cantidades(texto: str) -> dict:
    return {g: i["cantidad"] for g, i in detectar_items(texto).items()}


class TestDetectarItems(unittest.TestCase):

    def test_texto_tal_cual(self):
        casos = {
            "cambiar tapa de inspección":                   {"tapa_inspeccion": 1},
            "Tapa inspeccion 60":                           {"tapa_inspeccion": 1},
            "cambiar tapa insp.":                           {"tapa_inspeccion": 1},
            "cambiar tapa de acceso":                       {"tapa_acceso": 1},
            "tapa de inspección y tapa de acceso":          {"tapa_inspeccion": 1, "tapa_acceso": 1},
            "cambiar marco":                                {"marco": 1},
            "cambiar tapa y marco de acceso":               {"tapa_marco": 1},
            "revocar paredes":                              {"revoque": 1},
            "reparaciones de mampostería, fisuras":         {"revoque": 1},
            "no cierra la tapa, cambiarla":                 {"tapa": 1},
            "cambiar flotante":                             {"otras": 1},
        }
        for texto, esperado in casos.items():
            self.assertEqual(cantidades(texto), esperado, texto)

    def test_cantidades(self):
        casos = {
            "cambiar 2 tapas de acceso":                        {"tapa_acceso": 2},
            "cambiar dos tapas de acceso":                      {"tapa_acceso": 2},
            "cambiar ambas tapas de acceso":                    {"tapa_acceso": 2},
            "cambiar las dos tapas de inspección":              {"tapa_inspeccion": 2},
            "cambiar tapas de acceso":                          {"tapa_acceso": 2},
            "tapa de acceso de entrada de agua y ciego":        {"tapa_acceso": 2},
            "una tapa de acceso":                               {"tapa_acceso": 1},
        }
        for texto, esperado in casos.items():
            self.assertEqual(cantidades(texto), esperado, texto)

    def test_codigos_del_csv(self):
        items = detectar_items("TATCEA 56.5 punta recortada y TATCC 56")
        self.assertEqual(items["tapa_acceso"]["cantidad"], 2)
        self.assertEqual(items["tapa_acceso"]["variantes"], ["EA", "C"])
        self.assertEqual(items["tapa_acceso"]["codigos"], ["TATCEA 56.5", "TATCC 56"])
        self.assertEqual(cantidades("TITCEA 30, MATCEA 50 y TMTRC 49"),
                         {"tapa_inspeccion": 1, "marco": 1, "tapa_marco": 1})
        self.assertEqual(cantidades("tmtcea 49"), {"tapa_marco": 1})

    def test_codigo_pegado_a_la_medida(self):
        # Caso real: "Tapa de inspeccion y TMTCEA56" no reconocía el código
        self.assertEqual(cantidades("Tapa de inspeccion y TMTCEA56"), {"tapa_inspeccion": 1, "tapa_marco": 1})
        self.assertEqual(cantidades("tatcea56 y tatcc56,5"), {"tapa_acceso": 2})
        self.assertEqual(detectar_items("TITCEA30")["tapa_inspeccion"]["codigos"], ["TITCEA30"])

    def test_codigo_sin_medida(self):
        self.assertEqual(cantidades("TATCEA"), {"tapa_acceso": 1})
        self.assertEqual(cantidades("cambiar TITCC y TMTREA"), {"tapa_inspeccion": 1, "tapa_marco": 1})
        self.assertEqual(detectar_items("TATCEA y TATCC")["tapa_acceso"]["variantes"], ["EA", "C"])

    def test_codigo_y_texto_de_lo_mismo_es_una_sola_tapa(self):
        self.assertEqual(cantidades("cambiar tapa de acceso TATCEA 56"), {"tapa_acceso": 1})

    def test_palabras_que_contienen_marco_no_cuentan(self):
        self.assertEqual(cantidades("desmarcar la zona y revocar"), {"revoque": 1})

    def test_vacio(self):
        self.assertEqual(detectar_items(""), {})
        self.assertEqual(detectar_items(None), {})

    def test_codigo_de_otro_tanque(self):
        self.assertEqual(codigos_de_otro_tanque("TATREA 56 y TITCEA 30", "CISTERNA"), ["TATREA 56"])
        self.assertEqual(codigos_de_otro_tanque("TATREA 56", "RESERVA"), [])

    def test_mensaje_para_corregir_codigos(self):
        # Caso real: "TITREA40 TMTCEA49" en la cisterna
        msg = mensaje_codigos_de_otro_tanque("TITREA40 TMTCEA49", "CISTERNA")
        self.assertIn("• TITREA40 es de Reserva: para Cisterna es TITCEA40", msg)
        self.assertNotIn("TMTCEA49 es de", msg)
        self.assertIn("Escribí de nuevo las reparaciones de Cisterna", msg)
        self.assertIsNone(mensaje_codigos_de_otro_tanque("TITCEA40 TMTCEA49", "CISTERNA"))
        self.assertIn("TATCC 56 es de Cisterna: para Intermediario es TATHC56",
                      mensaje_codigos_de_otro_tanque("TATCC 56", "INTERMEDIARIO"))

    def test_lista_para_operario(self):
        texto = lista_para_operario(detectar_items("TATCEA 56, TATCC 56 y revocar"))
        self.assertEqual(texto, "• Tapa de acceso: entrada de agua y ciego, una foto de cada una\n• Revoque")
        self.assertEqual(lista_para_operario(detectar_items("cambiar 2 tapas de inspeccion")),
                         "• Tapa de inspección: 2 distintas, una foto de cada una")


if __name__ == "__main__":
    unittest.main()
