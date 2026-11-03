import unittest
from datetime import datetime, timedelta, timezone

import main

ENVOI = datetime(2026, 11, 2, 21, 6, 10, tzinfo=timezone.utc)
PROFIL = {"premier_exercice_envoye_le": ENVOI.isoformat()}


class PremierExerciceTests(unittest.TestCase):
    def test_message_ecrit_avant_l_envoi_est_ignore(self):
        recu = (ENVOI - timedelta(seconds=4)).isoformat()
        self.assertTrue(main.reponse_ecrite_avant_le_premier_exercice(PROFIL, recu))

    def test_message_ecrit_apres_l_envoi_est_une_vraie_reponse(self):
        recu = (ENVOI + timedelta(seconds=5)).isoformat()
        self.assertFalse(main.reponse_ecrite_avant_le_premier_exercice(PROFIL, recu))

    def test_ancien_message_hors_fenetre_pas_ignore(self):
        recu = (ENVOI - timedelta(minutes=10)).isoformat()
        self.assertFalse(main.reponse_ecrite_avant_le_premier_exercice(PROFIL, recu))

    def test_sans_premier_exercice_rien_a_ignorer(self):
        self.assertFalse(main.reponse_ecrite_avant_le_premier_exercice({}, ENVOI.isoformat()))


if __name__ == "__main__":
    unittest.main()
