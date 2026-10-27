"""Controle qualite du 26 oct. et devoir de SVT du 24 oct. : bonne reponse des QCM presque toujours (a),
2 choix seulement apres une erreur, legendes et justifications transformees en QCM, production ecrite
redigee par Akili en mode examen."""
import ast
import json
import random
import time
import unittest
from collections import Counter
from pathlib import Path
from typing import Optional

SOURCE = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
NOMS = {"consigne_bonne_lettre", "melanger_choix", "lire_json_modele", "generer_texte_gemini", "mini_test",
        "revision_lendemain", "instructions_mode", "LETTRES_QCM", "REGLES_PEDAGOGIE", "MINI_TEST_CONSIGNES",
        "REVISION_CONSIGNES"}


class FauxModele:
    def __init__(self, reponse):
        self.reponse, self.prompts = reponse, []

    def generate_content(self, contents):
        self.prompts.append(contents[0])
        return type("R", (), {"text": self.reponse, "candidates": []})()


def charger(modele=None):
    ns = {"json": json, "time": time, "random": random, "Optional": Optional, "model": modele,
          "TooManyRequests": type("TooManyRequests", (Exception,), {}),
          "Form": lambda *a, **k: None, "app": type("A", (), {"post": staticmethod(lambda *a, **k: (lambda f: f))})()}
    noeuds = [n for n in ast.parse(SOURCE).body
              if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in NOMS)
              or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in NOMS for t in n.targets))]
    exec(compile(ast.Module(body=noeuds, type_ignores=[]), "main.py", "exec"), ns)
    return ns


class BonneLettreTests(unittest.TestCase):
    def test_lettre_imposee(self):
        ns = charger()
        self.assertIn("place la bonne réponse en (c)", ns["consigne_bonne_lettre"]("c"))
        self.assertIn("4 options (a, b, c, d)", ns["consigne_bonne_lettre"]("d"))
        self.assertIn("au moins 3 options", ns["consigne_bonne_lettre"]("a"))

    def test_lettres_reparties(self):
        ns = charger()
        random.seed(7)
        lettres = Counter(ns["consigne_bonne_lettre"]().split("bonne réponse en (")[1][0] for _ in range(400))
        self.assertEqual(set(lettres), set("abcd"))
        self.assertTrue(all(60 < k < 140 for k in lettres.values()), lettres)

    def test_regles_ajoutees_a_la_fin_du_prompt_eleve(self):
        pedagogie = SOURCE.index('system_prompt = system_prompt + "\\n\\n" + REGLES_PEDAGOGIE')
        finale = SOURCE.index('system_prompt = system_prompt + "\\n\\n" + REGLE_FINALE_UNE_QUESTION')
        lettre = SOURCE.index('system_prompt = system_prompt + "\\n" + consigne_bonne_lettre()')
        self.assertLess(pedagogie, finale)
        self.assertLess(finale, lettre)
        self.assertLess(lettre, SOURCE.index("contents = [system_prompt]"))
        self.assertIn("if not enseignant:", SOURCE[SOURCE.rindex("\n", 0, pedagogie) - 120:pedagogie])

    def test_regles_pedagogiques(self):
        regles = charger()["REGLES_PEDAGOGIE"]
        for attendu in ("ne réduis jamais le choix à 2 options", "TOUS les numéros", "Ne la transforme jamais en QCM",
                        "dessiner sur papier", "ne l'écris jamais", "c'est pas grave", "photo de sa copie",
                        "corrige CHAQUE numéro donné", "« 2 : faux, c'est … »", "ne reprends jamais une réponse de l'élève",
                        "corrige l'ancienne", "ne décrit ni ne définit la bonne réponse", "sans nommer ni définir"):
            self.assertIn(attendu, regles)

    def test_mode_examen_ne_redige_pas_et_note_la_copie(self):
        examen = charger()["instructions_mode"]("examen", "BEPC")
        self.assertIn("Ne redige JAMAIS la reponse ou la production a la place de l'eleve", examen)
        self.assertIn("UNIQUEMENT sur ce que l'eleve a ecrit sur la photo de sa copie", examen)
        self.assertNotIn("Ne redige JAMAIS", charger()["instructions_mode"]("etude", "BEPC"))


class MelangeMiniTestTests(unittest.TestCase):
    QUESTION = {"question": "Q", "a": "juste", "b": "faux 1", "c": "faux 2", "bonne": "a", "explication": "E"}

    def test_la_bonne_reponse_suit_son_texte(self):
        melange = charger()["melanger_choix"]
        for ordre in ("abc", "bca", "cab", "cba"):
            q = melange(dict(self.QUESTION), ordre)
            self.assertEqual(q[q["bonne"]], "juste")
            self.assertEqual(sorted(q[x] for x in "abc"), ["faux 1", "faux 2", "juste"])
        self.assertEqual(melange(dict(self.QUESTION), "cab")["bonne"], "b")

    def test_question_incomplete_inchangee(self):
        melange = charger()["melanger_choix"]
        q = {"question": "Q", "a": "x", "b": "y", "bonne": "a"}
        self.assertEqual(melange(dict(q)), q)

    def test_mini_test_melange_les_trois_questions(self):
        donnees = {"chapitre": "Cellule", "questions": [dict(self.QUESTION) for _ in range(3)]}
        ns = charger(FauxModele(json.dumps(donnees)))
        random.seed(3)
        places = Counter()
        for _ in range(30):
            res = ns["mini_test"](historique=json.dumps([{"role": "user", "content": "la cellule"}]),
                                  matiere="SVT", serie="D", type_examen="BAC_GENERAL", classe="",
                                  phase="debut", chapitre="", questions_precedentes="[]")
            for q in res["questions"]:
                self.assertEqual(q[q["bonne"]], "juste")
                places[q["bonne"]] += 1
        self.assertEqual(set(places), set("abc"))


class RevisionLettreTests(unittest.TestCase):
    def test_lettre_tiree_par_le_code(self):
        modele = FauxModele("Hier, tu as travaillé la cellule.\nPetit défi de 2 minutes : ...")
        ns = charger(modele)
        random.seed(1)
        for _ in range(20):
            ns["revision_lendemain"](historique=json.dumps([{"role": "user", "content": "x"}]), bilan="",
                                     matiere="SVT", serie="D", type_examen="BAC_GENERAL", classe="")
        places = {p.split("Une seule bonne reponse, placee en ")[1][0] for p in modele.prompts}
        self.assertEqual(places, set("abc"))
        self.assertNotIn("LETTRE_PLACEHOLDER", modele.prompts[0])


if __name__ == "__main__":
    unittest.main()
