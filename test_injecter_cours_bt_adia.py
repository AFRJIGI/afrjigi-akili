"""Cours du BT Electronique de M. Adia (14 oct.) : rattachement a F2, classes, taille des extraits."""
import json
import re
import unittest
from collections import Counter
from pathlib import Path

import injecter_cours_bt_adia as inj

SOURCE_BOT = Path(__file__).with_name("whatsapp_bot").joinpath("main.py").read_text(encoding="utf-8")


class CoursAdiaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = inj.documents_paquet(json.loads(inj.DONNEES.read_text(encoding="utf-8")))

    def test_rattachement(self):
        self.assertEqual({d["serie"] for d in self.docs}, {"F2"})
        self.assertEqual(Counter((d["discipline"], d["niveau"]) for d in self.docs).keys(),
                         {("TELEPHONIE", "SECONDE"), ("TELEPHONIE", "PREMIERE"), ("TELEPHONIE", "TERMINALE"),
                          ("RADIO_TV", "SECONDE"), ("RADIO_TV", "PREMIERE"), ("RADIO_TV", "TERMINALE"),
                          ("ASI", "PREMIERE"), ("ASI", "TERMINALE"), ("TIR", "PREMIERE"), ("TIR", "TERMINALE")})
        self.assertEqual({d["matiere"] for d in self.docs}, {"ELECTRONIQUE", "INFORMATIQUE_INDUSTRIELLE"})
        debut = SOURCE_BOT.index('    "F2": [')
        liste_f2 = SOURCE_BOT[debut:SOURCE_BOT.index("    ],", debut)]
        for matiere in {d["matiere"] for d in self.docs}:
            self.assertIn(f'("{matiere}", ', liste_f2)

    def test_extraits(self):
        ids = [d["id"] for d in self.docs]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreater(len(self.docs), 200)
        self.assertTrue(all(len(d["texte"]) <= 2800 for d in self.docs))  # lus en entier par l'API
        self.assertTrue(all(d["type_doc"] == "COURS_ESSENTIEL" for d in self.docs))
        self.assertTrue(all("suis la progression officielle de la série" in d["texte"] for d in self.docs))
        self.assertTrue(all(re.search(r"(?<!\d)(\d{2}[ .]?){4}\d{2}(?!\d)", d["texte"]) is None for d in self.docs))
        self.assertFalse(any("PROFESSEUR : Monsieur" in d["texte"] or "Page 3 sur" in d["texte"] for d in self.docs))

    def test_plan(self):
        self.assertEqual(inj.plan(self.docs[:5], self.docs[:8]), self.docs[5:8])


if __name__ == "__main__":
    unittest.main()
