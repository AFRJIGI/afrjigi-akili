import unittest

from injecter_anglais_industriel_2024_2025 import (
    CANDIDATES,
    VERSION,
    build_document,
    document_id,
    filename,
    plan,
)


class AnglaisIndustrielTests(unittest.TestCase):
    def test_manifest_has_nine_unique_progressions(self):
        portal_ids = [item[0] for item in CANDIDATES]
        ids = [document_id(item[1], item[2]) for item in CANDIDATES]
        self.assertEqual(9, len(CANDIDATES))
        self.assertEqual(9, len(set(portal_ids)))
        self.assertEqual(9, len(set(ids)))

    def test_manifest_covers_requested_industrial_series(self):
        series = "".join(item[2] for item in CANDIDATES)
        for expected in ("E", "F1", "F2", "F3", "F4", "F7"):
            self.assertIn(expected, series)
        self.assertEqual({25510, 25511, 25512}, set(item[0] for item in CANDIDATES[:3]))

    def test_real_year_and_source_are_preserved(self):
        doc = build_document(
            25510,
            "PREMIERE",
            "EF1F2F3",
            "1ERE E-F1-F2-F3",
            "https://example.test/source",
            b"%PDF-example",
            "texte",
        )
        self.assertEqual("2024-2025", VERSION)
        self.assertEqual("2024-2025", doc["annee_scolaire"])
        self.assertEqual("Septembre 2024", doc["edition_source"])
        self.assertEqual("METFPA_IGETFPA", doc["source"])
        self.assertEqual("BAC_TECHNIQUE", doc["examen"])
        self.assertEqual("ANGLAIS", doc["matiere"])

    def test_names_are_stable_and_versioned(self):
        self.assertEqual(
            "metfpa_igetfpa_progression_anglais_2024_2025_terminale_f7",
            document_id("TERMINALE", "F7"),
        )
        self.assertEqual(
            "METFPA_IGETFPA_2024-2025_ANGLAIS_TERMINALE_F7.pdf",
            filename("TERMINALE", "F7"),
        )

    def test_plan_deduplicates_every_key_and_is_idempotent(self):
        candidate = {
            "id": "new",
            "source_url": "url",
            "sha256": "hash",
            "texte": "contenu utile",
            "niveau": "TERMINALE",
            "serie": "F7",
        }
        for field in ("id", "source_url", "sha256", "texte"):
            with self.subTest(field=field):
                self.assertEqual([], plan([{field: candidate[field]}], [candidate]))
        self.assertEqual([candidate], plan([], [candidate, candidate]))
        self.assertEqual([], plan([candidate], [candidate]))


if __name__ == "__main__":
    unittest.main()
