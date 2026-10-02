"""Reset efface tout ce que Firestore garde de l'eleve, et l'historique est relu
depuis Firestore (la memoire d'une copie Cloud Run peut etre perimee)."""
import unittest
from unittest import mock

import main

PHONE = "22500000011"
PROFIL = {"type_examen": "BEPC", "serie": "BEPC", "matiere": "ANGLAIS", "mode": "etude",
          "first_learning_request_at": "2026-09-29T12:00:00+00:00"}
CLE = f"{PHONE}:BEPC:BEPC:ANGLAIS:etude"


class FauxDoc:
    def __init__(self, db, collection, doc_id):
        self.db, self.collection, self.id = db, collection, doc_id
        self.reference = self

    def delete(self):
        self.db.supprimes.append((self.collection, self.id))


class FauxRequeteFirestore:
    def __init__(self, db, collection, filtres=()):
        self.db, self.collection, self.filtres = db, collection, list(filtres)

    def where(self, champ, op, valeur):
        return FauxRequeteFirestore(self.db, self.collection, self.filtres + [(champ, op, valeur)])

    def document(self, doc_id):
        return FauxDoc(self.db, self.collection, doc_id)

    def stream(self):
        ops = {">=": lambda a, b: a >= b, "<": lambda a, b: a < b}
        for cle in self.db.historiques:
            if all(ops[op](cle, v) for _, op, v in self.filtres):
                yield FauxDoc(self.db, self.collection, cle)


class FauxDb:
    def __init__(self, historiques):
        self.historiques = historiques
        self.supprimes = []

    def collection(self, nom):
        return FauxRequeteFirestore(self, nom)


class EffacerTracesTests(unittest.TestCase):
    def test_reset_efface_historiques_contexte_et_session(self):
        db = FauxDb([CLE, f"{PHONE}:BEPC:BEPC:MATHS:examen", "22500000012:BEPC:BEPC:ANGLAIS:etude"])
        with mock.patch.object(main, "feedback_db", db):
            main.effacer_traces_conversation(PHONE)
        self.assertIn(("whatsapp_historiques", CLE), db.supprimes)
        self.assertIn(("whatsapp_historiques", f"{PHONE}:BEPC:BEPC:MATHS:examen"), db.supprimes)
        self.assertNotIn(("whatsapp_historiques", "22500000012:BEPC:BEPC:ANGLAIS:etude"), db.supprimes)
        self.assertIn(("whatsapp_contexts", PHONE), db.supprimes)
        self.assertIn(("whatsapp_sessions_bilan", PHONE), db.supprimes)


class HistoriqueFraisTests(unittest.TestCase):
    def setUp(self):
        main.conversations.clear()
        main.conversations[CLE] = [
            {"role": "assistant", "content": "Tu es en MODE EXAMEN ACTIVE. Envoie la photo de ta copie."},
        ]
        self.patches = [
            mock.patch.object(main, "p0_enabled", return_value=False),
            mock.patch.object(main, "send_whatsapp", return_value=None),
            mock.patch.object(main, "send_whatsapp_typing_indicator", return_value=None),
            mock.patch.object(main, "sauver_historique_conv", return_value=None),
            mock.patch.object(main, "journal_session_ajouter", return_value=None),
            mock.patch.object(main, "mark_first_learning_request", side_effect=lambda phone, profile: profile),
        ]
        for p in self.patches:
            p.start()
        self.akili = mock.patch.object(main, "get_akili_response", return_value="Commençons par l'image 1.")
        self.akili_mock = self.akili.start()

    def tearDown(self):
        self.akili.stop()
        for p in self.patches:
            p.stop()
        main.conversations.clear()

    def historique_envoye(self):
        return " ".join(m["content"] for m in self.akili_mock.call_args.args[3])

    def test_memoire_perimee_remplacee_par_firestore(self):
        with mock.patch.object(main, "charger_historique_conv", return_value=[]):
            main.answer_learning_request(PHONE, dict(PROFIL), "Aide moi avec ces exercices")
        self.assertNotIn("MODE EXAMEN", self.historique_envoye())

    def test_firestore_en_panne_garde_la_memoire(self):
        with mock.patch.object(main, "charger_historique_conv", return_value=None):
            main.answer_learning_request(PHONE, dict(PROFIL), "Aide moi avec ces exercices")
        self.assertIn("MODE EXAMEN", self.historique_envoye())


if __name__ == "__main__":
    unittest.main()
