"""Controle qualite du 7 oct. (15 h 34) : philosophie proposee en 4e, exercice d'une autre matiere annonce
en toutes lettres, demande precise de l'eleve ignoree."""
import unittest
from unittest import mock

import main

PHONE = "22500000098"


class CollegeTests(unittest.TestCase):
    def test_pas_de_philosophie_au_college(self):
        listes = []
        with mock.patch.object(main, "envoyer_choix", side_effect=lambda p, q, options, **k: listes.append(options)):
            main.ask_matiere(PHONE, "4E")
            main.ask_matiere(PHONE, "SECONDE_A")
        college = [libelle for _, libelle, _ in listes[0]]
        self.assertNotIn("Philosophie", college)
        self.assertIn("EDHC", college)
        self.assertIn("Philosophie", [libelle for _, libelle, _ in listes[1]])
        for serie in ("6E", "5E", "4E", "BEPC"):
            self.assertFalse(main.matiere_proposee({"serie": serie}, "PHILO"), serie)

    def test_lettre_et_liste_affichee_concordent(self):
        envoyes = []
        profil = {"type_examen": "CLASSE_INTERMEDIAIRE", "serie": "4E", "onboarding_step": "matiere"}
        with mock.patch.object(main, "send_whatsapp", side_effect=lambda p, m, *a, **k: envoyes.append(m)), \
                mock.patch.object(main, "sauver_etat_whatsapp"), \
                mock.patch.object(main, "repartir_a_zero_apres_menu"), \
                mock.patch.object(main, "mark_onboarding_completed", side_effect=lambda p, prof: prof):
            self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "e"))
        main.user_profiles.pop(PHONE, None)
        self.assertEqual(profil["matiere"], "HG")  # e = Histoire-Géographie dans la liste du college


class ChangementDeMatiereTests(unittest.TestCase):
    def test_exercice_d_une_autre_matiere(self):
        texte = ("Maintenant moi je vais traiter mon exercice de premier histoire géo Ça me fait une courbe "
                 "Donc je veux que tu me montres comment faire la courbe là s'il te plaît")
        self.assertTrue(main.est_demande_changement_matiere(texte, "MATHS"))
        self.assertTrue(main.est_demande_changement_matiere("mon devoir de SVT", "HG"))

    def test_meme_matiere_ou_simple_mention(self):
        for texte in ["je veux faire mon exercice de maths", "Calcule la dérivée, c'est un exercice de maths",
                      "la suite de l'exercice"]:
            self.assertFalse(main.est_demande_changement_matiere(texte, "MATHS"), texte)


class FausseReponse:
    def __init__(self, statut, corps=None):
        self.status_code, self._corps = statut, corps or {}
        self.text = str(self._corps)

    def json(self):
        return self._corps

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class NouvelEssaiApiTests(unittest.TestCase):
    def appeler(self, reponses):
        appels = []

        def post(*a, **k):
            appels.append(1)
            r = reponses[len(appels) - 1]
            if isinstance(r, Exception):
                raise r
            return r
        with mock.patch.object(main.requests, "post", side_effect=post), mock.patch.object(main.time, "sleep"):
            texte = main.get_akili_response("2+2 ?", "MATHS", "BEPC", [], phone=PHONE)
        return texte, len(appels)

    def test_503_puis_reponse(self):
        texte, appels = self.appeler([FausseReponse(503), FausseReponse(200, {"reponse": "Ça fait 4. Et 3+3 ?"})])
        self.assertEqual((texte, appels), ("Ça fait 4. Et 3+3 ?", 2))

    def test_connexion_coupee_puis_reponse(self):
        texte, appels = self.appeler([main.requests.exceptions.ConnectionError("reset"),
                                      FausseReponse(200, {"reponse": "Bien. Et 3+3 ?"})])
        self.assertEqual((texte, appels), ("Bien. Et 3+3 ?", 2))

    def test_delai_depasse_sans_nouvel_essai(self):
        texte, appels = self.appeler([main.requests.exceptions.Timeout("90 s")])
        self.assertEqual(appels, 1)
        self.assertIn("petite difficulté technique", texte)


class ConsignesTests(unittest.TestCase):
    def test_demande_precise_et_une_question(self):
        source = open(main.__file__, encoding="utf-8").read()
        self.assertIn("DEMANDE PRECISE DE L'ELEVE", source)
        self.assertIn("un seul point d'interrogation par message", source)


if __name__ == "__main__":
    unittest.main()
