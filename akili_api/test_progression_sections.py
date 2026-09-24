import ast
import re
import unittest
import unicodedata
from pathlib import Path


def load_helpers():
    source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    wanted = {
        "normaliser_libelle_classe",
        "extraire_section_progression",
        "formater_contexte_document",
    }
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    namespace = {"re": re, "unicodedata": unicodedata}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "main.py", "exec"), namespace)
    return namespace


HELPERS = load_helpers()
extraire_section_progression = HELPERS["extraire_section_progression"]
formater_contexte_document = HELPERS["formater_contexte_document"]


class ProgressionSectionTests(unittest.TestCase):
    def setUp(self):
        self.doc = {
            "id": "dpfc_progression_2026_2027_mathematiques",
            "nom_fichier": "DPFC_2026-2027_MATHEMATIQUES.pdf",
            "source": "DPFC_OFFICIEL",
            "version": "2026-2027",
            "matiere": "MATHS",
            "type_doc": "PROGRESSION_ANNUELLE",
            "texte": (
                "**Classe: 6ème**\nContenu sixieme.\n"
                "**Classe: 1ère D**\nContenu premiere D.\n"
                "**Classe: Terminale D**\nContenu terminale D.\n"
            ),
        }

    def test_series_d_excludes_sixieme_and_selects_lycee_sections(self):
        result = extraire_section_progression(self.doc, "Quels themes sont prevus ?", "D")
        self.assertNotIn("sixieme", result)
        self.assertIn("premiere D", result)
        self.assertIn("terminale D", result)

    def test_explicit_class_selects_only_that_class(self):
        result = extraire_section_progression(self.doc, "Progression de Terminale D", "D")
        self.assertNotIn("premiere D", result)
        self.assertIn("terminale D", result)

    def test_formatted_context_identifies_versioned_source(self):
        result = formater_contexte_document(self.doc, "Progression de Terminale D", "D")
        self.assertIn("SOURCE: DPFC_2026-2027_MATHEMATIQUES.pdf", result)
        self.assertIn("ORIGINE: DPFC_OFFICIEL", result)
        self.assertIn("ANNEE/VERSION: 2026-2027", result)


if __name__ == "__main__":
    unittest.main()
