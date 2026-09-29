"""Le bilan de fin de session suit le mode (etude / examen) et la source (au revoir / pause)."""
import ast
import asyncio
import json
import time
import unittest
from pathlib import Path
from typing import Optional


class FauxModele:
    def __init__(self, reponses):
        self.reponses = list(reponses)
        self.prompts = []

    def generate_content(self, contents):
        self.prompts.append(contents[0])
        r = self.reponses.pop(0)
        if isinstance(r, Exception):
            raise r
        return type("R", (), {"text": r, "candidates": []})()


class TooManyRequests(Exception):
    pass


def charger(modele):
    tree = ast.parse(Path(__file__).with_name("main.py").read_text(encoding="utf-8"))
    noms = {"BILAN_REGLES_COMMUNES", "BILAN_ETUDE", "BILAN_EXAMEN", "BILAN_INACTIVITE"}
    noeuds = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and {t.id for t in node.targets if isinstance(t, ast.Name)} & noms:
            noeuds.append(node)
        elif isinstance(node, ast.AsyncFunctionDef) and node.name == "bilan_session":
            node.decorator_list = []
            noeuds.append(node)
    ns = {"json": json, "time": time, "Optional": Optional, "Form": lambda *a, **k: None,
          "model": modele, "TooManyRequests": TooManyRequests}
    exec(compile(ast.Module(body=noeuds, type_ignores=[]), "main.py", "exec"), ns)
    return ns["bilan_session"]


HISTORIQUE = json.dumps([
    {"role": "user", "content": "Une entreprise en rachète une autre ?"},
    {"role": "assistant", "content": "A. interne B. externe C. conjointe"},
    {"role": "user", "content": "b"},
    {"role": "assistant", "content": "Oui, c'est la croissance externe."},
])


class BilanSessionTests(unittest.TestCase):
    def appeler(self, modele, **k):
        bilan = charger(modele)
        params = dict(historique=HISTORIQUE, matiere="ECO", serie="G1", type_examen="BAC_TECHNIQUE",
                      mode="etude", source="au_revoir")
        params.update(k)
        return asyncio.run(bilan(**params))

    def test_mode_etude(self):
        m = FauxModele(["Bravo pour ta séance !"])
        r = self.appeler(m)
        self.assertEqual(r["reponse"], "Bravo pour ta séance !")
        self.assertIn("MODE ETUDE", m.prompts[0])
        self.assertIn("croissance externe", m.prompts[0])
        self.assertNotIn("pause", m.prompts[0])

    def test_mode_examen_et_pause(self):
        m = FauxModele(["Fin de ton entraînement."])
        self.appeler(m, mode="examen", source="inactivite")
        self.assertIn("MODE EXAMEN", m.prompts[0])
        self.assertIn("N'invente JAMAIS une note", m.prompts[0])
        self.assertIn("Tu as fait une pause", m.prompts[0])

    def test_reessaie_sur_429(self):
        m = FauxModele([TooManyRequests("429"), "Bilan"])
        self.assertEqual(self.appeler(m)["reponse"], "Bilan")

    def test_historique_vide(self):
        self.assertIn("error", self.appeler(FauxModele([]), historique="[]"))


if __name__ == "__main__":
    unittest.main()
