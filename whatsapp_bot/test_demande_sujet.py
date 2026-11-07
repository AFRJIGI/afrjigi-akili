"""« donne-moi un sujet » en mode examen ne declenche plus l'offre du mode etude (7 nov., 15 h)."""
import unittest
from unittest import mock

import main


class DemandeDeSujetTests(unittest.TestCase):
    def test_demandes_de_sujet(self):
        for texte in ("donne-moi un sujet", "Donne-moi un autre sujet", "autre sujet", "Un autre exercice",
                      "sujet suivant", "Propose-moi un autre sujet d'examen sur le même chapitre.",
                      "Donne-moi un sujet"):
            self.assertTrue(main.demande_de_sujet(texte), texte)

    def test_besoin_d_aide_n_est_pas_une_demande_de_sujet(self):
        for texte in ("je ne comprends pas ce sujet", "explique ce sujet", "donne-moi la réponse de l'exercice",
                      "aide-moi sur cet exercice", "bonjour", "ok"):
            self.assertFalse(main.demande_de_sujet(texte), texte)

    def test_pas_d_offre_de_mode_etude_apres_la_consigne(self):
        consigne = "Résous l'exercice sur une feuille de papier, puis envoie-moi une photo de ta copie."
        with mock.patch.object(main, "load_last_assistant_context", return_value=consigne), \
                mock.patch.object(main, "send_whatsapp_boutons", side_effect=AssertionError("pas d'offre")), \
                mock.patch.object(main, "send_whatsapp", side_effect=AssertionError("pas d'offre")):
            self.assertFalse(main.proposer_mode_etude("225", {"mode": "examen"}, "donne-moi un sujet"))

    def test_une_vraie_incomprehension_declenche_toujours_l_offre(self):
        consigne = "Résous l'exercice sur une feuille de papier, puis envoie-moi une photo de ta copie."
        with mock.patch.object(main, "load_last_assistant_context", return_value=consigne), \
                mock.patch.object(main, "send_whatsapp_boutons", return_value=True) as boutons:
            self.assertTrue(main.proposer_mode_etude("225", {"mode": "examen"}, "je ne comprends pas"))
        boutons.assert_called_once()


if __name__ == "__main__":
    unittest.main()
