"""Controle qualite du 10 oct. : changement de niveau en toutes lettres, lettre hors liste au menu,
ligne de la liste des matieres recopiee (« b. Physique-Chimie »)."""
import asyncio
import unittest
from unittest import mock

import main

PHONE = "22500000310"
PROFIL = {"type_examen": "BAC_GENERAL", "serie": "C", "matiere": "MATHS", "mode": "etude", "profile_ready": True,
          "profile_locked": True, "matiere_confirmed": True, "onboarding_step": "",
          "onboarding_completed_at": "2026-10-01T10:00:00+00:00"}


class FakeRequest:
    def __init__(self, texte, message_id):
        self._body = {"entry": [{"changes": [{"value": {"messages": [
            {"from": PHONE, "id": message_id, "type": "text", "text": {"body": texte}}]}}]}]}

    async def json(self):
        return self._body


class Webhook(unittest.TestCase):
    profil = PROFIL

    def setUp(self):
        self.envoyes, self.listes = [], []
        noop = lambda *a, **k: None
        self.patches = [
            mock.patch.object(main, "reserver_message_whatsapp", return_value=True),
            mock.patch.object(main, "send_whatsapp", side_effect=lambda phone, msg, *a, **k: self.envoyes.append(msg)),
            mock.patch.object(main, "send_whatsapp_liste",
                              side_effect=lambda phone, corps, lignes, bouton="Choisir": self.listes.append(corps) or True),
            mock.patch.object(main, "send_whatsapp_typing_indicator", side_effect=noop),
            mock.patch.object(main, "charger_etat_whatsapp", side_effect=lambda phone: dict(self.profil)),
            mock.patch.object(main, "sauver_etat_whatsapp", side_effect=noop),
            mock.patch.object(main, "save_whatsapp_event", side_effect=noop),
            mock.patch.object(main, "maybe_send_marketing_consent_prompt", side_effect=noop),
            mock.patch.object(main, "load_last_assistant_context", return_value="Quel est le nom de CH2=CH2 ? (a) (b) (c)"),
            mock.patch.object(main, "answer_learning_request", side_effect=AssertionError("ne doit pas appeler Akili")),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        main.user_profiles.pop(PHONE, None)

    def envoyer(self, texte, message_id):
        return asyncio.run(main.receive_message(FakeRequest(texte, message_id)))


class ChangementDeNiveauTests(Webhook):
    def test_je_veux_changer_de_niveau(self):
        # …6350 : Akili inventait « (a) Terminale C (b) Premiere C (c) Seconde C ».
        resultat = self.envoyer("Je veux changer de niveau", "wamid.niv1")
        self.assertEqual(resultat.get("reason"), "changement_niveau")
        self.assertEqual(main.user_profiles[PHONE]["onboarding_step"], "exam")
        self.assertIn("D'accord, changeons ton niveau.", self.listes[-1])

    def test_matiere_et_niveau_commence_par_le_niveau(self):
        resultat = self.envoyer("Changer de matière et de niveau d'étude", "wamid.niv2")
        self.assertEqual(resultat.get("reason"), "changement_niveau")

    def test_classe_dite_en_toutes_lettres(self):
        # …0512 (audio) : Akili repondait « le niveau est bien Premiere G2 maintenant » sans rien changer.
        self.profil = dict(PROFIL, type_examen="BAC_TECHNIQUE", serie="G2", classe="TERMINALE", matiere="COMPTA_ANALYTIQUE")
        resultat = self.envoyer("S'il vous plaît est-ce que je peux changer de classe pour remettre ça en classe "
                                "de première G2 s'il vous plaît", "wamid.niv3")
        self.assertEqual(resultat.get("reason"), "niveau_corrige")
        profil = main.user_profiles[PHONE]
        self.assertEqual((profil["serie"], profil["classe"], profil["matiere"]), ("G2", "PREMIERE", "COMPTA_ANALYTIQUE"))

    def test_aussi_quand_le_menu_est_ouvert(self):
        self.profil = dict(PROFIL, type_examen="BAC_TECHNIQUE", serie="G2", classe="TERMINALE",
                           matiere="COMPTA_ANALYTIQUE", onboarding_step="menu_choice")
        resultat = self.envoyer("je peux changer de classe pour remettre ça en classe de première G2", "wamid.niv4")
        self.assertEqual(resultat.get("reason"), "niveau_corrige")
        self.assertEqual(main.user_profiles[PHONE]["classe"], "PREMIERE")


class MenuTests(Webhook):
    def test_lettre_hors_liste_au_menu(self):
        # …4465 : « d » au menu lancait un exercice de francais.
        self.profil = dict(PROFIL, onboarding_step="menu_choice")
        self.envoyer("d", "wamid.menu1")
        self.assertIn(main.MESSAGE_CHOIX_NON_COMPRIS, self.envoyes)
        self.assertIn("Que veux-tu faire ?", self.listes[-1])
        self.assertEqual(main.user_profiles[PHONE]["onboarding_step"], "menu_choice")

    def test_classe_au_menu_choisit_le_niveau(self):
        self.profil = dict(PROFIL, onboarding_step="menu_choice")
        self.envoyer("classe", "wamid.menu2")
        self.assertEqual(main.user_profiles[PHONE]["onboarding_step"], "exam")


class MatiereRecopieeTests(Webhook):
    def test_ligne_de_la_liste_recopiee(self):
        # …5315 : « b. Physique-Chimie » ; Akili disait « nous passons a la Physique-Chimie », la matiere restait Maths.
        resultat = self.envoyer("b. Physique-Chimie", "wamid.mat1")
        self.assertEqual(resultat.get("reason"), "changement_matiere_direct")
        self.assertEqual(main.user_profiles[PHONE]["matiere"], "PC")


class DetectionTests(unittest.TestCase):
    def test_demandes_de_changement_de_niveau(self):
        for texte in ("Je veux changer de niveau", "Changer de classe", "Non changeons de classe d'abord",
                      "je veux une autre série", "Changer de matière et de niveau d'étude"):
            self.assertTrue(main.est_demande_changement_niveau(texte), texte)
        for texte in ("changer de matière", "je passe le compte en classe 6", "le niveau de l'eau monte",
                      "une autre classe 4 de comptes"):
            self.assertFalse(main.est_demande_changement_niveau(texte), texte)


if __name__ == "__main__":
    unittest.main()
