import os, unittest
os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "localhost:1")
import main


class SerieTechniqueTests(unittest.TestCase):
    def test_serie_seule(self):
        self.assertEqual(main.serie_technique_tapee("F2"), {"serie": "F2", "classe": ""})
        self.assertEqual(main.serie_technique_tapee("Première F2"), {"serie": "F2", "classe": "PREMIERE"})
        self.assertEqual(main.serie_technique_tapee("série G1")["serie"], "G1")

    def test_pas_une_serie(self):
        self.assertIsNone(main.serie_technique_tapee("B"))
        self.assertIsNone(main.serie_technique_tapee("E"))
        self.assertIsNone(main.serie_technique_tapee("calcule f1 de x plus deux"))
        self.assertIsNone(main.serie_technique_tapee("je voudrais de l aide en maths"))

    def test_parent(self):
        t = "Je suis la mère d un élève de la première F2 je voulais me renseigner Comment ça se passe"
        self.assertEqual(main.niveau_declare(t), {"type_examen": "BAC_TECHNIQUE", "serie": "F2", "classe": "PREMIERE"})

    def test_phrase_longue_sans_parent(self):
        t = "Dans mon exercice de première F2 on me demande de calculer la limite de la fonction quand x tend vers l infini et je ne comprends pas"
        self.assertIsNone(main.niveau_declare(t))


if __name__ == "__main__":
    unittest.main()
