import json
import unittest

from injecter_documents_m_coulibaly import DONNEES, corps, decider, decision_finale, documents_base, suites

PAQUET = json.loads(DONNEES.read_text(encoding="utf-8"))
SOURCES = {s["fichier"]: s for s in PAQUET["sources"]}


def base_de(*docs):
    par = {}
    for d in docs:
        par.setdefault(d["matiere"], []).append((d, suites(d["texte"])))
    return list(docs), par


class DonneesTests(unittest.TestCase):
    def test_tout_est_la(self):
        types = [s["type_doc"] for s in PAQUET["sources"]]
        self.assertEqual(types.count("PROGRAMME"), 12)
        self.assertEqual(types.count("FORMAT_EPREUVE"), 7)
        self.assertEqual(types.count("PROGRESSION_ANNUELLE"), 7)
        self.assertFalse(any("BT " in s["fichier"] for s in PAQUET["sources"]))  # BT : hors perimetre

    def test_extraits_lisibles_par_l_api(self):
        for s in PAQUET["sources"]:
            if s["type_doc"] != "PROGRESSION_ANNUELLE":
                for m in s["morceaux"]:
                    self.assertLessEqual(len(m), 2800, s["fichier"])
        programme_td = SOURCES["14. Prog Educt maths TD CND 0923.pdf"]
        self.assertNotIn("Mot de Madame la Ministre", " ".join(programme_td["morceaux"]))
        self.assertTrue(any("Leçon" in m and "Exemple de situation" in m for m in programme_td["morceaux"]))

    def test_cibles(self):
        college = SOURCES["1.Formats des évaluations en maths au Collège D2021-2.pdf"]
        self.assertIn(["BEPC", "BEPC"], college["cibles"])
        docs = documents_base(college, "M. Coulibaly")
        self.assertEqual(len(docs), len(college["morceaux"]) * 4)
        self.assertEqual(len({d["id"] for d in docs}), len(docs))
        self.assertEqual(SOURCES["PROGRESSION DE ECONOMIE D’ENTREPRISE Tle G1&G2.docx"]["matiere"], "ECO")


class DecisionTests(unittest.TestCase):
    def test_nouveau_deja_partiel(self):
        s = SOURCES["7.Format du Bac série C D2021-2.pdf"]
        texte = "\n".join(corps(m) for m in s["morceaux"])
        vide = base_de(dict(id="x", matiere="MATHS", texte="limites et continuite"))
        self.assertEqual(decider(s, *vide)[0], "NOUVEAU")
        plein = base_de(dict(id="ancien_format_c", matiere="MATHS", texte=texte.upper()))  # autre extraction
        self.assertEqual(decider(s, *plein)[0], "DEJA")
        moitie = base_de(dict(id="ancien", matiere="MATHS", texte=texte[: len(texte) * 2 // 5]))
        self.assertEqual(decider(s, *moitie)[0], "PARTIEL")
        meme_fichier = base_de(dict(id="y", matiere="MATHS", texte="", sha256_source=s["sha256"]))
        self.assertEqual(decider(s, *meme_fichier)[0], "DEJA")

    def test_programme_remplace_l_ancien_bloc(self):
        s = SOURCES["14. Prog Educt maths TD CND 0923.pdf"]
        bloc = "Mot de Madame la Ministre " + "\n".join(corps(m) for m in s["morceaux"]).upper()
        ancien = dict(id="knowledge_base_MATHS_D__PROGRAMME_TD", matiere="MATHS", type_doc="PROGRAMME", texte=bloc)
        sujet = dict(id="sujet_bac_d", matiere="MATHS", type_doc="SUJET", texte=bloc)
        decision, _, remplaces = decision_finale(s, *base_de(sujet, ancien))
        self.assertEqual((decision, remplaces), ("AJOUTER", ["knowledge_base_MATHS_D__PROGRAMME_TD"]))
        docs = documents_base(s, "M. Coulibaly", remplaces)
        self.assertTrue(all(d["remplace_ids"] == remplaces for d in docs))

    def test_deja_presents_ignores(self):
        for f in ["MATHEMATIQUES - Progressions annuelles_DPFC_2026_2027.pdf",
                  "PROGRESSION DE ECONOMIE GENERALE Tle G.docx", "PROGRESSION DE INITIATION ECONOMIQUE 2nde G1&G2.docx"]:
            self.assertEqual(decision_finale(SOURCES[f], *base_de())[0], "IGNORER")
        self.assertEqual(decision_finale(SOURCES["7.Format du Bac série C D2021-2.pdf"], *base_de())[0], "AJOUTER")

    def test_autre_matiere_ignoree(self):
        s = SOURCES["PROGRESSION DE SCIENCES ECONOMIQUES ET SOCIALES Tle B.docx"]
        maths = base_de(dict(id="m", matiere="MATHS", texte=s["morceaux"][0]))
        self.assertEqual(decider(s, *maths)[0], "NOUVEAU")


if __name__ == "__main__":
    unittest.main()
