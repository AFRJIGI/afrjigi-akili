"""Ecoles partenaires d'Akili : creation, import des codes, rapport par classe.

  python3 gerer_ecoles.py creer --ecole LKU --nom "Ecole ..."
  python3 gerer_ecoles.py generer --ecole LKU --classe "6e A" --nombre 40 [--sortie codes_6eA.csv]
  python3 gerer_ecoles.py importer --ecole LKU --fichier liste.csv [--simuler] [--sortie codes.csv]
  python3 gerer_ecoles.py lister --ecole LKU
  python3 gerer_ecoles.py reinitialiser LKU-K7M4Q          # eleve qui change de telephone
  python3 gerer_ecoles.py desactiver LKU-K7M4Q
  python3 gerer_ecoles.py rapport --ecole LKU [--jours 7] [--sortie rapport.txt]

Liste remise par l'ecole (CSV, SANS NOM d'eleve) : colonnes role (eleve|prof), classe (eleve), classes
(prof, separees par ;), matieres (prof, codes Akili separes par ;), nom (prof, facultatif), code (facultatif :
sinon genere, forme ECOLE-XXXXX avec au moins un chiffre). Un code deja importe est laisse tel quel, donc
reimporter une liste mise a jour ne change aucun code. Le fichier de sortie donne a l'ecole le code de chaque ligne.
"""
import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

ICI = Path(__file__).parent
sys.path.insert(0, str(ICI / "whatsapp_bot"))
import ecole  # noqa: E402
import espace_enseignant as prof  # noqa: E402
from gerer_enseignants import matieres_connues  # noqa: E402

PROJET = "astute-curve-307922"


def base():
    from google.cloud import firestore
    return firestore.Client(project=PROJET)


def maintenant():
    return datetime.now(timezone.utc).isoformat()


def ecrire_sortie(lignes, chemin):
    champs = ["code", "role", "classe", "classes", "matieres", "nom", "statut"]
    flux = open(chemin, "w", newline="", encoding="utf-8") if chemin else sys.stdout
    try:
        w = csv.DictWriter(flux, fieldnames=champs, extrasaction="ignore")
        w.writeheader()
        for ligne in lignes:
            w.writerow({**ligne, "classes": ";".join(ligne.get("classes") or []),
                        "matieres": ";".join(ligne.get("matieres") or [])})
    finally:
        if chemin:
            flux.close()


def enregistrer(db, id_ecole, lignes, simuler=False):
    """Ecrit les lignes ; renvoie les lignes avec 'statut' (nouveau | deja_importe)."""
    sorties = []
    for ligne in lignes:
        reference = db.collection(ecole.COLLECTION_CODES).document(ligne["code"])
        if reference.get().exists:
            sorties.append({**ligne, "statut": "deja_importe"})
            continue
        document = {"ecole": id_ecole, "role": ligne["role"], "actif": True, "cree_le": maintenant()}
        if ligne["role"] == ecole.ROLE_ELEVE:
            document.update({"classe": ligne["classe"], "classe_id": ecole.classe_id(ligne["classe"])})
        else:
            document.update({"classes": ligne["classes"], "matieres": ligne["matieres"], "nom": ligne["nom"]})
        if not simuler:
            reference.set(document)
            if ligne["role"] == ecole.ROLE_PROF:  # meme code pour l'espace enseignant WhatsApp
                db.collection(prof.COLLECTION_CODES).document(ligne["code"]).set({
                    "nom": ligne["nom"], "matieres": ligne["matieres"], "classes": ligne["classes"],
                    "actif": True, "ecole": id_ecole, "cree_le": maintenant()})
        sorties.append({**ligne, "statut": "nouveau"})
    return sorties


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("creer")
    a.add_argument("--ecole", required=True)
    a.add_argument("--nom", required=True)
    g = sp.add_parser("generer")
    g.add_argument("--ecole", required=True)
    g.add_argument("--classe", required=True)
    g.add_argument("--nombre", type=int, required=True)
    g.add_argument("--sortie")
    i = sp.add_parser("importer")
    i.add_argument("--ecole", required=True)
    i.add_argument("--fichier", required=True)
    i.add_argument("--simuler", action="store_true")
    i.add_argument("--sortie")
    l = sp.add_parser("lister")
    l.add_argument("--ecole", required=True)
    for nom in ("reinitialiser", "desactiver"):
        sp.add_parser(nom).add_argument("code")
    r = sp.add_parser("rapport")
    r.add_argument("--ecole", required=True)
    r.add_argument("--jours", type=int, default=7)
    r.add_argument("--sortie")
    args = p.parse_args(argv)
    db = base()

    if args.cmd == "creer":
        if not ecole.RE_ECOLE.match(args.ecole):
            sys.exit("Code d'école : 3 ou 4 lettres majuscules (ex. LKU).")
        db.collection(ecole.COLLECTION_ECOLES).document(args.ecole).set(
            {"nom": args.nom, "actif": True, "cree_le": maintenant()}, merge=True)
        print(f"École {args.ecole} enregistrée : {args.nom}")
    elif args.cmd in ("generer", "importer"):
        if not db.collection(ecole.COLLECTION_ECOLES).document(args.ecole).get().exists:
            sys.exit(f"École {args.ecole} inconnue : lancer d'abord « creer ».")
        existants = {d.id for d in db.collection(ecole.COLLECTION_CODES).where("ecole", "==", args.ecole).stream()}
        if args.cmd == "generer":
            ecole.profil_de_classe(args.classe)
            lignes = []
            for _ in range(args.nombre):
                code = ecole.nouveau_code(args.ecole, existants)
                existants.add(code)
                lignes.append({"role": ecole.ROLE_ELEVE, "code": code, "classe": args.classe})
            simuler = False
        else:
            texte = Path(args.fichier).read_text(encoding="utf-8")
            lignes, erreurs = ecole.lire_liste(texte, args.ecole, set(matieres_connues()))
            for e in erreurs:
                print("À corriger —", e)
            simuler = args.simuler
            if erreurs and not simuler:
                sys.exit("Rien n'a été importé : corriger le fichier puis relancer (ou --simuler pour voir le reste).")
        sorties = enregistrer(db, args.ecole, lignes, simuler)
        nouveaux = sum(1 for x in sorties if x["statut"] == "nouveau")
        print(f"{nouveaux} code(s) {'à créer (simulation)' if simuler else 'créés'}, "
              f"{len(sorties) - nouveaux} déjà importé(s).")
        ecrire_sortie(sorties, args.sortie)
    elif args.cmd == "lister":
        docs = [d.to_dict() | {"code": d.id} for d in db.collection(ecole.COLLECTION_CODES).where("ecole", "==", args.ecole).stream()]
        for d in sorted(docs, key=lambda x: (x.get("role", ""), x.get("classe", ""), x["code"])):
            etat = "lié" if d.get("eleve_hash") else ("actif" if d.get("actif", True) else "désactivé")
            print(f"{d['code']}  {d.get('role'):6} {d.get('classe') or ';'.join(d.get('classes') or [])}  {etat}")
        print(f"{len(docs)} code(s).")
    elif args.cmd == "reinitialiser":
        ref = db.collection(ecole.COLLECTION_CODES).document(args.code)
        if not ref.get().exists:
            sys.exit("Code inconnu.")
        from google.cloud import firestore
        ref.update({"eleve_hash": firestore.DELETE_FIELD, "lie_le": firestore.DELETE_FIELD})
        print(f"{args.code} réinitialisé : il peut être écrit depuis un nouveau numéro.")
    elif args.cmd == "desactiver":
        db.collection(ecole.COLLECTION_CODES).document(args.code).update({"actif": False})
        print(f"{args.code} désactivé.")
    elif args.cmd == "rapport":
        ecole_doc = db.collection(ecole.COLLECTION_ECOLES).document(args.ecole).get().to_dict() or {}
        codes = [d.to_dict() | {"code": d.id} for d in db.collection(ecole.COLLECTION_CODES).where("ecole", "==", args.ecole).stream()]
        du, au = ecole.periode(args.jours)
        activite = [d.to_dict() for d in db.collection(ecole.COLLECTION_ACTIVITE).where("ecole", "==", args.ecole).stream()]
        hashes = {c["eleve_hash"] for c in codes if c.get("eleve_hash")}
        # Les resultats sont sous le hachage, jamais le numero : on garde ceux des eleves de l'ecole, y compris
        # ceux d'avant la liaison du code.
        tests = [d.to_dict() for d in db.collection("mini_tests").stream() if (d.to_dict() or {}).get("eleve") in hashes]
        revisions = [d.to_dict() for d in db.collection("revisions_resultats").stream() if (d.to_dict() or {}).get("eleve") in hashes]
        classes = ecole.rapport_classes(codes, None, activite, tests, revisions, du, au)
        texte = ecole.texte_rapport(ecole_doc.get("nom") or args.ecole, classes, du, au)
        if args.sortie:
            Path(args.sortie).write_text(texte, encoding="utf-8")
            print(f"Rapport écrit : {args.sortie}")
        else:
            print(texte)


if __name__ == "__main__":
    main()
