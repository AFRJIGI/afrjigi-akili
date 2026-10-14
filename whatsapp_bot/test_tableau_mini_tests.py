"""Tableau de bord : resultats des mini-tests de progression (13 oct., pour mesurer l'effet d'Akili)."""
import unittest
from datetime import datetime, timedelta, timezone

import tableau_de_bord as tdb
from test_sante_tableau import AVIS, MESSAGES

NOW = datetime(2026, 10, 13, 18, 0, tzinfo=timezone.utc)
JOUR = (NOW - timedelta(days=1)).isoformat()
RESULTATS = [
    {"phase": "debut", "matiere": "MATHS", "score": 1, "eleve": "e1", "cree_le": JOUR},
    {"phase": "debut", "matiere": "MATHS", "score": 2, "eleve": "e2", "cree_le": JOUR},
    {"phase": "debut", "matiere": "PC", "score": 0, "eleve": "e3", "cree_le": (NOW - timedelta(days=20)).isoformat()},
    {"phase": "fin", "matiere": "MATHS", "score": 3, "score_debut": 1, "eleve": "e1", "cree_le": NOW.isoformat()},
    {"phase": "fin", "matiere": "MATHS", "score": 2, "score_debut": 2, "eleve": "e2", "cree_le": NOW.isoformat()},
    {"phase": "fin", "matiere": "PC", "score": 0, "score_debut": 1, "eleve": "e3", "cree_le": NOW.isoformat()},
    {"phase": "debut", "matiere": "SVT", "eleve": "e4"},  # incomplet : ignore
]
PROPOSITIONS = [{"processing_stage": "mini_test_propose_debut"}, {"processing_stage": "mini_test_propose_fin"},
                {"processing_stage": "akili_api"}]


class MiniTestsTests(unittest.TestCase):
    def test_chiffres(self):
        mt = tdb.calculer_mini_tests(RESULTATS, PROPOSITIONS, NOW)
        self.assertEqual((mt["proposes_7j"], mt["debuts"], mt["debuts_7j"], mt["eleves"]), (2, 3, 2, 3))
        self.assertEqual(mt["score_debut"], 1.0)
        self.assertEqual((mt["paires"], mt["avant"], mt["apres"]), (3, 1.33, 1.67))
        self.assertEqual((mt["progres"], mt["stables"], mt["baisses"]), (1, 1, 1))
        self.assertEqual(mt["matieres"][0][:2], ("MATHS", 2))

    def test_bloc_dans_la_page(self):
        st = tdb.calculer_stats(MESSAGES, AVIS, NOW)
        page = tdb.rendre_html(st, mini_tests=tdb.calculer_mini_tests(RESULTATS, PROPOSITIONS, NOW))
        self.assertIn("Mini-tests de progression", page)
        self.assertIn("1.33 → 1.67 / 3", page)
        self.assertIn("Progressent : <b>1</b> (33 %)", page)
        self.assertIn("Moins de 30 élèves", page)
        self.assertNotIn("e1", page.replace("e1x", ""))  # aucun identifiant d'eleve

    def test_sans_test_termine(self):
        page = tdb.rendre_html(tdb.calculer_stats(MESSAGES, AVIS, NOW),
                               mini_tests=tdb.calculer_mini_tests([], PROPOSITIONS, NOW))
        self.assertIn("Aucun test terminé pour le moment. 2 proposition(s)", page)

    def test_sans_fin_encore(self):
        mt = tdb.calculer_mini_tests(RESULTATS[:3], [], NOW)
        page = tdb.rendre_html(tdb.calculer_stats(MESSAGES, AVIS, NOW), mini_tests=mt)
        self.assertIn("la comparaison début → fin apparaîtra ici", page)


if __name__ == "__main__":
    unittest.main()
