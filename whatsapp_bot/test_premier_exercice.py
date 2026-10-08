"""Activation : a la fin d'une premiere inscription, Akili propose tout de suite un exercice court
(environ 870 eleves s'etaient inscrits sans jamais poser de question)."""
import asyncio
import unittest
from unittest import mock

import main

PHONE = "22500000100"


class FauxRequete:
    def __init__(self, texte, n):
        self._body = {"entry": [{"changes": [{"value": {"messages": [
            {"from": PHONE, "id": f"wamid.premier.{n}", "type": "text", "text": {"body": texte}}
        ]}}]}]}

    async def json(self):
        return self._body


class PremierExerciceTests(unittest.TestCase):
    def setUp(self):
        self.envoyes, self.akili, self.etat, self.n = [], [], {}, 0
        noop = lambda *a, **k: None
        self.patches = [
            mock.patch.object(main, "send_whatsapp", side_effect=lambda p, m, *a, **k: self.envoyes.append(m)),
            mock.patch.object(main, "envoyer_choix", side_effect=noop),
            mock.patch.object(main, "send_whatsapp_typing_indicator", side_effect=noop),
            mock.patch.object(main, "reserver_message_whatsapp", return_value=True),
            mock.patch.object(main, "charger_etat_whatsapp", side_effect=lambda p: dict(self.etat)),
            mock.patch.object(main, "sauver_etat_whatsapp", side_effect=lambda p, prof: self.etat.update(prof)),
            mock.patch.object(main, "save_whatsapp_event", side_effect=noop),
            mock.patch.object(main, "maybe_send_marketing_consent_prompt", side_effect=noop),
            mock.patch.object(main, "mark_onboarding_completed",
                              side_effect=lambda p, prof: dict(prof, profile_ready=True, onboarding_step="",
                                                              onboarding_completed_at=prof.get("onboarding_completed_at") or "2026-10-08")),
            mock.patch.object(main, "answer_learning_request",
                              side_effect=lambda p, prof, texte, **k: self.akili.append((texte, k))),
        ]
        for p in self.patches:
            p.start()
        main.processed_messages.clear()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        main.user_profiles.pop(PHONE, None)
        main.processed_messages.clear()

    def envoyer(self, texte, profil):
        self.etat = dict(profil)
        main.user_profiles[PHONE] = dict(profil)
        self.n += 1
        return asyncio.run(main.receive_message(FauxRequete(texte, self.n)))

    def test_nouvel_eleve_recoit_un_exercice(self):
        self.envoyer("a", {"type_examen": "BAC_GENERAL", "serie": "D", "onboarding_step": "matiere"})
        self.assertTrue(self.envoyes[0].startswith("Profil prêt : BAC Général, Terminale D, Mathématiques"))
        self.assertIn("voici un premier exercice", self.envoyes[0])
        self.assertEqual(len(self.akili), 1)
        texte, options = self.akili[0]
        self.assertEqual(texte, main.DEMANDE_PREMIER_EXERCICE)
        self.assertFalse(options["compter_activation"])  # l'activation se compte quand l'eleve repond
        self.assertNotIn("premier_exercice_a_proposer", main.user_profiles[PHONE])

    def test_question_gardee_passe_avant(self):
        self.envoyer("a", {"type_examen": "BAC_GENERAL", "serie": "D", "onboarding_step": "matiere",
                           "pending_question": "Calcule la limite de 1/x en 0", "pending_question_display": "Calcule"})
        self.assertEqual([t for t, _ in self.akili], ["Calcule la limite de 1/x en 0"])
        self.assertNotIn("voici un premier exercice", self.envoyes[0])

    def test_changement_de_matiere_d_un_inscrit(self):
        self.envoyer("b", {"type_examen": "BAC_GENERAL", "serie": "D", "matiere": "MATHS", "mode": "etude",
                           "onboarding_step": "matiere", "onboarding_completed_at": "2026-10-01",
                           "first_learning_request_at": "2026-10-01"})
        self.assertEqual(self.akili, [])
        self.assertTrue(self.envoyes[0].startswith("C'est noté"))


class ActivationTests(unittest.TestCase):
    def test_premier_exercice_ne_compte_pas_l_activation(self):
        profil = {"type_examen": "BEPC", "serie": "BEPC", "matiere": "MATHS", "mode": "etude",
                  "profile_ready": True, "profile_locked": True}
        with mock.patch.object(main, "p0_enabled", return_value=False), \
                mock.patch.object(main, "send_whatsapp"), mock.patch.object(main, "send_whatsapp_typing_indicator"), \
                mock.patch.object(main, "charger_historique_conv", return_value=[]), \
                mock.patch.object(main, "sauver_historique_conv"), mock.patch.object(main, "sauver_etat_whatsapp"), \
                mock.patch.object(main, "mark_first_learning_request") as marque, \
                mock.patch.object(main, "get_akili_response", return_value="Combien font 2 + 3 ? a) 5 b) 6 c) 4"):
            main.answer_learning_request(PHONE, profil, main.DEMANDE_PREMIER_EXERCICE, compter_activation=False)
        main.user_profiles.pop(PHONE, None)
        main.conversations.clear()
        marque.assert_not_called()


if __name__ == "__main__":
    unittest.main()
