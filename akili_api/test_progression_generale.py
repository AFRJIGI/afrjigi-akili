"""Progressions DPFC : bon document du cycle, partie de la classe de l'eleve, mois en cours."""
import ast
import re
import unicodedata
import unittest
from datetime import datetime, timezone
from pathlib import Path

SOURCE = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
FONCTIONS = {"serie_match", "normaliser_libelle_classe", "niveau_demande", "progression_de_reference",
             "aplatir", "classe_generale", "titres_de_classes", "section_de_classe", "fenetre_periode",
             "progression_generale", "consigne_progression"}
NOMS = {"CLASSES_GENERALES", "ALIAS_CLASSES", "MOIS_MAJ", "_SANS_ACCENT", "CLASSES_CONNUES", "MOIS_FR"}
ns = {"re": re, "unicodedata": unicodedata, "datetime": datetime, "timezone": timezone}
noeuds = [n for n in ast.parse(SOURCE).body
          if (isinstance(n, ast.FunctionDef) and n.name in FONCTIONS)
          or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in NOMS for t in n.targets))]
exec(compile(ast.Module(body=noeuds, type_ignores=[]), "main.py", "exec"), ns)

OCT = datetime(2026, 10, 3, tzinfo=timezone.utc)


def doc(i, matiere, niveau, texte):
    return {"id": i, "type_doc": "PROGRESSION_ANNUELLE", "matiere": matiere, "examen": "TOUS",
            "serie": "TOUTES", "niveau": niveau, "texte": texte}


MATHS = doc("maths", "MATHS", "TOUS_CYCLES",
            "**Classe: 6ème**\nSEPTEMBRE nombres entiers\n**Classe: 3ème**\nSEPTEMBRE calcul littéral\nOCTOBRE Thalès\n"
            "**Classe: Terminale C**\nlimites C\n**Classe: Terminale D**\nlimites et continuité D\n")
EDHC = doc("edhc", "EDHC", "TOUS_CYCLES",
           "PROGRESSIONS ANNUELLES EDHC\n**CLASSES DE 6º**\nSeptembre : prise de contact\n**TROISIEME TRIMESTRE**\nleçon 6e fin\n"
           "**CLASSES DE 3º**\nSeptembre : la citoyenneté\n")
FR_ADMIN = doc("fr_admin", "FRENCH", "1ER_CYCLE_ADMIN", "**Classe: SIXIÈME**\nconte\n**Classe: TROISIÈME**\nadmin 3e\n")
FR_PEDAGO = doc("fr_pedago", "FRENCH", "1ER_CYCLE_PEDAGO", "**Classe: Sixième**\nséance conte 6e\n**TROISIEME (3e)**\nséance dialogue argumentatif 3e\n")
ANGLAIS2 = doc("ang2", "ANGLAIS", "2ND_CYCLE",
               "**Progression Nationale-Secondes A et C**\nunit 1 people\n**PROGRESSION PREMIERES A**\nunit A\n**PROGRESSION PREMIERES C et D**\nunit CD\n")
MATHS_A = doc("mathsA", "MATHS", "TOUS_CYCLES",
              "**Classe: 1ère A1**\npremiere A1\n**Classe: 1ère A2**\npremiere A2\n**Classe: 1ère C**\npremiere C\n"
              "**Classe: Terminale A1**\nterminale A1\n**Classe: Terminale A2**\nterminale A2\n")
HG = doc("hg", "HG", "TOUS_CYCLES",
         "**Progression Annuelle d'HISTOIRE - Terminale**\nhistoire terminale\n"
         "**Progression Annuelle de GEOGRAPHIE - Terminale**\ngeographie terminale\n")
PHILO = doc("philo", "PHILO", "2ND_CYCLE", "**CLASSES: PREMIERES A1-A2**\nla philosophie\n**CLASSES: TERMINALES A**\nla conscience\n")
DOCS = [MATHS, EDHC, FR_ADMIN, FR_PEDAGO, ANGLAIS2, PHILO, HG]


def prog(matiere, serie, examen):
    return ns["progression_de_reference"](DOCS, matiere, serie, examen, "Propose-moi un exercice")


class ProgressionGeneraleTests(unittest.TestCase):
    def test_bepc_partie_troisieme(self):
        p = prog("MATHS", "BEPC", "BEPC")
        self.assertIn("Thalès", p["texte"])
        self.assertNotIn("nombres entiers", p["texte"])
        self.assertEqual(p["classe_eleve"], "3e")

    def test_trimestre_n_est_pas_une_classe(self):
        p = prog("EDHC", "BEPC", "BEPC")
        self.assertIn("citoyenneté", p["texte"])
        self.assertNotIn("leçon 6e fin", p["texte"])
        self.assertIn("leçon 6e fin", prog("EDHC", "6E", "CLASSE_INTERMEDIAIRE")["texte"])

    def test_francais_version_pedagogique(self):
        p = prog("FRENCH", "BEPC", "BEPC")
        self.assertEqual(p["id"], "fr_pedago")
        self.assertIn("dialogue argumentatif", p["texte"])

    def test_terminale_et_series(self):
        self.assertIn("continuité D", prog("MATHS", "D", "BAC_GENERAL")["texte"])
        self.assertNotIn("limites C", prog("MATHS", "D", "BAC_GENERAL")["texte"])
        self.assertIn("unit CD", prog("ANGLAIS", "PREMIERE_C", "CLASSE_INTERMEDIAIRE")["texte"])
        self.assertIn("unit 1 people", prog("ANGLAIS", "SECONDE_A", "CLASSE_INTERMEDIAIRE")["texte"])
        self.assertIn("la conscience", prog("PHILO", "A2", "BAC_GENERAL")["texte"])

    def test_series_a1_a2_et_apostrophe(self):
        docs = [MATHS_A]
        ref = lambda serie, examen: ns["progression_de_reference"](docs, "MATHS", serie, examen)["texte"]
        self.assertIn("terminale A2", ref("A2", "BAC_GENERAL"))
        self.assertNotIn("terminale A1", ref("A2", "BAC_GENERAL"))
        self.assertIn("premiere A1", ref("PREMIERE_A", "CLASSE_INTERMEDIAIRE"))
        self.assertNotIn("premiere C", ref("PREMIERE_A", "CLASSE_INTERMEDIAIRE"))
        hg = prog("HG", "D", "BAC_GENERAL")["texte"]  # "D'HISTOIRE" n'est pas la serie D
        self.assertIn("histoire terminale", hg)
        self.assertIn("geographie terminale", hg)

    def test_titre_de_plusieurs_classes_et_serie_absente(self):
        eps = doc("eps", "EPS", "1ER_CYCLE", "**SIXIEME - CINQUIEME**\nbasket 6e 5e\n**Classe de Quatrième / Troisième**\nathletisme 4e 3e\n")
        pc = doc("pc", "PC", "TOUS_CYCLES", "**Classe: TERMINALE C**\nmecanique C\n**Classe: TERMINALE D**\noptique D\n")
        ref = lambda docs, m, serie, examen: ns["progression_de_reference"](docs, m, serie, examen)
        self.assertIn("athletisme", ref([eps], "EPS", "BEPC", "BEPC")["texte"])
        self.assertIn("basket", ref([eps], "EPS", "5E", "CLASSE_INTERMEDIAIRE")["texte"])
        self.assertIsNone(ref([pc], "PC", "A2", "BAC_GENERAL"))  # pas de PC en Terminale A dans ce document
        self.assertIn("optique D", ref([pc], "PC", "D", "BAC_GENERAL")["texte"])

    def test_jamais_la_progression_d_une_autre_classe(self):
        self.assertIsNone(prog("PHILO", "BEPC", "BEPC"))  # pas de philo au premier cycle
        self.assertIsNone(prog("ANGLAIS", "BEPC", "BEPC"))  # seul le 2nd cycle est dans DOCS

    def test_fenetre_du_mois(self):
        texte = "SEPTEMBRE " + "x" * 9000 + " OCTOBRE leçon du mois " + "y" * 9000
        fenetre = ns["fenetre_periode"](texte, OCT, max_chars=7000)
        self.assertIn("OCTOBRE leçon du mois", fenetre)
        self.assertEqual(len(fenetre), 7000)
        self.assertEqual(ns["fenetre_periode"]("court", OCT), "court")

    def test_consigne_nomme_la_classe(self):
        texte = ns["consigne_progression"](dict(prog("MATHS", "BEPC", "BEPC"), institution="DPFC"), OCT)
        self.assertIn("progression DPFC de cette matiere (3e)", texte)


if __name__ == "__main__":
    unittest.main()
