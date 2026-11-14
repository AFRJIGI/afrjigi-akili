import ast
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
ns = {}
noeuds = [n for n in ast.parse(SOURCE).body
          if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "REGLES_PEDAGOGIE" for t in n.targets)]
exec(compile(ast.Module(body=noeuds, type_ignores=[]), "main.py", "exec"), ns)
REGLES = ns["REGLES_PEDAGOGIE"]


class ReglesVocabulaireTests(unittest.TestCase):
    def test_regle_presente(self):
        self.assertIn("MOTS DIFFICILES D'UN TEXTE", REGLES)
        self.assertIn("deuxième demande de vocabulaire", REGLES)

    def test_les_autres_regles_restent(self):
        for nom in ("QCM REPOSÉ", "ÉLÈVE QUI NE COMPREND PAS", "LÉGENDES D'UN SCHÉMA NUMÉROTÉ"):
            self.assertIn(nom, REGLES)


if __name__ == "__main__":
    unittest.main()
