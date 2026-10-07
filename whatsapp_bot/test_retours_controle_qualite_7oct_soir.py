"""Controle qualite du 7 oct. (soir), d'apres le diagnostic message par message :
- le message prerempli des publicites (« Bonjour Akili META-STUDENT ») relancait toute l'inscription ;
- une liste ouverte (menu, matieres) restait en attente pendant que l'eleve continuait son exercice ;
- le profil se lisait dans la consigne de reponse courte, qui recopie les messages d'Akili
  (« ton professeur d'Espagnol » -> eleve classe ENSEIGNANT ; « BEPC » -> niveau BEPC) ;
- un profil incomplet (« L1 », « CcBonjour Akili ») partait chez Akili ;
- une reponse courte arrivee sur une autre copie Cloud Run perdait son exercice ;
- « j'ai sommeil », « laisse tomber » ne terminaient pas la seance."""
import asyncio
import unittest
from unittest import mock

import main

PHONE = "22500000097"
INSCRIT = {"type_examen": "BAC_GENERAL", "serie": "A2", "matiere": "PHILO", "mode": "etude",
           "profile_ready": True, "profile_locked": True, "matiere_confirmed": True, "onboarding_step": "",
           "onboarding_completed_at": "2026-10-06T15:08:39+00:00"}


class FauxRequete:
    def __init__(self, texte, n):
        self._body = {"entry": [{"changes": [{"value": {"messages": [
            {"from": PHONE, "id": f"wamid.cq7soir.{n}", "type": "text", "text": {"body": texte}}
        ]}}]}]}

    async def json(self):
        return self._body


class WebhookTests(unittest.TestCase):
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

    def test_bonjour_de_la_publicite_garde_le_profil(self):
        self.envoyer("Bonjour Akili META-STUDENT", INSCRIT)
        profil = main.user_profiles[PHONE]
        self.assertEqual((profil["serie"], profil["matiere"], profil.get("onboarding_step")), ("A2", "PHILO", ""))
        self.assertTrue(self.envoyes[0].startswith("Bon retour sur Akili ! Ton profil : BAC Général, Terminale A2"))
        self.assertIn("écris menu", self.envoyes[0])
        self.assertEqual(self.listes, [])  # pas de nouvelle inscription

    def test_bonjour_pendant_l_inscription_reprend_la_question(self):
        self.envoyer("Bonjour Akili", {"type_examen": "BAC_GENERAL", "serie": "TOUTES", "onboarding_step": "serie_general"})
        self.assertEqual(self.envoyes[0], main.MESSAGE_REPRISE_INSCRIPTION)

    def test_menu_ouvert_puis_changement_de_matiere(self):
        self.envoyer("je veux plus faire de philo", dict(INSCRIT, onboarding_step="menu_choice"))
        profil = main.user_profiles[PHONE]
        self.assertEqual((profil["type_examen"], profil["serie"]), ("BAC_GENERAL", "A2"))  # pas de BEPC
        self.assertEqual(self.envoyes[0], "D'accord, on change de matière.")
        self.assertEqual(self.listes, ["Quelle matière veux-tu travailler ?"])
        self.assertEqual(self.akili, [])

    def test_menu_ouvert_puis_exercice(self):
        self.envoyer("L'homme est-il une énigme pour lui-même ? aide moi à faire l'introduction",
                     dict(INSCRIT, onboarding_step="menu_choice"))
        self.assertEqual(len(self.akili), 1)
        profil = self.akili[0][0]
        self.assertEqual((profil["matiere"], profil["onboarding_step"]), ("PHILO", ""))
        self.assertNotIn("forced_onboarding_pending_question", self.etapes)

    def test_liste_des_matieres_ouverte_puis_exercice(self):
        profil = dict(INSCRIT, onboarding_step="matiere")
        profil.pop("profile_locked")
        profil.pop("matiere_confirmed")
        self.envoyer("Analyse ce sujet : la liberté est-elle une illusion ?", profil)
        self.assertEqual(len(self.akili), 1)
        self.assertEqual(self.akili[0][0]["matiere"], "PHILO")
        self.assertEqual(main.user_profiles[PHONE]["onboarding_step"], "")

    def test_lettre_de_la_liste_toujours_un_choix(self):
        self.envoyer("a", dict(INSCRIT, onboarding_step="menu_choice"))
        self.assertEqual(self.listes, ["Quelle matière veux-tu travailler ?"])
        self.assertEqual(self.akili, [])

    def test_licence_a_la_question_du_niveau(self):
        self.envoyer("L1", {"serie": "TOUTES", "matiere": "MATHS", "onboarding_step": "exam"})
        self.assertEqual(self.envoyes[0], main.MESSAGE_HORS_CHAMP)
        self.assertEqual(self.akili, [])
        self.envoyer("J'suis en licence 1", {"type_examen": "BAC_GENERAL", "serie": "TOUTES",
                                             "matiere": "MATHS", "onboarding_step": "serie_general"})
        self.assertEqual(self.envoyes[-1], main.MESSAGE_HORS_CHAMP)
        self.assertNotIn(main.MESSAGE_CHOIX_NON_COMPRIS, self.envoyes)

    def test_message_sans_profil_lance_l_inscription(self):
        self.envoyer("CcBonjour Akili", {"serie": "TOUTES", "matiere": "MATHS"})
        self.assertEqual(self.akili, [])
        self.assertEqual(self.listes, ["Bienvenue sur Akili.\n\nQuel niveau prépares-tu ?"])
        self.assertEqual(main.user_profiles[PHONE]["onboarding_step"], "exam")

    def test_reponse_hors_liste_pendant_l_inscription_n_appelle_pas_akili(self):
        self.envoyer("ok merci", {"type_examen": "BAC_GENERAL", "serie": "TOUTES", "matiere": "MATHS",
                                  "onboarding_step": "serie_general"})
        self.assertEqual(self.akili, [])
        self.assertEqual(self.envoyes[0], main.MESSAGE_CHOIX_NON_COMPRIS)

    def test_philosophie_n_est_pas_une_question_gardee(self):
        self.envoyer("Philosophie", {"serie": "TOUTES", "matiere": "MATHS"})
        profil = main.user_profiles[PHONE]
        self.assertNotIn("pending_question", profil)
        self.assertEqual(self.envoyes[0], "D'accord. Avant de commencer, réponds à cette question :")

    def test_reponse_courte_ne_lit_pas_le_profil_dans_les_messages_d_akili(self):
        cle = "22500000097:BAC_GENERAL:A2:PHILO:etude"
        main.conversations[cle] = [
            {"role": "user", "content": "Philosophie"},
            {"role": "assistant", "content": "Je suis Akili, ton professeur d'Espagnol. Si tu as une question sur la "
                                             "philosophie, demande à un autre professeur. Choisis : a) b) c) d) le BEPC ?"},
        ]
        self.envoyer("D", INSCRIT)
        self.assertEqual(len(self.akili), 1)
        profil, texte = self.akili[0]
        self.assertNotEqual(profil.get("user_type"), "ENSEIGNANT")
        self.assertEqual((profil["type_examen"], profil["matiere"]), ("BAC_GENERAL", "PHILO"))
        self.assertNotIn("teacher_direct_request", self.etapes)
        self.assertIn("L'élève vient de répondre uniquement : D", texte)


class NiveauVerrouilleTests(unittest.TestCase):
    def test_bepc_dans_le_message_ne_change_pas_le_niveau(self):
        appels = []
        profil = {"type_examen": "BAC_GENERAL", "serie": "D", "matiere": "SVT", "mode": "etude",
                  "profile_ready": True, "profile_locked": True, "matiere_confirmed": True}
        with mock.patch.object(main, "p0_enabled", return_value=False), \
                mock.patch.object(main, "send_whatsapp"), \
                mock.patch.object(main, "send_whatsapp_typing_indicator"), \
                mock.patch.object(main, "charger_historique_conv", side_effect=lambda cle: appels.append(cle) or []), \
                mock.patch.object(main, "sauver_historique_conv"), \
                mock.patch.object(main, "sauver_etat_whatsapp"), \
                mock.patch.object(main, "mark_first_learning_request", side_effect=lambda phone, p: p), \
                mock.patch.object(main, "get_akili_response", return_value="D'accord."):
            main.answer_learning_request(PHONE, profil, "Publicité Facebook : préparer le BEPC ou le BAC")
        main.user_profiles.pop(PHONE, None)
        main.conversations.clear()
        self.assertEqual(profil["type_examen"], "BAC_GENERAL")
        self.assertEqual(appels[0], f"{PHONE}:BAC_GENERAL:D:SVT:etude")


class ContexteReponseCourteTests(unittest.TestCase):
    def tearDown(self):
        main.conversations.clear()

    def test_historique_relu_dans_firestore(self):
        main.conversations.clear()
        cle = f"{PHONE}:BAC_GENERAL:D:MATHS:etude"
        sauve = [{"role": "user", "content": "a"},
                 {"role": "assistant", "content": "Oui. Maintenant, applique cette règle au trinôme x²+x+1."}]
        with mock.patch.object(main, "charger_historique_conv", return_value=sauve), \
                mock.patch.object(main, "load_last_assistant_context", return_value=""):
            self.assertTrue(main.short_answer_has_exercise_context(PHONE, cle=cle))
            self.assertIn("applique cette règle", main.build_short_answer_prompt(PHONE, "∆= 3", cle=cle))

    def test_sans_historique_on_demande_l_exercice(self):
        main.conversations.clear()
        with mock.patch.object(main, "charger_historique_conv", return_value=[]), \
                mock.patch.object(main, "load_last_assistant_context", return_value=""):
            self.assertFalse(main.short_answer_has_exercise_context(PHONE, cle=f"{PHONE}:BEPC:BEPC:MATHS:etude"))


class FinDeSeanceTests(unittest.TestCase):
    def test_fatigue(self):
        for texte in ["stp j'ai sommeil 🫩", "laisse tomber", "je suis fatiguée", "J'ai trop sommeil là"]:
            self.assertTrue(main.est_message_au_revoir(texte), texte)
        for texte in ["je ne comprends pas", "la fatigue musculaire en SVT c'est quoi"]:
            self.assertFalse(main.est_message_au_revoir(texte), texte)

    def test_consigne_pas_de_refus_de_matiere(self):
        consigne = main.consigne_matiere_choisie("SVT", "D", "BAC_GENERAL")
        self.assertIn("Ne dis JAMAIS que tu ne peux aider que dans cette matière", consigne)
        self.assertIn("écrire menu", consigne)


if __name__ == "__main__":
    unittest.main()
