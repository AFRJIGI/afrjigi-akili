"""Classement des progressions E et F dans les matieres du menu WhatsApp."""
import ast
import importlib.util
import json
import unittest
from pathlib import Path

ICI = Path(__file__).parent
spec = importlib.util.spec_from_file_location("inj", ICI / "injecter_progressions_techniques_e_f.py")
inj = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inj)

BOT = ast.parse((ICI / "whatsapp_bot" / "main.py").read_text(encoding="utf-8"))
MATIERES_BOT = next(
    ast.literal_eval(n.value) for n in BOT.body
    if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "MATIERES_TECHNIQUE_PAR_SERIE" for t in n.targets)
)
PLAN = inj.plan_documents(json.loads(inj.INVENTAIRE.read_text(encoding="utf-8"))["inventaire"])


class ClassementTests(unittest.TestCase):
    def test_chaque_progression_va_dans_une_matiere_du_menu_de_sa_serie(self):
        for doc in PLAN:
            codes = [code for code, _ in MATIERES_BOT[doc["serie"]]]
            self.assertIn(doc["matiere"], codes, doc["titre"])

    def test_toutes_les_series_e_et_f_sont_couvertes(self):
        self.assertEqual({d["serie"] for d in PLAN}, {"E", "F1", "F2", "F3", "F4", "F7"})
        self.assertGreaterEqual(len(PLAN), 90)
        self.assertEqual(len({d["id"] for d in PLAN}), len(PLAN))
        self.assertEqual(len({d["url"] for d in PLAN}), len(PLAN))

    def test_exemples(self):
        cas = {
            ("BAC_F1", "Progression  CMI TF1"): ("CMI", "F1", "TERMINALE"),
            ("BAC_E", "PRogression etude de fabrication 1ERE E"): ("ETUDE_FABRICATION", "E", "PREMIERE"),
            ("BAC_F4", "PROGRESSION RDM BAF4 graphe 1ère, Tle"): ("RDM", "F4", "PREMIERE_TERMINALE"),
            ("BAC_F4", "PROGRSSION TECHNO bac F4  2e, 1e, Tle"): ("TECHNO_GENIE_CIVIL", "F4", "TOUS"),
            ("BAC_F7", "Biochimie cours 1ère F7"): ("BIOCHIMIE", "F7", "PREMIERE"),
            ("BAC_F3", "TF3ESSAI"): ("MESURES_ESSAIS", "F3", "TERMINALE"),
            ("BAC_F2", "9 1  Technologie schémas"): ("TECHNO_SCHEMAS", "F2", "TOUS"),
        }
        for (categorie, titre), attendu in cas.items():
            self.assertEqual(inj.classer(categorie, titre), attendu, titre)

    def test_hors_champ_ignore(self):
        for categorie, titre in [("BAC_F1", "PROGRESSION TLE F1"), ("BAC_E", "ANGLAIS Tle E & F1 F2 F3 2024 2025"),
                                 ("BAC_F3", "TF3 EE"), ("BAC_F7", "EPS 22 23 PROGRESSION PEDAGOGIQUE")]:
            self.assertIsNone(inj.classer(categorie, titre), titre)


if __name__ == "__main__":
    unittest.main()
