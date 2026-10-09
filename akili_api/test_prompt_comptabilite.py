import ast
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
NOMS = {"MATIERES_TECHNIQUES_GUIDEES", "LIBELLES_MATIERES_API", "LIBELLES_CLASSES_GENERALES",
        "LIBELLES_CLASSES_TECHNIQUE", "LIBELLES_SERIES_BT", "LIBELLES_ANNEES_BT", "niveau_bac_technique", "niveau_enseignant",
        "MATIERES_COMPTABLES", "ETAPES_FINANCIERE", "COMPTES_SYSCOHADA", "ETAPES_COMPTABLES", "PROMPT_COMPTABILITE",
        "prompt_comptabilite", "prompt_general_guide"}
ns = {}
noeuds = [n for n in ast.parse(SOURCE).body
          if (isinstance(n, ast.FunctionDef) and n.name in NOMS)
          or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in NOMS for t in n.targets))]
exec(compile(ast.Module(body=noeuds, type_ignores=[]), "main.py", "exec"), ns)


class PromptComptabiliteTests(unittest.TestCase):
    def test_financiere_guidee(self):
        prompt = ns["prompt_comptabilite"]("COMPTA_FIN", "BAC_TECHNIQUE", "G2", "TERMINALE")
        self.assertIn("professeur de Comptabilité financière pour le BAC Technique, série G2, classe de Terminale", prompt)
        self.assertIn("tu ne fais JAMAIS l'exercice entier", prompt)
        self.assertIn("une seule étape par message", prompt)
        self.assertIn("SYSCOHADA", prompt)
        self.assertIn("(2) sens de l'écriture : UNE seule question pour toute l'écriture", prompt)
        self.assertIn("ne demande jamais compte par compte s'il augmente ou diminue", prompt)  # test du 6 oct. : trop lent
        self.assertIn("4 échanges environ", prompt)
        self.assertIn("Crédit 401 Fournisseurs : 236 000", prompt)
        # Test du 6 oct. : Akili a refuse 90 000 et calcule la TVA sur le TTC (590 000 x 18 %).
        self.assertIn("JAMAIS sur le TTC", prompt)
        self.assertIn("refais toi-même le calcul à partir des montants de l'ÉNONCÉ DE DÉPART", prompt)
        self.assertIn("sans oublier le compte de TVA", prompt)  # au 1er test, la TVA n'etait pas abordee
        self.assertIn("700 caractères au maximum", prompt)
        # Test du 6 oct. : fini sans ecriture complete, puis « un sujet de philosophie pour le BAC ? »
        self.assertIn("propose un exercice semblable de Comptabilité financière, jamais d'une autre matière", prompt)
        self.assertNotIn("PLACEHOLDER", prompt)
        self.assertNotIn("$", prompt)

    def test_comptes_de_reference(self):
        prompt = ns["prompt_comptabilite"]("COMPTA_FIN", "BAC_TECHNIQUE", "G2", "")
        self.assertIn("604 Achats stockés de matières et fournitures consommables", prompt)
        self.assertIn("605 Autres achats", prompt)
        self.assertIn("TOUTES les options, y compris les fausses", prompt)
        numeros = [c.strip().split(" ")[0] for c in ns["COMPTES_SYSCOHADA"].rstrip(".").split(";")]
        self.assertEqual(len(numeros), len(set(numeros)))
        self.assertTrue(all(n.isdigit() for n in numeros))

    def test_etapes_par_matiere(self):
        analytique = ns["prompt_comptabilite"]("COMPTA_ANALYTIQUE", "BAC_TECHNIQUE", "G2", "")
        self.assertIn("tableau de répartition des charges indirectes", analytique)
        self.assertNotIn("(4) écriture au journal", analytique)
        societes = ns["prompt_comptabilite"]("COMPTA_SOCIETES", "BAC_TECHNIQUE", "G2", "")
        self.assertIn("prime d'émission", societes)
        self.assertIn("Comptabilité des sociétés", societes)
        self.assertIn("(3) calcul des montants", ns["prompt_comptabilite"]("COMPTA", "BAC_TECHNIQUE", "B", ""))

    def test_branchement(self):
        self.assertIn("elif matiere_propre in MATIERES_COMPTABLES:", SOURCE)
        self.assertIn("system_prompt = prompt_comptabilite(matiere_propre, examen_registre, serie, classe)", SOURCE)
        self.assertNotIn("Tu es Akili, un assistant pédagogique expert en préparation au BAC africain", SOURCE)
        for code in ns["MATIERES_COMPTABLES"]:
            self.assertNotIn(code, ns["MATIERES_TECHNIQUES_GUIDEES"])  # pas de consigne atelier/chantier

    def test_general_guide(self):
        prompt = ns["prompt_general_guide"]("DROIT", "BAC_TECHNIQUE", "G1", "")
        self.assertIn("professeur de Droit en Côte d'Ivoire. Niveau de l'élève : BAC Technique, série G1.", prompt)
        self.assertIn("pas à pas", prompt)
        self.assertIn("700 caractères", prompt)
        self.assertIn("Législation", ns["prompt_general_guide"]("LEGISLATION", "BAC_TECHNIQUE", "F7", ""))
        self.assertIn("Terminale D (BAC Général)", ns["prompt_general_guide"]("EDHC", "BAC_GENERAL", "D", ""))


if __name__ == "__main__":
    unittest.main()
