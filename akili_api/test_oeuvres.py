"""21 oct. : liste nationale des oeuvres litteraires agreees 2026-2027 (circulaire n° 3272 du 21 sept. 2026)."""
import unittest
from pathlib import Path

import oeuvres

SOURCE = Path(__file__).with_name("main.py").read_text(encoding="utf-8")


class OeuvresTests(unittest.TestCase):
    def test_nombre_d_oeuvres_par_classe_comme_la_circulaire(self):
        attendu = {"6E": (21, 2), "5E": (16, 2), "4E": (22, 2), "3E": (15, 2), "SECONDE": (18, 2),
                   "PREMIERE": (11, 1), "TERMINALE": (7, 5)}
        niveaux = oeuvres.DONNEES["niveaux"]
        self.assertEqual({k: (len(v["auteurs_africains"]), len(v["autres_auteurs"])) for k, v in niveaux.items()},
                         attendu)

    def test_terminale(self):
        bloc = oeuvres.consigne_oeuvres("TERMINALE")
        for titre in ["L'aventure ambiguë (A. H. KANE)", "L'étranger (Albert CAMUS)", "Les Soleils des indépendances"]:
            self.assertIn(titre, bloc)
        self.assertNotIn("Germinal", bloc)  # sur les fiches d'une chaine WhatsApp, pas sur la liste
        self.assertIn("ne figure pas sur la liste officielle 2026-2027", bloc)
        self.assertIn("N'invente jamais", bloc)

    def test_3e_et_seconde(self):
        self.assertIn("Une si longue lettre (Mariama Bâ)", oeuvres.consigne_oeuvres("3E"))
        self.assertIn("Le Monde s'effondre (Chinua ACHEBE)", oeuvres.consigne_oeuvres("SECONDE"))

    def test_classe_inconnue_ou_technique(self):
        self.assertEqual(oeuvres.consigne_oeuvres(None), "")
        self.assertEqual(oeuvres.consigne_oeuvres("F2"), "")

    def test_enseignant(self):
        bloc = oeuvres.consigne_oeuvres("PREMIERE", enseignant=True)
        self.assertIn("Antigone (J. ANOUILH)", bloc)
        self.assertIn("propose uniquement des œuvres de cette liste", bloc)
        self.assertNotIn("l'élève", bloc)

    def test_branche_dans_le_prompt_de_francais_avant_la_regle_finale(self):
        francais = SOURCE.index('system_prompt = system_prompt + "\\n\\n" + FRENCH_PEDAGOGY_GUIDANCE')
        bloc = SOURCE.index("bloc_oeuvres = consigne_oeuvres(")
        regle = SOURCE.index('system_prompt = system_prompt + "\\n\\n" + REGLE_FINALE_UNE_QUESTION')
        self.assertLess(francais, bloc)
        self.assertLess(bloc, regle)
        self.assertIn('if examen_registre != "BAC_TECHNIQUE"', SOURCE[francais:bloc + 200])


if __name__ == "__main__":
    unittest.main()
