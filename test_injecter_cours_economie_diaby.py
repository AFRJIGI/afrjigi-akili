import json
import re
import unittest

from injecter_cours_economie_diaby import DONNEES, documents_base, plan

PAQUET = json.loads(DONNEES.read_text(encoding="utf-8"))
DOCS = documents_base(PAQUET)


class CoursEconomieTests(unittest.TestCase):
    def test_tous_les_chapitres(self):
        par_partie = {}
        for d in DOCS:
            par_partie.setdefault(d["partie"], set()).add(d["chapitre"])
        self.assertEqual(par_partie["Économie générale"], set(range(1, 10)))
        self.assertEqual(par_partie["Économie et organisation des entreprises"], set(range(1, 9)))

    def test_extraits_utilisables(self):
        self.assertEqual(len({d["id"] for d in DOCS}), len(DOCS))
        for d in DOCS:
            self.assertLessEqual(len(d["texte"]), 2800, d["id"])  # l'API garde 2800 caracteres par document
            self.assertNotRegex(d["texte"], r"\.{5,}")             # pas de lignes de sommaire
            self.assertTrue(d["texte"].startswith("COURS D'ÉCONOMIE"))
        textes = " ".join(d["texte"] for d in DOCS)
        for notion in ["P + M = CF + CI + FBCF", "Bretton", "balance des paiements", "Porter"]:
            self.assertIn(notion.lower(), textes.lower())

    def test_series(self):
        for d in DOCS:
            attendu = "G1G2"  # la serie B a son programme SES : pas ce support de BTS
            self.assertEqual(d["serie"], attendu)
            self.assertEqual((d["matiere"], d["examen"], d["type_doc"]), ("ECO", "BAC_TECHNIQUE", "COURS_ESSENTIEL"))

    def test_pas_de_doublon(self):
        self.assertEqual(plan(DOCS, DOCS), [])
        self.assertEqual(len(plan([], DOCS)), len(DOCS))


if __name__ == "__main__":
    unittest.main()
