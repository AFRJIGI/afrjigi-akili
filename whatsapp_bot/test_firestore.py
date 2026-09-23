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


if __name__ == "__main__":
    unittest.main()
