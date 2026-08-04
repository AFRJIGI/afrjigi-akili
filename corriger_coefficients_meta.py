import json
from datetime import datetime, timezone
from google.cloud import storage

BUCKET = "akili-database-storage-astute-curve-307922"
DB = "data/jigi_global_database.json"
TARGET = "DPFC_OFFICIEL_COEFFICIENTS_SECONDAIRE_GENERAL.pdf"

client = storage.Client()
bucket = client.bucket(BUCKET)
blob = bucket.blob(DB)

data = json.loads(blob.download_as_text())
docs = data.get("documents", [])

backup = f"data/backups/jigi_global_database_before_coefficients_meta_fix_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
bucket.copy_blob(blob, bucket, backup)
print("Backup:", f"gs://{BUCKET}/{backup}")

fixed = 0
for d in docs:
    if d.get("nom_fichier") == TARGET:
        d["examen"] = "BAC_GENERAL"
        d["annee"] = "2026"
        d["niveau"] = "SECONDAIRE_GENERAL"
        d["serie"] = "TOUTES"
        d["matiere"] = "ORIENTATION"
        d["type_doc"] = "COEFFICIENTS"
        d["source"] = "DPFC"
        d["storage_path"] = "knowledge_base/ORIENTATION/TOUTES/2026_COEFFICIENTS_DPFC_OFFICIEL_COEFFICIENTS_SECONDAIRE_GENERAL.pdf"
        d["upload_path"] = d.get("upload_path") or "ingestion_programmes/DPFC_OFFICIEL_COEFFICIENTS_SECONDAIRE_GENERAL.pdf"
        fixed += 1

data["documents"] = docs
data["total"] = len(docs)
data["generated_at"] = datetime.now(timezone.utc).isoformat()

blob.upload_from_string(json.dumps(data, ensure_ascii=False, indent=2), content_type="application/json")

print("Documents corrigés:", fixed)
print("Total:", len(docs))
