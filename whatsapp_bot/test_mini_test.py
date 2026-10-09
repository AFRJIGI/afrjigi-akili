"""Mini-test de progression : propose a la fin d'une seance d'au moins 4 echanges, 3 questions a choix,
resultat enregistre sans le numero ; test de fin apres 3 jours d'activite dans la matiere. Depuis le 9 oct.,
l'etat du test est garde hors du profil et chaque bouton porte le numero de sa question."""
import asyncio
import copy
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
    def test_proposition_apres_au_moins_4_echanges(self):
        self.assertIsNone(mini_test.phase_a_proposer(dict(INSCRIT), 3, MAINTENANT))
        self.assertEqual(mini_test.phase_a_proposer(dict(INSCRIT), 4, MAINTENANT), "debut")
        self.assertEqual(mini_test.phase_a_proposer(dict(INSCRIT), 12, MAINTENANT), "debut")

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
        for entree, lettre in {"b": "b", "B": "b", "b.": "b", "minitest_c": "c", "minitest_q2_b": "b",
                               "d": None, "oui": None}.items():
            self.assertEqual(mini_test.lettre_de(entree), lettre, entree)
        self.assertEqual(mini_test.lire_reponse("minitest_q3_a"), (3, "a"))
        self.assertEqual(mini_test.lire_reponse("c"), (None, "c"))
        self.assertEqual(mini_test.boutons_reponse(1), [("minitest_q2_a", "a"), ("minitest_q2_b", "b"),
                                                        ("minitest_q2_c", "c")])

    def test_fin_sans_question_a_reprendre(self):
        profil = dict(INSCRIT)
        mini_test.proposer(profil, "debut", MAINTENANT)
        mini_test.demarrer(profil, mini_test.questions_valides(QUESTIONS))
        for lettre in ("a", "b", "c"):
            mini_test.enregistrer_reponse(profil["mini_test"], lettre)
        message, _ = mini_test.terminer(profil, MAINTENANT)
        self.assertTrue(message.endswith("Bon travail ! Envoie ton exercice ou ta question quand tu veux."))


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
        self.envoyes, self.boutons, self.akili, self.resultats, self.evenements = [], [], [], [], []
        self.etat = {}       # profil (whatsapp_state)
        self.etat_test = {}  # mini_tests_etat
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
            mock.patch.object(main, "charger_etat_mini_test",
                              side_effect=lambda phone, profile=None: copy.deepcopy(self.etat_test)),
            mock.patch.object(main, "sauver_etat_mini_test",
                              side_effect=lambda phone, e: setattr(self, "etat_test", copy.deepcopy(
                                  {k: v for k, v in e.items() if k in ("mini_test", "mini_tests")}))),
            mock.patch.object(main, "save_whatsapp_event",
                              side_effect=lambda phone, sens, texte, *a, **k: self.evenements.append((sens, texte))),
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
        self.assertTrue(main.proposer_mini_test_fin_de_seance(PHONE, profil, {"nb_echanges": 5, "matiere": "MATHS"}))
        self.assertEqual(self.boutons[-1], (mini_test.PROPOSITION_DEBUT, mini_test.BOUTONS_PROPOSITION))
        self.assertNotIn("mini_test", self.etat)  # rien dans le profil

    def test_pas_de_proposition_apres_une_seance_courte(self):
        profil = dict(INSCRIT)
        self.assertFalse(main.proposer_mini_test_fin_de_seance(PHONE, profil, {"nb_echanges": 3, "matiere": "MATHS"}))
        self.assertEqual(self.boutons, [])

    def test_test_complet_avec_les_boutons(self):
        self.proposer()
        self.envoyer(bouton=mini_test.OUI)
        self.assertEqual(self.envoyes, [mini_test.PREPARATION])
        self.assertTrue(self.boutons[-1][0].startswith("*Dérivées*\n\nQuestion 1/3 : Dérivée de x²"))
        self.assertEqual(self.boutons[-1][1], mini_test.boutons_reponse(0))
        self.envoyer(bouton="minitest_q1_a")
        self.envoyer(bouton="minitest_q2_b")
        self.assertTrue(self.boutons[-1][0].startswith("Question 3/3"))
        self.envoyer(texte="b")  # lettre tapee au lieu du bouton
        self.assertTrue(self.envoyes[-1].startswith("Merci ! Tu as 2/3."))
        self.assertTrue(self.envoyes[-1].endswith("Bon travail ! Envoie ton exercice ou ta question quand tu veux."))
        self.assertEqual(len(self.resultats), 1)
        resultat = self.resultats[0]
        self.assertEqual((resultat["score"], resultat["phase"], resultat["matiere"]), (2, "debut", "MATHS"))
        self.assertNotIn(PHONE, str(resultat))  # identifiant pseudonyme seulement
        self.assertEqual(self.akili, [])
        self.assertEqual(self.etat_test["mini_tests"]["MATHS"]["chapitre"], "Dérivées")
        self.assertNotIn("mini_test", self.etat_test)
        self.assertIn(("inbound", "[mini_test] minitest_q1_a"), self.evenements)  # reponse visible au controle

    def test_double_appui_sur_un_ancien_bouton_ignore(self):
        self.proposer()
        self.envoyer(bouton=mini_test.OUI)
        self.envoyer(bouton="minitest_q1_a")
        self.envoyer(bouton="minitest_q1_a")  # deuxieme appui sur la question 1
        self.envoyer(bouton="minitest_q1_c")
        self.assertEqual(self.etat_test["mini_test"]["index"], 1)
        self.assertEqual(self.etat_test["mini_test"]["reponses"], ["a"])
        self.assertFalse(any(m.startswith("Merci ! Tu as") for m in self.envoyes))

    def test_un_message_traite_en_parallele_n_efface_plus_le_test(self):
        self.proposer()
        self.envoyer(bouton=mini_test.OUI)
        # Un message envoye juste avant se termine apres le « Oui » et remet l'ancien profil.
        self.etat = dict(INSCRIT)
        self.envoyer(texte="A")
        self.assertEqual(self.akili, [])
        self.assertEqual(self.etat_test["mini_test"]["reponses"], ["a"])

    def test_oui_tape(self):
        self.proposer()
        self.envoyer(texte="Oui")
        self.assertEqual(self.envoyes, [mini_test.PREPARATION])
        self.assertEqual(self.etat_test["mini_test"]["etat"], "en_cours")

    def test_deuxieme_oui_pendant_le_test(self):
        self.proposer()
        self.envoyer(bouton=mini_test.OUI)
        self.envoyer(bouton=mini_test.OUI)
        self.assertEqual(self.envoyes, [mini_test.PREPARATION])
        self.assertEqual(self.etat_test["mini_test"]["index"], 0)

    def test_plus_tard(self):
        self.proposer()
        self.envoyer(bouton=mini_test.PLUS_TARD)
        self.assertEqual(self.envoyes, [mini_test.PLUS_TARD_OK])
        self.assertNotIn("mini_test", self.etat_test)

    def test_l_eleve_passe_a_autre_chose(self):
        self.proposer()
        self.envoyer(bouton=mini_test.OUI)
        self.envoyer(texte="Calcule la dérivée de f(x) = 3x² + 2x")
        self.assertEqual(self.envoyes[-1], mini_test.INTERROMPU)
        self.assertEqual(len(self.akili), 1)  # la question part chez Akili comme d'habitude
        self.assertNotIn("mini_test", self.etat_test)

    def test_proposition_ignoree(self):
        self.proposer()
        self.envoyer(texte="Explique-moi la limite en l'infini")
        self.assertEqual(len(self.akili), 1)
        self.assertNotIn(mini_test.INTERROMPU, self.envoyes)
        self.assertNotIn("mini_test", self.etat_test)

    def test_pas_pour_les_enseignants(self):
        profil = dict(INSCRIT, user_type="ENSEIGNANT")
        self.assertFalse(main.proposer_mini_test_fin_de_seance(PHONE, profil, {"nb_echanges": 6}))
        self.assertEqual(self.boutons, [])

    def test_jours_actifs_notes_une_fois_par_jour(self):
        self.etat_test = {"mini_tests": {"MATHS": {"debut_le": "2026-01-01", "chapitre": "X", "jours": []}}}
        main._jour_actif_note.pop(PHONE, None)
        main.mini_test_jour_actif(PHONE, dict(INSCRIT))
        self.assertEqual(len(self.etat_test["mini_tests"]["MATHS"]["jours"]), 1)
        with mock.patch.object(main, "charger_etat_mini_test", side_effect=AssertionError("deja lu aujourd'hui")):
            main.mini_test_jour_actif(PHONE, dict(INSCRIT))


class EtatAPartTests(unittest.TestCase):
    def test_reprise_de_l_ancien_etat_du_profil(self):
        base = mock.MagicMock()
        base.collection.return_value.document.return_value.get.return_value.exists = False
        profil = dict(INSCRIT, mini_test={"etat": "en_cours", "index": 1}, mini_tests={"MATHS": {"chapitre": "X"}})
        with mock.patch.object(main, "feedback_db", base):
            etat = main.charger_etat_mini_test(PHONE, profil)
        self.assertEqual(etat, {"mini_test": {"etat": "en_cours", "index": 1}, "mini_tests": {"MATHS": {"chapitre": "X"}}})
        base.collection.assert_called_with(mini_test.COLLECTION_ETAT)
        self.assertNotIn(PHONE, str(base.collection.return_value.document.call_args))  # identifiant pseudonyme

    def test_firestore_injoignable(self):
        base = mock.MagicMock()
        base.collection.side_effect = RuntimeError("panne")
        with mock.patch.object(main, "feedback_db", base):
            self.assertIsNone(main.charger_etat_mini_test(PHONE, dict(INSCRIT)))


if __name__ == "__main__":
    unittest.main()
