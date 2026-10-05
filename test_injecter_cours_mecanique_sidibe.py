import json
import unittest

from injecter_cours_mecanique_sidibe import DONNEES, documents_base, plan

PAQUET = json.loads(DONNEES.read_text(encoding="utf-8"))
DOCS = documents_base(PAQUET)


class CoursMecaniqueTests(unittest.TestCase):
    def test_tous_les_chapitres(self):
        self.assertEqual({d["chapitre"] for d in DOCS}, set(range(0, 14)))
        self.assertEqual(len({d["sha256"] for d in DOCS}), len(DOCS))  # F1 et F2 ne se dedoublonnent pas
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
        par_serie = {}
        for d in DOCS:
            par_serie.setdefault((d["serie"], d["matiere"]), []).append(d)
            self.assertEqual((d["examen"], d["type_doc"]), ("BAC_TECHNIQUE", "COURS_ESSENTIEL"))
        self.assertEqual(set(par_serie), {("F2", "MECANIQUE_APPLIQUEE"), ("F1", "MECANIQUE")})
        self.assertEqual(len(par_serie["F2", "MECANIQUE_APPLIQUEE"]), len(PAQUET["documents"]))
        self.assertEqual(len(par_serie["F1", "MECANIQUE"]), len(PAQUET["documents"]))
        for d in par_serie["F1", "MECANIQUE"]:
            self.assertIn("série F1", d["texte"].splitlines()[1])
            self.assertTrue(d["id"].startswith("sidibe_cours_meca_f1_"))

    def test_pas_de_doublon(self):
        self.assertEqual(plan(DOCS, DOCS), [])
        self.assertEqual(len(plan([], DOCS)), len(DOCS))


if __name__ == "__main__":
    unittest.main()
