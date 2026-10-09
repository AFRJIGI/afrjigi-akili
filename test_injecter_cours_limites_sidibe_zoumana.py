import json
import unittest

from injecter_cours_limites_sidibe_zoumana import DONNEES, documents_base, plan

PAQUET = json.loads(DONNEES.read_text(encoding="utf-8"))
DOCS = documents_base(PAQUET)


class CoursLimitesTests(unittest.TestCase):
    def test_toutes_les_seances(self):
        self.assertEqual({d["seance"] for d in DOCS}, set(range(0, 17)))  # presentation, 15 seances, exercices
        self.assertEqual(len({d["id"] for d in DOCS}), len(DOCS))
        self.assertEqual(len({d["sha256"] for d in DOCS}), len(DOCS))  # C et D ne se dedoublonnent pas

    def test_extraits_utilisables(self):
        for d in DOCS:
            self.assertLessEqual(len(d["texte"]), 2800, d["id"])  # l'API garde 2800 caracteres par document
            self.assertTrue(d["texte"].startswith("COURS DE MATHÉMATIQUES — Terminale D — Leçon 1"))
            self.assertNotIn("=== SEANCE", d["texte"])
        textes = " ".join(d["texte"] for d in DOCS)
        for notion in ["expression conjuguée", "valeurs intermédiaires", "dichotomie", "prolongement par continuité",
                       "lim (x→+∞) (√(x² + x) − x)", "[Vérification"]:
            self.assertIn(notion, textes)
        self.assertNotIn("$", textes)  # pas de LaTeX

    def test_rattachement(self):
        par_serie = {}
        for d in DOCS:
            par_serie.setdefault(d["serie"], []).append(d)
            self.assertEqual((d["matiere"], d["examen"], d["niveau"], d["type_doc"]),
                             ("MATHS", "BAC_GENERAL", "TERMINALE", "COURS_ESSENTIEL"))
        self.assertEqual(set(par_serie), {"C", "D"})
        for d in par_serie["C"]:
            self.assertIn("Terminale C", d["texte"].splitlines()[1])

    def test_pas_de_doublon(self):
        self.assertEqual(plan(DOCS, DOCS), [])
        self.assertEqual(len(plan([], DOCS)), len(DOCS))


if __name__ == "__main__":
    unittest.main()
