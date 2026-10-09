"""Fiche de lecon « Limites et continuite » (Terminale D) transmise par M. Sidibe Zoumana, enseignant de
mathematiques (fichier "Fiche lecon 1 - Limites et continuite - Tle D_4.pdf", 15 seances de 55 min).

Les formules du PDF etant cassees a l'extraction, la fiche a ete transcrite dans
donnees/cours_limites_continuite_m_sidibe_zoumana_transcription.txt puis decoupee par seance dans
donnees/cours_limites_m_sidibe_zoumana.json (script donnees/construire_cours_limites_m_sidibe_zoumana.py).
Chaque extrait devient un document COURS_ESSENTIEL de MATHS, BAC general, Terminale D, et aussi de la serie C
(meme lecon au programme de Terminale C).

  python3 injecter_cours_limites_sidibe_zoumana.py            # audit, aucune ecriture
  python3 injecter_cours_limites_sidibe_zoumana.py --apply    # sauvegarde la base puis ajoute

Redeployer akili-api ensuite : l'API charge la base au demarrage.
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

BUCKET = "akili-database-storage-astute-curve-307922"
DATABASE = "data/jigi_global_database.json"
DONNEES = Path(__file__).with_name("donnees") / "cours_limites_m_sidibe_zoumana.json"
# (serie, matiere du bot, prefixe d'id, ligne ajoutee sous le titre)
RATTACHEMENTS = [
    ("D", "MATHS", "sidibe_zoumana_limites_td", ""),
    ("C", "MATHS", "sidibe_zoumana_limites_tc",
     "Utilisé aussi en Terminale C : la leçon Limites et continuité y est au programme (approfondie).\n"),
]
MATIERES = {m for _, m, _, _ in RATTACHEMENTS}


def avec_ligne(texte, ligne):
    if not ligne:
        return texte
    titre, _, reste = texte.partition("\n")
    return f"{titre}\n{ligne}{reste}"


def documents_base(paquet):
    docs = []
    for serie, matiere, prefixe, ligne in RATTACHEMENTS:
        for d in paquet["documents"]:
            texte = avec_ligne(d["texte"], ligne)
            docs.append(dict(
                id=f"{prefixe}_s{d['seance']:02d}_{d['morceau']}",
                nom_fichier=f"Limites et continuité, Tle D (M. Sidibé Zoumana) - {d['titre']} ({d['morceau']}/{d['nb_morceaux']})",
                matiere=matiere, discipline="MATHS", examen="BAC_GENERAL",
                serie=serie, niveau="TERMINALE", niveau_source=paquet["classe_source"],
                type_doc="COURS_ESSENTIEL", source="ENSEIGNANT", institution="M. Sidibé Zoumana (enseignant)",
                transmis_par=paquet["transmis_par"], annee="2026",
                lecon="Limites et continuité", seance=d["seance"], titre_seance=d["titre"],
                sha256=hashlib.sha256(texte.encode("utf-8")).hexdigest(),
                sha256_source=paquet.get("sha256_pdf", ""),
                texte=texte, score=5,
                resume=f"Cours de mathématiques Tle D, Limites et continuité : {d['titre']}, extrait {d['morceau']}/{d['nb_morceaux']}",
            ))
    return docs


def plan(existants, candidats):
    ids = {d.get("id") for d in existants}
    empreintes = {d.get("sha256") for d in existants if d.get("sha256")}
    return [d for d in candidats if d["id"] not in ids and d["sha256"] not in empreintes]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    from google.cloud import storage

    paquet = json.loads(DONNEES.read_text(encoding="utf-8"))
    candidats = documents_base(paquet)
    client = storage.Client(project="astute-curve-307922")
    bucket = client.bucket(BUCKET)
    blob = bucket.blob(DATABASE)
    blob.reload()
    generation = int(blob.generation)
    original = blob.download_as_bytes(if_generation_match=generation, timeout=600)
    data = json.loads(original)
    deja = [d for d in data["documents"] if str(d.get("matiere", "")).upper() in MATIERES
            and d.get("examen") == "BAC_GENERAL" and d.get("serie") in {"C", "D"}]
    print(f"Base actuelle : {len(data['documents'])} documents, dont {len(deja)} en maths BAC général C/D")
    ajouts = plan(data["documents"], candidats)
    for serie, matiere, _, _ in RATTACHEMENTS:
        n = sum(1 for d in ajouts if d["serie"] == serie)
        print(f"  Série {serie} ({matiere}) : {n} extraits à ajouter")
    print(f"Ajouts proposés : {len(ajouts)} ; déjà présents : {len(candidats) - len(ajouts)} ; "
          f"total prévu : {len(data['documents']) + len(ajouts)}")
    if not args.apply or not ajouts:
        print("Audit terminé, aucune écriture." if not args.apply else "Rien à ajouter.")
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sauvegarde = f"data/backups/jigi_global_database_avant_limites_sidibe_zoumana_{stamp}.json"
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
    print(f"Terminé : {len(ajouts)} ajouts ; total {data['total']}. Redéploie akili-api.")


if __name__ == "__main__":
    main()
