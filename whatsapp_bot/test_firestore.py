import os
import unittest
import uuid


@unittest.skipUnless(
    os.environ.get("FIRESTORE_EMULATOR_HOST"),
    "Firestore emulator not configured; production access is forbidden in tests",
)
class FirestoreEmulatorSmokeTests(unittest.TestCase):
    def test_synthetic_document_round_trip(self):
        from google.cloud import firestore

        client = firestore.Client(project="afrjigi-local-test")
        document_id = f"synthetic-{uuid.uuid4().hex}"
        reference = client.collection("whatsapp_active_sessions_test").document(document_id)
        reference.set({"synthetic": True})
        self.assertEqual(reference.get().to_dict(), {"synthetic": True})
        reference.delete()

    def test_active_session_revision_transaction_rejects_stale_write(self):
        import main

        phone = f"synthetic-{uuid.uuid4().hex}"
        reference = main.feedback_db.collection(main.ACTIVE_SESSIONS_COLLECTION).document(phone)
        first = main.new_active_session({"matiere": "MATHS", "serie": "6E"}, phone=phone)
        first["revision"] = 1
        second = dict(first)
        second["revision"] = 2
        try:
            self.assertTrue(main.save_active_session_if_revision(phone, first, 0))
            self.assertFalse(main.save_active_session_if_revision(phone, second, 0))
            self.assertEqual(reference.get().to_dict()["revision"], 1)
            self.assertTrue(main.save_active_session_if_revision(phone, second, 1))
            self.assertEqual(reference.get().to_dict()["revision"], 2)
        finally:
            reference.delete()


if __name__ == "__main__":
    unittest.main()
