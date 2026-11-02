"""gerer_ecoles.py : import idempotent d'une liste d'ecole, sans reseau."""
import random
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent / "whatsapp_bot"))
import ecole  # noqa: E402
import gerer_ecoles  # noqa: E402


class Faux:
    def __init__(self):
        self.d = {}

    def collection(self, nom):
        faux = self

        class Doc:
            def __init__(self, i):
                self.i = i

            def get(self):
                v = faux.d.get((nom, self.i))
                return mock.Mock(exists=v is not None, to_dict=lambda: dict(v or {}))

            def set(self, data, merge=False):
                faux.d[(nom, self.i)] = dict(data)

        class Coll:
            def document(self, i):
                return Doc(i)

        return Coll()


class ImportTests(unittest.TestCase):
    def test_import_idempotent_et_prof_double(self):
        db = Faux()
        lignes, erreurs = ecole.lire_liste(
            "role,classe,classes,matieres,nom\neleve,6e A,,,\neleve,Tle D,,,\nprof,,Tle D,SVT,M. Koffi\n",
            "TST", {"SVT"}, random.Random(5))
        self.assertEqual(erreurs, [])
        sorties = gerer_ecoles.enregistrer(db, "TST", lignes)
        self.assertEqual([s["statut"] for s in sorties], ["nouveau"] * 3)
        prof_code = lignes[2]["code"]
        self.assertIn(("enseignants_codes", prof_code), db.d)             # espace enseignant WhatsApp
        self.assertEqual(db.d[("ecoles_codes", prof_code)]["role"], "prof")
        self.assertEqual(db.d[("ecoles_codes", lignes[0]["code"])]["classe"], "6e A")
        self.assertNotIn("nom", db.d[("ecoles_codes", lignes[0]["code"])])  # jamais de nom d'eleve
        second = gerer_ecoles.enregistrer(db, "TST", lignes)
        self.assertEqual([s["statut"] for s in second], ["deja_importe"] * 3)

    def test_simulation_n_ecrit_rien(self):
        db = Faux()
        lignes, _ = ecole.lire_liste("role,classe\neleve,3e\n", "TST", set(), random.Random(6))
        gerer_ecoles.enregistrer(db, "TST", lignes, simuler=True)
        self.assertEqual(db.d, {})


if __name__ == "__main__":
    unittest.main()
