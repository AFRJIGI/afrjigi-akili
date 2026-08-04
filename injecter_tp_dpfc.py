import json
import re
import zipfile
import io
from datetime import datetime, timezone
from xml.etree import ElementTree as ET
from google.cloud import storage

BUCKET_NAME = "akili-database-storage-astute-curve-307922"
DB_BLOB = "data/jigi_global_database.json"

PREFIXES = [
    "ingestion_tp/PC/",
    "ingestion_tp/SVT/",
]

FILENAME_RE = re.compile(
    r"^DPFC_(?P<examen>BEPC|BAC_GENERAL|BAC_TECHNIQUE)_(?P<niveau>[^_]+)_SERIE-(?P<serie>[^_]+)_(?P<matiere>PC|SVT)_TP_(?P<titre>.+)\.docx$"
)

def utc_stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

def extract_docx_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml")
        root = ET.fromstring(xml)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        texts = []
        for node in root.findall(".//w:t", ns):
            if node.text:
                texts.append(node.text)
        return "\n".join(texts).strip()
    except Exception as e:
        print(f"  ⚠️ Extraction DOCX échouée: {e}")
        return ""

def main():
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)
    db_blob = bucket.blob(DB_BLOB)

    data = json.loads(db_blob.download_as_text())
    docs = data.get("documents", [])

    backup_path = f"data/backups/jigi_global_database_before_tp_dpfc_{utc_stamp()}.json"
    bucket.copy_blob(db_blob, bucket, backup_path)
    print(f"Backup créé: gs://{BUCKET_NAME}/{backup_path}")

    existing_uploads = {d.get("upload_path") for d in docs if d.get("upload_path")}
    existing_names = {d.get("nom_fichier") for d in docs if d.get("nom_fichier")}

    created = 0
    skipped = 0
    errors = 0

    blobs = []
    for prefix in PREFIXES:
        blobs.extend(list(client.list_blobs(BUCKET_NAME, prefix=prefix)))

    blobs = [b for b in blobs if b.name.lower().endswith(".docx")]
    print(f"Fichiers TP trouvés dans GCS: {len(blobs)}")

    for blob in sorted(blobs, key=lambda b: b.name):
        filename = blob.name.split("/")[-1]
        print(f"\nTraitement: {filename}")

        if blob.name in existing_uploads or filename in existing_names:
            print("  Déjà dans la base -> ignore")
            skipped += 1
            continue

        m = FILENAME_RE.match(filename)
        if not m:
            print("  ❌ Nom non conforme -> ignore")
            errors += 1
            continue

        meta = m.groupdict()
        examen = meta["examen"]
        niveau = meta["niveau"]
        serie = meta["serie"]
        matiere = meta["matiere"]
        titre = meta["titre"].replace("-", " ")

        raw = blob.download_as_bytes()
        texte = extract_docx_text(raw)

        storage_path = f"knowledge_base/{matiere}/{serie}/{niveau}_TP_{filename}"
        dest_blob = bucket.blob(storage_path)

        if not dest_blob.exists():
            bucket.copy_blob(blob, bucket, storage_path)

        doc = {
            "source": "DPFC_TP",
            "examen": examen,
            "annee": niveau,
            "niveau": niveau,
            "serie": serie,
            "matiere": matiere,
            "type_doc": "TP",
            "titre": titre,
            "nom_fichier": filename,
            "upload_path": blob.name,
            "storage_path": storage_path,
            "texte": texte,
            "score_qualite": 4,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        docs.append(doc)
        created += 1
        print(f"  Créé -> {storage_path}")
        print(f"  Texte extrait: {len(texte)} caractères")

    data["documents"] = docs
    data["total"] = len(docs)
    data["generated_at"] = datetime.now(timezone.utc).isoformat()

    db_blob.upload_from_string(
        json.dumps(data, ensure_ascii=False, indent=2),
        content_type="application/json"
    )

    print("\n=== RÉSUMÉ ===")
    print(f"Créés: {created}")
    print(f"Ignorés déjà existants: {skipped}")
    print(f"Erreurs: {errors}")
    print(f"Total base: {len(docs)}")

if __name__ == "__main__":
    main()
