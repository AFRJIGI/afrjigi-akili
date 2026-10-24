"""Controle qualite du 24 oct. :
- « Niveau terminal » envoyait a la matiere sans serie : le profil n'etait jamais pret et
  « Bienvenue sur Akili » revenait a chaque message (note 1/5) ;
- le bilan de pause lisait le profil garde en memoire par la copie Cloud Run de la tache planifiee
  (bilan de Philosophie enregistre en Anglais, mini-test d'une matiere quittee) ;
- le defi du lendemain arrivait alors qu'une question d'Akili attendait encore sa reponse."""
import asyncio
import unittest
from datetime import timedelta
from unittest import mock

import main
import test_choix_non_compris as base
import test_classe_revision as rev

PHONE = base.PHONE


class SerieManquanteTests(unittest.TestCase):
    setUp = base.BonjourPendantInscriptionTests.setUp
    tearDown = base.BonjourPendantInscriptionTests.tearDown

    def envoyer(self, texte):
        main.processed_messages.clear()
        return asyncio.run(main.receive_message(base.FauxRequete(texte)))

    def listes(self):
        questions = []
        return questions, mock.patch.object(
            main, "envoyer_choix", side_effect=lambda phone, q, o, **k: questions.append(q))

    def test_niveau_sans_serie_redemande_le_niveau(self):
        self.etat = {"serie": "TOUTES", "matiere": "MATHS", "onboarding_step": "exam"}
        questions, patch = self.listes()
        with patch:
            self.envoyer("Niveau terminal")
        self.assertEqual(self.etat["onboarding_step"], "exam")
        self.assertEqual(self.envoyes[-1], main.MESSAGE_PRECISER_NIVEAU)
        self.assertEqual(questions, ["Quel niveau prépares-tu ?"])
        self.assertNotIn("Quelle matière", " ".join(questions))

    def test_bepc_sans_serie_va_a_la_matiere(self):
        self.etat = {"serie": "TOUTES", "matiere": "MATHS", "onboarding_step": "exam"}
        with mock.patch.object(main, "ask_matiere") as matiere:
            self.envoyer("Je suis au niveau BEPC")
        self.assertEqual((self.etat.get("type_examen"), self.etat.get("serie")), ("BEPC", "BEPC"))
        matiere.assert_called_once()

    def test_profil_sans_serie_complete_la_serie_au_lieu_de_tout_recommencer(self):
        self.etat = {"type_examen": "BAC_GENERAL", "serie": "TOUTES", "matiere": "ANGLAIS",
                     "matiere_confirmed": True, "mode": "etude", "profile_ready": True, "onboarding_step": "",
                     "onboarding_completed_at": "2026-10-22T05:54:00+00:00"}
        questions, patch = self.listes()
        with patch, mock.patch.object(main, "answer_learning_request") as akili:
            resultat = self.envoyer("Freedom and civil rights")
            self.assertEqual(resultat.get("reason"), "serie_manquante")
            self.assertEqual(self.envoyes[-1], main.MESSAGE_SERIE_MANQUANTE)
            self.assertNotIn("Bienvenue", " ".join(questions + self.envoyes))
            self.assertEqual(self.etat["onboarding_step"], "serie_general")
            self.envoyer("d")
        self.assertEqual((self.etat["serie"], self.etat["matiere"]), ("D", "ANGLAIS"))
        self.assertTrue(main.is_profile_ready(self.etat))
        self.assertTrue(self.envoyes[-1].startswith("C'est noté : "))
        self.assertNotIn("Quelle matière", " ".join(questions))
        akili.assert_not_called()

    def test_matiere_choisie_sans_serie_demande_la_serie(self):
        profil = {"type_examen": "BAC_GENERAL", "serie": "TOUTES", "onboarding_step": "matiere"}
        with mock.patch.object(main, "ask_serie_general") as serie:
            self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "i"))
        serie.assert_called_once()
        self.assertEqual((profil["matiere"], profil["onboarding_step"]), ("ANGLAIS", "serie_general"))
        self.assertFalse(main.is_profile_ready(profil))
        with mock.patch.object(main, "ask_matiere") as matiere, \
                mock.patch.object(main, "answer_learning_request"):
            self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "b"))
        matiere.assert_not_called()
        profil = main.user_profiles[PHONE]
        self.assertEqual((profil["serie"], profil["matiere"]), ("A2", "ANGLAIS"))
        self.assertTrue(main.is_profile_ready(main.mark_profile_ready_if_complete(profil)))

    def test_serie_choisie_normalement_affiche_toujours_les_matieres(self):
        profil = {"type_examen": "BAC_GENERAL", "serie": "TOUTES", "onboarding_step": "serie_general"}
        with mock.patch.object(main, "ask_matiere") as matiere:
            self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "d"))
        matiere.assert_called_once()
        self.assertEqual(main.user_profiles[PHONE]["onboarding_step"], "matiere")


class BilanAvecLeProfilActuelTests(unittest.TestCase):
    def test_bilan_lit_l_etat_firestore_avant_la_memoire(self):
        actuel = dict(rev.PROFIL, matiere="PHILO")
        main.user_profiles[PHONE] = dict(rev.PROFIL, matiere="ANGLAIS")  # copie memoire d'il y a 3 h
        vus = []
        try:
            with mock.patch.object(main, "reserver_bilan", return_value=rev.session()), \
                    mock.patch.object(main, "charger_etat_whatsapp", return_value=dict(actuel)), \
                    mock.patch.object(main, "generer_bilan_session", return_value="Bilan"), \
                    mock.patch.object(main, "send_whatsapp", side_effect=lambda *a, **k: vus.append(
                        main.user_profiles[PHONE]["matiere"])), \
                    mock.patch.object(main, "noter_session_bilan"), \
                    mock.patch.object(main, "planifier_revision"), \
                    mock.patch.object(main, "maybe_send_marketing_consent_prompt", return_value=False), \
                    mock.patch.object(main, "proposer_mini_test_fin_de_seance", return_value=True) as test:
                self.assertTrue(main.envoyer_fin_de_session(PHONE, source="inactivite"))
            self.assertEqual(vus, ["PHILO"])
            self.assertEqual(test.call_args[0][1]["matiere"], "PHILO")
        finally:
            main.user_profiles.pop(PHONE, None)


class QuestionSansReponseLeLendemainTests(rev.RevisionTests):
    def test_reprend_la_question_au_lieu_du_defi(self):
        self.seance_en_cours = {
            "conversation_key": rev.CLE,
            "derniere_activite": (rev.NOW - timedelta(hours=18, minutes=30)).isoformat(),
            "messages": [{"role": "user", "content": "a"},
                         {"role": "assistant", "content": "C'est exact !\n\nPour le terme en x² : a - 2 = -4\n"
                                                          "Combien trouves-tu pour a?"}]}
        with mock.patch.object(main, "generer_revision") as defi:
            self.assertEqual(main.traiter_revisions_lendemain(now=rev.NOW), {"revisions": 1})
        defi.assert_not_called()
        self.assertTrue(self.envoyes[-1].startswith("Bonjour ! Hier, on s'est arrêté sur cette question"))
        self.assertIn("Combien trouves-tu pour a?", self.envoyes[-1])
        self.assertIn({"statut": "reprise_envoyee"}, self.notes)

    def test_eleve_qui_a_repondu_recoit_le_defi(self):
        self.seance_en_cours = {
            "conversation_key": rev.CLE,
            "derniere_activite": (rev.NOW - timedelta(hours=18, minutes=30)).isoformat(),
            "messages": [{"role": "assistant", "content": "Combien trouves-tu pour a?"},
                         {"role": "user", "content": "a = -2, merci, à demain"}]}
        self.assertEqual(main.traiter_revisions_lendemain(now=rev.NOW), {"revisions": 1})
        self.assertIn("Petit défi", self.envoyes[-1])


if __name__ == "__main__":
    unittest.main()
