import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from PIL import Image

import file_attente
import rafale

MAINTENANT = datetime.now(timezone.utc)


class Doc:
    def __init__(self, i, d):
        self.id, self._d, self.exists = i, d, d is not None

    def to_dict(self):
        return self._d


class Ref:
    def __init__(self, st, i):
        self.st, self.i = st, i

    def set(self, d):
        self.st[self.i] = dict(d)

    def update(self, d):
        self.st[self.i].update(d)

    def delete(self):
        self.st.pop(self.i, None)

    def get(self):
        return Doc(self.i, self.st.get(self.i))


class Col:
    def __init__(self, st):
        self.st, self.f = st, None

    def document(self, i):
        return Ref(self.st, i)

    def where(self, k, o, v):
        c = Col(self.st)
        c.f = (k, v)
        return c

    def stream(self):
        return [Doc(i, d) for i, d in self.st.items() if d[self.f[0]] == self.f[1]]


class DB:
    def __init__(self):
        self.st = {}

    def collection(self, nom):
        return Col(self.st)


def corps(msg):
    return {"entry": [{"changes": [{"value": {"messages": [msg]}}]}]}


def texte(i, ts, t, de="225"):
    return {"from": de, "id": i, "timestamp": str(ts), "type": "text", "text": {"body": t}}


def image(i, ts, mid, legende="", de="225"):
    return {"from": de, "id": i, "timestamp": str(ts), "type": "image",
            "image": {"id": mid, "mime_type": "image/jpeg", "caption": legende}}


def autre(i, ts, type_, de="225"):
    return {"from": de, "id": i, "timestamp": str(ts), "type": type_, type_: {"id": "x"}}


async def pas_de_pause(_):
    return None


def enregistrer(db, msg, delta=0):
    file_attente.enregistrer(db, msg["from"], msg["id"], int(msg["timestamp"]), MAINTENANT + timedelta(seconds=delta),
                             corps=json.dumps(corps(msg)))


class RafaleTests(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.db = DB()

    def telecharger(self, media_id, nom, mime):
        chemin = os.path.join(self.dossier, f"{media_id}.jpg")
        hauteur = {"m1": 100, "m2": 300}.get(media_id, 50)
        Image.new("RGB", (400, hauteur), (10, 10, 10)).save(chemin)
        return chemin

    def lancer(self, chef):
        return asyncio.run(rafale.regrouper(
            self.db, file_attente, corps(chef), chef["from"], chef["id"], int(chef["timestamp"]), MAINTENANT,
            self.telecharger, pas_de_pause))

    def test_deux_textes_en_un(self):
        a, b = texte("a", 100, "a"), texte("b", 101, "merci")
        enregistrer(self.db, a); enregistrer(self.db, b, 1)
        fusionne, medias = self.lancer(a)
        msg = fusionne["entry"][0]["changes"][0]["value"]["messages"][0]
        self.assertEqual((msg["type"], msg["text"]["body"], msg["id"]), ("text", "a\nmerci", "a"))
        self.assertEqual(medias, {})
        self.assertTrue(file_attente.est_fusionne(self.db, "b"))
        self.assertFalse(file_attente.est_fusionne(self.db, "a"))

    def test_deux_photos_empilees(self):
        a, b = image("a", 100, "m1", "mon exercice"), image("b", 101, "m2")
        enregistrer(self.db, a); enregistrer(self.db, b, 1)
        fusionne, medias = self.lancer(a)
        msg = fusionne["entry"][0]["changes"][0]["value"]["messages"][0]
        self.assertEqual(msg["type"], "image")
        self.assertEqual(msg["image"]["id"], "m1")
        self.assertEqual(msg["image"]["caption"], "mon exercice")
        chemin = medias["m1"]
        with Image.open(chemin) as im:
            self.assertEqual(im.size, (400, 400))  # 100 + 300 de hauteur
        self.assertTrue(file_attente.est_fusionne(self.db, "b"))

    def test_photo_puis_texte(self):
        a, b = image("a", 100, "m1"), texte("b", 101, "corrige cet exercice")
        enregistrer(self.db, a); enregistrer(self.db, b, 1)
        fusionne, medias = self.lancer(a)
        msg = fusionne["entry"][0]["changes"][0]["value"]["messages"][0]
        self.assertEqual((msg["type"], msg["image"]["caption"]), ("image", "corrige cet exercice"))
        self.assertIn("m1", medias)

    def test_texte_puis_photo(self):
        a, b = texte("a", 100, "voici mon exercice"), image("b", 101, "m2")
        enregistrer(self.db, a); enregistrer(self.db, b, 1)
        fusionne, medias = self.lancer(a)
        msg = fusionne["entry"][0]["changes"][0]["value"]["messages"][0]
        self.assertEqual((msg["type"], msg["image"]["id"], msg["image"]["caption"]),
                         ("image", "m2", "voici mon exercice"))
        self.assertIn("m2", medias)

    def test_un_audio_coupe_la_rafale(self):
        a, b = texte("a", 100, "bonjour"), autre("b", 101, "audio")
        enregistrer(self.db, a); enregistrer(self.db, b, 1)
        self.assertEqual(self.lancer(a), (None, {}))
        self.assertFalse(file_attente.est_fusionne(self.db, "b"))

    def test_rien_a_regrouper(self):
        a = texte("a", 100, "bonjour")
        enregistrer(self.db, a)
        self.assertEqual(self.lancer(a), (None, {}))

    def test_un_message_plus_ancien_n_est_pas_absorbe(self):
        ancien, a = texte("z", 99, "avant"), texte("a", 100, "maintenant")
        enregistrer(self.db, ancien, -1); enregistrer(self.db, a)
        self.assertEqual(self.lancer(a), (None, {}))
        self.assertFalse(file_attente.est_fusionne(self.db, "z"))

    def test_autre_eleve_ignore(self):
        a, b = texte("a", 100, "a", de="1"), texte("b", 101, "b", de="2")
        enregistrer(self.db, a); enregistrer(self.db, b, 1)
        self.assertEqual(self.lancer(a), (None, {}))

    def test_telechargement_en_echec_ne_fusionne_pas(self):
        a, b = image("a", 100, "m1"), image("b", 101, "m2")
        enregistrer(self.db, a); enregistrer(self.db, b, 1)
        self.telecharger = lambda *args: None
        self.assertEqual(self.lancer(a), (None, {}))
        self.assertFalse(file_attente.est_fusionne(self.db, "b"))

    def test_plafond_de_messages(self):
        msgs = [texte(str(i), 100 + i, str(i)) for i in range(8)]
        for i, m in enumerate(msgs):
            enregistrer(self.db, m, i)
        fusionne, _ = self.lancer(msgs[0])
        msg = fusionne["entry"][0]["changes"][0]["value"]["messages"][0]
        self.assertEqual(msg["text"]["body"].count("\n"), rafale.MAX_MESSAGES - 1)


class IntegrationTests(unittest.TestCase):
    def test_branchement_dans_main(self):
        from pathlib import Path
        src = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
        self.assertIn("await rafale.regrouper(", src)
        self.assertIn("body = _corps_fusionne.get() or await request.json()", src)
        self.assertIn("(_medias_fusionnes.get() or {}).get(media_id)", src)
        self.assertIn('"reason": "fusionne"', src)


if __name__ == "__main__":
    unittest.main()
