"""« avis: » remplace « retour: » ; « Retour: <reponse> » apres une question d'Akili
est traite comme la reponse a l'exercice (cas reel en philosophie le 2 octobre)."""
import asyncio
import unittest
from unittest import mock

import main

PHONE = "22500000050"
PROFIL = {
    "type_examen": "BAC_GENERAL", "serie": "A2", "matiere": "PHILO", "mode": "etude",
    "profile_ready": True, "onboarding_step": "", "ville": "Abidjan", "matiere_confirmed": True,
    "profile_locked": True, "nom_ecole_asked": True,
    "first_learning_request_at": "2026-09-29T12:00:00+00:00",
}
QUESTION = "Quelles contradictions vois-tu entre les notions d'art et de langage ?"


class FauxRequete:
    def __init__(self, texte, mid):
        self._body = {"entry": [{"changes": [{"value": {"messages": [
            {"from": PHONE, "id": mid, "type": "text", "text": {"body": texte}}]}}]}]}

    async def json(self):
        return self._body


class PrefixeTests(unittest.TestCase):
    def test_prefixes(self):
        self.assertEqual(main.prefixe_avis("Retour: aucune contradiction"), ("retour", "aucune contradiction"))
        self.assertEqual(main.prefixe_avis("avis : trop long"), ("avis", "trop long"))
        self.assertEqual(main.prefixe_avis("FEEDBACK:ok"), ("feedback", "ok"))
        self.assertIsNone(main.prefixe_avis("le retour du roi"))

    def test_retour_court_apres_une_question(self):
        self.assertTrue(main.retour_est_une_reponse("retour", "aucune contradiction", QUESTION))
        self.assertFalse(main.retour_est_une_reponse("avis", "aucune contradiction", QUESTION))
        self.assertFalse(main.retour_est_une_reponse("retour", "aucune contradiction", "Bravo pour ta séance."))
        long = "Akili est trop lent quand je lui envoie une photo de mon exercice de maths"
        self.assertFalse(main.retour_est_une_reponse("retour", long, QUESTION))


class WebhookTests(unittest.TestCase):
    def setUp(self):
        self.envoyes, self.avis, self.akili = [], [], []
        noop = lambda *a, **k: None
        self.patches = [
            mock.patch.object(main, "send_whatsapp", side_effect=lambda phone, msg, *a, **k: self.envoyes.append(msg)),
            mock.patch.object(main, "send_whatsapp_typing_indicator", side_effect=noop),
            mock.patch.object(main, "reserver_message_whatsapp", return_value=True),
            mock.patch.object(main, "charger_etat_whatsapp", side_effect=lambda phone: dict(PROFIL)),
            mock.patch.object(main, "sauver_etat_whatsapp", side_effect=noop),
            mock.patch.object(main, "save_whatsapp_event", side_effect=noop),
            mock.patch.object(main, "maybe_send_marketing_consent_prompt", side_effect=noop),
            mock.patch.object(main, "load_last_assistant_context", return_value=QUESTION),
            mock.patch.object(main, "short_answer_has_exercise_context", return_value=True),
            mock.patch.object(main, "save_feedback_whatsapp",
                              side_effect=lambda phone, txt, profile=None, original=None, statut="nouveau", type_avis="retour":
                              self.avis.append((txt, statut, type_avis)) or True),
            mock.patch.object(main, "answer_learning_request",
                              side_effect=lambda phone, profile, texte, **k: self.akili.append(texte)),
        ]
        for p in self.patches:
            p.start()
        main.processed_messages.clear()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        main.user_profiles.pop(PHONE, None)
        main.processed_messages.clear()

    def envoyer(self, texte, mid):
        return asyncio.run(main.receive_message(FauxRequete(texte, mid)))

    def test_retour_reponse_part_chez_akili(self):
        self.envoyer("Retour: aucune contradiction", "r1")
        self.assertEqual(self.avis, [("aucune contradiction", "a_verifier", "retour_ambigu")])
        self.assertEqual(len(self.akili), 1)
        self.assertIn("aucune contradiction", self.akili[0])
        self.assertNotIn("Ton retour a été enregistré", " ".join(self.envoyes))

    def test_vrai_avis(self):
        self.envoyer("avis: les explications sont claires", "r2")
        self.assertEqual(self.avis, [("les explications sont claires", "nouveau", "retour")])
        self.assertEqual(self.akili, [])
        self.assertIn("enregistré", self.envoyes[-1])

    def test_retour_long_reste_un_avis(self):
        self.envoyer("Retour : Akili est trop lent quand je lui envoie une photo de mon exercice de maths", "r3")
        self.assertEqual(self.avis[0][1:], ("nouveau", "retour"))
        self.assertEqual(self.akili, [])

    def test_textes_affiches(self):
        self.assertIn("« avis: »", main.MESSAGE_AVIS_FIN_SESSION)


if __name__ == "__main__":
    unittest.main()
