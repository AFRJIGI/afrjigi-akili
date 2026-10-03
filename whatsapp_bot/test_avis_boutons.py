"""Avis de fin de seance : trois boutons, puis un commentaire si l'eleve n'est pas satisfait."""
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import main

PHONE = "22500000040"
PROFIL = {
    "type_examen": "BAC_TECHNIQUE", "serie": "G1", "matiere": "ECO", "mode": "etude",
    "profile_ready": True, "onboarding_step": "", "ville": "Abidjan", "matiere_confirmed": True,
    "profile_locked": True, "nom_ecole_asked": True,
    "first_learning_request_at": "2026-09-29T12:00:00+00:00",
}


class FauxRequete:
    def __init__(self, message):
        self._body = {"entry": [{"changes": [{"value": {"messages": [dict(message, **{"from": PHONE})]}}]}]}

    async def json(self):
        return self._body


def bouton(ident, titre, mid):
    return {"id": mid, "type": "interactive",
            "interactive": {"type": "button_reply", "button_reply": {"id": ident, "title": titre}}}


def texte(corps, mid):
    return {"id": mid, "type": "text", "text": {"body": corps}}


class AvisBoutonsTests(unittest.TestCase):
    def setUp(self):
        self.etat = dict(PROFIL)
        self.envoyes = []
        self.avis = []
        noop = lambda *a, **k: None

        def sauver(phone, profil):
            self.etat = dict(profil)

        self.patches = [
            mock.patch.object(main, "send_whatsapp", side_effect=lambda phone, msg, *a, **k: self.envoyes.append(msg)),
            mock.patch.object(main, "send_whatsapp_typing_indicator", side_effect=noop),
            mock.patch.object(main, "reserver_message_whatsapp", return_value=True),
            mock.patch.object(main, "charger_etat_whatsapp", side_effect=lambda phone: dict(self.etat)),
            mock.patch.object(main, "sauver_etat_whatsapp", side_effect=sauver),
            mock.patch.object(main, "save_whatsapp_event", side_effect=noop),
            mock.patch.object(main, "maybe_send_marketing_consent_prompt", side_effect=noop),
            mock.patch.object(main, "detect_marketing_consent_command", side_effect=AssertionError("pas de consentement")),
            mock.patch.object(main, "enregistrer_avis_seance",
                              side_effect=lambda phone, note, profile=None, commentaire=None: self.avis.append((note, commentaire)) or True),
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

    def envoyer(self, message):
        return asyncio.run(main.receive_message(FauxRequete(message)))

    def test_oui(self):
        resultat = self.envoyer(bouton("avis_oui", "Oui 👍", "m1"))
        self.assertEqual(resultat["reason"], "avis_seance")
        self.assertEqual(self.avis, [("oui", None)])
        self.assertEqual(self.envoyes, [main.MESSAGE_MERCI_AVIS])
        self.assertNotIn("attente_commentaire_avis", self.etat)

    def test_non_puis_commentaire(self):
        self.envoyer(bouton("avis_non", "Non", "m2"))
        self.assertEqual(self.envoyes[-1], main.MESSAGE_DEMANDE_COMMENTAIRE)
        self.assertEqual(self.etat["attente_commentaire_avis"]["note"], "non")
        main.processed_messages.clear()
        with mock.patch.object(main, "detect_marketing_consent_command", return_value=None):
            resultat = self.envoyer(texte("Les explications sont trop longues", "m3"))
        self.assertEqual(resultat["reason"], "commentaire_avis")
        self.assertEqual(self.avis[-1], ("non", "Les explications sont trop longues"))
        self.assertEqual(self.envoyes[-1], main.MESSAGE_MERCI_COMMENTAIRE)
        self.assertNotIn("attente_commentaire_avis", self.etat)

    def test_passer(self):
        self.envoyer(bouton("avis_un_peu", "Un peu", "m4"))
        with mock.patch.object(main, "detect_marketing_consent_command", return_value=None):
            self.envoyer(texte("passer", "m5"))
        self.assertEqual(self.avis, [("un_peu", None)])
        self.assertEqual(self.envoyes[-1], main.MESSAGE_PASSER_COMMENTAIRE)

    def test_commande_ou_delai_depasse_annule_l_attente(self):
        profil = {"attente_commentaire_avis": {"note": "non", "at": datetime.now(timezone.utc).isoformat()}}
        self.assertIsNone(main.commentaire_avis_attendu(dict(profil), "menu"))
        vieux = {"attente_commentaire_avis": {"note": "non",
                                              "at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()}}
        self.assertIsNone(main.commentaire_avis_attendu(vieux, "trop long"))
        self.assertNotIn("attente_commentaire_avis", vieux)
        self.assertEqual(main.commentaire_avis_attendu(dict(profil), "trop long"), "non")

    def test_boutons_envoyes_apres_le_bilan_et_secours_sans_boutons(self):
        with mock.patch.object(main, "send_whatsapp_boutons", return_value=False):
            main.demander_avis_seance(PHONE)
        self.assertEqual(self.envoyes[-1], main.MESSAGE_AVIS_FIN_SESSION)


if __name__ == "__main__":
    unittest.main()
