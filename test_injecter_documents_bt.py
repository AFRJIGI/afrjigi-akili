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
        self.assertEqual(set(series), {"F2", "G1 G2", "E F1 F2 F3 F4 F7", "B G1 G2", "B G1 G2 E F1 F2 F3 F4 F7",
                                       "F3", "E", "E F1 F2 F3 F4 F7 G2"})
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
        bt = [d for d in self.docs if d["id"].startswith("bt_")]
        self.assertEqual(len(bt), len(self.docs) - 3)
        self.assertFalse(any(d["type_doc"].startswith("PROGRESSION") for d in bt))
        accompagnement = [d for d in self.docs if d["type_doc"] == "DOCUMENT_ACCOMPAGNEMENT"]
        self.assertEqual({d["type_source"] for d in accompagnement}, {"PROGRESSION_ANNUELLE"})
        self.assertTrue(all(len(d["texte"]) <= 2800 for d in bt))
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


class ProgressionsDesSeriesTests(unittest.TestCase):
    """Dossier Progressions_terminale_E (10 oct.) : progressions METFPA des series, annees precedentes."""

    @classmethod
    def setUpClass(cls):
        docs = inj.documents_paquet(json.loads(inj.DONNEES.read_text(encoding="utf-8")))
        cls.progs = {d["id"]: d for d in docs if d["id"].startswith("tech_prog_")}

    def test_trois_progressions_de_terminale(self):
        self.assertEqual({(d["serie"], d["matiere"], d["annee"]) for d in self.progs.values()},
                         {("F3", "PHYSIQUE_APPLIQUEE", "2023-2024"), ("E", "PHILO", "2022-2023"),
                          ("E F1 F2 F3 F4 F7 G2", "FRANCAIS", "2024-2025")})
        for d in self.progs.values():
            self.assertEqual((d["type_doc"], d["niveau"], d["priorite"], d["examen"]),
                             ("PROGRESSION_ANNUELLE", "TERMINALE", -1, "BAC_TECHNIQUE"))
            self.assertLessEqual(len(d["texte"]), 7000)              # l'API lit 7 000 car. d'une progression
            self.assertIn("suis l'ordre des leçons", d["texte"])
            self.assertIsNone(re.search(r"\d{9,}", d["texte"]))      # telephones retires
            self.assertFalse(inj.est_ancienne_version(d))

    def test_texte_lisible(self):
        phys = self.progs["tech_prog_physique_appliquee_f3_terminale"]["texte"]
        self.assertIn("=== DEUXIEME SEMESTRE ===", phys)
        self.assertIn("APPLIQUER LA 3EME LOI DE KEPLER", phys)
        self.assertNotIn("NOM ET PRENOMS", phys)
        self.assertIn("Leçon 2 : Le commentaire de texte philosophique", self.progs["tech_prog_philo_e_terminale"]["texte"])

    def test_progressions_deja_en_base(self):
        philo = self.progs["tech_prog_philo_e_terminale"]
        base = [{"id": "x", "type_doc": "PROGRESSION_ANNUELLE", "examen": "BAC_TECHNIQUE", "matiere": "PHILO",
                 "serie": "E", "niveau": "TERMINALE"},
                {"id": "y", "type_doc": "PROGRESSION_ANNUELLE", "examen": "BAC_TECHNIQUE", "matiere": "PHILO",
                 "serie": "G1G2", "niveau": "TERMINALE"},
                {"id": "z", "type_doc": "DOCUMENT_ACCOMPAGNEMENT", "examen": "BAC_TECHNIQUE", "matiere": "PHILO",
                 "serie": "E", "niveau": "TERMINALE"}, philo]
        self.assertEqual([d["id"] for d in inj.progressions_en_place(base, philo)], ["x"])
        francais = self.progs["tech_prog_francais_e_f1_f2_f3_f4_f7_g2_terminale"]
        self.assertEqual(len(inj.progressions_en_place([dict(base[1], matiere="FRANCAIS")], francais)), 1)


if __name__ == "__main__":
    unittest.main()
