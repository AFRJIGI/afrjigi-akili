import unittest

import main


class DecrirePromptTest(unittest.TestCase):
    def test_decompose_les_blocs_du_prompt(self):
        systeme = "Tu es Akili.\nREGLES\nPLACE DE LA BONNE REPONSE (c)"
        question = ("CONSIGNES FIXES DU BOT\nHISTORIQUE RECENT:\nEleve: a\nAkili: b\n\n"
                    "QUESTION REELLE DE L'ELEVE:\nBonjour")
        ligne = main.decrire_prompt(systeme, question, "extraits", "MATHS", "etude")
        self.assertIn("matiere=MATHS mode=etude", ligne)
        self.assertIn(f"systeme={len(systeme)}", ligne)
        self.assertIn("consignes_bot=23", ligne)
        self.assertIn("contexte=8", ligne)
        self.assertIn(f"question={len('QUESTION REELLE DE L' + chr(39) + 'ELEVE:' + chr(10) + 'Bonjour')}", ligne)

    def test_la_phrase_tiree_au_hasard_ne_change_pas_l_empreinte_du_socle(self):
        base = "Tu es Akili.\nREGLES"
        a = main.decrire_prompt(base + "\nPLACE (a)", "q", "", "ECO", "etude")
        b = main.decrire_prompt(base + "\nPLACE (d)", "q", "", "ECO", "etude")
        empreinte = lambda ligne: [m for m in ligne.split() if m.startswith("socle_hash=")]
        self.assertEqual(empreinte(a), empreinte(b))

    def test_valeurs_vides_ne_plantent_pas(self):
        self.assertIn("PROMPT_STRUCTURE", main.decrire_prompt("", "", None, "", ""))


if __name__ == "__main__":
    unittest.main()
