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


if __name__ == "__main__":
    unittest.main()
