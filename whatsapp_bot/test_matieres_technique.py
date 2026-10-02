"""Le BAC Technique propose les matieres de la serie de l'eleve (F2 d'abord)."""
import unittest
from unittest import mock

import main


class MatieresTechniqueTests(unittest.TestCase):
    def test_menu_f2(self):
        menu = main.menu_matieres_technique("F2")
        self.assertIn("a. Mécanique appliquée", menu)
        self.assertIn("j. Technologie et schémas", menu)
        self.assertIn("l. Informatique industrielle", menu)
        self.assertNotIn("Comptabilité", menu)
        self.assertTrue(menu.endswith("Réponds par a, b, c, d, e, f, g, h, i, j, k ou l."))

    def test_autres_series_gardent_la_liste_actuelle(self):
        for serie in ["B", "G1", "G2", "E", "F1", "F3", "F4", "F7", None]:
            menu = main.menu_matieres_technique(serie)
            self.assertIn("a. Comptabilité Financière", menu)
            self.assertTrue(menu.endswith("l ou m."))
        self.assertEqual(main.choix_matieres_technique("G1"), main.BAC_TECHNIQUE_SUBJECT_CHOICES)

    def test_choix_f2(self):
        choix = main.choix_matieres_technique("f2")
        self.assertEqual(choix["a"], "MECANIQUE_APPLIQUEE")
        self.assertEqual(choix["f"], "MATHS")  # meme code que les documents de maths techniques
        self.assertEqual(choix["h"], "ELECTRONIQUE")
        self.assertNotIn("m", choix)

    def test_etape_matiere_f2(self):
        profil = {"type_examen": "BAC_TECHNIQUE", "serie": "F2", "onboarding_step": "matiere"}
        with mock.patch.object(main, "send_whatsapp"), mock.patch.object(main, "sauver_etat_whatsapp"):
            self.assertTrue(main.handle_onboarding_choice("22500000020", profil, "h"))
        self.assertEqual(main.user_profiles["22500000020"]["matiere"], "ELECTRONIQUE")
        main.user_profiles.pop("22500000020", None)

    def test_libelles_lisibles(self):
        for code, _ in main.MATIERES_TECHNIQUE_PAR_SERIE["F2"]:
            self.assertNotEqual(main.libelle_matiere(code), code, code)


if __name__ == "__main__":
    unittest.main()
