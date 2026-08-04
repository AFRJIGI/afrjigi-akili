import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess

BUCKET_DB = "gs://akili-database-storage-astute-curve-307922/data/jigi_global_database.json"
BUCKET_BACKUP_DIR = "gs://akili-database-storage-astute-curve-307922/data/backups"
TARGET = "DPFC_OFFICIEL_COEFFICIENTS_SECONDAIRE_GENERAL.pdf"

local_db = Path("jigi_global_database_coeff_fix.json")
backup_name = f"jigi_global_database_before_coefficients_meta_fix_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"

print("Téléchargement base...")
subprocess.run(["gcloud", "storage", "cp", BUCKET_DB, str(local_db)], check=True)

print("Backup cloud...")
subprocess.run(["gcloud", "storage", "cp", str(local_db), f"{BUCKET_BACKUP_DIR}/{backup_name}"], check=True)

data = json.loads(local_db.read_text(encoding="utf-8"))
docs = data.get("documents", [])

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

local_db.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

print("Upload base corrigée...")
subprocess.run(["gcloud", "storage", "cp", str(local_db), BUCKET_DB], check=True)

print("Documents corrigés:", fixed)
print("Total:", len(docs))
print("Backup:", f"{BUCKET_BACKUP_DIR}/{backup_name}")
