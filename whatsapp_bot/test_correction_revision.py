"""Correction des defis de revision avec la lettre gardee a l'envoi (0120)."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import main

NOW = datetime.now(timezone.utc)


class LettreTests(unittest.TestCase):
    def test_formes_reconnues(self):
        for texte in ("b", "B", "B.", "c)", "réponse c", "Ma réponse : a", "c'est b", "Je pense a", " a "):
            self.assertIn(main.lettre_choisie(texte), ("a", "b", "c"), texte)
        self.assertEqual(main.lettre_choisie("Réponse B"), "b")

    def test_autres_reponses_ignorees(self):
        for texte in ("", None, "a = 5", "la dérivée vaut 2x", "je ne sais pas", "d", "x" * 40, "abc"):
            self.assertIsNone(main.lettre_choisie(texte), texte)


class JugementTests(unittest.TestCase):
    def test_bonne_lettre(self):
        self.assertEqual(main.juger_reponse_revision({"bonne_reponse": "b"}, "b", "Voici la suite"), (True, "lettre"))

    def test_mauvaise_lettre_avec_reponse_d_akili_ambigue(self):
        self.assertEqual(main.juger_reponse_revision({"bonne_reponse": "b"}, "a", "Regardons ensemble"),
                         (False, "lettre"))

    def test_conflit_donne_aucun_verdict(self):
        self.assertEqual(main.juger_reponse_revision({"bonne_reponse": "b"}, "a", "Exact ! Bravo"),
                         (None, "conflit"))

    def test_repli_sur_la_correction_d_akili(self):
        self.assertEqual(main.juger_reponse_revision({}, "b", "Exact !"), (True, "texte_akili"))
        self.assertEqual(main.juger_reponse_revision({"bonne_reponse": "b"}, "5x", "Non, pas tout à fait"),
                         (False, "texte_akili"))

    def test_aucun_verdict(self):
        self.assertEqual(main.juger_reponse_revision({}, "je ne sais pas", "Voici un indice"), (None, "aucun"))


class EnregistrementTests(unittest.TestCase):
    def test_methode_et_verdict_ecrits(self):
        ecrits = []
        base = mock.MagicMock()
        base.collection.return_value.document.return_value.set.side_effect = lambda d, merge=False: ecrits.append(d)
        profil = {"revision_en_attente": {"id": "x", "le": (NOW - timedelta(hours=2)).isoformat(),
                                          "bonne_reponse": "c"}}
        with mock.patch.object(main, "feedback_db", base):
            main.noter_reponse_revision("p", profil, "Voici la suite", now=NOW, texte_eleve="c")
        self.assertEqual((ecrits[0]["juste"], ecrits[0]["methode"]), (True, "lettre"))


class GenerationTests(unittest.TestCase):
    def test_lettre_recuperee_de_l_api(self):
        reponse = mock.Mock()
        reponse.json.return_value = {"reponse": "Hier...", "bonne_reponse": "B"}
        details = {}
        with mock.patch.object(main.requests, "post", return_value=reponse):
            self.assertEqual(main.generer_revision({"messages": []}, {}, details), "Hier...")
        self.assertEqual(details, {"bonne_reponse": "b"})

    def test_api_ancienne_sans_lettre(self):
        reponse = mock.Mock()
        reponse.json.return_value = {"reponse": "Hier..."}
        details = {}
        with mock.patch.object(main.requests, "post", return_value=reponse):
            main.generer_revision({"messages": []}, {}, details)
        self.assertEqual(details, {})


if __name__ == "__main__":
    unittest.main()
