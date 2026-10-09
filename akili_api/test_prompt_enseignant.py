import ast
import unittest
from datetime import datetime, timezone
from pathlib import Path

SOURCE = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
NOMS = {"MATIERES_TECHNIQUES_GUIDEES", "LIBELLES_MATIERES_API", "LIBELLES_CLASSES_GENERALES",
        "LIBELLES_CLASSES_TECHNIQUE", "MOIS_FR", "niveau_bac_technique", "niveau_enseignant",
        "prompt_enseignant", "consigne_progression_enseignant"}
ns = {"datetime": datetime, "timezone": timezone}
noeuds = [n for n in ast.parse(SOURCE).body
          if (isinstance(n, ast.FunctionDef) and n.name in NOMS)
          or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in NOMS for t in n.targets))]
exec(compile(ast.Module(body=noeuds, type_ignores=[]), "main.py", "exec"), ns)


class PromptEnseignantTests(unittest.TestCase):
    def test_prompt(self):
        prompt = ns["prompt_enseignant"]("MECANIQUE_APPLIQUEE", "BAC_TECHNIQUE", "F2", "SECONDE")
        self.assertIn("enseignant de Mécanique appliquée (BAC Technique, série F2, classe de Seconde)", prompt)
        self.assertIn("vouvoie-le", prompt)
        self.assertIn("corrigés complets", prompt)
        self.assertNotIn("ne résous JAMAIS", prompt)
        self.assertIn("Terminale D (BAC Général)", ns["prompt_enseignant"]("MATHS", "BAC_GENERAL", "D", ""))
        self.assertIn("Première C", ns["prompt_enseignant"]("PC", "CLASSE_INTERMEDIAIRE", "PREMIERE_C", ""))
        self.assertIn("3e (BEPC)", ns["prompt_enseignant"]("FRANCAIS", "BEPC", "BEPC", ""))

    def test_progression(self):
        texte = ns["consigne_progression_enseignant"]({}, datetime(2026, 10, 5, tzinfo=timezone.utc))
        self.assertIn("5 octobre 2026", texte)
        self.assertNotIn("l'eleve", texte)

    def test_branchement(self):
        self.assertIn('user_type: Optional[str] = Form(None),', SOURCE)
        self.assertIn('enseignant = (user_type or "").strip().upper() == "ENSEIGNANT"', SOURCE)
        self.assertIn("system_prompt = prompt_enseignant(matiere_propre, examen_registre, serie, classe)", SOURCE)
        self.assertIn("if not enseignant:\n            system_prompt = system_prompt + \"\\n\\n\" + instructions_mode", SOURCE)


if __name__ == "__main__":
    unittest.main()
