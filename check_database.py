import json
from collections import Counter

with open("jigi_global_database_FIXED.json", "r", encoding="utf-8") as f:
    db = json.load(f)

documents = db["documents"]

ok      = [d for d in documents if d.get("texte")]
echecs  = [d for d in documents if not d.get("texte")]
ocr     = [d for d in documents if d.get("ocr_method") == "document-ai"]

print(f"📊 Total documents     : {len(documents)}")
print(f"✅ Avec texte          : {len(ok)}")
print(f"🤖 Via Document AI OCR : {len(ocr)}")
print(f"❌ Sans texte          : {len(echecs)}")

if echecs:
    print("\n─── Fichiers sans texte ───")
    for e in echecs:
        print(f"  • {e['nom_fichier']}")

matieres = Counter(d["matiere"] for d in ok)
print("\n─── Par matière ───")
for k, v in sorted(matieres.items()):
    print(f"  {k:15} : {v:3}")
