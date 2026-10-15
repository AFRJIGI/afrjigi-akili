"""Controle qualite du 11 oct. : eleve bloque (meme explication repetee), reponse sans choix prise pour une
option, travail « recu » qui n'a pas ete envoye, enonce modifie, bilan qui cite un exercice non traite."""
import ast
import re
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
NOMS = {"LANGAGE_ET_AUTRE_MATIERE", "BILAN_REGLES_COMMUNES"}
ns = {"re": re}
noeuds = [n for n in ast.parse(SOURCE).body
          if isinstance(n, ast.Assign) and any(getattr(t, "id", "") in NOMS for t in n.targets)]
exec(compile(ast.Module(body=noeuds, type_ignores=[]), "main.py", "exec"), ns)


class ReglesTests(unittest.TestCase):
    def test_regles_du_tuteur(self):
        texte = ns["LANGAGE_ET_AUTRE_MATIERE"]
        self.assertIn("ne répète jamais la même explication", texte)
        self.assertIn("Après trois essais sans réussir la même étape", texte)
        self.assertIn("ne choisis jamais à sa place", texte)
        self.assertIn("ne dis jamais que tu as reçu, lu ou corrigé", texte)
        self.assertIn("recopie exactement les nombres, les signes", texte)

    def test_regles_du_bilan(self):
        texte = ns["BILAN_REGLES_COMMUNES"]
        self.assertIn("n'est pas « vu »", texte)
        self.assertIn("reellement travaillee dans l'historique", texte)


if __name__ == "__main__":
    unittest.main()
