"""Controle qualite du 8 nov. (…9289) : « Menu français » devait changer la matiere du profil."""
import unittest
from unittest import mock

import main

PROFIL = {"type_examen": "BAC_GENERAL", "serie": "A2", "matiere": "ANGLAIS"}
DERNIER_MESSAGE = ("« Nuire » signifie causer du tort. Exemple : • Français : La pollution peut nuire à "
                   "l'environnement. • Anglais : Pollution can harm the environment. À toi d'essayer")


class MenuMatiereTests(unittest.TestCase):
    def avec_contexte(self, texte):
        return mock.patch.object(main, "load_last_assistant_context", return_value=texte)

    def test_menu_francais_change_la_matiere_meme_si_akili_citait_francais(self):
        with self.avec_contexte(DERNIER_MESSAGE):
            for texte in ("Menu français", "menu francais", "Menu Français svp"):
                self.assertEqual(main.nom_de_matiere_seul("225", PROFIL, texte), "FRANCAIS", texte)

    def test_francais_seul_reste_protege_quand_akili_le_citait(self):
        with self.avec_contexte(DERNIER_MESSAGE):
            self.assertIsNone(main.nom_de_matiere_seul("225", PROFIL, "français"))

    def test_menu_sans_matiere_ou_phrase_inchange(self):
        with self.avec_contexte(""):
            self.assertIsNone(main.nom_de_matiere_seul("225", PROFIL, "menu"))
            self.assertIsNone(main.nom_de_matiere_seul("225", PROFIL, "menu pour changer de classe en français svp merci"))
            self.assertEqual(main.nom_de_matiere_seul("225", PROFIL, "français"), "FRANCAIS")


if __name__ == "__main__":
    unittest.main()
