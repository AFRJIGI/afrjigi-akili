"""19 oct. : un seul message a la fois par eleve, toutes copies Cloud Run confondues (verrou_eleve.py)."""
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import verrou_eleve as v


class AlreadyExists(Exception):
    pass


class FailedPrecondition(Exception):
    pass


class _Instantane:
    def __init__(self, donnees, update_time):
        self.exists = donnees is not None
        self._d = dict(donnees) if donnees else None
        self.update_time = update_time

    def to_dict(self):
        return dict(self._d) if self._d else None


class _Ref:
    def __init__(self, base, cle):
        self.base, self.cle = base, cle

    def create(self, d):
        if self.cle in self.base.docs:
            raise AlreadyExists()
        self.base.ecrire(self.cle, d)

    def get(self):
        d, t = self.base.docs.get(self.cle, (None, None))
        return _Instantane(d, t)

    def _verifier(self, option):
        if option is not None and self.base.docs.get(self.cle, (None, None))[1] != option:
            raise FailedPrecondition()

    def update(self, d, option=None):
        self._verifier(option)
        self.base.ecrire(self.cle, dict(self.base.docs[self.cle][0], **d))

    def delete(self, option=None):
        self._verifier(option)
        self.base.docs.pop(self.cle, None)


class FausseBase:
    """create atomique, preconditions sur la date de derniere ecriture : comme Firestore."""
    def __init__(self):
        self.docs, self.horloge = {}, 0

    def ecrire(self, cle, d):
        self.horloge += 1
        self.docs[cle] = (dict(d), self.horloge)

    def collection(self, nom):
        base = self

        class _C:
            def document(self, cle):
                return _Ref(base, f"{nom}/{cle}")
        return _C()

    def write_option(self, last_update_time=None):
        return last_update_time


T0 = datetime(2026, 10, 19, 23, 0, tzinfo=timezone.utc)


class VerrouTests(unittest.TestCase):
    def setUp(self):
        self.db = FausseBase()

    def test_un_seul_detenteur(self):
        self.assertTrue(v.prendre(self.db, "225", "a", T0))
        self.assertFalse(v.prendre(self.db, "225", "b", T0 + timedelta(seconds=5)))
        self.assertTrue(v.prendre(self.db, "226", "b", T0))  # un autre eleve n'attend pas

    def test_liberation_puis_reprise(self):
        v.prendre(self.db, "225", "a", T0)
        v.liberer(self.db, "225", "b")  # pas son verrou : rien ne change
        self.assertFalse(v.prendre(self.db, "225", "b", T0))
        v.liberer(self.db, "225", "a")
        self.assertTrue(v.prendre(self.db, "225", "b", T0))

    def test_verrou_expire_repris(self):
        v.prendre(self.db, "225", "a", T0)
        self.assertTrue(v.prendre(self.db, "225", "b", T0 + v.DUREE_BAIL + timedelta(seconds=1)))
        v.liberer(self.db, "225", "a")  # l'ancienne copie se reveille : elle ne supprime pas le verrou de b
        self.assertFalse(v.prendre(self.db, "225", "c", T0 + v.DUREE_BAIL + timedelta(seconds=2)))

    def test_reprise_concurrente_d_un_verrou_expire(self):
        v.prendre(self.db, "225", "a", T0)
        plus_tard = T0 + v.DUREE_BAIL + timedelta(seconds=1)
        lu = _Ref(self.db, "verrous_eleves/225").get
        # b lit le verrou expire, mais c le reprend avant que b n'ecrive : b doit echouer.
        def get_puis_c():
            inst = lu()
            self.db.ecrire("verrous_eleves/225", {"jeton": "c", "expire_at": plus_tard + v.DUREE_BAIL})
            return inst
        with mock.patch.object(_Ref, "get", lambda self: get_puis_c()):
            self.assertFalse(v.prendre(self.db, "225", "b", plus_tard))

    def test_attente_puis_obtention(self):
        v.prendre(self.db, "225", "a", datetime.now(timezone.utc))
        pauses = []

        async def dormir(s):
            pauses.append(s)
            if len(pauses) == 3:
                v.liberer(self.db, "225", "a")  # le premier message est fini
        jeton = asyncio.run(v.attendre(self.db, "225", attente_max=10, pas=0.5, dormir=dormir))
        self.assertIsNotNone(jeton)
        self.assertEqual(len(pauses), 3)

    def test_attente_trop_longue_laisse_passer(self):
        v.prendre(self.db, "225", "a", datetime.now(timezone.utc))

        async def dormir(s):
            pass
        self.assertIsNone(asyncio.run(v.attendre(self.db, "225", attente_max=2, pas=0.5, dormir=dormir)))

    def test_firestore_en_panne_laisse_passer(self):
        class Panne:
            def collection(self, nom):
                raise RuntimeError("503")
        self.assertIsNone(asyncio.run(v.attendre(Panne(), "225")))


class ReceptionTests(unittest.TestCase):
    def test_expediteur(self):
        import main
        corps = {"entry": [{"changes": [{"value": {"messages": [{"from": "22501", "id": "x"}]}}]}]}
        self.assertEqual(main.expediteur_du_message(corps), "22501")
        self.assertIsNone(main.expediteur_du_message({"entry": [{"changes": [{"value": {"statuses": []}}]}]}))
        self.assertIsNone(main.expediteur_du_message({}))

    def test_verrou_libere_meme_en_cas_d_erreur(self):
        import main
        libere = []

        class Req:
            async def json(self):
                return {"entry": [{"changes": [{"value": {"messages": [{"from": "22502", "id": "y"}]}}]}]}

        async def prendre(phone):
            return "jeton"

        async def boum(request):
            raise RuntimeError("x")
        with mock.patch.object(main, "prendre_verrou_eleve", side_effect=prendre), \
                mock.patch.object(main, "liberer_verrou_eleve", side_effect=lambda p, j: libere.append((p, j))), \
                mock.patch.object(main, "_receive_message_impl", side_effect=boum):
            with self.assertRaises(RuntimeError):
                asyncio.run(main.receive_message(Req()))
        self.assertEqual(libere, [("22502", "jeton")])


if __name__ == "__main__":
    unittest.main()
