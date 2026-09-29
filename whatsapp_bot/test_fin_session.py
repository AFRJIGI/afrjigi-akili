"""Fin de session : bilan quand l'eleve dit au revoir, ou apres 30 min de pause."""
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import main

NOW = datetime(2026, 9, 29, 18, 0, tzinfo=timezone.utc)
PHONE = "22500000003"
PROFIL = {
    "type_examen": "BAC_TECHNIQUE", "serie": "G1", "matiere": "ECO", "mode": "etude",
    "profile_ready": True, "onboarding_step": "", "ville": "Abidjan", "matiere_confirmed": True,
    "profile_locked": True, "nom_ecole_asked": True,
    "first_learning_request_at": "2026-09-29T12:00:00+00:00",
}


class FauxStockage:
    """Remplace la collection Firestore whatsapp_sessions_bilan par un dict."""

    def __init__(self):
        self.docs = {}

    def charger(self, phone):
        doc = self.docs.get(phone)
        return dict(doc) if doc else None

    def sauver(self, phone, session):
        self.docs[phone] = dict(session)

    def fermer(self, phone, raison):
        self.docs[phone].update({"bilan_envoye": True, "bilan_source": raison})

    def reserver(self, phone, source, min_echanges=1):
        session = self.docs.get(phone)
        if not session or session.get("bilan_envoye") or int(session.get("nb_echanges", 0)) < min_echanges:
            return None
        avant = dict(session)
        session.update({"bilan_envoye": True, "bilan_source": source})
        return avant

    def lister(self, limite=200):
        return [(p, dict(d)) for p, d in self.docs.items() if not d.get("bilan_envoye")]


class BaseFinSession(unittest.TestCase):
    def setUp(self):
        self.stock = FauxStockage()
        self.envoyes = []
        self.bilans = []
        noop = lambda *a, **k: None
        self.patches = [
            mock.patch.object(main, "charger_session_bilan", side_effect=self.stock.charger),
            mock.patch.object(main, "sauver_session_bilan", side_effect=self.stock.sauver),
            mock.patch.object(main, "fermer_session_bilan", side_effect=self.stock.fermer),
            mock.patch.object(main, "reserver_bilan", side_effect=self.stock.reserver),
            mock.patch.object(main, "lister_sessions_en_attente", side_effect=self.stock.lister),
            mock.patch.object(main, "send_whatsapp", side_effect=lambda phone, msg, *a, **k: self.envoyes.append((phone, msg))),
            mock.patch.object(main, "generer_bilan_session",
                              side_effect=lambda session, source: self.bilans.append((session, source)) or f"BILAN {session.get('mode')} {source}"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def ajouter_echanges(self, n, debut=NOW, mode="etude", cle=f"{PHONE}:BAC_TECHNIQUE:G1:ECO:etude"):
        for i in range(n):
            main.journal_session_ajouter(PHONE, dict(PROFIL, mode=mode), cle, mode,
                                         f"question {i}", f"reponse {i}", now=debut + timedelta(minutes=i))


class DetectionAuRevoirTests(unittest.TestCase):
    def test_messages_de_fin(self):
        for texte in ["Merci, au revoir", "bonne nuit", "A demain !", "Je m'arrête là pour aujourd'hui",
                      "c'est fini pour aujourd'hui", "bye", "Aurevoir Akili", "je dois y aller merci"]:
            self.assertTrue(main.est_message_au_revoir(texte), texte)

    def test_pas_des_messages_de_fin(self):
        for texte in ["j'ai fini", "terminer", "merci", "a plus b", "Comment dit-on au revoir en anglais ?",
                      "Je m'arrête à la question 2, je ne comprends pas", "b",
                      "Explique la notion de bonne nuit dans le texte que je t'ai envoyé ce matin stp"]:
            self.assertFalse(main.est_message_au_revoir(texte), texte)


class JournalSessionTests(BaseFinSession):
    def test_echanges_ajoutes_a_la_meme_session(self):
        self.ajouter_echanges(3)
        session = self.stock.docs[PHONE]
        self.assertEqual(session["nb_echanges"], 3)
        self.assertEqual(len(session["messages"]), 6)
        self.assertFalse(session["bilan_envoye"])
        self.assertEqual(session["matiere"], "ECO")

    def test_nouvelle_session_apres_pause_ou_changement_de_matiere(self):
        self.ajouter_echanges(2)
        self.ajouter_echanges(1, debut=NOW + timedelta(minutes=45))
        self.assertEqual(self.stock.docs[PHONE]["nb_echanges"], 1)
        self.ajouter_echanges(1, debut=NOW + timedelta(minutes=46), cle=f"{PHONE}:BAC_TECHNIQUE:G1:DROIT:etude")
        self.assertEqual(self.stock.docs[PHONE]["nb_echanges"], 1)

    def test_nouvelle_session_apres_un_bilan(self):
        self.ajouter_echanges(2)
        main.envoyer_fin_de_session(PHONE, "au_revoir")
        self.ajouter_echanges(1, debut=NOW + timedelta(minutes=5))
        self.assertEqual(self.stock.docs[PHONE]["nb_echanges"], 1)
        self.assertFalse(self.stock.docs[PHONE]["bilan_envoye"])


class AuRevoirTests(BaseFinSession):
    def test_bilan_puis_simple_au_revoir(self):
        self.ajouter_echanges(2, mode="examen", cle=f"{PHONE}:BAC_TECHNIQUE:G1:ECO:examen")
        self.assertTrue(main.envoyer_fin_de_session(PHONE, "au_revoir"))
        self.assertIn("BILAN examen au_revoir", self.envoyes[-1][1])
        self.assertIn("retour:", self.envoyes[-1][1])
        # Deuxieme au revoir : pas de second bilan.
        self.assertFalse(main.envoyer_fin_de_session(PHONE, "au_revoir"))
        self.assertEqual(self.envoyes[-1][1], main.MESSAGE_AU_REVOIR_SIMPLE)
        self.assertEqual(len(self.bilans), 1)

    def test_au_revoir_sans_session(self):
        self.assertFalse(main.envoyer_fin_de_session(PHONE, "au_revoir"))
        self.assertEqual(self.envoyes[-1][1], main.MESSAGE_AU_REVOIR_SIMPLE)


class InactiviteTests(BaseFinSession):
    def test_bilan_seulement_apres_30_min_et_une_seule_fois(self):
        self.ajouter_echanges(3)  # derniere activite a NOW + 2 min
        self.assertEqual(main.traiter_bilans_inactivite(now=NOW + timedelta(minutes=20)), {"envoyes": 0, "fermees": 0})
        self.assertEqual(main.traiter_bilans_inactivite(now=NOW + timedelta(minutes=40)), {"envoyes": 1, "fermees": 0})
        self.assertEqual(self.bilans[-1][1], "inactivite")
        self.assertEqual(main.traiter_bilans_inactivite(now=NOW + timedelta(minutes=50)), {"envoyes": 0, "fermees": 0})

    def test_session_trop_courte_ou_trop_ancienne_fermee_sans_message(self):
        self.ajouter_echanges(1)
        self.assertEqual(main.traiter_bilans_inactivite(now=NOW + timedelta(minutes=40)), {"envoyes": 0, "fermees": 1})
        self.stock.docs.clear()
        self.ajouter_echanges(3)
        self.assertEqual(main.traiter_bilans_inactivite(now=NOW + timedelta(hours=30)), {"envoyes": 0, "fermees": 1})
        self.assertEqual(self.envoyes, [])


class FauxRequete:
    def __init__(self, texte=None, headers=None):
        self.headers = headers or {}
        self._body = {"entry": [{"changes": [{"value": {"messages": [
            {"from": PHONE, "id": f"wamid.{texte}", "type": "text", "text": {"body": texte}}
        ]}}]}]}

    async def json(self):
        return self._body


class WebhookEtTacheTests(BaseFinSession):
    def setUp(self):
        super().setUp()
        noop = lambda *a, **k: None
        self.patches_webhook = [
            mock.patch.object(main, "send_whatsapp_typing_indicator", side_effect=noop),
            mock.patch.object(main, "charger_etat_whatsapp", side_effect=lambda phone: dict(PROFIL)),
            mock.patch.object(main, "sauver_etat_whatsapp", side_effect=noop),
            mock.patch.object(main, "save_whatsapp_event", side_effect=noop),
            mock.patch.object(main, "maybe_send_marketing_consent_prompt", side_effect=noop),
            mock.patch.object(main, "answer_learning_request", side_effect=AssertionError("Akili ne doit pas etre appele")),
        ]
        for p in self.patches_webhook:
            p.start()
        main.user_profiles[PHONE] = dict(PROFIL)

    def tearDown(self):
        for p in self.patches_webhook:
            p.stop()
        main.user_profiles.pop(PHONE, None)
        super().tearDown()

    def test_au_revoir_dans_le_webhook(self):
        self.ajouter_echanges(2)
        resultat = asyncio.run(main.receive_message(FauxRequete("Merci, au revoir")))
        self.assertEqual(resultat.get("reason"), "fin_session")
        self.assertIn("BILAN etude au_revoir", self.envoyes[-1][1])

    def test_tache_refusee_sans_secret(self):
        with mock.patch.dict("os.environ", {"TACHES_SECRET": "s3cret"}):
            refus = asyncio.run(main.tache_bilans_inactivite(FauxRequete(headers={"X-Akili-Tache": "faux"})))
            self.assertEqual(refus.status_code, 403)
            ok = asyncio.run(main.tache_bilans_inactivite(FauxRequete(headers={"X-Akili-Tache": "s3cret"})))
            self.assertEqual(ok["status"], "ok")
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(asyncio.run(main.tache_bilans_inactivite(FauxRequete(headers={}))).status_code, 403)


if __name__ == "__main__":
    unittest.main()
