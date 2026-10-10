"""BT = BAC Technique (precision de Daouda, 9 oct.) : tertiaire = series B, G1, G2 ; industriel = E et F.
Les classes restent Seconde, Premiere, Terminale ; « 1re, 2e, 3e annee BT » y correspondent."""
import unittest

import espace_enseignant
import main
from test_inscription_courte import PHONE, Base


class InscriptionBTTests(Base):
    def test_series_avec_tertiaire_et_industriel(self):
        profil = {"onboarding_step": "exam", "serie": "TOUTES"}
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "c"))   # BAC Technique (BT)
        question = self.envoyes[-1]
        self.assertIn("Tertiaire : B, G1, G2. Industriel : E, F1, F2, F3, F4, F7.", question)
        self.assertIn("F2", question)
        self.assertIn("Industriel : électronique", question)
        self.assertNotIn("j.", question)                                      # plus d'option « BT » a part
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "f"))   # F2
        self.assertIn("Terminale", self.envoyes[-1])
        self.assertNotIn("année", self.envoyes[-1])
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "c"))   # Terminale
        self.assertEqual((profil["serie"], profil["classe"]), ("F2", "TERMINALE"))
        # Radio-TV et telephonie (BT ELN de M. Adia) sont dans l'electronique ; HG s'appelle CMC au technique.
        self.assertNotIn("Téléphonie", self.envoyes[-1])
        self.assertIn("e. CMC (Histoire-Géographie)", self.envoyes[-1])
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "téléphonie"))
        self.assertIn("Profil prêt : BAC Technique, série F2, Terminale, Électronique", self.envoyes[-1])

    def test_bt_ecrit_en_toutes_lettres(self):
        # Controle qualite du 9 oct. : « 3eme annee BT electronique » etait inscrit en BEPC maths.
        profil = {"onboarding_step": "exam", "serie": "TOUTES"}
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "3eme année BT électronique"))
        self.assertEqual((profil["type_examen"], profil["serie"], profil["classe"]),
                         ("BAC_TECHNIQUE", "F2", "TERMINALE"))
        self.assertEqual(profil["onboarding_step"], "matiere")

    def test_le_mot_bt_choisit_le_bac_technique(self):
        profil = {"onboarding_step": "exam", "serie": "TOUTES"}
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "BT"))
        self.assertEqual((profil["type_examen"], profil["onboarding_step"]), ("BAC_TECHNIQUE", "serie_technique"))

    def test_cmc_au_technique(self):
        profil = {"onboarding_step": "matiere", "type_examen": "BAC_TECHNIQUE", "serie": "G2", "classe": "PREMIERE"}
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "CMC"))
        self.assertEqual(profil["matiere"], "HG")

    def test_annee_de_bt_a_la_question_de_la_classe(self):
        profil = {"onboarding_step": "classe_technique", "type_examen": "BAC_TECHNIQUE", "serie": "G2"}
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "2e année"))
        self.assertEqual(profil["classe"], "PREMIERE")


class NiveauBTTests(unittest.TestCase):
    def test_niveaux_declares(self):
        cas = {
            "3eme année BT électronique": ("F2", "TERMINALE"),
            "je suis en 1A BT ELN": ("F2", "SECONDE"),
            "2BT compta": ("G2", "PREMIERE"),
            "je suis en BT électrotechnique 2e année": ("F3", "PREMIERE"),
        }
        for texte, (serie, classe) in cas.items():
            niveau = main.niveau_declare(texte)
            self.assertIsNotNone(niveau, texte)
            self.assertEqual((niveau["type_examen"], niveau["serie"], niveau["classe"]),
                             ("BAC_TECHNIQUE", serie, classe), texte)

    def test_pas_de_niveau_sans_specialite(self):
        for texte in ("je suis en BT", "BT tertiaire", "BT industriel 2e année", "j'ai 3 BTS"):
            self.assertIsNone(main.niveau_declare(texte), texte)

    def test_hors_champ(self):
        self.assertFalse(main.is_other_or_concours("je suis en BT électronique"))
        self.assertTrue(main.is_other_or_concours("je suis en CAP"))
        self.assertTrue(main.is_other_or_concours("2e année de BTS"))
        self.assertFalse(main.is_other_or_concours("capacité thermique"))
        self.assertIn("(BT : séries B, G1, G2, E et F)", main.MESSAGE_HORS_CHAMP)
        self.assertIn("Le CAP, le BTS et l'université ne sont pas encore disponibles", main.MESSAGE_HORS_CHAMP)

    def test_profils_inscrits_avec_une_option_bt(self):
        profil = main.migrer_serie_bt({"type_examen": "BAC_TECHNIQUE", "serie": "BT_ELN", "classe": "TERMINALE",
                                       "matiere": "TELEPHONIE"})
        self.assertEqual((profil["serie"], profil["matiere"]), ("F2", "ELECTRONIQUE"))
        self.assertEqual(main.migrer_serie_bt({"serie": "F2", "matiere": "RADIO_TV"})["matiere"], "ELECTRONIQUE")
        profil = main.migrer_serie_bt({"serie": "BT_TER", "matiere": "EOE"})
        self.assertEqual((profil["serie"], profil["matiere"]), ("G2", "MATHS"))
        self.assertEqual(main.migrer_serie_bt({"serie": "D", "matiere": "PC"}), {"serie": "D", "matiere": "PC"})


class EnseignantBTTests(unittest.TestCase):
    def test_classes_bt(self):
        cas = {"1A BT ELN": ("F2", "SECONDE"), "3BT ELN": ("F2", "TERMINALE"), "2 BT compta": ("G2", "PREMIERE")}
        for libelle, (serie, classe) in cas.items():
            self.assertEqual(espace_enseignant.classe_vers_profil(libelle),
                             {"type_examen": "BAC_TECHNIQUE", "serie": serie, "classe": classe}, libelle)
        self.assertEqual(espace_enseignant.classe_vers_profil("2nde F2")["serie"], "F2")


if __name__ == "__main__":
    unittest.main()
