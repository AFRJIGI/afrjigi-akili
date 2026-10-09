"""Endpoint /revision-lendemain : prompt construit a partir de la seance et du bilan d'hier."""
import ast
import json
import time
import unittest
from pathlib import Path
from typing import Optional

SOURCE = Path(__file__).with_name("main.py").read_text(encoding="utf-8")


class FauxModele:
    def __init__(self, reponse):
        self.reponse, self.prompts = reponse, []

    def generate_content(self, contents):
        self.prompts.append(contents[0])
        return type("R", (), {"text": self.reponse, "candidates": []})()


def charger(modele):
    ns = {"json": json, "time": time, "Optional": Optional, "model": modele,
          "TooManyRequests": type("TooManyRequests", (Exception,), {}),
          "Form": lambda *a, **k: None, "app": type("A", (), {"post": staticmethod(lambda *a, **k: (lambda f: f))})()}
    noeuds = [n for n in ast.parse(SOURCE).body
              if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in {"generer_texte_gemini", "revision_lendemain"})
              or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "REVISION_CONSIGNES" for t in n.targets))]
    exec(compile(ast.Module(body=noeuds, type_ignores=[]), "main.py", "exec"), ns)
    return ns


class RevisionTests(unittest.TestCase):
    def test_prompt_et_reponse(self):
        modele = FauxModele("Hier, tu as travaillé les vecteurs.\nPetit défi de 2 minutes : ...\nRéponds par a, b ou c.")
        ns = charger(modele)
        historique = json.dumps([{"role": "user", "content": "AB-> + BC-> ?"}, {"role": "assistant", "content": "AC->"}])
        res = ns["revision_lendemain"](historique=historique, bilan="À revoir : la relation de Chasles",
                                       matiere="Mathématiques", serie="F1", type_examen="BAC_TECHNIQUE",
                                       classe="PREMIERE")
        self.assertIn("Petit défi", res["reponse"])
        prompt = modele.prompts[0]
        self.assertIn("relation de Chasles", prompt)
        self.assertIn("BAC_TECHNIQUE F1 PREMIERE", prompt)
        self.assertIn("Ne donne jamais la bonne reponse", prompt)

    def test_historique_vide(self):
        ns = charger(FauxModele("x"))
        self.assertIn("error", ns["revision_lendemain"](historique="[]"))


if __name__ == "__main__":
    unittest.main()
