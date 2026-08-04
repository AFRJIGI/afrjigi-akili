import json
from datetime import datetime
from collections import Counter
from google.cloud import storage

BUCKET_NAME = "akili-database-storage-astute-curve-307922"
DB_BLOB = "data/jigi_global_database.json"

TECH_SERIES = {
    "B", "G1", "G2", "G1G2", "BG1", "BG2", "BG1G2",
    "F", "F1", "F2", "F3", "F4", "F1F2F3F4", "STI"
}

TECH_MATIERES = {
    "ESTI", "ETUDE-CAS", "ECO", "COMPTA", "DROIT", "TQG",
    "OC", "EXPRO", "PHY-APP", "ELECTRO", "MESURE",
    "ECO-ENTREPRISE", "TRT-TEXTE", "ANALYSE-FONCT",
    "COMPTA-ANALYTIQUE", "COMPTA-FINANCIERE", "SES"
}

def norm(v):
    return str(v or "").strip().upper()

def infer_examen(d):
    txt = " ".join(str(d.get(k, "")) for k in [
        "upload_path", "storage_path", "nom_fichier", "serie", "matiere", "type_doc"
    ]).upper()

    serie = norm(d.get("serie"))
    matiere = norm(d.get("matiere"))

    if "BEPC" in txt or serie == "BEPC":
        return "BEPC"

    if (
        "BAC_TECH" in txt
        or "BAC-TECH" in txt
        or "BAC TECH" in txt
        or serie in TECH_SERIES
        or matiere in TECH_MATIERES
    ):
        return "BAC_TECHNIQUE"

    return "BAC_GENERAL"

client = storage.Client()
bucket = client.bucket(BUCKET_NAME)
blob = bucket.blob(DB_BLOB)

raw = blob.download_as_text()
data = json.loads(raw)
docs = data.get("documents", [])

timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
backup_blob = f"data/backups/jigi_global_database_before_examen_normalization_{timestamp}.json"
bucket.blob(backup_blob).upload_from_string(raw, content_type="application/json")
print("Backup créé:", f"gs://{BUCKET_NAME}/{backup_blob}")

before = Counter(str(d.get("examen", "INCONNU")).strip() or "INCONNU" for d in docs)

changed = 0
after = Counter()

for d in docs:
    old = str(d.get("examen", "")).strip()
    new = infer_examen(d)

    if old != new:
        d["examen"] = new
        changed += 1

    after[new] += 1

data["documents"] = docs
data["total"] = len(docs)
data["generated_at"] = datetime.utcnow().isoformat() + "Z"

blob.upload_from_string(
    json.dumps(data, ensure_ascii=False, indent=2),
    content_type="application/json"
)

print("Avant:", dict(before))
print("Après:", dict(after))
print("Documents modifiés:", changed)
print("Total:", len(docs))
