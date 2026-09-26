import unittest
from injecter_maths_techniques_septembre_2026 import CANDIDATES, plan


class MathsAuditTests(unittest.TestCase):
    def test_scope_excludes_unconfirmed_streams(self):
        self.assertEqual(len(CANDIDATES), 15)
        self.assertEqual(len({d[0] for d in CANDIDATES}), 15)
        self.assertFalse({28963, 28964, 28965} & {d[0] for d in CANDIDATES})
        self.assertFalse(any("F4" in d[2] for d in CANDIDATES))

    def test_deduplication_each_identifier_and_idempotence(self):
        candidate = dict(id="new", source_url="url", sha256="hash", texte="contenu utile")
        for field in ("id", "source_url", "sha256", "texte"):
            with self.subTest(field=field):
                self.assertEqual(plan([{field: candidate[field]}], [candidate]), [])
        self.assertEqual(plan([], [candidate, candidate]), [candidate])
        self.assertEqual(plan([candidate], [candidate]), [])

    def test_preserve_unrelated_documents(self):
        old = dict(id="old", texte="ancien texte")
        candidate = dict(id="new", source_url="url", sha256="hash", texte="nouveau texte")
        existing = [old.copy()]
        self.assertEqual(plan(existing, [candidate]), [candidate])
        self.assertEqual(existing, [old])


if __name__ == "__main__":
    unittest.main()
