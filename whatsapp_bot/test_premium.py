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

    def test_premium_propose_les_operateurs(self):
        boutons = []
        with mock.patch.object(main, "feedback_db", faux_firestore(None)), \
                mock.patch.object(main, "send_whatsapp_boutons",
                                  side_effect=lambda phone, corps, b: boutons.append((corps, b)) or True), \
                mock.patch.object(main.requests, "post", side_effect=AssertionError("pas encore de lien")):
            resultat = self.envoyer("Premium")
        self.assertEqual(resultat["reason"], "premium_choix")
        self.assertIn("2 000 FCFA", boutons[0][0])
        self.assertEqual([i for i, _ in boutons[0][1]], ["pay_orange", "pay_mtn", "pay_moov"])

    def test_choix_de_l_operateur_envoie_le_lien(self):
        for ecrit, canal in (("premium orange", "OMCIV2"), ("Premium MTN", "MOMO"), ("premium moov", "FLOOZ")):
            self.envoyes.clear()
            main.processed_messages.clear()
            reponse = mock.Mock()
            reponse.json.return_value = {"url": "https://paiementpro.net/pay?s=1"}
            with mock.patch.object(main, "feedback_db", faux_firestore(None)), \
                    mock.patch.object(main.requests, "post", return_value=reponse) as post:
                resultat = self.envoyer(ecrit, mid="m-" + canal)
            self.assertEqual(resultat["reason"], "premium_lien")
            self.assertEqual(post.call_args.kwargs["json"], {"email": f"{PHONE}@afrjigi.com", "canal": canal})
            self.assertIn("https://paiementpro.net/pay?s=1", self.envoyes[0])

    def test_boutons_de_paiement_valent_le_texte_premium(self):
        self.assertEqual(main.commande_premium(main.BOUTONS_AIDE_TEXTE["pay_orange"]), (True, "OMCIV2"))
        self.assertEqual(main.commande_premium(main.BOUTONS_AIDE_TEXTE["pay_mtn"]), (True, "MOMO"))
        self.assertEqual(main.commande_premium(main.BOUTONS_AIDE_TEXTE["pay_moov"]), (True, "FLOOZ"))
        self.assertEqual(main.commande_premium("premium wave"), (False, None))
        self.assertEqual(main.commande_premium("je veux payer le loyer"), (False, None))

    def test_abonnement_actif_ne_cree_pas_de_lien(self):
        fin = (datetime.utcnow() + timedelta(days=10)).isoformat()
        with mock.patch.object(main, "feedback_db", faux_firestore({"tier": "PREMIUM", "premium_expire_le": fin})), \
                mock.patch.object(main.requests, "post", side_effect=AssertionError("pas de paiement")):
            resultat = self.envoyer("premium")
        self.assertEqual(resultat["reason"], "premium_actif")
        self.assertIn("jusqu'au", self.envoyes[0])

    def test_abonnement_expire_redonne_un_lien(self):
        passe = (datetime.utcnow() - timedelta(days=1)).isoformat()
        with mock.patch.object(main, "feedback_db", faux_firestore({"tier": "PREMIUM", "premium_expire_le": passe})), \
                mock.patch.object(main, "send_whatsapp_boutons", return_value=True), \
                mock.patch.object(main.requests, "post", side_effect=AssertionError("choix d'abord")):
            self.assertEqual(self.envoyer("premium")["reason"], "premium_choix")

    def test_erreur_de_paiement_message_clair(self):
        with mock.patch.object(main, "feedback_db", faux_firestore(None)), \
                mock.patch.object(main.requests, "post", side_effect=RuntimeError("boom")):
            resultat = self.envoyer("premium orange")
        self.assertEqual(resultat["reason"], "premium_erreur")
        self.assertIn("momentanément indisponible", self.envoyes[0])


if __name__ == "__main__":
    unittest.main()
