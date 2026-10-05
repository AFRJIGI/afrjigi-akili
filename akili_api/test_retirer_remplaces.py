import ast
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
ns = {}
noeuds = [n for n in ast.parse(SOURCE).body if isinstance(n, ast.FunctionDef) and n.name == "retirer_remplaces"]
exec(compile(ast.Module(body=noeuds, type_ignores=[]), "main.py", "exec"), ns)


class RetirerRemplacesTests(unittest.TestCase):
    def test_ancien_bloc_ecarte(self):
        docs = [{"id": "ancien"}, {"id": "autre"}, {"id": "nouveau_1", "remplace_ids": ["ancien"]},
                {"id": "nouveau_2", "remplace_ids": ["ancien"]}]
        self.assertEqual([d["id"] for d in ns["retirer_remplaces"](docs)], ["autre", "nouveau_1", "nouveau_2"])
        sans = [{"id": "a"}, {"id": "b"}]
        self.assertIs(ns["retirer_remplaces"](sans), sans)


if __name__ == "__main__":
    unittest.main()
