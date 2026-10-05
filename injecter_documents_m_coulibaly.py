"""Documents transmis par M. Coulibaly (professeur d'economie et de mathematiques), compares a la base.

Contenu (donnees/documents_m_coulibaly.json, construit par donnees/construire_documents_m_coulibaly.py) :
  - 12 programmes educatifs de Mathematiques DPFC (6e a Terminale), decoupes par lecon ;
  - 7 formats des evaluations de Mathematiques (college, BEPC, 2nd cycle litteraire, BAC A1, A2, C, D) ;
  - les progressions de Mathematiques DPFC 2026-2027 ;
  - 6 progressions d'economie 2025-2026 du Lycee technique d'Abidjan (B, G1, G2).

Pour chaque document, le script mesure la part de son texte deja presente dans la base (memes
suites de 4 mots, dans les documents de la meme matiere) :
  DEJA     : fichier identique, ou 60 % du texte deja present -> rien a faire ;
  PARTIEL  : 25 a 60 % (autre version ou extraits) -> affiche, ajoute seulement avec --avec-partiels ;
  NOUVEAU  : moins de 25 % -> ajoute.

  python3 injecter_documents_m_coulibaly.py                       # audit, aucune ecriture
  python3 injecter_documents_m_coulibaly.py --apply               # ajoute les NOUVEAU
  python3 injecter_documents_m_coulibaly.py --apply --avec-partiels

Redeployer akili-api ensuite.
"""
import argparse
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

BUCKET = "akili-database-storage-astute-curve-307922"
DATABASE = "data/jigi_global_database.json"
DONNEES = Path(__file__).with_name("donnees") / "documents_m_coulibaly.json"
SEUIL_DEJA, SEUIL_PARTIEL = 0.60, 0.25
N = 4


def mots(texte):
    texte = unicodedata.normalize("NFKD", str(texte or "")).encode("ascii", "ignore").decode().lower()
    return re.findall(r"[a-z0-9]+", texte)


def suites(texte):
    """Suites de 4 mots, gardees une sur quatre (le meme tirage des deux cotes) : la
    proportion reste juste et la memoire de Cloud Shell suffit pour toute la base."""
    m = mots(texte)
    hs = (hash(" ".join(m[i:i + N])) for i in range(max(0, len(m) - N + 1)))
    return {h for h in hs if h % 4 == 0}


def corps(morceau):
    """Texte d'un extrait sans l'en-tete ajoute par nous (titre et source)."""
    return morceau.split("\n\n", 1)[1] if morceau.startswith(("PROGRAMME ÉDUCATIF", "FORMAT DES")) else morceau


def slug(texte):
    return re.sub(r"[^a-z0-9]+", "_", unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode().lower()).strip("_")[:50]


def couverture(source, base_par_matiere):
    """(part du texte deja dans la base, document le plus proche, part dans ce document)."""
    candidat = set().union(*(suites(corps(m)) for m in source["morceaux"]))
    if not candidat:
        return 0.0, None, 0.0
    vus, meilleur, part_meilleur = set(), None, 0.0
    for doc, ens in base_par_matiere.get(source["matiere"], []):
        commun = candidat & ens
        if commun:
            vus |= commun
            if len(commun) / len(candidat) > part_meilleur:
                meilleur, part_meilleur = doc, len(commun) / len(candidat)
    return len(vus) / len(candidat), meilleur, part_meilleur


def decider(source, base, base_par_matiere):
    empreintes = {d.get("sha256") for d in base} | {d.get("sha256_source") for d in base}
    if source["sha256"] in empreintes:
        return "DEJA", "fichier identique deja dans la base", 1.0
    part, doc, part_doc = couverture(source, base_par_matiere)
    proche = f" ; le plus proche : {doc.get('id')} ({part_doc:.0%})" if doc else ""
    if part >= SEUIL_DEJA:
        return "DEJA", f"{part:.0%} du texte deja present{proche}", part
    if part >= SEUIL_PARTIEL:
        return "PARTIEL", f"{part:.0%} du texte deja present{proche}", part
    return "NOUVEAU", f"{part:.0%} du texte deja present{proche}", part


def documents_base(source, transmis_par):
    docs = []
    nb = len(source["morceaux"])
    for examen, serie in source["cibles"]:
        for k, texte in enumerate(source["morceaux"], 1):
            docs.append(dict(
                id=f"coulibaly_{slug(source['titre'])}_{examen.lower()}_{serie.lower()}" + (f"_{k}" if nb > 1 else ""),
                nom_fichier=source["fichier"] + (f" (extrait {k}/{nb})" if nb > 1 else ""),
                matiere=source["matiere"], examen=examen, serie=serie, niveau=source["niveau"],
                type_doc=source["type_doc"], source="ENSEIGNANT",
                institution=("DPFC" if source["matiere"] == "MATHS" else "Lycée technique d'Abidjan"),
                transmis_par=transmis_par, titre=source["titre"],
                annee="2025-2026" if source["matiere"] == "ECO" else ("2026-2027" if "2026_2027" in source["fichier"] else "2023"),
                sha256=hashlib.sha256(texte.encode("utf-8")).hexdigest(), sha256_source=source["sha256"],
                texte=texte, score=5,
                resume=f"{source['titre']} ({source['type_doc'].lower().replace('_', ' ')}), transmis par {transmis_par}",
            ))
    return docs


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--avec-partiels", action="store_true")
    args = parser.parse_args()
    from google.cloud import storage

    paquet = json.loads(DONNEES.read_text(encoding="utf-8"))
    bucket = storage.Client(project="astute-curve-307922").bucket(BUCKET)
    blob = bucket.blob(DATABASE)
    blob.reload()
    generation = int(blob.generation)
    original = blob.download_as_bytes(if_generation_match=generation, timeout=600)
    data = json.loads(original)
    base = data["documents"]
    print(f"Base actuelle : {len(base)} documents\n")
    base_par_matiere = {}
    for m in {s["matiere"] for s in paquet["sources"]}:
        base_par_matiere[m] = [(d, suites(d.get("texte", ""))) for d in base
                               if str(d.get("matiere") or "").upper() == m and not str(d.get("id", "")).startswith("coulibaly_")]
    ajouts, bilan = [], {}
    for source in paquet["sources"]:
        decision, pourquoi, _ = decider(source, base, base_par_matiere)
        if any(str(d.get("sha256_source")) == source["sha256"] for d in base):
            decision, pourquoi = "DEJA", "deja injecte par ce script"
        bilan[decision] = bilan.get(decision, 0) + 1
        print(f"{decision:8} | {source['type_doc']:20} | {source['titre'][:55]:55} | {pourquoi}")
        if decision == "NOUVEAU" or (decision == "PARTIEL" and args.avec_partiels):
            ajouts.extend(documents_base(source, paquet["transmis_par"]))
    print(f"\nBilan : {bilan}")
    print(f"Documents a ajouter : {len(ajouts)} ; total prevu : {len(base) + len(ajouts)}")
    if not args.apply or not ajouts:
        print("Audit termine, aucune ecriture." if not args.apply else "Rien a ajouter.")
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sauvegarde = f"data/backups/jigi_global_database_avant_coulibaly_{stamp}.json"
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
