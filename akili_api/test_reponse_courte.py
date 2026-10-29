"""Reponses breves de l'eleve : ni corpus ni progression, reflexion reduite ; historique non double (29 oct.)."""
import ast
import json
import unittest
from pathlib import Path

SRC = Path(__file__).with_name("main.py").read_text(encoding="utf-8")


def charger():
    tree = ast.parse(SRC)
    ns = {"json": json}
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "MOTS_NOUVELLE_DEMANDE" for t in node.targets):
            exec(compile(ast.Module([node], []), "main", "exec"), ns)
        if isinstance(node, ast.FunctionDef) and node.name == "est_reponse_courte":
            exec(compile(ast.Module([node], []), "main", "exec"), ns)
    return ns["est_reponse_courte"]


HISTO = json.dumps([{"role": "assistant", "content": "Quelle est la bonne reponse : a, b, c ou d ?"}])


class ReponseCourteTests(unittest.TestCase):
    def setUp(self):
        self.f = charger()

    def test_reponses_breves(self):
        for q in ("b", "B", "oui", "48", "x = 3", "je sais pas", "d'accord", "Explique encore"):
            self.assertTrue(self.f(q, HISTO), q)

    def test_pas_breves(self):
        self.assertFalse(self.f("b", "[]"))  # pas d'historique : premier message
        self.assertFalse(self.f("b", None))
        self.assertFalse(self.f("b", HISTO, a_un_fichier=True))
        for q in ("c'est quoi un ion ?", "exercice", "un autre exercice", "le cours", "Mon programme",
                  "Révision", "je veux un sujet de bac en maths", ""):
            self.assertFalse(self.f(q, HISTO), q)

    def test_branchement(self):
        self.assertIn("contexte_docs = [] if reponse_courte else chercher_contexte(", SRC)
        self.assertIn("progression = None if reponse_courte else progression_de_reference(", SRC)
        self.assertIn('if history and "HISTORIQUE RECENT" not in (question or ""):', SRC)
        self.assertIn('!= "ENSEIGNANT")', SRC)


class ReflexionCourteTests(unittest.TestCase):
    def test_reglage_transmis(self):
        import gemini_client
        self.assertIn("reflexion or REFLEXION", Path(gemini_client.__file__).read_text(encoding="utf-8"))
        ligne = gemini_client.ligne_consommation(None, 1.0, "m", "low")
        self.assertIn("niveau=low", ligne)
        self.assertIn("entree=0", ligne)


if __name__ == "__main__":
    unittest.main()
