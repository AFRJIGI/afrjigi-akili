"""Controle qualite du 17 oct. : « Cc » apres une pause reprend la question en attente au lieu de
« Bon retour… envoie ton exercice » ; une demande de nouvel exercice fait oublier l'ancien enonce."""
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import main

PHONE = "22500000117"
INSCRIT = {"type_examen": "BAC_GENERAL", "serie": "A2", "matiere": "FRANCAIS", "mode": "etude",
           "profile_ready": True, "profile_locked": True, "matiere_confirmed": True, "onboarding_step": "",
           "onboarding_completed_at": "2026-10-06T15:08:39+00:00", "first_learning_request_at": "x"}
QUESTION = "Quel exemple choisis-tu pour illustrer ton premier argument : a, b ou c ?"


def session(minutes, cle=None, reponse=None):
    return {"conversation_key": cle or main.cle_conversation_profil(PHONE, INSCRIT),
            "derniere_activite": (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(),
            "messages": [{"role": "user", "content": "ok"},
                         {"role": "assistant", "content": reponse or f"Très bien, ton argument est clair.\n\n{QUESTION}"}]}


class QuestionEnAttenteTests(unittest.TestCase):
    def question(self, s):
        with mock.patch.object(main, "charger_session_bilan", return_value=s):
            return main.question_en_attente(PHONE, INSCRIT)

    def test_seance_recente_meme_matiere(self):
        self.assertEqual(self.question(session(45)), QUESTION)

    def test_trop_ancienne(self):
        self.assertEqual(self.question(session(13 * 60)), "")

    def test_autre_matiere(self):
        self.assertEqual(self.question(session(45, cle=f"{PHONE}:BAC_GENERAL:A2:PHILO:etude")), "")

    def test_sans_question(self):
        self.assertEqual(self.question(session(45, reponse="Bravo, exercice terminé.")), "")

    def test_pas_de_seance(self):
        self.assertEqual(self.question(None), "")

    def test_question_tres_longue_garde_la_derniere_phrase(self):
        longue = "Explication. " * 40 + "Quelle est la valeur de x ?"
        self.assertEqual(self.question(session(10, reponse=longue)), "Quelle est la valeur de x ?")


class NouvelExerciceTests(unittest.TestCase):
    def test_demandes(self):
        for texte in ["Donne-moi un autre exercice", "nouvel exercice stp", "On passe à l'exercice suivant",
                      "Je veux changer d'exercice"]:
            self.assertTrue(main.demande_nouvel_exercice(texte), texte)

    def test_pas_une_demande(self):
        for texte in ["b", "x = 3", "Je n'ai pas compris l'exercice", "Corrige mon exercice"]:
            self.assertFalse(main.demande_nouvel_exercice(texte), texte)


class FauxRequete:
    def __init__(self, texte, n):
        self._body = {"entry": [{"changes": [{"value": {"messages": [
            {"from": PHONE, "id": f"wamid.cq17.{n}", "type": "text", "text": {"body": texte}}
        ]}}]}]}

    async def json(self):
        return self._body


class SalutationWebhookTests(unittest.TestCase):
    def setUp(self):
        self.envoyes, self.etat = [], dict(INSCRIT)
        noop = lambda *a, **k: None
        self.patches = [
            mock.patch.object(main, "send_whatsapp", side_effect=lambda phone, msg, *a, **k: self.envoyes.append(msg)),
            mock.patch.object(main, "send_whatsapp_typing_indicator", side_effect=noop),
            mock.patch.object(main, "reserver_message_whatsapp", return_value=True),
            mock.patch.object(main, "charger_etat_whatsapp", side_effect=lambda phone: dict(self.etat)),
            mock.patch.object(main, "sauver_etat_whatsapp", side_effect=lambda phone, p: self.etat.update(p)),
            mock.patch.object(main, "save_whatsapp_event", side_effect=noop),
            mock.patch.object(main, "maybe_send_marketing_consent_prompt", side_effect=noop),
            mock.patch.object(main, "charger_historique_conv", return_value=[]),
            mock.patch.object(main, "load_last_assistant_context", return_value=""),
            mock.patch.object(main, "answer_learning_request", side_effect=noop),
        ]
        for p in self.patches:
            p.start()
        main.processed_messages.clear()
        main.conversations.clear()
        main.user_profiles[PHONE] = dict(INSCRIT)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        main.user_profiles.pop(PHONE, None)
        main.processed_messages.clear()
        main.conversations.clear()

    def test_cc_reprend_la_question(self):
        with mock.patch.object(main, "charger_session_bilan", return_value=session(40)):
            asyncio.run(main.receive_message(FauxRequete("Cc", 1)))
        self.assertTrue(self.envoyes[0].startswith("Re-bonjour ! On en était là"))
        self.assertIn(QUESTION, self.envoyes[0])

    def test_cc_sans_seance_bon_retour(self):
        with mock.patch.object(main, "charger_session_bilan", return_value=None):
            asyncio.run(main.receive_message(FauxRequete("Cc", 2)))
        self.assertTrue(self.envoyes[0].startswith("Bon retour sur Akili !"))


if __name__ == "__main__":
    unittest.main()
