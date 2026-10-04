"""Progressions de mathematiques du BAC Technique transmises par M. Brou (fichiers Word MET-FPA).

Le texte a deja ete extrait des fichiers Word dans donnees/progressions_maths_m_brou_2026.json
(script donnees/construire_progressions_maths_m_brou.py). Ce script compare chaque progression
a la base et n'ajoute que ce qui manque :
  - une classe sans progression de maths dans la base (Seconde T1, T2, T3) : ajoutee ;
  - une classe deja couverte par la meme progression : rien a faire ;
  - une classe couverte par un texte ou l'on ne retrouve pas les lecons (PDF mal lu) :
    la version Word est ajoutee et Akili la prefere (priorite 1).

  python3 injecter_progressions_maths_brou.py            # audit, aucune ecriture
  python3 injecter_progressions_maths_brou.py --apply    # sauvegarde la base puis ajoute

Redeployer akili-api ensuite : l'API charge la base au demarrage.
"""
import argparse
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

BUCKET = "akili-database-storage-astute-curve-307922"
DATABASE = "data/jigi_global_database.json"
DONNEES = Path(__file__).with_name("donnees") / "progressions_maths_m_brou_2026.json"
SEUIL_COUVERTURE = 0.8
SERIES_ELEVES = ["B", "E", "F1", "F2", "F3", "F4", "F7", "G1", "G2"]


def normaliser(texte):
    texte = re.sub(r"[’'`´]", " ", str(texte or ""))
    texte = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode().upper()
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", texte).split())


def serie_match(serie_doc, serie_eleve):
    """Meme regle que l'API (akili_api/main.py) pour les series du BAC Technique."""
    s_doc, s_el = (serie_doc or "").upper().strip(), (serie_eleve or "").upper().strip()
    if not s_doc or s_doc == "TOUTES" or s_doc == s_el:
        return True
    if s_el in ("E", "B", "G1", "G2"):
        return s_el in s_doc
    if s_el in ("F1", "F2", "F3", "F4", "F7"):
        return s_el in s_doc or s_doc == "F"
    return False


def series_couvertes(serie):
    return [s for s in SERIES_ELEVES if serie_match(serie, s)]


MOIS = ("SEPTEMBRE", "OCTOBRE", "NOVEMBRE", "DECEMBRE", "JANVIER", "FEVRIER", "MARS", "AVRIL", "MAI", "JUIN", "JUILLET")


def lecons(texte):
    """Titres des lecons ("Septembre, semaines 1-3 : LIMITES – CONTINUITÉ (14h) - contenus")."""
    titres = []
    for ligne in texte.split("\n"):
        if " : " not in ligne:
            continue
        quand, reste = ligne.split(" : ", 1)
        if not normaliser(quand).startswith(MOIS):
            continue
        titre = normaliser(re.split(r"\s\(\d+h\)|\s-\s", reste, maxsplit=1)[0])
        if titre and titre != "REVISION" and titre not in titres:
            titres.append(titre)
    return titres


def couverture(titres, texte_existant):
    """Part des lecons retrouvees dans un document existant (debut du titre, sans accents)."""
    if not titres:
        return 0.0
    plat = normaliser(texte_existant)
    trouves = sum(1 for t in titres if " ".join(t.split()[:4]) in plat)
    return trouves / len(titres)


def comparer(base, doc):
    """[(document existant, couverture)] des progressions de maths de la meme classe et serie."""
    mes_series = series_couvertes(doc["serie"])
    resultats = []
    for d in base:
        if (str(d.get("type_doc") or "").upper().startswith("PROGRESSION")
                and str(d.get("matiere") or "").upper() == "MATHS"
                and str(d.get("examen") or "").upper() in {"BAC_TECHNIQUE", "TOUS"}
                and str(d.get("niveau") or "").upper() == doc["niveau"]
                and any(serie_match(d.get("serie"), s) for s in mes_series)):
            resultats.append((d, couverture(lecons(doc["texte"]), d.get("texte", ""))))
    return resultats


def decider(base, doc):
    """("CREER" | "DEJA", priorite, explication)."""
    if any(d.get("sha256") == doc["sha256"] or d.get("id") == identifiant(doc) for d in base):
        return "DEJA", 0, "deja injecte"
    existants = comparer(base, doc)
    if not existants:
        return "CREER", 0, "aucune progression de maths pour cette classe"
    meilleur = max(existants, key=lambda x: x[1])
    if meilleur[1] >= SEUIL_COUVERTURE:
        return "DEJA", 0, f"meme progression deja presente ({meilleur[0].get('id')}, {meilleur[1]:.0%} des lecons)"
    return "CREER", 1, (f"le texte present ({meilleur[0].get('id')}) ne contient que {meilleur[1]:.0%} des lecons :"
                        " la version Word sera preferee")


def identifiant(doc):
    return f"brou_progression_maths_{doc['niveau'].lower()}_{doc['serie'].lower()}"


def document_base(doc, priorite, transmis_par):
    return dict(
        id=identifiant(doc),
        nom_fichier=doc["fichier"], chemin=f"enseignants/brou/maths/{doc['sha256']}.docx",
        matiere="MATHS", discipline="MATHEMATIQUES", examen="BAC_TECHNIQUE",
        serie=doc["serie"], niveau=doc["niveau"], classe_source=doc["classe_source"],
        annee="2026", edition_source=doc["edition_source"], type_doc="PROGRESSION_ANNUELLE",
        source="ENSEIGNANT", institution="METFPA", transmis_par=transmis_par,
        sha256=doc["sha256"], texte=doc["texte"], score=5, priorite=priorite,
        resume=f"Progression mathematiques {doc['libelle']} (MET-FPA, {doc['edition_source'] or 'edition inconnue'}), "
               f"version Word transmise par {transmis_par}",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    from google.cloud import storage

    paquet = json.loads(DONNEES.read_text(encoding="utf-8"))
    client = storage.Client(project="astute-curve-307922")
    bucket = client.bucket(BUCKET)
    blob = bucket.blob(DATABASE)
    blob.reload()
    generation = int(blob.generation)
    original = blob.download_as_bytes(if_generation_match=generation, timeout=600)
    data = json.loads(original)
    print(f"Base actuelle : {len(data['documents'])} documents\n")

    ajouts = []
    for doc in paquet["documents"]:
        decision, priorite, pourquoi = decider(data["documents"], doc)
        print(f"{decision:5} | {doc['classe_source']:8} -> {doc['niveau']:9} {doc['serie']:8} | {pourquoi}")
        if decision == "CREER":
            ajouts.append(document_base(doc, priorite, paquet["transmis_par"]))
    print(f"\nAjouts proposes : {len(ajouts)} ; total prevu : {len(data['documents']) + len(ajouts)}")
    if not args.apply or not ajouts:
        print("Audit termine, aucune ecriture." if not args.apply else "Rien a ajouter.")
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sauvegarde = f"data/backups/jigi_global_database_avant_maths_brou_{stamp}.json"
    bucket.blob(sauvegarde).upload_from_string(original, content_type="application/json", if_generation_match=0)
    print(f"Sauvegarde : gs://{BUCKET}/{sauvegarde}")
    maintenant = datetime.now(timezone.utc).isoformat()
    for doc in ajouts:
        doc["integre_le"] = maintenant
    data["documents"].extend(ajouts)
    data["total"] = len(data["documents"])
    data["generated_at"] = maintenant
    blob.upload_from_string(json.dumps(data, ensure_ascii=False, indent=2), content_type="application/json",
                            if_generation_match=generation)
    print(f"Termine : {len(ajouts)} ajouts ; total {data['total']}. Redeploie akili-api.")


if __name__ == "__main__":
    main()
