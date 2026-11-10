import ast
import os
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
NOMS = {"MARQUEUR_FIN_CONSIGNES_FIXES", "ORDRE_CACHE", "separer_consignes_fixes"}
ns = {"os": os}
noeuds = [n for n in ast.parse(SOURCE).body
          if (isinstance(n, ast.FunctionDef) and n.name in NOMS)
          or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in NOMS for t in n.targets))]
exec(compile(ast.Module(body=noeuds, type_ignores=[]), "main.py", "exec"), ns)
M = ns["MARQUEUR_FIN_CONSIGNES_FIXES"]
separer = ns["separer_consignes_fixes"]
QUESTION = f"REGLES FIXES\n{M}\nGARDE-FOU\nHISTORIQUE RECENT:\nx\n\nQUESTION REELLE DE L'ELEVE:\nb"


class OrdreCacheTests(unittest.TestCase):
    def test_sans_marqueur_rien_ne_change(self):
        self.assertEqual(separer("bonjour", True), ("", "bonjour"))
        self.assertEqual(separer(None, False), ("", ""))

    def test_inactif_rend_exactement_le_texte_d_avant(self):
        fixes, reste = separer(QUESTION, False)
        self.assertEqual(fixes, "")
        self.assertEqual(reste, "REGLES FIXES\nGARDE-FOU\nHISTORIQUE RECENT:\nx\n\nQUESTION REELLE DE L'ELEVE:\nb")
        self.assertNotIn(M, reste)

    def test_actif_place_les_consignes_fixes_a_part(self):
        fixes, reste = separer(QUESTION, True)
        self.assertEqual(fixes, "REGLES FIXES\n\n")
        self.assertTrue(reste.startswith("GARDE-FOU"))
        self.assertNotIn(M, fixes + reste)
        # Rien ne se perd : les deux morceaux contiennent tout le texte d'origine.
        self.assertEqual((fixes + reste).replace("\n", ""), QUESTION.replace(M, "").replace("\n", ""))

    def test_defaut_inactif(self):
        self.assertIn('os.environ.get("AKILI_ORDRE_CACHE", "0")', SOURCE)

    def test_marqueur_identique_dans_le_bot(self):
        bot = Path(__file__).parent.parent.joinpath("whatsapp_bot", "main.py").read_text(encoding="utf-8")
        self.assertIn(f'MARQUEUR_FIN_CONSIGNES_FIXES = "{M}"', bot)
        self.assertEqual(bot.count('f"{instructions_whatsapp}\\n{MARQUEUR_FIN_CONSIGNES_FIXES}\\n"'), 3)


if __name__ == "__main__":
    unittest.main()
