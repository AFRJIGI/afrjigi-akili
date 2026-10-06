import unittest

from corriger_serie_cours_diaby import a_corriger


class CorrigerSerieDiabyTests(unittest.TestCase):
    def test_cibles(self):
        docs = [{"id": "diaby_cours_eco_eg_ch1_1", "serie": "BG1G2"}, {"id": "diaby_cours_eco_eg_ch1_2", "serie": "G1G2"},
                {"id": "diaby_cours_eco_eoe_ch1_1", "serie": "G1G2"}, {"id": "ses_tle_b", "serie": "B"}]
        self.assertEqual([d["id"] for d in a_corriger(docs)], ["diaby_cours_eco_eg_ch1_1"])


if __name__ == "__main__":
    unittest.main()
