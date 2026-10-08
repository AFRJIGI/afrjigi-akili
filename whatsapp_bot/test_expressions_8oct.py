"""Rapport des expressions d'eleves du 8 oct. : salutations SMS ou ivoiriennes (« Cc », « On dit quoi »),
lettres de choix dans une phrase (« D'accord a », « A et b »), « Comptabilité » quand la serie en a plusieurs,
« Bac général » tape a la question de la serie, changement de niveau d'un eleve deja inscrit."""
import asyncio
import unittest
from unittest import mock

import main

PHONE = "22500000103"
INSCRIT = {"type_examen": "BAC_GENERAL", "serie": "D", "matiere": "MATHS", "mode": "etude",
           "profile_ready": True, "profile_locked": True, "matiere_confirmed": True, "onboarding_step": "",
           "onboarding_completed_at": "2026-10-06T15:08:39+00:00", "first_learning_request_at": "x"}
NOUVEAU = {"serie": "TOUTES", "matiere": "MATHS"}


class FauxRequete:
    def __init__(self, texte, n):
        self._body = {"entry": [{"changes": [{"value": {"messages": [
            {"from": PHONE, "id": f"wamid.expr8.{n}", "type": "text", "text": {"body": texte}}
        ]}}]}]}

    async def json(self):
        return self._body


class FonctionsTests(unittest.TestCase):
    def test_salutations(self):
        for texte in ["Cc", "slt akili", "On dit quoi", "C'est comment mon ami", "Bsr", "Coucou prof"]:
            self.assertTrue(main.est_salutation(texte), texte)
        for texte in ["C'est comment la BEPC", "Cc je veux un exercice", "ça va", "a", "Bonjour j'ai un devoir"]:
            self.assertFalse(main.est_salutation(texte), texte)

    def test_choix_dans_une_phrase(self):
        attendus = {"D'accord a": ["a"], "Non a d'abord": ["a"], "A.b": ["a", "b"], "a,b pour l'instant": ["a", "b"],
                    "Ok je choisis a été b": ["a", "b"], "e second c": ["e", "c"], "A et C": ["a", "c"]}
        for texte, lettres in attendus.items():
            self.assertEqual(main.extraire_choix(texte), lettres, texte)
        for texte in ["Je est fort en a,b, d", "Calcule a et b", "mode eleve", ""]:
            self.assertIsNone(main.extraire_choix(texte), texte)


class ExpressionsWebhookTests(unittest.TestCase):
    def setUp(self):
        self.envoyes, self.listes, self.akili, self.etapes = [], [], [], []
        self.etat = {}
        noop = lambda *a, **k: None
        self.patches = [
            mock.patch.object(main, "send_whatsapp", side_effect=lambda phone, msg, *a, **k: self.envoyes.append(msg)),
            mock.patch.object(main, "envoyer_choix", side_effect=lambda phone, q, options, **k: self.listes.append(q)),
            mock.patch.object(main, "send_whatsapp_typing_indicator", side_effect=noop),
            mock.patch.object(main, "reserver_message_whatsapp", return_value=True),
            mock.patch.object(main, "charger_etat_whatsapp", side_effect=lambda phone: dict(self.etat)),
            mock.patch.object(main, "sauver_etat_whatsapp", side_effect=lambda phone, p: self.etat.update(p)),
            mock.patch.object(main, "save_whatsapp_event",
                              side_effect=lambda *a, **k: self.etapes.append((k.get("extra") or {}).get("processing_stage"))),
            mock.patch.object(main, "maybe_send_marketing_consent_prompt", side_effect=noop),
            mock.patch.object(main, "charger_historique_conv", return_value=[]),
            mock.patch.object(main, "load_last_assistant_context", return_value=""),
            mock.patch.object(main, "mark_onboarding_completed",
                              side_effect=lambda p, prof: dict(prof, profile_ready=True, onboarding_step="")),
            mock.patch.object(main, "answer_learning_request",
                              side_effect=lambda phone, profile, text, **k: self.akili.append((dict(profile), text))),
        ]
        for p in self.patches:
            p.start()
        main.processed_messages.clear()
        main.conversations.clear()
        self.n = 0

    def tearDown(self):
        for p in self.patches:
            p.stop()
        main.user_profiles.pop(PHONE, None)
        main.processed_messages.clear()
        main.conversations.clear()

    def envoyer(self, texte, profil=None):
        if profil is not None:
            self.etat = dict(profil)
            main.user_profiles[PHONE] = dict(profil)
        self.n += 1
        return asyncio.run(main.receive_message(FauxRequete(texte, self.n)))

    def test_cc_eleve_inscrit(self):
        self.envoyer("Cc", INSCRIT)
        self.assertTrue(self.envoyes[0].startswith("Bon retour sur Akili !"))
        self.assertEqual(self.akili, [])

    def test_on_dit_quoi_pendant_l_inscription(self):
        self.envoyer("On dit quoi", dict(NOUVEAU, onboarding_step="exam"))
        self.assertEqual(self.envoyes[0], main.MESSAGE_REPRISE_INSCRIPTION)
        self.assertEqual(self.listes, ["Bienvenue sur Akili.\n\nQuel niveau prépares-tu ?"])

    def test_d_accord_a_a_la_question_du_niveau(self):
        self.envoyer("D'accord a", dict(NOUVEAU, onboarding_step="exam"))
        profil = main.user_profiles[PHONE]
        self.assertEqual(profil["type_examen"], "BEPC")
        self.assertNotIn("multiple_choice_rejected", self.etapes)

    def test_deux_lettres_au_niveau_reposent_la_liste(self):
        self.envoyer("a et b", dict(NOUVEAU, onboarding_step="exam"))
        self.assertEqual(self.envoyes[0], "Choisis une seule option pour continuer. Exemple : a")
        self.assertEqual(len(self.listes), 1)

    def test_deux_matieres_on_commence_par_la_premiere(self):
        self.envoyer("A et b", dict(NOUVEAU, type_examen="BAC_GENERAL", serie="D", onboarding_step="matiere"))
        self.assertEqual(self.envoyes[0], main.MESSAGE_PREMIERE_MATIERE)
        profil = main.user_profiles[PHONE]
        self.assertEqual((profil["matiere"], profil.get("onboarding_step")), ("MATHS", ""))

    def test_comptabilite_en_g2(self):
        self.envoyer("Comptabilité", dict(NOUVEAU, type_examen="BAC_TECHNIQUE", serie="G2", classe="TERMINALE",
                                          onboarding_step="matiere"))
        self.assertEqual(self.envoyes[0], "Il y a 3 comptabilités dans ta série. Choisis laquelle dans la liste :")
        self.assertIn("Comptabilité analytique", self.envoyes[1])  # G2 : 12 matieres, liste en lettres
        self.assertEqual(main.user_profiles[PHONE]["onboarding_step"], "matiere")

    def test_bac_general_a_la_question_de_la_serie(self):
        self.envoyer("Bac général", dict(NOUVEAU, type_examen="BAC_GENERAL", onboarding_step="serie_general"))
        self.assertEqual(self.envoyes[0], "C'est noté : BAC Général. Choisis maintenant ta série :")
        self.assertEqual(self.listes, ["Quelle série du BAC Général ?"])

    def test_changer_de_niveau_eleve_inscrit(self):
        self.envoyer("b", dict(INSCRIT, onboarding_step="menu_choice"))
        self.assertEqual(self.listes, ["D'accord, changeons ton niveau.\n\nQuel niveau prépares-tu ?"])


if __name__ == "__main__":
    unittest.main()
