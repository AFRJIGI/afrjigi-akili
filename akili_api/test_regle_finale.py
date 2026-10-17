"""17 oct. : une seule question par message, rappelee a la toute fin du prompt (eleves seulement)."""
import pathlib
import unittest

SOURCE = (pathlib.Path(__file__).parent / "main.py").read_text(encoding="utf-8")


class RegleFinaleTests(unittest.TestCase):
    def test_regle_definie(self):
        self.assertIn("REGLE_FINALE_UNE_QUESTION = (", SOURCE)
        self.assertIn("AU PLUS UNE seule", SOURCE)

    def test_ajoutee_apres_la_progression_et_pas_pour_les_enseignants(self):
        progression = SOURCE.index("system_prompt = system_prompt + \"\\n\\n\" + consigne(progression)")
        regle = SOURCE.index("system_prompt = system_prompt + \"\\n\\n\" + REGLE_FINALE_UNE_QUESTION")
        self.assertLess(progression, regle)
        self.assertIn("if not enseignant:", SOURCE[progression:regle])
        contenus = SOURCE.index("contents = [system_prompt]")
        self.assertLess(regle, contenus)


if __name__ == "__main__":
    unittest.main()
