"""Controle qualite du 30 oct. : options d'un QCM modifiees quand la question est reposee (la bonne reponse
avait disparu), et application numerique entierement faite par Akili."""
import ast
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name("main.py").read_text(encoding="utf-8")


def charger():
    noms = {"REGLES_PEDAGOGIE", "consigne_bonne_lettre", "LETTRES_QCM"}
    ns = {"random": __import__("random")}
    noeuds = [n for n in ast.parse(SOURCE).body
              if (isinstance(n, ast.FunctionDef) and n.name in noms)
              or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in noms for t in n.targets))]
    exec(compile(ast.Module(body=noeuds, type_ignores=[]), "main.py", "exec"), ns)
    return ns


class QcmReposeTests(unittest.TestCase):
    def setUp(self):
        self.regles = charger()["REGLES_PEDAGOGIE"]

    def test_memes_options_quelle_que_soit_la_raison(self):
        self.assertIn("QCM REPOSÉ :", self.regles)
        self.assertIn("après une demande de l'élève", self.regles)
        self.assertIn("surtout pas la bonne réponse", self.regles)
        self.assertIn("n'en ajoute aucune", self.regles)

    def test_apres_une_erreur_toujours_couvert(self):
        self.assertIn("jamais 2 options", self.regles)
        self.assertIn("Après une deuxième erreur sur la même question", self.regles)

    def test_lettre_tiree_au_hasard_ne_sapplique_pas_a_une_question_reposee(self):
        consigne = charger()["consigne_bonne_lettre"]("b")
        self.assertIn("quand tu reposes la même question", consigne)
        self.assertNotIn("après une erreur : garde", consigne)


class ApplicationNumeriqueTests(unittest.TestCase):
    def test_regle_presente(self):
        regles = charger()["REGLES_PEDAGOGIE"]
        self.assertIn("APPLICATION NUMÉRIQUE :", regles)
        self.assertIn("ne fais pas les remplacements à la place de l'élève", regles)
        self.assertIn("montre la première substitution seulement", regles)


class GrilleTests(unittest.TestCase):
    def test_grille_alignee(self):
        grille = (Path(__file__).parent.parent / "controle_qualite.py").read_text(encoding="utf-8")
        self.assertIn("tous les remplacements d'une application numerique", grille)
        self.assertIn("quand il repose la meme question", grille)


if __name__ == "__main__":
    unittest.main()
