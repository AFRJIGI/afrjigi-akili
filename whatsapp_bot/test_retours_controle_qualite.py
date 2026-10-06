"""Corrections du controle qualite du 6 oct. : eleve qui veut arreter ou changer de matiere,
« 2nde C » compris comme Terminale C, options de QCM coupees par la limite de longueur."""
import unittest
from pathlib import Path
from unittest import mock

import main

QUESTION = ("Passons à la question 2 : quel est le rôle du liquide séminal ?\n"
            "a) Nourrir les spermatozoïdes\nb) Transporter les spermatozoïdes\n"
            "c) Protéger les spermatozoïdes\nd) Toutes ces réponses\nRéponds par a, b, c ou d.")


def message_long(n):
    return ("Non, la réponse c) La prostate n'est pas correcte. " + "La prostate produit une partie du liquide séminal. " * n
            + "Par élimination, c'est l'épididyme.\n\n" + QUESTION)


class ChangementMatiereTests(unittest.TestCase):
    def test_demandes_reconnues(self):
        for texte, matiere in [("je veux plus de svt", "SVT"), ("je ne veux plus", "SVT"), ("une autre matière", "PC"),
                               ("allons sur la rédaction littéraire c'est fini", "SVT"), ("Passons aux maths", "SVT"),
                               ("on va faire de l'anglais maintenant", "PHILO"), ("je ne veux plus continuer", "SVT")]:
            self.assertTrue(main.est_demande_changement_matiere(texte, matiere), texte)

    def test_messages_d_exercice_non_reconnus(self):
        for texte, matiere in [("je veux plus d'exercices", "MATHS"), ("je veux plus d'explication", "MATHS"),
                               ("passons à la question 2", "MATHS"), ("je veux faire les maths", "MATHS_FIN"),
                               ("calcule la dérivée de f", "MATHS"), ("b", "SVT"), ("on passe à la physique", "PC")]:
            self.assertFalse(main.est_demande_changement_matiere(texte, matiere), texte)

    def test_ouvre_la_liste_des_matieres(self):
        listes = []
        profil = {"type_examen": "BAC_GENERAL", "serie": "A2", "matiere": "SVT", "mode": "etude",
                  "profile_locked": True, "matiere_confirmed": True, "pending_question": "x"}
        with mock.patch.object(main, "sauver_etat_whatsapp"), \
                mock.patch.object(main, "ask_matiere", side_effect=lambda phone, serie: listes.append(serie)):
            main.ouvrir_choix_matiere("22500000084", profil)
        main.user_profiles.pop("22500000084", None)
        self.assertEqual(listes, ["A2"])
        self.assertEqual(profil["onboarding_step"], "matiere")
        self.assertNotIn("profile_locked", profil)
        self.assertNotIn("pending_question", profil)

    def test_branche_dans_le_webhook(self):
        source = Path(main.__file__).read_text(encoding="utf-8")
        self.assertIn("est_demande_changement_matiere(text, profile.get(\"matiere\"))", source)
        self.assertLess(source.index("est_message_au_revoir(text):\n            envoyer_fin_de_session"),
                        source.index("est_demande_changement_matiere(text, profile.get(\"matiere\"))"))


class FinDeSeanceTests(unittest.TestCase):
    def test_dormir_et_demain(self):
        for texte in ["Je peux aller dormir maintenant", "je peux aller dormir ?", "on continue demain", "bonne nuit"]:
            self.assertTrue(main.est_message_au_revoir(texte), texte)
        for texte in ["c'est quoi la dérivée ?", "j'ai fini", "dormir est-il un besoin ? explique"]:
            self.assertFalse(main.est_message_au_revoir(texte), texte)


class ClasseIntermediaireTests(unittest.TestCase):
    def test_seconde_et_premiere(self):
        for texte, attendu in [("2nde c", "SECONDE_C"), ("je suis en 1ère D", "PREMIERE_D"), ("seconde A2", "SECONDE_A"),
                               ("Première C", "PREMIERE_C")]:
            profil = main.update_profile_from_text({"serie": "TOUTES"}, texte)
            self.assertEqual(profil["serie"], attendu, texte)
            self.assertEqual(profil["type_examen"], "CLASSE_INTERMEDIAIRE", texte)
            self.assertEqual(main.infer_type_examen(attendu, ""), "CLASSE_INTERMEDIAIRE")

    def test_terminale_inchangee(self):
        profil = main.update_profile_from_text({"serie": "TOUTES"}, "Terminale C")
        self.assertEqual(profil["serie"], "C")
        self.assertEqual(main.infer_type_examen("D", "terminale D"), "BAC_GENERAL")


class OptionsNonCoupeesTests(unittest.TestCase):
    def test_question_et_options_ensemble(self):
        for n in (11, 12, 13):
            parts, reste = main.decouper_message(message_long(n), 850, 1)
            self.assertNotIn("a) Nourrir", parts[0], n)
            self.assertTrue(reste.startswith("Passons à la question 2"), n)
            self.assertIn("d) Toutes ces réponses", reste)

    def test_message_court_entier(self):
        parts, reste = main.decouper_message(message_long(9), 850, 1)
        self.assertIn("d) Toutes ces réponses", parts[0])
        self.assertEqual(reste, "")

    def test_options_sur_la_ligne_de_la_question(self):
        texte = "Explication. " * 60 + "Quelle formule utiliserais-tu ? (a) v = d/t (b) v = d × t (c) v = t/d. Réponds par a, b ou c."
        parts, reste = main.decouper_message(texte, 850, 1)
        self.assertTrue(reste.startswith("Quelle formule"))
        self.assertIn("(c) v = t/d", reste)

    def test_texte_sans_options_inchange(self):
        texte = "Une phrase d'explication assez longue. " * 30
        parts, reste = main.decouper_message(texte, 850, 1)
        self.assertEqual((parts[0] + " " + reste).split(), texte.split())


if __name__ == "__main__":
    unittest.main()
