"""Progressions de Terminale F2 transmises par M. Sidibe (annee 2024-2025, progression commune
des lycees techniques d'Abidjan et de Bouake) : Construction mecanique industrielle (CMI) et
Mecanique appliquee.

Le texte, verifie sur les PDF, est dans donnees/progressions_m_sidibe_tf2.json. Meme regle que
pour les progressions de M. Brou : une classe sans progression est ajoutee ; une progression
deja presente (memes lecons) n'est pas dupliquee ; si le texte present ne contient pas les
lecons (PDF mal lu), cette version est ajoutee et preferee (priorite 1).

  python3 injecter_progressions_m_sidibe.py            # audit, aucune ecriture
  python3 injecter_progressions_m_sidibe.py --apply    # sauvegarde la base puis ajoute

Redeployer akili-api ensuite.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from injecter_progressions_maths_brou import SEUIL_COUVERTURE, couverture, lecons, serie_match, series_couvertes

BUCKET = "akili-database-storage-astute-curve-307922"
DATABASE = "data/jigi_global_database.json"
DONNEES = Path(__file__).with_name("donnees") / "progressions_m_sidibe_tf2.json"


def identifiant(doc):
    return f"sidibe_progression_{doc['matiere'].lower()}_{doc['niveau'].lower()}_{doc['serie'].lower()}"


def comparer(base, doc):
    mes_series = series_couvertes(doc["serie"])
    titres = lecons(doc["texte"])
    return [
        (d, couverture(titres, d.get("texte", "")))
        for d in base
        if str(d.get("type_doc") or "").upper().startswith("PROGRESSION")
        and str(d.get("matiere") or "").upper() == doc["matiere"]
        and str(d.get("examen") or "").upper() in {"BAC_TECHNIQUE", "TOUS"}
        and doc["niveau"] in str(d.get("niveau") or "").upper().split("_")
        and any(serie_match(d.get("serie"), s) for s in mes_series)
    ]


def decider(base, doc):
    if any(d.get("sha256") == doc["sha256"] or d.get("id") == identifiant(doc) for d in base):
        return "DEJA", 0, "deja injecte"
    existants = comparer(base, doc)
    if not existants:
        return "CREER", 0, "aucune progression pour cette matiere et cette classe"
    meilleur = max(existants, key=lambda x: x[1])
    if meilleur[1] >= SEUIL_COUVERTURE:
        return "DEJA", 0, f"meme progression deja presente ({meilleur[0].get('id')}, {meilleur[1]:.0%} des lecons)"
    return "CREER", 1, (f"le texte present ({meilleur[0].get('id')}) ne contient que {meilleur[1]:.0%} des lecons :"
                        " cette version sera preferee")


def document_base(doc, priorite, transmis_par):
    return dict(
        id=identifiant(doc), nom_fichier=doc["fichier"], chemin=f"enseignants/sidibe/{doc['sha256']}.pdf",
        matiere=doc["matiere"], examen="BAC_TECHNIQUE", serie=doc["serie"], niveau=doc["niveau"],
        classe_source=doc["classe_source"], annee="2024-2025", version="2024-2025",
        edition_source=doc["edition_source"], type_doc="PROGRESSION_ANNUELLE", source="ENSEIGNANT",
        institution="des lycées techniques d'Abidjan et de Bouaké", transmis_par=transmis_par,
        sha256=doc["sha256"], texte=doc["texte"], score=5, priorite=priorite,
        resume=f"Progression {doc['libelle']} (2024-2025), transmise par {transmis_par}",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    from google.cloud import storage

    paquet = json.loads(DONNEES.read_text(encoding="utf-8"))
    bucket = storage.Client(project="astute-curve-307922").bucket(BUCKET)
    blob = bucket.blob(DATABASE)
    blob.reload()
    generation = int(blob.generation)
    original = blob.download_as_bytes(if_generation_match=generation, timeout=600)
    data = json.loads(original)
    print(f"Base actuelle : {len(data['documents'])} documents\n")
    ajouts = []
    for doc in paquet["documents"]:
        decision, priorite, pourquoi = decider(data["documents"], doc)
        print(f"{decision:5} | {doc['matiere']:20} {doc['niveau']} {doc['serie']} | {pourquoi}")
        if decision == "CREER":
            ajouts.append(document_base(doc, priorite, paquet["transmis_par"]))
    print(f"\nAjouts proposes : {len(ajouts)} ; total prevu : {len(data['documents']) + len(ajouts)}")
    if not args.apply or not ajouts:
        print("Audit termine, aucune ecriture." if not args.apply else "Rien a ajouter.")
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sauvegarde = f"data/backups/jigi_global_database_avant_sidibe_{stamp}.json"
    bucket.blob(sauvegarde).upload_from_string(original, content_type="application/json", if_generation_match=0)
    print(f"Sauvegarde : gs://{BUCKET}/{sauvegarde}")
    maintenant = datetime.now(timezone.utc).isoformat()
    for d in ajouts:
        d["integre_le"] = maintenant
    data["documents"].extend(ajouts)
    data["total"] = len(data["documents"])
    data["generated_at"] = maintenant
    blob.upload_from_string(json.dumps(data, ensure_ascii=False, indent=2), content_type="application/json",
                            if_generation_match=generation)
    print(f"Termine : {len(ajouts)} ajouts ; total {data['total']}. Redeploie akili-api.")


if __name__ == "__main__":
    main()
