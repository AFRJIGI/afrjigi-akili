"""Reprise au premier message d'une nouvelle journee (0119) : rappelle le chapitre travaille la veille
et propose le mini-test a ce moment-la, au lieu de la fin de seance ou l'eleve s'en allait."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import main
import mini_test

PHONE = "+2250700000000"
NOW = datetime.now(timezone.utc)
HIER = (NOW - timedelta(days=1)).isoformat()


def profil():
    return {"matiere": "MATHS", "serie": "D", "type_examen": "BAC", "profile_ready": True,
            "onboarding_completed_at": NOW.isoformat()}


def seance(nb_echanges=1, precedente_fin=HIER, precedente_matiere="MATHS"):
    return {"nb_echanges": nb_echanges, "precedente_fin": precedente_fin,
            "precedente_matiere": precedente_matiere}


class RepriseTests(unittest.TestCase):
    def setUp(self):
        main._reprise_notee.clear()
        self.eligible = mock.patch.object(main, "mini_test_eligible", return_value=True)
        self.eligible.start()
        self.addCleanup(self.eligible.stop)
        self.sauver = mock.patch.object(main, "sauver_etat_mini_test")
        self.sauver.start()
        self.addCleanup(self.sauver.stop)
        self.event = mock.patch.object(main, "save_whatsapp_event")
        self.event.start()
        self.addCleanup(self.event.stop)

    def _etat(self, cycle=None):
        return {"mini_tests": {"MATHS": dict(cycle or {})}}

    def test_chapitre_rappele_et_mini_test_propose(self):
        etat = self._etat({"chapitre": "Dérivées", "debut_le": (NOW - timedelta(days=5)).isoformat(),
                           "jours": ["a", "b", "c"]})
        with mock.patch.object(main, "charger_etat_mini_test", return_value=etat), \
             mock.patch.object(main, "send_whatsapp_boutons", return_value=True) as boutons:
            self.assertTrue(main.reprise_debut_de_seance(PHONE, profil(), seance()))
        texte = boutons.call_args[0][1]
        self.assertIn("Dérivées", texte)
        self.assertIn("La dernière fois", texte)

    def test_sans_chapitre_rappel_de_la_matiere_seule(self):
        with mock.patch.object(main, "charger_etat_mini_test",
                               return_value=self._etat({"propositions_debut": 3})), \
             mock.patch.object(main, "send_whatsapp") as envoi:
            self.assertTrue(main.reprise_debut_de_seance(PHONE, profil(), seance()))
        texte = envoi.call_args[0][1]
        self.assertIn("Mathématiques", texte)
        self.assertIn("ou tu préfères autre chose", texte)

    def test_rien_au_deuxieme_message_de_la_seance(self):
        with mock.patch.object(main, "charger_etat_mini_test", return_value=self._etat()), \
             mock.patch.object(main, "send_whatsapp") as envoi:
            self.assertFalse(main.reprise_debut_de_seance(PHONE, profil(), seance(nb_echanges=2)))
        envoi.assert_not_called()

    def test_rien_si_deja_venu_aujourd_hui(self):
        with mock.patch.object(main, "charger_etat_mini_test", return_value=self._etat()), \
             mock.patch.object(main, "send_whatsapp") as envoi:
            self.assertFalse(main.reprise_debut_de_seance(
                PHONE, profil(), seance(precedente_fin=NOW.isoformat())))
        envoi.assert_not_called()

    def test_rien_a_la_toute_premiere_seance(self):
        with mock.patch.object(main, "charger_etat_mini_test", return_value=self._etat()), \
             mock.patch.object(main, "send_whatsapp") as envoi:
            self.assertFalse(main.reprise_debut_de_seance(PHONE, profil(), seance(precedente_fin="")))
        envoi.assert_not_called()

    def test_une_seule_reprise_par_jour(self):
        with mock.patch.object(main, "charger_etat_mini_test",
                               return_value=self._etat({"propositions_debut": 3})), \
             mock.patch.object(main, "send_whatsapp") as envoi:
            self.assertTrue(main.reprise_debut_de_seance(PHONE, profil(), seance()))
            self.assertFalse(main.reprise_debut_de_seance(PHONE, profil(), seance()))
        self.assertEqual(envoi.call_count, 1)

    def test_rien_sans_matiere_ni_chapitre(self):
        with mock.patch.object(main, "charger_etat_mini_test", return_value={"mini_tests": {}}), \
             mock.patch.object(main, "send_whatsapp") as envoi:
            profil_sans = dict(profil(), matiere="")
            self.assertFalse(main.reprise_debut_de_seance(
                PHONE, profil_sans, seance(precedente_matiere="")))
        envoi.assert_not_called()


class FinDeSeanceTests(unittest.TestCase):
    def test_plus_de_proposition_apres_le_bilan(self):
        with mock.patch.object(main, "proposer_mini_test_fin_de_seance") as ancienne:
            self.assertFalse(main.mini_test_apres_bilan(PHONE, profil(), {"nb_echanges": 6}))
        ancienne.assert_not_called()


class PhaseAuDemarrageTests(unittest.TestCase):
    def test_zero_echange_accepte_au_demarrage(self):
        etat = {"matiere": "MATHS", "mini_tests": {}}
        self.assertIsNone(mini_test.phase_a_proposer(etat, 0))
        self.assertEqual(mini_test.phase_a_proposer(etat, 0, au_demarrage=True), "debut")

    def test_delai_entre_propositions_respecte_au_demarrage(self):
        etat = {"matiere": "MATHS",
                "mini_tests": {"MATHS": {"propose_le": mini_test.aujourd_hui()}}}
        self.assertIsNone(mini_test.phase_a_proposer(etat, 0, au_demarrage=True))

    def test_trois_refus_arretent_les_propositions_au_demarrage(self):
        etat = {"matiere": "MATHS", "mini_tests": {"MATHS": {"propositions_debut": 3}}}
        self.assertIsNone(mini_test.phase_a_proposer(etat, 0, au_demarrage=True))

    def test_test_en_cours_bloque_la_proposition(self):
        etat = {"matiere": "MATHS", "mini_test": {"etat": "en_cours"}, "mini_tests": {}}
        self.assertIsNone(mini_test.phase_a_proposer(etat, 0, au_demarrage=True))


class TexteRepriseTests(unittest.TestCase):
    def test_chapitre_prioritaire_sur_matiere(self):
        self.assertIn("Dérivées", mini_test.texte_reprise("Dérivées", "Mathématiques"))

    def test_matiere_en_repli(self):
        self.assertIn("Mathématiques", mini_test.texte_reprise("", "Mathématiques"))

    def test_rien_sans_rien(self):
        self.assertEqual(mini_test.texte_reprise("", ""), "")


if __name__ == "__main__":
    unittest.main()
