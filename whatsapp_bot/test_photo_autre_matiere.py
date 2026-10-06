"""Photo d'une autre matiere : Akili le signale par une balise, le bot passe dans cette matiere et
le dit a l'eleve (controle qualite du 6 oct. : inscrit en anglais, photo de maths)."""
import unittest
from unittest import mock

import main


class Reponse:
    status_code = 200
    text = ""

    def __init__(self, texte="ok"):
        self.texte = texte

    def json(self):
        return {"reponse": self.texte}


class BaliseTests(unittest.TestCase):
    def test_extraction(self):
        texte, nom = main.extraire_autre_matiere("[AUTRE_MATIERE: Mathématiques]\nL'exercice porte sur une fonction f.")
        self.assertEqual(nom, "Mathématiques")
        self.assertEqual(texte, "L'exercice porte sur une fonction f.")
        self.assertEqual(main.extraire_autre_matiere("Exercice 1 : ...")[1], "")
        self.assertEqual(main.extraire_autre_matiere("[Autre matière : Physique-Chimie] Soit")[1], "Physique-Chimie")

    def test_code_selon_le_niveau(self):
        general = {"type_examen": "BAC_GENERAL", "serie": "D"}
        self.assertEqual(main.code_matiere_pour_eleve(general, "Mathématiques"), "MATHS")
        self.assertEqual(main.code_matiere_pour_eleve(general, "Physique-Chimie"), "PC")
        self.assertIsNone(main.code_matiere_pour_eleve(general, "Comptabilité"))  # pas proposee en serie D
        technique = {"type_examen": "BAC_TECHNIQUE", "serie": "G2"}
        self.assertEqual(main.code_matiere_pour_eleve(technique, "Mathématiques"), "MATHS")
        self.assertEqual(main.code_matiere_pour_eleve(technique, "Mathématiques financières"), "MATHS_FIN")
        self.assertEqual(main.code_matiere_pour_eleve(technique, "Comptabilité"), "COMPTA_FIN")
        f1 = {"type_examen": "BAC_TECHNIQUE", "serie": "F1"}
        if any(c == "CMI" for c, _ in main.matieres_technique("F1")):
            self.assertEqual(main.code_matiere_pour_eleve(f1, "Construction mécanique industrielle"), "CMI")

    def test_consigne_seulement_avec_une_photo(self):
        envoye = {}

        def faux_post(url, files=None, timeout=None, **k):
            envoye.update({k2: v[1] for k2, v in (files or {}).items() if isinstance(v, tuple) and v[0] is None})
            return Reponse()

        with mock.patch.object(main.requests, "post", side_effect=faux_post):
            main.get_akili_response("Exercice 1", "ANGLAIS", "D", [], phone="225", type_examen="BAC_GENERAL", mode="etude")
        self.assertNotIn("[AUTRE_MATIERE:", envoye["question"])


class ChangementParPhotoTests(unittest.TestCase):
    def test_le_profil_passe_en_maths(self):
        phone = "22500000085"
        profil = {"type_examen": "BAC_GENERAL", "serie": "D", "matiere": "ANGLAIS", "mode": "etude",
                  "profile_locked": True, "profile_ready": True, "onboarding_completed_at": "2026-10-01"}
        envoyes = []
        with mock.patch.object(main, "get_akili_response",
                               return_value="[AUTRE_MATIERE: Mathématiques]\nCommence par la question 1 : f est-elle décroissante ?"), \
                mock.patch.object(main, "send_whatsapp", side_effect=lambda p, m, *a, **k: envoyes.append(m) or True), \
                mock.patch.object(main, "send_whatsapp_typing_indicator"), \
                mock.patch.object(main, "sauver_etat_whatsapp"), mock.patch.object(main, "sauver_historique_conv"), \
                mock.patch.object(main, "charger_historique_conv", return_value=[]), \
                mock.patch.object(main, "journal_session_ajouter"), \
                mock.patch.object(main, "send_vector_formula_if_needed"), \
                mock.patch.object(main, "mark_first_learning_request", side_effect=lambda p, prof: prof), \
                mock.patch.object(main, "p0_enabled", return_value=False):
            try:
                main.answer_learning_request(phone, profil, "voici mon exercice", media_file="/tmp/photo.jpg")
            finally:
                main.user_profiles.pop(phone, None)
                cles = [k for k in main.conversations if k.startswith(phone)]
        self.assertEqual(profil["matiere"], "MATHS")
        self.assertTrue(envoyes[-1].startswith("Ta photo est un exercice de Mathématiques : je passe en Mathématiques."))
        self.assertIn("revenir en Anglais", envoyes[-1])
        self.assertNotIn("[AUTRE_MATIERE", envoyes[-1])
        self.assertIn(f"{phone}:BAC_GENERAL:D:MATHS:etude", cles)
        for k in cles:
            main.conversations.pop(k, None)


if __name__ == "__main__":
    unittest.main()
