"""Le mode choisi par l'eleve fait foi : le mot "examen" dans l'historique ou les
consignes ne doit plus faire basculer un eleve en mode etude vers le mode examen."""
import ast
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
ns = {}
for noeud in ast.parse(SOURCE).body:
    if isinstance(noeud, ast.FunctionDef) and noeud.name == "normaliser_mode":
        exec(compile(ast.Module(body=[noeud], type_ignores=[]), "main.py", "exec"), ns)
normaliser_mode = ns["normaliser_mode"]

PROMPT_WHATSAPP = (
    "HISTORIQUE RECENT:\nAkili: Tu es en MODE EXAMEN ACTIVE. Resous l'exercice comme le jour de l'examen.\n\n"
    "QUESTION REELLE DE L'ELEVE:\nAide moi avec ces exercices"
)


class NormaliserModeTests(unittest.TestCase):
    def test_mode_etude_choisi_reste_etude(self):
        self.assertEqual(normaliser_mode("etude", PROMPT_WHATSAPP), "etude")
        self.assertEqual(normaliser_mode("étude", "je prepare mon examen du BEPC"), "etude")

    def test_mode_examen_choisi_reste_examen(self):
        self.assertEqual(normaliser_mode("examen", "explique-moi le cours"), "examen")

    def test_sans_mode_les_mots_cles_decident(self):
        self.assertEqual(normaliser_mode(None, "mets-moi en mode examen"), "examen")
        self.assertEqual(normaliser_mode("", "explique le present perfect"), "etude")


if __name__ == "__main__":
    unittest.main()
