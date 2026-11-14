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


class PhotosRegroupeesTests(unittest.TestCase):
    def test_consigne_selon_le_nombre_de_photos(self):
        def corps(n):
            image = {"id": "m1", "caption": ""}
            if n:
                image["photos_regroupees"] = n
            return {"entry": [{"changes": [{"value": {"messages": [{"type": "image", "image": image}]}}]}]}
        jeton = main._corps_fusionne.set(corps(3))
        try:
            self.assertIn("3 photos", main.consigne_photos_regroupees())
            main._corps_fusionne.set(corps(0))
            self.assertEqual(main.consigne_photos_regroupees(), "")
            main._corps_fusionne.set(None)
            self.assertEqual(main.consigne_photos_regroupees(), "")
        finally:
            main._corps_fusionne.reset(jeton)


if __name__ == "__main__":
    unittest.main()
