"""Controle qualite du 29 oct. : notes internes envoyees a l'eleve, options de QCM retirees ou remelangees
apres une erreur, eleve qui ne comprend rien, paragraphe de philosophie redige par Akili."""
import ast
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name("main.py").read_text(encoding="utf-8")


def charger():
    noms = {"MARQUEURS_FUITE_FORTS", "MARQUEURS_FUITE_FAIBLES", "fuite_de_consignes", "REGLES_PEDAGOGIE",
            "consigne_bonne_lettre", "LETTRES_QCM"}
    ns = {"random": __import__("random")}
    noeuds = [n for n in ast.parse(SOURCE).body
              if (isinstance(n, ast.FunctionDef) and n.name in noms)
              or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in noms for t in n.targets))]
    exec(compile(ast.Module(body=noeuds, type_ignores=[]), "main.py", "exec"), ns)
    return ns


FUITE = ("L'élève n'a pas choisi une lettre parmi les options proposées (a, b ou c). Je dois lui demander de "
         "choisir. Consignes à respecter : • Ne pas choisir à sa place. • Ne pas mettre de LaTeX. • Répondre en "
         "texte simple WhatsApp. • Une seule question à la fin. • Moins de 700 caractères.")


class FuiteTests(unittest.TestCase):
    def setUp(self):
        self.ns = charger()

    def test_notes_internes_detectees(self):
        self.assertTrue(self.ns["fuite_de_consignes"](FUITE))
        self.assertTrue(self.ns["fuite_de_consignes"]("Consignes à respecter : une seule question."))

    def test_messages_normaux_acceptes(self):
        for texte in ("Bonne réponse ! √18 = 3√2. Quelle est la forme simplifiée de √50 ?",
                      "Pas tout à fait. Indice : la force dépend du champ E->. Quelle lettre choisis-tu : a, b, c ou d ?",
                      "Je dois t'expliquer une chose : le vecteur AB-> se lit « vecteur AB ». Tu me suis ?",
                      ""):
            self.assertFalse(self.ns["fuite_de_consignes"](texte), texte)

    def test_nouvelle_generation_branchee(self):
        self.assertIn("fuite_de_consignes(texte_reponse)", SOURCE)
        self.assertIn("contents + [CONSIGNE_SANS_NOTES]", SOURCE)
        self.assertIn('!= "ENSEIGNANT" and fuite_de_consignes', SOURCE)


class ReglesTests(unittest.TestCase):
    def setUp(self):
        self.ns = charger()

    def test_qcm_memes_options(self):
        regles = self.ns["REGLES_PEDAGOGIE"]
        self.assertIn("garde EXACTEMENT les mêmes options, aux mêmes lettres", regles)
        self.assertIn("Après une deuxième erreur sur la même question, donne la bonne", regles)
        self.assertNotIn("options nouvelles ou reformulées", regles)
        self.assertIn("garde alors les mêmes options aux mêmes lettres", self.ns["consigne_bonne_lettre"]("b"))

    def test_eleve_qui_ne_comprend_pas(self):
        self.assertIn("exemple entièrement résolu", self.ns["REGLES_PEDAGOGIE"])

    def test_philosophie(self):
        self.assertIn("Ne donne jamais une « structure complète »", SOURCE)


class GrilleTests(unittest.TestCase):
    def test_grille_alignee(self):
        grille = (Path(__file__).parent.parent / "controle_qualite.py").read_text(encoding="utf-8")
        self.assertIn("retire, ajoute ou remelange les options d'un\n  QCM quand il repose la meme question", grille)
        self.assertIn("DEUX erreurs sur la meme question", grille)


if __name__ == "__main__":
    unittest.main()
