"""Apres le menu (« Envoie maintenant ton exercice »), Akili repart d'une page blanche :
l'ancienne question en cours ne revient plus dans l'historique de la meme matiere."""
import unittest
from pathlib import Path
from unittest import mock

import main

PHONE = "22500000081"
CLE = f"{PHONE}:BAC_TECHNIQUE:G2:COMPTA_FIN:etude"


class FauxDoc:
    def __init__(self, db, collection, doc_id):
        self.db, self.collection, self.doc_id = db, collection, doc_id

    def delete(self):
        self.db.supprimes.append((self.collection, self.doc_id))

    def get(self):
        return mock.Mock(exists=False)


class FauxDb:
    def __init__(self):
        self.supprimes = []

    def collection(self, nom):
        db = self

        class Collection:
            def document(self, doc_id):
                return FauxDoc(db, nom, doc_id)
        return Collection()


class NouveauDepartTests(unittest.TestCase):
    def setUp(self):
        self.envoyes = []
        self.db = FauxDb()
        self.patches = [
            mock.patch.object(main, "send_whatsapp", side_effect=lambda phone, msg, *a, **k: self.envoyes.append(msg)),
            mock.patch.object(main, "sauver_etat_whatsapp"),
            mock.patch.object(main, "feedback_db", self.db),
            mock.patch.object(main, "mark_onboarding_completed", side_effect=lambda phone, p: p),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        main.user_profiles.pop(PHONE, None)
        for k in [k for k in main.conversations if k.startswith(PHONE)]:
            main.conversations.pop(k, None)

    def test_menu_efface_question_en_cours(self):
        main.conversations[CLE] = [
            {"role": "user", "content": "Le 5 octobre, achat de marchandises à crédit..."},
            {"role": "assistant", "content": "Quel compte crédites-tu ? (a) 411 Clients (b) 401 Fournisseurs"},
        ]
        main.conversations["22500000099:BEPC:BEPC:MATHS:etude"] = [{"role": "user", "content": "x"}]
        profil = {"type_examen": "BAC_TECHNIQUE", "serie": "G2", "matiere": "COMPTA_FIN", "mode": "etude",
                  "onboarding_completed_at": "2026-10-01T10:00:00+00:00"}
        main.terminer_inscription(PHONE, profil, deja_inscrit=True)
        self.assertTrue(profil["nouveau_depart"])
        self.assertNotIn(CLE, main.conversations)
        self.assertIn("22500000099:BEPC:BEPC:MATHS:etude", main.conversations)  # autres eleves intacts
        self.assertIn(("whatsapp_contexts", PHONE), self.db.supprimes)
        self.assertEqual(main.get_recent_phone_context_text(PHONE), "")
        self.assertIn("Envoie maintenant ton exercice", self.envoyes[-1])
        main.conversations.pop("22500000099:BEPC:BEPC:MATHS:etude", None)

    def test_premiere_demande_apres_menu_repart_a_zero(self):
        source = Path(main.__file__).read_text(encoding="utf-8")
        debut = source.index("def answer_learning_request")
        corps = source[debut:debut + 4000]
        self.assertIn('if profile.pop("nouveau_depart", False):', corps)
        self.assertIn("sauver_historique_conv(conversation_key, [])", corps)
        # la remise a zero vient apres le rechargement Firestore, sinon l'ancien historique reviendrait
        self.assertLess(corps.index("hist_sauve = charger_historique_conv"), corps.index('profile.pop("nouveau_depart"'))


if __name__ == "__main__":
    unittest.main()
