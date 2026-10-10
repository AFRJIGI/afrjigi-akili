"""Documents BT : documents de cours des series du BAC Technique (10 oct. : les progressions BT ne sont pas
celles des series G et F, elles ne pilotent plus le choix de la lecon). Sans Google Cloud."""
import json
import re
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
        self.assertIn("bt_telephonie_terminale_01", ids)
        self.assertIn("bt_eoe_seconde_01", ids)
        self.assertFalse(any(inj.est_ancienne_version(d) for d in self.docs))

    def test_series(self):
        series = Counter(d["serie"] for d in self.docs)
        self.assertEqual(set(series), {"F2", "G1 G2", "E F1 F2 F3 F4 F7", "B G1 G2", "B G1 G2 E F1 F2 F3 F4 F7"})
        self.assertTrue(all(d["examen"] == "BAC_TECHNIQUE" and d["priorite"] == -1 for d in self.docs))
        self.assertEqual({d["matiere"] for d in self.docs if d["serie"] == "F2"},
                         {"ELECTRONIQUE", "TECHNO_SCHEMAS", "DESSIN_INDUSTRIEL", "INFORMATIQUE_INDUSTRIELLE"})

    def test_progressions_word_du_10_octobre(self):
        word = [d for d in self.docs if d["id"].startswith("bt_word_") and "cmc_tertiaire" not in d["id"]]
        self.assertEqual(Counter(d["matiere"] for d in word),
                         Counter(FRANCAIS=14, DESSIN_INDUSTRIEL=10, INFORMATIQUE_INDUSTRIELLE=3, HG=3))
        self.assertIn("bt_word_architecture_des_systemes_informatiques_premiere", [d["id"] for d in word])
        self.assertTrue(all(re.search(r"\d{9,}", d["texte"]) is None for d in word))  # telephones retires

    def test_cmc_tertiaire(self):
        cmc = [d for d in self.docs if d["id"].startswith("bt_word_cmc_tertiaire_")]
        self.assertEqual({(d["serie"], d["matiere"]) for d in cmc}, {("B G1 G2", "HG")})
        self.assertEqual({d["niveau"] for d in cmc}, {"SECONDE", "PREMIERE", "TERMINALE"})
        self.assertTrue(all("suis la progression officielle de la série" in d["texte"] for d in cmc))

    def test_plus_aucune_progression_officielle(self):
        # Les progressions BT (M. Adia, M. Coulibaly) sont des documents de cours, lus en entier (2 800 car.).
        self.assertFalse(any(d["type_doc"].startswith("PROGRESSION") for d in self.docs))
        accompagnement = [d for d in self.docs if d["type_doc"] == "DOCUMENT_ACCOMPAGNEMENT"]
        self.assertEqual({d["type_source"] for d in accompagnement}, {"PROGRESSION_ANNUELLE"})
        self.assertTrue(all(len(d["texte"]) <= 2800 for d in self.docs))
        self.assertTrue(all("suis la progression officielle de la série" in d["texte"] for d in accompagnement))

    def test_matieres_proposees_par_le_bot(self):
        for d in self.docs:
            for serie in d["serie"].split():
                self.assertIn(f'("{d["matiere"]}", ', matieres_de_la_serie(serie), (serie, d["matiere"]))

    def test_classe_indiquee_dans_le_texte(self):
        doc = next(d for d in self.docs if d["id"] == "bt_telephonie_seconde_02")
        self.assertIn("Progression du BT Électronique (Seconde de F2), donnée à titre de cours", doc["texte"])
        self.assertTrue(doc["texte"].startswith("PROGRESSION 2026-2027 - BT Électronique, 1re année"))
        self.assertIn("(extrait 2/", doc["texte"])

    def test_retrait_de_la_version_du_9_octobre(self):
        anciens = [{"id": "bt_eln_telephonie_seconde", "serie": "BT_ELN", "sha256": "x"},
                   {"id": "sidibe_cours_meca_bt_ind_ch01_a_1", "serie": "BT_IND", "sha256": "y"},
                   {"id": "sidibe_cours_meca_ch01_a_1", "serie": "F2", "sha256": "z"},
                   {"id": "bt_telephonie_seconde", "serie": "F2", "type_doc": "PROGRESSION_ANNUELLE", "sha256": "w"}]
        self.assertEqual([inj.est_ancienne_version(d) for d in anciens], [True, True, False, True])
        self.assertEqual(len(inj.plan(anciens, self.docs)), len(self.docs))
        self.assertEqual(inj.plan(anciens + self.docs[:3], self.docs[:5]), self.docs[3:5])


if __name__ == "__main__":
    unittest.main()
