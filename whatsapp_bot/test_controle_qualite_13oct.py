"""Controle qualite du 13 oct. (50 conversations apres le deploiement du 11) : « Ok demain » apres le bilan,
question de la ville et boutons d'avis juste apres « Tu as fait une pause », bilan d'une matiere quittee."""
import unittest
from datetime import timedelta
from unittest import mock

import main
from test_fin_session import NOW, PHONE, PROFIL, BaseFinSession


class AuRevoirTests(unittest.TestCase):
    def test_fins_de_seance(self):
        for texte in ("Ok demain", "demain", "d'accord à demain matin", "on verra demain", "C'est bon je te laisse",
                      "Je n'ai plus besoin de toi", "J'ai sommeil demain"):
            self.assertTrue(main.est_message_au_revoir(texte), texte)
        for texte in ("exercice pour demain", "le devoir de demain", "demain j'ai un devoir de maths"):
            self.assertFalse(main.est_message_au_revoir(texte), texte)


class ApresUnePauseTests(BaseFinSession):
    def setUp(self):
        super().setUp()
        self.ville = mock.patch.object(main, "demander_ville_ecole_si_besoin",
                                       side_effect=lambda phone: self.envoyes.append((phone, "VILLE")) or True)
        self.test = mock.patch.object(main, "proposer_mini_test_fin_de_seance", return_value=False)
        self.ville.start()
        self.test.start()

    def tearDown(self):
        self.ville.stop()
        self.test.stop()
        super().tearDown()

    def test_pas_de_question_ni_d_avis_apres_une_pause(self):
        self.ajouter_echanges(3)
        self.assertEqual(main.traiter_bilans_inactivite(now=NOW + timedelta(minutes=40))["envoyes"], 1)
        self.assertNotIn((PHONE, "VILLE"), self.envoyes)
        self.assertEqual(self.boutons, [])

    def test_ville_apres_un_au_revoir(self):
        self.ajouter_echanges(2)
        main.envoyer_fin_de_session(PHONE, "au_revoir")
        self.assertIn((PHONE, "VILLE"), self.envoyes)

    def test_pas_de_bilan_d_une_matiere_quittee(self):
        self.ajouter_echanges(3)
        with mock.patch.object(main, "charger_etat_whatsapp", side_effect=lambda phone: dict(PROFIL, matiere="MATHS")):
            self.assertEqual(main.traiter_bilans_inactivite(now=NOW + timedelta(minutes=40)),
                             {"envoyes": 0, "fermees": 1})
        self.assertEqual(self.bilans, [])


if __name__ == "__main__":
    unittest.main()
