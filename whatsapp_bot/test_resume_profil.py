"""Le message "Profil pret" montre le profil en clair, avec la classe."""
import unittest

import main


class ResumeProfilTests(unittest.TestCase):
    def test_bac_technique_avec_classe(self):
        p = {"type_examen": "BAC_TECHNIQUE", "serie": "F2", "classe": "SECONDE", "matiere": "MATHS_GENERAL", "mode": "etude"}
        self.assertEqual(main.resume_profil(p), "BAC Technique, série F2, Seconde, Mathématiques générales, mode étude")
        p = {"type_examen": "BAC_TECHNIQUE", "serie": "F1", "matiere": "CMI", "mode": "examen"}
        self.assertEqual(main.resume_profil(p), "BAC Technique, série F1, Construction mécanique industrielle, mode examen")

    def test_autres_niveaux(self):
        self.assertEqual(main.resume_profil({"type_examen": "BAC_GENERAL", "serie": "D", "matiere": "PC", "mode": "etude"}),
                         "BAC Général, Terminale D, Physique-Chimie, mode étude")
        self.assertEqual(main.resume_profil({"type_examen": "BEPC", "serie": "BEPC", "matiere": "FRENCH", "mode": "examen"}),
                         "BEPC (3e), Français, mode examen")
        self.assertEqual(main.resume_profil({"type_examen": "CLASSE_INTERMEDIAIRE", "serie": "PREMIERE_D", "matiere": "SVT"}),
                         "Première D, SVT, mode étude")
        self.assertNotIn("_", main.resume_profil({}))


if __name__ == "__main__":
    unittest.main()
