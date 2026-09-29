"""Consentement marketing WhatsApp, sans PII dans le stockage dédié."""

from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Any


CONSENT_COLLECTION = "whatsapp_marketing_consent"
CONSENT_SCHEMA_VERSION = 1
CONSENT_CHANNEL = "whatsapp"

OPTED_IN = "opted_in"
OPTED_OUT = "opted_out"
UNKNOWN = "unknown"
PROMPT_PENDING = "pending"
PROMPT_SENT = "sent"
PROMPT_FAILED = "failed"


def _normalize_command(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^A-Za-z0-9]+", " ", text).strip().upper()
    return " ".join(text.split())


OPT_OUT_COMMANDS = frozenset(
    _normalize_command(command)
    for command in {
        "STOP",
        "STOP ALL",
        "UNSUBSCRIBE",
        "UNSUBSCRIBE ALL",
        "OPT OUT",
        "CANCEL",
        "END",
        "QUIT",
        "ARRÊT",
        "ARRÊTER",
        "DÉSINSCRIPTION",
        "DÉSINSCRIRE",
        "ME DÉSINSCRIRE",
        "NE PLUS ME CONTACTER",
        "NE ME CONTACTEZ PLUS",
        "NE PLUS M'ENVOYER DE MESSAGES",
        "NE M'ENVOYEZ PLUS DE MESSAGES",
    }
)

OPT_IN_COMMANDS = frozenset(
    _normalize_command(command)
    for command in {
        "OPT IN",
        "SUBSCRIBE",
        "START MARKETING",
        "START PROMO",
        "OUI MARKETING",
        "OUI PROMOTIONS",
        "OUI AUX MESSAGES MARKETING",
        "J'ACCEPTE LES MESSAGES MARKETING",
        "JE CONSENS AUX MESSAGES MARKETING",
        "M'ABONNER AUX MESSAGES MARKETING",
        "ME RÉABONNER",
        "RÉABONNEMENT",
    }
)


def detect_marketing_consent_command(text: Any) -> str | None:
    """Retourne une décision uniquement pour une commande explicite et complète."""
    command = _normalize_command(text)
    if command in OPT_OUT_COMMANDS:
        return OPTED_OUT
    if command in OPT_IN_COMMANDS:
        return OPTED_IN
    return None


def consent_document_id(identifier: Any) -> str:
    """Produit le même identifiant pseudonyme que les segments hebdomadaires."""
    raw = str(identifier or "").strip().lower()
    if not raw:
        raise ValueError("missing_whatsapp_identifier")
    return hashlib.sha256(
        f"afrjigi-weekly-v1:{CONSENT_CHANNEL}:{raw}".encode("utf-8")
    ).hexdigest()


def build_marketing_consent_record(
    decision: str, now: datetime | None = None
) -> dict[str, Any]:
    """Construit un document de consentement ne contenant aucune PII."""
    if decision not in {OPTED_IN, OPTED_OUT}:
        raise ValueError("invalid_marketing_consent_decision")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    timestamp = now.astimezone(timezone.utc).isoformat()
    opted_in = decision == OPTED_IN
    return {
        "schema_version": CONSENT_SCHEMA_VERSION,
        "channel": CONSENT_CHANNEL,
        "consent_status": decision,
        "marketing_opt_in": opted_in,
        "unsubscribed": not opted_in,
        "source": "whatsapp_inbound_keyword",
        "last_command": "opt_in" if opted_in else "opt_out",
        "updated_at": timestamp,
        "opted_in_at": timestamp if opted_in else None,
        "opted_out_at": None if opted_in else timestamp,
    }


def build_marketing_consent_prompt_record(
    claim_id: str, now: datetime | None = None
) -> dict[str, Any]:
    """Réserve une invitation sans conserver l'identifiant ni le message entrant."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    timestamp = now.astimezone(timezone.utc).isoformat()
    return {
        "schema_version": CONSENT_SCHEMA_VERSION,
        "channel": CONSENT_CHANNEL,
        "consent_status": UNKNOWN,
        "marketing_opt_in": None,
        "unsubscribed": None,
        "source": "whatsapp_user_initiated_prompt",
        "prompt_delivery_status": PROMPT_PENDING,
        "prompt_claim_id": claim_id,
        "prompt_claimed_at": timestamp,
        "updated_at": timestamp,
    }


def claim_marketing_consent_prompt(
    client: Any, identifier: Any, now: datetime | None = None
) -> str | None:
    """Réserve atomiquement la première invitation; un échec d'envoi reste réessayable."""
    reference = client.collection(CONSENT_COLLECTION).document(
        consent_document_id(identifier)
    )
    claim_id = uuid.uuid4().hex
    record = build_marketing_consent_prompt_record(claim_id, now=now)
    try:
        reference.create(record)
        return claim_id
    except Exception as exc:
        if type(exc).__name__ != "AlreadyExists":
            raise

    snapshot = reference.get()
    existing = snapshot.to_dict() or {} if getattr(snapshot, "exists", False) else {}
    if (
        classify_marketing_consent(existing) != UNKNOWN
        or existing.get("prompt_delivery_status") != PROMPT_FAILED
    ):
        return None
    reference.set(record, merge=True)
    return claim_id


def mark_marketing_consent_prompt_delivery(
    client: Any,
    identifier: Any,
    claim_id: str,
    delivered: bool,
    now: datetime | None = None,
) -> None:
    """Marque le résultat sans PII; un échec pourra être repris au prochain message."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    timestamp = now.astimezone(timezone.utc).isoformat()
    status = PROMPT_SENT if delivered else PROMPT_FAILED
    client.collection(CONSENT_COLLECTION).document(
        consent_document_id(identifier)
    ).set({
        "prompt_delivery_status": status,
        "prompt_claim_id": claim_id,
        "prompt_sent_at": timestamp if delivered else None,
        "prompt_failed_at": None if delivered else timestamp,
        "updated_at": timestamp,
    }, merge=True)


def save_marketing_consent(
    client: Any,
    identifier: Any,
    decision: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Persiste l'état sous un ID hashé; ni l'identifiant ni le message ne sont écrits."""
    record = build_marketing_consent_record(decision, now=now)
    client.collection(CONSENT_COLLECTION).document(
        consent_document_id(identifier)
    ).set(record, merge=True)
    return record


def classify_marketing_consent(record: Any) -> str:
    """Classe en mode fail-safe: tout opt-out explicite prime sur l'opt-in."""
    if not isinstance(record, dict):
        return UNKNOWN
    if (
        record.get("unsubscribed") is True
        or record.get("consent_status") == OPTED_OUT
        or record.get("marketing_opt_in") is False
    ):
        return OPTED_OUT
    if (
        record.get("schema_version") == CONSENT_SCHEMA_VERSION
        and record.get("channel") == CONSENT_CHANNEL
        and record.get("consent_status") == OPTED_IN
        and record.get("marketing_opt_in") is True
        and record.get("unsubscribed") is False
    ):
        return OPTED_IN
    return UNKNOWN


def marketing_recipient_is_eligible(client: Any, identifier: Any) -> bool:
    """Garde-fou réutilisable par tout futur expéditeur de campagne."""
    snapshot = client.collection(CONSENT_COLLECTION).document(
        consent_document_id(identifier)
    ).get()
    if not getattr(snapshot, "exists", False):
        return False
    return classify_marketing_consent(snapshot.to_dict()) == OPTED_IN
