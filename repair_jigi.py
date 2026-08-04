import json
import os
from google.cloud import documentai_v1 as documentai

# Configuration
PROJECT_ID = "598190730734"
LOCATION = "us"
PROCESSOR_ID = "5a12933309f6be0d"
DB_FILE = "jigi_global_database.json"

def get_text_from_ocr(file_path):
    client = documentai.DocumentProcessorServiceClient()
    name = client.processor_path(PROJECT_ID, LOCATION, PROCESSOR_ID)
    
    with open(file_path, "rb") as image:
        image_content = image.read()

    raw_document = documentai.RawDocument(content=image_content, mime_type="application/pdf")
    request = documentai.ProcessRequest(name=name, raw_document=raw_document)
    
    result = client.process_document(request=request)
    return result.document.text

# Chargement de la base
with open(DB_FILE, 'r', encoding='utf-8') as f:
    full_data = json.load(f)

# On récupère la liste des documents
documents = full_data.get('documents', [])
print(f"🔍 Analyse de la base : {len(documents)} documents détectés.")

fixed_count = 0
for entry in documents:
    # On vérifie si le nombre de caractères est 0
    if entry.get('nb_caracteres') == 0:
        # On utilise 'chemin' qui est la clé dans ton JSON
        file_path = entry.get('chemin')
        
        # Correction pour s'assurer que le chemin est correct dans le Cloud Shell
        if not file_path.startswith('/home/'):
            file_path = os.path.join('/home/ddiarrassouba80/afrjigi-akili', file_path)

        if os.path.exists(file_path):
            print(f"🔄 Réparation de : {entry.get('nom_fichier')}...")
            try:
                extracted_text = get_text_from_ocr(file_path)
                entry['texte'] = extracted_text
                entry['nb_caracteres'] = len(extracted_text)
                entry['extraction_method'] = "DocumentAI_OCR"
                fixed_count += 1
                print(f"✅ Succès : {len(extracted_text)} caractères extraits.")
            except Exception as e:
                print(f"❌ Erreur sur {entry.get('nom_fichier')}: {e}")
        else:
            print(f"⚠️ Fichier introuvable : {file_path}")

# Sauvegarde
with open('jigi_global_database_FIXED.json', 'w', encoding='utf-8') as f:
    json.dump(full_data, f, ensure_ascii=False, indent=4)

print(f"\n✨ Mission terminée ! {fixed_count} fichiers réparés.")
