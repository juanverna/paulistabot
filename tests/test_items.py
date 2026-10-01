import unittest

from tests import entorno
entorno.preparar()

from bot.services.items_reparacion import (detectar_items, codigos_de_otro_tanque, lista_para_operario,
                                           mensaje_codigos_de_otro_tanque, problemas_de_reparaciones,
                                           CODIGOS_VALIDOS)


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
            "cambiar flotante":                             {"flotante": 1},
            "Cambiar automático":                           {"automatico": 1},
            "cambiar 2 flotantes y el automatico":          {"flotante": 2, "automatico": 1},
            "TITCEA30, cambiar flotante":                   {"tapa_inspeccion": 1, "flotante": 1},
            "pintar la puerta":                             {"otras": 1},
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
        self.assertIn("• TITREA40 es de Reserva, no de Cisterna.", msg)
        self.assertNotIn("TMTCEA49 es de", msg)
        self.assertIn("Escribí de nuevo las reparaciones de Cisterna", msg)
        self.assertIsNone(mensaje_codigos_de_otro_tanque("TITCEA40 TMTCEA49", "CISTERNA"))
        self.assertIn("TATCC 56 es de Cisterna, no de Intermediario.",
                      mensaje_codigos_de_otro_tanque("TATCC 56", "INTERMEDIARIO"))

    def test_codigos_validos_son_los_del_csv(self):
        import csv
        from pathlib import Path
        ruta = Path(__file__).resolve().parent.parent / "Articulos Python - Hoja 1.csv"
        with open(ruta, encoding="utf-8") as f:
            del_csv = {fila["Codigo"] for fila in csv.DictReader(f)
                       if fila["Codigo"].isalpha() and fila["Codigo"].isupper()}
        self.assertEqual(set(CODIGOS_VALIDOS), del_csv)

    def test_codigo_mal_escrito(self):
        # Caso real: "taticea30" pasaba como "Otras reparaciones"
        msg = problemas_de_reparaciones("taticea30", "CISTERNA")
        self.assertTrue(msg.startswith('⚠️ "taticea30" no es un código válido.\n\nUsá los códigos establecidos'), msg)
        self.assertNotIn("quisiste", msg)
        self.assertIn("Usá los códigos establecidos", msg)
        self.assertIn("Escribí de nuevo las reparaciones de Cisterna", msg)
        # Aunque haya otro código bien escrito
        self.assertIn('"TMTCXA49"', problemas_de_reparaciones("TITCEA30 y TMTCXA49", "CISTERNA") or "")

    def test_texto_que_no_es_ningun_item(self):
        msg = problemas_de_reparaciones("pintar la puerta", "RESERVA")
        self.assertIn('No entiendo a qué reparación te referís con "pintar la puerta"', msg)
        self.assertIn("flotante o automático", msg)
        self.assertIn("&lt;b&gt;", problemas_de_reparaciones("<b>hola</b>", "RESERVA"))  # escapado

    def test_reparaciones_que_se_entienden(self):
        for texto in ("TITCEA30 y TMTCEA49", "tatcea56", "cambiar tapa de acceso", "revocar paredes",
                      "tapa y marco de acceso", "cambiar tapa de inspeccion TITCEA 40", "no cierra la tapa",
                      "comprar materiales y revocar", "cambiar 2 tapas de acceso", "Tapas de inspeccion",
                      "cambiar marcos y tapas", "revocar mamposteria del tanque", "TMTCEA 49 matafuego",
                      "cambiar flotante", "cambiar automático", "flotante y automatico"):
            self.assertIsNone(problemas_de_reparaciones(texto, "CISTERNA"), texto)

    def test_flotante_y_automatico_en_cualquier_tanque(self):
        for tanque in ("CISTERNA", "RESERVA", "INTERMEDIARIO"):
            self.assertIsNone(problemas_de_reparaciones("cambiar flotante y automatico", tanque), tanque)
        self.assertEqual(lista_para_operario(detectar_items("cambiar flotante y automático")),
                         "• Flotante\n• Automático")

    def test_otro_tanque_y_mal_escrito_juntos(self):
        msg = problemas_de_reparaciones("TITREA40 y taticea30", "CISTERNA")
        self.assertIn("• TITREA40 es de Reserva, no de Cisterna.", msg)
        self.assertIn('"taticea30" no es un código válido', msg)

    def test_lista_para_operario(self):
        texto = lista_para_operario(detectar_items("TATCEA 56, TATCC 56 y revocar"))
        self.assertEqual(texto, "• Tapa de acceso: entrada de agua y ciego, una foto de cada una\n• Revoque")
        self.assertEqual(lista_para_operario(detectar_items("cambiar 2 tapas de inspeccion")),
                         "• Tapa de inspección: 2 distintas, una foto de cada una")


if __name__ == "__main__":
    unittest.main()
