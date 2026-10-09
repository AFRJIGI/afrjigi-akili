"""BT (Brevet de Technicien) dans le BAC Technique (precision de Daouda, 9 oct. : « BAC Technique,
l'abreviation c'est BT » ; tous les documents BT doivent etre pris en compte)."""
import unittest

import espace_enseignant
import main
from test_inscription_courte import PHONE, Base


class InscriptionBTTests(Base):
    def test_bac_technique_puis_bt_puis_option_puis_annee(self):
        profil = {"onboarding_step": "exam", "serie": "TOUTES"}
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "c"))   # BAC Technique / BT
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "j"))   # BT
        self.assertEqual(profil["onboarding_step"], "serie_bt")
        self.assertIn("Quel BT ?", self.envoyes[-1])
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "a"))   # BT Electronique
        self.assertEqual((profil["serie"], profil["onboarding_step"]), ("BT_ELN", "classe_technique"))
        self.assertIn("quelle année de BT", self.envoyes[-1])
        self.assertIn("3e année", self.envoyes[-1])
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "c"))   # 3e annee
        self.assertEqual(profil["classe"], "TERMINALE")
        self.assertEqual(profil["onboarding_step"], "matiere")
        self.assertIn("Électronique analogique", self.envoyes[-1])
        self.assertIn("Radio-télévision", self.envoyes[-1])
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "f"))   # Telephonie
        self.assertEqual(profil["matiere"], "TELEPHONIE")
        self.assertIn("Profil prêt : BT Électronique, 3e année, Téléphonie", self.envoyes[-1])

    def test_bt_ecrit_en_toutes_lettres(self):
        # Controle qualite du 9 oct. : « 3eme annee BT electronique » etait inscrit en BEPC maths.
        profil = {"onboarding_step": "exam", "serie": "TOUTES"}
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "3eme année BT électronique"))
        self.assertEqual((profil["type_examen"], profil["serie"], profil["classe"]),
                         ("BAC_TECHNIQUE", "BT_ELN", "TERMINALE"))
        self.assertEqual(profil["onboarding_step"], "matiere")

    def test_le_mot_bt_choisit_le_bac_technique(self):
        profil = {"onboarding_step": "exam", "serie": "TOUTES"}
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "BT"))
        self.assertEqual((profil["type_examen"], profil["onboarding_step"]), ("BAC_TECHNIQUE", "serie_technique"))

    def test_bt_tertiaire(self):
        profil = {"onboarding_step": "serie_bt", "type_examen": "BAC_TECHNIQUE"}
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "c"))
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "a"))  # 1re annee
        self.assertEqual((profil["serie"], profil["classe"]), ("BT_TER", "SECONDE"))
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "b"))
        self.assertEqual(profil["matiere"], "EOE")


class NiveauBTTests(unittest.TestCase):
    def test_niveaux_declares(self):
        cas = {
            "3eme année BT électronique": ("BT_ELN", "TERMINALE"),
            "je suis en 1A BT ELN": ("BT_ELN", "SECONDE"),
            "2BT tertiaire": ("BT_TER", "PREMIERE"),
            "je suis en BT électrotechnique 2e année": ("BT_IND", "PREMIERE"),
            "je fais le BT compta": ("BT_TER", ""),
        }
        for texte, (serie, classe) in cas.items():
            niveau = main.niveau_declare(texte)
            self.assertIsNotNone(niveau, texte)
            self.assertEqual((niveau["type_examen"], niveau["serie"], niveau["classe"]),
                             ("BAC_TECHNIQUE", serie, classe), texte)

    def test_pas_de_faux_bt(self):
        for texte in ("je suis en BT", "BAC technique G2", "j'ai 3 BTS", "exercice de compta sur la TVA"):
            niveau = main.niveau_declare(texte)
            self.assertFalse(niveau and main.est_serie_bt(niveau.get("serie")), texte)

    def test_hors_champ(self):
        self.assertFalse(main.is_other_or_concours("je suis en BT électronique"))
        self.assertTrue(main.is_other_or_concours("je suis en CAP"))
        self.assertTrue(main.is_other_or_concours("Certificat d'aptitude professionnelle"))
        self.assertTrue(main.is_other_or_concours("2e année de BTS"))
        self.assertFalse(main.is_other_or_concours("capacité thermique"))
        self.assertIn("BT compris", main.MESSAGE_HORS_CHAMP)
        self.assertIn("Le CAP, le BTS et l'université ne sont pas encore disponibles", main.MESSAGE_HORS_CHAMP)

    def test_libelles(self):
        profil = {"type_examen": "BAC_TECHNIQUE", "serie": "BT_IND", "classe": "PREMIERE", "matiere": "MATHS"}
        self.assertTrue(main.resume_profil(profil).startswith("BT Industriel, 2e année, Mathématiques"))
        consigne = main.consigne_matiere_choisie("EOE", "BT_TER", "BAC_TECHNIQUE", "SECONDE")
        self.assertIn("BT Tertiaire, 1re année", consigne)
        self.assertNotIn("série BT_TER", consigne)
        # Les autres series ne changent pas.
        self.assertTrue(main.resume_profil({"type_examen": "BAC_TECHNIQUE", "serie": "F2", "classe": "SECONDE",
                                            "matiere": "MATHS"}).startswith("BAC Technique, série F2, Seconde"))

    def test_libelles_des_nouvelles_matieres(self):
        for option in main.BT_OPTIONS_CHOICES.values():
            for code, _ in main.matieres_technique(option):
                self.assertNotEqual(main.libelle_matiere(code), code, code)


class EnseignantBTTests(unittest.TestCase):
    def test_classes_bt(self):
        cas = {"1A BT ELN": ("BT_ELN", "SECONDE"), "3BT ELN": ("BT_ELN", "TERMINALE"),
               "2 BT tertiaire": ("BT_TER", "PREMIERE"), "1ère année BT électrotechnique": ("BT_IND", "SECONDE")}
        for libelle, (serie, classe) in cas.items():
            self.assertEqual(espace_enseignant.classe_vers_profil(libelle),
                             {"type_examen": "BAC_TECHNIQUE", "serie": serie, "classe": classe}, libelle)
        self.assertEqual(espace_enseignant.classe_vers_profil("2nde F2")["serie"], "F2")


if __name__ == "__main__":
    unittest.main()
