import asyncio
import contextlib
import hashlib
import io
import json
import unittest
from datetime import datetime, timezone
from unittest import mock

import main
import marketing_consent as consent


NOW = datetime(2026, 9, 28, 20, 0, tzinfo=timezone.utc)
PHONE = "2250102030405"


class AlreadyExists(Exception):
    pass


class FakeDocumentReference:
    def __init__(self, doc_id):
        self.id = doc_id
        self.record = None
        self.merge = None
        self.exists = False

    def create(self, record):
        if self.exists:
            raise AlreadyExists("already exists")
        self.record = dict(record)
        self.exists = True

    def get(self):
        snapshot = mock.Mock(exists=self.exists)
        snapshot.to_dict.return_value = dict(self.record or {})
        return snapshot

    def set(self, record, merge=False):
        self.record = {**(self.record or {}), **dict(record)} if merge else dict(record)
        self.merge = merge
        self.exists = True


class FakeCollection:
    def __init__(self):
        self.reference = None

    def document(self, doc_id):
        if self.reference is None or self.reference.id != doc_id:
            self.reference = FakeDocumentReference(doc_id)
        return self.reference


class FakeClient:
    def __init__(self):
        self.collection_name = None
        self.collection_value = FakeCollection()

    def collection(self, name):
        self.collection_name = name
        return self.collection_value


class FakeRequest:
    def __init__(self, text, message_id="wamid.consent"):
        self.body = {
            "entry": [{"changes": [{"value": {"messages": [{
                "from": PHONE,
                "id": message_id,
                "type": "text",
                "text": {"body": text},
            }]}}]}]
        }

    async def json(self):
        return self.body


class MarketingConsentUnitTests(unittest.TestCase):
    def test_opt_out_equivalents_are_explicit_and_accent_insensitive(self):
        for command in (
            "STOP", "stop all", "Unsubscribe", "OPT-OUT", "arrêt",
            "me désinscrire", "Ne m'envoyez plus de messages",
        ):
            with self.subTest(command=command):
                self.assertEqual(
                    consent.detect_marketing_consent_command(command), consent.OPTED_OUT
                )

    def test_opt_in_equivalents_require_marketing_intent(self):
        for command in (
            "OUI MARKETING", "opt in", "Subscribe", "start promo",
            "J'accepte les messages marketing", "me réabonner",
        ):
            with self.subTest(command=command):
                self.assertEqual(
                    consent.detect_marketing_consent_command(command), consent.OPTED_IN
                )
        for ordinary_message in (
            "oui", "start", "arrête l'exercice", "stop puis explique-moi", "bonjour",
        ):
            with self.subTest(ordinary_message=ordinary_message):
                self.assertIsNone(
                    consent.detect_marketing_consent_command(ordinary_message)
                )

    def test_persisted_record_and_document_id_contain_no_pii(self):
        client = FakeClient()
        record = consent.save_marketing_consent(
            client, PHONE, consent.OPTED_OUT, now=NOW
        )
        reference = client.collection_value.reference
        self.assertEqual(client.collection_name, consent.CONSENT_COLLECTION)
        self.assertEqual(reference.id, consent.consent_document_id(PHONE))
        self.assertTrue(reference.merge)
        self.assertEqual(record, reference.record)
        serialized = json.dumps({"id": reference.id, **record}, ensure_ascii=False)
        self.assertNotIn(PHONE, serialized)
        self.assertNotIn("phone", serialized.lower())
        self.assertNotIn("email", serialized.lower())
        self.assertEqual(set(record), {
            "schema_version", "channel", "consent_status", "marketing_opt_in",
            "unsubscribed", "source", "last_command", "updated_at",
            "opted_in_at", "opted_out_at",
        })
        self.assertEqual(record["consent_status"], consent.OPTED_OUT)
        self.assertTrue(record["unsubscribed"])
        self.assertFalse(record["marketing_opt_in"])

    def test_document_id_matches_weekly_segment_hash_contract(self):
        self.assertEqual(
            consent.consent_document_id(PHONE),
            hashlib.sha256(
                f"afrjigi-weekly-v1:whatsapp:{PHONE}".encode("utf-8")
            ).hexdigest(),
        )

    def test_opt_out_wins_over_a_conflicting_record(self):
        self.assertEqual(consent.classify_marketing_consent({
            "schema_version": 1,
            "channel": "whatsapp",
            "consent_status": "opted_in",
            "marketing_opt_in": True,
            "unsubscribed": True,
        }), consent.OPTED_OUT)

    def test_only_complete_current_schema_opt_in_is_eligible(self):
        valid = {
            "schema_version": 1,
            "channel": "whatsapp",
            "consent_status": "opted_in",
            "marketing_opt_in": True,
            "unsubscribed": False,
        }
        self.assertEqual(consent.classify_marketing_consent(valid), consent.OPTED_IN)
        for field in valid:
            incomplete = dict(valid)
            incomplete.pop(field)
            with self.subTest(field=field):
                self.assertNotEqual(
                    consent.classify_marketing_consent(incomplete), consent.OPTED_IN
                )

    def test_campaign_guard_fails_closed_for_missing_or_unknown_consent(self):
        client = mock.Mock()
        reference = client.collection.return_value.document.return_value
        reference.get.return_value.exists = False
        self.assertFalse(consent.marketing_recipient_is_eligible(client, PHONE))

        reference.get.return_value.exists = True
        reference.get.return_value.to_dict.return_value = {
            "schema_version": 1,
            "channel": "whatsapp",
            "consent_status": "unknown",
        }
        self.assertFalse(consent.marketing_recipient_is_eligible(client, PHONE))

        reference.get.return_value.to_dict.return_value = {
            "schema_version": 1,
            "channel": "whatsapp",
            "consent_status": "opted_in",
            "marketing_opt_in": True,
            "unsubscribed": False,
        }
        self.assertTrue(consent.marketing_recipient_is_eligible(client, PHONE))

    def test_prompt_claim_is_pseudonymous_and_only_created_once(self):
        client = FakeClient()
        claim_id = consent.claim_marketing_consent_prompt(client, PHONE, now=NOW)
        self.assertTrue(claim_id)
        reference = client.collection_value.reference
        serialized = json.dumps({"id": reference.id, **reference.record})
        self.assertNotIn(PHONE, serialized)
        self.assertEqual(reference.record["consent_status"], consent.UNKNOWN)
        self.assertEqual(
            reference.record["prompt_delivery_status"], consent.PROMPT_PENDING
        )
        self.assertIsNone(
            consent.claim_marketing_consent_prompt(client, PHONE, now=NOW)
        )

    def test_failed_prompt_can_be_claimed_again(self):
        client = FakeClient()
        first = consent.claim_marketing_consent_prompt(client, PHONE, now=NOW)
        consent.mark_marketing_consent_prompt_delivery(
            client, PHONE, first, False, now=NOW
        )
        second = consent.claim_marketing_consent_prompt(client, PHONE, now=NOW)
        self.assertTrue(second)
        self.assertNotEqual(first, second)


class MarketingConsentWebhookTests(unittest.TestCase):
    def setUp(self):
        main.processed_messages.clear()

    def run_webhook(self, text):
        return asyncio.run(main.receive_message(FakeRequest(text)))

    def test_stop_is_persisted_before_other_message_processing(self):
        with mock.patch.object(main, "save_marketing_consent") as save, \
                mock.patch.object(main, "send_whatsapp") as send, \
                mock.patch.object(main, "send_whatsapp_typing_indicator"), \
                mock.patch.object(main, "maybe_send_marketing_consent_prompt") as prompt, \
                mock.patch.object(main, "charger_etat_whatsapp") as load_profile, \
                mock.patch.object(main, "answer_learning_request") as answer, \
                mock.patch.object(main, "save_whatsapp_event") as save_event, \
                contextlib.redirect_stdout(io.StringIO()) as stdout:
            result = self.run_webhook("STOP")

        self.assertEqual(result, {"status": "ok", "reason": "marketing_opted_out"})
        save.assert_called_once_with(main.feedback_db, PHONE, consent.OPTED_OUT)
        send.assert_called_once()
        self.assertIn("désinscription marketing", send.call_args.args[1])
        self.assertEqual(send.call_args.kwargs, {
            "persist_event": False,
            "allow_audio": False,
        })
        load_profile.assert_not_called()
        prompt.assert_not_called()
        answer.assert_not_called()
        save_event.assert_not_called()
        self.assertNotIn(PHONE, stdout.getvalue())
        self.assertNotIn("STOP", stdout.getvalue())

    def test_opt_in_is_persisted_and_acknowledged(self):
        with mock.patch.object(main, "save_marketing_consent") as save, \
                mock.patch.object(main, "send_whatsapp") as send, \
                mock.patch.object(main, "maybe_send_marketing_consent_prompt") as prompt, \
                mock.patch.object(main, "send_whatsapp_typing_indicator"):
            result = self.run_webhook("OUI MARKETING")

        self.assertEqual(result, {"status": "ok", "reason": "marketing_opted_in"})
        save.assert_called_once_with(main.feedback_db, PHONE, consent.OPTED_IN)
        self.assertIn("accord est enregistré", send.call_args.args[1])
        self.assertEqual(send.call_args.kwargs, {
            "persist_event": False,
            "allow_audio": False,
        })
        prompt.assert_not_called()

    def test_persistence_failure_is_retryable_and_never_acknowledged(self):
        message_id = "wamid.consent"
        with mock.patch.object(
            main, "save_marketing_consent", side_effect=RuntimeError("database unavailable")
        ), mock.patch.object(main, "send_whatsapp") as send, \
                mock.patch.object(main, "send_whatsapp_typing_indicator"):
            response = self.run_webhook("STOP")

        self.assertEqual(response.status_code, 503)
        self.assertNotIn(message_id, main.processed_messages)
        send.assert_not_called()
        self.assertNotIn("database unavailable", response.body.decode("utf-8"))

    def test_consent_acknowledgement_is_not_persisted_in_message_history(self):
        main.last_outbound_by_phone.pop(PHONE, None)
        graph_response = mock.Mock(status_code=200, text="{}")
        with mock.patch.object(main.requests, "post", return_value=graph_response) as post, \
                mock.patch.object(main, "save_whatsapp_event") as save_event, \
                mock.patch.object(main, "save_last_assistant_context") as save_context, \
                contextlib.redirect_stdout(io.StringIO()) as stdout:
            main.send_whatsapp(PHONE, "Consentement enregistré.",
                               persist_event=False, allow_audio=False)

        post.assert_called_once()
        save_event.assert_not_called()
        save_context.assert_not_called()
        self.assertNotIn(PHONE, stdout.getvalue())

    def test_one_time_prompt_records_delivery_without_message_history(self):
        with mock.patch.object(
            main, "claim_marketing_consent_prompt", return_value="claim-1"
        ), mock.patch.object(main, "send_whatsapp", return_value=True) as send, \
                mock.patch.object(main, "mark_marketing_consent_prompt_delivery") as mark:
            self.assertTrue(main.maybe_send_marketing_consent_prompt(PHONE))

        send.assert_called_once_with(
            PHONE,
            main.MARKETING_CONSENT_PROMPT,
            persist_event=False,
            allow_audio=False,
        )
        mark.assert_called_once_with(main.feedback_db, PHONE, "claim-1", True)

    def test_already_prompted_user_is_not_prompted_again(self):
        with mock.patch.object(
            main, "claim_marketing_consent_prompt", return_value=None
        ), mock.patch.object(main, "send_whatsapp") as send, \
                mock.patch.object(main, "mark_marketing_consent_prompt_delivery") as mark:
            self.assertFalse(main.maybe_send_marketing_consent_prompt(PHONE))

        send.assert_not_called()
        mark.assert_not_called()

    def test_normal_inbound_message_checks_the_prompt(self):
        main.user_profiles.pop(PHONE, None)
        with mock.patch.object(main, "maybe_send_marketing_consent_prompt") as prompt, \
                mock.patch.object(main, "send_whatsapp_typing_indicator"), \
                mock.patch.object(main, "charger_etat_whatsapp", return_value={}), \
                mock.patch.object(main, "ask_exam") as ask_exam, \
                mock.patch.object(main, "save_whatsapp_event"):
            result = self.run_webhook("bonjour")

        self.assertEqual(result, {"status": "ok"})
        prompt.assert_called_once_with(PHONE)
        ask_exam.assert_called_once_with(PHONE)


if __name__ == "__main__":
    unittest.main()
