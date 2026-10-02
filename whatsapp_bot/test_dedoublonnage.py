"""Plusieurs copies Cloud Run : un message renvoye par Meta n'est traite qu'une fois,
et chaque message repart de l'etat Firestore, pas de la memoire (perimee) de la copie."""
import asyncio
import unittest
from unittest import mock

import main

PHONE = "22500000009"
PROFIL = {
    "type_examen": "BAC_TECHNIQUE", "serie": "G1", "matiere": "ECO", "mode": "etude",
    "profile_ready": True, "onboarding_step": "", "ville": "Abidjan", "matiere_confirmed": True,
    "profile_locked": True, "nom_ecole_asked": True,
    "first_learning_request_at": "2026-09-29T12:00:00+00:00",
}


class FauxRequete:
    def __init__(self, texte, message_id=None):
        self._body = {"entry": [{"changes": [{"value": {"messages": [
            {"from": PHONE, "id": message_id or f"wamid.{texte}", "type": "text", "text": {"body": texte}}
        ]}}]}]}

    async def json(self):
        return self._body


class AlreadyExists(Exception):
    """Meme nom que google.api_core.exceptions.AlreadyExists."""


class BaseWebhook(unittest.TestCase):
    def setUp(self):
        self.firestore_etat = {}       # whatsapp_state
        self.registre = set()          # whatsapp_messages_traites
        self.envoyes = []
        self.sauvegardes = []
        noop = lambda *a, **k: None

        def reserver(message_id):
            if message_id in self.registre:
                return False
            self.registre.add(message_id)
            return True

        def charger(phone):
            main._etat_lecture_echouee.discard(phone)
            return dict(self.firestore_etat.get(phone) or {})

        def sauver(phone, profile):
            self.sauvegardes.append((phone, dict(profile)))
            self.firestore_etat[phone] = dict(profile)

        def effacer(phone):
            self.firestore_etat.pop(phone, None)

        self.patches = [
            mock.patch.object(main, "reserver_message_whatsapp", side_effect=reserver),
            mock.patch.object(main, "liberer_message_whatsapp", side_effect=lambda mid: self.registre.discard(mid)),
            mock.patch.object(main, "charger_etat_whatsapp", side_effect=charger),
            mock.patch.object(main, "sauver_etat_whatsapp", side_effect=sauver),
            mock.patch.object(main, "effacer_etat_whatsapp", side_effect=effacer),
            mock.patch.object(main, "send_whatsapp", side_effect=lambda phone, msg, *a, **k: self.envoyes.append(msg)),
            mock.patch.object(main, "send_whatsapp_typing_indicator", side_effect=noop),
            mock.patch.object(main, "save_whatsapp_event", side_effect=noop),
            mock.patch.object(main, "maybe_send_marketing_consent_prompt", side_effect=noop),
            mock.patch.object(main, "p0_enabled", return_value=False),
            mock.patch.object(main, "answer_learning_request", side_effect=AssertionError("Akili ne doit pas etre appele")),
        ]
        for p in self.patches:
            p.start()
        main.processed_messages.clear()
        main.user_profiles.pop(PHONE, None)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        main.processed_messages.clear()
        main.user_profiles.pop(PHONE, None)

    def envoyer(self, texte, message_id=None):
        return asyncio.run(main.receive_message(FauxRequete(texte, message_id)))

    def autre_copie(self):
        """La copie suivante n'a pas la memoire de la precedente."""
        main.processed_messages.clear()


class DoublonsTests(BaseWebhook):
    def test_message_renvoye_par_meta_traite_une_seule_fois_meme_sur_une_autre_copie(self):
        self.firestore_etat[PHONE] = dict(PROFIL)
        self.envoyer("profil", "wamid.A")
        self.assertEqual(len(self.envoyes), 1)
        self.autre_copie()
        resultat = self.envoyer("profil", "wamid.A")
        self.assertEqual(resultat.get("reason"), "duplicate")
        self.assertEqual(len(self.envoyes), 1)
        # Un nouveau message est bien traite.
        self.envoyer("profil", "wamid.B")
        self.assertEqual(len(self.envoyes), 2)

    def test_reset_renvoye_ne_rejoue_pas(self):
        self.firestore_etat[PHONE] = dict(PROFIL)
        self.envoyer("reset", "wamid.R")
        self.autre_copie()
        self.envoyer("reset", "wamid.R")
        self.assertEqual(sum("Profil réinitialisé" in m for m in self.envoyes), 1)


class EtatFraisTests(BaseWebhook):
    def test_memoire_perimee_ignoree(self):
        main.user_profiles[PHONE] = dict(PROFIL, mode="examen", type_examen="BEPC")  # vieille copie
        self.firestore_etat[PHONE] = dict(PROFIL)
        self.envoyer("profil")
        self.assertIn("mode=etude", self.envoyes[-1])
        self.assertIn("BAC_TECHNIQUE", self.envoyes[-1])

    def test_reset_fait_sur_une_autre_copie_respecte(self):
        main.user_profiles[PHONE] = dict(PROFIL)   # cette copie se souvient encore
        self.envoyer("profil")                      # Firestore vide : reset fait ailleurs
        self.assertIn("série=TOUTES", self.envoyes[-1])

    def test_lecture_firestore_en_panne_garde_la_memoire(self):
        main.user_profiles[PHONE] = dict(PROFIL)

        def panne(phone):
            main._etat_lecture_echouee.add(phone)
            return {}

        with mock.patch.object(main, "charger_etat_whatsapp", side_effect=panne):
            self.envoyer("profil")
        main._etat_lecture_echouee.discard(PHONE)
        self.assertIn("série=G1", self.envoyes[-1])


class SauvegardeFinDeMessageTests(BaseWebhook):
    def test_etape_onboarding_sauvee_pour_la_copie_suivante(self):
        self.envoyer("bonjour")
        self.assertEqual(self.firestore_etat[PHONE].get("onboarding_step"), "exam")
        main.user_profiles.pop(PHONE, None)
        self.autre_copie()
        self.envoyer("profil")  # repart bien de l'etape "exam"
        self.assertEqual(self.firestore_etat[PHONE].get("onboarding_step"), "exam")

    def test_rien_sauve_apres_reset(self):
        self.firestore_etat[PHONE] = dict(PROFIL)
        self.envoyer("reset")
        self.assertNotIn(PHONE, self.firestore_etat)

    def test_doublon_ne_sauve_rien(self):
        self.registre.add("wamid.D")
        self.envoyer("bonjour", "wamid.D")
        self.assertEqual(self.sauvegardes, [])


class FirestoreFonctionsTests(unittest.TestCase):
    def setUp(self):
        self.doc = mock.MagicMock()
        db = mock.MagicMock()
        db.collection.return_value.document.return_value = self.doc
        self.patch = mock.patch.object(main, "feedback_db", db)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        main._etat_lecture_echouee.discard(PHONE)

    def test_sauvegarde_complete_sauf_si_lecture_en_panne(self):
        main.sauver_etat_whatsapp(PHONE, {"a": 1})
        self.assertEqual(self.doc.set.call_args.kwargs, {"merge": False})
        main._etat_lecture_echouee.add(PHONE)
        main.sauver_etat_whatsapp(PHONE, {"a": 1})
        self.assertEqual(self.doc.set.call_args.kwargs, {"merge": True})

    def test_lecture_en_panne_signalee(self):
        self.doc.get.side_effect = RuntimeError("Firestore indisponible")
        self.assertEqual(main.charger_etat_whatsapp(PHONE), {})
        self.assertIn(PHONE, main._etat_lecture_echouee)
        self.doc.get.side_effect = None
        self.doc.get.return_value.exists = False
        main.charger_etat_whatsapp(PHONE)
        self.assertNotIn(PHONE, main._etat_lecture_echouee)

    def test_reserver_message(self):
        self.assertTrue(main.reserver_message_whatsapp("wamid.X"))
        self.doc.create.side_effect = AlreadyExists("409")
        self.assertFalse(main.reserver_message_whatsapp("wamid.X"))
        self.doc.create.side_effect = RuntimeError("panne")
        self.assertTrue(main.reserver_message_whatsapp("wamid.X"))
        self.assertTrue(main.reserver_message_whatsapp(None))


if __name__ == "__main__":
    unittest.main()
