"""Un mot du programme de philosophie (Etat, societe, travail, droit, technique...) ne fait plus
changer de matiere un eleve qui a deja choisi la sienne (test compta du 6 oct. : passage en philo)."""
import unittest
from unittest import mock

import main

PHONE = "22500000083"


def profil_compta():
    return {"type_examen": "BAC_TECHNIQUE", "serie": "G2", "matiere": "COMPTA_FIN", "mode": "etude",
            "classe": "TERMINALE", "profile_locked": True, "profile_ready": True, "matiere_confirmed": True,
            "onboarding_completed_at": "2026-10-01T10:00:00+00:00"}


class MatiereVerrouilleeTests(unittest.TestCase):
    def setUp(self):
        self.patches = [mock.patch.object(main, "send_whatsapp"), mock.patch.object(main, "sauver_etat_whatsapp"),
                        mock.patch.object(main, "envoyer_choix", lambda *a, **k: None)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        main.user_profiles.pop(PHONE, None)
        for k in [k for k in main.conversations if k.startswith(PHONE)]:
            main.conversations.pop(k, None)

    def matiere_apres(self, message, profil=None):
        profil = profil or profil_compta()
        profil = main.update_profile_from_text(profil, message)
        main.needs_onboarding(PHONE, profil, message)
        return profil["matiere"]

    def test_mots_du_programme_de_philo_ne_changent_plus_la_matiere(self):
        for message in ["Débit 601 : 500 000, Débit 4452 État : 90 000, Crédit 401 : 590 000",
                        "la société a un capital de 1 000 000", "le travail de la main d'oeuvre",
                        "je suis en BAC technique", "le droit préférentiel de souscription"]:
            self.assertEqual(self.matiere_apres(message), "COMPTA_FIN", message)

    def test_matiere_choisie_non_verrouillee(self):
        profil = profil_compta()
        profil.pop("profile_locked")
        profil["profile_ready"] = False
        with mock.patch.object(main, "is_profile_locked", return_value=False):
            self.assertEqual(self.matiere_apres("le compte 4452 État", profil), "COMPTA_FIN")
            self.assertEqual(self.matiere_apres("je veux faire de la philosophie", dict(profil)), "PHILO")

    def test_sans_matiere_les_mots_cles_servent_encore(self):
        self.assertEqual(main.detect_matiere_from_text("L'homme est-il libre ?"), "PHILO")
        self.assertIsNone(main.detect_matiere_from_text("Débit 4452 État", mots_cles_programme=False))

    def test_reponse_courte_sans_les_autres_matieres(self):
        cle = main.cle_conversation_profil(PHONE, profil_compta())
        main.conversations[cle] = [{"role": "assistant", "content": "Quel compte crédites-tu ? (a) 401 (b) 411"}]
        main.conversations[f"{PHONE}:BAC_GENERAL:D:PHILO:etude"] = [
            {"role": "assistant", "content": "Es-tu prêt à aborder un sujet de philosophie ?"}]
        with mock.patch.object(main, "load_last_assistant_context", return_value=""):
            contexte = main.get_recent_phone_context_text(PHONE, cle=cle)
        self.assertIn("401", contexte)
        self.assertNotIn("philosophie", contexte)


if __name__ == "__main__":
    unittest.main()
