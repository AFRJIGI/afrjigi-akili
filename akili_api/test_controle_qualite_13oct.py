"""Controle qualite du 13 oct. : formule d'accueil dans le bilan apres une pause, lecon demandee d'abord,
eleve frustre, meme lettre renvoyee."""
import ast
import re
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
NOMS = {"LANGAGE_ET_AUTRE_MATIERE", "BILAN_INACTIVITE", "PHRASE_PAUSE", "FORMULE_D_ACCUEIL", "nettoyer_bilan"}
ns = {"re": re}
noeuds = [n for n in ast.parse(SOURCE).body
          if (isinstance(n, ast.FunctionDef) and n.name in NOMS)
          or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in NOMS for t in n.targets))]
exec(compile(ast.Module(body=noeuds, type_ignores=[]), "main.py", "exec"), ns)


class BilanApresPauseTests(unittest.TestCase):
    def test_formule_d_accueil_retiree(self):
        texte = ns["nettoyer_bilan"]("C'est super de te remettre à la *Physique-Chimie* ! Aujourd'hui tu as vu : 1. Les forces.",
                                     "inactivite")
        self.assertTrue(texte.startswith("Tu as fait une pause, voici où tu en es."))
        self.assertNotIn("remettre", texte)
        self.assertIn("Aujourd'hui tu as vu", texte)

    def test_phrase_de_pause_pas_doublee(self):
        texte = ns["nettoyer_bilan"]("Tu as fait une pause, voici où tu en es.\nAujourd'hui tu as vu : 1. X.", "inactivite")
        self.assertEqual(texte.count("Tu as fait une pause"), 1)

    def test_bilan_d_au_revoir_inchange(self):
        texte = "Bravo, c'est super de te revoir motivé ! Aujourd'hui tu as vu : 1. X."
        self.assertEqual(ns["nettoyer_bilan"](texte, "au_revoir"), texte)
        self.assertIn("450 caracteres maximum", ns["BILAN_INACTIVITE"])


class ReglesTests(unittest.TestCase):
    def test_regles(self):
        texte = ns["LANGAGE_ET_AUTRE_MATIERE"]
        self.assertIn("LEÇON D'ABORD", texte)
        self.assertIn("ne recommence jamais une étape déjà faite", texte)
        self.assertIn("ne dis jamais que tu n'as pas reçu sa réponse", texte)
        self.assertIn("nettoyer_bilan(texte, source", SOURCE)


if __name__ == "__main__":
    unittest.main()
