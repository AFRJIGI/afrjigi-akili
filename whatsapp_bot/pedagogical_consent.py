"""Consentement limité aux rappels pédagogiques, indépendant des promotions."""
from datetime import datetime, timezone
import uuid
from marketing_consent import consent_document_id, OPTED_IN, OPTED_OUT, UNKNOWN

COLLECTION = "whatsapp_pedagogical_consent"
SCOPE = "weekly_summary_exercises_quizzes"
VERSION = 1
YES = "pedagogical_consent_v1_yes"
NO = "pedagogical_consent_v1_no"
PROMPT = (
    "Souhaites-tu recevoir sur WhatsApp ton bilan de la semaine, des rappels "
    "d’exercices et de petits quiz avec Akili ?\n\n"
    "Tu peux arrêter ces messages à tout moment avec « Se désinscrire » "
    "ou en écrivant STOP."
)
BUTTONS = [(YES, "Oui, je souhaite"), (NO, "Non merci")]


def classify(record):
    if not isinstance(record, dict):
        return UNKNOWN
    if record.get("consent_status") == OPTED_OUT:
        return OPTED_OUT
    if (record.get("consent_status") == OPTED_IN
            and record.get("scope") == SCOPE
            and record.get("notice_version") == VERSION
            and record.get("source") == "whatsapp_explicit_button"):
        return OPTED_IN
    return UNKNOWN


def reference(client, phone):
    return client.collection(COLLECTION).document(consent_document_id(phone))


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def claim_prompt(client, phone):
    # Firestore transaction: ne pas inviter deux fois, ni effacer un refus.
    from google.cloud import firestore
    ref = reference(client, phone)
    claim = uuid.uuid4().hex

    @firestore.transactional
    def reserve(tx):
        snapshot = ref.get(transaction=tx)
        record = snapshot.to_dict() or {} if snapshot.exists else {}
        if classify(record) != UNKNOWN or record.get("prompt_status") in {"pending", "sent"}:
            return None
        tx.set(ref, {"scope": SCOPE, "notice_version": VERSION,
                     "prompt_status": "pending", "prompt_claim": claim,
                     "updated_at": timestamp()}, merge=True)
        return claim
    return reserve(client.transaction())


def mark_prompt(client, phone, claim, delivered):
    from google.cloud import firestore
    ref = reference(client, phone)

    @firestore.transactional
    def mark(tx):
        snapshot = ref.get(transaction=tx)
        record = snapshot.to_dict() or {} if snapshot.exists else {}
        if record.get("prompt_claim") == claim:
            tx.set(ref, {"prompt_status": "sent" if delivered else "failed",
                         "updated_at": timestamp()}, merge=True)
    mark(client.transaction())


def save_decision(client, phone, decision, require_prompt=True):
    from google.cloud import firestore
    ref = reference(client, phone)
    if decision not in {OPTED_IN, OPTED_OUT}:
        raise ValueError("invalid_pedagogical_decision")

    @firestore.transactional
    def save(tx):
        snapshot = ref.get(transaction=tx)
        record = snapshot.to_dict() or {} if snapshot.exists else {}
        if require_prompt and (record.get("notice_version") != VERSION
                               or record.get("prompt_status") not in {"pending", "sent"}):
            return False
        tx.set(ref, {"scope": SCOPE, "notice_version": VERSION,
                     "consent_status": decision,
                     "source": "whatsapp_explicit_button" if require_prompt else "whatsapp_stop",
                     "updated_at": timestamp()}, merge=True)
        return True
    return save(client.transaction())
