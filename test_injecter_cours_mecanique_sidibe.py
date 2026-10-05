import json
import unittest

from injecter_cours_mecanique_sidibe import DONNEES, documents_base, plan

PAQUET = json.loads(DONNEES.read_text(encoding="utf-8"))
DOCS = documents_base(PAQUET)


class CoursMecaniqueTests(unittest.TestCase):
    def test_tous_les_chapitres(self):
        self.assertEqual({d["chapitre"] for d in DOCS}, set(range(0, 14)))
        for chapitre in range(1, 14):
            morceaux = sorted(d["texte"] for d in DOCS if d["chapitre"] == chapitre)
            self.assertTrue(morceaux, chapitre)

    def test_extraits_utilisables(self):
        self.assertEqual(len({d["id"] for d in DOCS}), len(DOCS))
        for d in DOCS:
            self.assertLessEqual(len(d["texte"]), 2800, d["id"])  # l'API garde 2800 caracteres par document
            self.assertTrue(d["texte"].startswith("COURS DE MÉCANIQUE APPLIQUÉE / RDM"))
            self.assertNotIn("=== CHAPITRE", d["texte"])
        textes = " ".join(d["texte"] for d in DOCS)
        for notion in ["σ = N / S", "ε = ΔL / L_0", "σ = E·ε", "τ = T / S", "Varignon", "Culman",
                       "M_A(→F) = F · d", "T ≤ 314159,26 N", "d_R ≈ 3,76 m"]:
            self.assertIn(notion, textes)
        self.assertNotIn("= 16000 N   soit", textes)  # erreur de calcul de la fiche corrigee

    def test_rattachement(self):
        for d in DOCS:
            self.assertEqual((d["matiere"], d["examen"], d["serie"], d["type_doc"]),
                             ("MECANIQUE_APPLIQUEE", "BAC_TECHNIQUE", "F2", "COURS_ESSENTIEL"))

    def test_pas_de_doublon(self):
        self.assertEqual(plan(DOCS, DOCS), [])
        self.assertEqual(len(plan([], DOCS)), len(DOCS))


if __name__ == "__main__":
    unittest.main()
