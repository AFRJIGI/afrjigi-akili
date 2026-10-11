"""Controle qualite du 11 oct. (50 conversations) : message sur soi « repris » comme une question apres
l'inscription, liste des niveaux renvoyee en boucle a un etudiant de BTS, « je veux choisir plusieurs »."""
import asyncio
import unittest
from unittest import mock

import main

PHONE = "22500000311"
NOUVEAU = {"serie": "TOUTES", "matiere": "MATHS", "onboarding_step": "exam"}


class FakeRequest:
    def __init__(self, texte, message_id):
        self._body = {"entry": [{"changes": [{"value": {"messages": [
            {"from": PHONE, "id": message_id, "type": "text", "text": {"body": texte}}]}}]}]}

    async def json(self):
        return self._body


class Webhook(unittest.TestCase):
    def setUp(self):
        self.envoyes, self.listes, self.akili = [], [], []
        self.etat = dict(NOUVEAU)
        noop = lambda *a, **k: None
        self.patches = [
            mock.patch.object(main, "reserver_message_whatsapp", return_value=True),
            mock.patch.object(main, "send_whatsapp", side_effect=lambda phone, msg, *a, **k: self.envoyes.append(msg)),
            mock.patch.object(main, "send_whatsapp_liste",
                              side_effect=lambda phone, corps, lignes, bouton="Choisir": self.listes.append(corps) or True),
            mock.patch.object(main, "send_whatsapp_typing_indicator", side_effect=noop),
            mock.patch.object(main, "charger_etat_whatsapp", side_effect=lambda phone: dict(self.etat)),
            mock.patch.object(main, "sauver_etat_whatsapp",
                              side_effect=lambda phone, p: self.etat.clear() or self.etat.update(p)),
            mock.patch.object(main, "save_whatsapp_event", side_effect=noop),
            mock.patch.object(main, "maybe_send_marketing_consent_prompt", side_effect=noop),
            mock.patch.object(main, "load_last_assistant_context", return_value=""),
            mock.patch.object(main, "answer_learning_request",
                              side_effect=lambda phone, profile, text, **k: self.akili.append(text)),
        ]
        for p in self.patches:
            p.start()
        main.processed_messages.clear()
        self.n = 0

    def tearDown(self):
        for p in self.patches:
            p.stop()
        main.user_profiles.pop(PHONE, None)
        main.processed_messages.clear()

    def envoyer(self, texte):
        self.n += 1
        resultat = asyncio.run(main.receive_message(FakeRequest(texte, f"wamid.qc11_{self.n}")))
        self.etat = dict(main.user_profiles.get(PHONE) or self.etat)
        return resultat


class HorsChampTests(Webhook):
    def test_liste_une_seule_fois(self):
        # …5475, …0154 : la liste des niveaux revenait a chaque message.
        self.envoyer("je suis en BTS")
        self.assertIn(main.MESSAGE_HORS_CHAMP, self.envoyes)
        self.assertEqual(len(self.listes), 1)
        self.envoyer("je suis en 2e année de BTS")
        self.envoyer("ok merci")
        self.assertEqual(len(self.listes), 1)
        self.assertEqual(self.envoyes[-1], main.MESSAGE_HORS_CHAMP_RAPPEL)
        self.assertEqual(self.akili, [])

    def test_choix_d_un_niveau_apres_le_message(self):
        self.envoyer("je suis à l'université")
        self.envoyer("b")
        self.assertEqual(main.user_profiles[PHONE]["type_examen"], "BAC_GENERAL")


class QuestionGardeeTests(Webhook):
    def test_message_sur_soi_pas_repris(self):
        # …5378 : « Je reprends ta question : Je veux cette application », puis un exercice invente.
        self.envoyer("Je veux cette application")
        self.assertNotIn("pending_question", main.user_profiles[PHONE])
        self.assertFalse(any("J'ai gardé" in m for m in self.envoyes))

    def test_vraie_question_gardee(self):
        self.envoyer("Comment on calcule la limite d'une fonction en l'infini ?")
        self.assertIn("pending_question", main.user_profiles[PHONE])

    def test_ressemble_a_une_question(self):
        for texte in ("Je veux cette application", "Au moment j'étais au premier",
                      "Mais je veux choisir plusieurs ça peut pas"):
            self.assertFalse(main.ressemble_a_une_question(texte), texte)
        for texte in ("la photosynthèse", "Explique-moi le théorème de Pythagore", "je ne comprends pas les limites",
                      "Résous 2x + 3 = 7", "je veux un exercice de maths", "qu'est-ce qu'un nombre premier"):
            self.assertTrue(main.ressemble_a_une_question(texte), texte)


class PlusieursMatieresTests(unittest.TestCase):
    def test_choisir_plusieurs(self):
        # …1184 : « Mais je veux choisir plusieurs ça peut pas » partait chez Akili.
        self.assertTrue(main.veut_plusieurs_matieres("Mais je veux choisir plusieurs ça peut pas"))
        self.assertTrue(main.veut_plusieurs_matieres("a, b et c"))
        self.assertFalse(main.veut_plusieurs_matieres("a"))


if __name__ == "__main__":
    unittest.main()
