"""Controle qualite du 19 oct. : une seule etape par message, balise d'autre matiere respectee,
« A revoir » limite a ce qui est reste faux."""
import pathlib
import unittest

SOURCE = (pathlib.Path(__file__).parent / "main.py").read_text(encoding="utf-8")


class ControleQualite19OctTests(unittest.TestCase):
    def test_une_seule_etape_dans_la_regle_finale(self):
        debut = SOURCE.index("REGLE_FINALE_UNE_QUESTION = (")
        fin = SOURCE.index("LONGUEUR_WHATSAPP = (")
        regle = SOURCE[debut:fin]
        self.assertIn("UNE SEULE ÉTAPE", regle)
        self.assertIn("ne donne jamais la solution complète", regle)
        self.assertIn("échoué trois fois", regle)  # meme seuil que ÉLÈVE BLOQUÉ

    def test_autre_matiere_avec_balise(self):
        self.assertIn("Si les consignes te demandent la ligne [AUTRE_MATIERE: …]", SOURCE)

    def test_a_revoir(self):
        self.assertIn("DERNIERE reponse de l'eleve est restee fausse", SOURCE)
        self.assertIn("n'est jamais « a revoir »", SOURCE)


if __name__ == "__main__":
    unittest.main()
