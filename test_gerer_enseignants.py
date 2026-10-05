import unittest

from gerer_enseignants import matieres_connues, message_pour_le_professeur, preparer

CONNUES = matieres_connues()


class GererEnseignantsTests(unittest.TestCase):
    def test_matieres_du_bot(self):
        for code in ["MATHS", "MECANIQUE_APPLIQUEE", "CMI", "ECO", "PHILO"]:
            self.assertIn(code, CONNUES)

    def test_preparer(self):
        matieres, classes = preparer("M. Sidibé", "mecanique_appliquee, CMI", "2nde F2, 1ère F2,Tle F2", CONNUES)
        self.assertEqual(matieres, ["MECANIQUE_APPLIQUEE", "CMI"])
        self.assertEqual(classes, ["2nde F2", "1ère F2", "Tle F2"])
        for mauvais in [("", "MATHS", "Tle D"), ("M. X", "MATHEMATIQUES", "Tle D"), ("M. X", "MATHS", "Licence 1"),
]:
            with self.assertRaises(ValueError):
                preparer(*mauvais, CONNUES)

    def test_classes_facultatives(self):
        self.assertEqual(preparer("M. Brou", "MATHS", "", CONNUES), (["MATHS"], []))
        message = message_pour_le_professeur("M. Brou", "PROF-BROU-1234", ["MATHS"], [], CONNUES)
        self.assertIn("Akili vous demandera ensuite vos classes", message)

    def test_message(self):
        message = message_pour_le_professeur("M. Sidibé", "PROF-SIDIBE-4821", ["MECANIQUE_APPLIQUEE"], ["2nde F2"], CONNUES)
        self.assertIn("PROF-SIDIBE-4821", message)
        self.assertIn("Mécanique appliquée", message)


if __name__ == "__main__":
    unittest.main()
