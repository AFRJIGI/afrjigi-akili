"""Injection versionnee des progressions officielles DPFC 2026-2027.

Mode par defaut: audit sans ecriture. Utiliser --apply pour sauvegarder la base,
copier les PDF officiels dans GCS, extraire leur texte et ajouter les entrees.
Les PROGRAMME, TP et COEFFICIENTS DPFC existants ne sont jamais supprimes.
"""

import argparse
import json
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

BASE = "https://dpfc-ci.net/dpfc/2027/progressions/"
DOCUMENTS = [
    ("ALLEMAND", "TOUS_CYCLES", "ALLEMAND_PROGRESSIONS%20NATIONALES_DPFC_2026-2027.pdf", "allemand"),
    ("ANGLAIS", "1ER_CYCLE", "ANGLAIS_1er%20cycle%20PROGRESSIONS_DPFC_2026_2027.pdf", "anglais_1er_cycle"),
    ("ANGLAIS", "2ND_CYCLE", "ANGLAIS_2nd%20Cycle_PROGRESSIONS%202nd%20cycle_DPFC_2026_2027.pdf", "anglais_2nd_cycle"),
    ("ARTS", "TOUS_CYCLES", "Arts%20Plastiques_PE%20Nouveaux_6%C3%A8-Tle_DPFC_2026_2027.pdf", "arts_plastiques"),
    ("EDHC", "TOUS_CYCLES", "EDHC_PROGRESSIONS%20ANNUELLES_DPFC_2026-2027.pdf", "edhc"),
    ("MUSIQUE", "TOUS_CYCLES", "Education%20Musicale_%20progression_DPFC_2026_2027.pdf", "education_musicale"),
    ("MUSIQUE", "ACCOMPAGNEMENT", "Education%20Musicale_DOCUMENT%20D%27accompagnement_DPFC_2026_2027.pdf", "education_musicale_accompagnement"),
    ("EPS", "1ER_CYCLE", "EPS_1er%20Cycle_PROGRESSION%201er%20CYCLE_DPFC_2026_2027.pdf", "eps_1er_cycle"),
    ("EPS", "2ND_CYCLE", "EPS_2nd%20Cycle_PROGRESSION%202nd%20CYCLE_DPFC_2026_2027.pdf", "eps_2nd_cycle"),
    ("ESPAGNOL", "TOUS_CYCLES", "ESPAGNOL-PROGRESSIONS_DPFC_2026_2027.pdf", "espagnol"),
    ("FRENCH", "1ER_CYCLE_ADMIN", "FRANCAIS_1er%20Cycle_2627_PROGRESSIONS_A%20USAGE%20ADMINISTRATIF_DPFC_2026_2027.pdf", "francais_1er_cycle_administratif"),
    ("FRENCH", "1ER_CYCLE_PEDAGO", "FRANCAIS_1er%20Cycle_2627_PROGRESSIONS_A%20USAGE%20PEDAGOGIQUE_DPFC_2026_2027.pdf", "francais_1er_cycle_pedagogique"),
    ("FRENCH", "2ND_CYCLE_ADMIN", "FRANCAIS_2nd%20Cycle_2627_PROGRESSIONS_A%20USAGE%20ADMINISTRATIF_DPFC_2026_2027.pdf", "francais_2nd_cycle_administratif"),
    ("FRENCH", "2ND_CYCLE_PEDAGO", "FRANCAIS_2nd%20Cycle_2627_PROGRESSIONS_A%20USAGE%20PEDAGOGIQUE_DPFC_2026_2027.pdf", "francais_2nd_cycle_pedagogique"),
    ("HG", "TOUS_CYCLES", "HG_PROGRESSIONS_DPFC_2026_2027.pdf", "histoire_geographie"),
    ("MATHS", "TOUS_CYCLES", "MATHEMATIQUES%20-%20Progressions%20annuelles_DPFC_2026_2027.pdf", "mathematiques"),
    ("PHILO", "2ND_CYCLE", "PHILOSOPHIE_PROGRESSIONS%20ANNUELLES_DPFC_2026_2027.pdf", "philosophie"),
    ("PC", "TOUS_CYCLES", "PHYSIQUE-CHIMIE_PROGRESSIONS%202026-2027_DPFC_2026_2027.pdf", "physique_chimie"),
    ("SVT", "TOUS_CYCLES", "SVT%20Progressions%20annuelles_DPFC_2026_2027.pdf", "svt"),
]


def download(url):
    request = urllib.request.Request(url, headers={"User-Agent": "AfrJigi-Akili/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response:
        content = response.read()
        if not content.startswith(b"%PDF-"):
            raise ValueError("La reponse recue n'est pas un PDF")
        return content


def extract_text(model, content):
    response = model.generate_content([
        Part.from_data(data=content, mime_type="application/pdf"),
        "Extrais fidelement le texte utile de cette progression pedagogique. "
        "Conserve les classes, mois, semaines, themes, lecons et competences. "
        "Ne produis aucun commentaire en dehors du texte extrait.",
    ])
    return (response.text or "").strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    client = storage.Client(project=PROJECT_ID)
    bucket = client.bucket(BUCKET_NAME)
    data = json.loads(bucket.blob(DB_BLOB).download_as_text(timeout=600))
    existing_ids = {d.get("id") for d in data.get("documents", [])}
    planned = []
    for subject, scope, remote_name, slug in DOCUMENTS:
        doc_id = f"dpfc_progression_{VERSION.replace('-', '_')}_{slug}"
        planned.append((doc_id, subject, scope, remote_name, slug, doc_id in existing_ids))

    print(f"Base actuelle: {len(data.get('documents', []))} documents")
    print(f"Progressions a creer: {sum(not p[5] for p in planned)}")
    print(f"Progressions deja presentes: {sum(p[5] for p in planned)}")
    for doc_id, subject, scope, _, _, exists in planned:
        print(f"{'SKIP' if exists else 'CREATE'} | {subject} | {scope} | {doc_id}")
    if not args.apply:
        print("Audit termine. Relancer avec --apply pour ecrire.")
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = f"data/backups/jigi_global_database_before_dpfc_progressions_{VERSION}_{stamp}.json"
    bucket.copy_blob(bucket.blob(DB_BLOB), bucket, backup)
    print(f"Backup: gs://{BUCKET_NAME}/{backup}")

    vertexai.init(project=PROJECT_ID, location=LOCATION)
    model = GenerativeModel("gemini-2.5-flash")
    created = 0
    for doc_id, subject, scope, remote_name, slug, exists in planned:
        if exists:
            continue
        url = BASE + remote_name
        content = download(url)
        filename = f"DPFC_2026-2027_{slug.upper()}.pdf"
        upload_path = f"ingestion_officielle/dpfc/{VERSION}/{filename}"
        destination = f"knowledge_base/{subject}/TOUTES/{VERSION}_PROGRESSION_ANNUELLE_{filename}"
        bucket.blob(upload_path).upload_from_string(content, content_type="application/pdf")
        bucket.copy_blob(bucket.blob(upload_path), bucket, destination)
        text = extract_text(model, content)
        if not text:
            raise RuntimeError(f"Extraction vide pour {filename}")
        data["documents"].append({
            "id": doc_id,
            "nom_fichier": filename,
            "chemin": destination,
            "matiere": subject,
            "serie": "TOUTES",
            "niveau": scope,
            "annee": VERSION,
            "version": VERSION,
            "type_doc": "PROGRESSION_ANNUELLE",
            "source": "DPFC_OFFICIEL",
            "score": 5,
            "texte": text,
            "resume": "Progression annuelle officielle DPFC 2026-2027",
            "official_url": url,
            "upload_path": upload_path,
            "integre_le": datetime.now(timezone.utc).isoformat(),
        })
        created += 1
        print(f"Cree: {doc_id} ({len(text)} caracteres)")

    data["total"] = len(data["documents"])
    data["generated_at"] = datetime.now(timezone.utc).isoformat()
    bucket.blob(DB_BLOB).upload_from_string(
        json.dumps(data, ensure_ascii=False, indent=2), content_type="application/json"
    )
    print(f"Termine: {created} ajouts; total={data['total']}")


if __name__ == "__main__":
    main()
