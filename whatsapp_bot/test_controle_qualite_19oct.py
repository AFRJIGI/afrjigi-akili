"""Controle qualite du 19 oct. : une courte demande d'une autre matiere (« factorise 4x + 8 » en SVT) change
la matiere comme une longue ; la consigne ne demande plus d'ecrire menu quand l'application change elle-meme."""
import unittest

import main
import test_controle_qualite_9oct as t9


class AutreMatiereCourteTests(unittest.TestCase):
    PHONE = t9.MatiereEtDocumentTests.PHONE
    setUp = t9.MatiereEtDocumentTests.setUp
    tearDown = t9.MatiereEtDocumentTests.tearDown
    profil = t9.MatiereEtDocumentTests.profil
    repondre = t9.MatiereEtDocumentTests.repondre

    def test_trois_mots_suffisent(self):
        profil = self.profil("SVT")
        self.repondre(profil, "factorise 4x + 8", "[AUTRE_MATIERE: Mathématiques]\nQuel facteur commun vois-tu ?")
        self.assertEqual(profil["matiere"], "MATHS")
        self.assertTrue(self.envoyes[-1].startswith("Ta question relève"))

    def test_reponse_courte_reste_dans_la_matiere(self):
        for reponse in ["c'est b", "x = 3", "oui la b"]:
            profil = self.profil("SVT")
            self.repondre(profil, reponse, "[AUTRE_MATIERE: Mathématiques]\nOui.")
            self.assertEqual(profil["matiere"], "SVT", reponse)


class ConsignesTests(unittest.TestCase):
    def test_consignes_coherentes(self):
        self.assertIn("ne lui dis donc pas d'écrire menu", main.CONSIGNE_QUESTION_AUTRE_MATIERE)
        consigne = main.consigne_matiere_choisie("SVT", "D", "BAC_GENERAL")
        self.assertIn("QUESTION D'UNE AUTRE MATIERE si elle figure", consigne)


if __name__ == "__main__":
    unittest.main()
