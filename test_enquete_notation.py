import unittest

from enquete_notation import analyser


class EnqueteNotationTests(unittest.TestCase):
    def test_analyse(self):
        messages = [
            {"direction": "outbound", "matiere": "MATHS", "text": "On a √(3)2 et x \\leq 3 avec u_n+1"},
            {"direction": "outbound", "matiere": "MATHS", "text": "La dérivée vaut 2x + 1."},
            {"direction": "outbound", "matiere": "PC", "text": "C = 0,1 mol.L^-1"},
            {"direction": "outbound", "matiere": "PHILO", "text": "\\textbf{Kant}"},
            {"direction": "inbound", "matiere": "MATHS", "phone": "2250701020304", "text": "je comprends pas ce symbole"},
        ]
        par_matiere, exemples, plaintes = analyser(messages, {"MATHS", "PC"})
        self.assertEqual((par_matiere["MATHS"]["messages"], par_matiere["MATHS"]["avec_defaut"]), (2, 1))
        self.assertIn("racine collee (√(3)2)", par_matiere["MATHS"]["defauts"])
        self.assertIn("exposant ^ non converti", par_matiere["PC"]["defauts"])
        self.assertNotIn("PHILO", par_matiere)
        self.assertEqual(plaintes[0][1], "…0304")


class TracesEtEnsemblesTests(unittest.TestCase):
    def test_traces_du_bot_et_ensembles_ignores(self):
        messages = [
            {"direction": "outbound", "matiere": "MATHS", "text": "[vector_formula_image]"},
            {"direction": "outbound", "matiere": "MATHS", "text": "[audio_reply]"},
            {"direction": "outbound", "matiere": "MATHS", "text": "Df = ℝ privé de {3}. Et {-1 ; 1} ?"},
            {"direction": "outbound", "matiere": "MATHS", "text": "Df = ℝ setminus {3} et x^{2}"},
        ]
        par_matiere, _, _ = analyser(messages, {"MATHS"})
        stats = par_matiere["MATHS"]
        self.assertEqual(stats["messages"], 2)
        self.assertEqual(stats["avec_defaut"], 1)
        self.assertIn("commande LaTeX restee en mot (setminus, mathbb...)", stats["defauts"])
        self.assertIn("accolades { }", stats["defauts"])


if __name__ == "__main__":
    unittest.main()
