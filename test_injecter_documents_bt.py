"""Documents BT rattaches aux series du BAC Technique : identifiants, series, matieres (sans Google Cloud)."""
import json
import unittest
from collections import Counter
from pathlib import Path

import injecter_documents_bt as inj

SOURCE_BOT = Path(__file__).with_name("whatsapp_bot").joinpath("main.py").read_text(encoding="utf-8")


def matieres_de_la_serie(serie):
    debut = SOURCE_BOT.index(f'    "{serie}": [')
    return SOURCE_BOT[debut:SOURCE_BOT.index("    ],", debut)]


class DocumentsBTTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = inj.documents_paquet(json.loads(inj.DONNEES.read_text(encoding="utf-8")))

    def test_identifiants_uniques_et_aucune_serie_bt(self):
        ids = [d["id"] for d in self.docs]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("bt_telephonie_terminale", ids)
        self.assertIn("bt_eoe_seconde", ids)
        self.assertFalse(any(inj.est_ancienne_version(d) for d in self.docs))

    def test_series(self):
        series = Counter(d["serie"] for d in self.docs)
        self.assertEqual(series["F2"], 21)          # BT Electronique de M. Adia
        self.assertEqual(series["G1 G2"], 6)        # EG et EOE de M. Coulibaly
        self.assertEqual(set(series), {"F2", "G1 G2", "E F1 F2 F3 F4 F7", "B G1 G2"})
        self.assertTrue(all(d["examen"] == "BAC_TECHNIQUE" and d["priorite"] == -1 for d in self.docs))

    def test_matieres_proposees_par_le_bot(self):
        for d in self.docs:
            for serie in d["serie"].split():
                self.assertIn(f'("{d["matiere"]}", ', matieres_de_la_serie(serie), (serie, d["matiere"]))

    def test_classe_indiquee_dans_le_texte(self):
        doc = next(d for d in self.docs if d["id"] == "bt_telephonie_seconde")
        self.assertIn("Correspond au BAC Technique, série F2 (électronique), classe de Seconde.", doc["texte"])
        self.assertTrue(doc["texte"].startswith("PROGRESSION 2026-2027 - BT Électronique, 1re année"))

    def test_retrait_de_la_version_du_9_octobre(self):
        anciens = [{"id": "bt_eln_telephonie_seconde", "serie": "BT_ELN", "sha256": "x"},
                   {"id": "sidibe_cours_meca_bt_ind_ch01_a_1", "serie": "BT_IND", "sha256": "y"},
                   {"id": "sidibe_cours_meca_ch01_a_1", "serie": "F2", "sha256": "z"}]
        self.assertEqual([inj.est_ancienne_version(d) for d in anciens], [True, True, False])
        self.assertEqual(len(inj.plan(anciens, self.docs)), len(self.docs))
        self.assertEqual(inj.plan(anciens + self.docs[:3], self.docs[:5]), self.docs[3:5])


if __name__ == "__main__":
    unittest.main()
