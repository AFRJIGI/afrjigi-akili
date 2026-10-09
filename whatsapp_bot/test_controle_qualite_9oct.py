"""Controle qualite du 9 oct. : une demande d'aide envoyee apres « Un peu » part chez Akili (l'avis est garde),
et le texte des flyers (« Bonjour Akili, je participe au pilote AfrJigi ») n'est plus repris comme une question."""
import unittest
from unittest import mock

import main
import test_avis_boutons as avis


class DemandeApresAvisTests(avis.AvisBoutonsTests):
    def test_demande_d_aide_apres_un_peu(self):
        self.envoyer(avis.bouton("avis_un_peu", "Un peu", "q1"))
        self.assertEqual(self.envoyes[-1], main.MESSAGE_DEMANDE_COMMENTAIRE)
        main.processed_messages.clear()
        akili = []
        with mock.patch.object(main, "detect_marketing_consent_command", return_value=None), \
                mock.patch.object(main, "answer_learning_request",
                                  side_effect=lambda phone, profile, text, **k: akili.append(text)):
            self.envoyer(avis.texte("Mets moi sur la voie de la re formulation", "q2"))
        self.assertEqual(self.avis[-1], ("un_peu", "Mets moi sur la voie de la re formulation"))
        self.assertEqual(akili, ["Mets moi sur la voie de la re formulation"])
        self.assertNotIn(main.MESSAGE_MERCI_COMMENTAIRE, self.envoyes)
        self.assertNotIn("attente_commentaire_avis", main.user_profiles[avis.PHONE])

    def test_un_vrai_commentaire_reste_un_commentaire(self):
        self.envoyer(avis.bouton("avis_non", "Non", "q3"))
        main.processed_messages.clear()
        with mock.patch.object(main, "detect_marketing_consent_command", return_value=None):
            resultat = self.envoyer(avis.texte("Tes réponses sont trop longues", "q4"))
        self.assertEqual(resultat["reason"], "commentaire_avis")
        self.assertEqual(self.envoyes[-1], main.MESSAGE_MERCI_COMMENTAIRE)


class DetectionTests(unittest.TestCase):
    def test_demandes_d_aide(self):
        for texte in ("Mets moi sur la voie de la re formulation", "Explique encore stp", "Comment on fait ?",
                      "Donne moi un autre exercice", "Je comprends pas", "on continue"):
            self.assertTrue(main.est_demande_d_aide(texte), texte)
        for texte in ("Trop long", "Tes réponses sont trop longues", "c'était lent"):
            self.assertFalse(main.est_demande_d_aide(texte), texte)

    def test_messages_d_accueil(self):
        for texte in ("Bonjour Akili, je participe au pilote AfrJigi", "Bonjour Akili", "slt", "Cc akili"):
            self.assertTrue(main.est_message_d_accueil(texte), texte)
        for texte in ("Bonjour, explique-moi les fonctions logarithmes", "Je participe au pilote, aide moi en maths ?",
                      "Calcule la dérivée de x²"):
            self.assertFalse(main.est_message_d_accueil(texte), texte)


if __name__ == "__main__":
    unittest.main()


class TexteDesFlyersTests(unittest.TestCase):
    def setUp(self):
        self.etat, self.envoyes = {}, []
        noop = lambda *a, **k: None
        self.patches = [
            mock.patch.object(main, "send_whatsapp", side_effect=lambda phone, msg, *a, **k: self.envoyes.append(msg)),
            mock.patch.object(main, "send_whatsapp_boutons", return_value=True),
            mock.patch.object(main, "send_whatsapp_liste", return_value=False, create=True),
            mock.patch.object(main, "send_whatsapp_typing_indicator", side_effect=noop),
            mock.patch.object(main, "reserver_message_whatsapp", return_value=True),
            mock.patch.object(main, "charger_etat_whatsapp", side_effect=lambda phone: dict(self.etat)),
            mock.patch.object(main, "sauver_etat_whatsapp",
                              side_effect=lambda phone, p: self.etat.clear() or self.etat.update(p)),
            mock.patch.object(main, "save_whatsapp_event", side_effect=noop),
            mock.patch.object(main, "maybe_send_marketing_consent_prompt", side_effect=noop),
            mock.patch.object(main, "detect_marketing_consent_command", return_value=None),
            mock.patch.object(main, "answer_learning_request", side_effect=AssertionError("pas d'appel a Akili")),
        ]
        for p in self.patches:
            p.start()
        main.processed_messages.clear()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        main.user_profiles.pop(avis.PHONE, None)
        main.processed_messages.clear()

    def test_le_texte_des_flyers_n_est_pas_garde(self):
        import asyncio
        asyncio.run(main.receive_message(avis.FauxRequete(
            avis.texte("Bonjour Akili, je participe au pilote AfrJigi", "f1"))))
        profil = main.user_profiles[avis.PHONE]
        self.assertNotIn("pending_question", profil)
        self.assertFalse(any("ta question" in m for m in self.envoyes), self.envoyes)
