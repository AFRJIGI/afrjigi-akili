import json
import unittest

from injecter_progressions_maths_brou import lecons
from injecter_progressions_m_sidibe import DONNEES, decider, document_base

PAQUET = json.loads(DONNEES.read_text(encoding="utf-8"))
DOCS = {d["matiere"]: d for d in PAQUET["documents"]}


def existant(doc, texte, **k):
    base = dict(id="metfpa_x", type_doc="PROGRESSION_ANNUELLE", matiere=doc["matiere"], examen="BAC_TECHNIQUE",
                niveau="TERMINALE", serie="F2", texte=texte)
    base.update(k)
    return base


class SidibeTests(unittest.TestCase):
    def test_deux_progressions_completes(self):
        self.assertEqual(set(DOCS), {"CMI", "MECANIQUE_APPLIQUEE"})
        self.assertEqual(len(lecons(DOCS["CMI"]["texte"])), 8)  # 9 chapitres, la revision n'est pas comptee
        self.assertEqual(len(lecons(DOCS["MECANIQUE_APPLIQUEE"]["texte"])), 7)
        for d in DOCS.values():
            self.assertEqual(len(d["sha256"]), 64)
            self.assertIn("Septembre", d["texte"])
            self.assertIn("Mai", d["texte"])

    def test_mecanique_appliquee_ajoutee(self):
        doc = DOCS["MECANIQUE_APPLIQUEE"]
        autre = existant(DOCS["CMI"], DOCS["CMI"]["texte"])  # autre matiere
        self.assertEqual(decider([autre], doc)[0], "CREER")

    def test_cmi_deja_presente_ou_mal_lue(self):
        doc = DOCS["CMI"]
        pdf = "\n".join(lecons(doc["texte"]))
        self.assertEqual(decider([existant(doc, pdf)], doc)[0], "DEJA")
        decision, priorite, _ = decider([existant(doc, "PROGRESSION TF2 illisible")], doc)
        self.assertEqual((decision, priorite), ("CREER", 1))
        self.assertEqual(document_base(doc, 1, "M. Sidibé")["priorite"], 1)
        # Une progression de Premiere F2 ne compte pas pour la Terminale.
        self.assertEqual(decider([existant(doc, pdf, niveau="PREMIERE")], doc)[0], "CREER")


if __name__ == "__main__":
    unittest.main()
