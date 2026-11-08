"""Controle qualite du 8 nov. : un « indice » donnait la correction complete (*Reponse :*) puis un nouvel exercice."""
import unittest
from pathlib import Path

import main


class RegleIndiceTests(unittest.TestCase):
    def test_la_consigne_distingue_indice_et_correction_complete(self):
        source = Path(main.__file__).read_text(encoding="utf-8")
        self.assertIn("- INDICE : quand l'élève demande un indice", source)
        self.assertIn("ne donne JAMAIS la correction", source)
        # La regle INDICE est placee apres la regle de la correction complete : elle precise qu'elle passe avant.
        self.assertLess(source.index("- NUMEROTATION DES ETAPES"), source.index("- INDICE :"))
        self.assertIn("Cette règle passe avant la règle de la correction complète", source)


if __name__ == "__main__":
    unittest.main()
