import json
from google.cloud import storage
from datetime import datetime
import vertexai
from vertexai.generative_models import GenerativeModel, Part

PROJECT_ID  = "astute-curve-307922"
BUCKET_NAME = "akili-database-storage-astute-curve-307922"
DB_BLOB     = "data/jigi_global_database.json"

vertexai.init(project=PROJECT_ID, location="us-central1")
model = GenerativeModel("gemini-2.5-flash")

# Liste des gros documents a ingerer (lus depuis GCS).
# upload_path = chemin GCS source (cle anti-doublon, comme pipeline_bepc.py)
FICHIERS = [
    {"upload_path": "ingestion_annales/COEFFICIENTS/DPFC_OFFICIEL_COEFFICIENTS_SECONDAIRE_GENERAL.pdf", "matiere": "ORIENTATION", "serie": "TOUTES", "annee": "2026", "type_doc": "COEFFICIENTS"},
]

def load_database():
    client = storage.Client()
    data = json.loads(client.bucket(BUCKET_NAME).blob(DB_BLOB).download_as_text(timeout=600))
    print(f"Base chargee : {len(data.get('documents', []))} documents")
    return data

def save_database(data):
    client = storage.Client()
    data["generated_at"] = datetime.now().isoformat()
    data["total"] = len(data["documents"])
    client.bucket(BUCKET_NAME).blob(DB_BLOB).upload_from_string(
        json.dumps(data, ensure_ascii=False, indent=2), content_type="application/json")
    print(f"Base sauvegardee : {data['total']} documents")

def extraire_texte_docx(file_bytes):
    """Extrait le texte d'un fichier .docx directement (pas besoin de Vertex AI)."""
    import docx, io
    try:
        doc = docx.Document(io.BytesIO(file_bytes))
        paragraphes = [p.text for p in doc.paragraphs if p.text.strip()]
        # Inclure aussi le texte des tableaux (frequent dans les progressions)
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    if cell.text.strip():
                        paragraphes.append(cell.text.strip())
        return "\n".join(paragraphes).strip()
    except Exception as e:
        print(f"  Erreur extraction docx : {e}")
        return ""

def extraire_texte(file_bytes):
    try:
        part = Part.from_data(data=file_bytes, mime_type="application/pdf")
        response = model.generate_content([part,
            "Extrais tout le texte de ce document PDF de maniere complete et fidele. "
            "Inclus tous les exercices, enonces, questions, reponses, lecons et contenus. "
            "Reponds uniquement avec le texte extrait sans commentaire."])
        # Concatenation manuelle de toutes les parts (plus robuste que response.text
        # qui echoue silencieusement si Gemini renvoie plusieurs parts)
        try:
            parts_text = [p.text for p in response.candidates[0].content.parts if hasattr(p, "text") and p.text]
            texte_final = "\n\n".join(parts_text).strip()
            if texte_final:
                return texte_final
        except Exception:
            pass
        # Fallback sur response.text si la methode ci-dessus echoue
        return (response.text or "").strip()
    except Exception as e:
        print(f"  Erreur extraction : {e}")
        return ""

def run():
    data = load_database()
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)

    # Anti-doublon : upload_path deja presents
    deja = set(d.get("upload_path", "") for d in data["documents"])
    crees = 0

    for f in FICHIERS:
        up = f["upload_path"]
        nom_fichier = up.split("/")[-1]
        print(f"\nTraitement : {nom_fichier}")

        if up in deja:
            print("  Deja dans la base (upload_path) -> ignore")
            continue

        try:
            # Lire le PDF DEPUIS GCS
            blob = bucket.blob(up)
            file_bytes = blob.download_as_bytes(timeout=600)
            print(f"  Taille : {len(file_bytes)} bytes")

            if nom_fichier.lower().endswith(".docx"):
                texte = extraire_texte_docx(file_bytes)
            else:
                texte = extraire_texte(file_bytes)
            print(f"  Texte extrait : {len(texte)} caracteres")
            if not texte:
                print("  Texte vide -> non cree")
                continue

            matiere  = f["matiere"]
            serie    = f["serie"]
            annee    = f["annee"]
            type_doc = f["type_doc"]
            dest = f"knowledge_base/{matiere}/{serie}/{annee}_{type_doc}_{nom_fichier}"

            # Copier vers knowledge_base/ (comme pipeline_bepc.py)
            bucket.copy_blob(blob, bucket, dest)

            data["documents"].append({
                "id": dest.replace("/", "_"),
                "nom_fichier": nom_fichier,
                "chemin": dest,
                "matiere": matiere,
                "serie": serie,
                "annee": annee,
                "type_doc": type_doc,
                "source": "ingestion_gros_doc",
                "score": 5,
                "texte": texte,
                "resume": "",
                "integre_le": datetime.now().isoformat(),
                "upload_path": up,
            })
            crees += 1
            save_database(data)
            print(f"  Cree dans la base -> {dest}")

        except Exception as e:
            print(f"  Erreur : {e}")

    print(f"\nTermine : {crees} documents crees")

run()