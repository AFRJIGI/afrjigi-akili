"""Les echecs de livraison signales par Meta apparaissent dans les journaux."""
import asyncio
import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

import main


class FauxRequete:
    def __init__(self, valeur):
        self._body = {"entry": [{"changes": [{"value": valeur}]}]}

    async def json(self):
        return self._body


class StatutsTests(unittest.TestCase):
    def test_echec_de_livraison_journalise(self):
        valeur = {"statuses": [
            {"status": "delivered", "recipient_id": "225"},
            {"status": "failed", "recipient_id": "13153021255",
             "errors": [{"code": 130497, "title": "Business account is restricted",
                         "error_data": {"details": "pays"}}]},
        ]}
        sortie = io.StringIO()
        with redirect_stdout(sortie):
            resultat = asyncio.run(main.receive_message(FauxRequete(valeur)))
        self.assertEqual(resultat, {"status": "ok"})
        self.assertIn("WHATSAPP_STATUS_FAILED recipient=13153021255 code=130497", sortie.getvalue())
        self.assertNotIn("recipient=225", sortie.getvalue())


if __name__ == "__main__":
    unittest.main()
