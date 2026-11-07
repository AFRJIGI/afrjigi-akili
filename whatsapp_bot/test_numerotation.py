"""Numerotation reguliere (7 nov.) : « 1. » ne devient plus une liste WhatsApp avec retrait, et les
sous-questions « b) », « c) » s'alignent sous « a) »."""
import unittest

import main

ENONCE = (
    "1. Calcule U2, U3 et U4.\n"
    "2. a) Démontre que (Vn) est une suite géométrique de raison 2.\n"
    "b) Exprime Vn en fonction de n.\n"
    "c) Justifie que pour tout n ≥ 1, Un = 2n-1 + 1.\n"
    "d) Calcule U13.\n"
    "3. Soit Tn = U1 + U2 + ... + Un.\n"
    "a) Justifie que Tn = 2n + n - 1.\n"
    "b) Calcule la somme des 13 premiers termes de (Un)."
)


class NumerotationTests(unittest.TestCase):
    def test_enonce_du_7_novembre(self):
        self.assertEqual(main.harmoniser_numerotation(ENONCE).split("\n"), [
            "1) Calcule U2, U3 et U4.",
            "",
            "2)",
            "   a) Démontre que (Vn) est une suite géométrique de raison 2.",
            "   b) Exprime Vn en fonction de n.",
            "   c) Justifie que pour tout n ≥ 1, Un = 2n-1 + 1.",
            "   d) Calcule U13.",
            "",
            "3) Soit Tn = U1 + U2 + ... + Un.",
            "   a) Justifie que Tn = 2n + n - 1.",
            "   b) Calcule la somme des 13 premiers termes de (Un).",
        ])

    def test_capture_du_7_novembre_14h49(self):
        texte = ("1) Résous x.\n2) Soit P(x).\na) Vérifie P.\nb) Résous P(x) = 0.\n"
                 "3) a) Résous P(x) < 0.\nb) Résous Q(x) < 0.")
        self.assertEqual(main.harmoniser_numerotation(texte).split("\n"), [
            "1) Résous x.", "", "2) Soit P(x).", "   a) Vérifie P.", "   b) Résous P(x) = 0.", "",
            "3)", "   a) Résous P(x) < 0.", "   b) Résous Q(x) < 0."])

    def test_lettres_sans_question_numerotee_restent_a_gauche(self):
        texte = "Réponds :\na) Paris\nb) Lomé\nc) Abidjan"
        self.assertEqual(main.harmoniser_numerotation(texte), texte)

    def test_ligne_vide_termine_la_question(self):
        texte = "1. Calcule A.\n\nb) Autre chose"
        self.assertEqual(main.harmoniser_numerotation(texte), "1) Calcule A.\n\nb) Autre chose")

    def test_decimaux_et_texte_ordinaire_inchanges(self):
        for texte in ("3.14 est une valeur approchée de pi.", "Il y a 2. Le reste suit.", "Étape 1 : calcule."):
            self.assertEqual(main.harmoniser_numerotation(texte), texte)

    def test_clean_whatsapp_response_l_applique(self):
        sortie = main.clean_whatsapp_response("**Exercice 1**\n1. Calcule A.\n2. a) Montre B.\nb) Donne C.")
        self.assertIn("1) Calcule A.\n\n2)\n   a) Montre B.\n   b) Donne C.", sortie)


class ExamenEtIndiceTests(unittest.TestCase):
    def test_consigne_courte_et_indice_sans_resultat(self):
        self.assertLess(len(main.MESSAGE_CONSIGNE_EXAMEN), 60)
        self.assertIn("sans aucun résultat", main.BOUTONS_AIDE_TEXTE["aide_indice"])

    def test_bouton_sujet_a_l_activation_de_l_examen(self):
        envoyes = []
        from unittest import mock
        with mock.patch.object(main, "send_whatsapp_boutons",
                               side_effect=lambda phone, corps, b: envoyes.append(b) or True):
            self.assertTrue(main.envoyer_bouton_sujet_examen("225", {"mode": "examen"}))
            self.assertFalse(main.envoyer_bouton_sujet_examen("225", {"mode": "etude"}))
            self.assertFalse(main.envoyer_bouton_sujet_examen("225", {"mode": "examen", "user_type": "ENSEIGNANT"}))
        self.assertEqual(envoyes, [[("examen_sujet", "Donne-moi un sujet"), ("nav_menu", "Menu")]])
        self.assertEqual(main.BOUTONS_AIDE_TEXTE["examen_sujet"], "Donne-moi un sujet")


if __name__ == "__main__":
    unittest.main()
