"""Audit puis injection additive des progressions IGETFPA d'anglais industriel.

Le mode par defaut ne fait aucune ecriture. ``--apply`` cree une sauvegarde de
la base GCS puis ajoute uniquement les neuf PDF 2024-2025 absents. Les copies
binaires publiees dans plusieurs dossiers du portail ne figurent qu'une fois
dans le manifeste.
"""

import argparse
import hashlib
import io
import json
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ID = "astute-curve-307922"
BUCKET = "akili-database-storage-astute-curve-307922"
DATABASE = "data/jigi_global_database.json"
VERSION = "2024-2025"

# ID portail, niveau, serie de recherche Akili, classe ecrite dans le PDF,
# fragments obligatoires apres extraction. Les IDs E sont les copies retenues
# pour les trois PDF identiques republies dans les dossiers F1, F2 et F3.
CANDIDATES = [
    (25511, "SECONDE", "EF1F2F3", "2NDE T1/F2", ("2NDE T1/F2", "TOOLS")),
    (25510, "PREMIERE", "EF1F2F3", "1ERE E-F1-F2-F3", ("1ERE E-F1-F2-F3", "RESOURCES")),
    (25512, "TERMINALE", "EF1F2F3", "TLE E-F1-F2-F3", ("TECHNOLOGY AND MATHEMATICS",)),
    (25659, "SECONDE", "F4", "2NDE T2", ("2 T2", "CIVIL ENGINEERING")),
    (25658, "PREMIERE", "F4", "1ERE F4", ("1ERE F4", "BUILDING MATERIALS")),
    (25660, "TERMINALE", "F4", "TLE F4", ("THE METHOD OF SCIENCE", "CONCRETE")),
    (25692, "SECONDE", "F7", "2NDE T3", ("2 T3", "OBJECTS IN A LAB")),
    (25691, "PREMIERE", "F7", "1ERE F7", ("1ERE F7", "PHOTOSYNTHESIS")),
    (25693, "TERMINALE", "F7", "TLE F7", ("TLE F7", "SAFETY MEASURES IN A LAB")),
]


def normalize(value):
    value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    return " ".join(value.upper().replace("’", "'").split())


def document_id(level, series):
    return f"metfpa_igetfpa_progression_anglais_2024_2025_{level.lower()}_{series.lower()}"


def filename(level, series):
    return f"METFPA_IGETFPA_2024-2025_ANGLAIS_{level}_{series}.pdf"


def inventory_match(inventory, portal_id):
    matches = [
        item for item in inventory
        if item.get("url", "").split("/")[-2].startswith(f"{portal_id}-")
    ]
    if len(matches) != 1:
        raise ValueError(f"Lien ambigu ou absent pour l'ID portail {portal_id}: {len(matches)}")
    return matches[0]


def download(url, max_attempts=6):
    separator = "&" if "?" in url else "?"
    request = urllib.request.Request(
        f"{url}{separator}force_download=1",
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
                f"Telechargement temporairement indisponible ({attempt}/{max_attempts}): "
                f"{exc}; nouvel essai dans {delay}s"
            )
            time.sleep(delay)
    raise RuntimeError(f"Echec du telechargement apres {max_attempts} essais: {url}") from last_error


def extract_pdf_text(content):
    from pypdf import PdfReader

    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)


def validate_text(text, expected_terms):
    normalized = normalize(text)
    required = ("SEPTEMBRE 2024", "2024-2025", *expected_terms)
    missing = [term for term in required if normalize(term) not in normalized]
    if missing:
        raise ValueError(f"Contenu inattendu; fragments absents: {missing}")


def build_document(portal_id, level, series, source_class, url, content, text):
    digest = hashlib.sha256(content).hexdigest()
    name = filename(level, series)
    return {
        "id": document_id(level, series),
        "nom_fichier": name,
        "chemin": f"ingestion_officielle/metfpa/anglais/{VERSION}/{digest}.pdf",
        "matiere": "ANGLAIS",
        "discipline": "ANGLAIS_DES_SPECIALITES",
        "examen": "BAC_TECHNIQUE",
        "serie": series,
        "niveau": level,
        "classe_source": source_class,
        "annee": VERSION,
        "annee_scolaire": VERSION,
        "version": VERSION,
        "edition_source": "Septembre 2024",
        "type_doc": "PROGRESSION_ANNUELLE",
        "source": "METFPA_IGETFPA",
        "institution": "METFPA",
        "institution_catalogue": "IGETFPA",
        "portail_source": "FOMESOUTRA",
        "statut_source": "MIROIR_FOMESOUTRA",
        "source_url": url,
        "source_portal_id": portal_id,
        "sha256": digest,
        "texte": text,
        "score": 5,
        "resume": (
            f"Progression IGETFPA d'anglais des specialites, {source_class}, "
            f"annee scolaire {VERSION}"
        ),
    }


def plan(existing, candidates):
    """Retourne les ajouts apres deduplication par ID, URL, PDF et texte."""
    ids = {doc.get("id") for doc in existing}
    urls = {doc.get("source_url") for doc in existing if doc.get("source_url")}
    hashes = {doc.get("sha256") for doc in existing if doc.get("sha256")}
    texts = {
        normalize(doc.get("texte"))
        for doc in existing
        if isinstance(doc.get("texte"), str) and doc.get("texte").strip()
    }
    additions = []
    for doc in candidates:
        normalized_text = normalize(doc.get("texte"))
        duplicate = (
            doc["id"] in ids
            or doc["source_url"] in urls
            or doc["sha256"] in hashes
            or normalized_text in texts
        )
        print(
            f"{'SKIP' if duplicate else 'CREATE'} | {doc['niveau']} | "
            f"{doc['serie']} | {doc['id']}"
        )
        if duplicate:
            continue
        additions.append(doc)
        ids.add(doc["id"])
        urls.add(doc["source_url"])
        hashes.add(doc["sha256"])
        texts.add(normalized_text)
    return additions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    from google.cloud import storage

    root = Path(__file__).parent
    inventory = json.loads(
        (root / "reports/bac_technique_progressions_inventory.json").read_text(encoding="utf-8")
    )["inventaire"]

    client = storage.Client(project=PROJECT_ID)
    bucket = client.bucket(BUCKET)
    blob = bucket.blob(DATABASE)
    blob.reload()
    generation = int(blob.generation)
    original = blob.download_as_bytes(if_generation_match=generation, timeout=600)
    data = json.loads(original)
    existing = data["documents"]
    existing_ids = {doc.get("id") for doc in existing}
    existing_urls = {doc.get("source_url") for doc in existing if doc.get("source_url")}
    print(f"Base actuelle: {len(existing)} documents")

    candidates = []
    pdfs = {}
    preexisting = 0
    for portal_id, level, series, source_class, expected_terms in CANDIDATES:
        item = inventory_match(inventory, portal_id)
        url = item["url"]
        doc_id = document_id(level, series)
        if doc_id in existing_ids or url in existing_urls:
            preexisting += 1
            print(f"SKIP | {level} | {series} | {doc_id}")
            continue
        content = download(url)
        text = extract_pdf_text(content)
        validate_text(text, expected_terms)
        doc = build_document(portal_id, level, series, source_class, url, content, text)
        candidates.append(doc)
        pdfs[doc["sha256"]] = content

    additions = plan(existing, candidates)
    print(f"Progressions deja presentes: {preexisting}")
    print(f"Ajouts proposes: {len(additions)}; total prevu: {len(existing) + len(additions)}")
    if not args.apply:
        print("Audit termine, aucune ecriture.")
        return
    if not additions:
        print("Aucun ajout necessaire.")
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = f"data/backups/jigi_global_database_before_anglais_industriel_{stamp}.json"
    bucket.blob(backup).upload_from_string(
        original,
        content_type="application/json",
        if_generation_match=0,
    )
    print(f"Backup: gs://{BUCKET}/{backup}")

    integrated_at = datetime.now(timezone.utc).isoformat()
    for doc in additions:
        target = bucket.blob(doc["chemin"])
        if not target.exists():
            target.upload_from_string(
                pdfs[doc["sha256"]],
                content_type="application/pdf",
                if_generation_match=0,
            )
        doc["integre_le"] = integrated_at

    data["documents"].extend(additions)
    data["total"] = len(data["documents"])
    data["generated_at"] = integrated_at
    blob.upload_from_string(
        json.dumps(data, ensure_ascii=False, indent=2),
        content_type="application/json",
        if_generation_match=generation,
    )
    print(f"Termine: {len(additions)} ajouts; total={data['total']}")


if __name__ == "__main__":
    main()
