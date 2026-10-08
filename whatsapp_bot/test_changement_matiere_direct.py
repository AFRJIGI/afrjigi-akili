"""Diagnostic …9171 (8 oct.) : « Je veux un sujet en philo… » ouvrait la liste des matieres ; un « ?? »
envoye pendant que le bot tardait refermait la liste et l'eleve repartait en maths."""
import asyncio
import unittest
from unittest import mock

import main

PHONE = "22500000102"
INSCRIT = {"type_examen": "BAC_GENERAL", "serie": "D", "matiere": "MATHS", "mode": "etude",
           "profile_ready": True, "profile_locked": True, "matiere_confirmed": True, "onboarding_step": "",
           "onboarding_completed_at": "2026-10-06T15:08:39+00:00", "first_learning_request_at": "x"}


class FauxRequete:
    def __init__(self, texte, n):
        self._body = {"entry": [{"changes": [{"value": {"messages": [
            {"from": PHONE, "id": f"wamid.9171.{n}", "type": "text", "text": {"body": texte}}
        ]}}]}]}

    async def json(self):
        return self._body


class ChangementDeMatiereTests(unittest.TestCase):
    def setUp(self):
        self.envoyes, self.listes, self.akili, self.etapes = [], [], [], []
        self.etat = {}
        noop = lambda *a, **k: None
        self.patches = [
            mock.patch.object(main, "send_whatsapp", side_effect=lambda phone, msg, *a, **k: self.envoyes.append(msg)),
            mock.patch.object(main, "envoyer_choix", side_effect=lambda phone, q, options, **k: self.listes.append(q)),
            mock.patch.object(main, "send_whatsapp_typing_indicator", side_effect=noop),
            mock.patch.object(main, "reserver_message_whatsapp", return_value=True),
            mock.patch.object(main, "charger_etat_whatsapp", side_effect=lambda phone: dict(self.etat)),
            mock.patch.object(main, "sauver_etat_whatsapp", side_effect=lambda phone, p: self.etat.update(p)),
            mock.patch.object(main, "save_whatsapp_event",
                              side_effect=lambda *a, **k: self.etapes.append((k.get("extra") or {}).get("processing_stage"))),
            mock.patch.object(main, "maybe_send_marketing_consent_prompt", side_effect=noop),
            mock.patch.object(main, "charger_historique_conv", return_value=[]),
            mock.patch.object(main, "load_last_assistant_context", return_value=""),
            mock.patch.object(main, "mark_onboarding_completed",
                              side_effect=lambda p, prof: dict(prof, profile_ready=True, onboarding_step="")),
            mock.patch.object(main, "answer_learning_request",
                              side_effect=lambda phone, profile, text, **k: self.akili.append((dict(profile), text))),
        ]
        for p in self.patches:
            p.start()
        main.processed_messages.clear()
        main.conversations.clear()
        self.n = 0

    def tearDown(self):
        for p in self.patches:
            p.stop()
        main.user_profiles.pop(PHONE, None)
        main.processed_messages.clear()
        main.conversations.clear()

    def envoyer(self, texte, profil=None):
        if profil is not None:
            self.etat = dict(profil)
            main.user_profiles[PHONE] = dict(profil)
        self.n += 1
        return asyncio.run(main.receive_message(FauxRequete(texte, self.n)))

    def test_matiere_nommee_avec_demande(self):
        texte = "Je veux un sujet en philo parce que demain j'ai devoir je vais me construire une introduction"
        self.envoyer(texte, INSCRIT)
        profil = main.user_profiles[PHONE]
        self.assertEqual((profil["matiere"], profil.get("onboarding_step")), ("PHILO", ""))
        self.assertEqual(self.listes, [])
        self.assertEqual(self.envoyes, ["D'accord, on passe en Philosophie."])
        self.assertEqual(len(self.akili), 1)
        self.assertEqual((self.akili[0][0]["matiere"], self.akili[0][1]), ("PHILO", texte))

    def test_matiere_nommee_sans_demande(self):
        self.envoyer("Allons en philosophie", INSCRIT)
        profil = main.user_profiles[PHONE]
        self.assertEqual((profil["matiere"], profil.get("onboarding_step")), ("PHILO", ""))
        self.assertEqual(self.listes, [])
        self.assertEqual(self.akili, [])
        self.assertTrue(self.envoyes[0].startswith("C'est noté : BAC Général, Terminale D, Philosophie"))

    def test_refus_ouvre_la_liste(self):
        self.envoyer("je veux plus faire de svt", dict(INSCRIT, matiere="PC"))
        self.assertEqual(self.listes, ["Quelle matière veux-tu travailler ?"])
        self.assertEqual(main.user_profiles[PHONE]["matiere"], "PC")

    def test_philo_pas_proposee_au_college(self):
        profil = dict(INSCRIT, type_examen="BEPC", serie="BEPC")
        self.assertIsNone(main.matiere_demandee(profil, "allons en philo"))
        self.envoyer("Je veux un sujet en philo pour mon devoir", profil)
        self.assertEqual(self.envoyes[0], "La philosophie se travaille en Terminale. Choisis une matière de ton niveau :")
        self.assertEqual(len(self.listes), 1)
        self.assertEqual(self.akili, [])

    def test_bac_technique_philo(self):
        profil = dict(INSCRIT, type_examen="BAC_TECHNIQUE", serie="G2", matiere="COMPTA_FIN")
        self.envoyer("Je veux un sujet en philo pour mon devoir", profil)
        self.assertEqual(main.user_profiles[PHONE]["matiere"], "PHILO")
        self.assertEqual(self.listes, [])
        self.assertEqual(self.envoyes, ["D'accord, on passe en Philosophie."])
        self.assertEqual(len(self.akili), 1)

    def test_bac_technique_compta_ouvre_la_liste(self):
        profil = dict(INSCRIT, type_examen="BAC_TECHNIQUE", serie="G2", matiere="MATHS")
        self.assertIsNone(main.matiere_demandee(profil, "allons en compta"))

    def test_deux_matieres_ouvrent_la_liste(self):
        self.assertIsNone(main.matiere_demandee(INSCRIT, "passons de la svt à la philo"))

    def test_bruit_pendant_la_liste_la_repose(self):
        profil = dict(INSCRIT, onboarding_step="matiere")
        profil.pop("profile_locked")
        profil.pop("matiere_confirmed")
        self.envoyer("??", profil)
        self.assertEqual(self.akili, [])
        self.assertEqual(main.user_profiles[PHONE]["onboarding_step"], "matiere")
        self.assertEqual(self.envoyes[0], main.MESSAGE_CHOIX_NON_COMPRIS)
        self.assertEqual(self.listes, ["Quelle matière veux-tu travailler ?"])
        self.envoyer("e")
        self.assertEqual(main.user_profiles[PHONE]["matiere"], "PHILO")

    def test_laisse_ca_garde_la_matiere(self):
        profil = dict(INSCRIT, onboarding_step="matiere")
        self.envoyer("Laisse ça", profil)
        profil = main.user_profiles[PHONE]
        self.assertEqual((profil["matiere"], profil.get("onboarding_step")), ("MATHS", ""))
        self.assertTrue(self.envoyes[0].startswith("D'accord, on ne change rien"))
        self.assertEqual(self.akili, [])

    def test_exercice_pendant_la_liste_la_referme(self):
        profil = dict(INSCRIT, onboarding_step="matiere")
        self.envoyer("Calcule la dérivée de f(x) = 3x² + 2x", profil)
        self.assertEqual(len(self.akili), 1)
        self.assertEqual(self.akili[0][0]["matiere"], "MATHS")


if __name__ == "__main__":
    unittest.main()
