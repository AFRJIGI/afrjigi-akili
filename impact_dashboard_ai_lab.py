import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from google.cloud import firestore, storage


BUCKET_NAME = "akili-database-storage-astute-curve-307922"
DB_BLOB = "data/jigi_global_database.json"

REPORT_BLOB = "analytics/rapport_ai_lab.json"
HISTORY_PREFIX = "analytics/ai_lab_historique"


MATIERE_NORMALISATION = {
    "maths": "Mathematiques",
    "mathematiques": "Mathematiques",
    "mathématiques": "Mathematiques",
    "philo": "Philosophie",
    "philosophie": "Philosophie",
    "pc": "Physique-Chimie",
    "physique": "Physique-Chimie",
    "physique-chimie": "Physique-Chimie",
    "physique chimie": "Physique-Chimie",
    "svt": "SVT",
    "sciences de la vie et de la terre (svt)": "SVT",
    "hg": "Histoire-Geographie",
    "histoire-geographie": "Histoire-Geographie",
    "histoire-géographie": "Histoire-Geographie",
    "histoire-geo": "Histoire-Geographie",
    "anglais": "Anglais",
    "anglais-oral": "Anglais",
    "allemand": "Allemand",
    "espagnol": "Espagnol",
    "francais": "Francais",
    "français": "Francais",
    "francais-qrp": "Francais",
    "français-qrp": "Francais",
    "francais-commentaire": "Francais",
    "français-commentaire": "Francais",
    "francais-dissertation": "Francais",
    "français-dissertation": "Francais",
    "french": "Francais",
    "orientation": "Orientation",
}


def normaliser_matiere(value):
    raw = (value or "").strip()
    if not raw:
        return None
    return MATIERE_NORMALISATION.get(raw.lower(), raw)


def parse_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            try:
                d = date.fromisoformat(value[:10])
                return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
            except ValueError:
                return None
    return None


def safe_stream(collection_ref):
    try:
        return list(collection_ref.stream())
    except Exception as exc:
        print(f"WARN: impossible de lire {collection_ref}: {exc}")
        return []


def read_users_metrics(db):
    users = safe_stream(db.collection("users"))
    today = date.today().isoformat()

    series = Counter()
    matieres = Counter()
    ecoles = Counter()
    ages = Counter()
    genres = Counter()
    profils = Counter()
    questions_today = 0
    active_today_from_users = 0
    active_users_fallback = {"today": set(), "7d": set(), "30d": set()}

    now = datetime.now(timezone.utc)
    start_7d = now - timedelta(days=7)
    start_30d = now - timedelta(days=30)

    for user in users:
        data = user.to_dict() or {}
        q_today = int(data.get("questions_today") or 0)
        questions_today += q_today
        if q_today > 0:
            active_today_from_users += 1
            active_users_fallback["today"].add(user.id)

        last_dt = parse_datetime(data.get("last_question_date") or data.get("last_active_at"))
        if last_dt:
            if last_dt >= start_7d:
                active_users_fallback["7d"].add(user.id)
            if last_dt >= start_30d:
                active_users_fallback["30d"].add(user.id)

        if (data.get("serie") or "").strip():
            series[data["serie"].strip()] += 1
        mat = normaliser_matiere(data.get("matiere"))
        if mat:
            matieres[mat] += 1
        if (data.get("nom_ecole") or "").strip():
            ecoles[data["nom_ecole"].strip()] += 1
        if (data.get("tranche_age") or "").strip():
            ages[data["tranche_age"].strip()] += 1
        if (data.get("genre") or "").strip():
            genres[data["genre"].strip()] += 1
        if (data.get("profil_type") or "").strip():
            profils[data["profil_type"].strip()] += 1

    return {
        "total_utilisateurs": len(users),
        "questions_aujourdhui": questions_today,
        "utilisateurs_actifs_aujourdhui_users": active_today_from_users,
        "active_users_fallback": active_users_fallback,
        "series": series,
        "matieres": matieres,
        "top_ecoles": ecoles,
        "tranches_age": ages,
        "genres": genres,
        "profils": profils,
    }


def read_message_metrics(db):
    now = datetime.now(timezone.utc)
    start_today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    start_7d = now - timedelta(days=7)
    start_30d = now - timedelta(days=30)

    total_student_questions = 0
    total_messages = 0
    active_today = set()
    active_7d = set()
    active_30d = set()
    by_matiere = Counter()
    by_examen = Counter()

    try:
        messages = db.collection_group("messages").stream()
        for msg in messages:
            data = msg.to_dict() or {}
            role = (data.get("role") or "").lower()
            timestamp = parse_datetime(data.get("timestamp") or data.get("created_at"))
            user_id = "unknown"
            try:
                if msg.reference.parent and msg.reference.parent.parent:
                    user_id = msg.reference.parent.parent.id
            except Exception:
                pass

            total_messages += 1
            if role == "user":
                total_student_questions += 1

            if timestamp:
                if timestamp >= start_today:
                    active_today.add(user_id)
                if timestamp >= start_7d:
                    active_7d.add(user_id)
                if timestamp >= start_30d:
                    active_30d.add(user_id)

            mat = normaliser_matiere(data.get("matiere"))
            if mat:
                by_matiere[mat] += 1
            if (data.get("type_examen") or "").strip():
                by_examen[data["type_examen"].strip()] += 1

        error = None
    except Exception as exc:
        error = str(exc)

    return {
        "total_messages": total_messages,
        "total_questions_eleves": total_student_questions,
        "active_today": active_today,
        "active_7d": active_7d,
        "active_30d": active_30d,
        "messages_par_matiere": by_matiere,
        "messages_par_examen": by_examen,
        "error": error,
    }


def read_knowledge_base_metrics(storage_client):
    bucket = storage_client.bucket(BUCKET_NAME)
    raw = bucket.blob(DB_BLOB).download_as_text()
    data = json.loads(raw)
    docs = data.get("documents", [])

    by_exam = Counter()
    by_subject = Counter()
    by_type = Counter()
    by_source = Counter()

    for doc in docs:
        by_exam[(doc.get("examen") or "INCONNU").strip() or "INCONNU"] += 1
        mat = normaliser_matiere(doc.get("matiere")) or "INCONNU"
        by_subject[mat] += 1
        by_type[(doc.get("type_doc") or "INCONNU").strip() or "INCONNU"] += 1
        by_source[(doc.get("source") or "INCONNU").strip() or "INCONNU"] += 1

    official_programs = sum(
        1 for doc in docs if (doc.get("type_doc") or "").upper() == "PROGRAMME"
    )
    official_tp = sum(
        1
        for doc in docs
        if (doc.get("type_doc") or "").upper() == "TP"
        or (doc.get("source") or "").upper() == "DPFC_TP"
    )
    coefficients_docs = sum(
        1 for doc in docs if (doc.get("type_doc") or "").upper() == "COEFFICIENTS"
    )

    exam_tracks = sorted(
        e for e in by_exam if e not in {"", "INCONNU", "None"}
    )

    return {
        "total_documents": len(docs),
        "exam_tracks": exam_tracks,
        "documents_par_examen": by_exam,
        "documents_par_matiere": by_subject,
        "documents_par_type": by_type,
        "documents_par_source": by_source,
        "programmes_officiels": official_programs,
        "tp_officiels": official_tp,
        "coefficients_officiels": coefficients_docs,
        "generated_at_db": data.get("generated_at"),
    }


def read_teacher_metrics(db):
    collection_names = ["enseignants", "enseignants_interesses"]
    total = 0
    by_status = Counter()
    by_subject = Counter()
    by_level = Counter()
    collections = {}

    for name in collection_names:
        docs = safe_stream(db.collection(name))
        collections[name] = len(docs)
        total += len(docs)
        for doc in docs:
            data = doc.to_dict() or {}
            by_status[(data.get("statut") or "nouveau").strip()] += 1
            mat = normaliser_matiere(data.get("matiere") or data.get("matiere_enseignee"))
            if mat:
                by_subject[mat] += 1
            if (data.get("niveau") or "").strip():
                by_level[data["niveau"].strip()] += 1

    return {
        "total_enseignants": total,
        "collections": collections,
        "enseignants_par_statut": by_status,
        "enseignants_par_matiere": by_subject,
        "enseignants_par_niveau": by_level,
    }


def counter_to_dict(counter, limit=None):
    items = counter.most_common(limit)
    return {k: v for k, v in items}


def main():
    db = firestore.Client()
    storage_client = storage.Client()

    users = read_users_metrics(db)
    messages = read_message_metrics(db)
    kb = read_knowledge_base_metrics(storage_client)
    teachers = read_teacher_metrics(db)

    if messages["error"]:
        active_today = users["active_users_fallback"]["today"]
        active_7d = users["active_users_fallback"]["7d"]
        active_30d = users["active_users_fallback"]["30d"]
        total_student_questions = users["questions_aujourdhui"]
    else:
        active_today = messages["active_today"] or users["active_users_fallback"]["today"]
        active_7d = messages["active_7d"] or users["active_users_fallback"]["7d"]
        active_30d = messages["active_30d"] or users["active_users_fallback"]["30d"]
        total_student_questions = messages["total_questions_eleves"]

    now = datetime.now(timezone.utc)
    today = date.today().isoformat()

    report = {
        "genere_le": now.isoformat(),
        "date": today,
        "pitch_deck_summary": {
            "context_note": "Usage metrics are currently measured during the school holiday period; the main adoption ramp is expected from the September back-to-school period through the 2026 exam season.",
            "headline_metrics": {
                "official_documents_processed": kb["total_documents"],
                "exam_tracks_covered": len(kb["exam_tracks"]),
                "exam_tracks": kb["exam_tracks"],
                "official_programs": kb["programmes_officiels"],
                "official_tp_worksheets": kb["tp_officiels"],
                "official_coefficients_docs": kb["coefficients_officiels"],
                "registered_users": users["total_utilisateurs"],
                "student_questions_tracked": total_student_questions,
                "teacher_network_contacts": teachers["total_enseignants"],
                "channels_deployed": ["Web app", "WhatsApp"],
                "learning_modes_live": ["Mode Etude", "Mode Examen"],
            },
        },
        "readiness_metrics": {
            "knowledge_base": {
                "total_documents": kb["total_documents"],
                "documents_par_examen": counter_to_dict(kb["documents_par_examen"]),
                "documents_par_matiere": counter_to_dict(kb["documents_par_matiere"], 15),
                "documents_par_type": counter_to_dict(kb["documents_par_type"]),
                "documents_par_source": counter_to_dict(kb["documents_par_source"]),
                "programmes_officiels": kb["programmes_officiels"],
                "tp_officiels": kb["tp_officiels"],
                "coefficients_officiels": kb["coefficients_officiels"],
            },
            "product": {
                "channels_deployed": ["Web app", "WhatsApp"],
                "learning_modes_live": ["Mode Etude", "Mode Examen"],
                "official_curriculum_grounding": True,
                "exam_tracks_covered": kb["exam_tracks"],
            },
        },
        "pilot_usage": {
            "context": "School holiday period; interpret active-user data as pilot usage, not full school-year demand.",
            "total_utilisateurs": users["total_utilisateurs"],
            "questions_aujourdhui": users["questions_aujourdhui"],
            "questions_eleves_total_suivi": total_student_questions,
            "utilisateurs_actifs_aujourdhui": len(active_today),
            "utilisateurs_actifs_7j": len(active_7d),
            "utilisateurs_actifs_30j": len(active_30d),
            "series": counter_to_dict(users["series"]),
            "matieres": counter_to_dict(users["matieres"]),
            "top_ecoles": counter_to_dict(users["top_ecoles"], 10),
            "tranches_age": counter_to_dict(users["tranches_age"]),
            "genres": counter_to_dict(users["genres"]),
            "profils": counter_to_dict(users["profils"]),
            "messages_par_matiere": counter_to_dict(messages["messages_par_matiere"], 15),
            "messages_par_examen": counter_to_dict(messages["messages_par_examen"]),
            "message_collection_group_error": messages["error"],
        },
        "teacher_network": {
            "total_enseignants": teachers["total_enseignants"],
            "collections": teachers["collections"],
            "enseignants_par_statut": counter_to_dict(teachers["enseignants_par_statut"]),
            "enseignants_par_matiere": counter_to_dict(teachers["enseignants_par_matiere"]),
            "enseignants_par_niveau": counter_to_dict(teachers["enseignants_par_niveau"]),
        },
    }

    content = json.dumps(report, ensure_ascii=False, indent=2)
    bucket = storage_client.bucket(BUCKET_NAME)
    bucket.blob(REPORT_BLOB).upload_from_string(content, content_type="application/json")
    bucket.blob(f"{HISTORY_PREFIX}/{today}.json").upload_from_string(
        content, content_type="application/json"
    )
    db.collection("analytics").document("rapport_ai_lab").set(report)
    db.collection("analytics_ai_lab").document(today).set(report)

    print(content)
    print(f"\nRapport sauvegarde: gs://{BUCKET_NAME}/{REPORT_BLOB}")
    print(f"Historique sauvegarde: gs://{BUCKET_NAME}/{HISTORY_PREFIX}/{today}.json")


if __name__ == "__main__":
    main()
