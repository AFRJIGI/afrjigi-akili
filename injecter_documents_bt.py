"""Documents BT rattaches aux series du BAC Technique (decision de Daouda, 9 oct. 2026).

BT = BAC Technique : le tertiaire regroupe les series B, G1, G2 ; l'industriel, les series E et F.
Les classes sont Seconde, Premiere, Terminale (« 1BT, 2BT, 3BT » ou « 1re a 3e annee » dans les documents).

Contenu (donnees/documents_bt.json, construit par donnees/construire_documents_bt.py) :
  - 21 progressions 2026-2027 du BT Electronique (M. Adia, ETIC Korhogo) -> serie F2 (electronique) :
    electronique analogique, numerique, mesures et atelier dans la matiere Electronique ; technologie et
    schemas ; radio-television et telephonie (deux matieres ajoutees a la liste de F2) ;
  - 6 progressions 2026-2027 d'Economie generale et d'EOE (M. Coulibaly) -> Economie, series G1 et G2 ;
  - programmes de Mathematiques (METFPA 2022) : industriel -> E, F1, F2, F3, F4, F7 ; tertiaire -> B, G1, G2.
Les progressions BT ont la priorite -1 : a classe egale, une progression officielle deja en place passe avant.

La version du 9 oct. (series BT_ELN, BT_IND, BT_TER et copie du cours de mecanique de M. Sidibe pour BT_IND)
est retiree de la base par --apply : documents dont la serie commence par « BT_ », et copies
« sidibe_cours_meca_bt_ind_* » (le cours reste en F1 et F2).

  python3 injecter_documents_bt.py            # audit, aucune ecriture
  python3 injecter_documents_bt.py --apply    # sauvegarde la base, retire l'ancienne version, ajoute

Redeployer akili-api ensuite : l'API charge la base au demarrage.
"""
import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BUCKET = "akili-database-storage-astute-curve-307922"
DATABASE = "data/jigi_global_database.json"
DONNEES = Path(__file__).with_name("donnees") / "documents_bt.json"
CLASSES = {"SECONDE": "Seconde", "PREMIERE": "Première", "TERMINALE": "Terminale"}
# Matieres du BT Electronique -> matieres de la serie F2
MATIERES_F2 = {"ELECTRONIQUE_ANALOGIQUE": "ELECTRONIQUE", "ELECTRONIQUE_NUMERIQUE": "ELECTRONIQUE",
               "MESURES_ESSAIS": "ELECTRONIQUE", "CONSTRUCTION_ELECTRONIQUE": "ELECTRONIQUE",
               "TECHNO_SCHEMAS": "TECHNO_SCHEMAS", "RADIO_TV": "RADIO_TV", "TELEPHONIE": "TELEPHONIE"}
ANCIENS_PREFIXES = ("sidibe_cours_meca_bt_ind_",)


def rattachement(source):
    """(serie, matiere, prefixe d'id, ligne ajoutee sous le titre) d'une source du paquet."""
    classe = CLASSES.get(source["niveau"], "")
    if source["serie"] == "BT_ELN":
        return ("F2", MATIERES_F2[source["matiere"]], f"bt_{source['matiere'].lower()}",
                f"Correspond au BAC Technique, série F2 (électronique), classe de {classe}.")
    if source["type_doc"] == "PROGRAMME" and "BT_IND" in source["serie"]:
        return ("E F1 F2 F3 F4 F7", "MATHS", "bt_industriel_maths_programme",
                "Vaut pour le BAC Technique industriel (séries E, F1, F2, F3, F4, F7) ; "
                "1re, 2e et 3e année = Seconde, Première et Terminale.")
    if source["type_doc"] == "PROGRAMME":
        return ("B G1 G2", "MATHS", "bt_tertiaire_maths_programme",
                "Vaut pour le BAC Technique tertiaire (séries B, G1, G2) ; "
                "1re, 2e et 3e année = Seconde, Première et Terminale.")
    return ("G1 G2", "ECO", f"bt_{source['matiere'].lower()}",
            f"Correspond au BAC Technique, séries G1 et G2, classe de {classe}.")


def avec_ligne(texte, ligne):
    titre, _, reste = texte.partition("\n")
    return f"{titre}\n{ligne}\n{reste}"


def documents_paquet(paquet):
    docs = []
    for s in paquet["sources"]:
        serie, matiere, prefixe, ligne = rattachement(s)
        nb = len(s["morceaux"])
        base_id = prefixe if s["type_doc"] == "PROGRAMME" else f"{prefixe}_{s['niveau'].lower()}"
        for k, morceau in enumerate(s["morceaux"], 1):
            texte = avec_ligne(morceau, ligne)
            docs.append(dict(
                id=base_id + (f"_{k:02d}" if nb > 1 else ""),
                nom_fichier=s["fichier"] + (f" (extrait {k}/{nb})" if nb > 1 else ""),
                matiere=matiere, discipline=s["matiere"], examen="BAC_TECHNIQUE", serie=serie, niveau=s["niveau"],
                type_doc=s["type_doc"], source="ENSEIGNANT", institution=s["institution"],
                transmis_par=s["transmis_par"], titre=s["titre"], priorite=-1,
                annee="2026-2027" if s["type_doc"] == "PROGRESSION_ANNUELLE" else "2022",
                sha256=hashlib.sha256(texte.encode("utf-8")).hexdigest(), sha256_source=s["sha256"],
                texte=texte, score=5,
                resume=f"{s['titre']} ({s['type_doc'].lower().replace('_', ' ')}), transmis par {s['transmis_par']}",
            ))
    return docs


def est_ancienne_version(doc):
    return (str(doc.get("serie") or "").upper().startswith("BT_")
            or str(doc.get("id") or "").startswith(ANCIENS_PREFIXES))


def plan(existants, candidats):
    restants = [d for d in existants if not est_ancienne_version(d)]
    ids = {d.get("id") for d in restants}
    empreintes = {d.get("sha256") for d in restants if d.get("sha256")}
    return [d for d in candidats if d["id"] not in ids and d["sha256"] not in empreintes]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    from google.cloud import storage

    candidats = documents_paquet(json.loads(DONNEES.read_text(encoding="utf-8")))
    bucket = storage.Client(project="astute-curve-307922").bucket(BUCKET)
    blob = bucket.blob(DATABASE)
    blob.reload()
    generation = int(blob.generation)
    original = blob.download_as_bytes(if_generation_match=generation, timeout=600)
    data = json.loads(original)
    anciens = [d for d in data["documents"] if est_ancienne_version(d)]
    print(f"Base actuelle : {len(data['documents'])} documents, dont {len(anciens)} de la version BT_* du 9 oct. à retirer")
    ajouts = plan(data["documents"], candidats)
    for (serie, matiere), n in sorted(Counter((d["serie"], d["matiere"]) for d in ajouts).items()):
        print(f"  {serie:18} {matiere:16} : {n} à ajouter")
    total = len(data["documents"]) - len(anciens) + len(ajouts)
    print(f"Retraits : {len(anciens)} ; ajouts : {len(ajouts)} ; déjà présents : {len(candidats) - len(ajouts)} ; "
          f"total prévu : {total}")
    if not args.apply or not (ajouts or anciens):
        print("Audit terminé, aucune écriture." if not args.apply else "Rien à changer.")
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sauvegarde = f"data/backups/jigi_global_database_avant_documents_bt_series_{stamp}.json"
    bucket.blob(sauvegarde).upload_from_string(original, content_type="application/json", if_generation_match=0)
    print(f"Sauvegarde : gs://{BUCKET}/{sauvegarde}")
    maintenant = datetime.now(timezone.utc).isoformat()
    for d in ajouts:
        d["integre_le"] = maintenant
    data["documents"] = [d for d in data["documents"] if not est_ancienne_version(d)] + ajouts
    data["total"] = len(data["documents"])
    data["generated_at"] = maintenant
    blob.upload_from_string(json.dumps(data, ensure_ascii=False, indent=2), content_type="application/json",
                            if_generation_match=generation)
    print(f"Terminé : {len(anciens)} retraits, {len(ajouts)} ajouts ; total {data['total']}. Redéploie akili-api.")


if __name__ == "__main__":
    main()
