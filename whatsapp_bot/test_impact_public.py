"""Page publique d'impact et nombre total d'eleves."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import main
import tableau_de_bord as tb

MAINTENANT = datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc)


def msg(phone, jours, matiere="MATHS", **extra):
    quand = (MAINTENANT - timedelta(days=jours)).replace(hour=10).isoformat()
    return dict({"phone": phone, "direction": "inbound", "created_at": quand, "matiere": matiere}, **extra)


MESSAGES = [msg("2250101", 1), msg("2250101", 0), msg("2250102", 1, "PHILO"), msg("2250103", 3, "PC"),
            msg("2250199", 0, "MATHS", enseignant_verifie=True),
            {"phone": "2250104", "direction": "outbound", "created_at": MAINTENANT.isoformat()},
            msg("2250105", 0, "MATHS", processing_stage="onboarding_choice")]  # inscription : matiere par defaut
UTILISATEURS = {"total": 4123, "nouveaux_hier": 37, "nouveaux_aujourdhui": 12}


class ImpactTests(unittest.TestCase):
    def test_chiffres(self):
        impact = tb.calculer_impact(MESSAGES, MAINTENANT, utilisateurs=UTILISATEURS, enseignants=5)
        self.assertEqual(impact["students_total"], 4123)
        self.assertEqual(impact["new_students_yesterday"], 37)
        self.assertEqual(impact["active_students_yesterday"], 2)
        self.assertEqual(impact["active_students_today"], 2)          # l'enseignant n'est pas compte
        self.assertEqual(impact["active_students_7_days"], 4)
        self.assertEqual(impact["next_day_return_rate_7_days"], 25.0)  # moyenne de 0 % (J-3) et 50 % (hier -> aujourd'hui)
        self.assertEqual(impact["partner_teachers"], 5)
        self.assertIn(("Mathematics", 1), impact["subjects_7_days"])  # l'eleve en inscription ne compte pas en maths
        self.assertEqual(len(impact["daily_active_students"]), 7)

    def test_aucune_donnee_personnelle(self):
        impact = tb.calculer_impact(MESSAGES, MAINTENANT, utilisateurs=UTILISATEURS, enseignants=5)
        page = tb.rendre_impact_html(impact)
        for texte in (page, json.dumps(impact)):
            self.assertNotIn("22501", texte)
        self.assertIn("4 123", page)
        self.assertIn("Try Akili on WhatsApp", page)
        self.assertIn("https://wa.me/13154030671", page)

    def test_tableau_prive_avec_totaux(self):
        stats = tb.calculer_stats(MESSAGES, [], MAINTENANT)
        page = tb.rendre_html(stats, utilisateurs=UTILISATEURS)
        self.assertIn("Élèves WhatsApp (total)", page)
        self.assertIn("4 123", page)
        self.assertIn("Nouveaux élèves hier", page)
        self.assertIn("12 aujourd'hui", page)

    def test_numero_note_une_fois(self):
        ecritures = []

        class Doc:
            def create(self, data):
                ecritures.append(data)

        db = mock.Mock()
        db.collection.return_value.document.return_value = Doc()
        main._numeros_connus.discard("2250555")
        with mock.patch.object(main, "feedback_db", db):
            main.noter_numero_whatsapp("2250555", "2026-10-05T10:00:00+00:00")
            main.noter_numero_whatsapp("2250555", "2026-10-05T11:00:00+00:00")
        self.assertEqual(ecritures, [{"premier_contact": "2026-10-05T10:00:00+00:00"}])


if __name__ == "__main__":
    unittest.main()
