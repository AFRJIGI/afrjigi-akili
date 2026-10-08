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
        # Depuis le controle qualite du 8 oct. : le niveau complet est enregistre, on passe a la matiere.
        profil = {"onboarding_step": "exam"}
        with mock.patch.object(main, "ask_matiere") as liste:
            self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "Terminale D"))
        self.assertEqual((profil["serie"], profil["onboarding_step"]), ("D", "matiere"))
        liste.assert_called_once()

    def test_vraie_question_pendant_l_inscription_non_bloquee(self):
        profil = {"type_examen": "BAC_TECHNIQUE", "serie": "F1", "onboarding_step": "mode"}
        with mock.patch.object(main, "is_learning_request", return_value=True):
            self.assertFalse(main.handle_onboarding_choice(PHONE, profil, "explique moi le tournage pour mon exercice de demain"))


class FauxRequete:
    def __init__(self, texte):
        self._body = {"entry": [{"changes": [{"value": {"messages": [
            {"from": PHONE, "id": f"wamid.reprise.{texte}", "type": "text", "text": {"body": texte}}
        ]}}]}]}

    async def json(self):
        return self._body


class BonjourPendantInscriptionTests(unittest.TestCase):
    def setUp(self):
        self.envoyes = []
        self.etat = {}
        noop = lambda *a, **k: None
        self.patches = [
            mock.patch.object(main, "send_whatsapp", side_effect=lambda phone, msg, *a, **k: self.envoyes.append(msg)),
            mock.patch.object(main, "send_whatsapp_typing_indicator", side_effect=noop),
            mock.patch.object(main, "reserver_message_whatsapp", return_value=True),
            mock.patch.object(main, "charger_etat_whatsapp", side_effect=lambda phone: dict(self.etat)),
            mock.patch.object(main, "sauver_etat_whatsapp", side_effect=lambda phone, p: self.etat.update(p)),
            mock.patch.object(main, "save_whatsapp_event", side_effect=noop),
            mock.patch.object(main, "maybe_send_marketing_consent_prompt", side_effect=noop),
        ]
        for p in self.patches:
            p.start()
        main.processed_messages.clear()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        main.user_profiles.pop(PHONE, None)
        main.processed_messages.clear()

    def envoyer(self, texte):
        import asyncio
        return asyncio.run(main.receive_message(FauxRequete(texte)))

    def test_bonjour_a_la_question_du_mode_garde_l_inscription(self):
        self.etat = {"type_examen": "BAC_TECHNIQUE", "serie": "F1", "matiere": "ANGLAIS",
                     "matiere_confirmed": True, "onboarding_step": "mode"}
        resultat = self.envoyer("Bonjour")
        self.assertEqual(resultat.get("reason"), "onboarding_resumed")
        self.assertEqual(self.envoyes[0], main.MESSAGE_REPRISE_INSCRIPTION)
        self.assertIn("Mode Étude", self.envoyes[1])
        self.assertEqual(self.etat["serie"], "F1")
        self.assertEqual(self.etat["onboarding_step"], "mode")

    def test_bonjour_sans_inscription_en_cours_demarre_akili(self):
        resultat = self.envoyer("Bonjour Akili")
        self.assertNotEqual(resultat.get("reason"), "onboarding_resumed")
        self.assertIn("Quel niveau prépares-tu", self.envoyes[-1])


if __name__ == "__main__":
    unittest.main()
