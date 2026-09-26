import json
import unittest
from unittest.mock import Mock, patch
import injecter_economie_generale_terminale_2025_2026 as subject


class InjectionTests(unittest.TestCase):
    def setUp(self):
        self.doc = dict(id=subject.DOC_ID, sha256=subject.SHA256,
                        source_url=subject.URL, texte="".join(f"mot{i} " for i in range(300)))

    def test_duplicate_id_hash_url_and_text(self):
        for key in ("id", "sha256", "source_url", "texte"):
            with self.subTest(key=key):
                self.assertEqual(subject.assess([{key: self.doc[key]}], self.doc)[0], "SKIP")

    def test_similar_document_blocks(self):
        other = dict(id="old", texte=self.doc["texte"] + " modification")
        self.assertEqual(subject.assess([other], self.doc)[0], "REVIEW")

    def test_changed_source_rejected(self):
        with self.assertRaisesRegex(ValueError, "change"):
            subject.build_document(b"HTML or changed DOCX")

    def test_audit_no_upload(self):
        bucket = Mock()
        blob = bucket.blob.return_value
        blob.generation = 12
        blob.download_as_bytes.return_value = b'{"documents": []}'
        with patch.object(subject, "build_document", return_value=self.doc):
            subject.run(bucket, b"content")
        blob.upload_from_string.assert_not_called()
        blob.download_as_bytes.assert_called_once_with(if_generation_match=12, timeout=600)

    def test_review_blocks_apply(self):
        bucket = Mock()
        blob = bucket.blob.return_value
        blob.generation = 12
        blob.download_as_bytes.return_value = json.dumps({"documents": [dict(texte=self.doc["texte"] + " changes")]}).encode()
        with patch.object(subject, "build_document", return_value=self.doc):
            with self.assertRaisesRegex(RuntimeError, "Ressemblance"):
                subject.run(bucket, b"content", apply=True)
        blob.upload_from_string.assert_not_called()

    def test_apply_preserves_existing_and_uses_generation(self):
        bucket, blob = Mock(), Mock()
        bucket.blob.return_value.exists.return_value = False
        data = {"documents": [{"id": "old"}], "extra": "keep"}
        subject.persist(bucket, blob, 42, b"original", data, self.doc, b"content")
        result = json.loads(blob.upload_from_string.call_args.args[0])
        self.assertEqual(result["documents"][0], {"id": "old"})
        self.assertEqual(result["extra"], "keep")
        self.assertEqual(result["total"], 2)
        self.assertEqual(blob.upload_from_string.call_args.kwargs["if_generation_match"], 42)
        self.assertEqual(data["documents"], [{"id": "old"}])
        self.assertEqual(bucket.blob.return_value.upload_from_string.call_args_list[0].args[0], b"original")


if __name__ == "__main__":
    unittest.main()
