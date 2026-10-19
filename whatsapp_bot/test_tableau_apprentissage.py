"""Tableau de bord : regularite (3 jours sur 7, retour dans la semaine) et defis de revision (13 oct.)."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import main
import tableau_de_bord as tdb

NOW = datetime(2026, 10, 13, 18, 0, tzinfo=timezone.utc)


def m(phone, jours):
    return {"phone": phone, "direction": "inbound", "matiere": "MATHS",
            "created_at": (NOW - timedelta(days=jours, hours=1)).isoformat()}


# e1 : 3 jours ; e2 : 2 jours ; e3 : actif il y a 7 jours et revenu ; e4 : actif il y a 7 jours seulement
MESSAGES = [m("e1", 0), m("e1", 2), m("e1", 4), m("e2", 0), m("e2", 1), m("e3", 7), m("e3", 3), m("e4", 7)]


class RegulariteTests(unittest.TestCase):
    def test_chiffres(self):
        r = tdb.calculer_stats(MESSAGES, [], NOW)["regularite"]
        self.assertEqual((r["actifs_semaine"], r["reguliers"], r["pct_reguliers"]), (3, 1, 33.3))
        self.assertEqual((r["base_retour_semaine"], r["pct_retour_semaine"]), (2, 50.0))

    def test_page(self):
        st = tdb.calculer_stats(MESSAGES, [], NOW)
        revs = tdb.calculer_revisions([
            {"envoyee_le": NOW.isoformat(), "repondu": True, "juste": True},
            {"envoyee_le": NOW.isoformat(), "repondu": True, "juste": False},
            {"envoyee_le": NOW.isoformat(), "repondu": True, "juste": None},
            {"envoyee_le": NOW.isoformat(), "repondu": False},
            {"envoyee_le": (NOW - timedelta(days=20)).isoformat(), "repondu": True, "juste": True},
        ], NOW)
        self.assertEqual(revs["semaine"]["pct_repondus"], 75)
        self.assertEqual((revs["total"]["justes"], revs["total"]["classes"], revs["total"]["pct_justes"]), (2, 3, 67))
        page = tdb.rendre_html(st, revisions=revs)
        self.assertIn("Élèves réguliers (7 j)", page)
        self.assertIn("33.3 %", page)
        self.assertIn("3 sur 4 envoyés", page)
        self.assertIn("2 sur 3 depuis le début", page)


class CorrectionTests(unittest.TestCase):
    def test_classement(self):
        for texte in ("Exact ! Le vecteur...", "Bravo, c'est juste.", "C'est ça !", "Très bien, tu as trouvé"):
            self.assertIs(main.correction_est_juste(texte), True, texte)
        for texte in ("Non, ce n'est pas la bonne réponse.", "Presque ! Regarde le signe.", "Pas tout à fait."):
            self.assertIs(main.correction_est_juste(texte), False, texte)
        self.assertIsNone(main.correction_est_juste("Voici un nouvel exercice sur les limites."))

    def test_reponse_notee_une_fois(self):
        ecrits = []
        base = mock.MagicMock()
        base.collection.return_value.document.return_value.set.side_effect = lambda d, merge=False: ecrits.append(d)
        profil = {"revision_en_attente": {"id": "abc_20261013", "le": (NOW - timedelta(hours=2)).isoformat()}}
        with mock.patch.object(main, "feedback_db", base):
            main.noter_reponse_revision("p", profil, "Exact ! Bien retenu.", now=NOW)
            main.noter_reponse_revision("p", profil, "Non.", now=NOW)
        self.assertEqual(len(ecrits), 1)
        self.assertEqual((ecrits[0]["repondu"], ecrits[0]["juste"]), (True, True))
        self.assertNotIn("revision_en_attente", profil)

    def test_trop_tard(self):
        base = mock.MagicMock()
        profil = {"revision_en_attente": {"id": "x", "le": (NOW - timedelta(hours=30)).isoformat()}}
        with mock.patch.object(main, "feedback_db", base):
            main.noter_reponse_revision("p", profil, "Exact", now=NOW)
        base.collection.return_value.document.return_value.set.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class RetourMoyenTests(unittest.TestCase):
    def test_moyenne_ponderee_sur_jours_complets(self):
        # veille J-2 : a, b ; J-1 : a revient -> 1/2. veille J-1 : a, c ; J-0 (aujourd'hui) exclu.
        msgs = [m("a", 2), m("b", 2), m("a", 1), m("c", 1), m("a", 0), m("c", 0)]
        rm = tdb.calculer_stats(msgs, [], NOW)["retour_moyen"]
        self.assertEqual(rm, {"pct": 50.0, "jours": 1})

    def test_plusieurs_jours(self):
        # J-3 : a,b,c,d ; J-2 : a,b (2/4) ; J-1 : a (1/2) -> (2+1)/(4+2) = 50 %
        msgs = [m(x, 3) for x in "abcd"] + [m("a", 2), m("b", 2), m("a", 1)]
        rm = tdb.calculer_stats(msgs, [], NOW)["retour_moyen"]
        self.assertEqual(rm, {"pct": 50.0, "jours": 2})

    def test_page(self):
        msgs = [m("a", 2), m("b", 2), m("a", 1)]
        page = tdb.rendre_html(tdb.calculer_stats(msgs, [], NOW))
        self.assertIn("Retour le lendemain (moy.)", page)
        self.assertIn("derniers jours complets", page)
