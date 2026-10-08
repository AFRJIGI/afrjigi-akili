import ast
import json
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
NOMS = {"MINI_TEST_CONSIGNES", "lire_json_modele"}
ns = {"json": json}
noeuds = [n for n in ast.parse(SOURCE).body
          if (isinstance(n, ast.FunctionDef) and n.name in NOMS)
          or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in NOMS for t in n.targets))]
exec(compile(ast.Module(body=noeuds, type_ignores=[]), "main.py", "exec"), ns)


class MiniTestApiTests(unittest.TestCase):
    def test_json_du_modele(self):
        attendu = {"chapitre": "Dérivées", "questions": []}
        for texte in ['{"chapitre": "Dérivées", "questions": []}',
                      '```json\n{"chapitre": "Dérivées", "questions": []}\n```',
                      'Voici le test : {"chapitre": "Dérivées", "questions": []} Bon courage']:
            self.assertEqual(ns["lire_json_modele"](texte), attendu, texte)
        self.assertIsNone(ns["lire_json_modele"]("pas de json"))
        self.assertIsNone(ns["lire_json_modele"]("{cassé"))

    def test_consignes(self):
        consignes = ns["MINI_TEST_CONSIGNES"]
        self.assertIn("exactement 3 questions", consignes)
        self.assertIn("Verifie chaque bonne reponse", consignes)
        self.assertIn('"bonne"', consignes)
        self.assertIn('@app.post("/mini-test")', SOURCE)


if __name__ == "__main__":
    unittest.main()
