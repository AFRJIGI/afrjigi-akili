import unittest
import main


class ValidationContradictoireTests(unittest.TestCase):
    def test_exact_puis_correction(self):
        t = "C'est exact! La bonne réponse est A : un marché de consommation est un avantage."
        self.assertTrue(main.retirer_validation_contradictoire(t).startswith("Pas tout à fait. La bonne réponse est A"))

    def test_exact_sans_correction_inchange(self):
        t = "C'est exact! Un marché de consommation écoule la production."
        self.assertEqual(main.retirer_validation_contradictoire(t), t)

    def test_pas_de_validation_inchange(self):
        t = "Pas tout à fait. La bonne réponse est A."
        self.assertEqual(main.retirer_validation_contradictoire(t), t)


if __name__ == "__main__":
    unittest.main()
