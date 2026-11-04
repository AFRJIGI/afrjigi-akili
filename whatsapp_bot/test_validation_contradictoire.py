import unittest
import main


class ValidationContradictoireTests(unittest.TestCase):
    def test_exact_puis_autre_lettre_est_corrige(self):
        t = "C'est exact! La bonne réponse est A : un marché de consommation est un avantage."
        self.assertTrue(main.retirer_validation_contradictoire(t, "B").startswith("Pas tout à fait. La bonne réponse est A"))

    def test_exact_puis_meme_lettre_reste_valide(self):
        # controle qualite du 4 nov. : l'eleve a raison, on ne le contredit pas
        for t, rep in [("C'est exact ! La bonne réponse est la lettre *d* (g = P / m = 10 N/kg).", "D"),
                       ("Exact! La bonne réponse est la lettre b (m = 1500 g).", "b"),
                       ("C'est exact ! La bonne réponse est la *(a)* : P = 7,5 N.", "A")]:
            self.assertEqual(main.retirer_validation_contradictoire(t, rep), t)

    def test_lettre_citee_sans_reponse_courte_inchange(self):
        t = "C'est exact! La bonne réponse est A."
        self.assertEqual(main.retirer_validation_contradictoire(t, "je pense que c'est la premiere"), t)
        self.assertEqual(main.retirer_validation_contradictoire(t), t)

    def test_negation_explicite_est_corrigee(self):
        t = "C'est exact! En réalité, la masse ne change pas."
        self.assertTrue(main.retirer_validation_contradictoire(t, "c").startswith("Pas tout à fait."))

    def test_exact_sans_correction_inchange(self):
        t = "C'est exact! Un marché de consommation écoule la production."
        self.assertEqual(main.retirer_validation_contradictoire(t, "a"), t)

    def test_pas_de_validation_inchange(self):
        t = "Pas tout à fait. La bonne réponse est A."
        self.assertEqual(main.retirer_validation_contradictoire(t, "a"), t)


if __name__ == "__main__":
    unittest.main()
