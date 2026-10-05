import unittest

from initialiser_numeros_whatsapp import a_ecrire, premiers_contacts


class InitialiserNumerosTests(unittest.TestCase):
    def test_premiers_contacts(self):
        messages = [
            {"phone": "1", "direction": "inbound", "created_at": "2026-09-02T10:00:00+00:00"},
            {"phone": "1", "direction": "inbound", "created_at": "2026-08-30T10:00:00+00:00"},
            {"phone": "2", "direction": "outbound", "created_at": "2026-08-01T10:00:00+00:00"},
            {"phone": "2", "direction": "inbound", "created_at": "2026-09-10T10:00:00+00:00"},
            {"phone": "3", "direction": "outbound", "created_at": "2026-09-10T10:00:00+00:00"},
        ]
        self.assertEqual(premiers_contacts(messages), {"1": "2026-08-30T10:00:00+00:00", "2": "2026-09-10T10:00:00+00:00"})

    def test_a_ecrire(self):
        premiers = {"1": "2026-08-30", "2": "2026-09-10", "3": "2026-09-01"}
        existants = {"2": "2026-09-10", "3": "2026-10-04"}
        self.assertEqual(a_ecrire(premiers, existants), {"1": "2026-08-30", "3": "2026-09-01"})


if __name__ == "__main__":
    unittest.main()
