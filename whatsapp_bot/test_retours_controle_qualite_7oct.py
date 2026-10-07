"""Controle qualite du 7 oct. : niveau annonce par l'eleve, BTS en boucle, listes journalisees,
consignes eleve bloque et validation."""
import unittest
from pathlib import Path
from unittest import mock

import main

PHONE = "22500000086"


class NiveauDeclareTests(unittest.TestCase):
    def test_niveaux_reconnus(self):
        cas = {
            "2ndc": {"type_examen": "CLASSE_INTERMEDIAIRE", "serie": "SECONDE_C", "classe": ""},
            "je suis en 2nde C": {"type_examen": "CLASSE_INTERMEDIAIRE", "serie": "SECONDE_C", "classe": ""},
            "Il s'agit en classe de première G1": {"type_examen": "BAC_TECHNIQUE", "serie": "G1", "classe": "PREMIERE"},
            "Tle D": {"type_examen": "BAC_GENERAL", "serie": "D", "classe": ""},
            "je suis en 3eme": {"type_examen": "BEPC", "serie": "BEPC", "classe": ""},
            "je suis en terminale F2": {"type_examen": "BAC_TECHNIQUE", "serie": "F2", "classe": "TERMINALE"},
        }
        for texte, attendu in cas.items():
            self.assertEqual(main.niveau_declare(texte), attendu, texte)

    def test_reponses_d_exercice_ignorees(self):
        for texte in ["5e", "x = 4e", "3e", "la question 2", "en seconde guerre mondiale, qui a gagné la bataille ?",
                      "Calcule la dérivée de f en terminale on voit les limites et les dérivées et les intégrales et tout"]:
            self.assertIsNone(main.niveau_declare(texte), texte)

    def test_profil_mis_a_jour(self):
        envoyes = []
        profil = {"type_examen": "BEPC", "serie": "BEPC", "matiere": "PC", "mode": "etude", "profile_locked": True,
                  "onboarding_completed_at": "2026-10-01"}
        niveau = main.niveau_declare("2ndc")
        self.assertTrue(main.niveau_different(profil, niveau))
        with mock.patch.object(main, "send_whatsapp", side_effect=lambda p, m, *a, **k: envoyes.append(m)), \
                mock.patch.object(main, "sauver_etat_whatsapp"), \
                mock.patch.object(main, "mark_onboarding_completed", side_effect=lambda p, prof: prof), \
                mock.patch.object(main, "feedback_db", mock.MagicMock()):
            main.appliquer_niveau_declare(PHONE, profil, niveau)
        main.user_profiles.pop(PHONE, None)
        self.assertEqual((profil["type_examen"], profil["serie"], profil["matiere"]),
                         ("CLASSE_INTERMEDIAIRE", "SECONDE_C", "PC"))
        self.assertEqual(envoyes[0], "D'accord, je mets ton profil à jour : Seconde C.")
        self.assertIn("Seconde C, Physique-Chimie", envoyes[1])
        self.assertFalse(main.niveau_different(profil, niveau))

    def test_matiere_absente_du_nouveau_niveau(self):
        listes = []
        profil = {"type_examen": "BAC_GENERAL", "serie": "A2", "matiere": "PHILO", "mode": "etude"}
        with mock.patch.object(main, "send_whatsapp"), mock.patch.object(main, "sauver_etat_whatsapp"), \
                mock.patch.object(main, "ask_matiere", side_effect=lambda p, serie: listes.append(serie)):
            main.appliquer_niveau_declare(PHONE, profil, main.niveau_declare("je suis en 3eme"))
        main.user_profiles.pop(PHONE, None)
        self.assertEqual(listes, ["BEPC"])  # pas de philosophie au BEPC : liste des matieres


class SourceTests(unittest.TestCase):
    source = Path(main.__file__).read_text(encoding="utf-8")

    def test_bts_avant_la_question_gardee(self):
        self.assertIn("Le BTS et l'université ne sont pas encore disponibles", main.MESSAGE_HORS_CHAMP)
        self.assertLess(self.source.index('track_inbound("hors_champ_bts_universite"'),
                        self.source.index('track_inbound("forced_onboarding_pending_question"'))

    def test_liste_journalisee(self):
        evenements = []
        with mock.patch.object(main, "LISTES_WHATSAPP", True), \
                mock.patch.object(main, "send_whatsapp_liste", return_value=True), \
                mock.patch.object(main, "save_whatsapp_event", side_effect=lambda *a, **k: evenements.append(a)):
            main.envoyer_choix(PHONE, "Quel niveau ?", [("a", "BEPC", ""), ("b", "BAC", "")])
        self.assertTrue(evenements and evenements[0][2].startswith("[liste] Quel niveau ?"))

    def test_consignes_eleve_bloque(self):
        self.assertIn("ne repose JAMAIS la même question", self.source)
        self.assertIn("-2 au lieu de -2t", self.source)


if __name__ == "__main__":
    unittest.main()
