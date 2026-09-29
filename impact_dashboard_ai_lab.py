import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

from google.cloud import firestore, storage
from google.cloud.firestore_v1 import FieldFilter


BUCKET_NAME = "akili-database-storage-astute-curve-307922"
DB_BLOB = "data/jigi_global_database.json"

REPORT_BLOB = "analytics/rapport_ai_lab.json"
HISTORY_PREFIX = "analytics/ai_lab_historique"


MATIERE_NORMALISATION = {
    "maths": "Mathematiques",
    "mathematiques": "Mathematiques",
    "math": "Mathematiques",
    "histoire geographie": "Histoire-Geographie",
    "histoire géographie": "Histoire-Geographie",
    "histoire -geographie": "Histoire-Geographie",
    "histoire - geographie": "Histoire-Geographie",
    "histoire-géographie": "Histoire-Geographie",
    "hist geo": "Histoire-Geographie",
    "hg": "Histoire-Geographie",
    "comptabilite": "Comptabilite",
    "comptabilité": "Comptabilite",
    "economie": "Economie",
    "économie": "Economie",
    "arts e": "Arts/Musique",
    "arts": "Arts/Musique",
    "musique": "Arts/Musique",
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


def classify_user_doc(doc):
    uid = (doc.id or "").lower()
    data = doc.to_dict() or {}
    email = str(data.get("email", "") or "").lower()
    marker = uid + " " + email

    if "test" in marker:
        return "test"
    if "@afrjigi.com" in marker or uid.replace("+", "").isdigit():
        return "whatsapp"
    if "@" in marker:
        return "web"
    return "unknown"


def read_users_metrics(db):
    users = safe_stream(db.collection("users"))

    user_types = Counter(classify_user_doc(doc) for doc in users)
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
        "utilisateurs_web_estimes": user_types.get("web", 0),
        "utilisateurs_whatsapp_dans_users": user_types.get("whatsapp", 0),
        "comptes_test": user_types.get("test", 0),
        "utilisateurs_non_classes": user_types.get("unknown", 0),
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
    from google.cloud.storage.retry import DEFAULT_RETRY
    storage_retry = DEFAULT_RETRY.with_deadline(600)
    raw = bucket.blob(DB_BLOB).download_as_text(
        timeout=300,
        retry=storage_retry,
    )
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
    collection_names = ["enseignants", "enseignants_interesses", "enseignants_interet"]
    total = 0
    by_status = Counter()
    by_subject = Counter()
    by_level = Counter()
    by_city = Counter()
    by_school = Counter()
    by_interview_status = Counter()
    by_prompt_status = Counter()
    collections = {}
    directory = []

    for name in collection_names:
        docs = safe_stream(db.collection(name))
        collections[name] = len(docs)
        total += len(docs)

        for doc in docs:
            data = doc.to_dict() or {}

            status = (data.get("statut") or "nouveau").strip()
            by_status[status] += 1

            raw_matiere = data.get("matiere") or data.get("matiere_enseignee") or ""
            matieres = []
            for part in str(raw_matiere).replace("/", ",").replace("&", ",").split(","):
                mat = normaliser_matiere(part)
                if mat:
                    matieres.append(mat)

            for mat in sorted(set(matieres)):
                by_subject[mat] += 1

            mat = ", ".join(sorted(set(matieres)))

            level = (
                data.get("niveau")
                or data.get("niveaux")
                or data.get("niveau_enseigne")
                or data.get("niveaux_enseignes")
                or ""
            ).strip()
            if level:
                by_level[level] += 1

            city = (data.get("ville") or data.get("city") or "").strip()
            if city:
                by_city[city] += 1

            school = (
                data.get("ecole")
                or data.get("etablissement")
                or data.get("school")
                or data.get("universite")
                or ""
            ).strip()
            if school:
                by_school[school] += 1

            interview_status = (
                data.get("statut_entretien")
                or data.get("interview_status")
                or "a_interviewer"
            ).strip()
            by_interview_status[interview_status] += 1

            prompt_status = (
                data.get("statut_prompt")
                or data.get("prompt_status")
                or "non_demarre"
            ).strip()
            by_prompt_status[prompt_status] += 1

            directory.append({
                "id": doc.id,
                "collection": name,
                "nom": data.get("nom") or data.get("name") or "",
                "matiere": mat or "",
                "etablissement": school,
                "ville": city,
                "niveaux": level,
                "whatsapp": data.get("whatsapp") or data.get("telephone") or data.get("phone") or "",
                "email": data.get("email") or "",
                "statut": status,
                "statut_entretien": interview_status,
                "statut_prompt": prompt_status,
                "commentaire": data.get("commentaire") or data.get("notes") or "",
            })

    core_subjects = {
        "Mathematiques",
        "Physique-Chimie",
        "SVT",
        "Francais",
        "Philosophie",
        "Histoire-Geographie",
        "Anglais",
        "Economie",
        "Comptabilite",
    }
    covered_subjects = set(by_subject)

    return {
        "total_enseignants": total,
        "collections": collections,
        "enseignants_par_statut": by_status,
        "enseignants_par_matiere": by_subject,
        "enseignants_par_niveau": by_level,
        "enseignants_par_ville": by_city,
        "enseignants_par_etablissement": by_school,
        "enseignants_par_statut_entretien": by_interview_status,
        "enseignants_par_statut_prompt": by_prompt_status,
        "matieres_coeur_couvertes": sorted(covered_subjects & core_subjects),
        "matieres_coeur_manquantes": sorted(core_subjects - covered_subjects),
        "repertoire_enseignants": sorted(
            directory,
            key=lambda item: (
                item.get("matiere") or "ZZZ",
                item.get("ville") or "ZZZ",
                item.get("nom") or "ZZZ",
            ),
        ),
    }


def counter_to_dict(counter, limit=None):
    items = counter.most_common(limit)
    return {k: v for k, v in items}


_FIRESTORE_COLLECTION_CACHE = {}


def read_collection_paginated(db, collection_name, page_size=500, max_retries=3):
    """Lit une collection Firestore par petits lots avec reprise automatique."""
    import time

    if collection_name in _FIRESTORE_COLLECTION_CACHE:
        return _FIRESTORE_COLLECTION_CACHE[collection_name]

    documents = []
    last_document = None

    while True:
        query = (
            db.collection(collection_name)
            .order_by("__name__")
            .limit(page_size)
        )

        if last_document is not None:
            query = query.start_after(last_document)

        page = None
        last_error = None

        for attempt in range(1, max_retries + 1):
            try:
                page = list(query.stream(timeout=120, retry=None))
                break
            except Exception as error:
                last_error = error
                print(
                    f"Firestore {collection_name}: "
                    f"page retry {attempt}/{max_retries}: {error}",
                    flush=True,
                )
                if attempt < max_retries:
                    time.sleep(attempt * 3)

        if page is None:
            raise RuntimeError(
                f"Lecture Firestore impossible pour {collection_name}: {last_error}"
            )

        documents.extend(page)

        if len(page) < page_size:
            break

        last_document = page[-1]

    _FIRESTORE_COLLECTION_CACHE[collection_name] = documents
    return documents



def read_whatsapp_metrics(db):
    """Lit les messages WhatsApp suivis depuis Firestore avec chiffres conservateurs."""
    from collections import Counter, defaultdict
    from datetime import datetime, timezone

    internal_phones = {"16465528791", "16466420404", "13153021255"}

    def parse_dt(ts):
        try:
            return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except Exception:
            return None

    def final_value(data, field, default=""):
        return data.get(f"{field}_after") or data.get(field) or default

    try:
        docs = read_collection_paginated(db, "whatsapp_messages")
    except Exception as e:
        return {
            "tracking_enabled": False,
            "error": str(e),
            "messages_entrants_suivis": 0,
            "utilisateurs_uniques": 0,
            "utilisateurs_actifs_aujourdhui": 0,
            "utilisateurs_revenus_30min": 0,
            "utilisateurs_revenus_2jours": 0,
            "taux_retour_30min": 0,
            "taux_retour_2jours": 0,
            "matieres": {},
            "series": {},
            "top_utilisateurs": [],
        }

    now = datetime.now(timezone.utc)
    today = now.date()

    rows = []
    for d in docs:
        data = d.to_dict()

        if data.get("direction") != "inbound":
            continue

        phone = data.get("phone", "")
        if phone in internal_phones:
            continue

        dt = parse_dt(data.get("created_at", ""))
        if not dt:
            continue

        rows.append({
            "phone": phone,
            "created_at": data.get("created_at", ""),
            "dt": dt,
            "matiere": final_value(data, "matiere", "VIDE"),
            "serie": final_value(data, "serie", "VIDE"),
            "type_examen": final_value(data, "type_examen", "VIDE"),
            "mode": final_value(data, "mode", "VIDE"),
            "stage": data.get("processing_stage") or "ancien_tracking",
            "text": data.get("text", ""),
        })

    by_phone = defaultdict(list)
    for row in rows:
        by_phone[row["phone"]].append(row)

    returned_30min = 0
    returned_2days = 0
    top_users = []

    for phone, items in by_phone.items():
        items = sorted(items, key=lambda x: x["dt"])
        first = items[0]
        last = items[-1]
        span_minutes = (last["dt"] - first["dt"]).total_seconds() / 60
        days = len(set(i["dt"].date() for i in items))

        if len(items) >= 2 and span_minutes >= 30:
            returned_30min += 1

        if days >= 2:
            returned_2days += 1

        top_users.append({
            "phone": phone,
            "messages": len(items),
            "jours": days,
            "span_minutes": round(span_minutes, 1),
            "first_seen": first["created_at"],
            "last_seen": last["created_at"],
            "matiere": last["matiere"],
            "serie": last["serie"],
        })

    top_users.sort(key=lambda x: x["messages"], reverse=True)

    unique_users = len(by_phone)
    active_today = len(set(r["phone"] for r in rows if r["dt"].date() == today))

    return {
        "tracking_enabled": True,
        "messages_entrants_suivis": len(rows),
        "utilisateurs_uniques": unique_users,
        "utilisateurs_actifs_aujourdhui": active_today,
        "utilisateurs_revenus_30min": returned_30min,
        "utilisateurs_revenus_2jours": returned_2days,
        "taux_retour_30min": round(returned_30min * 100 / unique_users, 1) if unique_users else 0,
        "taux_retour_2jours": round(returned_2days * 100 / unique_users, 1) if unique_users else 0,
        "matieres": dict(Counter(r["matiere"] for r in rows)),
        "series": dict(Counter(r["serie"] for r in rows)),
        "stages": dict(Counter(r["stage"] for r in rows)),
        "top_utilisateurs": top_users[:25],
    }



def clean_metric_location(value):
    raw = str(value or "").strip()
    norm = raw.lower().replace("-", " ").replace("'", " ").strip()
    norm = " ".join(norm.split())

    invalid = {
        "", "vide", "ok", "oui", "non", "ca", "c est ca", "c'est ca",
        "pas de commentaire", "passer", "passe", "passé"
    }
    if norm in invalid:
        return "VIDE"

    aliases = {
        "san pedro": "San Pedro",
        "san pedro ci": "San Pedro",
        "bouake": "Bouaké",
        "abidjan": "Abidjan",
        "yamoussoukro": "Yamoussoukro",
        "daloa": "Daloa",
        "korhogo": "Korhogo",
        "abengourou": "Abengourou",
        "aboisso": "Aboisso",
        "divo": "Divo",
        "tabou": "Tabou",
        "gagnoa": "Gagnoa",
        "adzope": "Adzopé",
        "bondoukou": "Bondoukou",
        "grand bereby": "Grand-Béréby",
        "zouan hounien": "Zouan-Hounien",
    }
    return aliases.get(norm, raw[:80])


def clean_metric_school(value):
    raw = str(value or "").strip()
    norm = raw.lower().replace("'", " ").strip()
    norm = " ".join(norm.split())

    invalid = {"", "vide", "ok", "oui", "non", "pas de commentaire", "passer", "passe", "passé"}
    if norm in invalid or norm.startswith("passer ") or norm.startswith("passe "):
        return "VIDE"

    aliases = {
        "lycee moderne 2": "Lycée Moderne 2",
        "lycée moderne 2": "Lycée Moderne 2",
        "college les elus de tabou": "Collège Les Élus de Tabou",
        "collège les élus de tabou": "Collège Les Élus de Tabou",
    }
    return aliases.get(norm, raw[:120])



def read_grand_pilote_metrics(db):
    """Mesure acquisition, onboarding, villes/ecoles pour le Grand Pilote."""
    from collections import Counter, defaultdict

    internal_phones = {"16465528791", "16466420404", "13153021255"}

    def norm(v, default="VIDE"):
        v = str(v or "").strip()
        return v if v else default

    def phone_from_user_id(user_id, data):
        phone = str(data.get("phone") or "").strip()
        if phone:
            return phone
        if str(user_id).endswith("@afrjigi.com"):
            return str(user_id).split("@", 1)[0]
        return str(user_id)

    users_by_source = defaultdict(lambda: {
        "users": 0,
        "onboarding_completed": 0,
        "first_learning_request": 0,
        "villes": Counter(),
        "ecoles": Counter(),
        "matieres": Counter(),
        "series": Counter(),
    })

    villes = Counter()
    ecoles = Counter()
    sources = Counter()
    onboarding_completed_total = 0
    first_learning_total = 0

    try:
        user_docs = list(db.collection("users").stream())
    except Exception as e:
        return {
            "tracking_enabled": False,
            "error": str(e),
            "sources": {},
            "villes": {},
            "ecoles": {},
            "onboarding_completed_total": 0,
            "first_learning_request_total": 0,
        }

    for doc in user_docs:
        data = doc.to_dict() or {}
        phone = phone_from_user_id(doc.id, data)

        if phone in internal_phones:
            continue

        source = norm(data.get("acquisition_source"), "ORGANIC")
        ville = clean_metric_location(data.get("ville"))
        ecole = clean_metric_school(data.get("nom_ecole"))
        matiere = norm(data.get("matiere"))
        serie = norm(data.get("serie"))

        has_onboarding = bool(data.get("onboarding_completed_at"))
        has_first_learning = bool(data.get("first_learning_request_at"))

        sources[source] += 1
        villes[ville] += 1
        ecoles[ecole] += 1

        bucket = users_by_source[source]
        bucket["users"] += 1
        bucket["villes"][ville] += 1
        bucket["ecoles"][ecole] += 1
        bucket["matieres"][matiere] += 1
        bucket["series"][serie] += 1

        if has_onboarding:
            onboarding_completed_total += 1
            bucket["onboarding_completed"] += 1

        if has_first_learning:
            first_learning_total += 1
            bucket["first_learning_request"] += 1

    messages_by_source = Counter()
    onboarding_events_by_source = Counter()
    first_learning_events_by_source = Counter()

    try:
        msg_docs = read_collection_paginated(db, "whatsapp_messages")
        for doc in msg_docs:
            data = doc.to_dict() or {}
            if data.get("direction") != "inbound":
                continue

            phone = str(data.get("phone") or "").strip()
            if phone in internal_phones:
                continue

            source = norm(data.get("acquisition_source"), "ORGANIC")
            stage = str(data.get("processing_stage") or "")

            messages_by_source[source] += 1

            if data.get("onboarding_completed_at") or stage == "onboarding_completed":
                onboarding_events_by_source[source] += 1

            if data.get("first_learning_request_at") or stage == "first_learning_request":
                first_learning_events_by_source[source] += 1

    except Exception:
        pass

    source_rows = {}
    for source, data in users_by_source.items():
        users_count = data["users"]
        onboarded = data["onboarding_completed"]
        first_learning = data["first_learning_request"]

        source_rows[source] = {
            "users": users_count,
            "messages": messages_by_source.get(source, 0),
            "onboarding_completed": onboarded,
            "first_learning_request": first_learning,
            "activation_rate": round(first_learning * 100 / users_count, 1) if users_count else 0,
            "onboarding_rate": round(onboarded * 100 / users_count, 1) if users_count else 0,
            "top_villes": counter_to_dict(data["villes"], 10),
            "top_ecoles": counter_to_dict(data["ecoles"], 10),
            "matieres": counter_to_dict(data["matieres"], 10),
            "series": counter_to_dict(data["series"], 10),
        }

    return {
        "tracking_enabled": True,
        "error": "",
        "campaign": "GRAND-PILOTE-2026",
        "sources": source_rows,
        "sources_total_users": dict(sources),
        "messages_by_source": dict(messages_by_source),
        "onboarding_completed_total": onboarding_completed_total,
        "first_learning_request_total": first_learning_total,
        "top_villes": counter_to_dict(villes, 20),
        "top_ecoles": counter_to_dict(ecoles, 20),
    }



def read_web_feedback_metrics(project_id="afrjigi"):
    """Lit les retours envoyes depuis app.afrjigi.com."""
    from collections import Counter
    from google.cloud import firestore

    try:
        web_db = firestore.Client(project=project_id)
        docs = list(web_db.collection("feedback_web").stream())
    except Exception as e:
        return {
            "tracking_enabled": False,
            "project_id": project_id,
            "error": str(e),
            "total_feedbacks": 0,
            "by_source": {},
            "by_campaign": {},
            "by_type_examen": {},
            "by_serie": {},
            "by_matiere": {},
            "recent_feedbacks": [],
        }

    rows = []
    for d in docs:
        data = d.to_dict() or {}
        rows.append({
            "id": d.id,
            "email": data.get("email", ""),
            "feedback": data.get("feedback", ""),
            "source": data.get("source", ""),
            "campaign": data.get("campaign", ""),
            "type_examen": data.get("type_examen", ""),
            "serie": data.get("serie", ""),
            "matiere": data.get("matiere", ""),
            "created_at": data.get("created_at", ""),
        })

    rows.sort(key=lambda x: x.get("created_at") or "", reverse=True)

    return {
        "tracking_enabled": True,
        "project_id": project_id,
        "total_feedbacks": len(rows),
        "by_source": dict(Counter(r["source"] or "VIDE" for r in rows)),
        "by_campaign": dict(Counter(r["campaign"] or "VIDE" for r in rows)),
        "by_type_examen": dict(Counter(r["type_examen"] or "VIDE" for r in rows)),
        "by_serie": dict(Counter(r["serie"] or "VIDE" for r in rows)),
        "by_matiere": dict(Counter(r["matiere"] or "VIDE" for r in rows)),
        "recent_feedbacks": rows[:20],
    }




def read_whatsapp_feedback_metrics(db):
    """Lit les retours envoyes depuis le bot WhatsApp."""
    from collections import Counter

    try:
        docs = read_collection_paginated(
            db,
            "feedback_whatsapp",
        )
    except Exception as e:
        return {
            "tracking_enabled": False,
            "error": str(e),
            "total_feedbacks": 0,
            "by_source": {},
            "by_status": {},
            "by_serie": {},
            "by_matiere": {},
            "recent_feedbacks": [],
        }

    rows = []

    for doc in docs:
        data = doc.to_dict() or {}
        phone = "".join(
            c for c in str(data.get("phone", ""))
            if c.isdigit()
        )
        masked_phone = (
            ("*" * max(0, len(phone) - 4)) + phone[-4:]
            if phone else ""
        )

        rows.append({
            "id": doc.id,
            "phone": masked_phone,
            "feedback": data.get("feedback", ""),
            "original_message": data.get(
                "original_message",
                "",
            ),
            "source": data.get("source", "whatsapp"),
            "statut": data.get("statut", ""),
            "serie": data.get("serie_detectee", ""),
            "matiere": data.get("matiere_detectee", ""),
            "type_examen": data.get(
                "type_examen_detecte",
                "",
            ),
            "mode": data.get("mode_detecte", ""),
            "created_at": data.get("created_at", ""),
        })

    rows.sort(
        key=lambda item: item.get("created_at") or "",
        reverse=True,
    )

    return {
        "tracking_enabled": True,
        "error": "",
        "total_feedbacks": len(rows),
        "by_source": dict(Counter(
            row["source"] or "whatsapp"
            for row in rows
        )),
        "by_status": dict(Counter(
            row["statut"] or "VIDE"
            for row in rows
        )),
        "by_serie": dict(Counter(
            row["serie"] or "VIDE"
            for row in rows
        )),
        "by_matiere": dict(Counter(
            row["matiere"] or "VIDE"
            for row in rows
        )),
        "recent_feedbacks": rows[:20],
    }


def main():
    db = firestore.Client()
    storage_client = storage.Client()

    users = read_users_metrics(db)
    messages = read_message_metrics(db)
    kb = read_knowledge_base_metrics(storage_client)
    teachers_db = firestore.Client(project="afrjigi")
    teachers = read_teacher_metrics(teachers_db)
    whatsapp = read_whatsapp_metrics(db)
    grand_pilote = read_grand_pilote_metrics(db)
    web_feedback = read_web_feedback_metrics()
    whatsapp_feedback = read_whatsapp_feedback_metrics(db)
    feedback_metrics = {
        "tracking_enabled": bool(
            web_feedback.get("tracking_enabled")
            or whatsapp_feedback.get("tracking_enabled")
        ),
        "total_feedbacks": (
            web_feedback.get("total_feedbacks", 0)
            + whatsapp_feedback.get("total_feedbacks", 0)
        ),
        "web_feedbacks": web_feedback.get(
            "total_feedbacks",
            0,
        ),
        "whatsapp_feedbacks": whatsapp_feedback.get(
            "total_feedbacks",
            0,
        ),
        "web_error": web_feedback.get("error", ""),
        "whatsapp_error": whatsapp_feedback.get(
            "error",
            "",
        ),
    }

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
                "registered_users": users.get("utilisateurs_web_estimes", users["total_utilisateurs"]),
                "student_questions_tracked": total_student_questions,
                "teacher_network_contacts": teachers["total_enseignants"],
                "whatsapp_users_tracked": whatsapp["utilisateurs_uniques"],
                "whatsapp_inbound_messages_tracked": whatsapp["messages_entrants_suivis"],
                "whatsapp_returning_users_30min": whatsapp["utilisateurs_revenus_30min"],
                "channels_deployed": ["Web app", "WhatsApp"],
                "learning_modes_live": ["Mode Etude", "Mode Examen"],
            },
        },
        "pilot_metrics": {
            "utilisateurs_web_estimes": users.get("utilisateurs_web_estimes"),
            "comptes_utilisateurs_total": users.get("total_utilisateurs"),
            "utilisateurs_whatsapp_dans_users": users.get("utilisateurs_whatsapp_dans_users"),
            "utilisateurs_actifs_aujourdhui": len(active_today),
            "utilisateurs_actifs_7j": len(active_7d),
            "utilisateurs_actifs_30j": len(active_30d),
        },
        "whatsapp_metrics": {
            "tracking_enabled": whatsapp.get("tracking_enabled"),
            "error": whatsapp.get("error", ""),
            "messages_total": whatsapp.get("messages_entrants_suivis"),
            "users_total": whatsapp.get("utilisateurs_uniques"),
            "actifs_aujourdhui": whatsapp.get("utilisateurs_actifs_aujourdhui"),
            "returning_users_30min": whatsapp.get("utilisateurs_revenus_30min"),
            "return_rate_30min": whatsapp.get("taux_retour_30min"),
            "returning_users_2days": whatsapp.get("utilisateurs_revenus_2jours"),
            "return_rate_2days": whatsapp.get("taux_retour_2jours"),
            "matieres": whatsapp.get("matieres", {}),
            "series": whatsapp.get("series", {}),
            "stages": whatsapp.get("stages", {}),
            "top_utilisateurs": whatsapp.get("top_utilisateurs", []),
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
            "total_utilisateurs": users.get("utilisateurs_web_estimes", users["total_utilisateurs"]),
            "comptes_utilisateurs_total": users["total_utilisateurs"],
            "utilisateurs_web_estimes": users.get("utilisateurs_web_estimes", 0),
            "utilisateurs_whatsapp_dans_users": users.get("utilisateurs_whatsapp_dans_users", 0),
            "comptes_test": users.get("comptes_test", 0),
            "utilisateurs_non_classes": users.get("utilisateurs_non_classes", 0),
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
        "whatsapp_usage": whatsapp,
        "grand_pilote_metrics": grand_pilote,
        "web_feedback_metrics": web_feedback,
        "whatsapp_feedback_metrics": whatsapp_feedback,
        "feedback_metrics": feedback_metrics,
        "teacher_network": {
            "total_enseignants": teachers["total_enseignants"],
            "collections": teachers["collections"],
            "enseignants_par_statut": counter_to_dict(teachers["enseignants_par_statut"]),
            "enseignants_par_matiere": counter_to_dict(teachers["enseignants_par_matiere"]),
            "enseignants_par_niveau": counter_to_dict(teachers["enseignants_par_niveau"]),
            "enseignants_par_ville": counter_to_dict(teachers["enseignants_par_ville"]),
            "top_etablissements": counter_to_dict(teachers["enseignants_par_etablissement"], 15),
            "enseignants_par_statut_entretien": counter_to_dict(teachers["enseignants_par_statut_entretien"]),
            "enseignants_par_statut_prompt": counter_to_dict(teachers["enseignants_par_statut_prompt"]),
            "matieres_coeur_couvertes": teachers["matieres_coeur_couvertes"],
            "matieres_coeur_manquantes": teachers["matieres_coeur_manquantes"],
            "repertoire_enseignants": teachers["repertoire_enseignants"],
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
