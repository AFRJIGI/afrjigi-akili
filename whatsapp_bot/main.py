import os
import time
import json
import requests
import re
import unicodedata
import uuid
import hashlib
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from google.cloud import firestore, storage
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from gtts import gTTS

app = FastAPI(title="AfrJigi WhatsApp Bot")

WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")
VERIFY_TOKEN = "afrjigi2026"
AKILI_API_URL = "https://akili-api-598190730734.us-central1.run.app/question"
TRANSCRIBE_URL = "https://akili-api-598190730734.us-central1.run.app/transcribe"

conversations = defaultdict(list)
user_profiles = defaultdict(dict)
processed_messages = set()
audio_reply_context = {}
last_outbound_by_phone = {}
feedback_db = firestore.Client()

ACTIVE_SESSIONS_COLLECTION = "whatsapp_active_sessions"
P0_SCHEMA_VERSION = 1
P0_SESSION_TTL_MINUTES = 30
P0_MAX_SCOPE_VALUE_CHARS = 64
P0_MAX_MESSAGE_ID_CHARS = 512
P0_MAX_QUESTION_TEXT_CHARS = 1500
P0_MAX_STUDENT_ANSWER_CHARS = 1000
P0_MAX_PREVIOUS_RESULTS = 20
P0_MAX_PREVIOUS_RESULTS_BYTES = 8 * 1024
P0_MEDIA_BUCKET = os.environ.get(
    "WHATSAPP_ACTIVE_SESSIONS_MEDIA_BUCKET",
    "akili-database-storage-astute-curve-307922",
)


def p0_enabled():
    return os.environ.get("WHATSAPP_ACTIVE_SESSIONS_P0_ENABLED", "false").lower() == "true"


def bounded_text(value, limit):
    return None if value is None else str(value)[:limit]


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


def nullable_document(value):
    value = value or {}
    return {
        "id": bounded_text(value.get("id"), P0_MAX_SCOPE_VALUE_CHARS),
        "ref": bounded_text(value.get("ref"), P0_MAX_QUESTION_TEXT_CHARS),
        "gcs_uri": bounded_text(value.get("gcs_uri"), P0_MAX_QUESTION_TEXT_CHARS),
        "media_id": bounded_text(value.get("media_id"), P0_MAX_MESSAGE_ID_CHARS),
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
    normalized = []
    for result in results or []:
        if not isinstance(result, dict):
            continue
        try:
            candidate = json.loads(json.dumps(result, ensure_ascii=False))
            proposed = normalized + [candidate]
            encoded = json.dumps(proposed, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError):
            continue
        if len(encoded) > P0_MAX_PREVIOUS_RESULTS_BYTES:
            break
        normalized.append(candidate)
        if len(normalized) == P0_MAX_PREVIOUS_RESULTS:
            break
    return normalized


def p0_profile_fields(profile):
    return {
        "subject": bounded_text(profile.get("matiere", "MATHS"), P0_MAX_SCOPE_VALUE_CHARS),
        "level_or_serie": bounded_text(profile.get("serie", "TOUTES"), P0_MAX_SCOPE_VALUE_CHARS),
        "type_examen": bounded_text(profile.get("type_examen", "BAC_GENERAL"), P0_MAX_SCOPE_VALUE_CHARS),
        "mode": bounded_text(profile.get("mode", "etude"), P0_MAX_SCOPE_VALUE_CHARS),
    }


def new_active_session(profile, phone=None, now=None, session_id=None):
    now = now or datetime.now(timezone.utc)
    return {
        "schema_version": P0_SCHEMA_VERSION,
        "phone": bounded_text(phone, P0_MAX_SCOPE_VALUE_CHARS),
        "session_id": session_id or uuid.uuid4().hex,
        "status": "active",
        **p0_profile_fields(profile),
        "profile_revision": profile.get("revision"),
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


def prepare_active_session(stored_state, profile, message_id, phone=None, now=None):
    now = now or datetime.now(timezone.utc)
    state = dict(stored_state or {})
    normalized_message_id = bounded_text(message_id, P0_MAX_MESSAGE_ID_CHARS)
    duplicate = bool(normalized_message_id and state.get("last_processed_message_id") == normalized_message_id)
    expired = parse_datetime(state.get("expires_at"))
    scope_changed = any(state.get(key) != value for key, value in p0_profile_fields(profile).items())
    if (not state or expired is None or now >= expired or scope_changed
            or state.get("schema_version") != P0_SCHEMA_VERSION):
        state = new_active_session(profile, phone=phone, now=now)
        duplicate = False
    return state, duplicate


def transition_after_success(prepared_state, student_answer, akili_response, message_id,
                             document=None, exercise=None, current_question=None,
                             structured_results=None, next_expected_action="await_student_answer",
                             now=None):
    if not isinstance(akili_response, str) or not akili_response.strip():
        raise ValueError("Une réponse Akili non vide est requise")
    now = now or datetime.now(timezone.utc)
    next_state = dict(prepared_state)
    previous_document = nullable_document(prepared_state.get("document"))
    next_document = nullable_document(document if document is not None else previous_document)
    document_changed = previous_document != next_document
    previous_exercise = nullable_exercise(prepared_state.get("exercise"))
    next_exercise = nullable_exercise(
        exercise if exercise is not None else (None if document_changed else previous_exercise)
    )
    previous_results = (
        [] if document_changed or previous_exercise != next_exercise
        else prepared_state.get("relevant_previous_results", [])
    )
    results = normalize_structured_results(list(previous_results) + list(structured_results or []))
    next_state.update({
        "document": next_document,
        "exercise": next_exercise,
        "current_question": nullable_question(
            current_question if current_question is not None
            else (None if document_changed else prepared_state.get("current_question"))
        ),
        "current_step": int(prepared_state.get("current_step", 0)) + 1,
        "student_last_answer": {
            "message_id": bounded_text(message_id, P0_MAX_MESSAGE_ID_CHARS),
            "value": bounded_text(student_answer, P0_MAX_STUDENT_ANSWER_CHARS),
            "normalized_value": None,
            "created_at": now,
        },
        "relevant_previous_results": results,
        "next_expected_action": bounded_text(next_expected_action, P0_MAX_SCOPE_VALUE_CHARS),
        "last_processed_message_id": bounded_text(message_id, P0_MAX_MESSAGE_ID_CHARS),
        "updated_at": now,
        "expires_at": now + timedelta(minutes=P0_SESSION_TTL_MINUTES),
        "revision": int(prepared_state.get("revision", 0)) + 1,
    })
    return next_state


def load_active_session(phone):
    snapshot = feedback_db.collection(ACTIVE_SESSIONS_COLLECTION).document(phone).get()
    return snapshot.to_dict() if snapshot.exists else None


def save_active_session_if_revision(phone, state, expected_revision):
    reference = feedback_db.collection(ACTIVE_SESSIONS_COLLECTION).document(phone)
    transaction = feedback_db.transaction()

    @firestore.transactional
    def save(tx):
        snapshot = reference.get(transaction=tx)
        current = snapshot.to_dict() if snapshot.exists else None
        current_revision = int(current.get("revision", 0)) if current else 0
        if current_revision != expected_revision:
            return False
        tx.set(reference, state)
        return True

    return save(transaction)


def delete_active_session(phone):
    feedback_db.collection(ACTIVE_SESSIONS_COLLECTION).document(phone).delete()


def normalize_p0_response(response):
    details = {"text": response} if isinstance(response, str) else dict(response or {})
    response_text = details.get("text")
    if not isinstance(response_text, str) or not response_text.strip():
        raise ValueError("Réponse Akili vide")
    current_question = details.get("current_question")
    if not isinstance(current_question, dict):
        matches = re.findall(r"(?:^|[.!?])\s*([^.!?\n]{1,1499}\?)", response_text)
        current_question = ({"id": None, "text": matches[-1].strip(),
                             "expected_response_type": "short_text"} if matches else None)
    return response_text, {
        "document": details.get("document"),
        "exercise": details.get("exercise"),
        "current_question": current_question,
        "structured_results": details.get("structured_results") or [],
        "next_expected_action": details.get("next_expected_action") or "await_student_answer",
    }


def build_active_session_prompt(state):
    """Construit uniquement le contexte pédagogique borné nécessaire à la reprise."""
    if not state:
        return ""
    context = {
        "session_id": state.get("session_id"),
        "document": nullable_document(state.get("document")),
        "exercise": nullable_exercise(state.get("exercise")),
        "current_question": nullable_question(state.get("current_question")),
        "current_step": state.get("current_step", 0),
        "relevant_previous_results": normalize_structured_results(
            state.get("relevant_previous_results", [])
        ),
        "next_expected_action": bounded_text(
            state.get("next_expected_action"), P0_MAX_SCOPE_VALUE_CHARS
        ),
    }
    return json.dumps(context, ensure_ascii=False, separators=(",", ":"), default=str)


def persist_document_media(media_file, phone, document):
    """Copie le média reçu dans GCS et retourne une référence durable bornée."""
    result = nullable_document(document)
    if not media_file:
        return result
    media_path = Path(media_file)
    if not media_path.exists():
        raise FileNotFoundError(f"Média WhatsApp introuvable: {media_path}")
    file_bytes = media_path.read_bytes()
    digest = hashlib.sha256(file_bytes).hexdigest()
    safe_phone = re.sub(r"[^0-9A-Za-z_-]+", "_", str(phone))[:64]
    safe_name = re.sub(r"[^0-9A-Za-z_.-]+", "_", media_path.name)[:160]
    blob_path = f"whatsapp_active_sessions/{safe_phone}/{digest}_{safe_name}"
    bucket = storage.Client().bucket(P0_MEDIA_BUCKET)
    bucket.blob(blob_path).upload_from_string(
        file_bytes,
        content_type=result.get("mime_type") or "application/octet-stream",
    )
    result["gcs_uri"] = f"gs://{P0_MEDIA_BUCKET}/{blob_path}"
    result["sha256"] = digest
    return result


def restore_document_media(document):
    """Restaure localement un média GCS pour le prochain appel Akili."""
    document = nullable_document(document)
    gcs_uri = document.get("gcs_uri")
    if not gcs_uri or not gcs_uri.startswith("gs://"):
        return None
    bucket_name, separator, blob_path = gcs_uri[5:].partition("/")
    if not separator or not bucket_name or not blob_path:
        return None
    suffix = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "application/pdf": ".pdf",
    }.get(document.get("mime_type"), ".bin")
    out_dir = Path("/tmp/whatsapp_active_sessions")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{document.get('sha256') or uuid.uuid4().hex}{suffix}"
    storage.Client().bucket(bucket_name).blob(blob_path).download_to_filename(str(out_path))
    return str(out_path)

def normalize_for_match(value):
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def has_expr(normalized_text, expr):
    expr_norm = normalize_for_match(expr)
    return re.search(rf"(?<![A-Z0-9]){re.escape(expr_norm)}(?![A-Z0-9])", normalized_text) is not None

# Mots-clés issus des programmes officiels DPFC Philosophie
# DPFC_BAC_TC_TD_TE_PHILOSOPHIE_PROGRAMME.pdf
# DPFC_BAC_TA1_TA2_PHILOSOPHIE_PROGRAMME.pdf
PHILO_KEYWORDS = [
    "CONNAISSANCE DE L HOMME",
    "CONNAISSANCE SCIENTIFIQUE",
    "CONNAISSANCE",
    "SCIENCE",
    "SCIENCES HUMAINES",
    "SCIENCES FORMELLES",
    "VERITE",
    "LANGAGE",
    "RAISON",
    "EXPERIENCE",
    "CONSCIENCE",
    "INCONSCIENT",
    "LIBERTE",
    "VIOLENCE",
    "AUTRUI",
    "SOCIETE",
    "ETAT",
    "NATION",
    "DROIT",
    "JUSTICE",
    "RELIGION",
    "DIEU",
    "MORALE",
    "OBLIGATION MORALE",
    "HISTOIRE DE L HUMANITE",
    "CULTURE",
    "CIVILISATION",
    "MYTHE",
    "PROGRES",
    "BONHEUR",
    "TRAVAIL",
    "TECHNIQUE",
    "ART",
    "DESIR",
    "PASSION",
    "PASSIONS",
    "NATURE HUMAINE",
    "VIVANT",
    "HOMME LIBRE",
    "ETRE LIBRE",
    "EST IL LIBRE",
    "PEUT IL ETRE LIBRE",
    "L HOMME EST IL LIBRE",
]



def save_feedback_whatsapp(phone, feedback_text, profile=None, original_message=None):
    try:
        profile = profile or {}
        feedback_db.collection("feedback_whatsapp").add({
            "phone": phone,
            "feedback": feedback_text,
            "original_message": original_message or "",
            "serie_detectee": profile.get("serie", ""),
            "matiere_detectee": profile.get("matiere", ""),
            "type_examen_detecte": profile.get("type_examen", ""),
            "mode_detecte": profile.get("mode", ""),
            "statut": "nouveau",
            "source": "whatsapp",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        print(f"Feedback WhatsApp enregistré pour {phone}", flush=True)
        return True
    except Exception as e:
        print(f"Erreur feedback WhatsApp: {repr(e)}", flush=True)
        return False




ACQUISITION_SOURCES = {
    "META-STUDENT": "META-STUDENT",
    "META-PARENT": "META-PARENT",
    "TERRAIN": "TERRAIN",
    "TEACHER-REF": "TEACHER-REF",
    "ORGANIC": "ORGANIC",
}

DEFAULT_CAMPAIGN = "GRAND-PILOTE-2026"


def extract_acquisition_tracking(text):
    """Detecte les codes de campagne dans le message WhatsApp et retourne le texte nettoye."""
    raw = text or ""
    upper = raw.upper()

    source = ""
    for code in ACQUISITION_SOURCES:
        variants = {
            code,
            code.replace("-", "_"),
            code.replace("-", " "),
        }
        if any(v in upper for v in variants):
            source = code
            break

    creative = ""
    m = re.search(r"\b(?:CREATIVE|VIDEO|AD)[-_ ]?([A-Z0-9_-]+)\b", upper)
    if m:
        creative = m.group(0).replace(" ", "-")

    clean = raw
    for code in ACQUISITION_SOURCES:
        clean = re.sub(rf"\b{re.escape(code)}\b", "", clean, flags=re.IGNORECASE)
        clean = re.sub(rf"\b{re.escape(code.replace('-', '_'))}\b", "", clean, flags=re.IGNORECASE)
        clean = re.sub(rf"\b{re.escape(code.replace('-', ' '))}\b", "", clean, flags=re.IGNORECASE)

    if creative:
        clean = re.sub(rf"\b{re.escape(creative)}\b", "", clean, flags=re.IGNORECASE)
        clean = re.sub(rf"\b{re.escape(creative.replace('-', ' '))}\b", "", clean, flags=re.IGNORECASE)

    clean = " ".join(clean.split()).strip()
    return clean, source, creative


def charger_etat_whatsapp(phone):
    """Recharge l'etat conversationnel depuis Firestore (survit au scale-to-zero)."""
    try:
        doc = feedback_db.collection("whatsapp_state").document(phone).get()
        if doc.exists:
            return doc.to_dict() or {}
    except Exception as e:
        print(f"Erreur charger_etat_whatsapp: {repr(e)}", flush=True)
    return {}

def sauver_etat_whatsapp(phone, profile):
    """Persiste l'etat conversationnel dans Firestore."""
    try:
        feedback_db.collection("whatsapp_state").document(phone).set(dict(profile or {}), merge=True)
    except Exception as e:
        print(f"Erreur sauver_etat_whatsapp: {repr(e)}", flush=True)

def effacer_etat_whatsapp(phone):
    """Supprime completement l'etat persiste dans Firestore (vrai reset)."""
    try:
        feedback_db.collection("whatsapp_state").document(phone).delete()
    except Exception as e:
        print(f"Erreur effacer_etat_whatsapp: {repr(e)}", flush=True)

def mark_onboarding_completed(phone, profile):
    """Marque la fin d'onboarding et sauvegarde le profil pilote."""
    profile = profile or {}
    now = datetime.now(timezone.utc).isoformat()

    profile["profile_ready"] = True
    profile["onboarding_step"] = ""
    profile.setdefault("onboarding_completed_at", now)
    profile.setdefault("campaign", DEFAULT_CAMPAIGN)
    profile.setdefault("acquisition_source", profile.get("acquisition_source") or "ORGANIC")

    try:
        feedback_db.collection("users").document(f"{phone}@afrjigi.com").set({
            "email": f"{phone}@afrjigi.com",
            "phone": phone,
            "source": "whatsapp",
            "acquisition_source": profile.get("acquisition_source", ""),
            "campaign": profile.get("campaign", ""),
            "creative": profile.get("creative", ""),
            "type_examen": profile.get("type_examen", ""),
            "serie": profile.get("serie", ""),
            "matiere": profile.get("matiere", ""),
            "mode": profile.get("mode", ""),
            "ville": profile.get("ville", ""),
            "nom_ecole": profile.get("nom_ecole", ""),
            "onboarding_completed_at": profile.get("onboarding_completed_at", ""),
            "last_profile_update": now,
        }, merge=True)
        print(f"WHATSAPP_ONBOARDING completed phone={phone} source={profile.get('acquisition_source', '')}", flush=True)
    except Exception as e:
        print(f"Erreur mark_onboarding_completed: {repr(e)}", flush=True)

    return profile


def mark_first_learning_request(phone, profile):
    """Marque la premiere vraie demande pedagogique apres onboarding."""
    profile = profile or {}
    if profile.get("first_learning_request_at"):
        return profile

    now = datetime.now(timezone.utc).isoformat()
    profile["first_learning_request_at"] = now

    try:
        feedback_db.collection("users").document(f"{phone}@afrjigi.com").set({
            "email": f"{phone}@afrjigi.com",
            "phone": phone,
            "first_learning_request_at": now,
            "acquisition_source": profile.get("acquisition_source", ""),
            "campaign": profile.get("campaign", ""),
            "creative": profile.get("creative", ""),
            "ville": profile.get("ville", ""),
            "nom_ecole": profile.get("nom_ecole", ""),
        }, merge=True)
        print(f"WHATSAPP_FIRST_LEARNING_REQUEST phone={phone}", flush=True)
    except Exception as e:
        print(f"Erreur mark_first_learning_request: {repr(e)}", flush=True)

    return profile



def save_whatsapp_event(phone, direction, text, profile=None, message_id=None, extra=None):
    """Enregistre les messages WhatsApp pour mesurer usage, retour et erreurs."""
    try:
        profile = profile or {}
        data = {
            "phone": phone,
            "direction": direction,
            "text": text or "",
            "message_id": message_id or "",
            "serie": profile.get("serie", ""),
            "matiere": profile.get("matiere", ""),
            "type_examen": profile.get("type_examen", ""),
            "mode": profile.get("mode", ""),
            "onboarding_step": profile.get("onboarding_step", ""),
            "acquisition_source": profile.get("acquisition_source", ""),
            "campaign": profile.get("campaign", ""),
            "creative": profile.get("creative", ""),
            "ville": profile.get("ville", ""),
            "nom_ecole": profile.get("nom_ecole", ""),
            "onboarding_completed_at": profile.get("onboarding_completed_at", ""),
            "first_learning_request_at": profile.get("first_learning_request_at", ""),
            "source": "whatsapp",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if extra:
            data.update(extra)

        feedback_db.collection("whatsapp_messages").add(data)
        print(f"WHATSAPP_EVENT saved direction={direction} phone={phone}", flush=True)
    except Exception as e:
        print(f"Erreur save_whatsapp_event: {repr(e)}", flush=True)



def transcribe_whatsapp_audio(audio_path):
    """Transcrit un audio WhatsApp via l'API Akili."""
    try:
        if not audio_path:
            return ""

        path = Path(audio_path)
        if not path.exists():
            print(f"WHATSAPP_AUDIO error: fichier introuvable {path}", flush=True)
            return ""

        mime_type = "audio/ogg"
        suffix = path.suffix.lower()

        if suffix == ".mp3":
            mime_type = "audio/mpeg"
        elif suffix == ".m4a":
            mime_type = "audio/mp4"
        elif suffix == ".wav":
            mime_type = "audio/wav"

        print(f"WHATSAPP_AUDIO transcribe path={path} mime={mime_type}", flush=True)

        with path.open("rb") as f:
            files = {"file": (path.name, f, mime_type)}
            res = requests.post(TRANSCRIBE_URL, files=files, timeout=90)

        print(f"WHATSAPP_AUDIO status={res.status_code} body={res.text[:500]}", flush=True)

        if res.status_code >= 400:
            return ""

        data = res.json()
        text = (
            data.get("text")
            or data.get("texte")
            or data.get("transcription")
            or data.get("transcript")
            or data.get("message")
            or ""
        )

        return str(text).strip()

    except Exception as e:
        print(f"Erreur transcribe_whatsapp_audio: {repr(e)}", flush=True)
        return ""


def download_whatsapp_media(media_id, filename="whatsapp_media", fallback_mime="application/octet-stream"):
    """Télécharge une image/document/audio WhatsApp depuis Graph API et retourne le chemin local."""
    try:
        if not WHATSAPP_TOKEN:
            print("WHATSAPP_MEDIA error: WHATSAPP_TOKEN manquant", flush=True)
            return None

        info_url = f"https://graph.facebook.com/v19.0/{media_id}"
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}

        info_res = requests.get(info_url, headers=headers, timeout=30)
        print(f"WHATSAPP_MEDIA info status={info_res.status_code} body={info_res.text[:300]}", flush=True)

        if info_res.status_code >= 400:
            return None

        info = info_res.json()
        media_url = info.get("url")
        mime_type = info.get("mime_type") or fallback_mime or "application/octet-stream"

        if not media_url:
            print("WHATSAPP_MEDIA error: url media absente", flush=True)
            return None

        media_res = requests.get(media_url, headers=headers, timeout=60)
        print(f"WHATSAPP_MEDIA download status={media_res.status_code} bytes={len(media_res.content)} mime={mime_type}", flush=True)

        if media_res.status_code >= 400 or not media_res.content:
            return None

        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename or "whatsapp_media")

        if "." not in safe_name:
            if "jpeg" in mime_type or "jpg" in mime_type:
                safe_name += ".jpg"
            elif "png" in mime_type:
                safe_name += ".png"
            elif "pdf" in mime_type:
                safe_name += ".pdf"
            elif "ogg" in mime_type:
                safe_name += ".ogg"
            elif "mpeg" in mime_type or "mp3" in mime_type:
                safe_name += ".mp3"
            else:
                safe_name += ".bin"

        out_dir = Path("/tmp/whatsapp_media")
        out_dir.mkdir(parents=True, exist_ok=True)

        out_path = out_dir / f"{media_id}_{safe_name}"
        out_path.write_bytes(media_res.content)

        print(f"WHATSAPP_MEDIA saved path={out_path}", flush=True)
        return str(out_path)

    except Exception as e:
        print(f"Erreur download_whatsapp_media: {repr(e)}", flush=True)
        return None


def detect_matiere_from_text(message):
    msg = normalize_for_match(message)
    matiere_patterns = [
        ("MATHS", ["MATH", "MATHS", "MATHEMATIQUES"]),
        ("PHILO", ["PHILO", "PHILOSOPHIE"] + PHILO_KEYWORDS),
        ("PC", ["PC", "PHYSIQUE", "CHIMIE", "PHYSIQUE CHIMIE"]),
        ("SVT", ["SVT", "SCIENCES DE LA VIE ET DE LA TERRE"]),
        ("HG", ["HG", "HISTOIRE", "GEOGRAPHIE", "HISTOIRE GEOGRAPHIE"]),
        ("ANGLAIS", ["ANGLAIS"]),
        ("ALLEMAND", ["ALLEMAND", "ALLEMANDE", "ALL", "GERMAN"]),
        ("ESPAGNOL", ["ESPAGNOL", "ESPAGNOLE", "ESP", "ESPANOL", "SPANISH"]),
        ("FRANCAIS", ["FRANCAIS", "FRANCAISE", "FRANÇAISE", "FRENCH"]),
        ("COMPTA", ["COMPTABILITE", "COMPTA"]),
        ("ECO", ["ECONOMIE", "ECO"]),
        ("DROIT", ["DROIT"]),
        ("ETUDE-CAS", ["ETUDE DE CAS", "ETUDE CAS"]),
    ]
    for value, patterns in matiere_patterns:
        if any(has_expr(msg, pat) for pat in patterns):
            return value
    return None


def is_other_or_concours(message):
    msg = normalize_for_match(message)
    return any(has_expr(msg, x) for x in [
        "CONCOURS", "INFIRMIER", "INFIRMIERE", "LICENCE", "UNIVERSITE",
        "MEDECINE", "SUPERIEUR", "BTS"
    ])


def choice_key(text):
    c = normalize_for_match(text)
    mapping = {
        "1": "a", "A": "a",
        "2": "b", "B": "b",
        "3": "c", "C": "c",
        "4": "d", "D": "d",
        "5": "e", "E": "e",
        "6": "f", "F": "f",
        "7": "g", "G": "g",
        "8": "h", "H": "h",
        "9": "i", "I": "i",
    }
    return mapping.get(c)


def ask_exam(phone):
    send_whatsapp(phone,
        "Bienvenue sur Akili.\n\n"
        "Quel niveau prépares-tu ?\n\n"
        "a. BEPC / 3e\n"
        "b. BAC Général\n"
        "c. BAC Technique\n"
        "d. Classe intermédiaire : 6e, 5e, 4e, Seconde ou Première\n"
        "e. Concours / autre\n\n"
        "Réponds par a, b, c, d ou e."
    )


def ask_serie_general(phone):
    send_whatsapp(phone,
        "Quelle série du BAC Général ?\n\n"
        "a. A1\n"
        "b. A2\n"
        "c. C\n"
        "d. D\n"
        "e. E\n\n"
        "Réponds par a, b, c, d ou e."
    )


def ask_serie_technique(phone):
    send_whatsapp(phone,
        "Quelle série du BAC Technique ?\n\n"
        "a. B\n"
        "b. G1\n"
        "c. G2\n"
        "d. F1\n"
        "e. F2/F3/F4\n\n"
        "Réponds par a, b, c, d ou e."
    )


def ask_seconde(phone):
    send_whatsapp(phone,
        "Tu es en seconde. Quelle série ?\n\n"
        "a. Seconde A\n"
        "b. Seconde C\n\n"
        "Réponds par a ou b."
    )


def ask_classe_intermediaire(phone):
    send_whatsapp(phone,
        "Tu es en quelle classe ?\n\n"
        "a. 6e\n"
        "b. 5e\n"
        "c. 4e\n"
        "d. Seconde A\n"
        "e. Seconde C\n"
        "f. Première A\n"
        "g. Première C\n"
        "h. Première D\n\n"
        "Réponds par a, b, c, d, e, f, g ou h."
    )



def ask_matiere_technique(phone, serie=None):
    send_whatsapp(phone,
        "Quelle matière veux-tu travailler ?\n\n"
        "a. Comptabilité Financière\n"
        "b. Comptabilité des sociétés\n"
        "c. Comptabilité Analytique\n"
        "d. Mathématiques financières\n"
        "e. Mathématique Générale\n"
        "f. Économie\n"
        "g. Expression Professionnelle\n"
        "h. Physique Appliquée\n"
        "i. Étude des Systèmes Techniques Industriels\n"
        "j. Droit\n"
        "k. Histoire-Géographie\n"
        "l. Français\n\n"
        "Réponds par a, b, c, d, e, f, g, h, i, j, k ou l."
    )


def ask_matiere(phone, serie="TOUTES"):
    serie = (serie or "").upper().strip()

    if serie == "BEPC":
        send_whatsapp(phone,
            "Quelle matière veux-tu travailler ?\n\n"
            "a. Mathématiques\n"
            "b. Physique-Chimie\n"
            "c. SVT\n"
            "d. Français\n"
            "e. Histoire-Géographie\n"
            "f. EDHC\n"
            "g. Espagnol\n"
            "h. Allemand\n"
            "i. Anglais\n\n"
            "Réponds par a, b, c, d, e, f, g, h ou i."
        )
        return

    send_whatsapp(phone,
        "Quelle matière veux-tu travailler ?\n\n"
        "a. Mathématiques\n"
        "b. Physique-Chimie\n"
        "c. SVT\n"
        "d. Français\n"
        "e. Philosophie\n"
        "f. Histoire-Géographie\n"
        "g. Espagnol\n"
        "h. Allemand\n"
        "i. Anglais\n\n"
        "Réponds par a, b, c, d, e, f, g, h ou i."
    )


def ask_mode(phone):
    send_whatsapp(phone,
        "Tu veux travailler comment ?\n"
        "a) Mode Étude : comprendre un cours\n"
        "b) Mode Examen : s'entraîner\n\n"
        "Réponds par a ou b."
    )



def ask_ville(phone):
    send_whatsapp(phone,
        "Dans quelle ville es-tu ?\n"
        "Réponds seulement avec le nom de la ville.\n"
        "Exemples : Abidjan, Bouaké, Korhogo, Daloa, Yamoussoukro."
    )


def ask_nom_ecole(phone):
    send_whatsapp(phone,
        "Quel est le nom de ton école ou lycée ?\n"
        "Réponds seulement avec le nom de l'établissement.\n"
        "Si tu préfères ne pas répondre, écris seulement : passer."
    )


def mot_cle_vers_lettre(step, text, profile):
    """Convertit une reponse en texte libre (ex: BEPC, maths, mode etude) en lettre
    de choix (a, b, c...), pour les etapes ou l'eleve ne repond pas directement par
    une lettre ou un chiffre."""
    msg = normalize_for_match(text)

    if step == "matiere" and profile.get("type_examen") != "BAC_TECHNIQUE":
        matiere = detect_matiere_from_text(text)
        if matiere:
            if (profile.get("serie") or "").upper().strip() == "BEPC":
                values = {"a": "MATHS", "b": "PC", "c": "SVT", "d": "FRANCAIS", "e": "HG", "f": "EDHC", "g": "ESPAGNOL", "h": "ALLEMAND", "i": "ANGLAIS"}
            else:
                values = {"a": "MATHS", "b": "PC", "c": "SVT", "d": "FRANCAIS", "e": "PHILO", "f": "HG", "g": "ESPAGNOL", "h": "ALLEMAND", "i": "ANGLAIS"}
            for lettre, val in values.items():
                if val == matiere:
                    return lettre
        return None

    mots_cles_par_etape = {
        "exam": {
            "a": ["BEPC", "3E", "3EME", "TROISIEME"],
            "b": ["BAC GENERAL", "GENERAL"],
            "c": ["BAC TECHNIQUE", "TECHNIQUE"],
            "d": ["INTERMEDIAIRE", "6E", "5E", "4E", "SECONDE", "PREMIERE"],
            "e": ["CONCOURS", "AUTRE"],
        },
        "serie_general": {
            "a": ["A1"], "b": ["A2"],
            "c": ["SERIE C", "TERMINALE C", "TERMINAL C"],
            "d": ["SERIE D", "TERMINALE D", "TERMINAL D"],
            "e": ["SERIE E", "TERMINALE E", "TERMINAL E"],
        },
        "serie_technique": {
            "a": ["SERIE B", "TERMINALE B", "TERMINAL B"],
            "b": ["G1"], "c": ["G2"], "d": ["F1"], "e": ["F2", "F3", "F4"],
        },
        "seconde": {
            "a": ["SECONDE A", "2NDE A"],
            "b": ["SECONDE C", "2NDE C"],
        },
        "classe_intermediaire": {
            "a": ["6E", "SIXIEME"],
            "b": ["5E", "CINQUIEME"],
            "c": ["4E", "QUATRIEME"],
            "d": ["SECONDE A"],
            "e": ["SECONDE C"],
            "f": ["PREMIERE A"],
            "g": ["PREMIERE C"],
            "h": ["PREMIERE D"],
        },
        "matiere": {
            "a": ["COMPTABILITE FINANCIERE", "COMPTA FINANCIERE"],
            "b": ["COMPTABILITE DES SOCIETES", "COMPTA SOCIETES"],
            "c": ["COMPTABILITE ANALYTIQUE", "COMPTA ANALYTIQUE"],
            "d": ["MATHEMATIQUES FINANCIERES", "MATHS FINANCIERES"],
            "e": ["MATHEMATIQUE GENERALE", "MATHS GENERALE"],
            "f": ["ECONOMIE"],
            "g": ["EXPRESSION PROFESSIONNELLE"],
            "h": ["PHYSIQUE APPLIQUEE"],
            "i": ["ETUDE DES SYSTEMES", "SYSTEMES TECHNIQUES", "ESTI"],
            "j": ["DROIT"],
            "k": ["HISTOIRE GEOGRAPHIE", "HG"],
            "l": ["FRANCAIS"],
        },
        "mode": {
            "a": ["MODE ETUDE", "ETUDE", "COMPRENDRE"],
            "b": ["MODE EXAMEN", "EXAMEN", "ENTRAINER"],
        },
        "menu_choice": {
            "a": ["MATIERE"],
            "b": ["NIVEAU", "SERIE", "EXAMEN"],
        },
    }

    mapping = mots_cles_par_etape.get(step)
    if not mapping:
        return None

    for lettre, mots in mapping.items():
        if any(has_expr(msg, mot) for mot in mots):
            return lettre
    return None


def handle_onboarding_choice(phone, profile, text):
    step = profile.get("onboarding_step")
    if not step:
        return False

    if step == "ville":
        ville = (text or "").strip()
        ville_norm = normalize_for_match(ville)
        invalid_villes = {"OUI", "OK", "D ACCORD", "C EST CA", "C'EST CA", "CA", "NON", "PASSER", "PASSE", "PAS DE COMMENTAIRE"}
        if len(ville) < 2 or ville_norm in invalid_villes:
            send_whatsapp(phone, "Écris seulement le nom de ta ville. Exemple : Abidjan.")
            return True
        profile["ville"] = ville[:80]
        profile["onboarding_step"] = "nom_ecole"
        user_profiles[phone] = profile
        sauver_etat_whatsapp(phone, profile)
        ask_nom_ecole(phone)
        return True

    if step == "nom_ecole":
        nom_ecole = (text or "").strip()
        nom_ecole_norm = normalize_for_match(nom_ecole)
        skip_ecole = (
            nom_ecole_norm in {"PASSER", "PASSE", "SKIP", "NON", "AUCUN", "PAS DE COMMENTAIRE"}
            or nom_ecole_norm.startswith("PASSER ")
            or nom_ecole_norm.startswith("PASSE ")
        )
        if skip_ecole:
            nom_ecole = ""
        profile["nom_ecole"] = nom_ecole[:120]
        profile["nom_ecole_asked"] = True
        profile = mark_onboarding_completed(phone, profile)
        user_profiles[phone] = profile
        sauver_etat_whatsapp(phone, profile)
        send_whatsapp(phone,
            f"Profil prêt : {profile.get('type_examen', 'BAC_GENERAL')}, série {profile.get('serie', 'TOUTES')}, {profile.get('matiere', 'MATHS')}, mode {profile.get('mode', 'etude')}.\n\n"
            "Envoie maintenant ton exercice, une photo, un PDF ou le chapitre à travailler.\n\n"
                "Commandes utiles :\n"
                "- menu : changer de matiere ou de niveau\n"
                "- changer profil : modifier ton niveau, ta série ou ta matière\n"
                "- retour: ton avis sur Akili\n\n"
                "Pendant le Grand Pilote, ton avis compte beaucoup."
        )
        return True

    key = choice_key(text) or mot_cle_vers_lettre(step, text, profile)
    if not key:
        return False

    if step == "menu_choice":
        if key == "a":
            profile["onboarding_step"] = "matiere"
            profile.pop("profile_locked", None)
            profile.pop("matiere_confirmed", None)
            user_profiles[phone] = profile
            sauver_etat_whatsapp(phone, profile)
            if profile.get("type_examen") == "BAC_TECHNIQUE":
                ask_matiere_technique(phone, profile.get("serie"))
            else:
                ask_matiere(phone, profile.get("serie", "TOUTES"))
            return True
        if key == "b":
            profile["onboarding_step"] = "exam"
            profile.pop("profile_locked", None)
            profile.pop("matiere_confirmed", None)
            user_profiles[phone] = profile
            sauver_etat_whatsapp(phone, profile)
            ask_exam(phone)
            return True

    if step == "exam":
        if key == "a":
            profile["type_examen"] = "BEPC"
            profile["serie"] = "BEPC"
            profile["onboarding_step"] = "matiere"
            user_profiles[phone] = profile
            sauver_etat_whatsapp(phone, profile)
            ask_matiere(phone, "BEPC")
            return True
        if key == "b":
            profile["type_examen"] = "BAC_GENERAL"
            profile["onboarding_step"] = "serie_general"
            user_profiles[phone] = profile
            sauver_etat_whatsapp(phone, profile)
            ask_serie_general(phone)
            return True
        if key == "c":
            profile["type_examen"] = "BAC_TECHNIQUE"
            profile["onboarding_step"] = "serie_technique"
            user_profiles[phone] = profile
            sauver_etat_whatsapp(phone, profile)
            ask_serie_technique(phone)
            return True
        if key == "d":
            profile["type_examen"] = "CLASSE_INTERMEDIAIRE"
            profile["onboarding_step"] = "classe_intermediaire"
            user_profiles[phone] = profile
            sauver_etat_whatsapp(phone, profile)
            ask_classe_intermediaire(phone)
            return True
        if key == "e":
            profile["type_examen"] = "AUTRE"
            profile["serie"] = "AUTRE"
            profile["onboarding_step"] = "autre"
            user_profiles[phone] = profile
            sauver_etat_whatsapp(phone, profile)
            send_whatsapp(phone, "Akili accompagne surtout le collège, le lycée, le BEPC et le BAC. Pour ton concours ou ton niveau supérieur, précise la matière ou le besoin.")
            return True


    if step == "serie_general":
        values = {"a": "A1", "b": "A2", "c": "C", "d": "D", "e": "E"}
        if key in values:
            profile["serie"] = values[key]
            profile["onboarding_step"] = "matiere"
            user_profiles[phone] = profile
            sauver_etat_whatsapp(phone, profile)
            ask_matiere(phone, profile["serie"])
            return True

    if step == "serie_technique":
        values = {"a": "B", "b": "G1", "c": "G2", "d": "F1", "e": "F2"}
        if key in values:
            profile["serie"] = values[key]
            profile["onboarding_step"] = "matiere"
            user_profiles[phone] = profile
            sauver_etat_whatsapp(phone, profile)
            ask_matiere_technique(phone, profile["serie"])
            return True

    if step == "seconde":
        values = {"a": "A", "b": "C"}
        if key in values:
            profile["serie"] = values[key]
            profile["type_examen"] = "BAC_GENERAL"
            profile["onboarding_step"] = "matiere"
            user_profiles[phone] = profile
            sauver_etat_whatsapp(phone, profile)
            ask_matiere(phone, profile["serie"])
            return True

    if step == "classe_intermediaire":
        values = {
            "a": "6E",
            "b": "5E",
            "c": "4E",
            "d": "SECONDE_A",
            "e": "SECONDE_C",
            "f": "PREMIERE_A",
            "g": "PREMIERE_C",
            "h": "PREMIERE_D",
        }
        if key in values:
            profile["serie"] = values[key]
            profile["onboarding_step"] = "matiere"
            user_profiles[phone] = profile
            sauver_etat_whatsapp(phone, profile)
            ask_matiere(phone, profile["serie"])
            return True

    if step == "matiere":
        if profile.get("type_examen") == "BAC_TECHNIQUE":
            values = {
                "a": "COMPTA_FIN",
                "b": "COMPTA_SOCIETES",
                "c": "COMPTA_ANALYTIQUE",
                "d": "MATHS_FIN",
                "e": "MATHS_GENERAL",
                "f": "ECO",
                "g": "EXPRESSION_PRO",
                "h": "PHYSIQUE_APPLIQUEE",
                "i": "ESTI",
                "j": "DROIT",
                "k": "HG",
                "l": "FRANCAIS",
            }
        else:
            if (profile.get("serie") or "").upper().strip() == "BEPC":
                values = {"a": "MATHS", "b": "PC", "c": "SVT", "d": "FRANCAIS", "e": "HG", "f": "EDHC", "g": "ESPAGNOL", "h": "ALLEMAND", "i": "ANGLAIS"}
            else:
                values = {"a": "MATHS", "b": "PC", "c": "SVT", "d": "FRANCAIS", "e": "PHILO", "f": "HG", "g": "ESPAGNOL", "h": "ALLEMAND", "i": "ANGLAIS"}

        if key in values:
            profile["matiere"] = values[key]
            profile["matiere_confirmed"] = True
            profil_deja_complet = (
                profile.get("mode")
                and profile.get("ville")
                and (profile.get("nom_ecole") or profile.get("nom_ecole_asked"))
            )
            if profil_deja_complet:
                profile = mark_onboarding_completed(phone, profile)
                user_profiles[phone] = profile
                sauver_etat_whatsapp(phone, profile)
                send_whatsapp(phone,
                    f"C'est note : {profile.get('type_examen', 'BAC_GENERAL')}, serie {profile.get('serie', 'TOUTES')}, {profile.get('matiere', 'MATHS')}, mode {profile.get('mode', 'etude')}.\n\n"
                    "Envoie maintenant ton exercice, une photo, un PDF ou le chapitre a travailler."
                )
                return True
            profile["onboarding_step"] = "mode"
            user_profiles[phone] = profile
            sauver_etat_whatsapp(phone, profile)
            ask_mode(phone)
            return True

    if step == "mode":
        if key in {"a", "b"}:
            profile["mode"] = "etude" if key == "a" else "examen"

            if not profile.get("ville"):
                profile["onboarding_step"] = "ville"
                user_profiles[phone] = profile
                sauver_etat_whatsapp(phone, profile)
                ask_ville(phone)
                return True

            if not profile.get("nom_ecole") and not profile.get("nom_ecole_asked"):
                profile["onboarding_step"] = "nom_ecole"
                user_profiles[phone] = profile
                sauver_etat_whatsapp(phone, profile)
                ask_nom_ecole(phone)
                return True

            profile = mark_onboarding_completed(phone, profile)
            user_profiles[phone] = profile
            sauver_etat_whatsapp(phone, profile)
            send_whatsapp(phone,
                f"Profil prêt : {profile.get('type_examen', 'BAC_GENERAL')}, série {profile.get('serie', 'TOUTES')}, {profile.get('matiere', 'MATHS')}, mode {profile.get('mode', 'etude')}.\n\n"
                "Envoie maintenant ton exercice, une photo, un PDF ou le chapitre à travailler.\n\n"
                "Commandes utiles :\n"
                "- menu : changer de matiere ou de niveau\n"
                "- changer profil : modifier ton niveau, ta série ou ta matière\n"
                "- retour: ton avis sur Akili\n\n"
                "Pendant le Grand Pilote, ton avis compte beaucoup."
            )
            return True

    return False


def needs_onboarding(phone, profile, text):
    msg = normalize_for_match(text)

    if is_other_or_concours(text):
        profile["type_examen"] = "AUTRE"
        profile["serie"] = "AUTRE"
        profile["onboarding_step"] = "autre"
        user_profiles[phone] = profile
        send_whatsapp(phone,
            "Akili est d'abord conçu pour le BEPC et le BAC.\n\n"
            "Mais je peux noter ton besoin pour concours / supérieur. Précise ce que tu veux travailler : français, culture générale, raisonnement, biologie, etc."
        )
        return True

    if has_expr(msg, "SECONDE") and profile.get("serie") in {"TOUTES", "", None}:
        profile["onboarding_step"] = "seconde"
        user_profiles[phone] = profile
        ask_seconde(phone)
        return True

    matiere_explicit = detect_matiere_from_text(text)
    if matiere_explicit:
        profile["matiere"] = matiere_explicit
        profile["matiere_confirmed"] = True

    # Si l'élève a donné une série/niveau mais pas de matière explicite, on clarifie.
    has_level_or_series = (
        profile.get("serie") not in {"TOUTES", "", None}
        or any(has_expr(msg, x) for x in ["TERMINAL", "TERMINALE", "TLE", "SECONDE", "PREMIERE", "1ERE", "BEPC"])
    )
    if has_level_or_series and not profile.get("matiere_confirmed") and not matiere_explicit:
        profile["onboarding_step"] = "matiere"
        user_profiles[phone] = profile
        ask_matiere(phone, profile.get("serie", "TOUTES"))
        return True

    return False


def clean_whatsapp_response(message):
    """Nettoie les reponses avant envoi WhatsApp en gardant les retours a la ligne."""
    text = str(message or "").strip()

    # Format WhatsApp : puces "- " ou "* " -> "• ", et gras Markdown "**texte**" -> "*texte*"
    text = re.sub(r"(?m)^[ \t]*[-*]\s+", "• ", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)

    # Symboles LaTeX courants.
    text = re.sub(r"\\+infty\b", "∞", text)
    text = re.sub(r"\\+ge\b", ">=", text)
    text = re.sub(r"\\+le\b", "<=", text)
    text = re.sub(r"\\+mathrmlim\b", "lim", text)
    text = re.sub(r"\\+mathrm\{lim\}", "lim", text)
    text = re.sub(r"\\+operatorname\{lim\}", "lim", text)
    text = re.sub(r"\\+ln\b", "ln", text)
    text = re.sub(r"\\+times\b", "×", text)
    text = re.sub(r"\\+cdot\b", "×", text)
    text = re.sub(r"\\+pi\b", "π", text)

    # Forme compacte : \frac1\sqrt5-2 signifie 1/(sqrt(5)-2).
    text = re.sub(
        r"\\+frac\s*\{?([+-]?\d+)\}?\s*\\+sqrt\s*\{?(\d+)\}?\s*([+-]\s*\d+)",
        r"(\1)/(√\2\3)",
        text,
    )

    # Fractions classiques.
    text = re.sub(
        r"\\+frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}",
        r"(\1)/(\2)",
        text,
    )

    # Vecteurs avec indices.
    subscript_table = str.maketrans("0123456789+-", "₀₁₂₃₄₅₆₇₈₉₊₋")

    def clean_vector(match):
        symbol = match.group(1) or match.group(3)
        index = match.group(2) or match.group(4) or ""
        return "vecteur " + symbol + index.translate(subscript_table)

    text = re.sub(
        r"\\+vec\s*(?:\{([A-Za-z]+)(?:_?\{?([0-9]+)\}?)?\}|([A-Za-z]+))(?:_?\{?([0-9]+)\}?)?",
        clean_vector,
        text,
    )

    def clean_long_vector(match):
        return match.group(1) + "→"

        r"\\+(?:vec|overrightarrow)\s*(?:\{([A-Za-z]+)(?:_?\{?([0-9]+)\}?)?\}|([A-Za-z]+))(?:_?\{?([0-9]+)\}?)?"

    # Racines, exposants et normes.
    text = re.sub(r"\\+sqrt\s*\{([^{}]+)\}", r"√(\1)", text)
    text = re.sub(r"\\+sqrt\s*([A-Za-z0-9.]+)", r"√\1", text)
    text = re.sub(r"\bsqrt\s*\(", "√(", text, flags=re.IGNORECASE)
    text = re.sub(r"\^\{?2\}?", "²", text)
    text = re.sub(r"\^\{?3\}?", "³", text)
    text = text.replace("||", "‖")
    text = text.replace("\\|", "‖")

    # Fractions compactes restantes.
    text = re.sub(r"\\+frac\s*([+-]?\d+)\s*(√[A-Za-z0-9.]+)", r"(\1)/(\2)", text)
    text = re.sub(r"\\+frac\s*([+-]?\d+)\s*([A-Za-z0-9.]+)", r"(\1)/(\2)", text)
    # \fracba (deux termes colles, lettres ou chiffres, sans accolades) -> (b)/(a)
    text = re.sub(r"\\+frac\s*([A-Za-z0-9.]+)\s*([A-Za-z0-9.]+)", r"(\1)/(\2)", text)
    # \frac restant isole -> retire le backslash au minimum
    text = re.sub(r"\\+frac\b", "", text)

    text = text.replace("\\mathbb{R}", "R")
    text = text.replace("\\rightarrow", "->")
    text = text.replace("\\to", "->")
    text = text.replace("\\lim", "lim")
    text = text.replace("\\in", "dans")
    text = text.replace("\\left", "")
    text = text.replace("\\right", "")

    replacements = {
        "$$": "",
        "$": "",
        "\\mathbb": "",
        "\\(": "",
        "\\)": "",
        "\\[": "",
        "\\]": "",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r"\{([^{}]+)\}", r"\1", text)

    # Preserve les retours a la ligne WhatsApp.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" \*\n \*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    text = text.strip()
    text = text.replace(" .", ".").replace(" ,", ",").replace(" ?", "?").replace(" !", "!")
    return text


def is_multiple_choice_answer(text):
    """Détecte les réponses du type a,b,c ou d et f pendant l'onboarding."""
    normalized = normalize_for_match(text)
    tokens = re.findall(r"\b[A-F]\b", normalized)
    return len(set(tokens)) > 1



def split_whatsapp_message(message, limit=850, max_parts=1, add_continuation=True):
    """Découpe une réponse WhatsApp sans couper au milieu d'un mot."""
    message = clean_whatsapp_response(message)
    if not message:
        return []

    parts = []
    remaining = message

    continuation = "\n\nJe m'arrête ici. Dis-moi si tu veux continuer."
    effective_limit = max(200, limit - len(continuation))

    while remaining and len(parts) < max_parts:
        if len(remaining) <= limit:
            parts.append(remaining.strip())
            remaining = ""
            break

        cut = remaining[:effective_limit]
        last_break = max(
            cut.rfind("\n\n"),
            cut.rfind("\n"),
            cut.rfind(". "),
            cut.rfind("? "),
            cut.rfind("! "),
            cut.rfind("; "),
            cut.rfind(", "),
        )

        if last_break < 120:
            space_break = cut.rfind(" ")
            last_break = space_break if space_break > 120 else effective_limit

        part = cut[:last_break + 1].strip()
        if part:
            parts.append(part)

        remaining = remaining[last_break + 1:].strip()

    if remaining and parts and add_continuation:
        parts[-1] = parts[-1].rstrip(" ,;:-") + continuation

    return parts

def format_whatsapp_message(message, limit=1400):
    """Compatibilité avec l'ancien appel : retourne seulement le premier bloc."""
    parts = split_whatsapp_message(message, limit=850, max_parts=1)
    return parts[0] if parts else ""



def send_whatsapp_typing_indicator(message_id):
    """Marque le message comme lu et affiche l'indicateur de saisie WhatsApp."""
    if not message_id:
        return

    try:
        url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json",
        }
        data = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
            "typing_indicator": {
                "type": "text"
            },
        }

        res = requests.post(url, headers=headers, json=data, timeout=10)
        print(f"WHATSAPP_TYPING status={res.status_code} body={res.text[:300]}", flush=True)
    except Exception as e:
        print(f"Erreur WHATSAPP_TYPING: {repr(e)}", flush=True)



def text_to_whatsapp_audio(text, phone):
    """Genere une reponse audio MP3 courte pour WhatsApp."""
    try:
        clean_text = clean_whatsapp_response(text or "").strip()
        if not clean_text:
            return None

        # gTTS reste plus fiable avec un texte court.
        if len(clean_text) > 900:
            clean_text = clean_text[:900].rsplit(" ", 1)[0] + "."

        out_dir = Path("/tmp/whatsapp_audio_replies")
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_phone = re.sub(r"[^0-9A-Za-z_-]+", "_", str(phone))
        out_path = out_dir / f"akili_reply_{safe_phone}_{int(time.time())}.mp3"

        tts = gTTS(text=clean_text, lang="fr")
        tts.save(str(out_path))

        print(f"WHATSAPP_AUDIO_REPLY generated path={out_path} bytes={out_path.stat().st_size}", flush=True)
        return str(out_path)
    except Exception as e:
        print(f"Erreur text_to_whatsapp_audio: {repr(e)}", flush=True)
        return None


def upload_whatsapp_audio(audio_path):
    """Upload un MP3 sur Meta WhatsApp et retourne le media_id."""
    try:
        if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
            print("WHATSAPP_AUDIO_REPLY upload skipped: token ou phone_number_id manquant", flush=True)
            return None

        path = Path(audio_path)
        if not path.exists():
            print(f"WHATSAPP_AUDIO_REPLY upload error: fichier introuvable {path}", flush=True)
            return None

        url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/media"
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        data = {
            "messaging_product": "whatsapp",
            "type": "audio/mpeg",
        }

        with path.open("rb") as f:
            files = {"file": (path.name, f, "audio/mpeg")}
            res = requests.post(url, headers=headers, data=data, files=files, timeout=60)

        print(f"WHATSAPP_AUDIO_REPLY upload status={res.status_code} body={res.text[:500]}", flush=True)

        if res.status_code >= 400:
            return None

        return res.json().get("id")
    except Exception as e:
        print(f"Erreur upload_whatsapp_audio: {repr(e)}", flush=True)
        return None


def send_whatsapp_audio(to, media_id):
    """Envoie un audio WhatsApp deja uploade sur Meta."""
    try:
        if not media_id:
            return False

        url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json",
        }
        data = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "audio",
            "audio": {"id": media_id},
        }

        res = requests.post(url, headers=headers, json=data, timeout=30)
        print(f"WHATSAPP_AUDIO_REPLY send status={res.status_code} body={res.text[:500]}", flush=True)

        if res.status_code < 300:
            save_whatsapp_event(
                to,
                "outbound",
                "[audio_reply]",
                user_profiles.get(to, {}),
                extra={"graph_status": res.status_code, "media_id": media_id, "message_type": "audio"}
            )
            return True

        return False
    except Exception as e:
        print(f"Erreur send_whatsapp_audio: {repr(e)}", flush=True)
        return False



def extract_vector_notations(message):
    """Extrait les vecteurs LaTeX ou decrits en langage naturel."""
    found = []

    def add_vector(symbol, index=""):
        item = (str(symbol or "").strip(), str(index or "").strip())
        if item[0] and item not in found:
            found.append(item)

    latex_pattern = re.compile(
        r"\\+(?:vec|overrightarrow)\s*(?:\{([A-Za-z]+)(?:_?\{?([0-9]+)\}?)?\}|([A-Za-z]+))(?:_?\{?([0-9]+)\}?)?"
    )
    for match in latex_pattern.finditer(str(message or "")):
        add_vector(
            match.group(1) or match.group(3),
            match.group(2) or match.group(4) or "",
        )

    plain_text = str(message or "").replace("*", "")
    candidates = []

    natural_patterns = [
        r"\bvecteur\s+vitesse\s+([A-Za-z])(?:\s+indice\s+([0-9]+))?",
        r"\bvecteur\s+(?!vitesse\b)([A-Za-z]{1,3})\b(?:\s+indice\s+([0-9]+))?",
        r"\bforce\s+([A-Za-z])\b(?:\s+indice\s+([0-9]+))?",
    ]

    for pattern in natural_patterns:
        for match in re.finditer(pattern, plain_text, flags=re.IGNORECASE):
            candidates.append(
                (match.start(), match.group(1), match.group(2) or "")
            )

    for _, symbol, index in sorted(candidates, key=lambda item: item[0]):
        add_vector(symbol, index)

    return found[:6]


def render_vector_formula_image(message, phone):
    """Cree un PNG avec une vraie fleche au-dessus de chaque vecteur."""
    vectors = extract_vector_notations(message)
    if not vectors:
        return None

    try:
        from PIL import Image, ImageDraw, ImageFont

        width = 1000
        row_height = 150
        height = 150 + row_height * len(vectors)
        image = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(image)

        regular_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        bold_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

        try:
            title_font = ImageFont.truetype(bold_path, 42)
            formula_font = ImageFont.truetype(regular_path, 58)
            label_font = ImageFont.truetype(regular_path, 30)
            index_font = ImageFont.truetype(regular_path, 34)
        except OSError:
            title_font = ImageFont.load_default()
            formula_font = ImageFont.load_default()
            label_font = ImageFont.load_default()
            index_font = ImageFont.load_default()

        navy = "#0B2B5B"
        orange = "#FF7A00"
        draw.text((50, 35), "Notation vectorielle", fill=navy, font=title_font)
        draw.line((50, 100, 950, 100), fill=orange, width=5)

        for position, (symbol, index) in enumerate(vectors):
            top = 140 + position * row_height
            draw.text((65, top + 38), "Vecteur", fill=navy, font=label_font)

            x = 285
            baseline = top + 30
            draw.text((x, baseline), symbol, fill="black", font=formula_font)
            box = draw.textbbox((x, baseline), symbol, font=formula_font)
            text_width = max(1, box[2] - box[0])
            arrow_width = max(55, text_width)

            arrow_y = top + 23
            arrow_start = x - 3
            arrow_end = x + arrow_width + 12
            draw.line((arrow_start, arrow_y, arrow_end, arrow_y), fill="black", width=4)
            draw.polygon(
                [
                    (arrow_end, arrow_y),
                    (arrow_end - 18, arrow_y - 10),
                    (arrow_end - 18, arrow_y + 10),
                ],
                fill="black",
            )

            if index:
                draw.text(
                    (x + text_width + 1, baseline + 37),
                    index,
                    fill="black",
                    font=index_font,
                )

        output_dir = Path("/tmp/whatsapp_formula_images")
        output_dir.mkdir(parents=True, exist_ok=True)
        safe_phone = re.sub(r"[^0-9A-Za-z-]+", "-", str(phone))
        output_path = output_dir / f"akili-vectors-{safe_phone}-{int(time.time())}.png"
        image.save(output_path, format="PNG", optimize=True)

        print(
            f"WHATSAPP_FORMULA_IMAGE generated path={output_path} "
            f"bytes={output_path.stat().st_size} vectors={len(vectors)}",
            flush=True,
        )
        return str(output_path)
    except Exception as exc:
        print(f"Erreur render_vector_formula_image: {repr(exc)}", flush=True)
        return None


def upload_whatsapp_image(image_path):
    """Televerse un PNG vers Meta et retourne son media_id."""
    try:
        path = Path(image_path)
        if not path.exists() or not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
            return None

        url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/media"
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        data = {"messaging_product": "whatsapp", "type": "image/png"}

        with path.open("rb") as image_file:
            files = {"file": (path.name, image_file, "image/png")}
            response = requests.post(
                url,
                headers=headers,
                data=data,
                files=files,
                timeout=60,
            )

        print(
            f"WHATSAPP_FORMULA_IMAGE upload status={response.status_code} "
            f"body={response.text[:500]}",
            flush=True,
        )
        if response.status_code >= 400:
            return None
        return response.json().get("id")
    except Exception as exc:
        print(f"Erreur upload_whatsapp_image: {repr(exc)}", flush=True)
        return None


def send_whatsapp_image(to, media_id, caption="Notation mathematique exacte"):
    """Envoie une image WhatsApp deja televersee."""
    try:
        if not media_id:
            return False

        url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json",
        }
        data = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "image",
            "image": {"id": media_id, "caption": caption},
        }

        response = requests.post(url, headers=headers, json=data, timeout=30)
        print(
            f"WHATSAPP_FORMULA_IMAGE send status={response.status_code} "
            f"body={response.text[:500]}",
            flush=True,
        )

        if response.status_code < 300:
            save_whatsapp_event(
                to,
                "outbound",
                "[vector_formula_image]",
                user_profiles.get(to, {}),
                extra={
                    "graph_status": response.status_code,
                    "media_id": media_id,
                    "message_type": "image",
                },
            )
            return True
        return False
    except Exception as exc:
        print(f"Erreur send_whatsapp_image: {repr(exc)}", flush=True)
        return False


def send_vector_formula_if_needed(phone, raw_message):
    """Genere et envoie une image seulement si la reponse contient un vecteur LaTeX."""
    image_path = render_vector_formula_image(raw_message, phone)
    if not image_path:
        return False

    media_id = upload_whatsapp_image(image_path)
    if not media_id:
        return False

    return send_whatsapp_image(phone, media_id)


def send_whatsapp(to, message, limit=850, add_continuation=True):
    message = clean_whatsapp_response(message)

    now_ts = time.time()
    dedupe_key = str(to)
    previous = last_outbound_by_phone.get(dedupe_key)
    if previous:
        previous_text, previous_ts = previous
        if previous_text == message and now_ts - previous_ts < 20:
            print(f"WHATSAPP_SEND_DEDUPE skipped duplicate to={to}", flush=True)
            return

    last_outbound_by_phone[dedupe_key] = (message, now_ts)

    should_reply_audio = bool(audio_reply_context.get(str(to)))
    message_parts = split_whatsapp_message(message, limit=limit, max_parts=1, add_continuation=add_continuation)

    if not message_parts:
        return

    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    for index, part in enumerate(message_parts, start=1):
        print(f"WHATSAPP_SEND_TEXT part={index}/{len(message_parts)} len={len(part)}: {part}", flush=True)

        data = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": part},
        }

        res = requests.post(url, headers=headers, json=data)
        print(f"DEBUG SEND: Status {res.status_code} - Response: {res.text}", flush=True)

        if res.status_code < 300:
            save_whatsapp_event(
                to,
                "outbound",
                part,
                user_profiles.get(to, {}),
                extra={"graph_status": res.status_code}
            )
            save_last_assistant_context(to, part, user_profiles.get(to, {}))

            if should_reply_audio and index == 1:
                audio_reply_context[str(to)] = False
                print(f"WHATSAPP_AUDIO_REPLY auto_from_send_whatsapp to={to}", flush=True)
                audio_path = text_to_whatsapp_audio(part, to)
                media_id = upload_whatsapp_audio(audio_path) if audio_path else None
                if media_id:
                    send_whatsapp_audio(to, media_id)




def is_teacher_request(message):
    msg = normalize_for_match(message)
    teacher_patterns = [
        "ENSEIGNANT",
        "ENSEIGNANTE",
        "PROFESSEUR",
        "PROF",
        "JE SUIS PROF",
        "JE SUIS PROFESSEUR",
        "JE SUIS ENSEIGNANT",
        "J ENSEIGNE",
        "MES ELEVES",
        "MA CLASSE",
        "MON COURS",
        "PREPARER UN COURS",
        "PREPARER UNE EVALUATION",
        "EXERCICE POUR MES ELEVES",
    ]
    return any(has_expr(msg, x) for x in teacher_patterns)




def sauver_historique_conv(conversation_key, historique):
    """Persiste l'historique complet d'une conversation (survit au scale-to-zero)."""
    try:
        if not conversation_key:
            return
        doc_id = conversation_key.replace("/", "_")
        feedback_db.collection("whatsapp_historiques").document(doc_id).set({
            "conversation_key": conversation_key,
            "historique": historique[-10:],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, merge=True)
    except Exception as e:
        print(f"Erreur sauver_historique_conv: {repr(e)}", flush=True)


def charger_historique_conv(conversation_key):
    """Recharge l'historique depuis Firestore si la RAM est vide."""
    try:
        if not conversation_key:
            return []
        doc_id = conversation_key.replace("/", "_")
        doc = feedback_db.collection("whatsapp_historiques").document(doc_id).get()
        if doc.exists:
            data = doc.to_dict() or {}
            hist = data.get("historique", [])
            if isinstance(hist, list):
                return hist
    except Exception as e:
        print(f"Erreur charger_historique_conv: {repr(e)}", flush=True)
    return []


def save_last_assistant_context(phone, text, profile=None):
    """Persiste le dernier message pedagogique envoye a un utilisateur."""
    try:
        if not phone or not text:
            return
        profile = profile or user_profiles.get(phone, {}) or {}
        feedback_db.collection("whatsapp_contexts").document(str(phone)).set({
            "phone": str(phone),
            "last_assistant_text": text,
            "matiere": profile.get("matiere", ""),
            "serie": profile.get("serie", ""),
            "type_examen": profile.get("type_examen", ""),
            "mode": profile.get("mode", ""),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, merge=True)
    except Exception as e:
        print(f"Erreur save_last_assistant_context: {repr(e)}", flush=True)


def load_last_assistant_context(phone):
    """Recharge le dernier contexte pedagogique meme si Cloud Run a perdu la memoire."""
    try:
        doc = feedback_db.collection("whatsapp_contexts").document(str(phone)).get()
        if not doc.exists:
            return ""
        data = doc.to_dict() or {}
        return (data.get("last_assistant_text") or "").strip()
    except Exception as e:
        print(f"Erreur load_last_assistant_context: {repr(e)}", flush=True)
        return ""


def is_learning_request(text):
    """Détermine si le message ressemble à une vraie demande élève."""
    command = (text or "").strip().lower()
    simple_commands = {
        "bonjour", "bonsoir", "salut", "hello", "hi", "menu", "aide", "start",
        "profil", "profile", "reset", "réinitialiser", "reinitialiser",
        "a", "b", "c", "d", "e", "f", "1", "2", "3", "4", "5", "6",
    }

    if not command or command in simple_commands:
        return False

    if command.startswith("feedback:") or command.startswith("retour:"):
        return False

    if len(command) < 8:
        return False

    learning_markers = [
        "?", "explique", "expliquer", "corrige", "corriger", "sujet",
        "exercice", "cours", "chapitre", "dissertation", "commentaire",
        "math", "philo", "physique", "chimie", "svt", "français",
        "histoire", "géographie", "bac", "bepc", "terminale", "3eme",
        "troisième", "seconde", "premiere", "première",
    ]

    return any(marker in command for marker in learning_markers) or len(command) >= 25






def is_short_exercise_answer(text):
    """Detecte une reponse courte a un exercice interactif."""
    t = normalize_for_match(text or "").strip()
    t = t.strip(" .,!?:;")
    return t in {
        "VRAI", "VRAIE", "VRAIS", "VRAIES",
        "FAUX", "FAUSSE", "FAUSSES",
        "V", "F",
        "A", "B", "C", "D", "E",
        "1", "2", "3", "4", "5"
    }



def is_contextual_exercise_answer(text):
    """Détecte une réponse d'élève qui dépend clairement de la question précédente."""
    t = normalize_for_match(text or "").strip()
    compact = " ".join(t.split())

    if is_short_exercise_answer(text):
        return True

    markers = [
        "LE RESULTAT EST",
        "LE RESULTAT C EST",
        "RESULTAT EST",
        "J AI TROUVE",
        "JE TROUVE",
        "J OBTIENS",
        "ON OBTIENT",
        "CA DONNE",
        "ÇA DONNE",
        "MA REPONSE EST",
        "LA REPONSE EST",
        "C EST VRAI",
        "C EST FAUX",
    ]

    if any(m in compact for m in markers):
        return True

    return False


def has_recent_phone_context(phone):
    """Verifie qu'une reponse courte peut etre rattachee a un contexte recent."""
    prefix = f"{phone}:"
    for key, items in conversations.items():
        if key.startswith(prefix) and items:
            recent = items[-6:]
            if any(m.get("role") == "assistant" and m.get("content") for m in recent):
                return True
    return False




def get_recent_phone_context_text(phone, max_items=6):
    """Retourne le contexte récent en mémoire, sinon le dernier contexte sauvegardé dans Firestore."""
    prefix = f"{phone}:"
    best_items = []

    for key, items in conversations.items():
        if key.startswith(prefix) and items:
            best_items.extend(items[-max_items:])

    if best_items:
        lines = []
        for item in best_items[-max_items:]:
            role = item.get("role", "")
            content = item.get("content", "")
            if content:
                lines.append(f"{role}: {content}")
        if lines:
            return "\n".join(lines)

    last_assistant = load_last_assistant_context(phone)
    if last_assistant:
        return f"assistant: {last_assistant}"

    return ""



def short_answer_has_exercise_context(phone):
    ctx_brut = get_recent_phone_context_text(phone)
    ctx = normalize_for_match(ctx_brut)
    markers = [
        "VRAI OU FAUX",
        "VRAIE OU FAUSSE",
        "VRAI OU FAUSSE",
        "EST CE VRAI",
        "EST ELLE VRAIE",
        "AFFIRMATION",
        "QUESTION",
        "EXERCICE",
        "QCM",
        "REPONDS PAR",
        "CHOISIS",
    ]
    if any(m in ctx for m in markers):
        return True
    # Reconnaitre un QCM au format a) b) c) d)  ou  a- b- c-  ou  a. b. c.
    import re as _re
    choix = _re.findall(r"(?im)^\s*[a-eA-E1-6]\s*[\)\.\-]", ctx_brut or "")
    if len(set(x.strip()[0].lower() for x in choix)) >= 2:
        return True
    return False


def build_short_answer_prompt(phone, answer):
    ctx = get_recent_phone_context_text(phone)
    return (
        "L'élève vient de répondre uniquement : "
        f"{answer}\n\n"
        "Tu dois répondre UNIQUEMENT à partir du dernier exercice ou de la dernière question dans l'historique récent. "
        "Ne change pas de sujet. Ne prends pas un autre sujet d'annale. "
        "Ne remplace pas l'exercice par un BAC 2025 ou 2026 différent. "
        "Dis si la réponse de l'élève est correcte, explique brièvement pourquoi, puis propose la suite logique.\n\n"
        f"HISTORIQUE RECENT A UTILISER OBLIGATOIREMENT :\n{ctx}"
    )



def soften_exercise_number_references(text):
    """Evite les numeros d'exercice inventes ou ambigus dans les suivis WhatsApp."""
    if not text:
        return text

    # On NE reecrit plus les numeros d'exercice : quand l'eleve demande
    # "exercice 2", Akili doit pouvoir dire "Exercice 2, question 1" clairement.
    # (Ancien comportement : tout "l'Exercice N" devenait "cet exercice",
    #  ce qui effacait les numeros legitimes et creait de la confusion.)
    replacements = []

    cleaned = text
    for pattern, repl in replacements:
        cleaned = re.sub(pattern, repl, cleaned)

    return cleaned


def clean_teacher_spanish_activity(text):
    """Nettoie les réponses enseignant espagnol pour garder la fiche directement exploitable."""
    text = clean_whatsapp_response(text or "").strip()

    # Nettoyage Markdown pour WhatsApp: garder le texte lisible sans astérisques cassés.
    for bad, good in [
        ("**", ""),
        ("*", ""),
        ("Titre :", "Titre :"),
        ("Objectif :", "Objectif :"),
        ("Situation :", "Situation :"),
        ("Support :", "Support :"),
        ("Exercice :", "Exercice :"),
        ("Corrigé indicatif :", "Corrigé indicatif :"),
    ]:
        text = text.replace(bad, good)

    # Supprimer les salutations/introductions avant les rubriques utiles.
    markers = [
        "Titre de la leçon :",
        "Titre de la leçon:",
        "Titre :",
        "Titre:",
        "Niveau :",
        "Niveau:",
        "Compétence :",
        "Compétence:",
        "Fonction langagière :",
        "Fonction langagière:",
        "Situation d'apprentissage :",
        "Situation d'apprentissage:",
        "Situation :",
        "Situation:",
        "Objectif :",
        "Objectif:",
        "Support :",
        "Support:",
        "Activité :",
        "Activité:",
        "Production attendue :",
        "Production attendue:",
    ]

    positions = [text.find(m) for m in markers if text.find(m) != -1]
    if positions:
        start = min(positions)
        if start > 0:
            text = text[start:].strip()

    # Si le modèle n'a pas mis "Titre", transformer une réponse structurée en fiche plus stricte.
    if not text.lower().startswith("titre") and "Objectif" in text:
        idx = text.find("Objectif")
        if idx > 0:
            text = text[idx:].strip()

    return enforce_teacher_whatsapp_limit(text, limit=900)

def enforce_teacher_whatsapp_limit(text, limit=900):
    """Force une réponse enseignant courte avant envoi WhatsApp."""
    text = clean_whatsapp_response(text or "")

    forbidden = [
        "Je m'arrête ici",
        "Dis-moi si tu veux continuer",
        "N'hésitez pas si vous souhaitez",
        "J'espère que cela vous sera utile",
    ]

    lines = []
    for line in text.splitlines():
        if any(f.lower() in line.lower() for f in forbidden):
            continue
        lines.append(line)

    text = "\n".join(lines).strip()

    if len(text) <= limit:
        return text

    # Enlever d'abord les sections souvent longues.
    cut_markers = [
        "Prolongement possible",
        "Prolongement :",
        "Remarque :",
        "Variante :",
    ]

    shortened = text
    for marker in cut_markers:
        idx = shortened.lower().find(marker.lower())
        if idx != -1:
            shortened = shortened[:idx].strip()
            if len(shortened) <= limit:
                return shortened

    # Dernier recours : couper proprement à une limite sûre.
    shortened = text[:limit - 40].rstrip()
    last_break = max(shortened.rfind("\n"), shortened.rfind(". "), shortened.rfind("; "))
    if last_break > 500:
        shortened = shortened[:last_break + 1].strip()

    return shortened


def mentions_user_document_without_content(text):
    t = normalize_for_match(text or "")
    compact = " ".join(t.split())

    document_markers = [
        "FICHIER", "DOCUMENT", "PHOTO", "IMAGE", "PDF",
        "SUJET ENVOYE", "PIECE JOINTE", "CAPTURE",
    ]
    exercise_refs = [
        "EXERCICE 1", "EXERCICE 2", "EXERCICE 3", "EXERCICE 4", "EXERCICE 5",
        "EXO 1", "EXO 2", "EXO 3", "EXO 4", "EXO 5",
        "CORRIGE CA", "TRAITE CA", "EXPLIQUE CA",
    ]

    return any(m in compact for m in document_markers + exercise_refs)


def answer_learning_request(phone, profile, text, media_file=None, message_id=None, reply_audio=False,
                            document_context=None):
    profile = mark_first_learning_request(phone, profile)
    user_profiles[phone] = profile
    """Envoie une vraie demande à Akili avec le profil final."""
    type_examen = infer_type_examen(profile.get("serie", "TOUTES"), text)
    mode = profile.get("mode") or infer_mode(text)

    profile["type_examen"] = type_examen
    profile["mode"] = mode
    user_profiles[phone] = profile

    matiere = profile.get("matiere", "MATHS")
    serie = profile.get("serie", "TOUTES")
    conversation_key = f"{phone}:{type_examen}:{serie}:{matiere}:{mode}"

    stored_active_session = None
    prepared_active_session = None
    if p0_enabled():
        stored_active_session = load_active_session(phone)
        prepared_active_session, duplicate = prepare_active_session(
            stored_active_session, profile, message_id, phone=phone
        )
        if duplicate:
            print(f"P0: message déjà traité durablement: {message_id}", flush=True)
            return None

    print(f"Profil WhatsApp: {profile}", flush=True)
    print(f"Conversation key: {conversation_key}", flush=True)

    if not conversations[conversation_key]:
        hist_sauve = charger_historique_conv(conversation_key)
        if hist_sauve:
            conversations[conversation_key] = hist_sauve
            print(f"HISTORIQUE recharge depuis Firestore: {len(hist_sauve)} messages", flush=True)

    if message_id:
        send_whatsapp_typing_indicator(message_id)

    if media_file is None and mentions_user_document_without_content(text):
        active_document = (prepared_active_session or {}).get("document")
        if active_document and active_document.get("gcs_uri"):
            try:
                media_file = restore_document_media(active_document)
                print("P0: document restauré depuis GCS", flush=True)
            except Exception as exc:
                print(f"P0: restauration GCS impossible: {exc!r}", flush=True)
        last_media = profile.get("last_document_media_file")
        if media_file is None and last_media and Path(last_media).exists():
            media_file = last_media
            print(f"DOCUMENT_CONTEXT reused last media file: {last_media}", flush=True)

    if mentions_user_document_without_content(text) and media_file is None and not profile.get("last_document_text"):
        send_whatsapp(
            phone,
            "Je n'arrive pas à lire clairement le contenu du fichier. Peux-tu envoyer une image plus nette ou recopier l'énoncé ?"
        )
        return

    try:
        akili_result = get_akili_response(
            text,
            matiere,
            serie,
            conversations[conversation_key],
            phone,
            type_examen,
            mode,
            media_file=media_file,
            user_type=profile.get("user_type"),
            active_session=prepared_active_session if p0_enabled() else None,
            raise_on_error=p0_enabled(),
            return_details=p0_enabled(),
        )
        if p0_enabled():
            reponse, transition_details = normalize_p0_response(akili_result)
            if document_context:
                transition_details["document"] = persist_document_media(
                    media_file, phone, document_context
                )
        else:
            reponse = akili_result
            transition_details = None
    except Exception as exc:
        print(f"P0: état inchangé après échec Akili: {exc!r}", flush=True)
        send_whatsapp(phone, "Désolé, je rencontre une petite difficulté technique, réessaie dans un instant.")
        return None

    if media_file:
        profile["last_document_media_file"] = str(media_file)
        profile["last_document_text"] = profile.get("last_document_text") or "__MEDIA_AVAILABLE__"
        user_profiles[phone] = profile

    reponse = soften_exercise_number_references(reponse)

    if p0_enabled():
        expected_revision = int((stored_active_session or {}).get("revision", 0))
        next_active_session = transition_after_success(
            prepared_active_session,
            text,
            reponse,
            message_id,
            **transition_details,
        )
        if not save_active_session_if_revision(phone, next_active_session, expected_revision):
            print(f"P0: conflit de révision pour {phone}, réponse non renvoyée", flush=True)
            return None

    conversations[conversation_key].append({"role": "user", "content": text})
    conversations[conversation_key].append({"role": "assistant", "content": reponse})
    conversations[conversation_key] = conversations[conversation_key][-10:]
    sauver_historique_conv(conversation_key, conversations[conversation_key])

    is_teacher = profile.get("user_type") == "ENSEIGNANT"
    send_limit = 1200 if is_teacher else 850
    if is_teacher and (matiere or "").upper().strip() == "ESPAGNOL":
        print("TEACHER_SPANISH_POSTPROCESS active", flush=True)
        is_apc_response = any(k in (reponse or "").upper() for k in [
            "TITRE DE LA LEÇON",
            "TITRE DE LA LECON",
            "SITUATION D'APPRENTISSAGE",
            "FONCTION LANGAGIERE",
            "FONCTION LANGAGIÈRE",
            "PRODUCTION ATTENDUE",
        ])
        limit = 1000 if is_apc_response else 900
        reponse = clean_teacher_spanish_activity(reponse)
        reponse = enforce_teacher_whatsapp_limit(reponse, limit=limit)
    elif is_teacher:
        reponse = enforce_teacher_whatsapp_limit(reponse, limit=900)

    send_whatsapp(phone, reponse, limit=send_limit, add_continuation=not is_teacher)
    send_vector_formula_if_needed(phone, text + "\n" + reponse)

    print(f"WHATSAPP_AUDIO_REPLY reply_audio={reply_audio}", flush=True)

    return reponse




def normalize_onboarding_state(profile):
    """Corrige les états incohérents de l'onboarding."""
    profile = profile or {}

    if profile.get("matiere_confirmed") and profile.get("onboarding_step") == "matiere":
        if profile.get("mode"):
            profile["onboarding_step"] = ""
        else:
            profile["onboarding_step"] = "mode"

    if profile.get("profile_ready"):
        profile["onboarding_step"] = ""

    return profile


def is_profile_ready(profile):
    """Le profil est prêt seulement si l'onboarding est terminé explicitement."""
    profile = profile or {}
    if profile.get("onboarding_step"):
        return False
    return bool(
        profile.get("profile_ready")
        and profile.get("type_examen")
        and profile.get("matiere")
        and profile.get("mode")
        and profile.get("ville")
        and profile.get("serie")
        and profile.get("serie") != "TOUTES"
    )


def mark_profile_ready_if_complete(profile):
    """Marque le profil prêt quand les choix obligatoires sont présents."""
    profile = profile or {}
    if (
        not profile.get("onboarding_step")
        and profile.get("type_examen")
        and profile.get("matiere")
        and profile.get("mode")
        and profile.get("ville")
        and profile.get("serie")
        and profile.get("serie") != "TOUTES"
    ):
        profile["profile_ready"] = True
    return profile


def is_explicit_profile_change_request(message):
    """Retourne True seulement si l'utilisateur demande clairement de changer son profil."""
    msg = normalize_for_match(message)
    if msg in {"RESET", "REINITIALISER", "REINITIALISER PROFIL"}:
        return True

    change_words = ["CHANGER", "MODIFIER", "RECOMMENCER", "REINITIALISER"]
    profile_words = ["PROFIL", "NIVEAU", "EXAMEN", "SERIE", "MATIERE", "CLASSE"]

    return any(has_expr(msg, c) for c in change_words) and any(has_expr(msg, p) for p in profile_words)


def is_profile_locked(profile):
    """Un profil prêt ne doit plus changer automatiquement pendant l'échange."""
    if not profile:
        return False

    if profile.get("profile_locked"):
        return True

    if profile.get("matiere_confirmed"):
        return True

    return (
        not profile.get("onboarding_step")
        and bool(profile.get("type_examen"))
        and bool(profile.get("serie"))
        and profile.get("serie") != "TOUTES"
        and bool(profile.get("matiere"))
    )


def lock_profile_if_ready(profile):
    if is_profile_ready(profile):
        profile["profile_locked"] = True
        profile["onboarding_step"] = ""
    return profile

def update_profile_from_text(profile, message):
    msg = normalize_for_match(message)

    if is_teacher_request(message):
        profile["user_type"] = "ENSEIGNANT"

    locked = is_profile_locked(profile) and not is_explicit_profile_change_request(message)
    locked_serie = profile.get("serie")
    locked_type_examen = profile.get("type_examen")
    locked_matiere = profile.get("matiere")
    locked_onboarding_step = profile.get("onboarding_step", "")

    intermediate_match = re.search(r"(?<![A-Z0-9])(6|5|4)\s*(?:E|EME)(?![A-Z0-9])", msg)
    if intermediate_match:
        profile["serie"] = f"{intermediate_match.group(1)}E"
        profile["type_examen"] = "CLASSE_INTERMEDIAIRE"

    if any(has_expr(msg, x) for x in ["BEPC", "3E", "3EME", "TROISIEME"]):
        profile["serie"] = "BEPC"
        profile["type_examen"] = "BEPC"

    # Detecte les niveaux du BAC General.
    for serie in ["A1", "A2", "C", "D", "E", "A"]:
        patterns = [
            f"SERIE {serie}", f"TERMINALE {serie}", f"TERMINAL {serie}",
            f"TLE {serie}", f"1ERE {serie}", f"PREMIERE {serie}",
            f"SECONDE {serie}", f"2NDE {serie}",
        ]
        if any(has_expr(msg, pat) for pat in patterns):
            profile["serie"] = serie
            break

    # Detecte les series techniques avant les matieres.
    for serie in ["G1", "G2", "F1", "F2", "F3", "F4", "B"]:
        patterns = [
            f"SERIE {serie}", f"TERMINALE {serie}", f"TERMINAL {serie}",
            f"TLE {serie}", f"BAC {serie}",
        ]
        if any(has_expr(msg, pat) for pat in patterns):
            profile["serie"] = serie
            break

    matiere_patterns = [
        ("MATHS", ["MATH", "MATHS", "MATHEMATIQUES"]),
        ("PHILO", ["PHILO", "PHILOSOPHIE"]),
        ("PC", ["PC", "PHYSIQUE", "CHIMIE", "PHYSIQUE CHIMIE", "PHYSIQUE CHIMIE"]),
        ("SVT", ["SVT", "SCIENCES DE LA VIE ET DE LA TERRE"]),
        ("HG", ["HG", "HISTOIRE", "GEOGRAPHIE", "HISTOIRE GEOGRAPHIE"]),
        ("ANGLAIS", ["ANGLAIS"]),
        ("ALLEMAND", ["ALLEMAND", "ALLEMANDE", "ALL", "GERMAN"]),
        ("ESPAGNOL", ["ESPAGNOL", "ESPAGNOLE", "ESP", "ESPANOL", "SPANISH"]),
        ("FRANCAIS", ["FRANCAIS", "FRANCAISE", "FRANÇAISE", "FRENCH"]),
        ("COMPTA", ["COMPTABILITE", "COMPTA"]),
        ("ECO", ["ECONOMIE", "ECO"]),
        ("DROIT", ["DROIT"]),
        ("ETUDE-CAS", ["ETUDE DE CAS", "ETUDE CAS"]),
        ("TQG", ["TQG"]),
        ("OC", ["ORGANISATION COMMERCIALE", "OC"]),
        ("ESTI", ["ESTI"]),
    ]

    for value, patterns in matiere_patterns:
        if any(has_expr(msg, pat) for pat in patterns):
            profile["matiere"] = value
            break

    if locked:
        if locked_serie:
            profile["serie"] = locked_serie
        if locked_type_examen:
            profile["type_examen"] = locked_type_examen
        if locked_matiere:
            profile["matiere"] = locked_matiere
        profile["profile_locked"] = True
        profile["onboarding_step"] = locked_onboarding_step or ""

    return profile


def infer_type_examen(serie, message):
    msg = (message or "").upper()
    serie = (serie or "").upper().strip()

    if serie in {"6E", "5E", "4E"} or re.search(
        r"(?<![A-Z0-9])(6|5|4)\s*(?:E|ÈME|EME)(?![A-Z0-9])", msg
    ):
        return "CLASSE_INTERMEDIAIRE"

    if serie == "BEPC" or "BEPC" in msg or "3EME" in msg or "3ÈME" in msg or "TROISIEME" in msg or "TROISIÈME" in msg:
        return "BEPC"

    if serie in {"B", "G1", "G2", "F1", "F2", "F3", "F4", "STI"}:
        return "BAC_TECHNIQUE"

    if any(x in msg for x in ["BAC TECH", "BAC TECHNIQUE", "TECHNIQUE", "TERMINALE G", "TERMINALE B"]):
        return "BAC_TECHNIQUE"

    return "BAC_GENERAL"


def infer_mode(message):
    msg = (message or "").upper()
    # NE garder que les intentions EXPLICITES d'examen. Les mots d'etude
    # normaux (exercice, sujet, corrige...) NE doivent PAS basculer en examen.
    examen_keywords = [
        "MODE EXAMEN", "MODE-EXAMEN", "NOTE-MOI", "NOTE MOI",
        "BAREME", "BARÈME", "EN CONDITIONS D'EXAMEN", "CONDITIONS D EXAMEN"
    ]

    if any(k in msg for k in examen_keywords):
        return "examen"

    return "etude"


def read_local_text_file(path, max_chars=6000):
    try:
        text = Path(path).read_text(encoding="utf-8")
        return text[:max_chars].strip()
    except Exception as e:
        print(f"Erreur lecture fichier local {path}: {repr(e)}", flush=True)
        return ""


def get_subject_guidelines(matiere):
    subject = (matiere or "").upper()

    paths_by_subject = {
        "HG": [
            Path("resources/histoire-geographie/synthese/histoire_geographie_prompt_guidelines.md"),
            Path("../resources/histoire-geographie/synthese/histoire_geographie_prompt_guidelines.md"),
        ],
        "PHILO": [
            Path("resources/philosophie/synthese/philosophie_prompt_guidelines.md"),
            Path("../resources/philosophie/synthese/philosophie_prompt_guidelines.md"),
        ],
        "ESPAGNOL": [
            Path("resources/espagnol/synthese/espagnol_prompt_guidelines.md"),
            Path("../resources/espagnol/synthese/espagnol_prompt_guidelines.md"),
        ],
        "ANGLAIS": [
            Path("resources/anglais/synthese/anglais_prompt_guidelines.md"),
            Path("../resources/anglais/synthese/anglais_prompt_guidelines.md"),
        ],
        "FRANCAIS": [
            Path("resources/francais/synthese/francais_prompt_guidelines.md"),
            Path("../resources/francais/synthese/francais_prompt_guidelines.md"),
        ],
        "FRENCH": [
            Path("resources/francais/synthese/francais_prompt_guidelines.md"),
            Path("../resources/francais/synthese/francais_prompt_guidelines.md"),
        ],
    }

    for path in paths_by_subject.get(subject, []):
        try:
            if path.exists():
                return path.read_text(encoding="utf-8")[:6000]
        except Exception as e:
            print(f"Erreur lecture fichier local {path}: {repr(e)}", flush=True)

    return ""


def filter_subject_guidelines_for_user(subject_guidelines, matiere, user_type=""):
    subject = (matiere or "").upper().strip()
    profile_type = (user_type or "").upper().strip()

    if not subject_guidelines:
        return ""

    if subject not in {"ESPAGNOL", "ANGLAIS"} or profile_type == "ENSEIGNANT":
        return subject_guidelines

    cleaned = subject_guidelines

    cut_markers = [
        "\n## Profil enseignant",
        "\n## Situation d'évaluation",
        "\n## Ton",
    ]

    positions = [cleaned.find(m) for m in cut_markers if cleaned.find(m) != -1]
    if positions:
        cleaned = cleaned[:min(positions)].rstrip()

    return (
        cleaned.rstrip()
        + "\n\n## Règles spécifiques élève "
        + subject.title()
        + "\n\n"
        + "- Ne donne pas de fiche enseignant.\n"
        + "- Ne donne pas le corrigé indicatif avant la réponse de l'élève.\n"
        + "- Propose 1 à 3 questions ou items maximum.\n"
        + "- Termine par une consigne courte demandant à l'élève de répondre.\n"
    )

FILLER_OPENING_KEYWORDS = [
    "EXCELLENTE IDEE", "EXCELLENTE QUESTION", "EXCELLENTE INITIATIVE", "EXCELLENTE FACON",
    "BONNE IDEE", "BONNE QUESTION", "BONNE INITIATIVE", "TRES BONNE IDEE", "TRES BONNE QUESTION",
    "JE COMPRENDS QUE TU", "JE VOIS QUE TU", "C EST UNE EXCELLENTE", "C EST UNE BONNE",
    "C EST UNE TRES BONNE", "QUELLE BONNE IDEE", "QUELLE EXCELLENTE",
    "TRES BIEN", "TRES BON", "C EST PARTI", "ALLONS Y",
]

FILLER_GREETING_WORDS = {
    "BONJOUR", "BONSOIR", "SALUT", "HELLO", "HI", "COUCOU",
    "EXCELLENT", "EXCELLENTE", "PARFAIT", "PARFAITE", "GENIAL", "GENIALE",
    "SUPER", "BRAVO", "TOP", "NICKEL",
}


def strip_filler_opening(text):
    """Supprime les phrases d'accroche/compliment en debut de reponse (garde-fou code, en plus du prompt)."""
    text = str(text or "").strip()
    if not text:
        return text

    sentences = re.split(r'(?<=[.!?])\s+', text)

    while sentences:
        first = sentences[0].strip()
        if not first:
            sentences.pop(0)
            continue

        first_norm = normalize_for_match(first)
        words = first_norm.split()

        is_bare_greeting = bool(words) and words[0] in FILLER_GREETING_WORDS and len(words) <= 4
        is_filler_sentence = any(kw in first_norm for kw in FILLER_OPENING_KEYWORDS)

        if is_bare_greeting or is_filler_sentence:
            sentences.pop(0)
            continue

        break

    if not sentences:
        return text

    result = " ".join(s.strip() for s in sentences if s.strip()).strip()
    return result if result else text


def get_akili_response(question, matiere, serie, history, phone="whatsapp_user", type_examen=None,
                       mode=None, media_file=None, user_type=None, raise_on_error=False,
                       return_details=False, active_session=None):
    try:
        # Sécurité: si l'appelant oublie user_type, on redétecte ici.
        if not user_type and is_teacher_request(question):
            user_type = "ENSEIGNANT"

        # Pour un enseignant, "exercice" ne doit pas activer le mode examen élève.
        if (user_type or "").upper() == "ENSEIGNANT":
            mode = "etude"

        contexte = "\n".join([
            f"{'Élève' if m['role'] == 'user' else 'Akili'}: {m['content']}"
            for m in history[-6:]
        ])
        active_session_context = build_active_session_prompt(active_session)
        active_context_instruction = (
            "ETAT PEDAGOGIQUE ACTIF STRUCTURE (reprends exactement cette activité; "
            "ce JSON n'est pas un historique de conversation):\n"
            f"{active_session_context}\n\n"
            if active_session_context else ""
        )

        bepc_instruction = ""
        if (type_examen or "").upper() == "BEPC" or (serie or "").upper() == "BEPC":
            bepc_instruction = (
                "IMPORTANT BEPC/3EME: privilégie les choix a, b, c ou 1, 2, 3. "
                "L'élève doit pouvoir répondre avec une seule lettre ou un seul chiffre. "
                "Ne demande une justification courte qu'après son choix. "
            )

        subject_guidelines = get_subject_guidelines(matiere)
        subject_guidelines = filter_subject_guidelines_for_user(subject_guidelines, matiere, user_type)

        teacher_instruction = ""
        if (user_type or "").upper() == "ENSEIGNANT":
            teacher_instruction = (
                "\nCONTEXTE PROFIL ENSEIGNANT:\n"
                "- L'utilisateur est un enseignant, pas un élève.\n"
                "- Adresse-toi à lui comme à un professeur: utilisez 'vous', 'vos élèves', 'votre classe'.\n"
                "- Ne dis jamais 'tes élèves' ni 'tu peux répondre'.\n"
                "- Aide-le à préparer des cours, exercices, corrigés, évaluations, consignes et progressions.\n"
                "- Propose des supports directement utilisables en classe.\n"
                "- Pour un enseignant, préfère une fiche courte: objectif, support/extrait très court, consignes, questions, corrigé bref.\n"
                "- Ne recopie pas un long texte d'annale dans WhatsApp. Donne seulement un extrait court ou un résumé exploitable.\n"
                "- Si le niveau, la matière ou l'objectif manque, pose une question courte avant de détailler.\n"
            )

        instructions_whatsapp = (
            "CONTEXTE TECHNIQUE WHATSAPP:\n"
            "REGLE ABSOLUE (priorite sur tout le reste): ne commence JAMAIS ta reponse par une salutation suivie d'un compliment ou d'une reformulation de la demande de l'eleve. "
            "INTERDIT, exemples reels a ne jamais reproduire: 'Bonjour! Excellente initiative de vouloir t'exercer en EDHC pour le BEPC.' ou 'Salut! Je comprends que tu cherches une histoire en SVT. C'est une excellente facon de voir cette matiere!'. "
            "CORRECT: commence directement par le contenu utile (l'exercice, la question ou l'explication), sans aucune phrase d'introduction ni compliment.\n"
            "REGLE ABSOLUE (priorite sur tout le reste): si l'énoncé contient une formule avec une lettre inconnue en exposant ou en indice (par exemple x, y, z, n dans CxHyOz), tu DOIS toujours recopier cette formule exactement comme elle a été écrite, en texte normal, sans aucune mise en indice ni exposant, même dans tes propres reformulations de l'énoncé. INTERDIT, exemples réels à ne jamais reproduire: 'CₓHᵧO₂' ou 'C_xH_yO_z' pour parler de CxHyOz (le z a été remplacé par le chiffre 2, ce qui dénature complètement l'exercice). CORRECT: écris CxHyOz, exactement ainsi, en texte plat, chaque fois que tu mentionnes cette formule.\n"
            "- Réponds en français simple.\n"
            "- Réponse courte, adaptée à WhatsApp.\n"
            "- Maximum 750 caractères.\n"
            "- Ne transcris pas tout l'énoncé.\n"
            "- Ne donne pas un long corrigé d'annales.\n"
            "- Si une image/photo est floue, coupée, sombre ou illisible, n'invente jamais le contenu. Réponds poliment : Je n'arrive pas à lire clairement ton image. Peux-tu en reprendre une plus claire, bien éclairée, ou me recopier le texte de l'exercice ?\n"
            "- Ne jamais utiliser de syntaxe LaTeX, sous aucune forme: ni $, ni $$, ni aucune commande qui commence par un backslash suivi de lettres (comme \\frac, \\text, \\mathbb, \\rightarrow, \\sqrt, \\times, \\cdot, \\left, \\right, \\overline, \\underline, \\alpha, \\beta, ou toute autre commande de ce type, connue ou pas). Si le texte source (enonce, PDF, photo) contient ce genre de syntaxe, ne la recopie JAMAIS telle quelle dans ta reponse: convertis-la toujours en texte simple et lisible sur WhatsApp. Exemples de conversion: \\text N devient simplement N, \\frac{1}{2} devient 1/2, \\sqrt{x} devient racine carree de x, \\times devient x ou fois.\n"
            "- Ne jamais ecrire de commande LaTeX pour une lettre grecque (\\alpha, \\beta, \\gamma, \\delta). Ecris plutot le nom en toutes lettres (particule alpha, rayon beta) ou le symbole Unicode (α, β, γ, δ).\n"
            "- NUCLEIDE/ISOTOPE: n'essaie jamais de reproduire une notation empilee avec le nombre de masse et le numero atomique colles au symbole, comme dans un PDF mal extrait (exemple casse a ne jamais recopier: {}_88^226}Ra). Ecris toujours en texte lineaire clair: symbole-nombre de masse, puis la precision entre parentheses. Exemple correct: noyau de radium Ra-226 (numero atomique Z = 88, nombre de masse A = 226). Si le texte source contient des accolades ou des symboles brises pour cette notation, corrige-la silencieusement dans ce format lineaire au lieu de la recopier telle quelle.\n"
            "- Pour le gras, utilise UN SEUL asterisque de chaque cote (*mot*), jamais deux (**mot**) qui est un format Markdown non supporte par WhatsApp.\n"
            "- Pour une liste, n'utilise jamais de tirets (-) ni d'asterisques comme puces. Utilise plutot des numeros (1. 2. 3.) ou le caractere •.\n"
            "- Écris les formules en texte simple lisible sur WhatsApp.\n"
            "- Exemple: x -> F(x) + c, R, (x^2 - 3x + 2)/(x - 1).\n"
            "- VECTEURS: n'ecris jamais 'fleche au-dessus'. Mets la fleche APRES la ou les lettres: AB->, u->, v->, F1->. Le vecteur AB s'ecrit AB-> et le vecteur vitesse v s'ecrit v->.\n"
            "- INDICES: utilise les petits chiffres Unicode: F1 s'ecrit F(indice 1) sous la forme F\u2081, v0 sous la forme v\u2080, x1 sous la forme x\u2081. Exemples: F\u2081->, v\u2080, x\u2099.\n"
            "- Si l'indice ou l'exposant est une lettre inconnue sans equivalent Unicode en petit caractere (comme y, z, n, a, b), n'utilise JAMAIS le format avec underscore (C_x, H_y, x_n). Ecris la lettre normale, directement collee, sans aucun symbole de separation: CxHyOz, xn, an. Ne melange jamais underscore et lettre normale dans une meme formule.\n"
            "- Norme d'un vecteur: ||AB->|| ou norme de AB->.\n"
            "- Si l'élève est en BEPC/3ème, privilégie les choix a, b, c.\n"
            "- Si l'exercice est un QCM, un texte à trous avec une liste de mots/propositions, ou un exercice d'association, tu DOIS toujours recopier la liste complète des choix ou propositions, mot pour mot. N'écris JAMAIS une formulation comme 'un mot de la liste convient' sans donner cette liste : l'élève ne peut pas répondre sans elle.\n"
            "- Ne modifie JAMAIS un symbole, une variable, un exposant ou un indice inconnu donné par l'élève dans l'énoncé (par exemple x, y, z, n dans une formule comme CxHyOz, ou tout coefficient littéral). Recopie-le exactement tel quel, y compris dans tes propres reformulations de l'énoncé. N'invente jamais une valeur numérique à la place d'une lettre inconnue, même s'il existe un exemple courant avec cette valeur.\n"
            "- Guide l'élève étape par étape.\n"
            "- Ne donne qu'une seule étape à la fois.\n"
            "- Termine toujours par une question courte à l'élève.\n"
            "- Ne commence jamais par une phrase d'accroche du type \'Salut, je comprends que tu cherches...\'. Va directement au contenu utile.\n"
            "- Ne récite pas la présentation générale du programme de la matière si la matière, la série et le mode sont déjà connus. Propose directement un exercice ou une explication concrète, sans demander à l'élève de choisir un sous-thème lui-même.\n"
            "- Ne répète pas un contexte ou une information déjà donnée dans les messages précédents de cette conversation.\n"
            "- En Espagnol, si tu poses une question de compréhension de texte, donne d'abord le court texte ou un extrait suffisant. Ne demande jamais à l'élève de lire un texte que tu n'as pas affiché dans WhatsApp. Si le texte est trop long, donne un résumé clair avant la question.\n"
            "- En Espagnol pour un enseignant, ne donne pas tout le texte support. Prépare une activité courte avec extrait de 2 phrases maximum, 3 questions maximum et corrigé indicatif.\n"
            "- Pour un enseignant, ne termine pas par 'je m'arrête ici'. La réponse doit tenir en un seul message court.\n"
            "- Pour un enseignant, limite stricte: maximum 850 caractères. Si nécessaire, retire le prolongement ou raccourcis le corrigé.\n"
            + teacher_instruction
            + (f"\nGUIDELINES MATIERE:\n{subject_guidelines}\n" if subject_guidelines else "")
        )

        format_guard = ""
        if (user_type or "").upper() == "ENSEIGNANT" and (matiere or "").upper() == "ESPAGNOL":
            q_up = (question or "").upper()
            is_apc_request = any(k in q_up for k in ["APC", "SEANCE", "SÉANCE", "LECON", "LEÇON", "FONCTION LANGAGIERE", "FONCTION LANGAGIÈRE"])

            if is_apc_request:
                format_guard = (
                    "FORMAT OBLIGATOIRE POUR CETTE REPONSE APC:\n"
                    "- Réponds avec les rubriques exactes: Titre de la leçon, Niveau, Compétence ou fonction langagière, Situation d'apprentissage, Activité ou tâche, Consignes, Production attendue.\n"
                    "- La situation d'apprentissage doit être concrète, proche de la classe, et faire utiliser la langue.\n"
                    "- Maximum 900 caractères. Pas d'introduction longue. Pas de conclusion longue.\n\n"
                )
            else:
                format_guard = (
                    "FORMAT OBLIGATOIRE POUR CETTE REPONSE:\n"
                    "- Réponds avec les rubriques exactes: Titre, Objectif, Situation ou support, Exercice, Corrigé indicatif.\n"
                    "- L'exercice doit être un vrai format de classe: QCM, texte à trous, association colonne A/B, ou production orale/écrite.\n"
                    "- Pour salutations/présentation, privilégie production orale/écrite et association colonne A/B.\n"
                    "- Maximum 850 caractères. Pas d'introduction longue. Pas de conclusion longue.\n\n"
                )

        if contexte and media_file:
            question_api = (
                f"{instructions_whatsapp}\n"
                f"{format_guard}"
                f"{active_context_instruction}"
                f"NOUVEAU DOCUMENT RECU AVEC CE MESSAGE: l'eleve vient de joindre un nouveau fichier ou une nouvelle photo. "
                f"Ce nouveau document contient l'exercice ACTUEL a traiter en priorite absolue, meme s'il ne correspond pas au sujet de l'historique ci-dessous. "
                f"Ne continue PAS l'ancien exercice de l'historique si le nouveau document presente un exercice different: lis le nouveau document et pars de son contenu.\n"
                f"HISTORIQUE RECENT (ancien contexte, informatif seulement, ne sert plus a identifier l'exercice actuel):\n{contexte}\n\n"
                f"QUESTION REELLE DE L'ELEVE:\n{question}"
            )
        elif contexte:
            question_api = (
                f"{instructions_whatsapp}\n"
                f"{format_guard}"
                f"{active_context_instruction}"
                f"HISTORIQUE RECENT:\n{contexte}\n\n"
                f"QUESTION REELLE DE L'ELEVE:\n{question}"
            )
        else:
            question_api = (
                f"{instructions_whatsapp}\n"
                f"{format_guard}"
                f"{active_context_instruction}"
                f"QUESTION REELLE DE L'ELEVE:\n{question}"
            )

        payload = {
            "email": f"{phone}@afrjigi.com",
            "question": question_api,
            "question_brute": question,
            "matiere": matiere,
            "serie": serie,
            "type_examen": type_examen,
            "mode": mode,
            "history": contexte,
            "user_type": user_type or "",
        }


        print(f"AKILI_API payload: {payload}", flush=True)
        request_files = {k: (None, str(v)) for k, v in payload.items() if v is not None}

        opened_file = None
        try:
            if media_file is not None:
                media_path = Path(media_file)
                mime_type = "application/octet-stream"
                suffix = media_path.suffix.lower()

                if suffix in {".jpg", ".jpeg"}:
                    mime_type = "image/jpeg"
                elif suffix == ".png":
                    mime_type = "image/png"
                elif suffix == ".pdf":
                    mime_type = "application/pdf"
                elif suffix in {".ogg", ".opus"}:
                    mime_type = "audio/ogg"
                elif suffix == ".mp3":
                    mime_type = "audio/mpeg"

                opened_file = media_path.open("rb")
                request_files["file"] = (media_path.name, opened_file, mime_type)
                print(f"AKILI_API media upload path={media_path} mime={mime_type}", flush=True)

            res = requests.post(AKILI_API_URL, files=request_files, timeout=90)
        finally:
            if opened_file:
                opened_file.close()
        print(f"AKILI_API status: {res.status_code}", flush=True)
        print(f"AKILI_API body: {res.text}", flush=True)

        if raise_on_error:
            res.raise_for_status()

        data = res.json()
        reponse_text = (
            data.get("reponse")
            or data.get("response")
            or data.get("answer")
            or data.get("message")
        )
        if not reponse_text:
            if raise_on_error:
                raise ValueError("Réponse Akili vide")
            reponse_text = "Désolé, je n'ai pas pu répondre."
        reponse_text = strip_filler_opening(reponse_text)
        if return_details:
            return {
                "text": reponse_text,
                "document": data.get("document"),
                "exercise": data.get("exercise"),
                "current_question": data.get("current_question"),
                "structured_results": data.get("relevant_previous_results") or [],
                "next_expected_action": data.get("next_expected_action") or "await_student_answer",
            }
        return reponse_text

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


@app.post("/whatsapp/webhook")
async def receive_message(request: Request):
    body = await request.json()

    try:
        messages = body["entry"][0]["changes"][0]["value"].get("messages", [])
        if not messages:
            return {"status": "ok"}

        msg = messages[0]
        phone = msg["from"]
        msg_type = msg.get("type")
        text = msg.get("text", {}).get("body", "").strip()
        media_file = None
        document_context = None
        incoming_was_audio = msg_type in {"audio", "voice"}
        audio_reply_context[phone] = incoming_was_audio
        print(f"WHATSAPP_AUDIO_REPLY incoming_was_audio={incoming_was_audio} msg_type={msg_type}", flush=True)

        if msg_type in {"document", "image", "audio", "voice"}:
            media_key = "audio" if msg_type == "voice" else msg_type
            media = msg.get(media_key, {})
            media_id = media.get("id")
            caption = (media.get("caption") or "").strip()
            filename = media.get("filename") or f"whatsapp_{msg_type}"
            fallback_mime = media.get("mime_type") or (
                "audio/ogg" if msg_type == "audio" else
                "image/jpeg" if msg_type == "image" else
                "application/pdf"
            )

            if media_id:
                if msg_type in {"document", "image"}:
                    document_context = {
                        "id": None,
                        "ref": None,
                        "gcs_uri": None,
                        "media_id": media_id,
                        "mime_type": fallback_mime,
                        "sha256": None,
                    }
                downloaded = download_whatsapp_media(media_id, filename, fallback_mime)

                if msg_type in {"audio", "voice"}:
                    text = transcribe_whatsapp_audio(downloaded)
                    if not text:
                        send_whatsapp(
                            phone,
                            "Je n'ai pas bien entendu ton audio. Peux-tu le renvoyer plus clairement ou écrire ta question ?"
                        )
                        return {"status": "ok", "reason": "audio_transcription_failed"}
                    print(f"WHATSAPP_AUDIO transcription: {text}", flush=True)
                else:
                    text = caption or "Analyse ce sujet envoyé en fichier et guide-moi pas à pas."
                    media_file = downloaded

        message_id = msg.get("id")

        if message_id in processed_messages:
            print(f"Message déjà traité: {message_id}", flush=True)
            return {"status": "ok"}

        if message_id:
            processed_messages.add(message_id)
            send_whatsapp_typing_indicator(message_id)

        if len(processed_messages) > 1000:
            processed_messages.clear()

        if not text:
            return {"status": "ok"}

        print(f"Message de {phone}: {text}", flush=True)

        profile = user_profiles[phone] or charger_etat_whatsapp(phone) or {"serie": "TOUTES", "matiere": "MATHS"}
        user_profiles[phone] = profile

        clean_text, acquisition_source, creative = extract_acquisition_tracking(text)
        if acquisition_source:
            profile["acquisition_source"] = acquisition_source
            profile["campaign"] = DEFAULT_CAMPAIGN
            if creative:
                profile["creative"] = creative
            text = clean_text or "Bonjour Akili"
            user_profiles[phone] = profile
            print(f"WHATSAPP_ACQUISITION source={acquisition_source} creative={creative} phone={phone}", flush=True)
        else:
            profile.setdefault("acquisition_source", profile.get("acquisition_source") or "ORGANIC")
            profile.setdefault("campaign", DEFAULT_CAMPAIGN)

        profile_before = dict(profile)

        def track_inbound(stage, profile_after=None):
            after = dict(profile_after or user_profiles.get(phone, profile) or {})
            save_whatsapp_event(
                phone,
                "inbound",
                text,
                after,
                message_id,
                extra={
                    "processing_stage": stage,
                    "serie_before": profile_before.get("serie", ""),
                    "matiere_before": profile_before.get("matiere", ""),
                    "type_examen_before": profile_before.get("type_examen", ""),
                    "mode_before": profile_before.get("mode", ""),
                    "onboarding_step_before": profile_before.get("onboarding_step", ""),
                    "serie_after": after.get("serie", ""),
                    "matiere_after": after.get("matiere", ""),
                    "type_examen_after": after.get("type_examen", ""),
                    "mode_after": after.get("mode", ""),
                    "onboarding_step_after": after.get("onboarding_step", ""),
                    "acquisition_source": after.get("acquisition_source", ""),
                    "campaign": after.get("campaign", ""),
                    "creative": after.get("creative", ""),
                    "ville": after.get("ville", ""),
                    "nom_ecole": after.get("nom_ecole", ""),
                    "onboarding_completed_at": after.get("onboarding_completed_at", ""),
                    "first_learning_request_at": after.get("first_learning_request_at", ""),
                },
            )

        original_text = text
        command = text.strip().lower()
        onboarding_step = profile.get("onboarding_step")
        print(f"SHORT_DEBUG text={text} is_short={is_short_exercise_answer(text)} is_contextual={is_contextual_exercise_answer(text)} onboarding={onboarding_step}", flush=True)
        if is_contextual_exercise_answer(text) and not profile.get("onboarding_step"):
            if not short_answer_has_exercise_context(phone):
                send_whatsapp(
                    phone,
                    "Je veux être sûr de répondre sur le bon exercice. Renvoie-moi la question ou une photo, et je continue avec toi."
                )
                track_inbound("contextual_answer_without_context", profile)
                print("SHORT_ANSWER_CONTEXT_EARLY without_context", flush=True)
                return {"status": "ok", "reason": "contextual_answer_without_context"}

            text = build_short_answer_prompt(phone, text)
            print("SHORT_ANSWER_CONTEXT_EARLY enforced", flush=True)

        if command.startswith("reset\n") or command.startswith("reset\r"):
            user_profiles.pop(phone, None)
            effacer_etat_whatsapp(phone)
            conversations_to_delete = [k for k in conversations if k.startswith(f"{phone}:")]
            for k in conversations_to_delete:
                conversations.pop(k, None)
            if p0_enabled():
                delete_active_session(phone)
            send_whatsapp(
                phone,
                "Profil réinitialisé. Envoie les choix un par un. Exemple : Bonjour Akili"
            )
            track_inbound("reset_multiline", {})
            return {"status": "ok"}

        if command.startswith("feedback:") or command.startswith("retour:"):
            profile = user_profiles.get(phone, {})
            feedback_text = text.split(":", 1)[1].strip()
            ok = save_feedback_whatsapp(phone, feedback_text, profile, text)
            if ok:
                send_whatsapp(phone, "Merci. Ton retour a été enregistré et nous aide à améliorer Akili.")
                track_inbound("feedback_saved", profile)
            else:
                send_whatsapp(phone, "Merci pour ton retour. Je n'ai pas pu l'enregistrer automatiquement, mais il sera pris en compte.")
            return {"status": "ok"}

        welcome_commands = {"bonjour", "bonsoir", "salut", "hello", "hi", "aide", "start"}
        if command in welcome_commands or command in {f"{c} akili" for c in welcome_commands}:
            profile = user_profiles[phone] or {"serie": "TOUTES", "matiere": "MATHS"}
            profile["onboarding_step"] = "exam"
            user_profiles[phone] = profile
            ask_exam(phone)
            track_inbound("welcome_onboarding_started", profile)
            return {"status": "ok"}

        if command in {"menu", "menu akili"}:
            profile = user_profiles[phone] or {"serie": "TOUTES", "matiere": "MATHS"}
            profil_complet = (
                profile.get("type_examen")
                and profile.get("serie") not in {"TOUTES", "", None}
                and profile.get("matiere")
            )
            if profil_complet:
                profile["onboarding_step"] = "menu_choice"
                user_profiles[phone] = profile
                sauver_etat_whatsapp(phone, profile)
                send_whatsapp(phone,
                    "Que veux-tu faire ?\n\n"
                    "a. Changer de matiere (garder le meme niveau)\n"
                    "b. Changer de niveau, serie ou examen\n\n"
                    "Reponds par a ou b."
                )
                track_inbound("menu_opened", profile)
                return {"status": "ok"}
            profile["onboarding_step"] = "exam"
            user_profiles[phone] = profile
            ask_exam(phone)
            track_inbound("welcome_onboarding_started", profile)
            return {"status": "ok"}

        if command in {"changer matière", "changer matiere", "changer de matière", "changer de matiere"}:
            profile = user_profiles[phone] or {"serie": "TOUTES", "matiere": "MATHS"}
            profile.pop("pending_question", None)
            if profile.get("type_examen") and profile.get("serie") not in {"TOUTES", "", None}:
                profile["onboarding_step"] = "matiere"
                profile.pop("profile_locked", None)
                profile.pop("matiere_confirmed", None)
                user_profiles[phone] = profile
                if profile.get("type_examen") == "BAC_TECHNIQUE":
                    ask_matiere_technique(phone, profile.get("serie"))
                else:
                    ask_matiere(phone, profile.get("serie", "TOUTES"))
                track_inbound("matiere_change_requested", profile)
                return {"status": "ok"}
            profile["onboarding_step"] = "exam"
            profile.pop("profile_locked", None)
            profile.pop("matiere_confirmed", None)
            user_profiles[phone] = profile
            ask_exam(phone)
            track_inbound("profile_change_requested", profile)
            return {"status": "ok"}

        if command in {"changer profil", "changer de profil", "changer niveau", "changer examen"}:
            profile = user_profiles[phone] or {"serie": "TOUTES", "matiere": "MATHS"}
            profile["onboarding_step"] = "exam"
            profile.pop("profile_locked", None)
            profile.pop("matiere_confirmed", None)
            profile.pop("pending_question", None)
            user_profiles[phone] = profile
            ask_exam(phone)
            track_inbound("profile_change_requested", profile)
            return {"status": "ok"}

        if command in {"reset", "réinitialiser", "reinitialiser"}:
            user_profiles.pop(phone, None)
            effacer_etat_whatsapp(phone)
            conversations_to_delete = [k for k in conversations if k.startswith(f"{phone}:")]
            for k in conversations_to_delete:
                conversations.pop(k, None)
            if p0_enabled():
                delete_active_session(phone)
            send_whatsapp(phone, "Profil réinitialisé. Dis-moi ton examen, ta série et ta matière. Exemple : Je suis en Terminale D, je veux travailler les Maths.")
            track_inbound("reset", {})
            return {"status": "ok"}

        profile = user_profiles[phone] or {"serie": "TOUTES", "matiere": "MATHS"}

        if is_teacher_request(text):
            profile = update_profile_from_text(profile, text)
            profile["user_type"] = "ENSEIGNANT"

            detected_matiere = detect_matiere_from_text(text)
            if detected_matiere:
                profile["matiere"] = detected_matiere
                profile["matiere_confirmed"] = True

            profile["type_examen"] = infer_type_examen(profile.get("serie", "TOUTES"), text)
            profile["mode"] = profile.get("mode") or infer_mode(text)
            profile["profile_ready"] = True
            profile["profile_locked"] = True
            profile["onboarding_step"] = ""
            user_profiles[phone] = profile

            track_inbound("teacher_direct_request", profile)
            answer_learning_request(
                phone, profile, text, media_file=media_file, message_id=message_id,
                reply_audio=incoming_was_audio, document_context=document_context,
            )
            return {"status": "ok"}

        # Si une simple lettre arrive sans contexte, ne jamais l'envoyer à l'API.
        # Cela arrive quand Cloud Run perd l'état en mémoire ou change d'instance.
        if choice_key(text) and not profile.get("onboarding_step") and not is_profile_ready(profile):
            profile["onboarding_step"] = "exam"
            user_profiles[phone] = profile
            send_whatsapp(
                phone,
                "Je n'ai pas encore ton profil complet. Reprenons depuis le début."
            )
            ask_exam(phone)
            track_inbound("orphan_choice_restarted_onboarding", profile)
            return {"status": "ok"}

        if profile.get("onboarding_step") and is_multiple_choice_answer(text):
            send_whatsapp(phone, "Choisis une seule option pour continuer. Exemple : a")
            track_inbound("multiple_choice_rejected", profile)
            return {"status": "ok"}

        if command in {"profil", "profile"}:
            send_whatsapp(
                phone,
                f"Profil actuel : examen={profile.get('type_examen', 'BAC_GENERAL')}, série={profile.get('serie', 'TOUTES')}, matière={profile.get('matiere', 'MATHS')}, mode={profile.get('mode', 'etude')}."
            )
            track_inbound("profile_command", profile)
            return {"status": "ok"}
        if handle_onboarding_choice(phone, profile, text):
            profile_after_choice = user_profiles.get(phone, profile)
            track_inbound("onboarding_choice", profile_after_choice)

            profile_after_choice = mark_profile_ready_if_complete(profile_after_choice)

            if not profile_after_choice.get("onboarding_step") and profile_after_choice.get("pending_question"):
                pending_question = profile_after_choice.pop("pending_question")
                pending_question_display = profile_after_choice.pop("pending_question_display", pending_question)
                profile_after_choice = mark_profile_ready_if_complete(profile_after_choice)
                user_profiles[phone] = profile_after_choice
                send_whatsapp(phone, f"Je reprends ta question : {pending_question_display}")
                answer_learning_request(phone, profile_after_choice, pending_question)
                track_inbound("pending_question_answered", profile_after_choice)

            return {"status": "ok"}

        if is_learning_request(text) and not is_profile_ready(profile) and not is_teacher_request(text):
            profile["pending_question"] = text
            profile["pending_question_display"] = original_text
            profile["onboarding_step"] = "exam"
            user_profiles[phone] = profile
            send_whatsapp(
                phone,
                "Avant de répondre, précise ton profil pour que je t'aide correctement.\n\n"
                f"J'ai gardé ta question : {original_text}"
            )
            ask_exam(phone)
            track_inbound("forced_onboarding_pending_question", profile)
            return {"status": "ok"}

        profile = update_profile_from_text(profile, text)
        normalize_onboarding_state(profile)
        user_profiles[phone] = profile

        if profile.get("serie") == "AUTRE" or profile.get("type_examen") == "AUTRE":
            send_whatsapp(
                phone,
                "Akili accompagne les élèves du collège, du lycée, du BEPC, du BAC Général et du BAC Technique. "
                "Dis-moi clairement ton besoin : concours, matière et niveau."
            )
            track_inbound("unsupported_exam", profile)
            return {"status": "ok"}

        if needs_onboarding(phone, profile, text):
            if is_learning_request(text):
                profile_waiting = user_profiles.get(phone, profile)
                profile_waiting["pending_question"] = text
                profile_waiting["pending_question_display"] = original_text
                user_profiles[phone] = profile_waiting
                send_whatsapp(phone, f"J'ai gardé ta question : {original_text}")
                track_inbound("needs_onboarding_pending_question", profile_waiting)
            else:
                track_inbound("needs_onboarding", user_profiles.get(phone, profile))
            return {"status": "ok"}

        if is_profile_locked(profile) and not is_explicit_profile_change_request(text):
            type_examen = profile.get("type_examen") or infer_type_examen(profile.get("serie", "TOUTES"), text)
        else:
            type_examen = infer_type_examen(profile.get("serie", "TOUTES"), text)

        mode = profile.get("mode") or infer_mode(text)
        profile["type_examen"] = type_examen
        profile["mode"] = mode
        lock_profile_if_ready(profile)
        user_profiles[phone] = profile
        sauver_etat_whatsapp(phone, profile)

        matiere = profile.get("matiere", "MATHS")
        serie = profile.get("serie", "TOUTES")
        conversation_key = f"{phone}:{type_examen}:{serie}:{matiere}:{mode}"

        print(f"Profil WhatsApp: {profile}", flush=True)
        print(f"Conversation key: {conversation_key}", flush=True)
        track_inbound("akili_api", profile)

        answer_learning_request(
            phone, profile, text, media_file=media_file, message_id=message_id,
            reply_audio=incoming_was_audio, document_context=document_context,
        )

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
