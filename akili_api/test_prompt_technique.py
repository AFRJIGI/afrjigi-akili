import ast
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
NOMS = {"MATIERES_TECHNIQUES_GUIDEES", "LIBELLES_CLASSES_TECHNIQUE", "CONSIGNE_TECHNIQUE", "niveau_bac_technique"}
ns = {}
noeuds = [n for n in ast.parse(SOURCE).body
          if (isinstance(n, ast.FunctionDef) and n.name in NOMS)
          or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in NOMS for t in n.targets))]
exec(compile(ast.Module(body=noeuds, type_ignores=[]), "main.py", "exec"), ns)


class PromptTechniqueTests(unittest.TestCase):
    def test_niveau(self):
        self.assertEqual(ns["niveau_bac_technique"]("f2", "SECONDE"), "BAC Technique, série F2, classe de Seconde")
        self.assertEqual(ns["niveau_bac_technique"]("F1", ""), "BAC Technique, série F1")
        self.assertEqual(ns["niveau_bac_technique"]("", None), "BAC Technique")

    def test_matieres_guidees(self):
        guidees = ns["MATIERES_TECHNIQUES_GUIDEES"]
        self.assertEqual(guidees["MECANIQUE_APPLIQUEE"], "Mécanique appliquée")
        for code in ["MECANIQUE", "CMI", "ELECTRONIQUE", "PHYSIQUE_APPLIQUEE", "RDM"]:
            self.assertIn(code, guidees)
        for code in ["ECO", "PHILO", "COMPTA_FIN", "DROIT"]:  # ont leur propre consigne ou restent generales
            self.assertNotIn(code, guidees)

    def test_branche_guidee(self):
        self.assertIn('"SVT"] or matiere_propre in MATIERES_TECHNIQUES_GUIDEES:', SOURCE)
        self.assertIn("niveau_texte = niveau_bac_technique(serie, classe)", SOURCE)
        self.assertIn("MATIERES_TECHNIQUES_GUIDEES.get(matiere_propre) or", SOURCE)


if __name__ == "__main__":
    unittest.main()
