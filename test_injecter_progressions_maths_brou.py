import json
import unittest

from injecter_progressions_maths_brou import DONNEES, decider, document_base, lecons, series_couvertes

PAQUET = json.loads(DONNEES.read_text(encoding="utf-8"))
DOCS = {d["classe_source"]: d for d in PAQUET["documents"]}


def existant(doc, texte=None, **k):
    base = dict(id="metfpa_x", type_doc="PROGRESSION_ANNUELLE", matiere="MATHS", examen="BAC_TECHNIQUE",
                niveau=doc["niveau"], serie=doc["serie"], texte=doc["texte"] if texte is None else texte)
    base.update(k)
    return base


class DonneesTests(unittest.TestCase):
    def test_seize_progressions_completes(self):
        self.assertEqual(len(PAQUET["documents"]), 16)
        self.assertEqual(len({d["sha256"] for d in PAQUET["documents"]}), 16)
        for d in PAQUET["documents"]:
            self.assertGreaterEqual(len(lecons(d["texte"])), 4, d["classe_source"])
            self.assertIn(d["edition_source"], {"Septembre 2026", "Septembre 2025"})
        self.assertIn("dans ℝ", DOCS["2T1"]["texte"])  # le symbole R des formules Word est garde

    def test_series_des_secondes_t(self):
        self.assertEqual(series_couvertes(DOCS["2T1"]["serie"]), ["E", "F1", "F2", "F3"])
        self.assertEqual(series_couvertes(DOCS["2T2"]["serie"]), ["F4"])
        self.assertEqual(series_couvertes(DOCS["2T3"]["serie"]), ["F7"])
        self.assertEqual(series_couvertes(DOCS["TF1,2,3"]["serie"]), ["F1", "F2", "F3"])


class DecisionTests(unittest.TestCase):
    def test_classe_absente_ajoutee(self):
        doc = DOCS["2T1"]
        autre = existant(DOCS["TB"])  # Terminale B : autre classe
        self.assertEqual(decider([autre], doc)[0], "CREER")

    def test_meme_progression_deja_presente(self):
        doc = DOCS["TB"]
        # Texte d'un PDF : memes lecons, mise en page differente, apostrophes droites.
        pdf = "\n".join(t.replace(" ", "\n", 1) for t in lecons(doc["texte"]))
        self.assertEqual(decider([existant(doc, texte=pdf)], doc)[0], "DEJA")
        self.assertEqual(decider([existant(doc, sha256=doc["sha256"])], doc)[0], "DEJA")

    def test_pdf_mal_lu_version_word_prioritaire(self):
        doc = DOCS["1B"]
        decision, priorite, _ = decider([existant(doc, texte="PROGRESSION 1B illisible")], doc)
        self.assertEqual((decision, priorite), ("CREER", 1))
        self.assertEqual(document_base(doc, priorite, "M. Brou")["priorite"], 1)

    def test_serie_differente_ne_compte_pas(self):
        doc = DOCS["2T2"]  # F4
        f7 = existant(DOCS["2T3"])
        self.assertEqual(decider([f7], doc)[0], "CREER")


if __name__ == "__main__":
    unittest.main()
