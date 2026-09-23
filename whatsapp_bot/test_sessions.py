import asyncio
import concurrent.futures
import json
import os
import sys
import threading
import types
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import requests


class _FastAPIStub:
    def __init__(self, *args, **kwargs):
        pass

    def get(self, *args, **kwargs):
        return lambda function: function

    def post(self, *args, **kwargs):
        return lambda function: function


fastapi_stub = types.ModuleType("fastapi")
fastapi_stub.FastAPI = _FastAPIStub
fastapi_stub.Request = object
responses_stub = types.ModuleType("fastapi.responses")
responses_stub.PlainTextResponse = object
sys.modules.setdefault("fastapi", fastapi_stub)
sys.modules.setdefault("fastapi.responses", responses_stub)

import main


NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
PROFILE = {
    "type_examen": "BAC_GENERAL",
    "serie": "D",
    "matiere": "MATHS",
    "mode": "etude",
}


class RequestStub:
    def __init__(self, message_id, text):
        self.body = {
            "entry": [{"changes": [{"value": {"messages": [{
                "from": "22501", "id": message_id, "text": {"body": text},
            }]}}]}]
        }

    async def json(self):
        return self.body


class FakeSnapshot:
    def __init__(self, value):
        self._value = deepcopy(value)
        self.exists = value is not None

    def to_dict(self):
        return deepcopy(self._value)


class FakeDocumentReference:
    def __init__(self, client, collection_name, document_id):
        self.client = client
        self.collection_name = collection_name
        self.document_id = document_id

    def get(self, transaction=None):
        return FakeSnapshot(self.client.documents.get((self.collection_name, self.document_id)))


class FakeCollectionReference:
    def __init__(self, client, collection_name):
        self.client = client
        self.collection_name = collection_name

    def document(self, document_id):
        return FakeDocumentReference(self.client, self.collection_name, document_id)


class FakeTransaction:
    def __init__(self, client):
        self.client = client

    def set(self, reference, value):
        key = (reference.collection_name, reference.document_id)
        self.client.documents[key] = deepcopy(value)
        self.client.writes.append(key)


class FakeFirestoreClient:
    def __init__(self):
        self.documents = {}
        self.writes = []
        self.collection_calls = []
        self.lock = threading.RLock()

    def collection(self, collection_name):
        self.collection_calls.append(collection_name)
        return FakeCollectionReference(self, collection_name)

    def transaction(self):
        return FakeTransaction(self)


class FirestoreAdapterTests(unittest.TestCase):
    def setUp(self):
        self.saved_modules = {
            name: sys.modules.get(name)
            for name in ("google", "google.cloud", "google.cloud.firestore")
        }
        google_module = types.ModuleType("google")
        cloud_module = types.ModuleType("google.cloud")
        firestore_module = types.ModuleType("google.cloud.firestore")

        def transactional(function):
            def wrapped(transaction):
                with transaction.client.lock:
                    return function(transaction)
            return wrapped

        firestore_module.transactional = transactional
        cloud_module.firestore = firestore_module
        google_module.cloud = cloud_module
        sys.modules["google"] = google_module
        sys.modules["google.cloud"] = cloud_module
        sys.modules["google.cloud.firestore"] = firestore_module
        self.client = FakeFirestoreClient()
        self.store = main.FirestoreActiveSessionStore(self.client)

    def tearDown(self):
        for name, module in self.saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def state(self, revision):
        state = main.new_active_session(
            PROFILE, now=NOW, session_id="session-1", phone="22501"
        )
        state["revision"] = revision
        return state

    def test_initial_creation_uses_active_sessions_document(self):
        created = self.store.save_if_revision("22501", self.state(1), expected_revision=0)
        self.assertTrue(created)
        self.assertEqual(self.client.writes, [("whatsapp_active_sessions", "22501")])
        self.assertEqual(self.store.get("22501")["revision"], 1)

    def test_update_with_current_revision_succeeds(self):
        self.client.documents[("whatsapp_active_sessions", "22501")] = self.state(1)
        updated = self.store.save_if_revision("22501", self.state(2), expected_revision=1)
        self.assertTrue(updated)
        self.assertEqual(self.store.get("22501")["revision"], 2)

    def test_stale_revision_is_rejected_without_write(self):
        self.client.documents[("whatsapp_active_sessions", "22501")] = self.state(2)
        updated = self.store.save_if_revision("22501", self.state(3), expected_revision=1)
        self.assertFalse(updated)
        self.assertEqual(self.client.writes, [])
        self.assertEqual(self.store.get("22501")["revision"], 2)

    def test_two_concurrent_transitions_accept_only_one(self):
        barrier = threading.Barrier(2)

        def save_once(marker):
            candidate = self.state(1)
            candidate["next_expected_action"] = marker
            barrier.wait()
            return self.store.save_if_revision("22501", candidate, expected_revision=0)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(save_once, ("first", "second")))

        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(len(self.client.writes), 1)

    def test_adapter_never_addresses_legacy_collections(self):
        self.store.save_if_revision("22501", self.state(1), expected_revision=0)
        self.store.get("22501")
        forbidden = {"whatsapp_state", "whatsapp_contexts", "whatsapp_historiques"}
        self.assertTrue(forbidden.isdisjoint(self.client.collection_calls))
        self.assertEqual(set(self.client.collection_calls), {"whatsapp_active_sessions"})


class ActiveSessionP0Tests(unittest.TestCase):
    def setUp(self):
        self.original_flag = os.environ.pop("WHATSAPP_ACTIVE_SESSIONS_P0_ENABLED", None)
        self.original_store = main.active_session_store
        self.original_get_response = main.get_akili_response
        self.original_send = main.send_whatsapp
        self.original_get_store = main.get_active_session_store
        main.active_session_store = None
        main.conversations.clear()
        main.user_profiles.clear()
        main.processed_messages.clear()

    def tearDown(self):
        if self.original_flag is not None:
            os.environ["WHATSAPP_ACTIVE_SESSIONS_P0_ENABLED"] = self.original_flag
        else:
            os.environ.pop("WHATSAPP_ACTIVE_SESSIONS_P0_ENABLED", None)
        main.active_session_store = self.original_store
        main.get_akili_response = self.original_get_response
        main.send_whatsapp = self.original_send
        main.get_active_session_store = self.original_get_store

    def enable_p0(self, store=None):
        os.environ["WHATSAPP_ACTIVE_SESSIONS_P0_ENABLED"] = "true"
        main.active_session_store = store or main.MemoryActiveSessionStore()
        return main.active_session_store

    def test_p0_is_disabled_by_default_and_legacy_behaviour_is_unchanged(self):
        sent = []
        main.get_akili_response = lambda *args, **kwargs: "réponse historique"
        main.send_whatsapp = lambda phone, message: sent.append((phone, message))
        main.get_active_session_store = lambda: self.fail("P0 store must not be opened")

        asyncio.run(main.receive_message(RequestStub("wamid.legacy", "Maths série D")))

        self.assertFalse(main.p0_enabled())
        self.assertEqual(sent, [("22501", "réponse historique")])
        self.assertIn("wamid.legacy", main.processed_messages)
        self.assertEqual(len(next(iter(main.conversations.values()))), 2)

    def _valid_state(self, store):
        prepared = main.new_active_session(PROFILE, now=NOW, session_id="session-1")
        state = main.transition_after_success(
            prepared, "ancienne réponse", "ancien résultat", "wamid.old", now=NOW,
        )
        store.documents["22501"] = deepcopy(state)
        return state

    def test_vertex_failure_does_not_advance_or_replace_state(self):
        store = self.enable_p0()
        before = self._valid_state(store)
        main.get_akili_response = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Vertex failed"))
        main.send_whatsapp = lambda *args: None

        main.process_p0_message("22501", "nouvelle réponse", "wamid.failure")

        self.assertEqual(store.documents["22501"], before)
        self.assertEqual(store.writes, [])

    def test_vertex_timeout_does_not_advance_or_replace_state(self):
        store = self.enable_p0()
        before = self._valid_state(store)
        main.get_akili_response = lambda *args, **kwargs: (_ for _ in ()).throw(requests.Timeout("timeout"))
        main.send_whatsapp = lambda *args: None

        main.process_p0_message("22501", "nouvelle réponse", "wamid.timeout")

        self.assertEqual(store.documents["22501"], before)
        self.assertEqual(store.writes, [])

    def test_exercise_change_clears_previous_results(self):
        state = main.new_active_session(PROFILE, now=NOW, session_id="session-1")
        state["exercise"] = {"id": "exo-1", "label": "Premier"}
        state["relevant_previous_results"] = [{"kind": "calculated_value", "value": 12}]

        changed = main.transition_after_success(
            state, "42", "nouveau résultat", "wamid.2", now=NOW,
            exercise={"id": "exo-2", "label": "Deuxième"},
            structured_results=[{"kind": "question_outcome", "value": "correct"}],
        )

        self.assertEqual(
            changed["relevant_previous_results"],
            [{"kind": "question_outcome", "value": "correct"}],
        )

    def test_exercise_change_with_null_ids_also_clears_results(self):
        state = main.new_active_session(PROFILE, now=NOW, session_id="session-1")
        state["exercise"] = {"id": None, "label": "Premier exercice"}
        state["relevant_previous_results"] = [{"kind": "intermediate", "value": 3}]
        changed = main.transition_after_success(
            state, "42", "nouveau résultat", "wamid.2", now=NOW,
            exercise={"id": None, "label": "Deuxième exercice"},
        )
        self.assertEqual(changed["relevant_previous_results"], [])

    def test_exact_size_limits_and_nullable_identifiers(self):
        state = main.new_active_session(PROFILE, now=NOW, session_id="session-1")
        structured_results = [
            {"kind": "intermediate", "value": "x" * 500}
            for _ in range(40)
        ]
        next_state = main.transition_after_success(
            state,
            "a" * 1200,
            "réponse Akili qui ne doit pas être stockée",
            "m" * 200,
            now=NOW,
            exercise={"id": None, "label": "e" * 3000},
            current_question={"id": None, "text": "q" * 3000},
            structured_results=structured_results,
        )

        self.assertIsNone(next_state["exercise"]["id"])
        self.assertIsNone(next_state["current_question"]["id"])
        self.assertEqual(len(next_state["student_last_answer"]["value"]), 1000)
        self.assertEqual(len(next_state["current_question"]["text"]), 1500)
        self.assertLessEqual(len(next_state["relevant_previous_results"]), 20)
        encoded = json.dumps(
            next_state["relevant_previous_results"], ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        self.assertLessEqual(len(encoded), 8 * 1024)

    def test_full_akili_response_is_never_stored_without_structured_results(self):
        state = main.new_active_session(PROFILE, now=NOW, session_id="session-1")
        full_response = "Voici une longue explication pédagogique complète."
        changed = main.transition_after_success(
            state, "42", full_response, "wamid.2", now=NOW,
        )
        self.assertEqual(changed["relevant_previous_results"], [])
        self.assertNotIn(full_response, json.dumps(changed, ensure_ascii=False, default=str))

    def test_p0_writes_only_to_additive_collection(self):
        store = self.enable_p0()
        main.get_akili_response = lambda *args, **kwargs: "réponse valide"
        main.send_whatsapp = lambda *args: None

        main.process_p0_message("22501", "Maths série D", "wamid.1")

        self.assertEqual(store.writes, [("whatsapp_active_sessions", "22501")])
        forbidden = {"whatsapp_state", "whatsapp_contexts", "whatsapp_historiques"}
        self.assertTrue(forbidden.isdisjoint(collection for collection, _ in store.writes))

    def test_duplicate_message_is_not_sent_to_vertex_twice(self):
        store = self.enable_p0()
        calls = []
        main.get_akili_response = lambda *args, **kwargs: calls.append(1) or "réponse valide"
        main.send_whatsapp = lambda *args: None

        main.process_p0_message("22501", "Maths série D", "wamid.1")
        main.process_p0_message("22501", "Maths série D", "wamid.1")

        self.assertEqual(calls, [1])
        self.assertEqual(len(store.writes), 1)

    def test_successful_vertex_response_commits_one_transition(self):
        store = self.enable_p0()
        sent = []
        main.get_akili_response = lambda *args, **kwargs: "indice pédagogique valide"
        main.send_whatsapp = lambda phone, message: sent.append((phone, message))

        main.process_p0_message("22501", "Maths série D", "wamid.success")
        state = store.documents["22501"]

        required_fields = {
            "schema_version", "phone", "session_id", "status", "subject",
            "level_or_serie", "type_examen", "mode", "profile_revision",
            "document", "exercise",
            "current_question", "current_step", "student_last_answer",
            "relevant_previous_results", "next_expected_action",
            "last_processed_message_id", "started_at", "updated_at", "expires_at", "revision",
        }
        self.assertTrue(required_fields.issubset(state))
        self.assertEqual(set(state), required_fields)
        self.assertEqual(state["schema_version"], main.P0_SCHEMA_VERSION)
        self.assertEqual(state["phone"], "22501")
        self.assertEqual(state["current_step"], 1)
        self.assertEqual(state["student_last_answer"]["value"], "Maths série D")
        self.assertEqual(state["last_processed_message_id"], "wamid.success")
        self.assertEqual(state["revision"], 1)
        self.assertEqual(state["relevant_previous_results"], [])
        self.assertEqual(sent, [("22501", "indice pédagogique valide")])

    def test_unknown_values_remain_null(self):
        state = main.new_active_session(PROFILE, now=NOW, session_id="session-1", phone="22501")
        self.assertTrue(all(value is None for value in state["document"].values()))
        self.assertTrue(all(value is None for value in state["exercise"].values()))
        self.assertTrue(all(value is None for value in state["current_question"].values()))
        self.assertIsNone(state["profile_revision"])
        self.assertTrue(all(value is None for value in state["student_last_answer"].values()))

    def test_preparation_is_read_only(self):
        stored = main.new_active_session(PROFILE, now=NOW, session_id="session-1")
        before = deepcopy(stored)
        main.prepare_active_session(stored, PROFILE, "wamid.1", now=NOW)
        self.assertEqual(stored, before)

    def test_expired_session_is_replaced(self):
        stored = main.new_active_session(PROFILE, now=NOW, session_id="expired-session")
        stored["expires_at"] = NOW - timedelta(seconds=1)
        prepared, duplicate = main.prepare_active_session(
            stored, PROFILE, "wamid.new", now=NOW,
            session_id="replacement-session", phone="22501",
        )
        self.assertFalse(duplicate)
        self.assertEqual(prepared["session_id"], "replacement-session")
        self.assertEqual(prepared["revision"], 0)

    def test_each_scope_change_starts_a_new_session(self):
        stored = main.new_active_session(PROFILE, now=NOW, session_id="session-1")
        changes = (
            {"matiere": "PC"},
            {"serie": "C"},
            {"type_examen": "BEPC"},
            {"mode": "examen"},
        )
        for index, change in enumerate(changes):
            with self.subTest(change=change):
                changed_profile = {**PROFILE, **change}
                prepared, duplicate = main.prepare_active_session(
                    stored, changed_profile, f"wamid.{index}", now=NOW,
                    session_id=f"session-{index + 2}", phone="22501",
                )
                self.assertFalse(duplicate)
                self.assertNotEqual(prepared["session_id"], stored["session_id"])

    def test_last_processed_message_id_is_deduplicated_during_preparation(self):
        stored = main.new_active_session(PROFILE, now=NOW, session_id="session-1")
        stored["last_processed_message_id"] = "wamid.duplicate"
        _, duplicate = main.prepare_active_session(
            stored, PROFILE, "wamid.duplicate", now=NOW,
        )
        self.assertTrue(duplicate)


if __name__ == "__main__":
    unittest.main()
