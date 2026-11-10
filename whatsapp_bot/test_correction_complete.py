import unittest
from pathlib import Path

import main


class CorrectionCompleteTests(unittest.TestCase):
    def test_demandes_claires(self):
        for texte in ("Je veux la correction", "Je veux  la  correction", "Je veux la correction de l'exercice seulement",
                      "Montre-moi les étapes de la solution de cet exercice.", "donne-moi la correction",
                      "la correction svp", "Corrige l'exercice", "correction", "Donne moi la solution complète"):
            self.assertTrue(main.demande_correction_complete(texte), texte)

    def test_autres_messages(self):
        for texte in ("b", "oui", "Donne-moi un indice pour cet exercice", "Corrige ma copie", "corrige mon exercice",
                      "Quelle est la correction de la question 2 ?", "Propose-moi un autre exercice sur le même chapitre.",
                      "", "Je veux la correction " + "mot " * 15):
            self.assertFalse(main.demande_correction_complete(texte), texte)

    def test_consigne_injectee_dans_les_trois_formes_de_prompt(self):
        source = Path(main.__file__).read_text(encoding="utf-8")
        self.assertEqual(source.count('f"{correction_complete_instruction}"'), 3)
        self.assertIn("Donne en UN SEUL message toutes les étapes", main.CORRECTION_COMPLETE_INSTRUCTION)


if __name__ == "__main__":
    unittest.main()
