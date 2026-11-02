"""Ecoles partenaires (0121) : codes, rattachement d'un eleve ou d'un professeur, liste CSV, rapport par classe.
Ecole fictive TST ; aucun nom d'eleve nulle part."""
import random
import unittest
from unittest import mock

import ecole
import espace_enseignant as prof
import main
from test_qualite_corrections import PHONE, Base, texte

CODE = "TST-K7M4Q"
PROF_CODE = "TST-P4R2X"
HASH = main.consent_document_id(PHONE)


class ModuleTests(unittest.TestCase):
    def test_extraire_code(self):
        self.assertEqual(ecole.extraire_code("tst-k7m4q"), CODE)
        self.assertEqual(ecole.extraire_code("Mon code est TST K7M4Q"), CODE)
        self.assertEqual(ecole.extraire_code("TST.K7M4Q merci"), CODE)
        self.assertIsNone(ecole.extraire_code("bonjour akili"))          # pas de chiffre
        self.assertIsNone(ecole.extraire_code("explique moi la photosynthese des plantes vertes svt 4"))
        self.assertIsNone(ecole.extraire_code("PROF-DIABY-4821") and None)  # teste plus bas via prof
        self.assertIsNone(ecole.extraire_code("TST-K7M4Q " + "mot " * 8))  # trop long : une phrase, pas un code

    def test_code_prof_passe_en_premier(self):
        self.assertEqual(prof.extraire_code("PROF-DIABY-4821"), "PROF-DIABY-4821")

    def test_generation(self):
        rng = random.Random(1)
        existants = set()
        for _ in range(300):
            code = ecole.nouveau_code("TST", existants, rng)
            self.assertRegex(code, r"^TST-[A-HJ-NP-Z2-9]{5}$")
            self.assertTrue(any(c.isdigit() for c in code))
            self.assertNotIn(code, existants)
            existants.add(code)
        with self.assertRaises(ValueError):
            ecole.nouveau_code("T1", set())

    def test_liste_csv(self):
        csv_texte = ("role,classe,classes,matieres,nom,code\n"
                     "eleve,6e A,,,,\n"
                     "eleve,Tle D,,,,TST-A2B3C\n"
                     "prof,,Tle D;3e,SVT;MATHS,M. Koffi,\n"
                     "eleve,Licence 2,,,,\n"          # classe inconnue
                     "prof,,3e,ASTROLOGIE,,\n"         # matiere inconnue
                     "eleve,5e,,,,AUT-12345\n")       # code d'une autre ecole
        lignes, erreurs = ecole.lire_liste(csv_texte, "TST", {"SVT", "MATHS"}, random.Random(2))
        self.assertEqual(len(lignes), 3)
        self.assertEqual(len(erreurs), 3)
        self.assertEqual(lignes[1]["code"], "TST-A2B3C")
        self.assertTrue(all(ecole.code_valide(l["code"]) and l["code"].startswith("TST-") for l in lignes))
        self.assertEqual(len({l["code"] for l in lignes}), 3)
        self.assertEqual(lignes[2]["classes"], ["Tle D", "3e"])

    def test_liste_point_virgule(self):
        lignes, erreurs = ecole.lire_liste("role;classe\neleve;2nde C\n", "TST", set(), random.Random(3))
        self.assertEqual((len(lignes), erreurs), (1, []))

    def test_rapport_eleves_et_classeur(self):
        import os, tempfile
        codes = [{"code": "TST-AAAA1", "role": "eleve", "classe": "Tle D", "eleve_hash": "h1"},
                 {"code": "TST-AAAA2", "role": "eleve", "classe": "Tle D", "eleve_hash": "h2"},
                 {"code": "TST-AAAA3", "role": "eleve", "classe": "Tle D"},
                 {"code": "TST-OFF22", "role": "eleve", "classe": "Tle D", "actif": False}]
        activite = [{"code": "TST-AAAA1", "jour": "2026-11-03", "echanges": 4, "matieres": {"SVT": 3, "MATHS": 1}},
                    {"code": "TST-AAAA1", "jour": "2026-11-05", "echanges": 2, "matieres": {"SVT": 2}}]
        tests = [{"eleve": "h1", "phase": "debut", "cree_le": "2026-11-03T10:00", "score": 1, "total": 3, "matiere": "SVT", "chapitre": "Digestion"},
                 {"eleve": "h1", "phase": "fin", "cree_le": "2026-11-06T10:00", "score": 3, "total": 3, "score_debut": 1}]
        lignes = ecole.rapport_eleves(codes, activite, tests, [], "2026-11-02", "2026-11-08")
        self.assertEqual([x["code"] for x in lignes], ["TST-AAAA1", "TST-AAAA2", "TST-AAAA3"])  # le code desactive n'y est pas
        a, b, c = lignes
        self.assertEqual((a["statut"], a["jours_actifs"], a["echanges"], a["derniere_activite"], a["progression"]),
                         ("Actif", 2, 6, "2026-11-05", 2))
        self.assertEqual(a["matieres_texte"], "SVT (5), Maths (1)")
        self.assertEqual((b["statut"], c["statut"]), ("Connecté, inactif cette période", "Pas encore connecté"))
        classes = ecole.rapport_classes(codes, None, activite, tests, [], "2026-11-02", "2026-11-08")
        with tempfile.TemporaryDirectory() as d:
            chemin = os.path.join(d, "rapport.xlsx")
            ecole.ecrire_classeur(chemin, "Ecole de test", classes, lignes, "2026-11-02", "2026-11-08")
            import openpyxl
            wb = openpyxl.load_workbook(chemin)
            self.assertEqual(wb.sheetnames, ["Par classe", "Par élève (code)", "À reprendre en classe"])
            self.assertEqual(wb["Par élève (code)"].max_row, 4)
            self.assertEqual(wb["Par classe"]["A2"].value, "Tle D")

    def test_rapport(self):
        codes = [
            {"code": "TST-AAAA1", "role": "eleve", "classe": "Tle D", "eleve_hash": "h1"},
            {"code": "TST-AAAA2", "role": "eleve", "classe": "Tle D", "eleve_hash": "h2"},
            {"code": "TST-AAAA3", "role": "eleve", "classe": "Tle D"},
            {"code": "TST-BBBB1", "role": "eleve", "classe": "3e", "eleve_hash": "h3"},
            {"code": "TST-PPPP1", "role": "prof", "classes": ["Tle D"]},
        ]
        activite = [
            {"code": "TST-AAAA1", "jour": "2026-11-03", "echanges": 5, "matieres": {"SVT": 3, "MATHS": 2}},
            {"code": "TST-AAAA1", "jour": "2026-11-04", "echanges": 2, "matieres": {"SVT": 2}},
            {"code": "TST-AAAA1", "jour": "2026-10-01", "echanges": 9, "matieres": {"SVT": 9}},  # hors periode
        ]
        tests = [
            {"eleve": "h1", "phase": "debut", "matiere": "SVT", "chapitre": "Digestion", "score": 1, "total": 3, "cree_le": "2026-11-03T10:00"},
            {"eleve": "h2", "phase": "debut", "matiere": "SVT", "chapitre": "Digestion", "score": 0, "total": 3, "cree_le": "2026-11-03T11:00"},
            {"eleve": "h1", "phase": "fin", "matiere": "SVT", "chapitre": "Digestion", "score": 3, "total": 3, "score_debut": 1, "cree_le": "2026-11-05T10:00"},
            {"eleve": "inconnu", "phase": "debut", "matiere": "SVT", "chapitre": "X", "score": 3, "total": 3, "cree_le": "2026-11-03T10:00"},
        ]
        revisions = [{"eleve": "h1", "envoyee_le": "2026-11-04T08:00", "repondu": True, "juste": True},
                     {"eleve": "h2", "envoyee_le": "2026-11-04T08:00", "repondu": True, "juste": None}]
        classes = ecole.rapport_classes(codes, None, activite, tests, revisions, "2026-11-02", "2026-11-08")
        self.assertEqual([c["classe"] for c in classes], ["3e", "Tle D"])
        d = [c for c in classes if c["classe"] == "Tle D"][0]
        self.assertEqual((d["codes"], d["lies"], d["actifs"], d["echanges"]), (3, 2, 1, 7))
        self.assertEqual(d["matieres"], {"SVT": 5, "MATHS": 2})
        self.assertEqual((d["tests_debut"], d["tests_fin"], d["gain_moyen"]), (2, 1, 2.0))
        self.assertEqual((d["revisions"], d["revisions_justes"]), (1, 1))
        self.assertEqual(d["inactifs"], ["TST-AAAA2"])
        self.assertEqual(d["non_lies"], ["TST-AAAA3"])
        self.assertEqual(d["chapitres_faibles"], [("SVT", "Digestion", 17, 2)])
        sortie = ecole.texte_rapport("Ecole test", classes, "2026-11-02", "2026-11-08")
        self.assertIn("Tle D : 2/3 élèves connectés (67 %)", sortie)
        self.assertIn("à reprendre en classe : SVT — Digestion", sortie)
        self.assertIn("TST-AAAA2", sortie)


class FauxFirestore:
    def __init__(self):
        self.docs = {
            ecole.COLLECTION_ECOLES: {"TST": {"nom": "Ecole de test", "actif": True}},
            ecole.COLLECTION_CODES: {
                CODE: {"ecole": "TST", "role": "eleve", "classe": "Tle D", "actif": True},
                "TST-D9D9D": {"ecole": "TST", "role": "eleve", "classe": "2nde C", "actif": True, "eleve_hash": "autre"},
                "TST-OFF22": {"ecole": "TST", "role": "eleve", "classe": "3e", "actif": False},
                PROF_CODE: {"ecole": "TST", "role": "prof", "actif": True},
            },
            prof.COLLECTION_CODES: {PROF_CODE: {"nom": "M. Koffi", "matieres": ["SVT"], "classes": ["Tle D", "3e"], "actif": True, "phone": ""}},
        }
        self.activite = []

    def collection(self, nom):
        base = self

        class Doc:
            def __init__(self, i):
                self.i = i

            def get(self):
                d = base.docs.get(nom, {}).get(self.i)
                return mock.Mock(exists=d is not None, to_dict=lambda: dict(d or {}))

            def update(self, champs):
                base.docs[nom][self.i].update(champs)

            def set(self, data, merge=False):
                if nom == ecole.COLLECTION_ACTIVITE:
                    base.activite.append((self.i, data))
                else:
                    base.docs.setdefault(nom, {}).setdefault(self.i, {}).update(data)

        class Coll:
            def document(self, i):
                return Doc(i)

            def add(self, data):
                pass

        return Coll()


class ParcoursTests(Base):
    def setUp(self):
        super().setUp()
        self.db = FauxFirestore()
        self.listes = []
        self.extra = [
            mock.patch.object(main, "feedback_db", self.db),
            mock.patch.object(main, "ask_matiere", side_effect=lambda phone, serie: self.listes.append(("matiere", serie))),
            mock.patch.object(main, "envoyer_choix", side_effect=lambda *a, **k: None),
            mock.patch.object(main, "load_last_assistant_context", return_value=""),
        ]
        for p in self.extra:
            p.start()

    def tearDown(self):
        for p in self.extra:
            p.stop()
        super().tearDown()

    def test_nouvel_eleve_avec_code(self):
        r = self.envoyer(texte("Bonjour Akili", "n0"))
        r = self.envoyer(texte("tst-k7m4q", "n1"))
        self.assertEqual(r["reason"], "ecole_code_eleve")
        self.assertEqual((self.etat["type_examen"], self.etat["serie"]), ("BAC_GENERAL", "D"))
        self.assertEqual((self.etat["ecole_id"], self.etat["code_eleve"], self.etat["classe_ecole"]), ("TST", CODE, "Tle D"))
        self.assertEqual(self.etat["nom_ecole"], "Ecole de test")
        self.assertEqual(self.db.docs[ecole.COLLECTION_CODES][CODE]["eleve_hash"], HASH)
        self.assertIn("tu es en Tle D (Ecole de test)", self.envoyes[-1])
        self.assertEqual(self.listes[-1], ("matiere", "D"))     # il ne lui reste qu'a choisir sa matiere
        self.assertEqual(self.etat["onboarding_step"], "matiere")

    def test_eleve_deja_inscrit_garde_sa_matiere(self):
        self.etat = {"type_examen": "BAC_GENERAL", "serie": "D", "matiere": "SVT", "matiere_confirmed": True,
                     "mode": "etude", "profile_ready": True, "user_type": "ELEVE"}
        r = self.envoyer(texte(CODE, "d1"))
        self.assertEqual(r["reason"], "ecole_code_eleve")
        self.assertEqual(self.etat["matiere"], "SVT")
        self.assertEqual(self.etat["code_eleve"], CODE)
        self.assertEqual(self.etat["onboarding_step"], "")
        self.assertIn("Continue", self.envoyes[-1])
        self.assertEqual(self.listes, [])

    def test_meme_numero_reecrit_son_code(self):
        self.db.docs[ecole.COLLECTION_CODES][CODE]["eleve_hash"] = HASH
        self.assertEqual(self.envoyer(texte(CODE, "m1"))["reason"], "ecole_code_eleve")

    def test_code_pris_par_un_autre_numero(self):
        r = self.envoyer(texte("TST-D9D9D", "p1"))
        self.assertEqual(r["reason"], "ecole_code_deja_utilise")
        self.assertNotIn("code_eleve", self.etat)
        self.assertEqual(self.db.docs[ecole.COLLECTION_CODES]["TST-D9D9D"]["eleve_hash"], "autre")

    def test_code_inconnu_ou_desactive(self):
        for i, code in enumerate(["TST-ZZZZ9", "TST-OFF22"]):
            self.assertEqual(self.envoyer(texte(code, f"i{i}"))["reason"], "ecole_code_invalide")
        self.assertIn("Je ne reconnais pas ce code", self.envoyes[-1])

    def test_ecole_desactivee(self):
        self.db.docs[ecole.COLLECTION_ECOLES]["TST"]["actif"] = False
        self.assertEqual(self.envoyer(texte(CODE, "x1"))["reason"], "ecole_code_invalide")

    def test_phrase_normale_ne_declenche_rien(self):
        self.envoyer(texte("Bonjour Akili", "q0"))
        self.envoyer(texte("Aide moi sur le chapitre 4 de SVT", "q1"))
        self.assertNotIn("ecole_id", self.etat)

    def test_professeur_de_l_ecole(self):
        r = self.envoyer(texte(PROF_CODE, "pr1"))
        self.assertEqual(r["reason"], "enseignant_active")
        self.assertTrue(self.etat["enseignant_verifie"])
        self.assertEqual((self.etat["ecole_id"], self.etat["matiere"]), ("TST", "SVT"))
        self.assertNotIn("code_eleve", self.etat)
        self.assertEqual(self.db.docs[prof.COLLECTION_CODES][PROF_CODE]["phone"], PHONE)

    def test_activite_ecrite_pour_un_eleve_d_ecole_seulement(self):
        main.noter_activite_ecole({"ecole_id": "TST", "code_eleve": CODE, "classe_ecole": "Tle D", "matiere": "SVT"})
        main.noter_activite_ecole({"matiere": "SVT"})
        main.noter_activite_ecole({"ecole_id": "TST", "matiere": "SVT"})  # enseignant : pas de code eleve
        self.assertEqual(len(self.db.activite), 1)
        cle, data = self.db.activite[0]
        self.assertRegex(cle, rf"^{CODE}__\d{{4}}-\d{{2}}-\d{{2}}$")
        self.assertEqual((data["ecole"], data["code"], data["classe"]), ("TST", CODE, "Tle D"))

    def test_resultat_mini_test_etiquete(self):
        ajouts = []
        coll = mock.Mock()
        coll.add.side_effect = ajouts.append
        with mock.patch.object(main.feedback_db, "collection", return_value=coll, create=True):
            main.enregistrer_resultat_mini_test(PHONE, {"ecole_id": "TST", "code_eleve": CODE, "classe_ecole": "Tle D"}, {"phase": "debut"})
            main.enregistrer_resultat_mini_test(PHONE, {}, {"phase": "debut"})
        self.assertEqual((ajouts[0]["ecole_id"], ajouts[0]["code_eleve"]), ("TST", CODE))
        self.assertNotIn("ecole_id", ajouts[1])
        self.assertEqual(ajouts[0]["eleve"], HASH)


if __name__ == "__main__":
    unittest.main()
