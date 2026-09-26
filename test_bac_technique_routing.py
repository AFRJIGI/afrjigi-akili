import ast
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).parent
WHATSAPP_MAIN = ROOT / "whatsapp_bot" / "main.py"
API_MAIN = ROOT / "akili_api" / "main.py"
FRONTEND_CONFIG = ROOT / "akili_frontend" / "examens_config.py"


def load_whatsapp_choices():
    tree = ast.parse(WHATSAPP_MAIN.read_text(encoding="utf-8"))
    assignments = {
        "BAC_GENERAL_SERIES_CHOICES",
        "BAC_TECHNIQUE_SERIES_CHOICES",
        "BAC_TECHNIQUE_SUBJECT_CHOICES",
    }
    functions = {
        "choice_key",
        "ask_serie_general",
        "ask_serie_technique",
        "ask_matiere_technique",
        "mot_cle_vers_lettre",
        "infer_type_examen",
    }
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if names & assignments:
                nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in functions:
            nodes.append(node)
    sent = []
    namespace = {
        "re": __import__("re"),
        "send_whatsapp": lambda phone, message: sent.append(message),
        "normalize_for_match": lambda value: str(value).upper().strip(),
        "detect_matiere_from_text": lambda value: "ANGLAIS" if "ANGLAIS" in str(value).upper() else None,
        "has_expr": lambda message, expression: expression in message,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(WHATSAPP_MAIN), "exec"), namespace)
    namespace["sent"] = sent
    return namespace


def load_api_routing():
    tree = ast.parse(API_MAIN.read_text(encoding="utf-8"))
    functions = {"serie_match", "normaliser_examen_requete"}
    nodes = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in functions
    ]
    namespace = {"re": __import__("re")}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(API_MAIN), "exec"), namespace)
    return namespace


def load_frontend_config():
    spec = importlib.util.spec_from_file_location("examens_config_test", FRONTEND_CONFIG)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BacTechniqueRoutingTests(unittest.TestCase):
    def test_e_is_only_in_bac_technique_and_f7_is_available(self):
        config = load_frontend_config().EXAMENS
        self.assertNotIn("E", config["BAC Général"]["series"])
        self.assertIn("E", config["BAC Technique"]["series"])
        self.assertIn("F7", config["BAC Technique"]["series"])
        self.assertIn("Anglais", config["BAC Technique"]["matieres_par_serie"]["F7"])

    def test_whatsapp_series_choices_are_distinct(self):
        ns = load_whatsapp_choices()
        self.assertEqual(
            ["B", "G1", "G2", "E", "F1", "F2", "F3", "F4", "F7"],
            list(ns["BAC_TECHNIQUE_SERIES_CHOICES"].values()),
        )
        self.assertNotIn("E", ns["BAC_GENERAL_SERIES_CHOICES"].values())
        self.assertEqual("ANGLAIS", ns["BAC_TECHNIQUE_SUBJECT_CHOICES"]["m"])

    def test_whatsapp_prompts_match_the_choices(self):
        ns = load_whatsapp_choices()
        ns["ask_serie_general"]("phone")
        general = ns["sent"].pop()
        ns["ask_serie_technique"]("phone")
        technique = ns["sent"].pop()
        ns["ask_matiere_technique"]("phone")
        subjects = ns["sent"].pop()
        self.assertNotIn("e. E", general)
        for label in ("d. E", "e. F1", "f. F2", "g. F3", "h. F4", "i. F7"):
            self.assertIn(label, technique)
        self.assertIn("m. Anglais", subjects)

    def test_text_and_numeric_answers_route_to_new_choices(self):
        ns = load_whatsapp_choices()
        self.assertEqual("m", ns["choice_key"]("m"))
        self.assertEqual("m", ns["choice_key"]("13"))
        self.assertEqual("d", ns["mot_cle_vers_lettre"]("serie_technique", "serie E", {}))
        self.assertEqual("i", ns["mot_cle_vers_lettre"]("serie_technique", "F7", {}))
        self.assertEqual(
            "m",
            ns["mot_cle_vers_lettre"](
                "matiere", "anglais", {"type_examen": "BAC_TECHNIQUE"}
            ),
        )
        self.assertEqual("BAC_TECHNIQUE", ns["infer_type_examen"]("E", ""))
        self.assertEqual("BAC_TECHNIQUE", ns["infer_type_examen"]("F7", ""))

    def test_api_routes_e_and_f7_as_bac_technique(self):
        ns = load_api_routing()
        self.assertEqual("BAC_TECHNIQUE", ns["normaliser_examen_requete"](None, "E"))
        self.assertEqual(
            "BAC_TECHNIQUE",
            ns["normaliser_examen_requete"]("BAC_GENERAL", "E"),
        )
        self.assertEqual("BAC_TECHNIQUE", ns["normaliser_examen_requete"](None, "F7"))
        self.assertTrue(ns["serie_match"]("EF1F2F3", "E"))
        self.assertTrue(ns["serie_match"]("F7", "F7"))


if __name__ == "__main__":
    unittest.main()
