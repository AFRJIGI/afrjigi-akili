import os
import json
import requests
import uuid
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from collections import defaultdict
from datetime import datetime, timedelta, timezone

app = FastAPI(title="AfrJigi WhatsApp Bot")

WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")
VERIFY_TOKEN = "afrjigi2026"
AKILI_API_URL = "https://akili-api-598190730734.us-central1.run.app/question"

conversations = defaultdict(list)
user_profiles = defaultdict(dict)
processed_messages = set()

ACTIVE_SESSIONS_COLLECTION = "whatsapp_active_sessions"
P0_SCHEMA_VERSION = 1
P0_SESSION_TTL_MINUTES = 30
P0_MAX_SCOPE_VALUE_CHARS = 64
P0_MAX_QUESTION_TEXT_CHARS = 1500
P0_MAX_STUDENT_ANSWER_CHARS = 1000
P0_MAX_PREVIOUS_RESULTS = 20
P0_MAX_PREVIOUS_RESULTS_BYTES = 8 * 1024


def utcnow():
    return datetime.now(timezone.utc)


def parse_datetime(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def p0_enabled():
    return os.environ.get("WHATSAPP_ACTIVE_SESSIONS_P0_ENABLED", "false").lower() == "true"


def bounded_text(value, limit):
    if value is None:
        return None
    return str(value)[:limit]


def nullable_document(value):
    value = value or {}
    return {
        "id": bounded_text(value.get("id"), P0_MAX_SCOPE_VALUE_CHARS),
        "ref": bounded_text(value.get("ref"), P0_MAX_QUESTION_TEXT_CHARS),
        "gcs_uri": bounded_text(value.get("gcs_uri"), P0_MAX_QUESTION_TEXT_CHARS),
        "media_id": bounded_text(value.get("media_id"), P0_MAX_SCOPE_VALUE_CHARS),
        "mime_type": bounded_text(value.get("mime_type"), P0_MAX_SCOPE_VALUE_CHARS),
        "sha256": bounded_text(value.get("sha256"), P0_MAX_SCOPE_VALUE_CHARS),
    }


def nullable_exercise(value):
    value = value or {}
    return {
        "id": bounded_text(value.get("id"), P0_MAX_SCOPE_VALUE_CHARS),
        "label": bounded_text(value.get("label"), P0_MAX_QUESTION_TEXT_CHARS),
    }


def nullable_question(value):
    value = value or {}
    return {
        "id": bounded_text(value.get("id"), P0_MAX_SCOPE_VALUE_CHARS),
        "text": bounded_text(value.get("text"), P0_MAX_QUESTION_TEXT_CHARS),
        "expected_response_type": bounded_text(
            value.get("expected_response_type"), P0_MAX_SCOPE_VALUE_CHARS
        ),
    }


def normalize_structured_results(results):
    """Keep only explicitly supplied JSON objects within 20 entries and 8 KiB."""
    normalized = []
    for result in results or []:
        if not isinstance(result, dict):
            continue
        try:
            candidate = json.loads(json.dumps(result, ensure_ascii=False))
            proposed = normalized + [candidate]
            size = len(json.dumps(proposed, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        except (TypeError, ValueError):
            continue
        if size > P0_MAX_PREVIOUS_RESULTS_BYTES:
            break
        normalized.append(candidate)
        if len(normalized) == P0_MAX_PREVIOUS_RESULTS:
            break
    return normalized


def profile_fields(profile):
    return {
        "subject": bounded_text(profile.get("matiere", "MATHS"), P0_MAX_SCOPE_VALUE_CHARS),
        "level_or_serie": bounded_text(profile.get("serie", "TOUTES"), P0_MAX_SCOPE_VALUE_CHARS),
        "type_examen": bounded_text(profile.get("type_examen", "BAC_GENERAL"), P0_MAX_SCOPE_VALUE_CHARS),
        "mode": bounded_text(profile.get("mode", "etude"), P0_MAX_SCOPE_VALUE_CHARS),
    }


def new_active_session(profile, now=None, session_id=None, phone=None):
    now = now or utcnow()
    state = {
        "schema_version": P0_SCHEMA_VERSION,
        "phone": bounded_text(phone, P0_MAX_SCOPE_VALUE_CHARS),
        "session_id": session_id or uuid.uuid4().hex,
        "status": "active",
        **profile_fields(profile),
        "profile_revision": None,
        "document": nullable_document(None),
        "exercise": nullable_exercise(None),
        "current_question": nullable_question(None),
        "current_step": 0,
        "student_last_answer": {
            "message_id": None, "value": None, "normalized_value": None, "created_at": None,
        },
        "relevant_previous_results": [],
        "next_expected_action": "start_or_resume",
        "last_processed_message_id": None,
        "started_at": now,
        "updated_at": now,
        "expires_at": now + timedelta(minutes=P0_SESSION_TTL_MINUTES),
        "revision": 0,
    }
    return state


def prepare_active_session(stored_state, profile, message_id, now=None, session_id=None, phone=None):
    """Read-only preparation. It never mutates or persists the stored state."""
    now = now or utcnow()
    state = dict(stored_state or {})
    duplicate = bool(message_id and state.get("last_processed_message_id") == message_id)
    expires_at = parse_datetime(state.get("expires_at"))
    expired = expires_at is None or now >= expires_at
    scope_changed = any(state.get(key) != value for key, value in profile_fields(profile).items())
    invalid_schema = state.get("schema_version") != P0_SCHEMA_VERSION
    if not state or expired or scope_changed or invalid_schema:
        state = new_active_session(profile, now=now, session_id=session_id, phone=phone)
        duplicate = False
    return state, duplicate


def transition_after_success(prepared_state, student_answer, akili_response, message_id,
                             now=None, document=None, exercise=None, current_question=None,
                             structured_results=None,
                             next_expected_action="await_student_answer"):
    """Create the next state only after Akili returned a valid response."""
    if not isinstance(akili_response, str) or not akili_response.strip():
        raise ValueError("Une réponse Akili non vide est requise")
    now = now or utcnow()
    next_state = dict(prepared_state)
    previous_exercise = nullable_exercise(prepared_state.get("exercise"))
    next_exercise = nullable_exercise(exercise if exercise is not None else previous_exercise)
    exercise_changed = previous_exercise != next_exercise
    previous_results = [] if exercise_changed else prepared_state.get("relevant_previous_results", [])
    results = normalize_structured_results(list(previous_results) + list(structured_results or []))
    next_state.update({
        "document": nullable_document(document if document is not None else prepared_state.get("document")),
        "exercise": next_exercise,
        "current_question": nullable_question(
            current_question if current_question is not None else prepared_state.get("current_question")
        ),
        "student_last_answer": {
            "message_id": bounded_text(message_id, P0_MAX_SCOPE_VALUE_CHARS),
            "value": bounded_text(student_answer, P0_MAX_STUDENT_ANSWER_CHARS),
            "normalized_value": None,
            "created_at": now,
        },
        "current_step": int(prepared_state.get("current_step", 0)) + 1,
        "relevant_previous_results": results,
        "next_expected_action": bounded_text(next_expected_action, P0_MAX_SCOPE_VALUE_CHARS),
        "last_processed_message_id": bounded_text(message_id, P0_MAX_SCOPE_VALUE_CHARS),
        "updated_at": now,
        "expires_at": now + timedelta(minutes=P0_SESSION_TTL_MINUTES),
        "revision": int(prepared_state.get("revision", 0)) + 1,
    })
    return next_state


class MemoryActiveSessionStore:
    collection_name = ACTIVE_SESSIONS_COLLECTION

    def __init__(self):
        self.documents = {}
        self.writes = []

    def get(self, phone):
        state = self.documents.get(phone)
        return dict(state) if state else None

    def save_if_revision(self, phone, state, expected_revision):
        current = self.documents.get(phone)
        current_revision = int(current.get("revision", 0)) if current else 0
        if current_revision != expected_revision:
            return False
        self.documents[phone] = dict(state)
        self.writes.append((self.collection_name, phone))
        return True


class FirestoreActiveSessionStore:
    collection_name = ACTIVE_SESSIONS_COLLECTION

    def __init__(self, client):
        self.client = client

    def get(self, phone):
        snapshot = self.client.collection(self.collection_name).document(phone).get()
        return snapshot.to_dict() if snapshot.exists else None

    def save_if_revision(self, phone, state, expected_revision):
        from google.cloud import firestore
        ref = self.client.collection(self.collection_name).document(phone)
        transaction = self.client.transaction()

        @firestore.transactional
        def save(tx):
            snapshot = ref.get(transaction=tx)
            current = snapshot.to_dict() if snapshot.exists else None
            current_revision = int(current.get("revision", 0)) if current else 0
            if current_revision != expected_revision:
                return False
            tx.set(ref, state)
            return True

        return save(transaction)


active_session_store = None


def get_active_session_store():
    global active_session_store
    if active_session_store is None:
        from google.cloud import firestore
        active_session_store = FirestoreActiveSessionStore(firestore.Client())
    return active_session_store

def format_whatsapp_message(message, limit=1400):
    message = message.strip()

    if len(message) <= limit:
        return message

    cut = message[:limit]
    last_break = max(cut.rfind("\n"), cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))

    if last_break > 500:
        cut = cut[:last_break + 1]

    return cut.strip() + "\n\nDis-moi si tu veux la suite."

def send_whatsapp(to, message):
    message = format_whatsapp_message(message)

    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message},
    }

    res = requests.post(url, headers=headers, json=data)
    print(f"DEBUG SEND: Status {res.status_code} - Response: {res.text}", flush=True)


def update_profile_from_text(profile, message):
    msg = message.upper()

    if "BEPC" in msg or "3EME" in msg or "3ÈME" in msg or "TROISIEME" in msg or "TROISIÈME" in msg:
        profile["serie"] = "BEPC"
        profile["type_examen"] = "BEPC"

    for serie in ["A1", "A2", "G1", "G2", "F1", "F2", "F3", "F4", "A", "B", "C", "D", "E"]:
        if (
            f"SERIE {serie}" in msg
            or f"SÉRIE {serie}" in msg
            or f"SERIE-{serie}" in msg
            or f"SÉRIE-{serie}" in msg
        ):
            profile["serie"] = serie
            break

    matieres = {
        "MATH": "MATHS",
        "MATHS": "MATHS",
        "MATHEMATIQUES": "MATHS",
        "MATHÉMATIQUES": "MATHS",
        "PHILO": "PHILO",
        "PC": "PC",
        "PHYSIQUE": "PC",
        "CHIMIE": "PC",
        "SVT": "SVT",
        "HG": "HG",
        "HISTOIRE": "HG",
        "GEOGRAPHIE": "HG",
        "GÉOGRAPHIE": "HG",
        "ANGLAIS": "ANGLAIS",
        "FRANCAIS": "FRANCAIS",
        "FRANÇAIS": "FRANCAIS",

        # Matières BAC Technique
        "COMPTABILITE": "COMPTA",
        "COMPTABILITÉ": "COMPTA",
        "COMPTA": "COMPTA",
        "ECONOMIE": "ECO",
        "ÉCONOMIE": "ECO",
        "ECO": "ECO",
        "DROIT": "DROIT",
        "ETUDE DE CAS": "ETUDE-CAS",
        "ÉTUDE DE CAS": "ETUDE-CAS",
        "ETUDE-CAS": "ETUDE-CAS",
        "TQG": "TQG",
        "ORGANISATION COMMERCIALE": "OC",
        "OC": "OC",
        "ESTI": "ESTI",
    }

    for key, value in matieres.items():
        if key in msg:
            profile["matiere"] = value
            break

    return profile


def infer_type_examen(serie, message):
    msg = (message or "").upper()
    serie = (serie or "").upper().strip()

    if serie == "BEPC" or "BEPC" in msg or "3EME" in msg or "3ÈME" in msg or "TROISIEME" in msg or "TROISIÈME" in msg:
        return "BEPC"

    if serie in {"B", "G1", "G2", "F1", "F2", "F3", "F4", "STI"}:
        return "BAC_TECHNIQUE"

    if any(x in msg for x in ["BAC TECH", "BAC TECHNIQUE", "TECHNIQUE", "TERMINALE G", "TERMINALE B"]):
        return "BAC_TECHNIQUE"

    return "BAC_GENERAL"


def infer_mode(message):
    msg = (message or "").upper()
    examen_keywords = [
        "MODE EXAMEN", "SUJET", "EXERCICE", "ENTRAINE", "ENTRAÎNE",
        "ENTRAINEMENT", "ENTRAÎNEMENT", "CORRIGE", "CORRIGÉ",
        "CORRIGE-MOI", "NOTE-MOI", "BAREME", "BARÈME", "EPREUVE", "ÉPREUVE"
    ]

    if any(k in msg for k in examen_keywords):
        return "examen"

    return "etude"


def get_akili_response(question, matiere, serie, history, phone="whatsapp_user", type_examen=None,
                       mode=None, raise_on_error=False):
    try:
        contexte = "\n".join([
            f"{'Élève' if m['role'] == 'user' else 'Akili'}: {m['content']}"
            for m in history[-6:]
        ])

        question_whatsapp = (
            "IMPORTANT: Tu réponds dans WhatsApp. "
            "Réponse courte, moins de 900 caractères. "
            "Ne transcris pas l'énoncé complet. "
            "Ne donne pas un long corrigé d'annales. "
            "Si c'est en Maths, donne seulement un petit exercice simple ou la première étape. "
            "Structure: idée clé, 3 points maximum, puis une question pour continuer.\n\n"
            f"Question élève: {question}"
       )

        payload = {
            "email": f"{phone}@afrjigi.com",
            "question": f"{contexte}\nÉlève: {question_whatsapp}" if contexte else question_whatsapp,
            "matiere": matiere,
            "serie": serie,
            "type_examen": type_examen,
            "mode": mode,
            "history": contexte,
        }
        

        print(f"AKILI_API payload: {payload}", flush=True)
        res = requests.post(AKILI_API_URL, files={k: (None, str(v)) for k, v in payload.items() if v is not None}, timeout=60)
        print(f"AKILI_API status: {res.status_code}", flush=True)
        print(f"AKILI_API body: {res.text}", flush=True)

        if raise_on_error:
            res.raise_for_status()

        data = res.json()
        response_text = (
            data.get("reponse")
            or data.get("response")
            or data.get("answer")
            or data.get("message")
        )
        if response_text:
            return response_text
        if raise_on_error:
            raise ValueError("Réponse Akili vide")
        return "Désolé, je n'ai pas pu répondre."

    except Exception as e:
        if raise_on_error:
            raise
        import traceback
        print(f"Erreur AKILI_API: {repr(e)}", flush=True)
        traceback.print_exc()
        return "Désolé, je rencontre une petite difficulté technique, réessaie dans un instant."


@app.get("/")
def health():
    return {"status": "AfrJigi WhatsApp Bot actif"}


@app.get("/whatsapp/webhook")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    print(f"Webhook verify: mode={mode} token={token} challenge={challenge}", flush=True)

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(content=challenge, status_code=200)

    return PlainTextResponse("Forbidden", status_code=403)


def process_legacy_message(phone, text, message_id):
    """Original pre-P0 behaviour, kept unchanged behind the disabled flag."""
    if message_id in processed_messages:
        print(f"Message déjà traité: {message_id}", flush=True)
        return
    if message_id:
        processed_messages.add(message_id)
    if len(processed_messages) > 1000:
        processed_messages.clear()

    profile = user_profiles[phone] or {"serie": "TOUTES", "matiere": "MATHS"}
    profile = update_profile_from_text(profile, text)
    type_examen = infer_type_examen(profile.get("serie", "TOUTES"), text)
    mode = infer_mode(text)
    profile["type_examen"] = type_examen
    profile["mode"] = mode
    user_profiles[phone] = profile

    matiere = profile.get("matiere", "MATHS")
    serie = profile.get("serie", "TOUTES")
    conversation_key = f"{phone}:{type_examen}:{serie}:{matiere}:{mode}"
    reponse = get_akili_response(
        text, matiere, serie, conversations[conversation_key],
        phone, type_examen, mode,
    )
    conversations[conversation_key].append({"role": "user", "content": text})
    conversations[conversation_key].append({"role": "assistant", "content": reponse})
    conversations[conversation_key] = conversations[conversation_key][-10:]
    send_whatsapp(phone, reponse)


def infer_p0_mode(message, current_mode):
    inferred = infer_mode(message)
    msg = (message or "").upper()
    if inferred == "examen":
        return "examen"
    if any(key in msg for key in ["MODE ETUDE", "MODE ÉTUDE", "COURS", "LECON", "LEÇON"]):
        return "etude"
    return current_mode if current_mode in {"etude", "examen"} else "etude"


def p0_history(state):
    history = []
    last_answer = (state.get("student_last_answer") or {}).get("value")
    if last_answer:
        history.append({"role": "user", "content": last_answer})
    history.extend(
        {"role": "assistant", "content": json.dumps(result, ensure_ascii=False)}
        for result in state.get("relevant_previous_results", [])
    )
    return history[-6:]


def process_p0_message(phone, text, message_id):
    """Prepare without writes, call Akili, then persist exactly one successful transition."""
    store = get_active_session_store()
    stored_state = store.get(phone)
    stored_scope = stored_state or {}
    profile = {
        "serie": stored_scope.get("level_or_serie", "TOUTES"),
        "matiere": stored_scope.get("subject", "MATHS"),
        "type_examen": stored_scope.get("type_examen", "BAC_GENERAL"),
        "mode": stored_scope.get("mode", "etude"),
    }
    profile = update_profile_from_text(profile, text)
    profile["type_examen"] = infer_type_examen(profile.get("serie", "TOUTES"), text)
    profile["mode"] = infer_p0_mode(text, profile.get("mode", "etude"))

    prepared_state, duplicate = prepare_active_session(
        stored_state, profile, message_id, phone=phone
    )
    if duplicate:
        print(f"Message déjà traité par P0: {message_id}", flush=True)
        return

    try:
        reponse = get_akili_response(
            text,
            profile["matiere"],
            profile["serie"],
            p0_history(prepared_state),
            phone,
            profile["type_examen"],
            profile["mode"],
            raise_on_error=True,
        )
    except Exception as exc:
        print(f"P0: état inchangé après échec Akili: {exc!r}", flush=True)
        send_whatsapp(phone, "Désolé, je rencontre une petite difficulté technique, réessaie dans un instant.")
        return

    expected_revision = int((stored_state or {}).get("revision", 0))
    next_state = transition_after_success(prepared_state, text, reponse, message_id)
    if not store.save_if_revision(phone, next_state, expected_revision):
        print(f"P0: conflit de révision pour {phone}, état non remplacé", flush=True)
        return
    send_whatsapp(phone, reponse)


@app.post("/whatsapp/webhook")
async def receive_message(request: Request):
    body = await request.json()

    try:
        messages = body["entry"][0]["changes"][0]["value"].get("messages", [])
        if not messages:
            return {"status": "ok"}

        msg = messages[0]
        phone = msg["from"]
        text = msg.get("text", {}).get("body", "").strip()
        message_id = msg.get("id")

        if not text:
            return {"status": "ok"}

        print(f"Message de {phone}: {text}", flush=True)
        if p0_enabled():
            process_p0_message(phone, text, message_id)
        else:
            process_legacy_message(phone, text, message_id)

    except Exception as e:
        import traceback
        print(f"Erreur webhook WhatsApp: {repr(e)}", flush=True)
        traceback.print_exc()

    return {"status": "ok"}


@app.get("/instagram/webhook")
async def verify_instagram(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(content=challenge, status_code=200)

    return PlainTextResponse("Forbidden", status_code=403)


@app.post("/instagram/webhook")
async def instagram_message(request: Request):
    body = await request.json()

    try:
        entries = body.get("entry", [])
        for entry in entries:
            messaging = entry.get("messaging", [])
            for event in messaging:
                sender_id = event["sender"]["id"]
                message = event.get("message", {})
                text = message.get("text", "")

                if text:
                    print(f"Instagram DM de {sender_id}: {text}", flush=True)
                    reponse = get_akili_response(
                        question=text,
                        matiere="MATHS",
                        serie="TOUTES",
                        history=[],
                    )
                    send_instagram_dm(sender_id, reponse)

    except Exception as e:
        import traceback
        print(f"Erreur Instagram: {repr(e)}", flush=True)
        traceback.print_exc()

    return {"status": "ok"}


def send_instagram_dm(recipient_id: str, message: str):
    if len(message) > 1000:
        message = message[:1000] + "..."

    url = "https://graph.facebook.com/v25.0/me/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    data = {
        "recipient": {"id": recipient_id},
        "message": {"text": message},
    }

    res = requests.post(url, headers=headers, json=data)
    print(f"Instagram SEND: {res.status_code} - {res.text}", flush=True)
