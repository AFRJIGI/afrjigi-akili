"""Pendant l'inscription, une reponse hors liste fait reposer la question
(avant, "anglais" a la question du mode partait chez Akili sans ville ni ecole)."""
import unittest
from unittest import mock

import main

PHONE = "22500000030"


class ChoixNonComprisTests(unittest.TestCase):
    def setUp(self):
        self.envoyes = []
        self.patches = [
            mock.patch.object(main, "send_whatsapp", side_effect=lambda phone, msg, *a, **k: self.envoyes.append(msg)),
            mock.patch.object(main, "sauver_etat_whatsapp"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        main.user_profiles.pop(PHONE, None)

    def test_mot_hors_liste_a_la_question_du_mode(self):
        profil = {"type_examen": "BAC_TECHNIQUE", "serie": "F1", "matiere": "CMI",
                  "matiere_confirmed": True, "onboarding_step": "mode"}
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "anglais"))
        self.assertEqual(self.envoyes[0], main.MESSAGE_CHOIX_NON_COMPRIS)
        self.assertIn("Mode Étude", self.envoyes[1])
        self.assertEqual(profil["matiere"], "CMI")
        self.assertEqual(profil["onboarding_step"], "mode")

    def test_matiere_absente_de_la_serie(self):
        profil = {"type_examen": "BAC_TECHNIQUE", "serie": "F2", "onboarding_step": "matiere"}
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "philosophie"))
        self.assertIn("a. Mécanique appliquée", self.envoyes[1])
        self.assertNotIn("matiere", profil)

    def test_profil_en_toutes_lettres_a_la_premiere_question(self):
        profil = {"onboarding_step": "exam"}
        self.assertFalse(main.handle_onboarding_choice(PHONE, profil, "Terminale D"))
        self.assertEqual(self.envoyes, [])

    def test_vraie_question_pendant_l_inscription_non_bloquee(self):
        profil = {"type_examen": "BAC_TECHNIQUE", "serie": "F1", "onboarding_step": "mode"}
        with mock.patch.object(main, "is_learning_request", return_value=True):
            self.assertFalse(main.handle_onboarding_choice(PHONE, profil, "explique moi le tournage pour mon exercice de demain"))


if __name__ == "__main__":
    unittest.main()
