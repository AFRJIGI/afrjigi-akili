"""Controle qualite du 9 oct. : une demande d'aide envoyee apres « Un peu » part chez Akili (l'avis est garde),
et le texte des flyers (« Bonjour Akili, je participe au pilote AfrJigi ») n'est plus repris comme une question."""
import unittest
from unittest import mock

import main
import test_avis_boutons as avis


class DemandeApresAvisTests(avis.AvisBoutonsTests):
    def test_demande_d_aide_apres_un_peu(self):
        self.envoyer(avis.bouton("avis_un_peu", "Un peu", "q1"))
        self.assertEqual(self.envoyes[-1], main.MESSAGE_DEMANDE_COMMENTAIRE)
        main.processed_messages.clear()
        akili = []
        with mock.patch.object(main, "detect_marketing_consent_command", return_value=None), \
                mock.patch.object(main, "answer_learning_request",
                                  side_effect=lambda phone, profile, text, **k: akili.append(text)):
            self.envoyer(avis.texte("Mets moi sur la voie de la re formulation", "q2"))
        self.assertEqual(self.avis[-1], ("un_peu", "Mets moi sur la voie de la re formulation"))
        self.assertEqual(akili, ["Mets moi sur la voie de la re formulation"])
        self.assertNotIn(main.MESSAGE_MERCI_COMMENTAIRE, self.envoyes)
        self.assertNotIn("attente_commentaire_avis", main.user_profiles[avis.PHONE])

    def test_un_vrai_commentaire_reste_un_commentaire(self):
        self.envoyer(avis.bouton("avis_non", "Non", "q3"))
        main.processed_messages.clear()
        with mock.patch.object(main, "detect_marketing_consent_command", return_value=None):
            resultat = self.envoyer(avis.texte("Tes réponses sont trop longues", "q4"))
        self.assertEqual(resultat["reason"], "commentaire_avis")
        self.assertEqual(self.envoyes[-1], main.MESSAGE_MERCI_COMMENTAIRE)


class DetectionTests(unittest.TestCase):
    def test_demandes_d_aide(self):
        for texte in ("Mets moi sur la voie de la re formulation", "Explique encore stp", "Comment on fait ?",
                      "Donne moi un autre exercice", "Je comprends pas", "on continue"):
            self.assertTrue(main.est_demande_d_aide(texte), texte)
        for texte in ("Trop long", "Tes réponses sont trop longues", "c'était lent"):
            self.assertFalse(main.est_demande_d_aide(texte), texte)

    def test_messages_d_accueil(self):
        for texte in ("Bonjour Akili, je participe au pilote AfrJigi", "Bonjour Akili", "slt", "Cc akili"):
            self.assertTrue(main.est_message_d_accueil(texte), texte)
        for texte in ("Bonjour, explique-moi les fonctions logarithmes", "Je participe au pilote, aide moi en maths ?",
                      "Calcule la dérivée de x²"):
            self.assertFalse(main.est_message_d_accueil(texte), texte)


if __name__ == "__main__":
    unittest.main()


class TexteDesFlyersTests(unittest.TestCase):
    def setUp(self):
        self.etat, self.envoyes = {}, []
        noop = lambda *a, **k: None
        self.patches = [
            mock.patch.object(main, "send_whatsapp", side_effect=lambda phone, msg, *a, **k: self.envoyes.append(msg)),
            mock.patch.object(main, "send_whatsapp_boutons", return_value=True),
            mock.patch.object(main, "send_whatsapp_liste", return_value=False, create=True),
            mock.patch.object(main, "send_whatsapp_typing_indicator", side_effect=noop),
            mock.patch.object(main, "reserver_message_whatsapp", return_value=True),
            mock.patch.object(main, "charger_etat_whatsapp", side_effect=lambda phone: dict(self.etat)),
            mock.patch.object(main, "sauver_etat_whatsapp",
                              side_effect=lambda phone, p: self.etat.clear() or self.etat.update(p)),
            mock.patch.object(main, "save_whatsapp_event", side_effect=noop),
            mock.patch.object(main, "maybe_send_marketing_consent_prompt", side_effect=noop),
            mock.patch.object(main, "detect_marketing_consent_command", return_value=None),
            mock.patch.object(main, "answer_learning_request", side_effect=AssertionError("pas d'appel a Akili")),
        ]
        for p in self.patches:
            p.start()
        main.processed_messages.clear()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        main.user_profiles.pop(avis.PHONE, None)
        main.processed_messages.clear()

    def test_le_texte_des_flyers_n_est_pas_garde(self):
        import asyncio
        asyncio.run(main.receive_message(avis.FauxRequete(
            avis.texte("Bonjour Akili, je participe au pilote AfrJigi", "f1"))))
        profil = main.user_profiles[avis.PHONE]
        self.assertNotIn("pending_question", profil)
        self.assertFalse(any("ta question" in m for m in self.envoyes), self.envoyes)


class _Reponse:
    def __init__(self, donnees):
        self._donnees = donnees

    def json(self):
        return self._donnees


class MatiereEtDocumentTests(unittest.TestCase):
    """Questions d'une autre matiere et transcription des photos (controle qualite du 9 oct.)."""
    PHONE = "22500000091"

    def setUp(self):
        import tempfile
        self.envoyes = []
        self.photo = tempfile.NamedTemporaryFile(suffix="_whatsapp_image.jpg", delete=False)
        self.photo.write(b"\xff\xd8\xff fausse image")
        self.photo.close()
        self.patches = [
            mock.patch.object(main, "send_whatsapp", side_effect=lambda p, m, *a, **k: self.envoyes.append(m) or True),
            mock.patch.object(main, "send_whatsapp_typing_indicator"),
            mock.patch.object(main, "sauver_etat_whatsapp"), mock.patch.object(main, "sauver_historique_conv"),
            mock.patch.object(main, "charger_historique_conv", return_value=[]),
            mock.patch.object(main, "journal_session_ajouter"),
            mock.patch.object(main, "send_vector_formula_if_needed"),
            mock.patch.object(main, "mini_test_jour_actif"),
            mock.patch.object(main, "mark_first_learning_request", side_effect=lambda p, prof: prof),
            mock.patch.object(main, "p0_enabled", return_value=False),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        import os
        for p in self.patches:
            p.stop()
        os.unlink(self.photo.name)
        main.user_profiles.pop(self.PHONE, None)
        for k in [k for k in main.conversations if k.startswith(self.PHONE)]:
            main.conversations.pop(k, None)

    def profil(self, matiere, serie="D"):
        return {"type_examen": "BAC_GENERAL", "serie": serie, "matiere": matiere, "mode": "etude",
                "profile_locked": True, "profile_ready": True, "onboarding_completed_at": "2026-10-01"}

    def repondre(self, profil, texte, reponse_akili, media=None, transcription=None):
        appels = []

        def faux_post(url, files=None, timeout=None, **k):
            appels.append(url)
            return _Reponse(transcription or {"error": "x"})

        with mock.patch.object(main, "get_akili_response", return_value=reponse_akili), \
                mock.patch.object(main.requests, "post", side_effect=faux_post):
            main.answer_learning_request(self.PHONE, profil, texte, media_file=media)
        return appels

    def test_question_de_philo_en_espagnol(self):
        profil = self.profil("ESPAGNOL", "A2")
        self.repondre(profil, "Quelle est la différence entre la conscience de l'homme et celle de l'animal",
                      "[AUTRE_MATIERE: Philosophie]\nBonne question. Qu'est-ce que la conscience selon toi ?")
        self.assertEqual(profil["matiere"], "PHILO")
        self.assertTrue(self.envoyes[-1].startswith("Ta question relève de Philosophie : je passe en Philosophie."))
        self.assertIn("revenir en Espagnol", self.envoyes[-1])

    def test_reponse_courte_ou_matiere_proche_sans_changement(self):
        profil = self.profil("ESPAGNOL", "A2")
        self.repondre(profil, "b", "[AUTRE_MATIERE: Philosophie]\nOui, c'est juste.")
        self.assertEqual(profil["matiere"], "ESPAGNOL")
        self.assertNotIn("[AUTRE_MATIERE", self.envoyes[-1])
        profil = self.profil("FRANCAIS", "A2")
        self.repondre(profil, "Comment faire une bonne dissertation sur la liberté",
                      "[AUTRE_MATIERE: Philosophie]\nCommence par définir les termes.")
        self.assertEqual(profil["matiere"], "FRANCAIS")

    def test_la_photo_est_retenue_comme_enonce(self):
        profil = self.profil("MATHS")
        texte = "Exercice 2\n1. Montre que f est dérivable sur R.\n2. Calcule f'(x)."
        appels = self.repondre(profil, "voici mon exercice", "Commence par la question 1. Que sais-tu de f ?",
                               media=self.photo.name, transcription={"texte": texte, "matiere": "Mathematiques"})
        self.assertTrue(appels[-1].endswith("/transcrire-document"))
        cle = f"{self.PHONE}:BAC_GENERAL:D:MATHS:etude"
        self.assertEqual(main.enonce_en_cours(profil, cle), main.PREFIXE_DOCUMENT_ELEVE + texte)
        self.assertEqual(profil["matiere"], "MATHS")
        self.assertEqual(len(self.envoyes), 1)  # pas de message de changement de matiere

    def test_photo_d_histoire_en_maths(self):
        profil = self.profil("MATHS")
        self.repondre(profil, "aide moi", "Complète la première phrase : les premiers Européens sont les... ?",
                      media=self.photo.name,
                      transcription={"texte": "Complète : Les premiers européens qui s'installent...",
                                     "matiere": "Histoire-Geographie"})
        self.assertEqual(profil["matiere"], "HG")
        self.assertTrue(self.envoyes[-1].startswith("Ton document est un exercice d'Histoire-Géographie"))
        cle = f"{self.PHONE}:BAC_GENERAL:D:HG:etude"
        self.assertTrue(main.enonce_en_cours(profil, cle).startswith(main.PREFIXE_DOCUMENT_ELEVE))
        self.assertEqual(len(main.conversations[cle]), 2)  # le premier echange suit l'eleve

    def test_photo_de_maths_en_physique_reste_en_physique(self):
        profil = self.profil("PC")
        self.repondre(profil, "aide moi", "Quelle est la formule de la vitesse ?", media=self.photo.name,
                      transcription={"texte": "Un mobile parcourt 100 m en 20 s. Calcule sa vitesse.",
                                     "matiere": "Mathematiques"})
        self.assertEqual(profil["matiere"], "PC")
        self.assertTrue(main.enonce_en_cours(profil, f"{self.PHONE}:BAC_GENERAL:D:PC:etude"))

    def test_pas_de_transcription_en_mode_examen(self):
        profil = dict(self.profil("MATHS"), mode="examen")
        appels = self.repondre(profil, "voici ma copie", "Réponse enregistrée.", media=self.photo.name,
                               transcription={"texte": "Ma copie : x = 2", "matiere": "Mathematiques"})
        self.assertFalse(any(u.endswith("/transcrire-document") for u in appels))

    def test_lycee_professionnel_hors_champ(self):
        self.assertTrue(main.is_other_or_concours("Je suis au professionnel"))
        self.assertTrue(main.is_other_or_concours("je fais le lycée professionnel"))
        self.assertTrue(main.is_other_or_concours("3eme année BT électronique"))
        self.assertFalse(main.is_other_or_concours("BAC technique G2"))


class SecondControleDu9OctTests(unittest.TestCase):
    """Second controle qualite du 9 oct. : « Français » seul, audio qui cite deux matieres, « À » accentue,
    defi du lendemain en pleine seance."""
    PROFIL = {"type_examen": "BEPC", "serie": "BEPC", "matiere": "MATHS", "mode": "etude", "profile_ready": True,
              "matiere_confirmed": True, "profile_locked": True}

    def test_nom_de_matiere_seul(self):
        with mock.patch.object(main, "load_last_assistant_context",
                               return_value="Développe (x+3)². Te souviens-tu de la formule pour (a+b)² ?"):
            self.assertEqual(main.nom_de_matiere_seul("225", dict(self.PROFIL), "Français"), "FRANCAIS")
            self.assertEqual(main.nom_de_matiere_seul("225", dict(self.PROFIL), "le français stp"), "FRANCAIS")
            self.assertIsNone(main.nom_de_matiere_seul("225", dict(self.PROFIL), "Maths"))
            self.assertIsNone(main.nom_de_matiere_seul("225", dict(self.PROFIL),
                                                       "le français c'est dur pour moi"))

    def test_francais_reponse_a_une_question_sur_les_matieres(self):
        with mock.patch.object(main, "load_last_assistant_context",
                               return_value="Quelle matière pose problème à Kadiatou ? a. HG b. Français"):
            self.assertIsNone(main.nom_de_matiere_seul("225", dict(self.PROFIL), "Français"))

    def test_audio_qui_cite_deux_matieres(self):
        audio = ("S'il vous plaît passons du du je je je fais en maths le mot donc on peut français "
                 "C'est le français qui me pratique français")
        self.assertTrue(main.est_demande_changement_matiere(audio, "MATHS"))
        self.assertEqual(main.matiere_demandee(dict(self.PROFIL), audio), "FRANCAIS")
        self.assertIsNone(main.matiere_demandee(dict(self.PROFIL), "je veux faire maths et français et anglais"))

    def test_lettre_accentuee(self):
        with mock.patch.object(main, "get_recent_phone_context_text", return_value="assistant: a. dynamomètre ?"):
            self.assertIn("uniquement : A\n", main.build_short_answer_prompt("225", "À"))
            self.assertIn("uniquement : b\n", main.build_short_answer_prompt("225", "b"))

    def test_defi_du_lendemain_attend_le_dernier_message(self):
        from datetime import datetime, timedelta, timezone
        recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        ancien = (datetime.now(timezone.utc) - timedelta(hours=20)).isoformat()
        with mock.patch.object(main, "charger_session_bilan", return_value={"derniere_activite": ancien}), \
                mock.patch.object(main, "charger_etat_whatsapp", return_value={"dernier_message_eleve": recent}):
            derniere = main.derniere_activite_eleve("225", {"derniere_activite": ancien})
        self.assertEqual(derniere.isoformat(), recent)
