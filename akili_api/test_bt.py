"""BT = BAC Technique (9 oct. 2026) : les documents BT sont rattaches aux series B, G1, G2, E et F ;
« 1re, 2e, 3e annee » et « 1BT, 2BT, 3BT » designent la Seconde, la Premiere et la Terminale."""
import ast
import re
import unicodedata
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
NOMS = {"serie_match", "annee_bt_demandee", "normaliser_libelle_classe", "niveau_demande",
        "CLASSES_CONNUES", "progression_de_reference"}
ns = {"re": re, "unicodedata": unicodedata}
noeuds = [n for n in ast.parse(SOURCE).body
          if (isinstance(n, ast.FunctionDef) and n.name in NOMS)
          or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in NOMS for t in n.targets))]
exec(compile(ast.Module(body=noeuds, type_ignores=[]), "main.py", "exec"), ns)


def prog(serie, niveau, texte, priorite=0):
    return {"type_doc": "PROGRESSION_ANNUELLE", "matiere": "ECO", "examen": "BAC_TECHNIQUE",
            "serie": serie, "niveau": niveau, "texte": texte, "priorite": priorite}


class BTTests(unittest.TestCase):
    def test_series_des_documents_bt(self):
        match = ns["serie_match"]
        for serie in ("E", "F1", "F2", "F3", "F4", "F7"):
            self.assertTrue(match("E F1 F2 F3 F4 F7", serie), serie)   # maths BT industriel
            self.assertFalse(match("B G1 G2", serie), serie)
        for serie in ("B", "G1", "G2"):
            self.assertTrue(match("B G1 G2", serie), serie)            # maths BT tertiaire
            self.assertFalse(match("E F1 F2 F3 F4 F7", serie), serie)
        self.assertTrue(match("G1 G2", "G2"))
        self.assertFalse(match("G1 G2", "B"))

    def test_annee_citee(self):
        annee = ns["annee_bt_demandee"]
        self.assertEqual(annee("COURS DE 1ERE ANNEE"), "SECONDE")
        self.assertEqual(annee("PROGRAMME 3BT"), "TERMINALE")
        self.assertEqual(annee("2 BT"), "PREMIERE")
        self.assertIsNone(annee("EXERCICE DE PREMIERE"))

    def test_progression_de_l_annee_et_priorite(self):
        docs = [prog("G1 G2", "SECONDE", "1BT", priorite=-1), prog("G1G2", "SECONDE", "officielle"),
                prog("G1 G2", "PREMIERE", "2BT", priorite=-1)]
        ref = ns["progression_de_reference"]
        # A classe egale, la progression deja en place passe avant celle du BT (priorite -1).
        self.assertEqual(ref(docs, "ECO", "G2", "BAC_TECHNIQUE", "exercice", classe="SECONDE")["texte"], "officielle")
        self.assertEqual(ref(docs, "ECO", "G2", "BAC_TECHNIQUE", "cours de 2e année", classe="SECONDE")["texte"], "2BT")


if __name__ == "__main__":
    unittest.main()
