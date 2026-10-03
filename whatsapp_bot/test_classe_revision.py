"""Classe demandee a l'inscription (BAC Technique) et defi de revision le lendemain."""
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import main

PHONE = "22500000060"
NOW = datetime(2026, 10, 4, 15, 0, tzinfo=timezone.utc)
PROFIL = {
    "type_examen": "BAC_TECHNIQUE", "serie": "F1", "classe": "PREMIERE", "matiere": "CMI", "mode": "etude",
    "profile_ready": True, "onboarding_step": "", "ville": "Abidjan", "matiere_confirmed": True,
    "profile_locked": True, "nom_ecole_asked": True, "first_learning_request_at": "2026-09-29T12:00:00+00:00",
}
CLE = f"{PHONE}:BAC_TECHNIQUE:F1:CMI:etude"


def session(**k):
    base = {"conversation_key": CLE, "bilan_envoye": True, "bilan_texte": "À revoir : la cotation",
            "nb_echanges": 4, "messages": [{"role": "user", "content": "cotation ?"}],
            "matiere": "CMI", "serie": "F1", "type_examen": "BAC_TECHNIQUE",
            "derniere_activite": (NOW - timedelta(hours=20)).isoformat()}
    base.update(k)
    return base


class ClasseTests(unittest.TestCase):
    def setUp(self):
        self.envoyes = []
        self.patches = [
            mock.patch.object(main, "send_whatsapp", side_effect=lambda phone, msg, *a, **k: self.envoyes.append(msg)),
            mock.patch.object(main, "sauver_etat_whatsapp"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        main.user_profiles.pop(PHONE, None)

    def test_serie_puis_classe_puis_matieres(self):
        profil = {"type_examen": "BAC_TECHNIQUE", "onboarding_step": "serie_technique"}
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "e"))
        self.assertIn("Tu es en quelle classe", self.envoyes[-1])
        self.assertEqual(profil["onboarding_step"], "classe_technique")
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "Première"))
        self.assertEqual(profil["classe"], "PREMIERE")
        self.assertEqual(profil["onboarding_step"], "matiere")
        self.assertIn("a. Construction mécanique industrielle (CMI)", self.envoyes[-1])

    def test_mauvaise_reponse_repose_la_question(self):
        profil = {"type_examen": "BAC_TECHNIQUE", "serie": "F1", "onboarding_step": "classe_technique"}
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "voiture"))
        self.assertIn("Tu es en quelle classe", self.envoyes[-1])

    def test_classe_envoyee_a_akili(self):
        self.assertIn("(BAC Technique, série F1, Première)", main.consigne_matiere_choisie("CMI", "F1", "BAC_TECHNIQUE", "PREMIERE"))
        envoye = {}

        class Reponse:
            status_code, text = 200, ""

            def json(self):
                return {"reponse": "ok"}

        def faux_post(url, files=None, timeout=None, **k):
            envoye.update({c: v[1] for c, v in (files or {}).items()})
            return Reponse()

        with mock.patch.object(main.requests, "post", side_effect=faux_post):
            main.get_akili_response("Propose-moi un exercice", "CMI", "F1", [], phone="225",
                                    type_examen="BAC_TECHNIQUE", mode="etude", classe="PREMIERE")
        self.assertEqual(envoye["classe"], "PREMIERE")
        self.assertIn("Première", envoye["question"])


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.envoyes, self.notes, self.historique = [], [], []
        self.sessions = [(PHONE, session())]
        self.profil = dict(PROFIL)
        self.patches = [
            mock.patch.object(main, "send_whatsapp", side_effect=lambda phone, msg, *a, **k: self.envoyes.append(msg)),
            mock.patch.object(main, "lister_sessions_pour_revision", side_effect=lambda now, limite=200: list(self.sessions)),
            mock.patch.object(main, "charger_etat_whatsapp", side_effect=lambda phone: dict(self.profil)),
            mock.patch.object(main, "reserver_revision", side_effect=lambda phone: dict(self.sessions[0][1])),
            mock.patch.object(main, "noter_session_bilan", side_effect=lambda phone, champs: self.notes.append(champs)),
            mock.patch.object(main, "generer_revision", return_value="Hier, tu as travaillé la cotation.\nPetit défi de 2 minutes : ...\nRéponds par a, b ou c."),
            mock.patch.object(main, "ajouter_a_historique", side_effect=lambda cle, texte: self.historique.append((cle, texte))),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        main.user_profiles.pop(PHONE, None)

    def test_envoi(self):
        self.assertEqual(main.traiter_revisions_lendemain(now=NOW), {"revisions": 1})
        self.assertIn("Petit défi", self.envoyes[-1])
        self.assertIn(main.MESSAGE_ARRET_REVISION, self.envoyes[-1])
        self.assertEqual(self.historique[0][0], CLE)
        self.assertIn({"revision_statut": "envoyee"}, self.notes)

    def test_pas_la_nuit(self):
        self.assertEqual(main.traiter_revisions_lendemain(now=NOW.replace(hour=22)), {"revisions": 0})
        self.assertEqual(self.envoyes, [])

    def test_refus_ou_changement_de_matiere(self):
        self.profil["revisions_off"] = True
        self.assertEqual(main.traiter_revisions_lendemain(now=NOW), {"revisions": 0})
        self.profil = dict(PROFIL, matiere="AUTOMATISME")
        self.assertEqual(main.traiter_revisions_lendemain(now=NOW), {"revisions": 0})
        self.assertEqual(self.envoyes, [])
        self.assertTrue(all(n.get("revision_statut") == "ignoree" for n in self.notes))

    def test_seance_non_eligible(self):
        for s in [session(bilan_texte=""), session(nb_echanges=1), session(revision_envoyee=True), session(bilan_envoye=False)]:
            self.assertFalse(main.session_eligible_revision(s))
        self.assertTrue(main.session_eligible_revision(session()))

    def test_bilan_texte_conserve(self):
        with mock.patch.object(main, "reserver_bilan", return_value=session(bilan_envoye=False)), \
             mock.patch.object(main, "generer_bilan_session", return_value="Bravo. À revoir : la cotation"), \
             mock.patch.object(main, "demander_avis_seance"):
            main.envoyer_fin_de_session(PHONE, "au_revoir")
        self.assertIn({"bilan_texte": "Bravo. À revoir : la cotation"}, self.notes)


class ContexteTests(unittest.TestCase):
    def test_dernier_message_d_akili_toujours_inclus(self):
        main.conversations.clear()
        main.conversations[CLE] = [{"role": "assistant", "content": "Ancien exercice d'hier"}]
        with mock.patch.object(main, "load_last_assistant_context", return_value="Petit défi de 2 minutes : a. b. c."):
            ctx = main.get_recent_phone_context_text(PHONE)
        main.conversations.clear()
        self.assertTrue(ctx.endswith("assistant: Petit défi de 2 minutes : a. b. c."))


class CommandeRevisionTests(unittest.TestCase):
    def test_pas_de_revision(self):
        envoyes, etat = [], dict(PROFIL)

        class Requete:
            async def json(self):
                return {"entry": [{"changes": [{"value": {"messages": [
                    {"from": PHONE, "id": "wamid.rev", "type": "text", "text": {"body": "Pas de révision"}}]}}]}]}

        noop = lambda *a, **k: None
        with mock.patch.object(main, "send_whatsapp", side_effect=lambda phone, msg, *a, **k: envoyes.append(msg)), \
             mock.patch.object(main, "send_whatsapp_typing_indicator", side_effect=noop), \
             mock.patch.object(main, "reserver_message_whatsapp", return_value=True), \
             mock.patch.object(main, "charger_etat_whatsapp", side_effect=lambda phone: dict(etat)), \
             mock.patch.object(main, "sauver_etat_whatsapp", side_effect=lambda phone, p: etat.update(p)), \
             mock.patch.object(main, "save_whatsapp_event", side_effect=noop), \
             mock.patch.object(main, "maybe_send_marketing_consent_prompt", side_effect=noop):
            main.processed_messages.clear()
            resultat = asyncio.run(main.receive_message(Requete()))
        main.user_profiles.pop(PHONE, None)
        self.assertEqual(resultat["reason"], "revisions_off")
        self.assertTrue(etat["revisions_off"])
        self.assertIn("plus de défi", envoyes[-1])


if __name__ == "__main__":
    unittest.main()
