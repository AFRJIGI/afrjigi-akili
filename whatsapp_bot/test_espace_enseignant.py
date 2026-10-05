"""Espace enseignant : code d'acces, menu, mode eleve / preparation, signalements."""
import unittest
from unittest import mock

import espace_enseignant as prof
import main
from test_qualite_corrections import PHONE, Base, texte

CODE = "PROF-SIDIBE-4821"
DOC_CODE = {"code": CODE, "nom": "M. Sidibé", "matieres": ["MECANIQUE_APPLIQUEE", "CMI"],
            "classes": ["2nde F2", "1ère F2", "Tle F2"], "actif": True, "phone": ""}


class FauxFirestore:
    """Juste ce que l'espace enseignant lit et ecrit."""
    def __init__(self, codes):
        self.codes, self.ajouts, self.maj = codes, [], []

    def collection(self, nom):
        base = self

        class Doc:
            def __init__(self, doc_id):
                self.doc_id = doc_id

            def get(self):
                data = base.codes.get(self.doc_id) if nom == prof.COLLECTION_CODES else None
                return mock.Mock(exists=data is not None, to_dict=lambda: dict(data or {}))

            def update(self, champs):
                base.maj.append((nom, self.doc_id, champs))
                base.codes.get(self.doc_id, {}).update(champs)

        class Collection:
            def document(self, doc_id):
                return Doc(doc_id)

            def add(self, data):
                base.ajouts.append((nom, data))

        return Collection()


class ModuleTests(unittest.TestCase):
    def test_codes(self):
        self.assertEqual(prof.extraire_code("Bonjour, voici mon code : prof-sidibe-4821"), CODE)
        self.assertIsNone(prof.extraire_code("mon prof de maths est absent"))
        self.assertIsNone(prof.extraire_code("PROF-SIDIBE-48210"))
        code = prof.nouveau_code("M. Sidibé", existants={CODE})
        self.assertRegex(code, r"^PROF-SIDIBE-\d{4}$")
        self.assertNotEqual(code, CODE)
        self.assertEqual(prof.slug_nom("Mme Kouassi Aya"), "KOUASSI")

    def test_classes(self):
        self.assertEqual(prof.classe_vers_profil("2nde F2"), {"type_examen": "BAC_TECHNIQUE", "serie": "F2", "classe": "SECONDE"})
        self.assertEqual(prof.classe_vers_profil("Tle D"), {"type_examen": "BAC_GENERAL", "serie": "D", "classe": ""})
        self.assertEqual(prof.classe_vers_profil("1ère C")["serie"], "PREMIERE_C")
        self.assertEqual(prof.classe_vers_profil("3ème")["type_examen"], "BEPC")
        self.assertEqual(prof.classe_vers_profil("6e")["serie"], "6E")
        with self.assertRaises(ValueError):
            prof.classe_vers_profil("Licence 2")

    def test_titres_de_liste(self):
        _, options = prof.options_menu("M. Sidibé")
        for lettre, titre, _ in options:
            self.assertLessEqual(len(f"{lettre}. {titre}"), 24, titre)

    def test_signalement(self):
        self.assertEqual(prof.texte_signalement("Correction : le couple vaut 40 N·m"), "le couple vaut 40 N·m")
        self.assertIsNone(prof.texte_signalement("erreur"))
        self.assertIsNone(prof.texte_signalement("explique la traction"))


class ParcoursTests(Base):
    def setUp(self):
        super().setUp()
        self.db = FauxFirestore({CODE: dict(DOC_CODE)})
        self.choix = []
        self.extra = [
            mock.patch.object(main, "feedback_db", self.db),
            mock.patch.object(main, "envoyer_choix", side_effect=lambda phone, q, options: self.choix.append((q, options))),
            mock.patch.object(main, "load_last_assistant_context", return_value="Réponse d'Akili : C = 400 N·m"),
        ]
        for p in self.extra:
            p.start()

    def tearDown(self):
        for p in self.extra:
            p.stop()
        super().tearDown()

    def test_activation_puis_modes(self):
        resultat = self.envoyer(texte("Bonjour, mon code est PROF-SIDIBE-4821", "e1"))
        self.assertEqual(resultat["reason"], "enseignant_active")
        self.assertIn("Bonjour M. Sidibé", self.envoyes[-1])
        self.assertTrue(self.etat["enseignant_verifie"])
        self.assertEqual((self.etat["matiere"], self.etat["serie"], self.etat["classe"]), ("MECANIQUE_APPLIQUEE", "F2", "SECONDE"))
        self.assertEqual(self.etat["mode"], prof.MODE_PROFIL_ASSISTANT)
        self.assertTrue(main.is_profile_ready(self.etat))
        self.assertEqual(self.db.codes[CODE]["phone"], PHONE)
        self.assertEqual(len(self.choix[-1][1]), 4)  # menu a, b, c, d

        self.assertEqual(self.envoyer(texte("a", "e2"))["reason"], "enseignant_mode_eleve")
        self.assertEqual(main.type_utilisateur_akili(self.etat), "ELEVE_TEST")
        self.assertEqual(self.etat["mode"], "etude")
        self.assertIn("Mode élève activé", self.envoyes[-1])

        self.envoyer(texte("menu prof", "e3"))
        self.assertEqual(self.envoyer(texte("b", "e4"))["reason"], "enseignant_mode_assistant")
        self.assertEqual(main.type_utilisateur_akili(self.etat), "ENSEIGNANT")
        self.assertTrue(main.espace_enseignant_actif(self.etat))

    def test_changer_matiere_et_classe(self):
        self.envoyer(texte(CODE, "c1"))
        self.envoyer(texte("c", "c2"))
        self.assertEqual(self.choix[-1][0], "Quelle matière ?")
        self.envoyer(texte("b", "c3"))
        self.assertEqual(self.choix[-1][0], "Quelle classe ?")
        self.assertEqual(self.envoyer(texte("c", "c4"))["reason"], "enseignant_classe")
        self.assertEqual((self.etat["matiere"], self.etat["classe"], self.etat["enseignant_classe"]), ("CMI", "TERMINALE", "Tle F2"))
        self.assertIn("C'est noté", self.envoyes[-1])

    def test_signalement(self):
        self.envoyer(texte(CODE, "s1"))
        self.assertEqual(self.envoyer(texte("correction : le couple vaut 40 N·m, d = 400 mm", "s2"))["reason"],
                         "enseignant_signalement")
        nom, data = self.db.ajouts[-1]
        self.assertEqual(nom, prof.COLLECTION_SIGNALEMENTS)
        self.assertEqual(data["texte"], "le couple vaut 40 N·m, d = 400 mm")
        self.assertIn("400 N·m", data["message_akili"])
        self.envoyer(texte("d", "s3"))
        self.assertEqual(self.envoyer(texte("Il manque l'unité dans le corrigé", "s4"))["reason"], "enseignant_signalement")

    def test_question_normale_va_a_akili(self):
        self.envoyer(texte(CODE, "q1"))
        self.envoyer(texte("Prépare une évaluation de 30 min sur la traction", "q2"))
        self.assertTrue(self.akili)
        self.assertNotIn("attente_prof", self.etat)

    def test_codes_refuses(self):
        self.assertEqual(self.envoyer(texte("PROF-SIDIBE-1111", "r1"))["reason"], "enseignant_code_invalide")
        self.db.codes[CODE]["phone"] = "22599999999"
        self.assertEqual(self.envoyer(texte(CODE, "r2"))["reason"], "enseignant_code_deja_utilise")
        self.assertFalse(self.etat.get("enseignant_verifie"))

    def test_eleve_qui_parle_de_son_prof(self):
        self.etat = {"type_examen": "BAC_GENERAL", "serie": "D", "matiere": "MATHS", "mode": "etude",
                     "profile_ready": True, "onboarding_step": "", "matiere_confirmed": True, "profile_locked": True}
        self.assertIsNone(main.traiter_espace_enseignant(PHONE, dict(self.etat), "correction : mon prof dit que c'est faux"))
        self.assertEqual(main.type_utilisateur_akili(self.etat), None)


class FinDeSeanceTests(unittest.TestCase):
    def _fin(self, profil):
        main.user_profiles[PHONE] = profil
        with mock.patch.object(main, "reserver_bilan", return_value={"nb_echanges": 4, "messages": []}), \
             mock.patch.object(main, "generer_bilan_session", return_value="Bilan") as bilan, \
             mock.patch.object(main, "send_whatsapp") as envoi, \
             mock.patch.object(main, "noter_session_bilan"), mock.patch.object(main, "planifier_revision"), \
             mock.patch.object(main, "demander_ville_ecole_si_besoin") as ville, \
             mock.patch.object(main, "maybe_send_marketing_consent_prompt") as consentement, \
             mock.patch.object(main, "demander_avis_seance") as avis:
            resultat = main.envoyer_fin_de_session(PHONE, source="inactivite")
        main.user_profiles.pop(PHONE, None)
        return resultat, bilan, envoi, (ville, consentement, avis)

    def test_preparation_sans_bilan(self):
        resultat, bilan, envoi, suites = self._fin({"enseignant_verifie": True, "mode_enseignant": prof.MODE_ASSISTANT})
        self.assertFalse(resultat)
        bilan.assert_not_called()
        envoi.assert_not_called()

    def test_mode_eleve_bilan_sans_questions_d_eleve(self):
        resultat, bilan, envoi, suites = self._fin({"enseignant_verifie": True, "mode_enseignant": prof.MODE_ELEVE})
        self.assertTrue(resultat)
        bilan.assert_called_once()
        for suite in suites:
            suite.assert_not_called()


class RequeteAkiliTests(unittest.TestCase):
    def _payload(self, **kwargs):
        envoye = {}

        def post(url, files=None, **k):
            envoye.update({cle: valeur[1] for cle, valeur in files.items()})
            return mock.Mock(status_code=200, json=lambda: {"reponse": "ok"}, text="{}")

        with mock.patch.object(main.requests, "post", side_effect=post):
            main.get_akili_response("Prépare une évaluation", "MECANIQUE_APPLIQUEE", "F2", [], phone=PHONE,
                                    type_examen="BAC_TECHNIQUE", mode="enseignant", **kwargs)
        return envoye

    def test_user_type_envoye(self):
        verifie = self._payload(user_type="ENSEIGNANT", espace_enseignant=True)
        self.assertEqual(verifie["user_type"], "ENSEIGNANT")
        self.assertIn("ESPACE ENSEIGNANT VERIFIE", verifie["question"])
        self.assertEqual(verifie["mode"], "etude")
        declare = self._payload(user_type="ENSEIGNANT")
        self.assertEqual(declare["user_type"], "ENSEIGNANT_DECLARE")
        self.assertNotIn("ESPACE ENSEIGNANT VERIFIE", declare["question"])
        eleve = self._payload(user_type="ELEVE_TEST")
        self.assertEqual(eleve["user_type"], "ELEVE_TEST")
        self.assertNotIn("CONTEXTE PROFIL ENSEIGNANT", eleve["question"])


if __name__ == "__main__":
    unittest.main()
