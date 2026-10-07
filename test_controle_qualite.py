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


class FauxDoc:
    def __init__(self, donnees):
        self.donnees = donnees

    def to_dict(self):
        return dict(self.donnees)


class FausseRequete:
    def __init__(self, db, apres=None, taille=None):
        self.db, self.apres, self.taille = db, apres, taille

    def where(self, *a):
        return self

    def order_by(self, *a):
        return self

    def select(self, champs):
        self.db.champs = champs
        return self

    def limit(self, n):
        return FausseRequete(self.db, self.apres, n)

    def start_after(self, doc):
        return FausseRequete(self.db, doc, self.taille)

    def stream(self):
        self.db.appels += 1
        if self.db.pannes:
            self.db.pannes -= 1
            raise RuntimeError("503 Stream removed (ping timeout)")
        debut = 0 if self.apres is None else self.db.docs.index(self.apres) + 1
        return iter(self.db.docs[debut:debut + self.taille])


class FausseDb:
    def __init__(self, n, pannes=0):
        self.docs = [FauxDoc({"phone": "225", "created_at": f"2026-10-06T10:{i:04d}"}) for i in range(n)]
        self.pannes, self.appels, self.champs = pannes, 0, None

    def collection(self, nom):
        return FausseRequete(self)


class LectureParPagesTests(unittest.TestCase):
    def test_toutes_les_pages_et_champs_utiles(self):
        db = FausseDb(25)
        messages = cq.lire_messages(db, "2026-10-05", taille_page=10)
        self.assertEqual(len(messages), 25)
        self.assertEqual(db.appels, 3)
        self.assertIn("matiere", db.champs)

    def test_nouvel_essai_apres_coupure(self):
        cq_sleep = __import__("time").sleep
        __import__("time").sleep = lambda s: None
        try:
            db = FausseDb(5, pannes=1)
            self.assertEqual(len(cq.lire_messages(db, "2026-10-05", taille_page=10)), 5)
        finally:
            __import__("time").sleep = cq_sleep


class TranscriptionLongueTests(unittest.TestCase):
    def test_message_de_850_caracteres_entier(self):
        liste = [msg("2250100000009", "outbound", "x" * 850, 1)]
        self.assertIn("x" * 850, cq.transcription(liste))
        self.assertNotIn("suite non recopiee", cq.transcription(liste))

    def test_message_tres_long_marque(self):
        texte = cq.transcription([msg("2250100000009", "outbound", "y" * 2000, 1)])
        self.assertIn("[suite non recopiee pour la relecture]", texte)
        self.assertIn("[liste]", cq.GRILLE)
