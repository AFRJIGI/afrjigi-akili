"""Corrections issues du premier controle qualite (3 octobre)."""
import asyncio
import unittest
from datetime import datetime, timezone
from unittest import mock

import main

PHONE = "22500000070"
PRET = {
    "type_examen": "BAC_GENERAL", "serie": "D", "matiere": "MATHS", "mode": "examen",
    "profile_ready": True, "onboarding_step": "", "ville": "Abidjan", "matiere_confirmed": True,
    "profile_locked": True, "nom_ecole_asked": True, "first_learning_request_at": "2026-09-29T12:00:00+00:00",
}


class Base(unittest.TestCase):
    def sauver(self, phone, profil):
        self.etat = dict(profil)  # sauvegarde complete, comme Firestore sans merge

    def setUp(self):
        self.envoyes, self.boutons, self.akili, self.journal = [], [], [], []
        self.etat = {}
        noop = lambda *a, **k: None

        def evenement(phone, direction, texte, profile=None, message_id=None, extra=None):
            self.journal.append((direction, texte, dict(extra or {})))

        self.patches = [
            mock.patch.object(main, "send_whatsapp", side_effect=lambda phone, msg, *a, **k: self.envoyes.append(msg)),
            mock.patch.object(main, "send_whatsapp_boutons",
                              side_effect=lambda phone, corps, boutons: self.boutons.append((corps, boutons)) or True),
            mock.patch.object(main, "send_whatsapp_typing_indicator", side_effect=noop),
            mock.patch.object(main, "reserver_message_whatsapp", return_value=True),
            mock.patch.object(main, "charger_etat_whatsapp", side_effect=lambda phone: dict(self.etat)),
            mock.patch.object(main, "sauver_etat_whatsapp", side_effect=self.sauver),
            mock.patch.object(main, "save_whatsapp_event", side_effect=evenement),
            mock.patch.object(main, "maybe_send_marketing_consent_prompt", side_effect=noop),
            mock.patch.object(main, "detect_marketing_consent_command", return_value=None),
            mock.patch.object(main, "charger_historique_conv", return_value=[]),
            mock.patch.object(main, "sauver_historique_conv", side_effect=noop),
            mock.patch.object(main, "answer_learning_request",
                              side_effect=lambda phone, profile, texte, **k: self.akili.append((texte, k, dict(profile)))),
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
        corps = {"entry": [{"changes": [{"value": {"messages": [dict({"from": PHONE}, **message)]}}]}]}

        class Requete:
            async def json(self_inner):
                return corps

        return asyncio.run(main.receive_message(Requete()))


def texte(corps, mid, ts="1790000000"):
    return {"id": mid, "type": "text", "text": {"body": corps}, "timestamp": ts}


class InscriptionTests(Base):
    def test_plus_d_option_concours(self):
        main.ask_exam(PHONE)
        self.assertNotIn("Concours", self.envoyes[-1])
        self.assertIn("Réponds par a, b, c ou d.", self.envoyes[-1])
        profil = {"onboarding_step": "exam"}
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "e"))
        self.assertEqual(self.envoyes[-1].split("\n")[0], "Bienvenue sur Akili.")
        self.assertNotEqual(profil.get("type_examen"), "AUTRE")

    def test_profil_autre_ne_bloque_plus(self):
        self.etat = {"type_examen": "AUTRE", "serie": "AUTRE", "onboarding_step": "", "matiere": "MATHS"}
        self.envoyer(texte("ok", "a1"))
        self.assertIn(main.MESSAGE_HORS_CHAMP, self.envoyes)
        self.assertIn("Quel niveau prépares-tu", self.envoyes[-1])
        self.assertEqual(self.etat["onboarding_step"], "exam")
        self.assertNotEqual(self.etat.get("type_examen"), "AUTRE")
        # Une vraie question depuis un profil AUTRE : gardee, et retour a la premiere question
        self.etat = {"type_examen": "AUTRE", "serie": "AUTRE", "onboarding_step": "", "matiere": "MATHS"}
        main.processed_messages.clear()
        self.envoyer(texte("Explique moi les limites en maths", "a3"))
        self.assertEqual(self.etat["onboarding_step"], "exam")
        self.assertNotEqual(self.etat.get("type_examen"), "AUTRE")
        self.assertIn("Quel niveau prépares-tu", self.envoyes[-1])

    def test_libelles_du_mode_et_tape_menu(self):
        main.ask_mode(PHONE)
        self.assertIn("Akili t'explique pas à pas", self.envoyes[-1])
        self.assertIn("tu fais seul, Akili corrige et note", self.envoyes[-1])
        self.etat = dict(PRET)
        self.envoyer(texte("Tape menu", "a2"))
        self.assertIn("Que veux-tu faire", self.envoyes[-1])

    def test_photo_gardee_pendant_l_inscription(self):
        self.etat = {"type_examen": "BAC_GENERAL", "serie": "D", "matiere": "MATHS", "matiere_confirmed": True,
                     "onboarding_step": "mode"}
        photo = {"id": "p1", "type": "image", "timestamp": "1790000000", "image": {"id": "MEDIA123", "mime_type": "image/jpeg"}}
        with mock.patch.object(main, "download_whatsapp_media", return_value="/tmp/photo.jpg"):
            self.envoyer(photo)
        self.assertEqual(self.etat["onboarding_step"], "mode")  # l'inscription ne repart pas du debut
        self.assertEqual(self.etat["pending_media"]["media_id"], "MEDIA123")
        self.assertIn("J'ai gardé ta photo et ta question", self.envoyes[-2])
        self.assertIn("Tu veux travailler comment", self.envoyes[-1])
        # Fin de l'inscription : la photo est retelechargee et envoyee a Akili
        self.etat.update({"onboarding_step": "nom_ecole", "mode": "etude", "ville": "Abidjan"})
        with mock.patch.object(main, "download_whatsapp_media", return_value="/tmp/photo2.jpg") as dl:
            self.envoyer(texte("passer", "p2"))
        dl.assert_called_once()
        self.assertEqual(self.akili[-1][1]["media_file"], "/tmp/photo2.jpg")
        self.assertIn("Je reprends ton exercice en photo.", self.envoyes)


class JournalTests(Base):
    def test_heure_de_meta_et_vrai_texte(self):
        self.etat = dict(PRET, mode="etude")
        with mock.patch.object(main, "is_contextual_exercise_answer", return_value=True), \
             mock.patch.object(main, "short_answer_has_exercise_context", return_value=True):
            self.envoyer(texte("0", "j1", ts="1790000000"))
        entrant = [j for j in self.journal if j[0] == "inbound"][-1]
        self.assertEqual(entrant[1], "0")
        self.assertEqual(entrant[2]["created_at"], datetime.fromtimestamp(1790000000, timezone.utc).isoformat())
        self.assertIn("vient de répondre uniquement", entrant[2]["texte_traite"])


class ContexteTests(unittest.TestCase):
    def test_question_recente_suffit(self):
        with mock.patch.object(main, "get_recent_phone_context_text", return_value="assistant: Calcule 0t + 2 pour t = 0. Que trouves-tu ?"), \
             mock.patch.object(main, "load_last_assistant_context", return_value="Calcule 0t + 2 pour t = 0. Que trouves-tu ?"):
            self.assertTrue(main.short_answer_has_exercise_context(PHONE))

    def test_longue_reponse_non_coupee(self):
        longue = ("Phrase d'explication assez longue pour le test. " * 25).strip() + " Que trouves-tu ?"
        self.assertGreater(len(longue), 1000)
        parties = main.split_whatsapp_message(longue, limit=1600, max_parts=1)
        self.assertTrue(parties[0].rstrip().endswith("trouves-tu?"), parties[0][-40:])


class ModeEtudeTests(Base):
    def test_offre_puis_oui(self):
        self.etat = dict(PRET)
        resultat = self.envoyer(texte("Explique moi comment faire stp", "m1"))
        self.assertEqual(resultat["reason"], "offre_mode_etude")
        self.assertEqual([b[0] for b in self.boutons[-1][1]], ["mode_etude_oui", "mode_examen_garder"])
        self.assertEqual(self.etat["demande_mode_etude"]["texte"], "Explique moi comment faire stp")
        bouton = {"id": "m2", "type": "interactive",
                  "interactive": {"type": "button_reply", "button_reply": {"id": "mode_etude_oui", "title": "Oui, mode étude"}}}
        self.assertEqual(self.envoyer(bouton)["reason"], "choix_mode")
        self.assertEqual(self.etat["mode"], "etude")
        self.assertEqual(self.akili[-1][0], "Explique moi comment faire stp")
        self.assertEqual(self.akili[-1][2]["mode"], "etude")

    def test_non_puis_pas_de_nouvelle_offre(self):
        self.etat = dict(PRET)
        self.envoyer(texte("je ne comprends pas", "n1"))
        bouton = {"id": "n2", "type": "interactive",
                  "interactive": {"type": "button_reply", "button_reply": {"id": "mode_examen_garder", "title": "Non"}}}
        self.envoyer(bouton)
        self.assertEqual(self.etat["mode"], "examen")
        self.assertIn("on reste en mode examen", self.envoyes[-1])
        nb = len(self.boutons)
        self.envoyer(texte("je ne comprends pas", "n3"))
        self.assertEqual(len(self.boutons), nb)  # pas de nouvelle offre pendant 30 min

    def test_pas_d_offre_en_mode_etude_ni_pour_une_photo(self):
        self.assertFalse(main.demande_explication("Analyse ce sujet envoyé en fichier et guide-moi pas à pas."))
        self.assertFalse(main.proposer_mode_etude(PHONE, dict(PRET, mode="etude"), "explique moi"))
        self.assertTrue(main.demande_explication("Je suis bloqué"))


if __name__ == "__main__":
    unittest.main()
