"""Les routes qui appellent Gemini doivent etre des fonctions ordinaires (def) : FastAPI les execute dans des
fils separes. En async def, un appel bloquant a Gemini arretait tout le serveur (journaux du 8 oct., 19 h 52)."""
import ast
import pathlib
import unittest

SOURCE = (pathlib.Path(__file__).parent / "main.py").read_text(encoding="utf-8")
ROUTES_GEMINI = {"/question", "/bilan-session", "/revision-lendemain", "/mini-test", "/sante"}


def routes():
    for noeud in ast.parse(SOURCE).body:
        if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for deco in noeud.decorator_list:
                if isinstance(deco, ast.Call) and deco.args and isinstance(deco.args[0], ast.Constant):
                    yield deco.args[0].value, noeud


class RoutesTests(unittest.TestCase):
    def test_routes_gemini_en_def(self):
        trouvees = {chemin: noeud for chemin, noeud in routes() if chemin in ROUTES_GEMINI}
        self.assertEqual(set(trouvees), ROUTES_GEMINI)
        for chemin, noeud in trouvees.items():
            self.assertIsInstance(noeud, ast.FunctionDef, f"{chemin} ne doit pas etre async def")
            self.assertNotIn("await ", ast.get_source_segment(SOURCE, noeud), chemin)


if __name__ == "__main__":
    unittest.main()
