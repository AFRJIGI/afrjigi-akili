"""Akili recoit la matiere choisie en toutes lettres (avant : "Propose-moi un exercice"
en CMI donnait un exercice de chimie)."""
import unittest
from unittest import mock

import main


class Reponse:
    status_code = 200
    text = ""

    def json(self):
        return {"reponse": "Exercice : une poutre..."}


class ConsigneMatiereTests(unittest.TestCase):
    def test_consigne(self):
        texte = main.consigne_matiere_choisie("CMI", "F1", "BAC_TECHNIQUE")
        self.assertIn("Construction mécanique industrielle (BAC Technique, série F1)", texte)
        self.assertIn("jamais sur une autre", texte)
        self.assertIn("Anglais (BEPC)", main.consigne_matiere_choisie("ANGLAIS", "BEPC", "BEPC"))
        self.assertEqual(main.consigne_matiere_choisie(None), "")

    def test_question_envoyee_a_akili(self):
        envoye = {}

        def faux_post(url, files=None, timeout=None, **k):
            envoye.update({k2: v[1] for k2, v in (files or {}).items()})
            return Reponse()

        with mock.patch.object(main.requests, "post", side_effect=faux_post):
            main.get_akili_response("Propose-moi un exercice", "CMI", "F1", [], phone="225",
                                    type_examen="BAC_TECHNIQUE", mode="etude")
        self.assertIn("MATIERE CHOISIE PAR L'ELEVE : Construction mécanique industrielle", envoye["question"])
        self.assertEqual(envoye["matiere"], "CMI")


if __name__ == "__main__":
    unittest.main()
