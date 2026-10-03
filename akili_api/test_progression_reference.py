"""Pour le BAC Technique, la progression officielle de la matiere, de la serie et de la
classe est ajoutee au contexte meme quand la question ne la cite pas."""
import ast
import re
import unicodedata
import unittest
from datetime import datetime, timezone
from pathlib import Path

SOURCE = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
VOULUES = {"serie_match", "normaliser_libelle_classe", "niveau_demande",
           "progression_de_reference", "consigne_progression"}
NOMS = {"MOIS_FR", "CLASSES_CONNUES", "CLASSES_GENERALES", "ALIAS_CLASSES", "MOIS_MAJ", "_SANS_ACCENT"}
VOULUES |= {"progression_generale", "classe_generale", "titres_de_classes", "section_de_classe", "aplatir"}
ns = {"re": re, "unicodedata": unicodedata, "datetime": datetime, "timezone": timezone}
noeuds = [n for n in ast.parse(SOURCE).body
          if (isinstance(n, ast.FunctionDef) and n.name in VOULUES)
          or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in NOMS for t in n.targets))]
exec(compile(ast.Module(body=noeuds, type_ignores=[]), "main.py", "exec"), ns)


def prog(doc_id, matiere, serie, niveau, texte="x" * 500):
    return {"id": doc_id, "type_doc": "PROGRESSION_ANNUELLE", "matiere": matiere, "serie": serie,
            "examen": "BAC_TECHNIQUE", "niveau": niveau, "texte": texte}


DOCS = [
    prog("cmi_tf1", "CMI", "F1", "TERMINALE"),
    prog("cmi_1f1", "CMI", "F1", "PREMIERE"),
    prog("cmi_2t1", "CMI", "EF1F3", "SECONDE"),
    prog("cmi_tf3", "CMI", "F3", "TERMINALE"),
    prog("rdm_f4", "RDM", "F4", "PREMIERE_TERMINALE"),
    prog("labo_f4", "LABO_MATERIAUX", "F4", "TOUS"),
    prog("info_f2", "INFORMATIQUE_INDUSTRIELLE", "F2", "SECONDE"),
    {"id": "cours_cmi", "type_doc": "COURS", "matiere": "CMI", "serie": "F1", "examen": "BAC_TECHNIQUE"},
]


class ProgressionReferenceTests(unittest.TestCase):
    def ref(self, matiere, serie, question="Propose-moi un exercice"):
        doc = ns["progression_de_reference"](DOCS, matiere, serie, "BAC_TECHNIQUE", question)
        return doc and doc["id"]

    def test_terminale_par_defaut(self):
        self.assertEqual(self.ref("CMI", "F1"), "cmi_tf1")
        self.assertEqual(self.ref("CMI", "F3"), "cmi_tf3")

    def test_classe_citee_par_l_eleve(self):
        self.assertEqual(self.ref("CMI", "F1", "je suis en premiere, un exercice"), "cmi_1f1")
        self.assertEqual(self.ref("CMI", "F3", "exercice de seconde"), "cmi_2t1")

    def test_classe_du_profil(self):
        ref = lambda question, classe: ns["progression_de_reference"](DOCS, "CMI", "F1", "BAC_TECHNIQUE", question, classe=classe)["id"]
        self.assertEqual(ref("Propose-moi un exercice", "PREMIERE"), "cmi_1f1")
        self.assertEqual(ref("Propose-moi un exercice", "SECONDE"), "cmi_2t1")
        self.assertEqual(ref("un exercice de terminale", "PREMIERE"), "cmi_tf1")
        self.assertEqual(ref("exercice de seconde", "PREMIERE"), "cmi_2t1")  # la question l'emporte
        self.assertEqual(ref("Propose-moi un exercice", None), "cmi_tf1")

    def test_progressions_multi_classes(self):
        self.assertEqual(self.ref("RDM", "F4"), "rdm_f4")
        self.assertEqual(self.ref("LABO_MATERIAUX", "F4"), "labo_f4")

    def test_pas_de_progression_d_une_autre_classe_ou_serie(self):
        self.assertIsNone(self.ref("INFORMATIQUE_INDUSTRIELLE", "F2"))  # seconde seulement
        self.assertIsNone(self.ref("CMI", "F4"))
        self.assertIsNone(ns["progression_de_reference"](DOCS, "CMI", "F1", "BAC_GENERAL"))

    def test_consigne(self):
        texte = ns["consigne_progression"](DOCS[0], datetime(2026, 10, 2, tzinfo=timezone.utc))
        self.assertIn("2 octobre 2026", texte)
        self.assertIn("(terminale)", texte)
        self.assertIn("periode actuelle", texte)


if __name__ == "__main__":
    unittest.main()
