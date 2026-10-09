"""Documents BT : identifiants, series et annees des documents ajoutes a la base (sans Google Cloud)."""
import json
import unittest
from collections import Counter

import injecter_documents_bt as inj


class DocumentsBTTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = inj.documents_paquet(json.loads(inj.DONNEES.read_text(encoding="utf-8")))
        cls.meca = inj.documents_meca_bt()

    def test_identifiants_uniques(self):
        ids = [d["id"] for d in self.docs + self.meca]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("bt_eln_telephonie_terminale", ids)
        self.assertIn("bt_ter_eoe_seconde", ids)

    def test_progressions_par_option_et_annee(self):
        progressions = Counter((d["serie"], d["niveau"]) for d in self.docs if d["type_doc"] == "PROGRESSION_ANNUELLE")
        for annee in ("SECONDE", "PREMIERE", "TERMINALE"):
            self.assertEqual(progressions[("BT_ELN", annee)], 7, annee)   # 7 matieres d'electronique par annee
            self.assertEqual(progressions[("BT_TER", annee)], 2, annee)   # EG et EOE
        self.assertTrue(all(d["examen"] == "BAC_TECHNIQUE" for d in self.docs))

    def test_matieres_connues_du_bot(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).with_name("whatsapp_bot")))
        source = Path(__file__).with_name("whatsapp_bot").joinpath("main.py").read_text(encoding="utf-8")
        for d in self.docs:
            for serie in d["serie"].split():
                self.assertIn(f'("{d["matiere"]}", ', source[source.index(f'"{serie}": ['):], (serie, d["matiere"]))

    def test_programmes_de_maths_en_extraits(self):
        maths = [d for d in self.docs if d["type_doc"] == "PROGRAMME"]
        self.assertTrue(maths and all(d["matiere"] == "MATHS" and len(d["texte"]) <= 2800 for d in maths))
        self.assertEqual({d["serie"] for d in maths}, {"BT_ELN BT_IND", "BT_TER"})

    def test_mecanique_pour_le_bt_industriel(self):
        self.assertTrue(self.meca)
        self.assertTrue(all(d["serie"] == "BT_IND" and d["matiere"] == "MECANIQUE_APPLIQUEE" for d in self.meca))
        self.assertTrue(all(d["id"].startswith("sidibe_cours_meca_bt_ind_") for d in self.meca))
        self.assertIn("Utilisé aussi en BT industriel", self.meca[0]["texte"])

    def test_plan_ignore_les_documents_deja_presents(self):
        self.assertEqual(inj.plan(self.docs[:3], self.docs[:5]), self.docs[3:5])


if __name__ == "__main__":
    unittest.main()
