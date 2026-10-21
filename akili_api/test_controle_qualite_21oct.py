"""Controle qualite du 21 oct. : un seul corrige a la fois, reconnaitre ses erreurs d'enonce, verifier
toutes les questions avant d'annoncer la fin d'un exercice."""
import pathlib
import unittest

SOURCE = (pathlib.Path(__file__).parent / "main.py").read_text(encoding="utf-8")


class ControleQualite21OctTests(unittest.TestCase):
    def regle_finale(self):
        return SOURCE[SOURCE.index("REGLE_FINALE_UNE_QUESTION = ("):SOURCE.index("LONGUEUR_WHATSAPP = (")]

    def test_un_seul_corrige(self):
        regle = self.regle_finale()
        self.assertIn("CORRIGÉ DEMANDÉ", regle)
        self.assertIn("la correction d'UNE seule question", regle)
        self.assertNotIn("demande lui-même un corrigé", regle)  # l'ancienne exception

    def test_erreur_et_fin_d_exercice(self):
        bloc = SOURCE[SOURCE.index("LANGAGE_ET_AUTRE_MATIERE = ("):SOURCE.index("REGLE_FINALE_UNE_QUESTION = (")]
        self.assertIn("TON ERREUR", bloc)
        self.assertIn("« Je me suis trompé : … »", bloc)
        self.assertIn("FIN D'EXERCICE", bloc)
        self.assertIn("Ne repropose jamais un exercice", bloc)


if __name__ == "__main__":
    unittest.main()
