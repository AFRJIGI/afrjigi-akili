"""Controle qualite du 14 oct. : historique trop court, « Je n'ai plus le sujet » sur une introduction redigee,
« pas de revisions stp », deux mini-tests lances par un « Oui » double, saturation de l'API."""
import unittest
from unittest import mock

import main


class HistoriqueTests(unittest.TestCase):
    def test_taille(self):
        self.assertEqual((main.HISTORIQUE_MAX, main.HISTORIQUE_ENVOYE), (16, 12))
        source = open(main.__file__, encoding="utf-8").read()
        self.assertNotIn("[-10:]", source)
        self.assertNotIn("history[-8:]", source)


class SujetIndisponibleTests(unittest.TestCase):
    def test_long_texte_avec_le_mot_image(self):
        intro = ("L'homme a souvent de lui-même une image claire et croit maîtriser ses actes. Pourtant Freud montre "
                 "que l'inconscient agit sans qu'il le sache. Dès lors, l'inconscient prive-t-il l'homme de sa liberté ?")
        self.assertFalse(main.mentions_user_document_without_content(intro))
        self.assertTrue(main.mentions_user_document_without_content("corrige le document que je t'ai envoyé"))
        self.assertTrue(main.mentions_user_document_without_content("traite ça"))


class RevisionsTests(unittest.TestCase):
    def test_commandes(self):
        for texte in ("Pas de révisions", "pas de révision stp", "Non pas de révisions merci", "stop révision"):
            self.assertEqual(main.commande_de_revision(texte), "arret", texte)
        self.assertEqual(main.commande_de_revision("révisions"), "reprise")
        self.assertIsNone(main.commande_de_revision("il n'y a pas de révision possible pour cet exercice de maths ici"))
        self.assertIsNone(main.commande_de_revision("Explique-moi la photosynthèse"))


if __name__ == "__main__":
    unittest.main()
