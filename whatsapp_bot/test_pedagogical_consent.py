import sys
import types
import unittest
from unittest import mock
import pedagogical_consent as consent


class Ref:
    def __init__(self):
        self.record = {}
    def get(self, **kwargs):
        return types.SimpleNamespace(exists=bool(self.record), to_dict=lambda: dict(self.record))


class Client:
    def __init__(self):
        self.ref = Ref()
        self.collection_names = []
    def collection(self, name):
        self.collection_names.append(name)
        return self
    def document(self, identifier):
        self.identifier = identifier
        return self.ref
    def transaction(self):
        return self
    def set(self, ref, record, merge=True):
        ref.record.update(record)


class ConsentTests(unittest.TestCase):
    def setUp(self):
        cloud = types.ModuleType("google.cloud")
        cloud.firestore = types.SimpleNamespace(transactional=lambda fn: fn)
        self.patch = mock.patch.dict(sys.modules, {"google.cloud": cloud})
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.client = Client()
        self.phone = "test-user"

    def invite(self):
        claim = consent.claim_prompt(self.client, self.phone)
        consent.mark_prompt(self.client, self.phone, claim, True)
        return claim

    def test_yes_requires_invitation(self):
        self.assertFalse(consent.save_decision(self.client, self.phone, consent.OPTED_IN))
        self.invite()
        self.assertTrue(consent.save_decision(self.client, self.phone, consent.OPTED_IN))
        self.assertEqual(consent.classify(self.client.ref.record), consent.OPTED_IN)
        self.assertEqual(set(self.client.collection_names), {consent.COLLECTION})
        self.assertNotIn(self.phone, str(self.client.ref.record))

    def test_refusal_is_not_invited_again(self):
        self.invite()
        consent.save_decision(self.client, self.phone, consent.OPTED_OUT)
        self.assertIsNone(consent.claim_prompt(self.client, self.phone))

    def test_stop_without_prompt(self):
        consent.save_decision(self.client, self.phone, consent.OPTED_OUT, require_prompt=False)
        self.assertEqual(consent.classify(self.client.ref.record), consent.OPTED_OUT)
        self.assertIsNone(consent.claim_prompt(self.client, self.phone))

    def test_failed_delivery_can_retry(self):
        claim = consent.claim_prompt(self.client, self.phone)
        consent.mark_prompt(self.client, self.phone, claim, False)
        self.assertIsNotNone(consent.claim_prompt(self.client, self.phone))

    def test_old_ack_cannot_replace_new_claim(self):
        claim = consent.claim_prompt(self.client, self.phone)
        consent.mark_prompt(self.client, self.phone, "other", True)
        self.assertEqual(self.client.ref.record["prompt_status"], "pending")
        self.assertIsNone(consent.claim_prompt(self.client, self.phone))

    def test_old_consent_is_not_eligible(self):
        self.assertEqual(consent.classify({"consent_status": "opted_in", "marketing_opt_in": True}), consent.UNKNOWN)

    def test_notice_and_buttons(self):
        self.assertNotIn("marketing", consent.PROMPT.casefold())
        self.assertNotIn("offre", consent.PROMPT.casefold())
        self.assertTrue(all(len(title) <= 20 for _, title in consent.BUTTONS))
        self.assertNotEqual(consent.YES, consent.NO)


if __name__ == "__main__":
    unittest.main()
