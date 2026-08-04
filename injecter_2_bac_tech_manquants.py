import json
import os
import tempfile
from datetime import datetime
from google.cloud import storage

BUCKET_NAME = "akili-database-storage-astute-curve-307922"
DB_BLOB = "data/jigi_global_database.json"

FICHIERS = [
    {
        "upload_path": "ingestion_annales/BAC_TECH_TERMINALE/2018_SERIE-G1G2_ETUDE-CAS_DOCUMENT.pdf",
        "examen": "BAC_TECHNIQUE",
        "annee": "2018",
        "serie": "G1G2",
        "matiere": "ETUDE-CAS",
        "type_doc": "DOCUMENT",
    },
    {
        "upload_path": "ingestion_annales/BAC_TECH_TERMINALE/0000_SERIE-G2_TQG_DOCUMENT.docx",
        "examen": "BAC_TECHNIQUE",
        "annee": "INCONNUE",
        "serie": "G2",
        "matiere": "TQG",
        "type_doc": "DOCUMENT",
    },
]

client = storage.Client()
bucket = client.bucket(BUCKET_NAME)

db_blob = bucket.blob(DB_BLOB)
data = json.loads(db_blob.download_as_text())

docs = data.get("documents", [])
existing = {d.get("upload_path") for d in docs}

created = 0

for item in FICHIERS:
    upload_path = item["upload_path"]

    if upload_path in existing:
        print("Déjà présent:", upload_path)
        continue

    source_blob = bucket.blob(upload_path)
    if not source_blob.exists():
        print("ABSENT GCS:", upload_path)
        continue

    filename = upload_path.split("/")[-1]
    dest = (
        f"knowledge_base/{item['matiere']}/{item['serie']}/"
        f"{item['annee']}_{item['type_doc']}_{filename}"
    )

    print("Copie:", upload_path, "->", dest)
    bucket.copy_blob(source_blob, bucket, dest)

    new_doc = {
        "id": f"bac_tech_manual_{len(docs)+1}",
        "upload_path": upload_path,
        "storage_path": dest,
        "nom_fichier": filename,
        "examen": item["examen"],
        "annee": item["annee"],
        "serie": item["serie"],
        "matiere": item["matiere"],
        "type_doc": item["type_doc"],
        "source": "MANUAL_GCS_FIX",
        "resume": "Document BAC Technique ajouté manuellement après contrôle de complétude.",
        "texte_extrait": "",
        "score_qualite": 3,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }

    docs.append(new_doc)
    existing.add(upload_path)
    created += 1

data["documents"] = docs
data["total"] = len(docs)
data["generated_at"] = datetime.utcnow().isoformat() + "Z"

db_blob.upload_from_string(
    json.dumps(data, ensure_ascii=False, indent=2),
    content_type="application/json"
)

print("Documents ajoutés:", created)
print("Total base:", len(docs))
