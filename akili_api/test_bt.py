"""BT (Brevet de Technicien) dans le BAC Technique : documents, libelles et annee (9 oct. 2026)."""
import ast
import re
import unicodedata
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
NOMS = {"serie_match", "LIBELLES_SERIES_BT", "LIBELLES_ANNEES_BT", "LIBELLES_CLASSES_TECHNIQUE",
        "niveau_bac_technique", "annee_bt_demandee", "normaliser_libelle_classe", "niveau_demande",
        "CLASSES_CONNUES", "progression_de_reference", "normaliser_examen_requete"}
ns = {"re": re, "unicodedata": unicodedata}
noeuds = [n for n in ast.parse(SOURCE).body
          if (isinstance(n, ast.FunctionDef) and n.name in NOMS)
          or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in NOMS for t in n.targets))]
exec(compile(ast.Module(body=noeuds, type_ignores=[]), "main.py", "exec"), ns)


def prog(serie, niveau, texte):
    return {"type_doc": "PROGRESSION_ANNUELLE", "matiere": "TELEPHONIE", "examen": "BAC_TECHNIQUE",
            "serie": serie, "niveau": niveau, "texte": texte}


class BTTests(unittest.TestCase):
    def test_documents_bt_reserves_aux_options_bt(self):
        match = ns["serie_match"]
        self.assertTrue(match("BT_ELN", "BT_ELN"))
        self.assertTrue(match("BT_ELN BT_IND", "BT_IND"))
        self.assertFalse(match("BT_ELN BT_IND", "BT_TER"))
        self.assertTrue(match("TOUTES", "BT_TER"))
        self.assertFalse(match("F2", "BT_ELN"))
        # « BT_IND » contient un D, « BT_ELN » un E, « BT_TER » un T : pas pour les series D, E, B.
        for serie in ("D", "E", "B", "G1", "F2", "C"):
            self.assertFalse(match("BT_ELN BT_IND BT_TER", serie), serie)
        self.assertTrue(match("G1G2", "G1"))  # inchange

    def test_libelles(self):
        niveau = ns["niveau_bac_technique"]
        self.assertEqual(niveau("BT_ELN", "TERMINALE"), "BT Électronique (Brevet de Technicien), 3e année")
        self.assertEqual(niveau("BT_TER", ""), "BT Tertiaire (Brevet de Technicien)")
        self.assertEqual(niveau("F2", "SECONDE"), "BAC Technique, série F2, classe de Seconde")
        self.assertEqual(ns["normaliser_examen_requete"]("", "BT_IND"), "BAC_TECHNIQUE")

    def test_progression_de_l_annee(self):
        docs = [prog("BT_ELN", "SECONDE", "1A"), prog("BT_ELN", "PREMIERE", "2A"), prog("BT_ELN", "TERMINALE", "3A")]
        ref = ns["progression_de_reference"]
        self.assertEqual(ref(docs, "TELEPHONIE", "BT_ELN", "BAC_TECHNIQUE", "exercice", classe="PREMIERE")["texte"], "2A")
        # L'annee citee l'emporte ; « 1ere annee » n'est pas la Premiere (2e annee) pour un eleve de BT.
        self.assertEqual(ref(docs, "TELEPHONIE", "BT_ELN", "BAC_TECHNIQUE", "cours de 1ère année", classe="TERMINALE")["texte"], "1A")
        self.assertEqual(ref(docs, "TELEPHONIE", "BT_ELN", "BAC_TECHNIQUE", "programme 3BT", classe="SECONDE")["texte"], "3A")
        self.assertIsNone(ref(docs, "TELEPHONIE", "F2", "BAC_TECHNIQUE", "exercice", classe="SECONDE"))


if __name__ == "__main__":
    unittest.main()
