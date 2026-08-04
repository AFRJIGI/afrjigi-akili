import json
from datetime import datetime, date
from google.cloud import firestore, storage
from collections import Counter

db = firestore.Client()
BUCKET_NAME = "akili-database-storage-astute-curve-307922"

# Normalisation des matières : regroupe les variantes (MATHS/Mathématiques, PHILO/Philosophie...)
# sous un nom unique et propre. Ajoute ici toute nouvelle variante repérée.
MATIERE_NORMALISATION = {
    "maths": "Mathématiques",
    "mathematiques": "Mathématiques",
    "mathématiques": "Mathématiques",
    "philo": "Philosophie",
    "philosophie": "Philosophie",
    "pc": "Physique-Chimie",
    "physique-chimie": "Physique-Chimie",
    "physique chimie": "Physique-Chimie",
    "svt": "SVT",
    "sciences de la vie et de la terre (svt)": "SVT",
    "histoire-geographie": "Histoire-Géographie",
    "histoire-géographie": "Histoire-Géographie",
    "histoire-geo": "Histoire-Géographie",
    "anglais": "Anglais",
    "anglais-oral": "Anglais",
    "allemand": "Allemand",
    "espagnol": "Espagnol",
    "francais-qrp": "Français",
    "français-qrp": "Français",
    "francais-commentaire": "Français",
    "français-commentaire": "Français",
    "francais-dissertation": "Français",
    "français-dissertation": "Français",
    "francais": "Français",
    "français": "Français",
    "litterature": "Français",
    "littérature": "Français",
}

def normaliser_matiere(valeur):
    v = (valeur or "").strip()
    if not v:
        return None
    return MATIERE_NORMALISATION.get(v.lower(), v)  # si inconnue, garde la valeur d'origine

def generer_rapport():
    users = list(db.collection("users").stream())
    total = len(users)
    ecoles = Counter()
    ages = Counter()
    series = Counter()
    matieres = Counter()
    genres = Counter()
    profils = Counter()
    actifs = 0
    total_q = 0
    for u in users:
        d = u.to_dict()
        total_q += d.get("questions_today", 0)
        if (d.get("nom_ecole") or "").strip(): ecoles[d["nom_ecole"].strip()] += 1
        if (d.get("tranche_age") or "").strip(): ages[d["tranche_age"].strip()] += 1
        if (d.get("serie") or "").strip(): series[d["serie"].strip()] += 1
        mat = normaliser_matiere(d.get("matiere"))
        if mat: matieres[mat] += 1
        if (d.get("genre") or "").strip(): genres[d["genre"].strip()] += 1
        if (d.get("profil_type") or "").strip(): profils[d["profil_type"].strip()] += 1
        if d.get("questions_today", 0) > 0: actifs += 1
    aujourdhui = date.today().isoformat()
    rapport = {
        "genere_le": datetime.now().isoformat(),
        "date": aujourdhui,
        "total_utilisateurs": total,
        "questions_aujourdhui": total_q,
        "utilisateurs_actifs": actifs,
        "taux_activation": round(actifs/total*100, 1) if total > 0 else 0,
        "series": dict(series.most_common()),
        "tranches_age": dict(ages.most_common()),
        "top_ecoles": dict(ecoles.most_common(10)),
        "genres": dict(genres.most_common()),
        "matieres": dict(matieres.most_common()),
        "profils": dict(profils.most_common()),
    }
    bucket = storage.Client().bucket(BUCKET_NAME)
    contenu = json.dumps(rapport, ensure_ascii=False, indent=2)
    bucket.blob("analytics/rapport_impact.json").upload_from_string(contenu, content_type="application/json")
    bucket.blob(f"analytics/historique/{aujourdhui}.json").upload_from_string(contenu, content_type="application/json")
    db.collection("analytics").document("rapport_quotidien").set(rapport)
    db.collection("analytics").document(aujourdhui).set(rapport)
    print(contenu)
    print(f"\nHistorique sauvegarde : analytics/historique/{aujourdhui}.json")

generer_rapport()
