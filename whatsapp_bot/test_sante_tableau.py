"""Verification de sante horaire et tableau de bord."""
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import main
import tableau_de_bord as tdb

NOW = datetime(2026, 10, 4, 18, 0, tzinfo=timezone.utc)


def m(phone, jours, direction="inbound", matiere="MATHS"):
    return {"phone": phone, "direction": direction, "matiere": matiere,
            "created_at": (NOW - timedelta(days=jours, hours=1)).isoformat()}


MESSAGES = [m("p1", 1), m("p2", 1), m("p3", 1), m("p1", 0), m("p2", 0, matiere="ECO"), m("p4", 0),
            m("p1", 0, direction="outbound"), m("p9", 9)]
AVIS = [
    {"type": "avis_seance", "note": "oui", "created_at": NOW.isoformat()},
    {"type": "avis_seance", "note": "non", "created_at": NOW.isoformat()},
    {"type": "commentaire_avis", "note": "non", "feedback": "Trop <long>", "matiere_detectee": "HG", "created_at": NOW.isoformat()},
    {"type": "retour_ambigu", "statut": "a_verifier", "feedback": "aucune contradiction", "created_at": NOW.isoformat()},
]


class StatsTests(unittest.TestCase):
    def test_chiffres(self):
        st = tdb.calculer_stats(MESSAGES, AVIS, NOW)
        self.assertEqual(st["aujourd_hui"]["actifs"], 3)
        self.assertEqual(st["aujourd_hui"]["messages"], 3)
        self.assertEqual(st["hier"]["actifs"], 3)
        self.assertEqual(st["hier_meme_heure"]["actifs"], 3)  # messages d'hier a 17 h, avant 18 h
        self.assertEqual(st["aujourd_hui"]["retour"], 66.7)  # p1 et p2 revenus sur 3
        self.assertEqual(len(st["serie"]), 7)
        self.assertEqual(dict(st["matieres"]), {"MATHS": 2, "ECO": 1})
        self.assertEqual(st["notes"], {"oui": 1, "non": 1})
        self.assertEqual([c["texte"] for c in st["commentaires"]], ["Trop <long>"])  # l'avis "a verifier" est ecarte

    def test_page_sans_numero_et_echappee(self):
        st = tdb.calculer_stats(MESSAGES, AVIS, NOW)
        page = tdb.rendre_html(st, sante={"ok": False, "at": NOW.isoformat(),
                                          "verifications": [{"nom": "WhatsApp (Meta)", "ok": False, "detail": "paiement"}]},
                               echecs_jour=4, qualite={"jour": "2026-10-04", "moyenne": 3.4, "nb": 20, "graves": 3},
                               revisions_jour=12, genere_le="04/10/2026 18:00")
        self.assertIn("Trop &lt;long&gt;", page)
        self.assertNotIn("Trop <long>", page)
        self.assertNotIn("p1", page)
        self.assertIn("problème détecté", page)
        self.assertIn("3.4 / 5", page)
        self.assertIn("66.7 %", page)  # tuile ; les barres arrondissent (67%)
        self.assertIn('class="tuile alerte"', page)


class SanteTests(unittest.TestCase):
    def test_tout_va_bien_puis_echec(self):
        ok = lambda: (True, "ok")
        with mock.patch.object(main, "_sante_firestore", ok), mock.patch.object(main, "_sante_api", ok), \
             mock.patch.object(main, "_sante_whatsapp", ok), mock.patch.object(main, "_sante_livraison", ok):
            self.assertTrue(main.verifier_sante()["ok"])
        with mock.patch.object(main, "_sante_firestore", ok), mock.patch.object(main, "_sante_api", ok), \
             mock.patch.object(main, "_sante_whatsapp", side_effect=RuntimeError("401")), \
             mock.patch.object(main, "_sante_livraison", ok):
            resultat = main.verifier_sante()
        self.assertFalse(resultat["ok"])
        self.assertIn("RuntimeError", resultat["verifications"][2]["detail"])

    def test_whatsapp_bloque(self):
        class Reponse:
            status_code = 200

            def json(self):
                return {"quality_rating": "GREEN", "health_status": {"can_send_message": "BLOCKED", "entities": [
                    {"errors": [{"error_code": 141006, "error_description": "Paiement en attente"}]}]}}

        with mock.patch.object(main.requests, "get", return_value=Reponse()):
            ok, detail = main._sante_whatsapp()
        self.assertFalse(ok)
        self.assertIn("Paiement en attente", detail)

    def test_appels_sip_ne_declenchent_pas_d_alerte(self):
        def reponse(erreurs):
            class R:
                status_code = 200

                def json(self):
                    return {"quality_rating": "GREEN", "health_status": {"can_send_message": "LIMITED", "entities": [
                        {"entity_type": "APP", "errors": [{"error_code": 1, "error_description": e} for e in erreurs]}]}}
            return R()

        sip = ("WhatsApp Business calling cannot use SIP because it is not enabled",
               "This app cannot use SIP for WhatsApp Business calling because it has not configured a SIP server")
        with mock.patch.object(main.requests, "get", return_value=reponse(sip)):
            ok, detail = main._sante_whatsapp()
        self.assertTrue(ok, detail)
        with mock.patch.object(main.requests, "get", return_value=reponse(sip + ("Messaging limit reached",))):
            ok, detail = main._sante_whatsapp()
        self.assertFalse(ok)  # une autre limite, elle, reste une alerte

    def test_champ_inconnu_ne_declenche_pas_d_alerte(self):
        class Erreur:
            status_code = 400

            def json(self):
                return {"error": {"code": 100, "message": "nonexisting field (health_status)"}}

        class Bon:
            status_code = 200

            def json(self):
                return {"quality_rating": "GREEN"}

        with mock.patch.object(main.requests, "get", side_effect=[Erreur(), Bon()]):
            ok, detail = main._sante_whatsapp()
        self.assertTrue(ok, detail)


class AccesTests(unittest.TestCase):
    class Requete:
        def __init__(self, cle="", entete=""):
            self.query_params = {"cle": cle}
            self.headers = {"X-Akili-Tache": entete}

    def test_tableau_protege(self):
        with mock.patch.dict("os.environ", {"TABLEAU_CLE": "secret123"}):
            self.assertEqual(asyncio.run(main.page_tableau_de_bord(self.Requete("faux"))).status_code, 403)
            main._cache_tableau.update({"at": None, "page": None})
            with mock.patch.object(main, "construire_tableau", return_value="<html>ok</html>"):
                page = asyncio.run(main.page_tableau_de_bord(self.Requete("secret123")))
            self.assertEqual(page.status_code, 200)
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(asyncio.run(main.page_tableau_de_bord(self.Requete(""))).status_code, 403)

    def test_tache_sante_protegee(self):
        with mock.patch.dict("os.environ", {"TACHES_SECRET": "s3"}):
            self.assertEqual(asyncio.run(main.tache_sante(self.Requete(entete="non"))).status_code, 403)


if __name__ == "__main__":
    unittest.main()
