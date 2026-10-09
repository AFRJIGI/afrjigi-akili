"""Le BAC Technique propose les matieres de la serie de l'eleve (F2 d'abord)."""
import unittest
from unittest import mock

import main


class MatieresTechniqueTests(unittest.TestCase):
    def test_menu_f2(self):
        menu = main.menu_matieres_technique("F2")
        self.assertIn("a. Mécanique appliquée", menu)
        self.assertIn("j. Technologie et schémas", menu)
        self.assertIn("k. Informatique industrielle", menu)
        self.assertNotIn("Mécanique\n", menu)
        self.assertNotIn("Comptabilité", menu)
        self.assertTrue(menu.endswith("Réponds par a, b, c, d, e, f, g, h, i, j ou k."))

    def test_serie_inconnue_garde_la_liste_commune(self):
        for serie in ["STI", None]:
            menu = main.menu_matieres_technique(serie)
            self.assertIn("a. Comptabilité Financière", menu)
            self.assertTrue(menu.endswith("l ou m."))
        self.assertEqual(main.choix_matieres_technique(None), main.BAC_TECHNIQUE_SUBJECT_CHOICES)

    def test_chaque_serie_a_sa_liste(self):
        series = [s for s in main.BAC_TECHNIQUE_SERIES_CHOICES.values() if s != "BT"]
        series += list(main.BT_OPTIONS_CHOICES.values())  # BT : une liste par option
        for serie in series:
            matieres = main.MATIERES_TECHNIQUE_PAR_SERIE[serie]
            codes = [c for c, _ in matieres]
            self.assertLessEqual(len(matieres), 13, serie)
            self.assertEqual(len(codes), len(set(codes)), serie)
            # Le BT n'a pas d'histoire-geographie dans les documents recus.
            for code in ("FRANCAIS", "ANGLAIS") + (() if main.est_serie_bt(serie) else ("HG",)):
                self.assertIn(code, codes, serie)
            self.assertIn("MATHS", codes, serie)  # meme code que les documents de maths
            for code in codes:
                self.assertNotEqual(main.libelle_matiere(code), code, code)
        self.assertNotIn("PHILO", [c for c, _ in main.MATIERES_TECHNIQUE_PAR_SERIE["F2"]])
        self.assertEqual(main.MATIERES_TECHNIQUE_PAR_SERIE["B"][0][0], "ECO")  # SES

    def test_matiere_ecrite_en_toutes_lettres(self):
        cas = [
            ("F1", "anglais", "ANGLAIS"), ("F1", "Philo", "PHILO"),
            ("F1", "construction mécanique", "CMI"), ("F1", "mécanique", "MECANIQUE"),
            ("F2", "Mécanique appliquée", "MECANIQUE_APPLIQUEE"), ("F2", "électronique", "ELECTRONIQUE"),
            ("G2", "compta analytique", "COMPTA_ANALYTIQUE"), ("G2", "maths financières", "MATHS_FIN"),
            ("G2", "maths", "MATHS"), ("B", "SES", "ECO"), ("F4", "RDM", "RDM"),
            ("F7", "microbio", "MICROBIOLOGIE"), ("F7", "biochimie", "BIOCHIMIE"),
        ]
        for serie, texte, attendu in cas:
            lettre = main.lettre_matiere_technique(serie, texte)
            self.assertEqual(main.choix_matieres_technique(serie).get(lettre), attendu, (serie, texte))
        self.assertIsNone(main.lettre_matiere_technique("F2", "philosophie"))

    def test_anglais_ecrit_en_f1_pendant_l_inscription(self):
        profil = {"type_examen": "BAC_TECHNIQUE", "serie": "F1", "onboarding_step": "matiere"}
        with mock.patch.object(main, "send_whatsapp"), mock.patch.object(main, "sauver_etat_whatsapp"):
            self.assertTrue(main.handle_onboarding_choice("22500000021", profil, "Anglais"))
        self.assertEqual(main.user_profiles["22500000021"]["matiere"], "ANGLAIS")
        main.user_profiles.pop("22500000021", None)

    def test_anciens_profils_maths_generales(self):
        self.assertEqual(main.CODES_MATIERE_API.get("MATHS_GENERAL"), "MATHS")

    def test_choix_f2(self):
        choix = main.choix_matieres_technique("f2")
        self.assertEqual(choix["a"], "MECANIQUE_APPLIQUEE")
        self.assertEqual(choix["f"], "MATHS")  # meme code que les documents de maths techniques
        self.assertEqual(choix["h"], "ELECTRONIQUE")
        self.assertNotIn("l", choix)
        self.assertNotIn("MECANIQUE", choix.values())

    def test_etape_matiere_f2(self):
        profil = {"type_examen": "BAC_TECHNIQUE", "serie": "F2", "onboarding_step": "matiere"}
        with mock.patch.object(main, "send_whatsapp"), mock.patch.object(main, "sauver_etat_whatsapp"):
            self.assertTrue(main.handle_onboarding_choice("22500000020", profil, "h"))
        self.assertEqual(main.user_profiles["22500000020"]["matiere"], "ELECTRONIQUE")
        main.user_profiles.pop("22500000020", None)

    def test_menu_f1(self):
        menu = main.menu_matieres_technique("F1")
        self.assertIn("a. Construction mécanique industrielle (CMI)", menu)
        self.assertIn("m. Philosophie", menu)
        self.assertNotIn("Électronique", menu)
        self.assertTrue(menu.endswith("k, l ou m."))
        choix = main.choix_matieres_technique("F1")
        self.assertEqual((choix["h"], choix["m"]), ("MATHS", "PHILO"))

    def test_libelles_lisibles(self):
        for serie in ("F1", "F2"):
            for code, _ in main.MATIERES_TECHNIQUE_PAR_SERIE[serie]:
                self.assertNotEqual(main.libelle_matiere(code), code, code)


if __name__ == "__main__":
    unittest.main()
