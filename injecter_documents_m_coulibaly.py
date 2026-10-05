"""Documents transmis par M. Coulibaly (professeur d'economie et de mathematiques), compares a la base.

Contenu (donnees/documents_m_coulibaly.json, construit par donnees/construire_documents_m_coulibaly.py) :
  - 12 programmes educatifs de Mathematiques DPFC (6e a Terminale), decoupes par lecon ;
  - 7 formats des evaluations de Mathematiques (college, BEPC, 2nd cycle litteraire, BAC A1, A2, C, D) ;
  - les progressions de Mathematiques DPFC 2026-2027 ;
  - 6 progressions d'economie 2025-2026 du Lycee technique d'Abidjan (B, G1, G2).

Le script mesure la part du texte de chaque document deja presente dans la base (memes suites
de 4 mots, meme matiere). Avec des extractions PDF differentes, un document identique ne
depasse souvent pas 50 a 60 % : les decisions ci-dessous ont ete prises sur l'audit du
5 octobre 2026.
  - Programmes educatifs : deja dans la base, mais en un seul bloc dont l'API ne lit que les
    2 800 premiers caracteres (le mot de la ministre). La version decoupee par lecon est ajoutee
    et REMPLACE l'ancienne (champ remplace_ids : l'API ne charge plus l'ancienne, rien n'est
    supprime de la base).
  - Formats des epreuves et 4 progressions d'economie : nouveaux, ajoutes.
  - Progressions de maths DPFC 2026-2027, initiation economique 2nde G, economie generale Tle G :
    deja presentes, ignorees.

  python3 injecter_documents_m_coulibaly.py            # audit, aucune ecriture
  python3 injecter_documents_m_coulibaly.py --apply    # sauvegarde la base puis ajoute

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
SEUIL_REMPLACE = 0.20  # part minimale partagee avec l'ancien programme remplace
N = 4
DEJA_PRESENTS = {
    "MATHEMATIQUES - Progressions annuelles_DPFC_2026_2027.pdf": "meme fichier DPFC que dpfc_progression_2026_2027_mathematiques",
    "PROGRESSION DE INITIATION ECONOMIQUE 2nde G1&G2.docx": "deja present (progression 2nde G1G2 2025-2026)",
    "PROGRESSION DE ECONOMIE GENERALE Tle G.docx": "deja present (metfpa_progression_economie_generale_2025_2026_terminale_g)",
}


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


def programme_remplace(source, base_par_matiere):
    """Ancien programme de la meme classe (un seul bloc) que la version decoupee remplace."""
    candidat = set().union(*(suites(corps(m)) for m in source["morceaux"]))
    meilleur, part = None, 0.0
    for doc, ens in base_par_matiere.get(source["matiere"], []):
        if str(doc.get("type_doc") or "").upper() != "PROGRAMME" or not candidat:
            continue
        p = len(candidat & ens) / len(candidat)
        if p > part:
            meilleur, part = doc, p
    return (meilleur, part) if meilleur and part >= SEUIL_REMPLACE else (None, part)


def decision_finale(source, base, base_par_matiere):
    """(AJOUTER | IGNORER, explication, documents remplaces)."""
    if any(str(d.get("sha256_source")) == source["sha256"] for d in base):
        return "IGNORER", "deja injecte par ce script", []
    if source["fichier"] in DEJA_PRESENTS:
        return "IGNORER", DEJA_PRESENTS[source["fichier"]], []
    if source["type_doc"] == "PROGRAMME":
        ancien, part = programme_remplace(source, base_par_matiere)
        if ancien:
            return "AJOUTER", f"remplace {ancien.get('id')} ({part:.0%} en commun, un seul bloc de {len(ancien.get('texte', ''))} car.)", [ancien.get("id")]
        return "AJOUTER", "aucun ancien programme reconnu", []
    return "AJOUTER", decider(source, base, base_par_matiere)[1], []


def documents_base(source, transmis_par, remplace_ids=()):
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
                texte=texte, score=5, remplace_ids=list(remplace_ids),
                resume=f"{source['titre']} ({source['type_doc'].lower().replace('_', ' ')}), transmis par {transmis_par}",
            ))
    return docs


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
    base = data["documents"]
    print(f"Base actuelle : {len(base)} documents\n")
    base_par_matiere = {}
    for m in {s["matiere"] for s in paquet["sources"]}:
        base_par_matiere[m] = [(d, suites(d.get("texte", ""))) for d in base
                               if str(d.get("matiere") or "").upper() == m and not str(d.get("id", "")).startswith("coulibaly_")]
    ajouts, bilan = [], {}
    for source in paquet["sources"]:
        decision, pourquoi, remplaces = decision_finale(source, base, base_par_matiere)
        bilan[decision] = bilan.get(decision, 0) + 1
        print(f"{decision:8} | {source['type_doc']:20} | {source['titre'][:50]:50} | {pourquoi}")
        if decision == "AJOUTER":
            ajouts.extend(documents_base(source, paquet["transmis_par"], remplaces))
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
