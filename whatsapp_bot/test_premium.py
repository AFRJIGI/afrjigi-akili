"""Commande « premium » : abonnement actif, ou lien de paiement Paiement Pro."""
import asyncio
import unittest
from datetime import datetime, timedelta
from unittest import mock

import main
from test_avis_boutons import FauxRequete, PHONE, PROFIL, texte


class FauxDoc:
    def __init__(self, d):
        self.d = d
        self.exists = d is not None

    def to_dict(self):
        return self.d


def faux_firestore(fiche):
    db = mock.MagicMock()
    db.collection.return_value.document.return_value.get.return_value = FauxDoc(fiche)
    return db


class PremiumTests(unittest.TestCase):
    def setUp(self):
        self.etat = dict(PROFIL)
        self.envoyes = []
        noop = lambda *a, **k: None
        self.patches = [
            mock.patch.object(main, "send_whatsapp", side_effect=lambda phone, msg, *a, **k: self.envoyes.append(msg)),
            mock.patch.object(main, "send_whatsapp_typing_indicator", side_effect=noop),
            mock.patch.object(main, "reserver_message_whatsapp", return_value=True),
            mock.patch.object(main, "charger_etat_whatsapp", side_effect=lambda phone: dict(self.etat)),
            mock.patch.object(main, "sauver_etat_whatsapp", side_effect=noop),
            mock.patch.object(main, "save_whatsapp_event", side_effect=noop),
            mock.patch.object(main, "maybe_send_marketing_consent_prompt", side_effect=noop),
            mock.patch.object(main, "answer_learning_request", side_effect=AssertionError("Akili ne doit pas etre appele")),
        ]
        for p in self.patches:
            p.start()
        main.processed_messages.clear()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        main.user_profiles.pop(PHONE, None)
        main.processed_messages.clear()

    def envoyer(self, corps, mid="p1"):
        return asyncio.run(main.receive_message(FauxRequete(texte(corps, mid))))

    def test_envoie_le_lien_de_paiement(self):
        reponse = mock.Mock()
        reponse.json.return_value = {"url": "https://paiementpro.net/pay?s=1"}
        with mock.patch.object(main, "feedback_db", faux_firestore(None)), \
                mock.patch.object(main.requests, "post", return_value=reponse) as post:
            resultat = self.envoyer("Premium")
        self.assertEqual(resultat["reason"], "premium_lien")
        self.assertEqual(post.call_args.kwargs["json"], {"email": f"{PHONE}@afrjigi.com"})
        self.assertIn("https://paiementpro.net/pay?s=1", self.envoyes[0])
        self.assertIn("2 000 FCFA", self.envoyes[0])

    def test_abonnement_actif_ne_cree_pas_de_lien(self):
        fin = (datetime.utcnow() + timedelta(days=10)).isoformat()
        with mock.patch.object(main, "feedback_db", faux_firestore({"tier": "PREMIUM", "premium_expire_le": fin})), \
                mock.patch.object(main.requests, "post", side_effect=AssertionError("pas de paiement")):
            resultat = self.envoyer("premium")
        self.assertEqual(resultat["reason"], "premium_actif")
        self.assertIn("jusqu'au", self.envoyes[0])

    def test_abonnement_expire_redonne_un_lien(self):
        passe = (datetime.utcnow() - timedelta(days=1)).isoformat()
        reponse = mock.Mock()
        reponse.json.return_value = {"url": "https://x"}
        with mock.patch.object(main, "feedback_db", faux_firestore({"tier": "PREMIUM", "premium_expire_le": passe})), \
                mock.patch.object(main.requests, "post", return_value=reponse):
            self.assertEqual(self.envoyer("premium")["reason"], "premium_lien")

    def test_erreur_de_paiement_message_clair(self):
        with mock.patch.object(main, "feedback_db", faux_firestore(None)), \
                mock.patch.object(main.requests, "post", side_effect=RuntimeError("boom")):
            resultat = self.envoyer("payer")
        self.assertEqual(resultat["reason"], "premium_erreur")
        self.assertIn("momentanément indisponible", self.envoyes[0])


if __name__ == "__main__":
    unittest.main()
