"""Controle qualite du 7 oct. (23 h 28) : boucle de la consigne du mode examen, message de fin
apres la ville et l'ecole, niveau du primaire."""
import unittest
from unittest import mock

import main

PHONE = "22500000099"
CONSIGNE = ("Je vois ton exercice. En mode examen, tu dois résoudre l'exercice entièrement sur une feuille de "
            "papier, puis m'envoyer une photo claire de ta copie.")


class ModeExamenTests(unittest.TestCase):
    def proposer(self, texte, dernier=CONSIGNE, mode="examen"):
        envois = []
        profil = {"mode": mode}
        with mock.patch.object(main, "load_last_assistant_context", return_value=dernier), \
                mock.patch.object(main, "send_whatsapp_boutons", side_effect=lambda *a, **k: envois.append(a) or True), \
                mock.patch.object(main, "send_whatsapp"):
            return main.proposer_mode_etude(PHONE, profil, texte), envois

    def test_eleve_perdu_apres_la_consigne(self):
        for texte in ["Ke vous attend maintenant", "Tu es inutile pour moi", "Je t'en merde", "Corrige l'exercice"]:
            propose, envois = self.proposer(texte)
            self.assertTrue(propose, texte)
            self.assertEqual(envois[0][1], main.OFFRE_MODE_ETUDE)

    def test_reponse_tapee_non_interrompue(self):
        for texte in ["ok", "D'accord", "x = 3 et y = 2", "f'(x) = 2x + 1 donc f est croissante sur ]0 ; +inf[ selon le tableau"]:
            self.assertFalse(self.proposer(texte)[0], texte)

    def test_sans_consigne_ou_en_mode_etude(self):
        self.assertFalse(self.proposer("ok", dernier="Bravo, ta copie vaut 14/20.")[0])
        self.assertFalse(self.proposer("Tu es inutile pour moi", mode="etude")[0])


class MessagesTests(unittest.TestCase):
    def test_merci_ne_ferme_pas_la_seance(self):
        self.assertNotIn("À bientôt", main.MESSAGE_MERCI_VILLE_ECOLE)
        self.assertIn("On continue", main.MESSAGE_MERCI_VILLE_ECOLE)
        self.assertNotIn("À bientôt", main.MESSAGE_PASSER_VILLE_ECOLE)

    def test_consigne_niveau_du_primaire(self):
        source = open(main.__file__, encoding="utf-8").read()
        self.assertIn("NIVEAU HORS PROGRAMME", source)
        self.assertIn("CM2", source)


if __name__ == "__main__":
    unittest.main()
