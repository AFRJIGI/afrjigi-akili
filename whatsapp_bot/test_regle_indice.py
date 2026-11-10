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

    def test_indice_d_un_qcm_de_vocabulaire_ne_definit_pas_la_bonne_reponse(self):
        # Controle qualite du 10 nov. (7494) : « le titre recherche est le document financier que l'on achete
        # a la Bourse... » decrivait l'action au lieu de donner un indice.
        source = Path(main.__file__).read_text(encoding="utf-8")
        self.assertIn("l'indice ne définit PAS la bonne réponse", source)
        self.assertLess(source.index("l'indice ne définit PAS la bonne réponse"),
                        source.index("Cette règle passe avant la règle de la correction complète"))


if __name__ == "__main__":
    unittest.main()
