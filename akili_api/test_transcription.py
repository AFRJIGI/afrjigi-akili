"""Transcription des photos et PDF d'eleves (controle qualite du 9 oct.)."""
import ast
import pathlib
import unittest

SOURCE = (pathlib.Path(__file__).parent / "main.py").read_text(encoding="utf-8")
ns = {}
for noeud in ast.parse(SOURCE).body:
    if isinstance(noeud, ast.FunctionDef) and noeud.name == "lire_transcription":
        exec(compile(ast.Module([noeud], []), "main.py", "exec"), ns)


class LectureTests(unittest.TestCase):
    def test_matiere_et_texte(self):
        self.assertEqual(ns["lire_transcription"]("MATIERE: Histoire-Geographie\nExercice 1\n1. Complete..."),
                         ("Histoire-Geographie", "Exercice 1\n1. Complete..."))

    def test_matiere_inconnue_ou_absente(self):
        self.assertEqual(ns["lire_transcription"]("MATIERE: ?\nTexte"), ("", "Texte"))
        self.assertEqual(ns["lire_transcription"]("Texte sans ligne de matiere"), ("", "Texte sans ligne de matiere"))
        self.assertEqual(ns["lire_transcription"]("**MATIERE: SVT**\nLa cellule"), ("SVT", "La cellule"))

    def test_longueur_bornee(self):
        self.assertEqual(len(ns["lire_transcription"]("MATIERE: SVT\n" + "x" * 9000)[1]), 4000)


if __name__ == "__main__":
    unittest.main()
