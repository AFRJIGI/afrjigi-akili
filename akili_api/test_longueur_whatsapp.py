import ast
import re
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
NOMS = {"LONGUEUR_WHATSAPP", "LANGAGE_ET_AUTRE_MATIERE", "vient_de_whatsapp"}
ns = {"re": re}
noeuds = [n for n in ast.parse(SOURCE).body
          if (isinstance(n, ast.FunctionDef) and n.name in NOMS)
          or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in NOMS for t in n.targets))]
exec(compile(ast.Module(body=noeuds, type_ignores=[]), "main.py", "exec"), ns)


class LongueurWhatsappTests(unittest.TestCase):
    def test_canal(self):
        self.assertTrue(ns["vient_de_whatsapp"]("2250700000000@afrjigi.com"))
        self.assertTrue(ns["vient_de_whatsapp"](" 13154030671@afrjigi.com "))
        self.assertFalse(ns["vient_de_whatsapp"]("ddiarrassouba@afrjigi.com"))
        self.assertFalse(ns["vient_de_whatsapp"]("eleve@gmail.com"))

    def test_consigne(self):
        self.assertIn("700 caractères au maximum", ns["LONGUEUR_WHATSAPP"])
        self.assertIn("une seule notion du sujet", ns["LONGUEUR_WHATSAPP"])
        # ajoutee pour les eleves seulement, apres les instructions de mode
        debut = SOURCE.index("if not enseignant:\n            system_prompt = system_prompt + \"\\n\\n\" + instructions_mode")
        self.assertIn("if vient_de_whatsapp(clean_email):", SOURCE[debut:debut + 400])

    def test_langage_et_autre_matiere(self):
        texte = ns["LANGAGE_ET_AUTRE_MATIERE"]
        self.assertIn("nouchi", texte)
        self.assertIn("français scolaire simple", texte)
        self.assertIn("ne refuse jamais", texte)
        self.assertIn("LANGAGE_ET_AUTRE_MATIERE + \"\\n\\n\" + LONGUEUR_WHATSAPP", SOURCE)


if __name__ == "__main__":
    unittest.main()
