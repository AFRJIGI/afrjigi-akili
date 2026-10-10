"""Documents BT dans la base, comme documents de cours des series du BAC Technique.

10 oct. (M. Coulibaly) : les progressions du BT et celles des series G1, G2 (ou F) sont differentes, meme si
des contenus se recoupent. Les progressions BT ne sont donc plus la « progression officielle » d'une serie
(Akili ne s'en sert plus pour choisir la lecon du moment) : elles deviennent des documents d'accompagnement
(DOCUMENT_ACCOMPAGNEMENT, en extraits de 2 600 caracteres au plus), qu'Akili consulte pour expliquer.
Radio-television et telephonie ne sont plus des matieres de F2 : leurs documents vont dans Electronique.
Progressions Word du 10 oct. (dossier Progressions_Electroniques) : dessin industriel et informatique -> F2 ;
francais / techniques d'expression -> toutes les series du BAC Technique ; CMC du BT industriel -> E et F ;
CMC du BT tertiaire (dossier CMC_Tertiare, 1re a 3e annee) -> B, G1, G2.

Historique : le 9 oct., documents rattaches aux series du BAC Technique (decision de Daouda).

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
import re
import unicodedata
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
               "TECHNO_SCHEMAS": "TECHNO_SCHEMAS", "RADIO_TV": "ELECTRONIQUE", "TELEPHONIE": "ELECTRONIQUE",
               "DESSIN_INDUSTRIEL": "DESSIN_INDUSTRIEL", "INFORMATIQUE_INDUSTRIELLE": "INFORMATIQUE_INDUSTRIELLE"}
SERIES_TECHNIQUES = "B G1 G2 E F1 F2 F3 F4 F7"
ANCIENS_PREFIXES = ("sidibe_cours_meca_bt_ind_",)
VERSION = 3          # 3 : documents d'accompagnement (10 oct.) ; les versions precedentes sont remplacees
TAILLE_EXTRAIT = 2600  # l'API lit 2 800 caracteres par document qui n'est pas une progression


def slug(texte):
    texte = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", texte).strip("_")[:40]


def prefixe_id(source):
    # Progressions Word du 10 oct. : deux matieres « informatique » en 2e annee, l'id vient de leur titre.
    if source["fichier"].startswith("CMC_Tertiare/"):
        return "bt_word_cmc_tertiaire"
    if source["fichier"].startswith("Progressions_Electroniques/"):
        return "bt_word_" + slug(source["titre"].split(",")[0])
    return f"bt_{source['matiere'].lower()}"


def rattachement(source):
    """(serie, matiere, prefixe d'id, ligne ajoutee sous le titre) d'une source du paquet."""
    classe = CLASSES.get(source["niveau"], "")
    if source["serie"] == "BT_TOUS":
        return (SERIES_TECHNIQUES, source["matiere"], prefixe_id(source),
                f"Progression du BT (toutes options), donnée à titre de cours pour la classe de {classe} : le "
                "programme des séries du BAC Technique est différent, suis la progression officielle de la série.")
    if source["serie"] == "BT_IND" and source["type_doc"] != "PROGRAMME":
        return ("E F1 F2 F3 F4 F7", source["matiere"], prefixe_id(source),
                f"Progression du BT industriel, donnée à titre de cours pour la classe de {classe} : le programme "
                "des séries E et F est différent, suis la progression officielle de la série.")
    if source["serie"] == "BT_TER" and source["matiere"] == "HG":
        return ("B G1 G2", "HG", prefixe_id(source),
                f"Progression du BT tertiaire, donnée à titre de cours pour la classe de {classe} : le programme de "
                "CMC des séries B, G1 et G2 est différent, suis la progression officielle de la série.")
    if source["serie"] == "BT_ELN":
        return ("F2", MATIERES_F2[source["matiere"]], prefixe_id(source),
                f"Progression du BT Électronique ({classe} de F2), donnée à titre de cours : le programme du "
                "BAC F2 peut être différent, suis la progression officielle de la série.")
    if source["type_doc"] == "PROGRAMME" and "BT_IND" in source["serie"]:
        return ("E F1 F2 F3 F4 F7", "MATHS", "bt_industriel_maths_programme",
                "Vaut pour le BAC Technique industriel (séries E, F1, F2, F3, F4, F7) ; "
                "1re, 2e et 3e année = Seconde, Première et Terminale.")
    if source["type_doc"] == "PROGRAMME":
        return ("B G1 G2", "MATHS", "bt_tertiaire_maths_programme",
                "Vaut pour le BAC Technique tertiaire (séries B, G1, G2) ; "
                "1re, 2e et 3e année = Seconde, Première et Terminale.")
    return ("G1 G2", "ECO", prefixe_id(source),
            f"Progression du BT tertiaire ({classe} de G1, G2), donnée à titre de cours : le programme des "
            "séries G1 et G2 est différent, suis la progression officielle de la série.")


def avec_ligne(texte, ligne):
    titre, _, reste = texte.partition("\n")
    return f"{titre}\n{ligne}\n{reste}"


def decouper(texte, taille=TAILLE_EXTRAIT):
    """Progression BT en extraits (coupes aux lignes) ; chaque extrait garde le titre et la ligne d'avertissement."""
    lignes = texte.split("\n")
    entete, corps = "\n".join(lignes[:2]), lignes[2:]
    morceaux, actuel = [], []
    for ligne in corps:
        if actuel and len(entete) + sum(len(x) + 1 for x in actuel) + len(ligne) > taille:
            morceaux.append(actuel)
            actuel = []
        actuel.append(ligne[:taille - len(entete) - 20])
    if actuel:
        morceaux.append(actuel)
    nb = len(morceaux)
    return [entete + (f" (extrait {k}/{nb})" if nb > 1 else "") + "\n" + "\n".join(m) for k, m in enumerate(morceaux, 1)]


def documents_paquet(paquet):
    docs = []
    for s in paquet["sources"]:
        serie, matiere, prefixe, ligne = rattachement(s)
        base_id = prefixe if s["type_doc"] == "PROGRAMME" else f"{prefixe}_{s['niveau'].lower()}"
        if s["type_doc"] == "PROGRAMME":
            textes = [avec_ligne(m, ligne) for m in s["morceaux"]]
            type_doc = "PROGRAMME"
        else:
            textes = [t for m in s["morceaux"] for t in decouper(avec_ligne(m, ligne))]
            type_doc = "DOCUMENT_ACCOMPAGNEMENT"
        nb = len(textes)
        for k, texte in enumerate(textes, 1):
            docs.append(dict(
                id=base_id + (f"_{k:02d}" if nb > 1 else ""),
                nom_fichier=s["fichier"] + (f" (extrait {k}/{nb})" if nb > 1 else ""),
                matiere=matiere, discipline=s["matiere"], examen="BAC_TECHNIQUE", serie=serie, niveau=s["niveau"],
                type_doc=type_doc, type_source=s["type_doc"], source="ENSEIGNANT", institution=s["institution"],
                transmis_par=s["transmis_par"], titre=s["titre"], priorite=-1, version_bt=VERSION,
                annee="2026-2027" if s["type_doc"] == "PROGRESSION_ANNUELLE" else "2022",
                sha256=hashlib.sha256(texte.encode("utf-8")).hexdigest(), sha256_source=s["sha256"],
                texte=texte, score=5,
                resume=f"{s['titre']} (BT, {s['type_doc'].lower().replace('_', ' ')}), transmis par {s['transmis_par']}",
            ))
    return docs


def est_ancienne_version(doc):
    identifiant = str(doc.get("id") or "")
    return (str(doc.get("serie") or "").upper().startswith("BT_")
            or identifiant.startswith(ANCIENS_PREFIXES)
            or (identifiant.startswith("bt_") and doc.get("version_bt") != VERSION))


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
    print(f"Base actuelle : {len(data['documents'])} documents, dont {len(anciens)} documents BT d'une version précédente à retirer")
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
