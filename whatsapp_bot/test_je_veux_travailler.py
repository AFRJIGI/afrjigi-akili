"""Controle qualite du 8 nov. (…3417) : « Je veux travailler en français » change la matiere du profil."""
import unittest

import main

PROFIL_A2_PHILO = {"type_examen": "BAC_GENERAL", "serie": "A2", "matiere": "PHILO"}


class JeVeuxTravaillerTests(unittest.TestCase):
    def test_changement_reconnu(self):
        for texte in ("Je veux travailler en français", "je voudrais étudier le français", "On travaille le français",
                      "Je veux réviser en français", "Travaillons le français"):
            self.assertTrue(main.est_demande_changement_matiere(texte, "PHILO"), texte)
            self.assertEqual(main.matiere_demandee(PROFIL_A2_PHILO, texte), "FRANCAIS", texte)

    def test_pas_de_changement_dans_la_meme_matiere_ou_sans_matiere(self):
        for texte, actuelle in (("Je veux travailler en français", "FRANCAIS"),
                                ("Je veux travailler les limites", "MATHS"),
                                ("Je veux travailler la dissertation", "PHILO"),
                                ("Je veux travailler la dissertation de philo", "PHILO")):
            self.assertFalse(main.est_demande_changement_matiere(texte, actuelle), texte)

    def test_refus_de_matiere_inchange(self):
        self.assertIsNone(main.matiere_demandee(PROFIL_A2_PHILO, "je veux plus de français"))


if __name__ == "__main__":
    unittest.main()
