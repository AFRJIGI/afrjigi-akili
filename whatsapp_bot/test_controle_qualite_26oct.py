"""Controle qualite du 26 oct. :
- les textes pre-remplis des publicites (« Pour commencer, cliquez sur le lien: https://wa.me/... »,
  « Bonjour ! Puis-je en savoir plus a ce sujet ? ») etaient gardes comme questions puis « repris »
  apres l'inscription (7 conversations sur 49) ;
- les doublons de Meta faisaient la queue devant le verrou de l'eleve (570 en 48 h) avant d'etre jetes."""
import asyncio
import unittest
from pathlib import Path
from unittest import mock

import main
import test_choix_non_compris as base

PHONE = base.PHONE


class TextesPreRemplisTests(unittest.TestCase):
    setUp = base.BonjourPendantInscriptionTests.setUp
    tearDown = base.BonjourPendantInscriptionTests.tearDown

    def envoyer(self, texte):
        main.processed_messages.clear()
        return asyncio.run(main.receive_message(base.FauxRequete(texte)))

    def verifier_pas_garde(self, texte):
        self.etat = {}
        main.user_profiles.pop(PHONE, None)
        self.envoyes.clear()
        with mock.patch.object(main, "envoyer_choix"):
            self.envoyer(texte)
        profil = main.user_profiles.get(PHONE) or self.etat
        self.assertFalse(profil.get("pending_question"), texte)
        self.assertNotIn("J'ai gardé", " ".join(self.envoyes), texte)

    def test_lien_de_la_publicite(self):
        self.verifier_pas_garde("Pour commencer, cliquez sur le lien: https://wa.me/13154030671?text=Bonjour")

    def test_en_savoir_plus(self):
        self.verifier_pas_garde("Bonjour ! Puis-je en savoir plus à ce sujet ?")

    def test_reconnaissance(self):
        for texte in ["Bonjour Akili META-STUDENT AD-INDUS", "Puis-je en savoir plus ?",
                      "https://wa.me/13154030671?text=Bonjour"]:
            self.assertTrue(main.est_message_d_accueil(texte), texte)
        for texte in ["Explique-moi les fonctions logarithme ?", "Corrige cet exercice : 2x + 3 = 7",
                      "Je veux en savoir plus sur la photosynthèse, explique-moi"]:
            self.assertFalse(main.est_message_pre_rempli(texte), texte)

    def test_vraie_question_toujours_gardee(self):
        self.etat = {}
        main.user_profiles.pop(PHONE, None)
        with mock.patch.object(main, "envoyer_choix"):
            self.envoyer("Explique-moi comment calculer la dérivée de x² + 3x ?")
        profil = main.user_profiles.get(PHONE) or self.etat
        self.assertTrue(profil.get("pending_question"))


class DoublonAvantLeVerrouTests(unittest.TestCase):
    setUp = base.BonjourPendantInscriptionTests.setUp
    tearDown = base.BonjourPendantInscriptionTests.tearDown

    def test_doublon_rejete_sans_attendre_le_verrou(self):
        main.processed_messages.clear()
        with mock.patch.object(main, "reserver_message_whatsapp", return_value=False), \
                mock.patch.object(main, "prendre_verrou_eleve") as verrou, \
                mock.patch.object(main, "_receive_message_impl") as impl:
            resultat = asyncio.run(main.receive_message(base.FauxRequete("Bonjour")))
        self.assertEqual(resultat.get("reason"), "duplicate")
        verrou.assert_not_called()
        impl.assert_not_called()

    def test_premier_envoi_reserve_une_seule_fois_puis_traite(self):
        main.processed_messages.clear()
        appels = []

        def reserver(message_id):
            appels.append(message_id)
            return len(appels) == 1
        self.etat = {}
        with mock.patch.object(main, "reserver_message_whatsapp", side_effect=reserver), \
                mock.patch.object(main, "envoyer_choix"):
            resultat = asyncio.run(main.receive_message(base.FauxRequete("Bonjour")))
        self.assertNotEqual(resultat.get("reason"), "duplicate")
        self.assertEqual(appels, ["wamid.reprise.Bonjour"])


class QcmApresErreurTests(unittest.TestCase):
    """Devoir de SVT du 24 oct. : apres une erreur, il ne restait que 2 choix."""
    def test_consigne_eleve_bloque_garde_au_moins_3_options(self):
        source = Path(main.__file__).read_text(encoding="utf-8")
        self.assertIn("ne réduis jamais le choix à 2 options : propose au moins 3 options", source)


if __name__ == "__main__":
    unittest.main()
