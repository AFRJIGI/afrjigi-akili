"""Controle qualite : choix des conversations, transcription, lecture du JSON, rapport."""
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("cq", Path(__file__).with_name("controle_qualite.py"))
cq = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cq)


def msg(phone, direction, texte, minute):
    return {"phone": phone, "direction": direction, "text": texte, "created_at": f"2026-10-04T10:{minute:02d}:00+00:00",
            "type_examen": "BAC_TECHNIQUE", "serie": "F1", "matiere": "CMI", "mode": "etude"}


MESSAGES = [
    # Vraie seance de travail
    msg("2250100000001", "inbound", "Propose-moi un exercice", 1),
    msg("2250100000001", "outbound", "Une vis de diametre 10 mm...", 2),
    msg("2250100000001", "inbound", "78,5", 3),
    msg("2250100000001", "outbound", "Exact ! Calcule maintenant la contrainte.", 4),
    msg("2250100000001", "inbound", "je ne sais pas", 5),
    # Inscription seulement
    msg("2250100000002", "inbound", "Bonjour", 1),
    msg("2250100000002", "outbound", "Bienvenue sur Akili. Quel niveau...", 2),
    msg("2250100000002", "inbound", "c", 3),
    msg("2250100000002", "outbound", "Quelle série du BAC Technique ?", 4),
    msg("2250100000002", "inbound", "e", 5),
]


class ControleQualiteTests(unittest.TestCase):
    def test_seules_les_seances_de_travail_sont_relues(self):
        self.assertEqual(list(cq.regrouper(MESSAGES)), ["2250100000001"])

    def test_echantillon_reproductible(self):
        conv = {f"p{i}": [] for i in range(50)}
        self.assertEqual(cq.echantillon(conv, 5, "2026-10-04"), cq.echantillon(conv, 5, "2026-10-04"))
        self.assertEqual(len(cq.echantillon(conv, 5, "x")), 5)

    def test_transcription_et_profil(self):
        liste = cq.regrouper(MESSAGES)["2250100000001"]
        texte = cq.transcription(liste)
        self.assertIn("[10:01] ELEVE : Propose-moi un exercice", texte)
        self.assertIn("AKILI : Exact !", texte)
        self.assertEqual(cq.profil_de(liste), "BAC_TECHNIQUE, F1, CMI, etude")
        self.assertEqual(cq.masquer("2250100000001"), "...0001")

    def test_lecture_json(self):
        self.assertEqual(cq.lire_resultat('```json\n{"note": 4, "resume": "ok"}\n```')["note"], 4)
        self.assertEqual(cq.lire_resultat('Voici : {"note": 2, "problemes": []} fin')["note"], 2)
        self.assertIsNone(cq.lire_resultat("pas de json"))
        self.assertEqual(cq.lire_resultat('{"note": 5}')["problemes"], [])

    def test_rapport(self):
        resultats = [
            {"eleve": "...0001", "profil": "BAC_TECHNIQUE, F1, CMI", "note": 2, "resume": "Erreur de calcul validee",
             "problemes": [{"type": "erreur_contenu", "gravite": "grave", "extrait": "Exact ! 80 mm2",
                            "explication": "La bonne valeur est 78,5 mm2"}]},
            {"eleve": "...0003", "profil": "BEPC, ANGLAIS", "note": 5, "resume": "Tres bien", "problemes": []},
        ]
        texte = cq.rapport(resultats, "2026-10-04")
        self.assertIn("Note moyenne : 3.5 / 5", texte)
        self.assertIn("erreur_contenu : 1", texte)
        self.assertIn("Problemes graves a relire (1)", texte)
        self.assertIn("La bonne valeur est 78,5 mm2", texte)
        self.assertNotIn("2250100000001", texte)


if __name__ == "__main__":
    unittest.main()
