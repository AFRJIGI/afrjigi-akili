"""Classement des progressions E et F dans les matieres du menu WhatsApp."""
import ast
import importlib.util
import json
import unittest
from pathlib import Path

ICI = Path(__file__).parent
spec = importlib.util.spec_from_file_location("inj", ICI / "injecter_progressions_techniques_e_f.py")
inj = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inj)

BOT = ast.parse((ICI / "whatsapp_bot" / "main.py").read_text(encoding="utf-8"))
MATIERES_BOT = next(
    ast.literal_eval(n.value) for n in BOT.body
    if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "MATIERES_TECHNIQUE_PAR_SERIE" for t in n.targets)
)
PLAN = inj.plan_documents(json.loads(inj.INVENTAIRE.read_text(encoding="utf-8"))["inventaire"])


class ClassementTests(unittest.TestCase):
    def test_chaque_progression_va_dans_une_matiere_du_menu_de_sa_serie(self):
        for doc in PLAN:
            codes = [code for code, _ in MATIERES_BOT[doc["serie"]]]
            self.assertIn(doc["matiere"], codes, doc["titre"])

    def test_toutes_les_series_e_et_f_sont_couvertes(self):
        self.assertEqual({d["serie"] for d in PLAN}, {"E", "F1", "F2", "F3", "F4", "F7"})
        self.assertGreaterEqual(len(PLAN), 90)
        self.assertEqual(len({d["id"] for d in PLAN}), len(PLAN))
        self.assertEqual(len({d["url"] for d in PLAN}), len(PLAN))

    def test_exemples(self):
        cas = {
            ("BAC_F1", "Progression  CMI TF1"): ("CMI", "F1", "TERMINALE"),
            ("BAC_E", "PRogression etude de fabrication 1ERE E"): ("ETUDE_FABRICATION", "E", "PREMIERE"),
            ("BAC_F4", "PROGRESSION RDM BAF4 graphe 1ère, Tle"): ("RDM", "F4", "PREMIERE_TERMINALE"),
            ("BAC_F4", "PROGRSSION TECHNO bac F4  2e, 1e, Tle"): ("TECHNO_GENIE_CIVIL", "F4", "TOUS"),
            ("BAC_F7", "Biochimie cours 1ère F7"): ("BIOCHIMIE", "F7", "PREMIERE"),
            ("BAC_F3", "TF3ESSAI"): ("MESURES_ESSAIS", "F3", "TERMINALE"),
            ("BAC_F2", "9 1  Technologie schémas"): ("TECHNO_SCHEMAS", "F2", "TOUS"),
        }
        for (categorie, titre), attendu in cas.items():
            self.assertEqual(inj.classer(categorie, titre), attendu, titre)

    def test_hors_champ_ignore(self):
        for categorie, titre in [("BAC_F1", "PROGRESSION TLE F1"), ("BAC_E", "ANGLAIS Tle E & F1 F2 F3 2024 2025"),
                                 ("BAC_F3", "TF3 EE"), ("BAC_F7", "EPS 22 23 PROGRESSION PEDAGOGIQUE")]:
            self.assertIsNone(inj.classer(categorie, titre), titre)


class ExtractionTests(unittest.TestCase):
    def test_types_de_fichiers(self):
        import io as _io, zipfile
        b = _io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            z.writestr("word/document.xml",
                       "<w:document><w:body><w:p><w:r><w:t>PROGRESSION TOURNAGE TF1</w:t></w:r></w:p>"
                       "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Septembre</w:t></w:r></w:p></w:tc>"
                       "<w:tc><w:p><w:r><w:t>Le&#231;on 1 : </w:t></w:r><w:r><w:t>filetage</w:t></w:r></w:p></w:tc>"
                       "</w:tr></w:tbl></w:body></w:document>")
        self.assertEqual(inj.type_fichier(b.getvalue()), "docx")
        self.assertEqual(inj.texte_docx(b.getvalue()), "PROGRESSION TOURNAGE TF1\nSeptembre | Leçon 1 : filetage")

        b = _io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            z.writestr("xl/sharedStrings.xml", "<sst><si><t>Semaine</t></si><si><t>Leçon</t></si><si><t>Cotation</t></si></sst>")
            z.writestr("xl/worksheets/sheet1.xml",
                       '<worksheet><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
                       '<row r="2"><c r="A2"><v>3</v></c><c r="B2" t="s"><v>2</v></c></row></sheetData></worksheet>')
        self.assertEqual(inj.type_fichier(b.getvalue()), "xlsx")
        self.assertEqual(inj.texte_xlsx(b.getvalue()), "Semaine | Leçon\n3 | Cotation")

        doc = b"\xd0\xcf\x11\xe0" + b"\x00" * 50 + "PROGRESSION FRAISAGE semaine 1 : surfaçage".encode("utf-16-le")
        self.assertEqual(inj.type_fichier(doc), "doc")
        self.assertIn("PROGRESSION FRAISAGE semaine 1 : surfaçage", inj.texte_doc(doc))
        self.assertEqual(inj.type_fichier(b"%PDF-1.4 ..."), "pdf")
        self.assertEqual(inj.type_fichier(b"<!DOCTYPE html><html><body>Erreur</body></html>"), "html")


class GoogleTests(unittest.TestCase):
    def test_adresses_de_telechargement_direct(self):
        ident = "1AbCdEfGhIjKlMnOpQrStUvWxYz012345"
        self.assertEqual(inj.adresses_google(f"https://docs.google.com/document/d/{ident}/edit"),
                         [f"https://docs.google.com/document/d/{ident}/export?format=docx"])
        self.assertEqual(inj.adresses_google(f"https://drive.google.com/file/d/{ident}/view"),
                         [f"https://drive.usercontent.google.com/download?id={ident}&export=download&confirm=t"])
        page = f'<a href="https://drive.google.com/uc?export=download&id={ident}">'.encode()
        self.assertEqual(len(inj.adresses_google("https://accounts.google.com/x", page)), 1)
        self.assertEqual(inj.adresses_google("https://www.fomesoutra.com/x", b"<html></html>"), [])


if __name__ == "__main__":
    unittest.main()
