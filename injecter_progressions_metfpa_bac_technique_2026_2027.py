"""Injection versionnee des progressions METFPA BAC Technique 2026-2027.

Le mode par defaut est un audit sans ecriture. Utiliser --apply pour creer une
sauvegarde GCS, telecharger les PDF du miroir Fomesoutra, extraire leur texte
et ajouter les documents absents. Aucun document existant n'est supprime.
"""

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from google.cloud import storage
import vertexai
from vertexai.generative_models import GenerativeModel, Part


PROJECT_ID = "astute-curve-307922"
LOCATION = "us-central1"
BUCKET_NAME = "akili-database-storage-astute-curve-307922"
DB_BLOB = "data/jigi_global_database.json"
VERSION = "2026-2027"


DOCUMENTS = [
    ("GEOGRAPHIE", "PREMIERE", "F1F2F3F4F7", "29064-progression-2026-27-geographie-premiere-f-by-tehua"),
    ("GEOGRAPHIE", "PREMIERE", "B", "29063-progression-2026-27-geographie-premiere-b-by-tehua"),
    ("GEOGRAPHIE", "PREMIERE", "G1G2", "29062-progression-2026-27-geographie-premiere-g-et-h-by-tehua"),
    ("GEOGRAPHIE", "SECONDE", "B", "29061-progression-2026-27-geographie-seconde-ab-by-tehua"),
    ("GEOGRAPHIE", "SECONDE", "G1G2", "29060-progression-2026-27-geographie-seconde-g-et-h-by-tehua"),
    ("GEOGRAPHIE", "TERMINALE", "B", "29059-progression-2026-27-geographie-terminale-b-by-tehua"),
    ("GEOGRAPHIE", "TERMINALE", "G1G2", "29058-progression-2026-27-geographie-terminale-g-et-h-by-tehua"),
    ("HISTOIRE", "PREMIERE", "B", "29057-progression-2026-27-histoire-premiere-b-by-tehua"),
    ("HISTOIRE", "PREMIERE", "G1G2", "29056-progression-2026-27-histoire-premiere-g-et-h-by-tehua"),
    ("HISTOIRE", "SECONDE", "B", "29055-progression-2026-27-histoire-seconde-ab-by-tehua"),
    ("HISTOIRE", "SECONDE", "G1G2", "29054-progression-2026-27-histoire-seconde-g-et-h-by-tehua"),
    ("HISTOIRE", "TERMINALE", "B", "29053-progression-2026-27-histoire-terminale-b-by-tehua"),
    ("HISTOIRE", "TERMINALE", "G1G2", "29052-progression-2026-27-histoire-terminale-g-et-h-by-tehua"),
    ("GEOGRAPHIE", "PREMIERE", "E", "29045-progression-geographie-2026-27-premiere-e-by-tehua"),
    ("GEOGRAPHIE", "SECONDE", "EF1F2F3F4F7", "29044-progression-geographie-2026-27-seconde-t-et-f-by-tehua"),
    ("HISTOIRE", "PREMIERE", "E", "29043-progression-histoire-2026-27-premiere-e-by-tehua"),
    ("HISTOIRE", "PREMIERE", "F1F2F3F4F7", "29042-progression-histoire-2026-27-premiere-f-by-tehua"),
    ("HISTOIRE", "SECONDE", "EF1F2F3F4F7", "29041-progression-histoire-2026-27-seconde-t-et-f-b-y-tehua"),
]

FOLDER_URL = (
    "https://www.fomesoutra.com/livres/"
    "metfpa-ministere-de-lenseignement-technique-de-la-formation-professionnelle-et-de-lapprentissage/"
    "progressions-de-lenseignement-technique-et-professionnel/histoire-geographie-du-technique/"
)


def source_url(slug):
    return f"{FOLDER_URL}{slug}/file"


def document_id(discipline, niveau, serie):
    return (
        f"metfpa_progression_{VERSION.replace('-', '_')}_"
        f"{discipline.lower()}_{niveau.lower()}_{serie.lower()}"
    )


def filename(discipline, niveau, serie):
    return f"METFPA_{VERSION}_{discipline}_{niveau}_{serie}.pdf"


def download(url, max_attempts=6):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "AfrJigi-Akili/1.0",
            "Accept-Encoding": "identity",
            "Connection": "close",
        },
    )
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                content = response.read()
            if not content.startswith(b"%PDF-"):
                raise ValueError(f"La reponse recue n'est pas un PDF: {url}")
            return content
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt == max_attempts:
                break
            delay = min(5 * attempt, 30)
            print(
                f"Telechargement temporairement indisponible "
                f"({attempt}/{max_attempts}): {exc}; nouvel essai dans {delay}s"
            )
            time.sleep(delay)
    raise RuntimeError(f"Echec du telechargement apres {max_attempts} essais: {url}") from last_error


def extract_text(model, content, discipline, niveau, serie, max_attempts=4):
    prompt = (
        "Extrais fidelement le texte utile de cette progression METFPA "
        f"de {discipline}, niveau {niveau}, serie {serie}. Conserve les "
        "semaines, themes, lecons, competences et volumes horaires. "
        "Ne produis aucun commentaire en dehors du texte extrait."
    )
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = model.generate_content([
                Part.from_data(data=content, mime_type="application/pdf"),
                prompt,
            ])
            text = (response.text or "").strip()
            if not text:
                raise RuntimeError("Extraction Vertex vide")
            return text
        except Exception as exc:
            last_error = exc
            if attempt == max_attempts:
                break
            delay = min(10 * attempt, 30)
            print(
                f"Extraction temporairement indisponible "
                f"({attempt}/{max_attempts}): {exc}; nouvel essai dans {delay}s"
            )
            time.sleep(delay)
    raise RuntimeError(
        f"Echec de l'extraction apres {max_attempts} essais: "
        f"{discipline} {niveau} {serie}"
    ) from last_error


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    client = storage.Client(project=PROJECT_ID)
    bucket = client.bucket(BUCKET_NAME)
    data = json.loads(bucket.blob(DB_BLOB).download_as_text(timeout=600))
    existing_ids = {doc.get("id") for doc in data.get("documents", [])}
    existing_urls = {doc.get("source_url") for doc in data.get("documents", [])}

    planned = []
    for discipline, niveau, serie, slug in DOCUMENTS:
        doc_id = document_id(discipline, niveau, serie)
        url = source_url(slug)
        exists = doc_id in existing_ids or url in existing_urls
        planned.append((discipline, niveau, serie, slug, doc_id, url, exists))

    print(f"Base actuelle: {len(data.get('documents', []))} documents")
    print(f"Progressions METFPA a creer: {sum(not item[6] for item in planned)}")
    print(f"Progressions METFPA deja presentes: {sum(item[6] for item in planned)}")
    for discipline, niveau, serie, _, doc_id, _, exists in planned:
        print(f"{'SKIP' if exists else 'CREATE'} | {discipline} | {niveau} | {serie} | {doc_id}")

    if not args.apply:
        print("Audit termine. Relancer avec --apply pour ecrire.")
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = f"data/backups/jigi_global_database_before_metfpa_bac_tech_{VERSION}_{stamp}.json"
    bucket.copy_blob(bucket.blob(DB_BLOB), bucket, backup)
    print(f"Backup: gs://{BUCKET_NAME}/{backup}")

    vertexai.init(project=PROJECT_ID, location=LOCATION)
    model = GenerativeModel("gemini-2.5-flash")
    known_hashes = {doc.get("sha256") for doc in data.get("documents", []) if doc.get("sha256")}
    created = 0
    duplicate_hashes = 0

    for discipline, niveau, serie, _, doc_id, url, exists in planned:
        if exists:
            continue
        content = download(url)
        digest = hashlib.sha256(content).hexdigest()
        if digest in known_hashes:
            duplicate_hashes += 1
            print(f"DOUBLON SHA256: {doc_id}")
            continue

        name = filename(discipline, niveau, serie)
        upload_path = f"ingestion_officielle/metfpa/{VERSION}/bac_technique/{name}"
        destination = f"knowledge_base/HG/{serie}/{VERSION}_PROGRESSION_ANNUELLE_{name}"
        bucket.blob(upload_path).upload_from_string(content, content_type="application/pdf")
        bucket.copy_blob(bucket.blob(upload_path), bucket, destination)

        text = extract_text(model, content, discipline, niveau, serie)
        if not text:
            raise RuntimeError(f"Extraction vide pour {name}")

        data["documents"].append({
            "id": doc_id,
            "nom_fichier": name,
            "chemin": destination,
            "upload_path": upload_path,
            "matiere": "HG",
            "discipline": discipline,
            "serie": serie,
            "examen": "BAC_TECHNIQUE",
            "niveau": niveau,
            "annee": VERSION,
            "version": VERSION,
            "type_doc": "PROGRESSION_ANNUELLE",
            "source": "METFPA_OFFICIEL",
            "institution": "METFPA",
            "ministere": (
                "Ministere de l'Enseignement Technique, de la Formation "
                "Professionnelle et de l'Apprentissage"
            ),
            "portail_source": "FOMESOUTRA",
            "statut_source": "MIROIR_FOMESOUTRA",
            "source_url": url,
            "sha256": digest,
            "score": 5,
            "texte": text,
            "resume": f"Progression annuelle METFPA {discipline} {niveau} {serie} {VERSION}",
            "integre_le": datetime.now(timezone.utc).isoformat(),
        })
        known_hashes.add(digest)
        created += 1
        print(f"Cree: {doc_id} ({len(text)} caracteres)")
        time.sleep(2)

    data["total"] = len(data["documents"])
    data["generated_at"] = datetime.now(timezone.utc).isoformat()
    bucket.blob(DB_BLOB).upload_from_string(
        json.dumps(data, ensure_ascii=False, indent=2),
        content_type="application/json",
    )
    print(
        f"Termine: {created} ajouts; {duplicate_hashes} doublons SHA256; "
        f"total={data['total']}"
    )


if __name__ == "__main__":
    main()
