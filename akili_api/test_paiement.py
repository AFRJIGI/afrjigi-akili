import unittest
from datetime import datetime

import paiement


class FauxDoc:
    def __init__(self, donnees):
        self._d = donnees

    @property
    def exists(self):
        return self._d is not None

    def to_dict(self):
        return dict(self._d) if self._d is not None else None


class FauxRef:
    def __init__(self, store, cle):
        self.store, self.cle = store, cle

    def get(self):
        return FauxDoc(self.store.get(self.cle))

    def set(self, donnees, merge=False):
        self.store[self.cle] = {**self.store.get(self.cle, {}), **donnees} if merge else dict(donnees)

    def update(self, donnees):
        self.store[self.cle].update(donnees)


class FauxDb:
    def __init__(self):
        self.store = {}

    def collection(self, nom):
        outer = self

        class Col:
            def document(self, cle):
                return FauxRef(outer.store.setdefault(nom, {}), cle)
        return Col()


def faux_post(reponse):
    appels = []

    def post(url, charge):
        appels.append((url, charge))
        return reponse
    post.appels = appels
    return post


class CreerPaiementTests(unittest.TestCase):
    def test_cree_la_reference_le_lien_et_la_fiche(self):
        db, post = FauxDb(), faux_post({"success": True, "url": "https://paiementpro.net/pay?s=1"})
        res = paiement.creer_paiement(db, "2250712345678@afrjigi.com", "PP-X", "https://api.test/", "jeton", "omciv2",
                                      post=post, maintenant=1000)
        self.assertEqual(res, {"url": "https://paiementpro.net/pay?s=1", "reference": "AKILI-2250712345678-1000"})
        url, charge = post.appels[0]
        self.assertEqual(url, paiement.URL_INITIALISATION)
        self.assertEqual(charge["merchantId"], "PP-X")
        self.assertEqual(charge["amount"], 2000)
        self.assertEqual(charge["channel"], "OMCIV2")
        self.assertEqual(charge["customerPhoneNumber"], "2250712345678")
        self.assertEqual(charge["notificationURL"], "https://api.test/webhook/paiementpro/jeton")
        self.assertEqual(charge["returnURL"], "https://api.test/paiement/retour")
        fiche = db.store["paiements"]["AKILI-2250712345678-1000"]
        self.assertEqual((fiche["statut"], fiche["montant"]), ("en_attente", 2000))

    def test_refus_de_paiement_pro_ne_cree_pas_de_fiche(self):
        db = FauxDb()
        with self.assertRaises(paiement.ErreurPaiement):
            paiement.creer_paiement(db, "2250712345678@afrjigi.com", "PP-X", "https://api.test", "jeton", "MOMO",
                                    post=faux_post({"success": False}))
        self.assertEqual(db.store.get("paiements", {}), {})

    def test_compte_non_whatsapp_ou_config_absente(self):
        with self.assertRaises(paiement.ErreurPaiement):
            paiement.creer_paiement(FauxDb(), "a@b.com", "PP-X", "https://api.test", "jeton", "MOMO", post=faux_post({}))
        with self.assertRaises(paiement.ErreurPaiement):
            paiement.creer_paiement(FauxDb(), "2250712345678@afrjigi.com", "", "https://api.test", "jeton", "MOMO",
                                    post=faux_post({}))

    def test_canal_obligatoire_et_connu(self):
        for canal in (None, "", "CARD", "WAVE"):
            with self.assertRaises(paiement.ErreurPaiement):
                paiement.creer_paiement(FauxDb(), "2250712345678@afrjigi.com", "PP-X", "https://api.test", "jeton",
                                        canal, post=faux_post({"success": True, "url": "u"}))


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.db = FauxDb()
        self.db.store["paiements"] = {"R1": {"email": "225@afrjigi.com", "montant": 2000, "statut": "en_attente"}}
        self.actives = []
        self.activer = lambda email, jours: self.actives.append((email, jours))

    def notifier(self, **params):
        return paiement.traiter_notification(self.db, params, self.activer, merchant_id="PP-X")

    def test_paiement_reussi_active_une_seule_fois(self):
        self.assertEqual(self.notifier(referenceNumber="R1", amount="2000", responsecode="0", merchantId="PP-X"),
                         "active")
        self.assertEqual(self.actives, [("225@afrjigi.com", 30)])
        self.assertEqual(self.notifier(referenceNumber="R1", amount="2000", responsecode="0"), "deja_paye")
        self.assertEqual(len(self.actives), 1)

    def test_echec_n_active_pas(self):
        self.assertEqual(self.notifier(referenceNumber="R1", amount="2000", responsecode="-1"), "echec")
        self.assertEqual(self.actives, [])
        self.assertEqual(self.db.store["paiements"]["R1"]["statut"], "echec")

    def test_montant_different_n_active_pas(self):
        self.assertEqual(self.notifier(referenceNumber="R1", amount="100", responsecode="0"), "montant_incorrect")
        self.assertEqual(self.actives, [])

    def test_reference_inconnue_ou_absente(self):
        self.assertEqual(self.notifier(referenceNumber="ZZZ", amount="2000", responsecode="0"), "inconnue")
        self.assertEqual(self.notifier(amount="2000", responsecode="0"), "ignoree")
        self.assertEqual(self.actives, [])

    def test_autre_marchand_ignore(self):
        self.assertEqual(self.notifier(referenceNumber="R1", amount="2000", responsecode="0", merchantId="PP-AUTRE"),
                         "ignoree")
        self.assertEqual(self.actives, [])

    def test_montant_avec_decimales(self):
        self.assertEqual(self.notifier(referenceNumber="R1", amount="2000.00", responsecode="0"), "active")


class DiversTests(unittest.TestCase):
    def test_token(self):
        self.assertTrue(paiement.token_valide("abc", "abc"))
        self.assertFalse(paiement.token_valide("abd", "abc"))
        self.assertFalse(paiement.token_valide("", ""))
        self.assertFalse(paiement.token_valide(None, "abc"))

    def test_expiration_prolongee_ou_repartie(self):
        now = datetime(2026, 11, 7, 12, 0, 0)
        self.assertEqual(paiement.nouvelle_expiration(None, 30, now), datetime(2026, 12, 7, 12).isoformat())
        encore = datetime(2026, 11, 20).isoformat()
        self.assertEqual(paiement.nouvelle_expiration(encore, 30, now), datetime(2026, 12, 20).isoformat())
        passee = datetime(2026, 10, 1).isoformat()
        self.assertEqual(paiement.nouvelle_expiration(passee, 30, now), datetime(2026, 12, 7, 12).isoformat())


if __name__ == "__main__":
    unittest.main()
