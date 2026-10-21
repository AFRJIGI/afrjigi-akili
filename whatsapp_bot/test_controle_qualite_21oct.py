"""Controle qualite du 21 oct. : un eleve inscrit par erreur en BAC General ecrit « je suis en 3eme, je
cherche le BEPC » a la question de la serie ; Akili lui reposait la meme question pendant 6 heures."""
import asyncio
import unittest
from unittest import mock

import main
import test_choix_non_compris as base

PHONE = base.PHONE


class ChangementDeNiveauPendantInscriptionTests(unittest.TestCase):
    setUp = base.BonjourPendantInscriptionTests.setUp
    tearDown = base.BonjourPendantInscriptionTests.tearDown

    def envoyer(self, texte):
        return asyncio.run(main.receive_message(base.FauxRequete(texte)))

    def verifier_bepc(self, texte):
        self.etat = {"type_examen": "BAC_GENERAL", "serie": "TOUTES", "matiere": "MATHS",
                     "onboarding_step": "serie_general"}
        main.user_profiles.pop(PHONE, None)
        main.processed_messages.clear()
        self.envoyes.clear()
        with mock.patch.object(main, "ask_matiere") as liste:
            self.envoyer(texte)
        profil = main.user_profiles.get(PHONE) or self.etat
        self.assertEqual((profil.get("type_examen"), profil.get("serie")), ("BEPC", "BEPC"), texte)
        self.assertNotIn("Quelle série du BAC Général", " ".join(self.envoyes), texte)
        liste.assert_called_once()

    def test_phrase_longue(self):
        self.verifier_bepc("Nom je suis en classe de 3eme je cherche bpc")

    def test_phrase_courte(self):
        self.verifier_bepc("Non je suis en 3e")


if __name__ == "__main__":
    unittest.main()


class VerrouSurCloudRunTests(unittest.TestCase):
    """Le verrou de 0102 n'etait jamais pris : NameError (classe de fausse base absente), rattrapee en silence."""
    def test_pris_sur_cloud_run(self):
        appels = []

        async def attendre(db, phone):
            appels.append(phone)
            return "jeton"
        with mock.patch.dict("os.environ", {"K_SERVICE": "afrjigi-whatsapp"}), \
                mock.patch.object(main.verrou_eleve, "attendre", side_effect=attendre):
            self.assertEqual(asyncio.run(main.prendre_verrou_eleve("22501")), "jeton")
        self.assertEqual(appels, ["22501"])

    def test_jamais_pendant_les_tests(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("K_SERVICE", None)
            os.environ.pop("WHATSAPP_VERROU_ELEVE", None)
            with mock.patch.object(main.verrou_eleve, "attendre") as attendre:
                self.assertIsNone(asyncio.run(main.prendre_verrou_eleve("22501")))
            attendre.assert_not_called()

    def test_plus_aucune_reference_a_une_classe_absente(self):
        import pathlib
        source = pathlib.Path(main.__file__).read_text(encoding="utf-8")
        self.assertNotIn("_Firestore" + "DeTest", source)
