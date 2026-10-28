"""Programme personnalise de revision (« mon programme », 28 oct.) : plan a rebours jusqu'a l'examen."""
import asyncio
import unittest
from datetime import date
from unittest import mock

import main
import programme
import test_choix_non_compris as base

AUJOURD_HUI = date(2026, 10, 28)
PROFIL_D = {"type_examen": "BAC_GENERAL", "serie": "D", "matiere": "MATHS", "matiere_confirmed": True,
            "mode": "etude", "profile_ready": True, "onboarding_step": "",
            "onboarding_completed_at": "2026-10-01T10:00:00+00:00"}


class CalculTests(unittest.TestCase):
    def test_semaines_et_phases(self):
        self.assertEqual(programme.semaines_restantes("BAC_GENERAL", AUJOURD_HUI), 33)
        self.assertEqual(programme.semaines_restantes("BEPC", AUJOURD_HUI), 36)
        self.assertEqual(programme.semaines_restantes("BAC_GENERAL", date(2027, 6, 20)), 0)
        self.assertEqual(programme.phase("BAC_GENERAL", AUJOURD_HUI), "revoir")
        self.assertEqual(programme.phase("BAC_GENERAL", date(2027, 4, 15)), "sujets")
        self.assertEqual(programme.phase("BAC_GENERAL", date(2027, 6, 1)), "finale")

    def test_examen_du_profil(self):
        self.assertEqual(programme.examen_du_profil(PROFIL_D), "BAC_GENERAL")
        self.assertEqual(programme.examen_du_profil({"type_examen": "BEPC"}), "BEPC")
        self.assertEqual(programme.examen_du_profil({"type_examen": "BAC_TECHNIQUE", "classe": "TERMINALE"}),
                         "BAC_TECHNIQUE")
        self.assertIsNone(programme.examen_du_profil({"type_examen": "BAC_TECHNIQUE", "classe": "PREMIERE"}))
        self.assertIsNone(programme.examen_du_profil({"type_examen": "CLASSE_INTERMEDIAIRE", "serie": "4E"}))

    def test_coefficients_de_la_serie(self):
        coefs = {c: k for c, _, k in programme.matieres_du_profil(PROFIL_D)}
        self.assertEqual((coefs["MATHS"], coefs["PC"], coefs["SVT"], coefs["PHILO"], coefs["ANGLAIS"]), (4, 4, 4, 2, 1))
        self.assertNotIn("EDHC", coefs)
        self.assertEqual({c for c, _, _ in programme.matieres_du_profil({"type_examen": "BEPC"})} & {"PHILO", "EDHC"},
                         {"EDHC"})
        technique = programme.matieres_du_profil({"type_examen": "BAC_TECHNIQUE"}, [("ECO", "Économie"), ("DROIT", "Droit")])
        self.assertEqual(technique, [("ECO", "Économie", 1), ("DROIT", "Droit", 1)])

    def test_repartition(self):
        matieres = programme.matieres_du_profil(PROFIL_D)
        seances = programme.repartir(matieres, ["PC"], 7)
        self.assertEqual(sum(seances.values()), 7)
        self.assertEqual(max(seances, key=seances.get), "PC")
        self.assertNotIn("ESPAGNOL", seances)  # facultative, non choisie
        avec_langue = programme.repartir(matieres, ["ESPAGNOL"], 5)
        self.assertGreaterEqual(avec_langue.get("ESPAGNOL", 0), 1)
        self.assertEqual(sum(avec_langue.values()), 5)

    def test_lecture_des_reponses(self):
        matieres = programme.matieres_du_profil(PROFIL_D)
        for texte in ("a c", "a,c", "ac", "A et C", "1 3", "a c c"):
            self.assertEqual(programme.lire_prioritaires(texte, matieres), ["MATHS", "SVT"], texte)
        for texte in ("a b c d", "z", "je sais pas", "", "abcd"):
            self.assertIsNone(programme.lire_prioritaires(texte, matieres), texte)
        self.assertEqual(programme.lire_temps("b"), "60")
        self.assertEqual(programme.lire_temps("4"), "WE")
        self.assertIsNone(programme.lire_temps("beaucoup"))

    def test_texte(self):
        texte = programme.texte_programme(PROFIL_D, {"examen": "BAC_GENERAL", "prioritaires": ["PC"], "temps": "60"},
                                          programme.matieres_du_profil(PROFIL_D), AUJOURD_HUI)
        self.assertIn("Ton programme BAC D", texte)
        self.assertIn("33 semaines", texte)
        self.assertIn("Revoir le programme", texte)
        self.assertIn("Physique-Chimie : ", texte)
        self.assertIn("⭐", texte)
        self.assertIn("on passe en physique-chimie", texte)
        self.assertNotIn("**", texte)
        deja = programme.texte_programme(PROFIL_D, {"examen": "BAC_GENERAL", "prioritaires": ["MATHS"], "temps": "60"},
                                         programme.matieres_du_profil(PROFIL_D), AUJOURD_HUI)
        self.assertIn("Tu es déjà en Mathématiques", deja)


class ConversationTests(unittest.TestCase):
    setUp_base = base.BonjourPendantInscriptionTests.setUp
    tearDown_base = base.BonjourPendantInscriptionTests.tearDown

    def setUp(self):
        self.setUp_base()
        self.etat = dict(PROFIL_D)
        self.listes = []

        def sauver(phone, p):
            self.etat = dict(p)
        self.extra = [mock.patch.object(main, "sauver_etat_whatsapp", side_effect=sauver),
                      mock.patch.object(main, "envoyer_choix",
                                        side_effect=lambda phone, q, o, **k: self.listes.append((q, o)))]
        for p in self.extra:
            p.start()
        main.user_profiles.pop(base.PHONE, None)

    def tearDown(self):
        for p in self.extra:
            p.stop()
        self.tearDown_base()

    def envoyer(self, texte):
        main.processed_messages.clear()
        return asyncio.run(main.receive_message(base.FauxRequete(texte)))

    def test_parcours_complet(self):
        with mock.patch.object(main, "answer_learning_request") as akili:
            self.assertEqual(self.envoyer("Mon programme").get("reason"), "programme_demarre")
            self.assertIn("Quelles matières veux-tu renforcer", self.envoyes[-1])
            self.assertIn("c. SVT (coef. 4)", self.envoyes[-1])
            self.assertEqual(self.envoyer("b c").get("reason"), "programme_prioritaires")
            self.assertEqual(self.listes[-1][0], "Combien de temps peux-tu travailler avec Akili ?")
            self.assertEqual(self.envoyer("b").get("reason"), "programme_cree")
        akili.assert_not_called()
        self.assertEqual(self.etat["programme"]["prioritaires"], ["PC", "SVT"])
        self.assertEqual(self.etat["programme"]["temps"], "60")
        self.assertNotIn("programme_etape", self.etat)
        self.assertIn("Ton programme BAC D", self.envoyes[-1])
        # Plus tard : « mon programme » le reaffiche ; « modifier mon programme » repose les questions.
        self.assertEqual(self.envoyer("mon programme").get("reason"), "programme_affiche")
        self.assertIn("Ton programme BAC D", self.envoyes[-2])
        self.assertEqual(self.envoyer("Modifier mon programme").get("reason"), "programme_demarre")

    def test_la_phrase_conseillee_change_de_matiere(self):
        self.etat["programme"] = {"examen": "BAC_GENERAL", "prioritaires": ["PC"], "temps": "60"}
        self.envoyer("mon programme")
        with mock.patch.object(main, "answer_learning_request", return_value={"status": "ok"}):
            self.envoyer("on passe en physique-chimie")
        self.assertEqual(self.etat.get("matiere"), "PC")

    def test_reponse_non_comprise_puis_vraie_question(self):
        self.envoyer("mon programme")
        self.assertEqual(self.envoyer("je sais pas").get("reason"), "programme_rappel")
        self.assertEqual(self.envoyes[-1], programme.PRIORITES_NON_COMPRISES)
        with mock.patch.object(main, "answer_learning_request", return_value={"status": "ok"}) as akili:
            self.envoyer("Comment calculer la dérivée de x² + 3x ?")
        self.assertNotIn("programme_etape", self.etat)
        akili.assert_called_once()

    def test_fin_annule(self):
        self.envoyer("mon programme")
        self.assertEqual(self.envoyer("fin").get("reason"), "programme_annule")
        self.assertNotIn("programme_etape", self.etat)

    def test_classe_sans_examen(self):
        self.etat = dict(PROFIL_D, type_examen="CLASSE_INTERMEDIAIRE", serie="4E")
        self.assertEqual(self.envoyer("mon programme").get("reason"), "programme_sans_examen")
        self.assertEqual(self.envoyes[-1], programme.PAS_D_EXAMEN)

    def test_option_du_menu(self):
        profil = dict(PROFIL_D, onboarding_step="menu_choice")
        main.user_profiles[base.PHONE] = profil
        self.assertTrue(main.handle_onboarding_choice(base.PHONE, profil, "d"))
        self.assertEqual(main.user_profiles[base.PHONE]["programme_etape"], "prioritaires")


if __name__ == "__main__":
    unittest.main()
