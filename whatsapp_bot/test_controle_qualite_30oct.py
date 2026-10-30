"""Controle qualite du 30 oct. : l'eleve envoie une photo et Akili perd le fil (il redemande une etape deja
faite, ou dit ne pas avoir recu le document). L'historique joint au message photo reste valable pour savoir
ou en est l'eleve ; seul l'exercice en cours vient du nouveau document."""
import unittest
from pathlib import Path

import main

SOURCE = Path(main.__file__).read_text(encoding="utf-8")


class HistoriqueAvecPhotoTests(unittest.TestCase):
    def test_historique_reste_valable_pour_la_progression(self):
        self.assertIn("tiens compte de ce que l'eleve a deja fait ou dit dans l'historique", SOURCE)
        self.assertIn("ne lui redemande jamais une etape qu'il a deja realisee", SOURCE)
        self.assertIn("il reste valable pour savoir ou en est l'eleve", SOURCE)

    def test_le_nouveau_document_reste_l_exercice_en_cours(self):
        self.assertIn("Ne continue PAS l'ancien exercice de l'historique si le nouveau document presente "
                      "un exercice different", SOURCE)

    def test_ancienne_formulation_retiree(self):
        # « informatif seulement, ne sert plus a identifier l'exercice actuel » faisait ignorer la progression.
        self.assertNotIn("informatif seulement", SOURCE)


class QcmReposeTests(unittest.TestCase):
    def test_consigne_bot_couvre_toutes_les_repetitions(self):
        self.assertIn("Chaque fois que tu reposes la même question, pour quelque raison que ce soit, "
                      "garde exactement les mêmes options aux mêmes lettres", SOURCE)
        self.assertIn("n'en retire aucune (surtout pas la bonne réponse)", SOURCE)


if __name__ == "__main__":
    unittest.main()
