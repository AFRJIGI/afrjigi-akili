"""Un eleve qui choisit plusieurs matieres a l'onboarding recoit une explication,
reste a l'etape matiere, et peut ensuite choisir une seule lettre normalement."""
import asyncio
import unittest
from unittest import mock

import main


class FakeRequest:
    def __init__(self, texte, message_id):
        self._body = {"entry": [{"changes": [{"value": {"messages": [
            {"from": "22500000002", "id": message_id, "type": "text", "text": {"body": texte}}
        ]}}]}]}

    async def json(self):
        return self._body


class DetectionTests(unittest.TestCase):
    def test_detecte_plusieurs_lettres_et_tout(self):
        for texte in ["a,b,c,d,e,i", "A,b,c,d,e,f,g,h,i", "a et c", "Nn je veux tout",
                      "toutes les matières", "g, h, i", "1,2,3"]:
            self.assertTrue(main.veut_plusieurs_matieres(texte), texte)

    def test_ne_detecte_pas_un_choix_simple_ou_une_phrase(self):
        for texte in ["a", "b", "maths", "j'ai une question a propos de b", "Je suis en D", ""]:
            self.assertFalse(main.veut_plusieurs_matieres(texte), texte)


class WebhookTests(unittest.TestCase):
    def setUp(self):
        self.phone = "22500000002"
        self.envoyes = []
        self.profile = {"type_examen": "BAC_GENERAL", "serie": "D", "matiere": "MATHS",
                        "onboarding_step": "matiere", "matiere_confirmed": False}
        main.user_profiles[self.phone] = dict(self.profile)
        noop = lambda *a, **k: None
        self.patches = [
            mock.patch.object(main, "send_whatsapp", side_effect=lambda phone, msg, *a, **k: self.envoyes.append(msg)),
            mock.patch.object(main, "send_whatsapp_typing_indicator", side_effect=noop),
            mock.patch.object(main, "charger_etat_whatsapp", side_effect=lambda phone: dict(self.profile)),
            mock.patch.object(main, "sauver_etat_whatsapp", side_effect=noop),
            mock.patch.object(main, "save_whatsapp_event", side_effect=noop),
            mock.patch.object(main, "maybe_send_marketing_consent_prompt", side_effect=noop),
            mock.patch.object(main, "answer_learning_request", side_effect=AssertionError("ne doit pas appeler Akili")),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        main.user_profiles.pop(self.phone, None)

    def envoyer(self, texte, message_id):
        return asyncio.run(main.receive_message(FakeRequest(texte, message_id)))

    def test_plusieurs_lettres_puis_une_seule(self):
        resultat = self.envoyer("a,b,c,d,e,i", "wamid.multi1")
        self.assertEqual(resultat.get("reason"), "multiple_subjects_requested")
        self.assertIn("une matière à la fois", self.envoyes[-1])
        self.assertIn("changer matière", self.envoyes[-1])
        self.assertEqual(main.user_profiles[self.phone].get("onboarding_step"), "matiere")

        self.envoyer("b", "wamid.multi1b")
        profil = main.user_profiles[self.phone]
        self.assertEqual(profil.get("matiere"), "PC")
        self.assertNotEqual(profil.get("onboarding_step"), "matiere")

    def test_je_veux_tout(self):
        resultat = self.envoyer("Nn je veux tout", "wamid.multi2")
        self.assertEqual(resultat.get("reason"), "multiple_subjects_requested")


if __name__ == "__main__":
    unittest.main()
