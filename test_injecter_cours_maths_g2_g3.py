"""Cours harmonises de mathematiques generales G2-G3 (M. Brou, 22 oct.) : rattachement, classes, extraits."""
import json
import re
import unittest
from collections import Counter
from pathlib import Path

import injecter_cours_maths_g2_g3 as inj

SOURCE_BOT = Path(__file__).with_name("whatsapp_bot").joinpath("main.py").read_text(encoding="utf-8")


class CoursMathsG2G3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = inj.documents_paquet(json.loads(inj.DONNEES.read_text(encoding="utf-8")))

    def test_rattachement(self):
        self.assertEqual({(d["matiere"], d["examen"], d["serie"]) for d in self.docs}, {("MATHS", "BAC_TECHNIQUE", "G2")})
        self.assertEqual(set(Counter(d["niveau"] for d in self.docs)), {"SECONDE", "PREMIERE", "TERMINALE"})
        debut = SOURCE_BOT.index('    "G2": [')
        self.assertIn('("MATHS", ', SOURCE_BOT[debut:SOURCE_BOT.index("    ],", debut)])

    def test_chapitres_de_terminale(self):
        chapitres = {d["titre_chapitre"] for d in self.docs if d["niveau"] == "TERMINALE"}
        for titre in ["FONCTION LOGARITHME NEPERIEN", "PRIMITIVES ET CALCUL INTEGRAL", "DENOMBREMENT ET PROBABILITE"]:
            self.assertTrue(any(titre in c for c in chapitres), titre)

    def test_extraits(self):
        ids = [d["id"] for d in self.docs]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreater(len(self.docs), 150)
        self.assertTrue(all(len(d["texte"]) <= 2800 for d in self.docs))
        self.assertTrue(all(d["type_doc"] == "COURS_ESSENTIEL" for d in self.docs))
        self.assertTrue(all("suis la progression de sa classe" in d["texte"] for d in self.docs))
        tout = json.dumps(self.docs, ensure_ascii=False)
        self.assertNotIn("TEHUA", tout.upper())
        self.assertIsNone(re.search(r"\S+@\S+\.\w+", tout))
        self.assertNotIn("𝑥", tout)  # lettres mathematiques ramenees au texte simple (NFKC)

    def test_plan(self):
        self.assertEqual(inj.plan(self.docs[:5], self.docs[:8]), self.docs[5:8])


if __name__ == "__main__":
    unittest.main()
