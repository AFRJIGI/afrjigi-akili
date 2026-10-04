import os
import time
import json
import requests
import re
import unicodedata
import uuid
import hashlib
import contextvars
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from google.cloud import firestore, storage
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from gtts import gTTS
import tableau_de_bord
from template_replies import retention_template_text
import pedagogical_consent as pedagogical
from marketing_consent import (
    OPTED_IN,
    claim_marketing_consent_prompt,
    detect_marketing_consent_command,
    mark_marketing_consent_prompt_delivery,
    save_marketing_consent,
)

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



def prefixe_avis(text):
    """("retour", "trop long") pour "Retour : trop long" ; None si le message n'est pas un avis.
    Accepte avis:, retour: et feedback:, avec ou sans espace avant les deux-points."""
    m = re.match(r"^\s*(avis|retour|feedback)\s*:\s*(.*)$", text or "", flags=re.I | re.S)
    if not m:
        return None
    return m.group(1).lower(), m.group(2).strip()


def retour_est_une_reponse(prefixe, contenu, derniere_question):
    """"Retour: aucune contradiction" juste apres une question d'Akili : c'est la reponse
    de l'eleve a l'exercice ("retour" se comprend comme "reponse"), pas un avis."""
    if prefixe != "retour" or not contenu:
        return False
    if len(normalize_for_match(contenu).split()) > 8:
        return False
    return (derniere_question or "").rstrip().endswith("?")


def save_feedback_whatsapp(phone, feedback_text, profile=None, original_message=None, statut="nouveau", type_avis="retour"):
    try:
        profile = profile or {}
        feedback_db.collection("feedback_whatsapp").add({
            "phone": phone,
            "type": type_avis,
            "feedback": feedback_text,
            "original_message": original_message or "",
            "serie_detectee": profile.get("serie", ""),
            "matiere_detectee": profile.get("matiere", ""),
            "type_examen_detecte": profile.get("type_examen", ""),
            "mode_detecte": profile.get("mode", ""),
            "statut": statut,
            "source": "whatsapp",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        print(f"Feedback WhatsApp enregistré pour {phone} type={type_avis}", flush=True)
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


# Telephones dont la derniere lecture Firestore a echoue : on ne remplace pas leur etat en entier.
_etat_lecture_echouee = set()


def charger_etat_whatsapp(phone):
    """Recharge l'etat conversationnel depuis Firestore (survit au scale-to-zero)."""
    try:
        doc = feedback_db.collection("whatsapp_state").document(phone).get()
        _etat_lecture_echouee.discard(phone)
        if doc.exists:
            return doc.to_dict() or {}
    except Exception as e:
        _etat_lecture_echouee.add(phone)
        print(f"Erreur charger_etat_whatsapp: {repr(e)}", flush=True)
    return {}

def sauver_etat_whatsapp(phone, profile):
    """Persiste l'etat conversationnel dans Firestore. Le profil remplace l'etat en entier,
    sinon les cles retirees (pending_question, profile_locked...) reviendraient au message suivant."""
    try:
        feedback_db.collection("whatsapp_state").document(phone).set(
            dict(profile or {}), merge=phone in _etat_lecture_echouee
        )
    except Exception as e:
        print(f"Erreur sauver_etat_whatsapp: {repr(e)}", flush=True)


# ─── DEDOUBLONNAGE : Meta renvoie le meme message si la reponse tarde ───
# Chaque copie Cloud Run a sa propre memoire : le registre doit etre dans Firestore.
MESSAGES_TRAITES_COLLECTION = "whatsapp_messages_traites"
MESSAGES_TRAITES_JOURS = 7


def _message_traite_ref(message_id):
    cle = hashlib.sha256(str(message_id).encode("utf-8")).hexdigest()
    return feedback_db.collection(MESSAGES_TRAITES_COLLECTION).document(cle)


def _est_deja_existant(exc):
    return any(c.__name__ in {"AlreadyExists", "Conflict"} for c in type(exc).__mro__)


def reserver_message_whatsapp(message_id):
    """Vrai si ce message n'a encore ete pris par aucune copie du bot (create echoue s'il existe)."""
    if not message_id:
        return True
    now = datetime.now(timezone.utc)
    try:
        _message_traite_ref(message_id).create({
            "recu_at": now.isoformat(),
            "expire_at": now + timedelta(days=MESSAGES_TRAITES_JOURS),
        })
        return True
    except Exception as e:
        if _est_deja_existant(e):
            return False
        # Firestore indisponible : mieux vaut repondre deux fois que jamais.
        print(f"Erreur reserver_message_whatsapp: {repr(e)}", flush=True)
        return True


def liberer_message_whatsapp(message_id):
    """Permet a Meta de renvoyer ce message (on a repondu 503 pour qu'il reessaie)."""
    if not message_id:
        return
    try:
        _message_traite_ref(message_id).delete()
    except Exception as e:
        print(f"Erreur liberer_message_whatsapp: {repr(e)}", flush=True)


# Telephone dont le profil a ete charge pendant la requete en cours (sauve a la fin).
_profil_charge_requete = contextvars.ContextVar("profil_charge_requete", default=None)

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


MARKETING_CONSENT_PROMPT = (
    "Souhaites-tu recevoir sur WhatsApp les rappels pédagogiques et les offres "
    "d'AfrJigi ?\n\nPour accepter, envoie OUI MARKETING. Tu pourras te "
    "désinscrire à tout moment en envoyant STOP."
)


def maybe_send_marketing_consent_prompt(phone):
    """Invite une seule fois, après un message initié par l'utilisateur."""
    try:
        claim_id = pedagogical.claim_prompt(feedback_db, phone)
    except Exception as exc:
        print(
            "WHATSAPP_MARKETING_CONSENT_PROMPT claim_failed "
            f"error_class={type(exc).__name__}",
            flush=True,
        )
        return False
    if not claim_id:
        return False

    delivered = False
    try:
        delivered = bool(send_whatsapp_boutons(
            phone,
            pedagogical.PROMPT,
            pedagogical.BUTTONS,
        ))
    except Exception as exc:
        print(
            "WHATSAPP_MARKETING_CONSENT_PROMPT send_failed "
            f"error_class={type(exc).__name__}",
            flush=True,
        )
    try:
        pedagogical.mark_prompt(
            feedback_db, phone, claim_id, delivered
        )
    except Exception as exc:
        print(
            "WHATSAPP_MARKETING_CONSENT_PROMPT delivery_state_failed "
            f"error_class={type(exc).__name__}",
            flush=True,
        )
    return delivered



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


BAC_GENERAL_SERIES_CHOICES = {
    "a": "A1",
    "b": "A2",
    "c": "C",
    "d": "D",
}

BAC_TECHNIQUE_SERIES_CHOICES = {
    "a": "B",
    "b": "G1",
    "c": "G2",
    "d": "E",
    "e": "F1",
    "f": "F2",
    "g": "F3",
    "h": "F4",
    "i": "F7",
}

BAC_TECHNIQUE_SUBJECT_CHOICES = {
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
    "m": "ANGLAIS",
}

LETTRES_CHOIX = "abcdefghijklm"

# Liste actuelle (tertiaire + quelques matieres industrielles), pour les series sans liste propre.
MATIERES_TECHNIQUE_PAR_DEFAUT = [
    ("COMPTA_FIN", "Comptabilité Financière"),
    ("COMPTA_SOCIETES", "Comptabilité des sociétés"),
    ("COMPTA_ANALYTIQUE", "Comptabilité Analytique"),
    ("MATHS_FIN", "Mathématiques financières"),
    ("MATHS_GENERAL", "Mathématique Générale"),
    ("ECO", "Économie"),
    ("EXPRESSION_PRO", "Expression Professionnelle"),
    ("PHYSIQUE_APPLIQUEE", "Physique Appliquée"),
    ("ESTI", "Étude des Systèmes Techniques Industriels"),
    ("DROIT", "Droit"),
    ("HG", "Histoire-Géographie"),
    ("FRANCAIS", "Français"),
    ("ANGLAIS", "Anglais"),
]

# Matieres propres a chaque serie (liste fournie par AfrJigi).
MATIERES_TECHNIQUE_PAR_SERIE = {
    # F2 : liste fournie par AfrJigi. Les autres series : d'apres les progressions
    # officielles (MET-FPA, DPFC) recensees dans reports/bac_technique_progressions_inventory.json.
    "B": [
        ("ECO", "Sciences économiques et sociales (SES)"),
        ("MATHS", "Mathématiques"),
        ("FRANCAIS", "Français"),
        ("ANGLAIS", "Anglais"),
        ("HG", "Histoire-Géographie"),
        ("PHILO", "Philosophie"),
    ],
    "G1": [
        ("ECO", "Économie (générale et d'entreprise)"),
        ("DROIT", "Droit"),
        ("EXPRESSION_PRO", "Expression professionnelle"),
        ("MATHS", "Mathématiques"),
        ("FRANCAIS", "Français"),
        ("ANGLAIS", "Anglais"),
        ("HG", "Histoire-Géographie"),
        ("PHILO", "Philosophie"),
    ],
    "G2": [
        ("COMPTA_FIN", "Comptabilité financière"),
        ("COMPTA_ANALYTIQUE", "Comptabilité analytique"),
        ("COMPTA_SOCIETES", "Comptabilité des sociétés"),
        ("MATHS_FIN", "Mathématiques financières"),
        ("MATHS", "Mathématiques"),
        ("ECO", "Économie (générale et d'entreprise)"),
        ("DROIT", "Droit"),
        ("EXPRESSION_PRO", "Expression professionnelle"),
        ("FRANCAIS", "Français"),
        ("ANGLAIS", "Anglais"),
        ("HG", "Histoire-Géographie"),
        ("PHILO", "Philosophie"),
    ],
    "E": [
        ("MATHS", "Mathématiques"),
        ("PC", "Sciences physiques"),
        ("CMI", "Construction mécanique industrielle (CMI)"),
        ("TECHNO_GENERALE", "Technologie générale"),
        ("AUTOMATISME", "Automatisme"),
        ("ETUDE_FABRICATION", "Étude de fabrication"),
        ("FABRICATION", "Fabrication (tournage, fraisage)"),
        ("FRANCAIS", "Français"),
        ("ANGLAIS", "Anglais"),
        ("HG", "Histoire-Géographie"),
        ("PHILO", "Philosophie"),
    ],
    "F3": [
        ("PHYSIQUE_APPLIQUEE", "Physique appliquée"),
        ("TECHNO_SCHEMAS", "Technologie et schémas"),
        ("MESURES_ESSAIS", "Mesures et essais"),
        ("CABLAGE", "Câblage"),
        ("CMI", "Construction mécanique industrielle (CMI)"),
        ("MATHS", "Mathématiques"),
        ("FRANCAIS", "Français"),
        ("ANGLAIS", "Anglais"),
        ("HG", "Histoire-Géographie"),
        ("PHILO", "Philosophie"),
    ],
    "F4": [
        ("TOPOGRAPHIE", "Topographie appliquée"),
        ("RDM", "Résistance des matériaux (RDM)"),
        ("TECHNO_GENIE_CIVIL", "Technologie (génie civil)"),
        ("METHODES", "Méthodes"),
        ("LABO_MATERIAUX", "Laboratoire (essais des matériaux)"),
        ("DESSIN_GENIE_CIVIL", "Dessin technique (génie civil)"),
        ("LEGISLATION", "Législation"),
        ("MATHS", "Mathématiques"),
        ("FRANCAIS", "Français"),
        ("ANGLAIS", "Anglais"),
        ("HG", "Histoire-Géographie"),
        ("PHILO", "Philosophie"),
    ],
    "F7": [
        ("BIOCHIMIE", "Biochimie"),
        ("MICROBIOLOGIE", "Microbiologie"),
        ("BIOLOGIE", "Biologie"),
        ("CHIMIE", "Chimie"),
        ("MATHS", "Mathématiques"),
        ("FRANCAIS", "Français"),
        ("ANGLAIS", "Anglais"),
        ("HG", "Histoire-Géographie"),
        ("PHILO", "Philosophie"),
    ],
    "F1": [
        ("CMI", "Construction mécanique industrielle (CMI)"),
        ("MECANIQUE", "Mécanique"),
        ("TECHNO_GENERALE", "Technologie générale"),
        ("AUTOMATISME", "Automatisme"),
        ("BUREAU_METHODES", "Bureau des méthodes"),
        ("ETUDE_OUTILLAGE", "Étude d'outillage"),
        ("FABRICATION", "Fabrication (tournage, fraisage, affûtage)"),
        ("MATHS", "Mathématiques"),
        ("PHYSIQUE_APPLIQUEE", "Physique appliquée (PCT)"),
        ("FRANCAIS", "Français"),
        ("ANGLAIS", "Anglais"),
        ("HG", "Histoire-Géographie"),
        ("PHILO", "Philosophie"),
    ],
    "F2": [
        ("MECANIQUE_APPLIQUEE", "Mécanique appliquée"),
        ("CMI", "Construction mécanique industrielle"),
        ("FRANCAIS", "Français"),
        ("ANGLAIS", "Anglais"),
        ("HG", "Histoire-Géographie"),
        ("MATHS", "Mathématiques"),
        ("PHYSIQUE_APPLIQUEE", "Physique appliquée (PCT)"),
        ("ELECTRONIQUE", "Électronique"),
        ("DESSIN_INDUSTRIEL", "Dessin industriel / Dessin technique"),
        ("TECHNO_SCHEMAS", "Technologie et schémas"),
        ("INFORMATIQUE_INDUSTRIELLE", "Informatique industrielle"),
    ],
}


# Autres facons d'ecrire une matiere (en plus de son libelle).
MOTS_CLES_MATIERE_TECHNIQUE = {
    "COMPTA_FIN": ["COMPTABILITE FINANCIERE", "COMPTA FINANCIERE", "COMPTA FIN"],
    "COMPTA_SOCIETES": ["COMPTABILITE DES SOCIETES", "COMPTA SOCIETES"],
    "COMPTA_ANALYTIQUE": ["COMPTABILITE ANALYTIQUE", "COMPTA ANALYTIQUE"],
    "MATHS_FIN": ["MATHEMATIQUES FINANCIERES", "MATHS FINANCIERES", "MATHS FIN"],
    "MATHS_GENERAL": ["MATHEMATIQUE GENERALE", "MATHS GENERALE", "MATHS", "MATH", "MATHEMATIQUES"],
    "MATHS": ["MATHS", "MATH", "MATHEMATIQUES", "MATHEMATIQUE"],
    "ECO": ["ECONOMIE", "ECO", "SES", "SCIENCES ECONOMIQUES"],
    "DROIT": ["DROIT"],
    "EXPRESSION_PRO": ["EXPRESSION PROFESSIONNELLE", "EXPRESSION"],
    "PHYSIQUE_APPLIQUEE": ["PHYSIQUE APPLIQUEE", "PHYSIQUE", "PCT"],
    "PC": ["SCIENCES PHYSIQUES", "PHYSIQUE", "PHYSIQUE CHIMIE", "PC"],
    "ESTI": ["ETUDE DES SYSTEMES", "SYSTEMES TECHNIQUES", "ESTI"],
    "HG": ["HISTOIRE GEOGRAPHIE", "HG", "HISTOIRE", "GEOGRAPHIE"],
    "FRANCAIS": ["FRANCAIS", "FRENCH"],
    "ANGLAIS": ["ANGLAIS", "ENGLISH"],
    "PHILO": ["PHILOSOPHIE", "PHILO"],
    "MECANIQUE_APPLIQUEE": ["MECANIQUE APPLIQUEE"],
    "MECANIQUE": ["MECANIQUE", "MECA"],
    "CMI": ["CMI", "CONSTRUCTION MECANIQUE"],
    "ELECTRONIQUE": ["ELECTRONIQUE"],
    "DESSIN_INDUSTRIEL": ["DESSIN INDUSTRIEL", "DESSIN TECHNIQUE", "DESSIN"],
    "TECHNO_SCHEMAS": ["TECHNOLOGIE ET SCHEMAS", "TECHNO SCHEMA", "TECHNO SCHEMAS", "SCHEMAS", "SCHEMA"],
    "INFORMATIQUE_INDUSTRIELLE": ["INFORMATIQUE INDUSTRIELLE", "INFORMATIQUE"],
    "TECHNO_GENERALE": ["TECHNOLOGIE GENERALE", "TECHNO GENERALE", "TECHNOLOGIE"],
    "AUTOMATISME": ["AUTOMATISME", "AUTOMATISMES"],
    "BUREAU_METHODES": ["BUREAU DES METHODES", "METHODES"],
    "ETUDE_OUTILLAGE": ["ETUDE D OUTILLAGE", "OUTILLAGE"],
    "ETUDE_FABRICATION": ["ETUDE DE FABRICATION"],
    "FABRICATION": ["FABRICATION", "TOURNAGE", "FRAISAGE", "AFFUTAGE"],
    "MESURES_ESSAIS": ["MESURES ET ESSAIS", "MESURES", "ESSAIS"],
    "CABLAGE": ["CABLAGE"],
    "TOPOGRAPHIE": ["TOPOGRAPHIE", "TOPO"],
    "RDM": ["RESISTANCE DES MATERIAUX", "RDM"],
    "TECHNO_GENIE_CIVIL": ["TECHNOLOGIE", "TECHNO"],
    "METHODES": ["METHODES"],
    "LABO_MATERIAUX": ["LABORATOIRE", "LABO", "ESSAIS DES MATERIAUX"],
    "DESSIN_GENIE_CIVIL": ["DESSIN TECHNIQUE", "DESSIN"],
    "LEGISLATION": ["LEGISLATION"],
    "BIOCHIMIE": ["BIOCHIMIE", "BIOCHIMIQUE"],
    "MICROBIOLOGIE": ["MICROBIOLOGIE", "MICROBIO"],
    "BIOLOGIE": ["BIOLOGIE", "BIO"],
    "CHIMIE": ["CHIMIE"],
}


def lettre_matiere_technique(serie, text):
    """Lettre de la matiere ecrite en toutes lettres ("anglais", "compta analytique"),
    dans la liste de la serie de l'eleve. L'expression la plus longue gagne
    ("construction mecanique" -> CMI, pas Mecanique)."""
    msg = normalize_for_match(text)
    meilleure, longueur = None, 0
    for i, (code, libelle) in enumerate(matieres_technique(serie)):
        for mot in [libelle] + MOTS_CLES_MATIERE_TECHNIQUE.get(code, []):
            mot_norm = normalize_for_match(mot)
            if len(mot_norm) > longueur and has_expr(msg, mot_norm):
                meilleure, longueur = LETTRES_CHOIX[i], len(mot_norm)
    return meilleure


def matieres_technique(serie):
    """Liste (code, libelle) des matieres proposees pour cette serie du BAC Technique."""
    serie = (serie or "").upper().strip()
    return MATIERES_TECHNIQUE_PAR_SERIE.get(serie, MATIERES_TECHNIQUE_PAR_DEFAUT)


def choix_matieres_technique(serie):
    """{lettre: code} pour l'etape matiere du BAC Technique."""
    return {LETTRES_CHOIX[i]: code for i, (code, _) in enumerate(matieres_technique(serie))}


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
        "10": "j", "J": "j",
        "11": "k", "K": "k",
        "12": "l", "L": "l",
        "13": "m", "M": "m",
    }
    return mapping.get(c)


MESSAGE_HORS_CHAMP = (
    "Akili accompagne les élèves de la 6e à la Terminale : BEPC, BAC Général et BAC Technique. "
    "Si tu es dans l'une de ces classes, choisis ton niveau :"
)


DEMANDES_EXPLICATION = [
    "EXPLIQUE", "EXPLIQUER", "EXPLIQUEZ", "GUIDE MOI", "GUIDEZ MOI", "GUIDER", "PAS A PAS",
    "JE NE COMPRENDS PAS", "JE COMPRENDS PAS", "J AI PAS COMPRIS", "JE N AI PAS COMPRIS",
    "COMMENT ON FAIT", "COMMENT FAIRE", "AIDE MOI", "AIDEZ MOI", "TRAITE MOI", "TRAITE CET EXERCICE",
    "RESOUS", "RESOUDRE POUR MOI", "DONNE MOI LA REPONSE", "DONNE LA REPONSE", "JE SUIS BLOQUE",
    "JE NE SAIS PAS", "JE SAIS PAS", "MONTRE MOI",
]
OFFRE_MODE_ETUDE = (
    "En mode examen, Akili ne donne pas d'explication : tu résous seul, puis il corrige et note ta copie.\n\n"
    "Tu veux plutôt que je t'explique pas à pas ? Passe en mode étude."
)
BOUTONS_MODE = [("mode_etude_oui", "Oui, mode étude"), ("mode_examen_garder", "Non, je continue")]
OFFRE_MODE_PAUSE_MINUTES = 30


def demande_explication(text):
    msg = normalize_for_match(text)
    if not msg or msg.startswith("ANALYSE CE SUJET ENVOYE"):
        return False
    return any(has_expr(msg, expr) for expr in DEMANDES_EXPLICATION)


def proposer_mode_etude(phone, profile, text, now=None):
    """Vrai si on vient de proposer le mode etude (eleve en mode examen qui demande de l'aide)."""
    now = now or datetime.now(timezone.utc)
    if (profile.get("mode") or "") != "examen" or not demande_explication(text):
        return False
    refus = parse_datetime(profile.get("offre_mode_etude_refusee_at"))
    if refus and now - refus < timedelta(minutes=OFFRE_MODE_PAUSE_MINUTES):
        return False
    profile["demande_mode_etude"] = {"texte": text, "at": now.isoformat()}
    if not send_whatsapp_boutons(phone, OFFRE_MODE_ETUDE, BOUTONS_MODE):
        send_whatsapp(phone, OFFRE_MODE_ETUDE + "\n\nPour changer de mode, écris menu.", allow_audio=False)
    return True


def copier_historique(ancienne_cle, nouvelle_cle):
    """L'exercice commence en mode examen continue en mode etude avec son historique."""
    if ancienne_cle == nouvelle_cle:
        return
    nouveau = charger_historique_conv(nouvelle_cle)
    if nouveau:
        return
    ancien = charger_historique_conv(ancienne_cle) or list(conversations.get(ancienne_cle) or [])
    if ancien:
        conversations[nouvelle_cle] = list(ancien)[-10:]
        sauver_historique_conv(nouvelle_cle, conversations[nouvelle_cle])


def traiter_bouton_mode(phone, bouton_id):
    if bouton_id not in {"mode_etude_oui", "mode_examen_garder"}:
        return False
    profile = charger_etat_whatsapp(phone) or user_profiles.get(phone) or {}
    demande = profile.pop("demande_mode_etude", None) or {}
    if bouton_id == "mode_examen_garder":
        profile["offre_mode_etude_refusee_at"] = datetime.now(timezone.utc).isoformat()
        user_profiles[phone] = profile
        sauver_etat_whatsapp(phone, profile)
        send_whatsapp(phone, "D'accord, on reste en mode examen : résous l'exercice sur ta feuille, "
                             "puis envoie la photo de ta copie.", allow_audio=False)
        return True
    ancienne_cle = cle_conversation_profil(phone, profile)
    profile["mode"] = "etude"
    copier_historique(ancienne_cle, cle_conversation_profil(phone, profile))
    user_profiles[phone] = profile
    sauver_etat_whatsapp(phone, profile)
    send_whatsapp(phone, "C'est noté, on passe en mode étude : je t'explique pas à pas.", allow_audio=False)
    if demande.get("texte"):
        answer_learning_request(phone, profile, demande["texte"])
        sauver_etat_whatsapp(phone, user_profiles.get(phone, profile))
    return True


def recuperer_media_garde(media_info):
    """Retelecharge la photo envoyee pendant l'inscription (WhatsApp la garde 30 jours)."""
    if not media_info or not media_info.get("media_id"):
        return None, None
    try:
        fichier = download_whatsapp_media(media_info["media_id"], media_info.get("filename") or "whatsapp_image",
                                          media_info.get("mime_type") or "image/jpeg")
    except Exception as e:
        print(f"Erreur recuperer_media_garde: {repr(e)}", flush=True)
        return None, None
    if not fichier:
        return None, None
    contexte = {"id": None, "ref": None, "gcs_uri": None, "media_id": media_info["media_id"],
                "mime_type": media_info.get("mime_type"), "sha256": None}
    return fichier, contexte


def repartir_premiere_question(profile):
    """Sort un profil "AUTRE" (ancienne option Concours / autre) : retour a la premiere question."""
    profile = dict(profile or {})
    for cle in ("type_examen", "classe", "profile_locked", "profile_ready", "matiere_confirmed"):
        profile.pop(cle, None)
    profile["serie"] = "TOUTES"
    profile["onboarding_step"] = "exam"
    return profile


def ask_exam(phone):
    send_whatsapp(phone,
        "Bienvenue sur Akili.\n\n"
        "Quel niveau prépares-tu ?\n\n"
        "a. BEPC / 3e\n"
        "b. BAC Général\n"
        "c. BAC Technique\n"
        "d. Classe intermédiaire : 6e, 5e, 4e, Seconde ou Première\n\n"
        "Réponds par a, b, c ou d."
    )


def ask_serie_general(phone):
    send_whatsapp(phone,
        "Quelle série du BAC Général ?\n\n"
        "a. A1\n"
        "b. A2\n"
        "c. C\n"
        "d. D\n\n"
        "Réponds par a, b, c ou d."
    )


CLASSES_TECHNIQUE = {"a": "SECONDE", "b": "PREMIERE", "c": "TERMINALE"}
LIBELLES_CLASSES = {"SECONDE": "Seconde", "PREMIERE": "Première", "TERMINALE": "Terminale"}


def ask_classe_technique(phone):
    send_whatsapp(phone,
        "Tu es en quelle classe ?\n\n"
        "a. Seconde\n"
        "b. Première\n"
        "c. Terminale\n\n"
        "Réponds par a, b ou c."
    )


def ask_serie_technique(phone):
    send_whatsapp(phone,
        "Quelle série du BAC Technique ?\n\n"
        "a. B\n"
        "b. G1\n"
        "c. G2\n"
        "d. E\n"
        "e. F1\n"
        "f. F2\n"
        "g. F3\n"
        "h. F4\n"
        "i. F7\n\n"
        "Réponds par a, b, c, d, e, f, g, h ou i."
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



def menu_matieres_technique(serie=None):
    matieres = matieres_technique(serie)
    lettres = LETTRES_CHOIX[:len(matieres)]
    lignes = "\n".join(f"{lettres[i]}. {libelle}" for i, (_, libelle) in enumerate(matieres))
    return (
        "Quelle matière veux-tu travailler ?\n\n"
        f"{lignes}\n\n"
        f"Réponds par {', '.join(lettres[:-1])} ou {lettres[-1]}."
    )


def ask_matiere_technique(phone, serie=None):
    send_whatsapp(phone, menu_matieres_technique(serie))


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
        "a) Mode Étude : Akili t'explique pas à pas\n"
        "b) Mode Examen : tu fais seul, Akili corrige et note\n\n"
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

    if step == "matiere" and profile.get("type_examen") == "BAC_TECHNIQUE":
        return lettre_matiere_technique(profile.get("serie"), text)

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
        },
        "serie_general": {
            "a": ["A1"], "b": ["A2"],
            "c": ["SERIE C", "TERMINALE C", "TERMINAL C"],
            "d": ["SERIE D", "TERMINALE D", "TERMINAL D"],
        },
        "classe_technique": {
            "a": ["SECONDE", "2NDE", "2ND"],
            "b": ["PREMIERE", "1ERE", "1IERE"],
            "c": ["TERMINALE", "TERMINAL", "TLE"],
        },
        "serie_technique": {
            "a": ["SERIE B", "TERMINALE B", "TERMINAL B"],
            "b": ["G1"], "c": ["G2"],
            "d": ["SERIE E", "TERMINALE E", "TERMINAL E"],
            "e": ["F1"], "f": ["F2"], "g": ["F3"], "h": ["F4"], "i": ["F7"],
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
            f"Profil prêt : {resume_profil(profile)}.\n\n"
            "Envoie maintenant ton exercice, une photo, un PDF ou le chapitre à travailler.\n\n"
                "Commandes utiles :\n"
                "- menu : changer de matiere ou de niveau\n"
                "- changer profil : modifier ton niveau, ta série ou ta matière\n"
                "- avis: ton avis sur Akili\n\n"
                "Pendant le Grand Pilote, ton avis compte beaucoup."
        )
        return True

    key = choice_key(text) or mot_cle_vers_lettre(step, text, profile)
    if not key:
        return reposer_si_choix_attendu(phone, profile, text)

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


    if step == "serie_general":
        values = BAC_GENERAL_SERIES_CHOICES
        if key in values:
            profile["serie"] = values[key]
            profile["onboarding_step"] = "matiere"
            user_profiles[phone] = profile
            sauver_etat_whatsapp(phone, profile)
            ask_matiere(phone, profile["serie"])
            return True

    if step == "serie_technique":
        values = BAC_TECHNIQUE_SERIES_CHOICES
        if key in values:
            profile["serie"] = values[key]
            profile["onboarding_step"] = "classe_technique"
            user_profiles[phone] = profile
            sauver_etat_whatsapp(phone, profile)
            ask_classe_technique(phone)
            return True

    if step == "classe_technique":
        if key in CLASSES_TECHNIQUE:
            profile["classe"] = CLASSES_TECHNIQUE[key]
            profile["onboarding_step"] = "matiere"
            user_profiles[phone] = profile
            sauver_etat_whatsapp(phone, profile)
            ask_matiere_technique(phone, profile.get("serie"))
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
            values = choix_matieres_technique(profile.get("serie"))
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
                    f"C'est noté : {resume_profil(profile)}.\n\n"
                    "Envoie maintenant ton exercice, une photo, un PDF ou le chapitre à travailler."
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
                f"Profil prêt : {resume_profil(profile)}.\n\n"
                "Envoie maintenant ton exercice, une photo, un PDF ou le chapitre à travailler.\n\n"
                "Commandes utiles :\n"
                "- menu : changer de matiere ou de niveau\n"
                "- changer profil : modifier ton niveau, ta série ou ta matière\n"
                "- avis: ton avis sur Akili\n\n"
                "Pendant le Grand Pilote, ton avis compte beaucoup."
            )
            return True

    return reposer_si_choix_attendu(phone, profile, text)


# Etapes ou seule une lettre de la liste est attendue. L'etape "exam" n'y est pas :
# l'eleve peut y ecrire son profil en toutes lettres ("Je suis en Terminale D...").
ETAPES_A_REPOSER = {"exam", "serie_general", "serie_technique", "classe_technique", "seconde", "classe_intermediaire", "matiere", "mode"}
MESSAGE_CHOIX_NON_COMPRIS = "Je n'ai pas compris ton choix. Réponds seulement avec la lettre de la liste."


def reposer_si_choix_attendu(phone, profile, text):
    """Reponse qui ne correspond a aucun choix ("anglais" a la question du mode) :
    on repose la question au lieu de l'envoyer a Akili avec un profil incomplet.
    Une vraie question (longue) continue son chemin habituel."""
    if profile.get("onboarding_step") not in ETAPES_A_REPOSER:
        return False
    nb_mots = len(normalize_for_match(text).split())
    if profile.get("onboarding_step") == "exam" and not re.fullmatch(r"[A-Za-z]", (text or "").strip()):
        return False
    if nb_mots > 3 and (nb_mots > 6 or is_learning_request(text)):
        return False
    send_whatsapp(phone, MESSAGE_CHOIX_NON_COMPRIS)
    reposer_question_onboarding(phone, profile)
    return True


def reposer_question_onboarding(phone, profile):
    """Renvoie la question de l'etape en cours. Faux si l'etape n'a pas de question a reposer."""
    step = profile.get("onboarding_step")
    if step == "exam":
        ask_exam(phone)
    elif step == "ville":
        ask_ville(phone)
    elif step == "nom_ecole":
        ask_nom_ecole(phone)
    elif step == "serie_general":
        ask_serie_general(phone)
    elif step == "serie_technique":
        ask_serie_technique(phone)
    elif step == "classe_technique":
        ask_classe_technique(phone)
    elif step == "seconde":
        ask_seconde(phone)
    elif step == "classe_intermediaire":
        ask_classe_intermediaire(phone)
    elif step == "matiere":
        if profile.get("type_examen") == "BAC_TECHNIQUE":
            ask_matiere_technique(phone, profile.get("serie"))
        else:
            ask_matiere(phone, profile.get("serie", "TOUTES"))
    elif step == "mode":
        ask_mode(phone)
    else:
        return False
    return True


MESSAGE_REPRISE_INSCRIPTION = "Bonjour ! On continue ton inscription là où tu t'es arrêté."


def needs_onboarding(phone, profile, text):
    msg = normalize_for_match(text)

    if is_other_or_concours(text) and not is_profile_ready(profile):
        profile.update(repartir_premiere_question(profile))
        user_profiles[phone] = profile
        send_whatsapp(phone, MESSAGE_HORS_CHAMP)
        ask_exam(phone)
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


MESSAGE_UNE_MATIERE_A_LA_FOIS = (
    "Je t'accompagne sur une matière à la fois pour bien suivre ton travail.\n"
    "Par laquelle veux-tu commencer ? Réponds par une seule lettre.\n\n"
    "Tu pourras changer quand tu veux en écrivant : changer matière"
)


def veut_plusieurs_matieres(text):
    """Detecte, a l'etape matiere, un eleve qui choisit plusieurs matieres
    ("a,b,c,d,e,i", "a et c") ou toutes ("je veux tout", "toutes les matieres")."""
    tokens = normalize_for_match(text).split()
    if not tokens:
        return False
    if any(t in {"TOUT", "TOUTES", "TOUS"} for t in tokens):
        return True
    choix = r"[A-M]|1[0-3]|[1-9]"
    lettres = {t for t in tokens if re.fullmatch(choix, t)}
    autres = [t for t in tokens if not re.fullmatch(choix, t) and t not in {"ET", "OU"}]
    return len(lettres) > 1 and not autres


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


def send_whatsapp(
    to, message, limit=1600, add_continuation=True, persist_event=True, allow_audio=True
):
    message = clean_whatsapp_response(message)

    now_ts = time.time()
    dedupe_key = str(to)
    previous = last_outbound_by_phone.get(dedupe_key)
    if previous:
        previous_text, previous_ts = previous
        if previous_text == message and now_ts - previous_ts < 20:
            print("WHATSAPP_SEND_DEDUPE skipped duplicate", flush=True)
            return True

    last_outbound_by_phone[dedupe_key] = (message, now_ts)

    should_reply_audio = allow_audio and bool(audio_reply_context.get(str(to)))
    message_parts = split_whatsapp_message(message, limit=limit, max_parts=1, add_continuation=add_continuation)

    if not message_parts:
        return False

    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    sent = True
    for index, part in enumerate(message_parts, start=1):
        print(f"WHATSAPP_SEND_TEXT part={index}/{len(message_parts)} len={len(part)}: {part}", flush=True)

        data = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": part},
        }

        res = requests.post(url, headers=headers, json=data)
        if persist_event:
            print(f"DEBUG SEND: Status {res.status_code} - Response: {res.text}", flush=True)
        else:
            print(f"DEBUG SEND: Status {res.status_code}", flush=True)

        if res.status_code >= 300:
            sent = False
            continue
        if persist_event:
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

    return sent




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
    """Recharge l'historique depuis Firestore. None si Firestore est en panne
    (on garde alors la memoire de cette copie), [] s'il n'y a pas d'historique."""
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
        return None
    return []


def effacer_traces_conversation(phone):
    """Reset : efface aussi ce que Firestore garde de l'eleve (historiques de toutes ses
    matieres, dernier message d'Akili, session en cours pour le bilan). Sinon l'ancien
    historique revenait apres le reset et Akili reprenait l'ancien exercice ou l'ancien mode."""
    phone = str(phone)
    try:
        docs = (
            feedback_db.collection("whatsapp_historiques")
            .where("conversation_key", ">=", f"{phone}:")
            .where("conversation_key", "<", f"{phone};")
            .stream()
        )
        for doc in docs:
            doc.reference.delete()
    except Exception as e:
        print(f"Erreur effacer historiques: {repr(e)}", flush=True)
    for collection in ("whatsapp_contexts", "whatsapp_sessions_bilan"):
        try:
            feedback_db.collection(collection).document(phone).delete()
        except Exception as e:
            print(f"Erreur effacer {collection}: {repr(e)}", flush=True)


# ─── FIN DE SESSION : bilan quand l'eleve dit au revoir, ou apres une pause ───
SESSIONS_BILAN_COLLECTION = "whatsapp_sessions_bilan"
SESSION_INACTIVITE_MINUTES = 30
SESSION_FENETRE_WHATSAPP_HEURES = 23  # WhatsApp n'autorise un message libre que 24 h apres le dernier message de l'eleve
SESSION_MAX_MESSAGES = 40
BILAN_MIN_ECHANGES_INACTIVITE = 2
BILAN_MAX_PAR_TACHE = 20
AKILI_BILAN_URL = os.environ.get("AKILI_BILAN_URL", AKILI_API_URL.rsplit("/", 1)[0] + "/bilan-session")
MESSAGE_AVIS_FIN_SESSION = "Ton avis nous aide : écris « avis: » suivi de ton message."
MESSAGE_AU_REVOIR_SIMPLE = "À bientôt ! Reviens quand tu veux : envoie un exercice, une photo ou le chapitre à travailler."

EXPRESSIONS_AU_REVOIR = [
    "AU REVOIR", "AUREVOIR", "A BIENTOT", "A DEMAIN", "A LA PROCHAINE", "A PLUS TARD",
    "BONNE NUIT", "BONNE SOIREE", "BYE",
    "C EST FINI POUR AUJOURD HUI", "FINI POUR AUJOURD HUI", "C EST TOUT POUR AUJOURD HUI",
    "JE M ARRETE LA", "JE M ARRETE ICI", "JE M ARRETE POUR AUJOURD HUI",
    "ON S ARRETE LA", "ON S ARRETE ICI", "ON ARRETE LA", "ON ARRETE ICI",
    "FIN DE SESSION", "FIN DE LA SESSION", "TERMINER LA SESSION", "ARRETER LA SESSION",
    "JE VAIS DORMIR", "JE DOIS Y ALLER", "JE DOIS PARTIR",
]


def est_message_au_revoir(text):
    """Vrai si l'eleve termine sa session ("merci, au revoir", "bonne nuit", "je m'arrete la").
    "j'ai fini" / "terminer" ne comptent pas : en mode examen, ils demandent la correction."""
    if "?" in (text or ""):
        return False
    msg = normalize_for_match(text)
    if not msg or len(msg.split()) > 10:
        return False
    return any(has_expr(msg, expr) for expr in EXPRESSIONS_AU_REVOIR)


def _session_bilan_ref(phone):
    return feedback_db.collection(SESSIONS_BILAN_COLLECTION).document(phone)


def charger_session_bilan(phone):
    try:
        snapshot = _session_bilan_ref(phone).get()
        return snapshot.to_dict() if snapshot.exists else None
    except Exception as e:
        print(f"Erreur charger_session_bilan: {repr(e)}", flush=True)
        return None


def sauver_session_bilan(phone, session):
    try:
        _session_bilan_ref(phone).set(session)
    except Exception as e:
        print(f"Erreur sauver_session_bilan: {repr(e)}", flush=True)


def fermer_session_bilan(phone, raison):
    try:
        _session_bilan_ref(phone).update({"bilan_envoye": True, "bilan_source": raison})
    except Exception as e:
        print(f"Erreur fermer_session_bilan: {repr(e)}", flush=True)


def reserver_bilan(phone, source, min_echanges=1):
    """Marque la session "bilan envoye" dans une transaction et la renvoie (None si
    rien a resumer ou si le bilan est deja parti) : un bilan n'est jamais envoye deux fois."""
    reference = _session_bilan_ref(phone)
    transaction = feedback_db.transaction()

    @firestore.transactional
    def reserver(tx):
        snapshot = reference.get(transaction=tx)
        session = snapshot.to_dict() if snapshot.exists else None
        if not session or session.get("bilan_envoye") or int(session.get("nb_echanges", 0)) < min_echanges:
            return None
        tx.update(reference, {
            "bilan_envoye": True,
            "bilan_source": source,
            "bilan_at": datetime.now(timezone.utc).isoformat(),
        })
        return session

    try:
        return reserver(transaction)
    except Exception as e:
        print(f"Erreur reserver_bilan: {repr(e)}", flush=True)
        return None


def lister_sessions_en_attente(limite=200):
    try:
        docs = (
            feedback_db.collection(SESSIONS_BILAN_COLLECTION)
            .where("bilan_envoye", "==", False)
            .limit(limite)
            .stream()
        )
        return [(doc.id, doc.to_dict() or {}) for doc in docs]
    except Exception as e:
        print(f"Erreur lister_sessions_en_attente: {repr(e)}", flush=True)
        return []


def journal_session_ajouter(phone, profile, conversation_key, mode, texte_eleve, reponse, now=None):
    """Garde le fil de la session en cours (jusqu'a 40 messages) pour le bilan de fin.
    Une nouvelle session commence apres un bilan, un changement de matiere/mode ou 30 min de pause."""
    now = now or datetime.now(timezone.utc)
    profile = profile or {}
    session = charger_session_bilan(phone)
    derniere = parse_datetime((session or {}).get("derniere_activite"))
    if (
        not session
        or session.get("bilan_envoye")
        or session.get("conversation_key") != conversation_key
        or not derniere
        or now - derniere > timedelta(minutes=SESSION_INACTIVITE_MINUTES)
    ):
        session = {"conversation_key": conversation_key, "debut": now.isoformat(), "messages": [], "nb_echanges": 0}

    messages = list(session.get("messages") or [])
    messages.append({"role": "user", "content": str(texte_eleve or "")[:1000]})
    messages.append({"role": "assistant", "content": str(reponse or "")[:1500]})
    session.update({
        "messages": messages[-SESSION_MAX_MESSAGES:],
        "nb_echanges": int(session.get("nb_echanges", 0)) + 1,
        "derniere_activite": now.isoformat(),
        "bilan_envoye": False,
        "matiere": profile.get("matiere"),
        "serie": profile.get("serie"),
        "type_examen": profile.get("type_examen"),
        "mode": mode or profile.get("mode") or "etude",
    })
    sauver_session_bilan(phone, session)
    return session


LIBELLES_MATIERES = {
    "MATHS": "Mathématiques", "PC": "Physique-Chimie", "SVT": "SVT", "FRANCAIS": "Français",
    "FRENCH": "Français", "PHILO": "Philosophie", "HG": "Histoire-Géographie", "ANGLAIS": "Anglais",
    "ALLEMAND": "Allemand", "ESPAGNOL": "Espagnol", "EDHC": "EDHC",
    "COMPTA_FIN": "Comptabilité financière", "COMPTA_SOCIETES": "Comptabilité des sociétés",
    "COMPTA_ANALYTIQUE": "Comptabilité analytique", "COMPTA": "Comptabilité",
    "MATHS_FIN": "Mathématiques financières", "MATHS_GENERAL": "Mathématiques générales",
    "ECO": "Économie", "EXPRESSION_PRO": "Expression professionnelle",
    "PHYSIQUE_APPLIQUEE": "Physique appliquée", "ESTI": "Étude des systèmes techniques industriels",
    "DROIT": "Droit",
    "MECANIQUE_APPLIQUEE": "Mécanique appliquée", "CMI": "Construction mécanique industrielle",
    "ELECTRONIQUE": "Électronique", "DESSIN_INDUSTRIEL": "Dessin industriel",
    "TECHNO_SCHEMAS": "Technologie et schémas", "MECANIQUE": "Mécanique",
    "TECHNO_GENERALE": "Technologie générale", "AUTOMATISME": "Automatisme",
    "BUREAU_METHODES": "Bureau des méthodes", "ETUDE_OUTILLAGE": "Étude d'outillage",
    "FABRICATION": "Fabrication mécanique",
    "ETUDE_FABRICATION": "Étude de fabrication", "MESURES_ESSAIS": "Mesures et essais",
    "CABLAGE": "Câblage", "TOPOGRAPHIE": "Topographie appliquée",
    "RDM": "Résistance des matériaux", "TECHNO_GENIE_CIVIL": "Technologie (génie civil)",
    "METHODES": "Méthodes", "LABO_MATERIAUX": "Laboratoire (essais des matériaux)",
    "DESSIN_GENIE_CIVIL": "Dessin technique (génie civil)", "LEGISLATION": "Législation",
    "BIOCHIMIE": "Biochimie", "MICROBIOLOGIE": "Microbiologie", "BIOLOGIE": "Biologie",
    "CHIMIE": "Chimie",
    "INFORMATIQUE_INDUSTRIELLE": "Informatique industrielle",
}


# Codes envoyes autrement a l'API (les documents de maths techniques sont sous MATHS).
CODES_MATIERE_API = {"MATHS_GENERAL": "MATHS"}


LIBELLES_EXAMENS = {
    "BAC_TECHNIQUE": "BAC Technique", "BAC_GENERAL": "BAC Général", "BEPC": "BEPC",
    "CLASSE_INTERMEDIAIRE": "classe intermédiaire",
}


LIBELLES_CLASSES_INTERMEDIAIRES = {
    "6E": "6e", "5E": "5e", "4E": "4e", "SECONDE_A": "Seconde A", "SECONDE_C": "Seconde C",
    "PREMIERE_A": "Première A", "PREMIERE_C": "Première C", "PREMIERE_D": "Première D",
}
LIBELLES_MODES = {"etude": "mode étude", "examen": "mode examen"}


def resume_profil(profile):
    """Profil en clair pour l'eleve : "BAC Technique, série F2, Seconde, Mathématiques, mode étude"."""
    profile = profile or {}
    examen = (profile.get("type_examen") or "BAC_GENERAL").upper()
    serie = str(profile.get("serie") or "").upper()
    if examen == "BAC_TECHNIQUE":
        parties = ["BAC Technique", f"série {serie}" if serie and serie != "TOUTES" else "",
                   LIBELLES_CLASSES.get(str(profile.get("classe") or "").upper(), "")]
    elif examen == "BEPC":
        parties = ["BEPC (3e)"]
    elif examen == "CLASSE_INTERMEDIAIRE":
        parties = [LIBELLES_CLASSES_INTERMEDIAIRES.get(serie, "classe intermédiaire")]
    else:
        parties = [f"BAC Général, Terminale {serie}" if serie and serie != "TOUTES" else "BAC Général"]
    mode = profile.get("mode") or "etude"
    parties += [libelle_matiere(profile.get("matiere") or "MATHS"), LIBELLES_MODES.get(mode, f"mode {mode}")]
    return ", ".join(x for x in parties if x)


def consigne_matiere_choisie(matiere, serie=None, type_examen=None, classe=None):
    """Rappelle a Akili la matiere choisie, en toutes lettres : l'API ne connait pas les
    codes des matieres techniques (CMI, RDM...) et proposait un exercice d'une autre
    matiere (chimie au lieu de construction mecanique)."""
    if not matiere:
        return ""
    examen = LIBELLES_EXAMENS.get((type_examen or "").upper(), type_examen or "")
    niveau = ", ".join(x for x in [
        examen,
        f"série {serie}" if serie and serie not in {"TOUTES", "BEPC"} else "",
        LIBELLES_CLASSES.get(str(classe or "").upper(), ""),
    ] if x)
    return (
        f"\nMATIERE CHOISIE PAR L'ELEVE : {libelle_matiere(matiere)}"
        + (f" ({niveau})" if niveau else "")
        + ". Reste strictement dans cette matière : chaque exercice, explication ou exemple que tu proposes "
        "doit porter sur cette matière, jamais sur une autre. Si l'élève envoie un sujet d'une autre matière, "
        "aide-le quand même sur ce sujet.\n"
    )


def libelle_matiere(code):
    code = (code or "").strip()
    return LIBELLES_MATIERES.get(code.upper(), code)


def generer_bilan_session(session, source):
    """Demande a Akili le bilan personnalise. En cas d'echec, message fixe selon le mode."""
    mode = (session.get("mode") or "etude").lower()
    try:
        res = requests.post(
            AKILI_BILAN_URL,
            data={
                "historique": json.dumps(session.get("messages") or [], ensure_ascii=False),
                "matiere": libelle_matiere(session.get("matiere")),
                "serie": session.get("serie") or "",
                "type_examen": session.get("type_examen") or "",
                "mode": mode,
                "source": source,
            },
            timeout=90,
        )
        data = res.json()
        texte = (data.get("reponse") or "").strip()
        if texte:
            return texte
        print(f"BILAN_SESSION reponse vide: {str(data)[:300]}", flush=True)
    except Exception as e:
        print(f"BILAN_SESSION echec: {repr(e)}", flush=True)
    if mode == "examen":
        return "Fin de ton entraînement. Bravo pour tes efforts ! Pour retravailler tes erreurs, passe en mode étude (tape menu)."
    return "Bravo pour ta séance ! Reviens quand tu veux pour continuer : envoie un exercice, une photo ou le chapitre à travailler."


# ─── AVIS DE FIN DE SEANCE : trois boutons WhatsApp ───
QUESTION_AVIS = "Akili t'a aidé aujourd'hui ?"
BOUTONS_AVIS = [("avis_oui", "Oui 👍"), ("avis_un_peu", "Un peu"), ("avis_non", "Non")]
NOTES_AVIS = {"avis_oui": "oui", "avis_un_peu": "un_peu", "avis_non": "non"}
MESSAGE_MERCI_AVIS = "Merci, ça nous fait plaisir ! Reviens quand tu veux : envoie un exercice, une photo ou le chapitre à travailler."
MESSAGE_DEMANDE_COMMENTAIRE = "Merci. En une phrase, qu'est-ce qui t'a manqué ? (ou écris passer)"
MESSAGE_MERCI_COMMENTAIRE = "Merci, ton avis est enregistré : il nous aide à améliorer Akili. Pour continuer, envoie ton exercice ou ta question."
MESSAGE_PASSER_COMMENTAIRE = "D'accord ! Pour continuer, envoie ton exercice ou ta question."
COMMENTAIRE_AVIS_MINUTES = 30
MOTS_COMMANDES = {"reset", "reinitialiser", "réinitialiser", "menu", "profil", "profile", "bonjour", "bonsoir",
                  "salut", "hello", "hi", "aide", "start", "changer"}


def send_whatsapp_boutons(to, corps, boutons):
    """Message WhatsApp avec jusqu'a 3 boutons de reponse ((id, titre de 20 caracteres max))."""
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": corps[:1024]},
            "action": {"buttons": [
                {"type": "reply", "reply": {"id": ident, "title": titre[:20]}} for ident, titre in boutons[:3]
            ]},
        },
    }
    try:
        res = requests.post(url, headers=headers, json=data, timeout=30)
        print(f"WHATSAPP_SEND_BOUTONS status={res.status_code} body={res.text[:200]}", flush=True)
        return res.status_code < 300
    except Exception as e:
        print(f"Erreur WHATSAPP_SEND_BOUTONS: {repr(e)}", flush=True)
        return False


def demander_avis_seance(phone):
    if not send_whatsapp_boutons(phone, QUESTION_AVIS, BOUTONS_AVIS):
        # Sans boutons (echec d'envoi), on garde l'ancienne ligne pour ne pas perdre l'avis.
        send_whatsapp(phone, MESSAGE_AVIS_FIN_SESSION, allow_audio=False)


def enregistrer_avis_seance(phone, note, profile=None, commentaire=None):
    """Note de la seance (oui / un_peu / non) et commentaire eventuel, dans feedback_whatsapp."""
    profile = profile or {}
    session = charger_session_bilan(phone) or {}
    try:
        feedback_db.collection("feedback_whatsapp").add({
            "phone": phone,
            "type": "commentaire_avis" if commentaire is not None else "avis_seance",
            "note": note,
            "feedback": commentaire or "",
            "matiere_detectee": session.get("matiere") or profile.get("matiere", ""),
            "serie_detectee": session.get("serie") or profile.get("serie", ""),
            "type_examen_detecte": session.get("type_examen") or profile.get("type_examen", ""),
            "mode_detecte": session.get("mode") or profile.get("mode", ""),
            "bilan_source": session.get("bilan_source", ""),
            "nb_echanges": session.get("nb_echanges", 0),
            "statut": "nouveau",
            "source": "whatsapp",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        print(f"AVIS_SEANCE note={note} commentaire={'oui' if commentaire else 'non'}", flush=True)
        return True
    except Exception as e:
        print(f"Erreur enregistrer_avis_seance: {repr(e)}", flush=True)
        return False


def traiter_bouton_avis(phone, bouton_id):
    """L'eleve a touche un bouton d'avis. Pour "Un peu" ou "Non", on lui demande pourquoi."""
    note = NOTES_AVIS.get(bouton_id)
    if not note:
        return False
    profile = charger_etat_whatsapp(phone) or user_profiles.get(phone) or {}
    enregistrer_avis_seance(phone, note, profile)
    if note == "oui":
        profile.pop("attente_commentaire_avis", None)
        send_whatsapp(phone, MESSAGE_MERCI_AVIS, allow_audio=False)
    else:
        profile["attente_commentaire_avis"] = {"note": note, "at": datetime.now(timezone.utc).isoformat()}
        send_whatsapp(phone, MESSAGE_DEMANDE_COMMENTAIRE, allow_audio=False)
    if profile:
        user_profiles[phone] = profile
        sauver_etat_whatsapp(phone, profile)
    return True


def commentaire_avis_attendu(profile, text, now=None):
    """Note en attente de commentaire, si la reponse arrive a temps et n'est pas une commande."""
    attente = (profile or {}).get("attente_commentaire_avis")
    if not attente:
        return None
    depuis = parse_datetime(attente.get("at"))
    now = now or datetime.now(timezone.utc)
    if not depuis or now - depuis > timedelta(minutes=COMMENTAIRE_AVIS_MINUTES):
        profile.pop("attente_commentaire_avis", None)
        return None
    premier_mot = (text or "").strip().lower().split(" ")[0] if (text or "").strip() else ""
    if premier_mot in MOTS_COMMANDES or prefixe_avis(text):
        profile.pop("attente_commentaire_avis", None)
        return None
    return attente.get("note") or "non"


def noter_session_bilan(phone, champs):
    try:
        _session_bilan_ref(phone).update(champs)
    except Exception as e:
        print(f"Erreur noter_session_bilan: {repr(e)}", flush=True)


# Le lendemain d'une seance, dans les 24 h ou WhatsApp autorise un message libre :
# un QCM de 2 minutes sur le point "a revoir" du bilan.
AKILI_REVISION_URL = os.environ.get("AKILI_REVISION_URL", AKILI_API_URL.rsplit("/", 1)[0] + "/revision-lendemain")
REVISION_APRES_HEURES = 18          # au plus tot 18 h apres le dernier message de l'eleve
REVISION_AVANT_HEURES = 23          # au plus tard 23 h apres (fenetre WhatsApp de 24 h)
REVISION_HEURES_ENVOI = range(7, 21)  # heure d'Abidjan (UTC) : pas de message la nuit
REVISION_MAX_PAR_TACHE = 30
MESSAGE_ARRET_REVISION = "(Écris « pas de révision » si tu ne veux plus ces petits défis.)"
COMMANDES_ARRET_REVISION = {"PAS DE REVISION", "PAS DE REVISIONS", "STOP REVISION", "STOP REVISIONS",
                            "PLUS DE REVISION", "PLUS DE REVISIONS"}
COMMANDES_REPRISE_REVISION = {"REVISIONS", "REPRENDRE LES REVISIONS", "OUI REVISION", "OUI REVISIONS"}


def cle_conversation_profil(phone, profile):
    profile = profile or {}
    return (f"{phone}:{profile.get('type_examen')}:{profile.get('serie', 'TOUTES')}:"
            f"{profile.get('matiere', 'MATHS')}:{profile.get('mode') or 'etude'}")


# La revision prevue est gardee a part : avant, elle vivait dans la fiche de la seance, et le
# moindre message apres le bilan ("merci", un avis) ouvrait une nouvelle seance qui l'effacait.
REVISIONS_COLLECTION = "whatsapp_revisions"


def _revision_ref(phone):
    return feedback_db.collection(REVISIONS_COLLECTION).document(phone)


def planifier_revision(phone, session, bilan_texte, now=None):
    """Apres un bilan : revision prevue pour le lendemain (remplace une revision plus ancienne)."""
    if not bilan_texte or int(session.get("nb_echanges", 0)) < BILAN_MIN_ECHANGES_INACTIVITE:
        return
    now = now or datetime.now(timezone.utc)
    try:
        _revision_ref(phone).set({
            "statut": "prevue",
            "prevue_le": now.isoformat(),
            "conversation_key": session.get("conversation_key"),
            "messages": list(session.get("messages") or [])[-SESSION_MAX_MESSAGES:],
            "bilan_texte": str(bilan_texte)[:2000],
            "nb_echanges": int(session.get("nb_echanges", 0)),
            "matiere": session.get("matiere"),
            "serie": session.get("serie"),
            "type_examen": session.get("type_examen"),
            "mode": session.get("mode"),
            "derniere_activite": session.get("derniere_activite") or now.isoformat(),
        })
    except Exception as e:
        print(f"Erreur planifier_revision: {repr(e)}", flush=True)


def lister_revisions_prevues(limite=500):
    try:
        docs = feedback_db.collection(REVISIONS_COLLECTION).where("statut", "==", "prevue").limit(limite).stream()
        return [(doc.id, doc.to_dict() or {}) for doc in docs]
    except Exception as e:
        print(f"Erreur lister_revisions_prevues: {repr(e)}", flush=True)
        return []


def noter_revision(phone, champs):
    try:
        _revision_ref(phone).update(champs)
    except Exception as e:
        print(f"Erreur noter_revision: {repr(e)}", flush=True)


def derniere_activite_eleve(phone, revision):
    """Dernier message de l'eleve : fin de la seance revisee, ou plus tard s'il a reecrit depuis."""
    dates = [parse_datetime(revision.get("derniere_activite"))]
    session = charger_session_bilan(phone) or {}
    dates.append(parse_datetime(session.get("derniere_activite")))
    dates = [d for d in dates if d]
    return max(dates) if dates else None


def reserver_revision(phone):
    """Passe la revision de "prevue" a "en_cours" (transaction) : jamais deux revisions pour une seance."""
    reference = _revision_ref(phone)
    transaction = feedback_db.transaction()

    @firestore.transactional
    def reserver(tx):
        snapshot = reference.get(transaction=tx)
        revision = snapshot.to_dict() if snapshot.exists else None
        if not revision or revision.get("statut") != "prevue":
            return None
        tx.update(reference, {"statut": "en_cours", "revision_at": datetime.now(timezone.utc).isoformat()})
        return revision

    try:
        return reserver(transaction)
    except Exception as e:
        print(f"Erreur reserver_revision: {repr(e)}", flush=True)
        return None


def session_eligible_revision(revision):
    return bool(
        revision.get("bilan_texte")
        and int(revision.get("nb_echanges", 0)) >= BILAN_MIN_ECHANGES_INACTIVITE
    )


def generer_revision(session, profile):
    try:
        res = requests.post(
            AKILI_REVISION_URL,
            data={
                "historique": json.dumps(session.get("messages") or [], ensure_ascii=False),
                "bilan": session.get("bilan_texte") or "",
                "matiere": libelle_matiere(session.get("matiere") or ""),
                "serie": session.get("serie") or "",
                "type_examen": session.get("type_examen") or "",
                "classe": (profile or {}).get("classe") or "",
            },
            timeout=90,
        )
        texte = (res.json().get("reponse") or "").strip()
        if not texte:
            print(f"REVISION reponse vide: {res.text[:200]}", flush=True)
        return texte
    except Exception as e:
        print(f"REVISION echec: {repr(e)}", flush=True)
        return ""


def ajouter_a_historique(conversation_key, texte):
    """La revision entre dans l'historique : la reponse de l'eleve sera corrigee dans ce contexte."""
    historique = charger_historique_conv(conversation_key)
    if historique is None:
        historique = list(conversations.get(conversation_key) or [])
    historique = list(historique) + [{"role": "assistant", "content": texte}]
    conversations[conversation_key] = historique[-10:]
    sauver_historique_conv(conversation_key, conversations[conversation_key])


def traiter_revisions_lendemain(now=None):
    now = now or datetime.now(timezone.utc)
    if now.hour not in REVISION_HEURES_ENVOI:
        return {"revisions": 0}
    prevues = lister_revisions_prevues()
    envoyees = dans_fenetre = 0
    for phone, revision in prevues:
        if envoyees >= REVISION_MAX_PAR_TACHE:
            break
        fin_seance = parse_datetime(revision.get("derniere_activite"))
        if fin_seance and now - fin_seance < timedelta(hours=REVISION_APRES_HEURES):
            continue  # trop tot (et l'eleve n'a pas pu ecrire avant la fin de sa seance)
        derniere = derniere_activite_eleve(phone, revision)
        if not derniere or now - derniere > timedelta(hours=REVISION_AVANT_HEURES):
            noter_revision(phone, {"statut": "expiree"})  # hors de la fenetre WhatsApp de 24 h
            continue
        if now - derniere < timedelta(hours=REVISION_APRES_HEURES):
            continue  # l'eleve a reecrit depuis : on attend 18 h apres son dernier message
        if not session_eligible_revision(revision):
            noter_revision(phone, {"statut": "ignoree"})
            continue
        dans_fenetre += 1
        profile = charger_etat_whatsapp(phone) or {}
        # Pas de revision si l'eleve l'a refusee, ou s'il a change de matiere ou de mode depuis.
        if profile.get("revisions_off") or cle_conversation_profil(phone, profile) != revision.get("conversation_key"):
            noter_revision(phone, {"statut": "ignoree"})
            continue
        if not reserver_revision(phone):
            continue
        texte = generer_revision(revision, profile)
        if not texte:
            noter_revision(phone, {"statut": "echec"})
            continue
        user_profiles[phone] = profile
        send_whatsapp(phone, f"{texte}\n\n{MESSAGE_ARRET_REVISION}", allow_audio=False)
        ajouter_a_historique(revision.get("conversation_key"), texte)
        noter_revision(phone, {"statut": "envoyee"})
        envoyees += 1
        print(f"REVISION_LENDEMAIN envoyee matiere={revision.get('matiere')}", flush=True)
    print(f"REVISION_TACHE prevues={len(prevues)} dans_fenetre={dans_fenetre} envoyees={envoyees}", flush=True)
    return {"revisions": envoyees}


def envoyer_fin_de_session(phone, source="au_revoir"):
    min_echanges = 1 if source == "au_revoir" else BILAN_MIN_ECHANGES_INACTIVITE
    session = reserver_bilan(phone, source, min_echanges=min_echanges)
    if not session:
        if source == "au_revoir":
            send_whatsapp(phone, MESSAGE_AU_REVOIR_SIMPLE, allow_audio=False)
        return False
    texte = generer_bilan_session(session, source)
    send_whatsapp(phone, texte, allow_audio=False)
    noter_session_bilan(phone, {"bilan_texte": texte[:2000]})
    planifier_revision(phone, session, texte)
    demander_avis_seance(phone)
    print(f"FIN_SESSION envoyee source={source} echanges={session.get('nb_echanges')}", flush=True)
    return True


def traiter_bilans_inactivite(now=None):
    """Appele par Cloud Scheduler : bilan pour chaque session en pause depuis 30 min."""
    now = now or datetime.now(timezone.utc)
    envoyes = fermees = 0
    for phone, session in lister_sessions_en_attente():
        if envoyes >= BILAN_MAX_PAR_TACHE:
            break
        derniere = parse_datetime(session.get("derniere_activite"))
        if not derniere:
            continue
        pause = now - derniere
        if pause < timedelta(minutes=SESSION_INACTIVITE_MINUTES):
            continue
        if (
            pause > timedelta(hours=SESSION_FENETRE_WHATSAPP_HEURES)
            or int(session.get("nb_echanges", 0)) < BILAN_MIN_ECHANGES_INACTIVITE
        ):
            fermer_session_bilan(phone, "fermee_sans_bilan")
            fermees += 1
            continue
        if envoyer_fin_de_session(phone, source="inactivite"):
            envoyes += 1
    return {"envoyes": envoyes, "fermees": fermees}


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

    if prefixe_avis(command):
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

    last_assistant = load_last_assistant_context(phone)
    if best_items:
        lines = []
        for item in best_items[-max_items:]:
            role = item.get("role", "")
            content = item.get("content", "")
            if content:
                lines.append(f"{role}: {content}")
        if last_assistant and not any(last_assistant.strip() in str(i.get("content", "")) for i in best_items[-max_items:]):
            lines.append(f"assistant: {last_assistant}")
        if lines:
            return "\n".join(lines)

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
    # Akili vient de poser une question (calcul, definition...) : la reponse courte s'y rattache.
    derniere = load_last_assistant_context(phone)
    if derniere and "?" in derniere[-300:]:
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


MESSAGE_SUJET_INDISPONIBLE = (
    "Je n'ai plus le sujet de cet exercice. Renvoie-moi la photo du sujet ou recopie l'énoncé, "
    "et je continue avec toi."
)


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

    if any(marker in compact for marker in document_markers):
        return True

    # Un énoncé recopié peut lui-même commencer par « EXERCICE 1 ». Une
    # référence courte doit réutiliser le document; un texte substantiel doit
    # être traité directement comme l'énoncé fourni par l'élève.
    return len(compact.split()) <= 12 and any(marker in compact for marker in exercise_refs)


def is_short_pedagogical_answer(text):
    """Reconnaît les réponses minimales attendues par un QCM/une étape guidée."""
    compact = normalize_for_match(text or "").strip()
    choice = r"(?:[A-L0-9]|VRAI|FAUX|OUI|NON)"
    if re.fullmatch(rf"\(?\s*{choice}\s*\)?[.)]?", compact):
        return True
    return bool(re.fullmatch(
        rf"(?:LA|MA) REPONSE (?:CORRECTE )?EST {choice}|"
        rf"JE PENSE QUE (?:CETTE|LA) REPONSE EST {choice}",
        compact,
    ))


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

    # Toujours relire Firestore : la memoire de cette copie Cloud Run peut etre perimee
    # (reset ou nouveaux echanges traites par une autre copie).
    hist_sauve = charger_historique_conv(conversation_key)
    if hist_sauve is not None:
        conversations[conversation_key] = list(hist_sauve)
        print(f"HISTORIQUE recharge depuis Firestore: {len(hist_sauve)} messages", flush=True)

    if message_id:
        send_whatsapp_typing_indicator(message_id)

    # Ce que l'eleve a vraiment tape. Pour une reponse courte ("b"), `text` a ete
    # reecrit par build_short_answer_prompt (consignes + historique) : la detection
    # "l'eleve parle d'un document" et l'historique doivent porter sur "b", pas sur
    # ce prompt, sinon une simple lettre est prise pour une demande sur un fichier
    # et l'historique s'imbrique a chaque reponse courte.
    texte_eleve = text
    marqueur_reponse_courte = "vient de répondre uniquement : "
    if text.startswith("L'") and marqueur_reponse_courte in text[:80]:
        texte_eleve = text.split(marqueur_reponse_courte, 1)[1].split("\n", 1)[0]

    if media_file is None and mentions_user_document_without_content(texte_eleve):
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

    if mentions_user_document_without_content(texte_eleve) and media_file is None and not profile.get("last_document_text"):
        send_whatsapp(
            phone,
            MESSAGE_SUJET_INDISPONIBLE
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
            classe=profile.get("classe"),
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
            texte_eleve,
            reponse,
            message_id,
            **transition_details,
        )
        if not save_active_session_if_revision(phone, next_active_session, expected_revision):
            print(f"P0: conflit de révision pour {phone}, réponse non renvoyée", flush=True)
            return None

    conversations[conversation_key].append({"role": "user", "content": texte_eleve})
    conversations[conversation_key].append({"role": "assistant", "content": reponse})
    conversations[conversation_key] = conversations[conversation_key][-10:]
    sauver_historique_conv(conversation_key, conversations[conversation_key])
    journal_session_ajouter(phone, profile, conversation_key, mode, texte_eleve, reponse)

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
    for serie in ["A1", "A2", "C", "D", "A"]:
        patterns = [
            f"SERIE {serie}", f"TERMINALE {serie}", f"TERMINAL {serie}",
            f"TLE {serie}", f"1ERE {serie}", f"PREMIERE {serie}",
            f"SECONDE {serie}", f"2NDE {serie}",
        ]
        if any(has_expr(msg, pat) for pat in patterns):
            profile["serie"] = serie
            break

    # Detecte les series techniques avant les matieres.
    for serie in ["G1", "G2", "E", "F1", "F2", "F3", "F4", "F7", "B"]:
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

    if serie in {"B", "G1", "G2", "E", "F1", "F2", "F3", "F4", "F7", "STI"}:
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
    """Supprime les phrases d'accroche/compliment en debut de reponse (garde-fou code, en plus du prompt).

    Seules les phrases d'accroche du debut sont retirees : le reste du texte est garde
    tel quel, retours a la ligne compris. (L'ancienne version recollait toutes les
    phrases avec des espaces, ce qui cassait les listes : "... precedentes. 2. Reponse".)
    """
    text = str(text or "").strip()
    if not text:
        return text

    reste = text
    while reste:
        fin_phrase = re.search(r"[.!?](?=\s)", reste)
        premiere = reste[:fin_phrase.end()] if fin_phrase else reste

        first_norm = normalize_for_match(premiere)
        words = first_norm.split()

        # Une validation de reponse ("C'est une tres bonne reponse !", "Exact.") n'est
        # pas une accroche : l'eleve doit savoir que sa reponse est juste.
        est_validation = any(kw in first_norm for kw in ("REPONSE", "CORRECT", "EXACT", "JUSTE"))

        is_bare_greeting = bool(words) and words[0] in FILLER_GREETING_WORDS and len(words) <= 4
        is_filler_sentence = any(kw in first_norm for kw in FILLER_OPENING_KEYWORDS)

        if est_validation or not (is_bare_greeting or is_filler_sentence):
            break
        if not fin_phrase:
            return text  # tout le message est une accroche : on le garde tel quel
        reste = reste[fin_phrase.end():].lstrip()

    return reste if reste else text


def get_akili_response(question, matiere, serie, history, phone="whatsapp_user", type_examen=None,
                       mode=None, media_file=None, user_type=None, raise_on_error=False,
                       return_details=False, active_session=None, classe=None):
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
        short_answer_instruction = (
            "REPONSE COURTE DE L'ELEVE: ce message est une réponse à la dernière "
            "question pédagogique de l'historique. Aucun nouveau fichier ni aucune "
            "nouvelle image n'est joint. Interprète cette réponse dans l'exercice en "
            "cours et ne demande jamais de renvoyer un fichier.\n\n"
            if media_file is None and is_short_pedagogical_answer(question) else ""
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
            "- Tutoie TOUJOURS l'élève (tu, ton, ta, tes). N'utilise jamais le vouvoiement (vous, votre, souhaitez-vous), sauf si l'utilisateur est un enseignant.\n"
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
        instructions_whatsapp += consigne_matiere_choisie(matiere, serie, type_examen, classe)

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
                f"{short_answer_instruction}"
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
                f"{short_answer_instruction}"
                f"HISTORIQUE RECENT:\n{contexte}\n\n"
                f"QUESTION REELLE DE L'ELEVE:\n{question}"
            )
        else:
            question_api = (
                f"{instructions_whatsapp}\n"
                f"{format_guard}"
                f"{active_context_instruction}"
                f"{short_answer_instruction}"
                f"QUESTION REELLE DE L'ELEVE:\n{question}"
            )

        payload = {
            "email": f"{phone}@afrjigi.com",
            "question": question_api,
            "question_brute": question,
            "matiere": CODES_MATIERE_API.get(matiere, matiere),
            "serie": serie,
            "type_examen": type_examen,
            "mode": mode,
            # L'API Akili attend un tableau JSON et ignorait auparavant ce champ
            # parce qu'elle recevait une chaîne déjà mise en forme.
            "history": json.dumps(history[-6:], ensure_ascii=False),
            "user_type": user_type or "",
            "classe": classe or "",
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


@app.post("/taches/sante")
async def tache_sante(request: Request):
    """Appele toutes les heures par Cloud Scheduler, avec l'en-tete X-Akili-Tache."""
    import hmac
    secret = os.environ.get("TACHES_SECRET", "")
    if not secret or not hmac.compare_digest(secret, request.headers.get("X-Akili-Tache", "")):
        return JSONResponse(status_code=403, content={"status": "forbidden"})
    return verifier_sante()


@app.get("/tableau-de-bord")
async def page_tableau_de_bord(request: Request):
    """Tableau de bord du jour. Adresse : /tableau-de-bord?cle=<TABLEAU_CLE>."""
    import hmac
    cle = os.environ.get("TABLEAU_CLE", "")
    if not cle or not hmac.compare_digest(cle, request.query_params.get("cle", "")):
        return PlainTextResponse("Accès refusé", status_code=403)
    now = datetime.now(timezone.utc)
    if not _cache_tableau["at"] or now - _cache_tableau["at"] > timedelta(minutes=TABLEAU_CACHE_MINUTES):
        _cache_tableau.update({"at": now, "page": construire_tableau(now)})
    return HTMLResponse(_cache_tableau["page"], headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})


@app.post("/taches/bilans-inactivite")
async def tache_bilans_inactivite(request: Request):
    """Appele toutes les 10 min par Cloud Scheduler, avec l'en-tete X-Akili-Tache."""
    import hmac
    secret = os.environ.get("TACHES_SECRET", "")
    fourni = request.headers.get("X-Akili-Tache", "")
    if not secret or not hmac.compare_digest(secret, fourni):
        return JSONResponse(status_code=403, content={"status": "forbidden"})
    resultat = traiter_bilans_inactivite()
    try:
        resultat.update(traiter_revisions_lendemain())
    except Exception as e:
        print(f"Erreur traiter_revisions_lendemain: {repr(e)}", flush=True)
    print(f"TACHE_BILANS_INACTIVITE {resultat}", flush=True)
    return {"status": "ok", **resultat}


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


SANTE_COLLECTION = "sante"
SEUIL_ECHECS_JOUR = 20


def compter_echec_livraison(now=None):
    jour = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    try:
        feedback_db.collection(SANTE_COLLECTION).document(f"echecs_{jour}").set(
            {"jour": jour, "nombre": firestore.Increment(1)}, merge=True)
    except Exception as e:
        print(f"Erreur compter_echec_livraison: {repr(e)}", flush=True)


def lire_echecs_jour(now=None):
    jour = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    try:
        doc = feedback_db.collection(SANTE_COLLECTION).document(f"echecs_{jour}").get()
        return int((doc.to_dict() or {}).get("nombre", 0)) if doc.exists else 0
    except Exception as e:
        print(f"Erreur lire_echecs_jour: {repr(e)}", flush=True)
        return 0


def _verifier(nom, fonction):
    try:
        ok, detail = fonction()
    except Exception as e:
        ok, detail = False, f"{type(e).__name__}: {str(e)[:160]}"
    return {"nom": nom, "ok": bool(ok), "detail": detail}


def _sante_firestore():
    now = datetime.now(timezone.utc).isoformat()
    ref = feedback_db.collection(SANTE_COLLECTION).document("ping")
    ref.set({"at": now})
    lu = (ref.get().to_dict() or {}).get("at")
    return lu == now, "lecture et écriture"


def _sante_api():
    base = AKILI_API_URL.rsplit("/", 1)[0]
    accueil = requests.get(base + "/", timeout=30).json()
    nb = int(accueil.get("documents", 0))
    if nb < 1000:
        return False, f"seulement {nb} documents chargés"
    gemini = requests.get(base + "/sante", timeout=60).json()
    if gemini.get("gemini") != "ok":
        return False, f"Gemini ne répond pas ({gemini.get('detail', '')})"
    return True, f"{nb} documents, Gemini répond"


def _sante_whatsapp():
    def lire(champs):
        res = requests.get(
            f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}",
            params={"fields": champs},
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}, timeout=30,
        )
        return res, res.json()

    res, data = lire("quality_rating,health_status,messaging_limit_tier")
    if res.status_code >= 300 and (data.get("error") or {}).get("code") == 100:
        # Champ health_status inconnu pour cette version de l'API : on verifie sans lui.
        res, data = lire("quality_rating,messaging_limit_tier")
    if res.status_code >= 300:
        return False, f"Meta refuse l'accès : {(data.get('error') or {}).get('message', res.status_code)}"
    etat = (data.get("health_status") or {}).get("can_send_message", "AVAILABLE")
    qualite = data.get("quality_rating", "?")
    if etat != "AVAILABLE":
        erreurs = [
            str(err.get("error_description") or err.get("possible_solution") or err.get("error_code"))
            for entite in (data.get("health_status") or {}).get("entities", [])
            for err in entite.get("errors", [])
        ]
        # Les appels WhatsApp (SIP) non configures rendent l'etat LIMITED, mais les messages
        # partent normalement : ce n'est pas une panne d'Akili.
        if etat == "LIMITED" and erreurs and all(
                re.search(r"\bSIP\b|CALLING", e, flags=re.I) for e in erreurs):
            return True, f"envoi possible, qualité {qualite} (appels WhatsApp non configurés, sans effet sur les messages)"
        return False, f"envoi {etat} : {'; '.join(erreurs)[:200]}"
    if qualite == "RED":
        return False, "note de qualité Meta : ROUGE"
    return True, f"envoi possible, qualité {qualite}"


def _sante_livraison():
    nb = lire_echecs_jour()
    return nb <= SEUIL_ECHECS_JOUR, f"{nb} message(s) non livré(s) aujourd'hui"


def verifier_sante():
    """Verifications toutes les heures : resultat dans Firestore et une ligne SANTE_OK / SANTE_ECHEC
    dans les journaux (l'alerte e-mail se declenche sur SANTE_ECHEC)."""
    verifications = [
        _verifier("Base de données (Firestore)", _sante_firestore),
        _verifier("API Akili et Gemini", _sante_api),
        _verifier("WhatsApp (Meta)", _sante_whatsapp),
        _verifier("Livraison des messages", _sante_livraison),
    ]
    resultat = {"at": datetime.now(timezone.utc).isoformat(), "ok": all(v["ok"] for v in verifications),
                "verifications": verifications}
    try:
        feedback_db.collection(SANTE_COLLECTION).document("derniere").set(resultat)
    except Exception as e:
        print(f"Erreur sauvegarde sante: {repr(e)}", flush=True)
    if resultat["ok"]:
        print("SANTE_OK", flush=True)
    else:
        echecs = " | ".join(f"{v['nom']} : {v['detail']}" for v in verifications if not v["ok"])
        print(f"SANTE_ECHEC {echecs}", flush=True)
    return resultat


# ─── Tableau de bord (page web protegee par une cle) ───
_cache_tableau = {"at": None, "page": None}
TABLEAU_CACHE_MINUTES = 10


def _flux(requete, champs):
    try:
        return [d.to_dict() or {} for d in requete.select(champs).stream()]
    except Exception as e:
        print(f"Erreur tableau de bord: {repr(e)}", flush=True)
        return []


def construire_tableau(now=None):
    now = now or datetime.now(timezone.utc)
    debut = (now - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    aujourd_hui = now.strftime("%Y-%m-%d")
    messages = _flux(feedback_db.collection("whatsapp_messages").where("created_at", ">=", debut),
                     ["phone", "direction", "created_at", "matiere"])
    avis = _flux(feedback_db.collection("feedback_whatsapp").where("created_at", ">=", debut),
                 ["type", "note", "feedback", "statut", "matiere_detectee", "created_at"])
    revisions = _flux(feedback_db.collection(REVISIONS_COLLECTION).where("revision_at", ">=", aujourd_hui),
                      ["statut"])
    qualite = None
    for jour in [aujourd_hui, (now - timedelta(days=1)).strftime("%Y-%m-%d")]:
        lignes = _flux(feedback_db.collection("controle_qualite").where("jour", "==", jour), ["note", "problemes"])
        notes = [l["note"] for l in lignes if isinstance(l.get("note"), (int, float))]
        if notes:
            graves = sum(1 for l in lignes for p in (l.get("problemes") or []) if p.get("gravite") == "grave")
            qualite = {"jour": jour, "moyenne": round(sum(notes) / len(notes), 1), "nb": len(notes), "graves": graves}
            break
    try:
        doc = feedback_db.collection(SANTE_COLLECTION).document("derniere").get()
        sante = doc.to_dict() if doc.exists else None
    except Exception:
        sante = None
    stats = tableau_de_bord.calculer_stats(messages, avis, now)
    return tableau_de_bord.rendre_html(
        stats, sante=sante, echecs_jour=lire_echecs_jour(now), qualite=qualite,
        revisions_jour=sum(1 for r in revisions if r.get("statut") == "envoyee"),
        genere_le=now.strftime("%d/%m/%Y %H:%M"), libelle=libelle_matiere,
    )


def journaliser_statuts_whatsapp(statuts):
    """Meta confirme chaque envoi (sent, delivered, read) ou signale un echec ("failed").
    Un envoi accepte (statut 200) peut quand meme ne jamais arriver : seul ce retour le dit."""
    for statut in statuts:
        try:
            if statut.get("status") != "failed":
                continue
            compter_echec_livraison()
            for erreur in statut.get("errors") or [{}]:
                details = (erreur.get("error_data") or {}).get("details", "")
                print(
                    f"WHATSAPP_STATUS_FAILED recipient={statut.get('recipient_id')} "
                    f"code={erreur.get('code')} title={erreur.get('title')} details={details}",
                    flush=True,
                )
        except Exception as e:
            print(f"Erreur journaliser_statuts_whatsapp: {repr(e)}", flush=True)


@app.post("/whatsapp/webhook")
async def receive_message(request: Request):
    """Traite le message puis sauve le profil complet dans Firestore : la copie Cloud Run
    qui recevra le message suivant repartira de cet etat, pas d'une memoire perimee."""
    jeton = _profil_charge_requete.set(None)
    try:
        return await _receive_message_impl(request)
    finally:
        phone = _profil_charge_requete.get()
        _profil_charge_requete.reset(jeton)
        if phone:
            profil = user_profiles.get(phone)
            if profil:  # vide apres un reset : rien a sauver
                sauver_etat_whatsapp(phone, profil)


async def _receive_message_impl(request: Request):
    body = await request.json()

    try:
        valeur = body["entry"][0]["changes"][0]["value"]
        journaliser_statuts_whatsapp(valeur.get("statuses") or [])
        messages = valeur.get("messages", [])
        if not messages:
            return {"status": "ok"}

        msg = messages[0]
        phone = msg["from"]
        msg_type = msg.get("type")
        text = msg.get("text", {}).get("body", "").strip()
        template_text = retention_template_text(msg)
        if msg_type == "button":
            if template_text is None:
                return {"status": "ok", "reason": "bouton_modele_inconnu"}
            text = template_text
        bouton_id = ((msg.get("interactive") or {}).get("button_reply") or {}).get("id") if msg_type == "interactive" else None
        message_id = msg.get("id")
        if message_id and (message_id in processed_messages or not reserver_message_whatsapp(message_id)):
            print(f"Message déjà traité: {message_id}", flush=True)
            return {"status": "ok", "reason": "duplicate"}
        if message_id:
            processed_messages.add(message_id)
        media_file = None
        document_context = None
        media_info = None
        legende = ""
        try:
            recu_le = datetime.fromtimestamp(int(msg.get("timestamp")), timezone.utc).isoformat()
        except (TypeError, ValueError):
            recu_le = datetime.now(timezone.utc).isoformat()
        incoming_was_audio = msg_type in {"audio", "voice"}
        audio_reply_context[phone] = incoming_was_audio
        print(f"WHATSAPP_AUDIO_REPLY incoming_was_audio={incoming_was_audio} msg_type={msg_type}", flush=True)

        if msg_type in {"document", "image", "audio", "voice"}:
            media_key = "audio" if msg_type == "voice" else msg_type
            media = msg.get(media_key, {})
            media_id = media.get("id")
            caption = (media.get("caption") or "").strip()
            legende = caption
            filename = media.get("filename") or f"whatsapp_{msg_type}"
            fallback_mime = media.get("mime_type") or (
                "audio/ogg" if msg_type == "audio" else
                "image/jpeg" if msg_type == "image" else
                "application/pdf"
            )

            if media_id:
                if msg_type in {"document", "image"}:
                    media_info = {"media_id": media_id, "filename": filename, "mime_type": fallback_mime}
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

        if message_id:
            send_whatsapp_typing_indicator(message_id)

        if bouton_id in {pedagogical.YES, pedagogical.NO}:
            decision = OPTED_IN if bouton_id == pedagogical.YES else pedagogical.OPTED_OUT
            try:
                saved = pedagogical.save_decision(feedback_db, phone, decision)
            except Exception:
                if message_id:
                    processed_messages.discard(message_id)
                    liberer_message_whatsapp(message_id)
                return JSONResponse(status_code=503, content={"status": "retry", "reason": "pedagogical_consent_persistence_failed"})
            if not saved:
                return {"status": "ok", "reason": "pedagogical_prompt_missing"}
            send_whatsapp(phone,
                "Ton accord est enregistré pour les bilans, rappels d’exercices et quiz. Pour arrêter, écris STOP."
                if decision == OPTED_IN else
                "D’accord, tu ne recevras pas ces rappels. Tu peux continuer à utiliser Akili.",
                persist_event=False, allow_audio=False)
            return {"status": "ok", "reason": "pedagogical_" + decision}

        if bouton_id:
            if traiter_bouton_avis(phone, bouton_id):
                return {"status": "ok", "reason": "avis_seance"}
            if traiter_bouton_mode(phone, bouton_id):
                return {"status": "ok", "reason": "choix_mode"}
            return {"status": "ok", "reason": "bouton_inconnu"}

        if len(processed_messages) > 1000:
            processed_messages.clear()

        if not text:
            return {"status": "ok"}

        # Ce qui est garde dans le journal : le message tel que l'eleve l'a envoye.
        if media_info:
            texte_journal = f"[{'photo' if msg_type == 'image' else 'document'}] {legende}".strip()
        elif incoming_was_audio:
            texte_journal = f"[audio] {text}"
        else:
            texte_journal = text

        consent_decision = detect_marketing_consent_command(text)
        if consent_decision:
            try:
                if consent_decision == pedagogical.OPTED_OUT:
                    pedagogical.save_decision(feedback_db, phone, consent_decision, require_prompt=False)
                save_marketing_consent(feedback_db, phone, consent_decision)
            except Exception as exc:
                if message_id:
                    processed_messages.discard(message_id)
                    liberer_message_whatsapp(message_id)
                print(
                    "WHATSAPP_MARKETING_CONSENT save_failed "
                    f"error_class={type(exc).__name__}",
                    flush=True,
                )
                return JSONResponse(
                    status_code=503,
                    content={
                        "status": "retry",
                        "reason": "marketing_consent_persistence_failed",
                    },
                )

            if consent_decision == OPTED_IN:
                send_whatsapp(
                    phone,
                    "Ton accord est enregistré. Tu peux recevoir les campagnes WhatsApp "
                    "d'AfrJigi. Pour te désinscrire à tout moment, envoie STOP.",
                    persist_event=False,
                    allow_audio=False,
                )
                reason = "marketing_opted_in"
            else:
                send_whatsapp(
                    phone,
                    "Ta désinscription est enregistrée. Tu ne recevras plus de rappels ni "
                    "de campagnes WhatsApp d’AfrJigi. Tu peux continuer à utiliser Akili.",
                    persist_event=False,
                    allow_audio=False,
                )
                reason = "marketing_opted_out"
            print(f"WHATSAPP_MARKETING_CONSENT status={consent_decision}", flush=True)
            return {"status": "ok", "reason": reason}

        maybe_send_marketing_consent_prompt(phone)

        print(f"Message de {phone}: {text}", flush=True)

        etat_firestore = charger_etat_whatsapp(phone)
        if phone in _etat_lecture_echouee:
            profile = user_profiles[phone] or etat_firestore or {"serie": "TOUTES", "matiere": "MATHS"}
        else:
            profile = etat_firestore or {"serie": "TOUTES", "matiere": "MATHS"}
        user_profiles[phone] = profile
        _profil_charge_requete.set(phone)

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
                texte_journal,
                after,
                message_id,
                extra={
                    "created_at": recu_le,
                    "texte_traite": text[:1000] if text != texte_journal else "",
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
        if normalize_for_match(text) in COMMANDES_ARRET_REVISION | COMMANDES_REPRISE_REVISION:
            arret = normalize_for_match(text) in COMMANDES_ARRET_REVISION
            profile["revisions_off"] = arret
            user_profiles[phone] = profile
            send_whatsapp(phone, (
                "C'est noté, je ne t'enverrai plus de défi de révision. Écris « révisions » pour les retrouver."
                if arret else
                "C'est noté : je t'enverrai un petit défi de révision le lendemain de tes séances."
            ), allow_audio=False)
            track_inbound("revisions_off" if arret else "revisions_on", profile)
            return {"status": "ok", "reason": "revisions_off" if arret else "revisions_on"}

        if not onboarding_step and is_profile_ready(profile) and media_file is None \
                and proposer_mode_etude(phone, profile, text):
            user_profiles[phone] = profile
            track_inbound("offre_mode_etude", profile)
            return {"status": "ok", "reason": "offre_mode_etude"}

        note_en_attente = commentaire_avis_attendu(profile, text)
        if note_en_attente:
            profile.pop("attente_commentaire_avis", None)
            user_profiles[phone] = profile
            if normalize_for_match(text) in {"PASSER", "PASSE", "NON", "RIEN", "NON MERCI"}:
                send_whatsapp(phone, MESSAGE_PASSER_COMMENTAIRE, allow_audio=False)
            else:
                enregistrer_avis_seance(phone, note_en_attente, profile, commentaire=text[:1000])
                send_whatsapp(phone, MESSAGE_MERCI_COMMENTAIRE, allow_audio=False)
            track_inbound("commentaire_avis", profile)
            return {"status": "ok", "reason": "commentaire_avis"}

        avis = prefixe_avis(text)
        if avis and not onboarding_step and retour_est_une_reponse(avis[0], avis[1], load_last_assistant_context(phone)):
            # On garde une copie a verifier, et la reponse part chez Akili comme les autres.
            save_feedback_whatsapp(phone, avis[1], profile, text, statut="a_verifier", type_avis="retour_ambigu")
            print("RETOUR_AMBIGU traite comme reponse a l'exercice", flush=True)
            text = avis[1]
            original_text = text
            command = text.strip().lower()

        if not onboarding_step and is_profile_ready(profile) and est_message_au_revoir(text):
            envoyer_fin_de_session(phone, source="au_revoir")
            track_inbound("fin_session_au_revoir", profile)
            return {"status": "ok", "reason": "fin_session"}

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
            effacer_traces_conversation(phone)
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

        if prefixe_avis(text):
            profile = user_profiles.get(phone, {})
            feedback_text = prefixe_avis(text)[1]
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
            # Au milieu de l'inscription, "bonjour" ne fait pas tout recommencer :
            # on repose la question en cours ("reset" reste la commande pour repartir de zero).
            if profile.get("onboarding_step") in ETAPES_A_REPOSER | {"ville", "nom_ecole"}:
                send_whatsapp(phone, MESSAGE_REPRISE_INSCRIPTION)
                reposer_question_onboarding(phone, profile)
                track_inbound("welcome_onboarding_resumed", profile)
                return {"status": "ok", "reason": "onboarding_resumed"}
            profile["onboarding_step"] = "exam"
            user_profiles[phone] = profile
            ask_exam(phone)
            track_inbound("welcome_onboarding_started", profile)
            return {"status": "ok"}

        if command in {"menu", "menu akili", "tape menu", "taper menu", "tapez menu", "menu."}:
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
            effacer_traces_conversation(phone)
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

        if profile.get("onboarding_step") == "matiere" and veut_plusieurs_matieres(text):
            send_whatsapp(phone, MESSAGE_UNE_MATIERE_A_LA_FOIS)
            track_inbound("multiple_subjects_requested", profile)
            return {"status": "ok", "reason": "multiple_subjects_requested"}

        if profile.get("onboarding_step") and is_multiple_choice_answer(text):
            send_whatsapp(phone, "Choisis une seule option pour continuer. Exemple : a")
            track_inbound("multiple_choice_rejected", profile)
            return {"status": "ok"}

        if command in {"profil", "profile"}:
            send_whatsapp(
                phone,
                f"Profil actuel : {resume_profil(profile)}."
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
                pending_media = profile_after_choice.pop("pending_media", None)
                profile_after_choice = mark_profile_ready_if_complete(profile_after_choice)
                user_profiles[phone] = profile_after_choice
                media_reprise, contexte_reprise = recuperer_media_garde(pending_media)
                if media_reprise:
                    send_whatsapp(phone, "Je reprends ton exercice en photo.")
                else:
                    send_whatsapp(phone, f"Je reprends ta question : {pending_question_display}")
                answer_learning_request(phone, profile_after_choice, pending_question,
                                        media_file=media_reprise, document_context=contexte_reprise)
                track_inbound("pending_question_answered", profile_after_choice)

            return {"status": "ok"}

        if is_learning_request(text) and not is_profile_ready(profile) and not is_teacher_request(text):
            if profile.get("type_examen") == "AUTRE" or profile.get("serie") == "AUTRE":
                profile = repartir_premiere_question(profile)
            profile["pending_question"] = text
            profile["pending_question_display"] = original_text
            if media_info:
                profile["pending_media"] = media_info
            etape_en_cours = profile.get("onboarding_step")
            if etape_en_cours not in ETAPES_A_REPOSER | {"ville", "nom_ecole"}:
                profile["onboarding_step"] = etape_en_cours = "exam"
            user_profiles[phone] = profile
            garde = "ta photo et ta question" if media_info else f"ta question : {original_text}"
            send_whatsapp(
                phone,
                "Avant de répondre, je dois connaître ton profil pour bien t'aider.\n\n"
                f"J'ai gardé {garde}. Réponds d'abord à cette question :"
            )
            reposer_question_onboarding(phone, profile)
            track_inbound("forced_onboarding_pending_question", profile)
            return {"status": "ok"}

        profile = update_profile_from_text(profile, text)
        normalize_onboarding_state(profile)
        user_profiles[phone] = profile

        if profile.get("serie") == "AUTRE" or profile.get("type_examen") == "AUTRE":
            profile = repartir_premiere_question(profile)
            user_profiles[phone] = profile
            send_whatsapp(phone, MESSAGE_HORS_CHAMP)
            ask_exam(phone)
            track_inbound("unsupported_exam", profile)
            return {"status": "ok"}

        if needs_onboarding(phone, profile, text):
            if is_learning_request(text):
                profile_waiting = user_profiles.get(phone, profile)
                profile_waiting["pending_question"] = text
                profile_waiting["pending_question_display"] = original_text
                if media_info:
                    profile_waiting["pending_media"] = media_info
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
