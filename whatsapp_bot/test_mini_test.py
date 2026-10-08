"""Mini-test de progression : proposition apres la 4e reponse d'Akili, 3 questions a choix, resultat
enregistre sans le numero ; test de fin apres 3 jours d'activite dans la matiere."""
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import main
import mini_test

PHONE = "22500000104"
INSCRIT = {"type_examen": "BAC_GENERAL", "serie": "D", "matiere": "MATHS", "mode": "etude",
           "profile_ready": True, "profile_locked": True, "matiere_confirmed": True, "onboarding_step": "",
           "onboarding_completed_at": "2026-10-06T15:08:39+00:00", "first_learning_request_at": "x"}
QUESTIONS = {"chapitre": "Dérivées", "questions": [
    {"question": "Dérivée de x^2 ?", "a": "2x", "b": "x", "c": "2", "bonne": "a", "explication": "On abaisse l'exposant."},
    {"question": "Dérivée de 3x ?", "a": "x", "b": "3", "c": "0", "bonne": "b", "explication": ""},
    {"question": "Dérivée de 5 ?", "a": "5", "b": "1", "c": "0", "bonne": "c", "explication": "Une constante."},
]}
MAINTENANT = datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc)


class LogiqueTests(unittest.TestCase):
    def test_proposition_a_la_4e_reponse_seulement(self):
        self.assertIsNone(mini_test.phase_a_proposer(dict(INSCRIT), 3, MAINTENANT))
        self.assertEqual(mini_test.phase_a_proposer(dict(INSCRIT), 4, MAINTENANT), "debut")
        self.assertIsNone(mini_test.phase_a_proposer(dict(INSCRIT), 5, MAINTENANT))

    def test_pas_deux_propositions_en_deux_jours_et_trois_au_plus(self):
        profil = dict(INSCRIT)
        mini_test.proposer(profil, "debut", MAINTENANT)
        profil.pop("mini_test")  # « plus tard »
        self.assertIsNone(mini_test.phase_a_proposer(profil, 4, MAINTENANT + timedelta(days=1)))
        self.assertEqual(mini_test.phase_a_proposer(profil, 4, MAINTENANT + timedelta(days=2)), "debut")
        profil["mini_tests"]["MATHS"]["propositions_debut"] = 3
        self.assertIsNone(mini_test.phase_a_proposer(profil, 4, MAINTENANT + timedelta(days=5)))

    def test_cycle_complet(self):
        profil = dict(INSCRIT)
        mini_test.proposer(profil, "debut", MAINTENANT)
        mini_test.demarrer(profil, mini_test.questions_valides(QUESTIONS))
        for lettre in ("a", "a", "c"):
            fini = mini_test.enregistrer_reponse(profil["mini_test"], lettre)
        self.assertTrue(fini)
        message, resultat = mini_test.terminer(profil, MAINTENANT)
        self.assertTrue(message.startswith("Merci ! Tu as 2/3."))
        self.assertIn("Question 2 : la bonne réponse était b (3).", message)
        self.assertEqual((resultat["phase"], resultat["score"], resultat["chapitre"]), ("debut", 2, "Dérivées"))
        # 3 jours d'activite apres le test de debut -> test de fin
        for jours in (0, 1, 2, 3):
            mini_test.noter_jour_actif(profil, "MATHS", MAINTENANT + timedelta(days=jours))
        self.assertEqual(profil["mini_tests"]["MATHS"]["jours"], ["2026-10-10", "2026-10-11", "2026-10-12"])
        self.assertEqual(mini_test.phase_a_proposer(profil, 4, MAINTENANT + timedelta(days=3)), "fin")
        texte = mini_test.proposer(profil, "fin", MAINTENANT + timedelta(days=3))
        self.assertIn("« Dérivées »", texte)
        mini_test.demarrer(profil, mini_test.questions_valides(QUESTIONS))
        for lettre in ("a", "b", "c"):
            mini_test.enregistrer_reponse(profil["mini_test"], lettre)
        message, resultat = mini_test.terminer(profil, MAINTENANT + timedelta(days=3))
        self.assertTrue(message.startswith("Tu as 3/3 (au début : 2/3). Bravo, tu as progressé !"))
        self.assertEqual((resultat["phase"], resultat["score_debut"]), ("fin", 2))
        self.assertIsNone(mini_test.phase_a_proposer(profil, 4, MAINTENANT + timedelta(days=10)))  # 14 jours

    def test_question_d_akili_reposee_apres_le_test(self):
        texte = ("Oui, c'est exact ! La dérivée de f(x) = 3x est 3.\n\n"
                 "Maintenant, peux-tu me dire quelle est la dérivée de f(x) = x² + 3x + 5 ?")
        reprise = mini_test.derniere_question(texte)
        self.assertEqual(reprise, "Maintenant, peux-tu me dire quelle est la dérivée de f(x) = x² + 3x + 5 ?")
        self.assertEqual(mini_test.derniere_question("Bravo, tu as fini."), "")
        profil = dict(INSCRIT)
        mini_test.proposer(profil, "debut", MAINTENANT, reprise=reprise)
        mini_test.demarrer(profil, mini_test.questions_valides(QUESTIONS))
        for lettre in ("a", "b", "c"):
            mini_test.enregistrer_reponse(profil["mini_test"], lettre)
        message, _ = mini_test.terminer(profil, MAINTENANT)
        self.assertTrue(message.endswith("On reprend ton travail. " + reprise))
        self.assertIn("Je te reposerai 3 questions dans quelques jours", message)

    def test_reponse_de_l_api_controlee(self):
        self.assertIsNotNone(mini_test.questions_valides(QUESTIONS))
        mauvaise = {"chapitre": "X", "questions": QUESTIONS["questions"][:2]}
        self.assertIsNone(mini_test.questions_valides(mauvaise))
        sans_bonne = {"chapitre": "X", "questions": [dict(q, bonne="d") for q in QUESTIONS["questions"]]}
        self.assertIsNone(mini_test.questions_valides(sans_bonne))

    def test_lettres(self):
        for entree, lettre in {"b": "b", "B": "b", "b.": "b", "minitest_c": "c", "d": None, "oui": None}.items():
            self.assertEqual(mini_test.lettre_de(entree), lettre, entree)


class FauxRequete:
    def __init__(self, n, texte=None, bouton=None):
        message = {"from": PHONE, "id": f"wamid.minitest.{n}"}
        if bouton:
            message.update({"type": "interactive", "interactive": {"type": "button_reply",
                                                                   "button_reply": {"id": bouton, "title": "x"}}})
        else:
            message.update({"type": "text", "text": {"body": texte}})
        self._body = {"entry": [{"changes": [{"value": {"messages": [message]}}]}]}

    async def json(self):
        return self._body


class WebhookTests(unittest.TestCase):
    def setUp(self):
        self.envoyes, self.boutons, self.akili, self.resultats = [], [], [], []
        self.etat = {}
        noop = lambda *a, **k: None
        base = mock.MagicMock()
        base.collection.return_value.add.side_effect = lambda doc: self.resultats.append(doc)
        self.patches = [
            mock.patch.object(main, "send_whatsapp", side_effect=lambda phone, msg, *a, **k: self.envoyes.append(msg)),
            mock.patch.object(main, "send_whatsapp_boutons",
                              side_effect=lambda phone, corps, boutons: self.boutons.append((corps, boutons)) or True),
            mock.patch.object(main, "send_whatsapp_typing_indicator", side_effect=noop),
            mock.patch.object(main, "reserver_message_whatsapp", return_value=True),
            mock.patch.object(main, "charger_etat_whatsapp", side_effect=lambda phone: dict(self.etat)),
            mock.patch.object(main, "sauver_etat_whatsapp",  # comme Firestore : l'etat est remplace en entier
                              side_effect=lambda phone, p: self.etat.clear() or self.etat.update(p)),
            mock.patch.object(main, "save_whatsapp_event", side_effect=noop),
            mock.patch.object(main, "maybe_send_marketing_consent_prompt", side_effect=noop),
            mock.patch.object(main, "charger_historique_conv", return_value=[]),
            mock.patch.object(main, "load_last_assistant_context", return_value=""),
            mock.patch.object(main, "generer_mini_test", return_value=mini_test.questions_valides(QUESTIONS)),
            mock.patch.object(main, "feedback_db", base),
            mock.patch.object(main, "answer_learning_request",
                              side_effect=lambda phone, profile, text, **k: self.akili.append(text)),
        ]
        for p in self.patches:
            p.start()
        main.processed_messages.clear()
        self.n = 0

    def tearDown(self):
        for p in self.patches:
            p.stop()
        main.user_profiles.pop(PHONE, None)
        main.processed_messages.clear()

    def envoyer(self, texte=None, bouton=None):
        self.n += 1
        return asyncio.run(main.receive_message(FauxRequete(self.n, texte, bouton)))

    def proposer(self):
        profil = dict(INSCRIT)
        self.etat = dict(profil)
        main.user_profiles[PHONE] = profil
        main.mini_test_apres_reponse(PHONE, profil, {"nb_echanges": 4})
        self.assertEqual(self.boutons[-1], (mini_test.PROPOSITION_DEBUT, mini_test.BOUTONS_PROPOSITION))

    def test_test_complet_avec_les_boutons(self):
        self.proposer()
        self.envoyer(bouton=mini_test.OUI)
        self.assertEqual(self.envoyes, [mini_test.PREPARATION])
        self.assertTrue(self.boutons[-1][0].startswith("*Dérivées*\n\nQuestion 1/3 : Dérivée de x²"))
        for lettre in ("a", "b"):
            self.envoyer(bouton=f"minitest_{lettre}")
        self.assertTrue(self.boutons[-1][0].startswith("Question 3/3"))
        self.envoyer(texte="b")  # lettre tapee au lieu du bouton
        self.assertTrue(self.envoyes[-1].startswith("Merci ! Tu as 2/3."))
        self.assertEqual(len(self.resultats), 1)
        resultat = self.resultats[0]
        self.assertEqual((resultat["score"], resultat["phase"], resultat["matiere"]), (2, "debut", "MATHS"))
        self.assertNotIn(PHONE, str(resultat))  # identifiant pseudonyme seulement
        self.assertEqual(self.akili, [])
        self.assertEqual(self.etat["mini_tests"]["MATHS"]["chapitre"], "Dérivées")
        self.assertNotIn("mini_test", main.user_profiles[PHONE])

    def test_oui_tape(self):
        self.proposer()
        self.envoyer(texte="Oui")
        self.assertEqual(self.envoyes, [mini_test.PREPARATION])
        self.assertEqual(main.user_profiles[PHONE]["mini_test"]["etat"], "en_cours")

    def test_plus_tard(self):
        self.proposer()
        self.envoyer(bouton=mini_test.PLUS_TARD)
        self.assertEqual(self.envoyes, [mini_test.PLUS_TARD_OK])
        self.assertNotIn("mini_test", self.etat)

    def test_l_eleve_passe_a_autre_chose(self):
        self.proposer()
        self.envoyer(bouton=mini_test.OUI)
        self.envoyer(texte="Calcule la dérivée de f(x) = 3x² + 2x")
        self.assertEqual(self.envoyes[-1], mini_test.INTERROMPU)
        self.assertEqual(len(self.akili), 1)  # la question part chez Akili comme d'habitude
        self.assertNotIn("mini_test", main.user_profiles[PHONE])

    def test_proposition_ignoree(self):
        self.proposer()
        self.envoyer(texte="Explique-moi la limite en l'infini")
        self.assertEqual(len(self.akili), 1)
        self.assertNotIn(mini_test.INTERROMPU, self.envoyes)

    def test_pas_pour_les_enseignants(self):
        profil = dict(INSCRIT, user_type="ENSEIGNANT")
        main.mini_test_apres_reponse(PHONE, profil, {"nb_echanges": 4})
        self.assertEqual(self.boutons, [])


if __name__ == "__main__":
    unittest.main()
