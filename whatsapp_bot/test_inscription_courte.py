"""Inscription courte : listes a toucher, pas de question du mode, ville et ecole apres le premier bilan."""
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import main

PHONE = "22500000070"


class Base(unittest.TestCase):
    def setUp(self):
        self.envoyes, self.listes = [], []
        self.liste_ok = False
        self.patches = [
            mock.patch.object(main, "send_whatsapp", side_effect=lambda phone, msg, *a, **k: self.envoyes.append(msg)),
            mock.patch.object(main, "send_whatsapp_liste",
                              side_effect=lambda phone, corps, lignes, bouton="Choisir": self.listes.append((corps, lignes)) or self.liste_ok),
            mock.patch.object(main, "sauver_etat_whatsapp"),
            mock.patch.object(main, "mark_onboarding_completed",
                              side_effect=lambda phone, p: p.update({"profile_ready": True, "onboarding_step": "",
                                                                     "onboarding_completed_at": "2026-10-04T10:00:00+00:00"}) or p),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        main.user_profiles.pop(PHONE, None)


class InscriptionTests(Base):
    def test_bac_technique_en_4_reponses_sans_mode_ni_ville(self):
        profil = {"onboarding_step": "exam", "serie": "TOUTES"}
        for reponse in ["c", "f", "a"]:  # BAC Technique, F2, Seconde
            self.assertTrue(main.handle_onboarding_choice(PHONE, profil, reponse))
        self.assertEqual(profil["onboarding_step"], "matiere")
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "a"))
        self.assertEqual(profil["mode"], "etude")
        self.assertEqual(profil["onboarding_step"], "")
        self.assertTrue(main.is_profile_ready(profil))  # sans ville
        self.assertNotIn("ville", profil)
        self.assertIn("Profil prêt : BAC Technique, série F2, Seconde", self.envoyes[-1])
        self.assertIn("Tu es en mode étude", self.envoyes[-1])
        self.assertFalse(any("ville" in m.lower() for m in self.envoyes))

    def test_changer_de_matiere_reste_court(self):
        profil = {"onboarding_step": "matiere", "type_examen": "BAC_GENERAL", "serie": "D", "mode": "examen",
                  "onboarding_completed_at": "2026-09-01T00:00:00+00:00"}
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "b"))
        self.assertEqual((profil["matiere"], profil["mode"]), ("PC", "examen"))
        self.assertTrue(self.envoyes[-1].startswith("C'est noté : BAC Général, Terminale D, Physique-Chimie, mode examen"))

    def test_menu_change_le_mode(self):
        profil = {"onboarding_step": "menu_choice", "type_examen": "BEPC", "serie": "BEPC", "matiere": "MATHS",
                  "mode": "etude", "onboarding_completed_at": "2026-09-01T00:00:00+00:00"}
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "c"))
        self.assertEqual(profil["onboarding_step"], "mode")
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "b"))
        self.assertEqual(profil["mode"], "examen")
        self.assertIn("mode examen", self.envoyes[-1])

    def test_eleve_arrete_a_la_question_du_mode(self):
        profil = {"onboarding_step": "mode", "type_examen": "BAC_GENERAL", "serie": "C", "matiere": "MATHS",
                  "matiere_confirmed": True}
        self.assertTrue(main.handle_onboarding_choice(PHONE, profil, "a"))
        self.assertEqual(profil["onboarding_step"], "")
        self.assertIn("Profil prêt", self.envoyes[-1])


class ListeTests(Base):
    def test_liste_puis_repli_texte(self):
        self.liste_ok = True
        main.ask_matiere_technique(PHONE, "F3")  # 10 matieres
        corps, lignes = self.listes[-1]
        self.assertIn("Quelle matière", corps)
        self.assertEqual(self.envoyes, [])
        self.assertTrue(all(len(titre) <= 24 for _, titre, _ in lignes))
        longue = next(l for l in lignes if l[1].endswith("…"))
        self.assertIn(longue[1][3:-1], longue[2])  # le libelle complet est dans la description
        self.liste_ok = False
        main.ask_exam(PHONE)
        self.assertIn("d. Classe intermédiaire : 6e, 5e, 4e, Seconde ou Première", self.envoyes[-1])
        self.assertIn("Réponds par a, b, c ou d.", self.envoyes[-1])

    def test_plus_de_10_matieres_en_lettres(self):
        self.liste_ok = True
        with mock.patch.object(main, "matieres_technique", return_value=[(f"M{i}", f"Matière {i}") for i in range(12)]):
            main.ask_matiere_technique(PHONE, "F2")
        self.assertEqual(self.listes, [])
        self.assertIn("l. Matière 11", self.envoyes[-1])

    def test_reponse_touchee_dans_la_liste(self):
        etat = {"onboarding_step": "exam", "serie": "TOUTES"}

        class Requete:
            async def json(self):
                return {"entry": [{"changes": [{"value": {"messages": [
                    {"from": PHONE, "id": "wamid.liste", "type": "interactive",
                     "interactive": {"type": "list_reply", "list_reply": {"id": "choix_a", "title": "a. BEPC / 3e"}}}]}}]}]}

        noop = lambda *a, **k: None
        with mock.patch.object(main, "send_whatsapp_typing_indicator", side_effect=noop), \
             mock.patch.object(main, "reserver_message_whatsapp", return_value=True), \
             mock.patch.object(main, "charger_etat_whatsapp", side_effect=lambda phone: dict(etat)), \
             mock.patch.object(main, "save_whatsapp_event", side_effect=noop), \
             mock.patch.object(main, "maybe_send_marketing_consent_prompt", side_effect=noop):
            main.processed_messages.clear()
            asyncio.run(main.receive_message(Requete()))
        self.assertEqual(main.user_profiles[PHONE]["type_examen"], "BEPC")
        self.assertEqual(main.user_profiles[PHONE]["onboarding_step"], "matiere")


class VilleEcoleTests(Base):
    NOW = datetime(2026, 10, 4, 15, 0, tzinfo=timezone.utc)

    def test_demandee_une_seule_fois(self):
        main.user_profiles[PHONE] = {"type_examen": "BEPC"}
        self.assertTrue(main.demander_ville_ecole_si_besoin(PHONE))
        self.assertEqual(self.envoyes[-1], main.QUESTION_VILLE_ECOLE)
        self.assertFalse(main.demander_ville_ecole_si_besoin(PHONE))
        main.user_profiles[PHONE] = {"ville": "Daloa"}
        self.assertFalse(main.demander_ville_ecole_si_besoin(PHONE))

    def test_lecture_de_la_reponse(self):
        self.assertEqual(main.lire_ville_ecole("Bouaké, Lycée moderne 1"), ("Bouaké", "Lycée moderne 1"))
        self.assertEqual(main.lire_ville_ecole("Korhogo lycée Houphouët-Boigny"), ("Korhogo", "lycée Houphouët-Boigny"))
        self.assertEqual(main.lire_ville_ecole("Yamoussoukro"), ("Yamoussoukro", ""))
        self.assertEqual(main.lire_ville_ecole("Collège Saint Viateur"), ("", "Collège Saint Viateur"))

    def test_reponses(self):
        attente = lambda minutes=5: {"attente_ville_ecole": (self.NOW - timedelta(minutes=minutes)).isoformat()}
        self.assertEqual(main.ville_ecole_attendue(attente(), "Abidjan, Lycée classique", now=self.NOW),
                         ("Abidjan", "Lycée classique"))
        self.assertIs(main.ville_ecole_attendue(attente(), "passer", now=self.NOW), False)
        p = attente()
        self.assertIsNone(main.ville_ecole_attendue(p, "merci", now=self.NOW))
        self.assertIn("attente_ville_ecole", p)  # on attend encore la vraie reponse
        p = attente()
        self.assertIsNone(main.ville_ecole_attendue(p, "Propose-moi un exercice sur les limites", now=self.NOW))
        self.assertNotIn("attente_ville_ecole", p)
        p = attente(minutes=90)
        self.assertIsNone(main.ville_ecole_attendue(p, "Abidjan", now=self.NOW))
        self.assertNotIn("attente_ville_ecole", p)


if __name__ == "__main__":
    unittest.main()
