"""Segmentation des anciens utilisateurs pour la relance (lecture seule)."""
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("seg", Path(__file__).with_name("segmenter_anciens_utilisateurs.py"))
seg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seg)

OUI = {"consent_status": "opted_in", "scope": seg.pedagogique.SCOPE, "notice_version": seg.pedagogique.VERSION,
       "source": "whatsapp_explicit_button"}
NON = {"consent_status": "opted_out"}


def m(phone, jour, etape="akili_api", direction="inbound", **extra):
    return dict({"phone": phone, "direction": direction, "created_at": f"2026-{jour}T10:00:00+00:00",
                 "processing_stage": etape, "matiere": "MATHS", "serie": "D", "type_examen": "BAC_GENERAL"}, **extra)


MESSAGES = [
    # habitue : 3 jours de travail en septembre
    m("225001", "09-20"), m("225001", "09-21"), m("225001", "09-25"), m("225001", "09-25", direction="outbound"),
    # une seance
    m("225002", "09-22", "onboarding_choice", matiere="SVT"), m("225002", "09-22", matiere="SVT"),
    # inscription seulement
    m("225003", "09-23", "onboarding_choice"), m("225003", "09-23", "welcome_onboarding_started"),
    # actif recemment
    m("225004", "09-20"), m("225004", "10-06"),
    # enseignant
    m("225005", "09-20", enseignant_verifie=True), m("225005", "09-21"), m("225005", "09-22"),
]
LIMITE = "2026-09-30T00:00:00+00:00"


class SegmentationTests(unittest.TestCase):
    def setUp(self):
        self.infos = seg.resumer(MESSAGES)

    def test_segments(self):
        attendus = {"225001": "habitues", "225002": "une_seance", "225003": "inscription",
                    "225004": "exclu_actif", "225005": "exclu_enseignant"}
        for phone, attendu in attendus.items():
            self.assertEqual(seg.segment(self.infos[phone], LIMITE), attendu, phone)

    def test_resume(self):
        info = self.infos["225001"]
        self.assertEqual(len(info["jours_travail"]), 3)
        self.assertEqual(info["entrants"], 3)  # le message sortant ne compte pas
        self.assertEqual(info["dernier"][:10], "2026-09-25")
        self.assertEqual(self.infos["225002"]["matiere"], "SVT")

    def test_consentement(self):
        self.assertEqual(seg.consentement(OUI, None), "relancable")
        self.assertEqual(seg.consentement(None, None), "sans_accord")
        self.assertEqual(seg.consentement(OUI, NON), "stop")  # STOP l'emporte toujours
        self.assertEqual(seg.consentement(NON, None), "stop")
        promo_oui = seg.marketing.build_marketing_consent_record("opted_in")
        self.assertEqual(seg.consentement(None, promo_oui), "relancable")  # « OUI MARKETING »

    def test_lecture_des_consentements_par_lots(self):
        class Doc:
            def __init__(self, i, d):
                self.id, self._d, self.exists = i, d, d is not None

            def to_dict(self):
                return self._d

        class Ref:
            def __init__(self, coll, i):
                self.coll, self.id = coll, i

        class Coll:
            def __init__(self, nom):
                self.nom = nom

            def document(self, i):
                return Ref(self.nom, i)

        oui_id = seg.marketing.consent_document_id("225001")

        class Db:
            appels = 0

            def collection(self, nom):
                return Coll(nom)

            def get_all(self, refs):
                Db.appels += 1
                return [Doc(r.id, OUI if (r.coll == seg.pedagogique.COLLECTION and r.id == oui_id) else None)
                        for r in refs]

        accords = seg.lire_consentements(Db(), ["225001", "225002", "225003"], taille=2)
        self.assertEqual(seg.consentement(*accords["225001"]), "relancable")
        self.assertEqual(seg.consentement(*accords["225002"]), "sans_accord")
        self.assertEqual(Db.appels, 4)  # 2 lots x 2 collections

    def test_nouvel_essai_apres_coupure(self):
        class Requete:
            appels = 0

            def stream(self):
                Requete.appels += 1
                if Requete.appels < 3:
                    raise AttributeError("'_UnaryStreamMultiCallable' object has no attribute '_retry'")
                return iter(["doc"])

        self.assertEqual(seg.lire_page(Requete(), attente=lambda s: None), ["doc"])
        self.assertEqual(Requete.appels, 3)

    def test_rapport(self):
        lignes = [{"segment": "habitues", "consentement": "relancable", "matiere": "MATHS", "type_examen": "BAC_GENERAL"},
                  {"segment": "habitues", "consentement": "sans_accord", "matiere": "PC", "type_examen": "BAC_GENERAL"},
                  {"segment": "exclu_actif", "consentement": "", "matiere": "", "type_examen": ""}]
        texte = seg.rapport(lignes)
        self.assertIn("Habitués partis (3 jours de travail ou plus) : 2  -> relançables 1, sans accord 1, STOP 0", texte)
        self.assertIn("1 actifs récemment (dont 0 ont déjà accepté les rappels)", texte)


if __name__ == "__main__":
    unittest.main()
