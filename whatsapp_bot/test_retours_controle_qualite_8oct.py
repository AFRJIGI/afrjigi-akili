"""Controle qualite du 8 oct. (2 h 11) : niveau ecrit en toutes lettres pendant l'inscription, ancien
enonce retenu apres une nouvelle photo, temperature de l'API selon la matiere."""
import importlib.util
import unittest
from pathlib import Path
from unittest import mock

import main

PHONE = "22500000101"


class NiveauEcritTests(unittest.TestCase):
    def setUp(self):
        self.envoyes, self.listes, self.akili = [], [], []
        self.patches = [
            mock.patch.object(main, "send_whatsapp", side_effect=lambda p, m, *a, **k: self.envoyes.append(m)),
            mock.patch.object(main, "envoyer_choix", side_effect=lambda p, q, options, **k: self.listes.append(q)),
            mock.patch.object(main, "sauver_etat_whatsapp"),
            mock.patch.object(main, "mark_onboarding_completed",
                              side_effect=lambda p, prof: dict(prof, profile_ready=True, onboarding_step="",
                                                               onboarding_completed_at="2026-10-08")),
            mock.patch.object(main, "answer_learning_request",
                              side_effect=lambda p, prof, t, **k: self.akili.append(t)),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        main.user_profiles.pop(PHONE, None)

    def test_terminale_d_a_la_question_du_niveau(self):
        profil = {"serie": "TOUTES", "matiere": "MATHS", "onboarding_step": "exam"}
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "Terminale D"))
        self.assertEqual((profil["type_examen"], profil["serie"], profil["onboarding_step"]),
                         ("BAC_GENERAL", "D", "matiere"))
        self.assertEqual(self.listes, ["Quelle matière veux-tu travailler ?"])
        self.assertNotIn("pending_question", profil)

    def test_niveau_et_matiere_ensemble(self):
        profil = {"serie": "TOUTES", "onboarding_step": "serie_general", "type_examen": "BAC_GENERAL"}
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "Tle C maths"))
        self.assertTrue(self.envoyes[0].startswith("Profil prêt : BAC Général, Terminale C, Mathématiques"))
        self.assertEqual(self.akili, [main.DEMANDE_PREMIER_EXERCICE])

    def test_lettre_reste_un_choix(self):
        profil = {"serie": "TOUTES", "onboarding_step": "serie_general", "type_examen": "BAC_GENERAL"}
        with mock.patch.object(main, "ask_matiere") as liste:
            self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "d"))
        self.assertEqual(profil["serie"], "D")
        liste.assert_called_once()


class EnonceTests(unittest.TestCase):
    def test_nouvelle_photo_oublie_l_ancien_enonce(self):
        profil = {"type_examen": "BAC_GENERAL", "serie": "D", "matiere": "MATHS", "mode": "etude",
                  "profile_ready": True, "profile_locked": True, "first_learning_request_at": "x",
                  "enonce_en_cours": {"cle": f"{PHONE}:BAC_GENERAL:D:MATHS:etude", "texte": "g(x) = 2x³ - 3x² - 12x + 7"}}
        with mock.patch.object(main, "p0_enabled", return_value=False), \
                mock.patch.object(main, "send_whatsapp"), mock.patch.object(main, "send_whatsapp_typing_indicator"), \
                mock.patch.object(main, "charger_historique_conv", return_value=[]), \
                mock.patch.object(main, "sauver_historique_conv"), mock.patch.object(main, "sauver_etat_whatsapp"), \
                mock.patch.object(main, "get_akili_response", return_value="Je vois ta fonction f. Calcule f'(x)."):
            main.answer_learning_request(PHONE, profil, "[photo] voici mon exercice", media_file="/tmp/photo.jpg")
        main.user_profiles.pop(PHONE, None)
        main.conversations.clear()
        self.assertNotIn("enonce_en_cours", profil)


class TemperatureApiTests(unittest.TestCase):
    def test_matieres_precises(self):
        source = (Path(main.__file__).parents[1] / "akili_api" / "main.py").read_text(encoding="utf-8")
        import re
        espace = {}
        prefixes = re.search(r"^PREFIXES_MATIERES_PRECISES = .*$", source, re.M).group(0)
        fonction = re.search(r"^def config_generation\(matiere\):\n(?:    .*\n)+", source, re.M).group(0)
        exec(prefixes + "\n" + fonction, espace)
        self.assertEqual(espace["config_generation"]("MATHS")["temperature"], 0.3)
        self.assertEqual(espace["config_generation"]("COMPTA_FIN")["temperature"], 0.3)
        self.assertEqual(espace["config_generation"]("PHILO")["temperature"], 0.7)
        self.assertIn("generation_config=config_generation(matiere)", source)


if __name__ == "__main__":
    unittest.main()
