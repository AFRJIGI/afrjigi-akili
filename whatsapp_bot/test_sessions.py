import json
import os
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import requests
import main

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
PROFILE = {
    "type_examen": "CLASSE_INTERMEDIAIRE", "serie": "6E",
    "matiere": "MATHS", "mode": "etude",
    "first_learning_request_at": "2026-09-23T12:00:00+00:00",
}


class ActiveSessionSchemaTests(unittest.TestCase):
    def test_flag_is_disabled_by_default(self):
        previous = os.environ.pop("WHATSAPP_ACTIVE_SESSIONS_P0_ENABLED", None)
        try:
            self.assertFalse(main.p0_enabled())
        finally:
            if previous is not None:
                os.environ["WHATSAPP_ACTIVE_SESSIONS_P0_ENABLED"] = previous

    def test_schema_contains_only_expected_fields(self):
        state = main.new_active_session(PROFILE, phone="22501", now=NOW, session_id="session-1")
        self.assertEqual(set(state), {
            "schema_version", "phone", "session_id", "status", "subject",
            "level_or_serie", "type_examen", "mode", "profile_revision",
            "document", "exercise", "current_question", "current_step",
            "student_last_answer", "relevant_previous_results",
            "next_expected_action", "last_processed_message_id", "started_at",
            "updated_at", "expires_at", "revision",
        })

    def test_preparation_is_read_only(self):
        state = main.new_active_session(PROFILE, phone="22501", now=NOW, session_id="session-1")
        before = deepcopy(state)
        main.prepare_active_session(state, PROFILE, "wamid.1", phone="22501", now=NOW)
        self.assertEqual(state, before)

    def test_long_message_id_is_deduplicated(self):
        message_id = "wamid." + ("x" * 300)
        state = main.new_active_session(PROFILE, phone="22501", now=NOW)
        state = main.transition_after_success(state, "42", "Continue ?", message_id, now=NOW)
        _, duplicate = main.prepare_active_session(state, PROFILE, message_id, phone="22501", now=NOW)
        self.assertTrue(duplicate)
        self.assertEqual(state["last_processed_message_id"], message_id)

    def test_expiration_creates_new_session(self):
        state = main.new_active_session(PROFILE, phone="22501", now=NOW, session_id="old")
        state["expires_at"] = NOW - timedelta(seconds=1)
        prepared, duplicate = main.prepare_active_session(
            state, PROFILE, "wamid.new", phone="22501", now=NOW
        )
        self.assertFalse(duplicate)
        self.assertNotEqual(prepared["session_id"], "old")
        self.assertEqual(prepared["revision"], 0)

    def test_scope_change_creates_new_session(self):
        state = main.new_active_session(PROFILE, phone="22501", now=NOW, session_id="old")
        prepared, _ = main.prepare_active_session(
            state, {**PROFILE, "matiere": "PC"}, "wamid.new", phone="22501", now=NOW
        )
        self.assertNotEqual(prepared["session_id"], "old")

    def test_limits_and_nullable_ids(self):
        state = main.new_active_session(PROFILE, phone="22501", now=NOW)
        changed = main.transition_after_success(
            state, "a" * 1200, "Réponse valide ?", "m" * 600, now=NOW,
            current_question={"id": None, "text": "q" * 3000},
            structured_results=[{"value": "x" * 500} for _ in range(40)],
        )
        self.assertEqual(len(changed["student_last_answer"]["value"]), 1000)
        self.assertEqual(len(changed["last_processed_message_id"]), 512)
        self.assertEqual(len(changed["current_question"]["text"]), 1500)
        self.assertLessEqual(len(changed["relevant_previous_results"]), 20)
        encoded = json.dumps(changed["relevant_previous_results"], ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8")
        self.assertLessEqual(len(encoded), 8 * 1024)

    def test_exercise_change_clears_previous_results(self):
        state = main.new_active_session(PROFILE, phone="22501", now=NOW)
        state["exercise"] = {"id": "exo-1", "label": "Exercice 1"}
        state["relevant_previous_results"] = [{"value": 12}]
        changed = main.transition_after_success(
            state, "42", "Continue ?", "wamid.2", now=NOW,
            exercise={"id": "exo-2", "label": "Exercice 2"},
            structured_results=[{"outcome": "correct"}],
        )
        self.assertEqual(changed["relevant_previous_results"], [{"outcome": "correct"}])

    def test_new_document_clears_exercise_and_previous_results(self):
        state = main.new_active_session(PROFILE, phone="22501", now=NOW)
        state["document"] = main.nullable_document({"media_id": "media-old"})
        state["exercise"] = {"id": "exo-old", "label": "Ancien exercice"}
        state["current_question"] = {
            "id": "q-old", "text": "Ancienne question ?", "expected_response_type": "short_text",
        }
        state["relevant_previous_results"] = [{"value": 12}]
        changed = main.transition_after_success(
            state, "nouvelle photo", "Que vois-tu ?", "wamid.new-doc", now=NOW,
            document={"media_id": "media-new", "mime_type": "image/jpeg"},
        )
        self.assertEqual(changed["relevant_previous_results"], [])
        self.assertIsNone(changed["exercise"]["id"])
        self.assertIsNone(changed["current_question"]["id"])
        self.assertIsNone(changed["current_question"]["text"])

    def test_active_session_prompt_contains_only_resume_context(self):
        state = main.new_active_session(PROFILE, phone="22501", now=NOW, session_id="session-1")
        state["current_question"] = {
            "id": None, "text": "Quel nombre ?", "expected_response_type": "short_text",
        }
        state["relevant_previous_results"] = [{"value": 12}]
        prompt = main.build_active_session_prompt(state)
        self.assertIn("Quel nombre ?", prompt)
        self.assertIn('\"value\":12', prompt)
        self.assertNotIn("student_last_answer", prompt)

    def test_active_session_context_is_sent_to_akili(self):
        state = main.new_active_session(PROFILE, phone="22501", now=NOW, session_id="session-1")
        state["current_question"] = {
            "id": None, "text": "Question active unique ?", "expected_response_type": "short_text",
        }
        captured = {}
        original_post = main.requests.post

        class Response:
            status_code = 200
            text = '{"reponse":"Continue ?"}'

            @staticmethod
            def json():
                return {"reponse": "Continue ?"}

        try:
            main.requests.post = lambda *args, **kwargs: captured.update(kwargs) or Response()
            main.get_akili_response(
                "42", "MATHS", "6E", [], active_session=state,
            )
        finally:
            main.requests.post = original_post

        self.assertIn("Question active unique ?", captured["files"]["question"][1])

    def test_full_akili_response_is_not_stored(self):
        state = main.new_active_session(PROFILE, phone="22501", now=NOW)
        response = "Une explication pédagogique complète qui ne doit pas être persistée."
        changed = main.transition_after_success(state, "42", response, "wamid.2", now=NOW)
        self.assertNotIn(response, json.dumps(changed, ensure_ascii=False, default=str))

    def test_response_extracts_last_question_only(self):
        response, details = main.normalize_p0_response(
            "Idée clé : compare les milliers. Quel nombre est le plus grand ?"
        )
        self.assertTrue(response.startswith("Idée clé"))
        self.assertEqual(details["current_question"]["text"], "Quel nombre est le plus grand ?")

    def test_document_never_stores_local_path(self):
        document = main.nullable_document({
            "media_id": "media-123", "mime_type": "image/jpeg", "local_path": "/tmp/a.jpg"
        })
        self.assertEqual(document["media_id"], "media-123")
        self.assertNotIn("local_path", document)
        self.assertNotIn("/tmp", json.dumps(document))

    def test_intermediate_level_detection(self):
        profile = main.update_profile_from_text(
            {"serie": "TOUTES", "matiere": "MATHS"}, "Je suis en 6ème"
        )
        self.assertEqual(profile["serie"], "6E")
        self.assertEqual(main.infer_type_examen("6E", "maths"), "CLASSE_INTERMEDIAIRE")


class ActiveSessionFlowTests(unittest.TestCase):
    def setUp(self):
        names = (
            "load_active_session", "save_active_session_if_revision", "get_akili_response",
            "send_whatsapp", "send_whatsapp_typing_indicator", "send_vector_formula_if_needed",
            "charger_historique_conv", "sauver_historique_conv",
        )
        self.originals = {name: getattr(main, name) for name in names}
        self.previous_flag = os.environ.get("WHATSAPP_ACTIVE_SESSIONS_P0_ENABLED")
        main.user_profiles.clear()
        main.conversations.clear()
        main.send_whatsapp_typing_indicator = lambda *args: None
        main.send_vector_formula_if_needed = lambda *args: None
        main.charger_historique_conv = lambda *args: []
        main.sauver_historique_conv = lambda *args: None

    def tearDown(self):
        for name, value in self.originals.items():
            setattr(main, name, value)
        if self.previous_flag is None:
            os.environ.pop("WHATSAPP_ACTIVE_SESSIONS_P0_ENABLED", None)
        else:
            os.environ["WHATSAPP_ACTIVE_SESSIONS_P0_ENABLED"] = self.previous_flag

    def enable(self):
        os.environ["WHATSAPP_ACTIVE_SESSIONS_P0_ENABLED"] = "true"

    def test_disabled_flag_never_opens_active_session_store(self):
        os.environ["WHATSAPP_ACTIVE_SESSIONS_P0_ENABLED"] = "false"
        main.load_active_session = lambda *args: self.fail("P0 store must remain closed")
        main.get_akili_response = lambda *args, **kwargs: "Question suivante ?"
        main.send_whatsapp = lambda *args, **kwargs: None
        main.answer_learning_request("22501", dict(PROFILE), "42", message_id="wamid.legacy")

    def test_success_persists_structured_state_before_send(self):
        self.enable()
        events = []
        main.load_active_session = lambda *args: None
        main.get_akili_response = lambda *args, **kwargs: {
            "text": "Compare les nombres. Lequel est le plus grand ?",
            "exercise": {"id": "exo-2", "label": "Exercice 2"},
            "current_question": {"id": "q-2", "text": "Compare 4 508 et 4 580.",
                                 "expected_response_type": "short_text"},
            "structured_results": [{"question_id": "q-1", "outcome": "correct"}],
            "next_expected_action": "explain_reasoning",
        }
        main.save_active_session_if_revision = (
            lambda phone, state, expected_revision: events.append(("save", deepcopy(state))) or True
        )
        main.send_whatsapp = lambda *args, **kwargs: events.append(("send", args[1]))
        main.answer_learning_request(
            "22501", dict(PROFILE), "4508 < 4580", message_id="wamid.success",
            document_context={"media_id": "media-1", "mime_type": "image/jpeg"},
        )
        self.assertEqual([event[0] for event in events], ["save", "send"])
        state = events[0][1]
        self.assertEqual(state["document"]["media_id"], "media-1")
        self.assertEqual(state["exercise"]["id"], "exo-2")
        self.assertEqual(state["relevant_previous_results"][0]["outcome"], "correct")

    def test_duplicate_skips_akili_and_send(self):
        self.enable()
        state = main.new_active_session(
            PROFILE, phone="22501", now=datetime.now(timezone.utc)
        )
        state["last_processed_message_id"] = "wamid.duplicate"
        main.load_active_session = lambda *args: state
        main.get_akili_response = lambda *args, **kwargs: self.fail("Akili must not be called")
        main.send_whatsapp = lambda *args, **kwargs: self.fail("WhatsApp must not be called")
        result = main.answer_learning_request(
            "22501", dict(PROFILE), "42", message_id="wamid.duplicate"
        )
        self.assertIsNone(result)

    def test_vertex_failure_does_not_write_state(self):
        self.enable()
        writes, sent = [], []
        main.load_active_session = lambda *args: None
        main.save_active_session_if_revision = lambda *args: writes.append(args) or True
        main.get_akili_response = lambda *args, **kwargs: (_ for _ in ()).throw(
            requests.Timeout("timeout")
        )
        main.send_whatsapp = lambda *args, **kwargs: sent.append(args[1])
        main.answer_learning_request("22501", dict(PROFILE), "42", message_id="wamid.failure")
        self.assertEqual(writes, [])
        self.assertEqual(len(sent), 1)

    def test_revision_conflict_does_not_send_response(self):
        self.enable()
        sent = []
        main.load_active_session = lambda *args: None
        main.save_active_session_if_revision = lambda *args: False
        main.get_akili_response = lambda *args, **kwargs: "Question suivante ?"
        main.send_whatsapp = lambda *args, **kwargs: sent.append(args[1])
        main.answer_learning_request("22501", dict(PROFILE), "42", message_id="wamid.conflict")
        self.assertEqual(sent, [])


if __name__ == "__main__":
    unittest.main()
