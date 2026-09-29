import ast
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("injecter_progressions_metfpa_bac_technique_2026_2027.py")


def load_constants_and_helpers():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    wanted_assignments = {"VERSION", "DOCUMENTS", "FOLDER_URL"}
    wanted_functions = {"source_url", "document_id", "filename"}
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if names & wanted_assignments:
                nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in wanted_functions:
            nodes.append(node)
    namespace = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SCRIPT), "exec"), namespace)
    return namespace


NS = load_constants_and_helpers()


class MetfpaManifestTests(unittest.TestCase):
    def test_manifest_has_18_unique_documents(self):
        documents = NS["DOCUMENTS"]
        ids = [NS["document_id"](*item[:3]) for item in documents]
        urls = [NS["source_url"](item[3]) for item in documents]
        self.assertEqual(18, len(documents))
        self.assertEqual(18, len(set(ids)))
        self.assertEqual(18, len(set(urls)))

    def test_manifest_covers_tertiary_and_industrial_series(self):
        series = "".join(item[2] for item in NS["DOCUMENTS"])
        for expected in ["B", "G1", "G2", "E", "F1", "F2", "F3", "F4", "F7"]:
            self.assertIn(expected, series)

    def test_metadata_names_are_versioned_pdf_files(self):
        for discipline, niveau, serie, _ in NS["DOCUMENTS"]:
            name = NS["filename"](discipline, niveau, serie)
            self.assertTrue(name.startswith("METFPA_2026-2027_"))
            self.assertTrue(name.endswith(".pdf"))


if __name__ == "__main__":
    unittest.main()
