"""Codes d'acces de l'espace enseignant d'Akili (WhatsApp) et signalements des enseignants.

  python3 gerer_enseignants.py ajouter --nom "M. Sidibé" --matieres MECANIQUE_APPLIQUEE,CMI \\
          --classes "2nde F2,1ère F2,Tle F2"
  python3 gerer_enseignants.py lister
  python3 gerer_enseignants.py signalements [--jours 14]
  python3 gerer_enseignants.py revoquer PROF-SIDIBE-4821

Le code est a envoyer au professeur : il l'ecrit une fois a Akili sur WhatsApp, et son
numero devient un profil enseignant (menu : voir Akili comme ses eleves, preparer cours et
evaluations, changer de matiere ou de classe, signaler une erreur). Un code ne sert que pour
un seul numero. Les numeros sont masques a l'affichage.
"""
import argparse
import ast
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ICI = Path(__file__).parent
sys.path.insert(0, str(ICI / "whatsapp_bot"))
import espace_enseignant as prof  # noqa: E402

PROJET = "astute-curve-307922"
CHAMPS_ENSEIGNANT = ["user_type", "enseignant_verifie", "enseignant_nom", "enseignant_code", "enseignant_matieres",
                     "enseignant_classes", "enseignant_classe", "mode_enseignant", "attente_prof"]


def matieres_connues():
    """Codes de matiere du bot (LIBELLES_MATIERES de whatsapp_bot/main.py), sans importer le bot."""
    arbre = ast.parse((ICI / "whatsapp_bot" / "main.py").read_text(encoding="utf-8"))
    for noeud in arbre.body:
        if isinstance(noeud, ast.Assign) and any(getattr(c, "id", "") == "LIBELLES_MATIERES" for c in noeud.targets):
            return ast.literal_eval(noeud.value)
    raise RuntimeError("LIBELLES_MATIERES introuvable dans whatsapp_bot/main.py")


def preparer(nom, matieres, classes, connues):
    """Valide la demande ; renvoie (matieres, classes) propres ou leve ValueError."""
    nom = (nom or "").strip()
    if not nom:
        raise ValueError("--nom est obligatoire")
    codes = [m.strip().upper() for m in matieres.split(",") if m.strip()]
    inconnues = [m for m in codes if m not in connues]
    if not codes or inconnues:
        raise ValueError(f"Matières inconnues : {inconnues or 'aucune'}. Codes possibles : {', '.join(sorted(connues))}")
    libelles = [c.strip() for c in classes.split(",") if c.strip()]
    if not libelles:
        raise ValueError("--classes est obligatoire (ex. \"2nde F2,1ère F2\")")
    if len(codes) > 10 or len(libelles) > 10:
        raise ValueError("10 matières et 10 classes au plus (liste WhatsApp)")
    for libelle in libelles:
        prof.classe_vers_profil(libelle)  # ValueError si la classe n'est pas reconnue
    return codes, libelles


def message_pour_le_professeur(nom, code, matieres, classes, connues):
    return (
        f"Bonjour {nom},\n\nMerci pour les documents que vous partagez avec Akili. Vous avez maintenant un "
        "espace enseignant pour tester Akili et l'utiliser pour préparer vos cours.\n\n"
        f"Écrivez simplement ce code à Akili sur WhatsApp : {code}\n\n"
        f"Matières : {', '.join(connues.get(m, m) for m in matieres)}\nClasses : {', '.join(classes)}\n\n"
        "Vous pourrez voir Akili comme vos élèves le voient, préparer leçons, exercices et évaluations avec "
        "corrigés, et signaler une erreur en écrivant « correction : » suivi de votre remarque. "
        "Ce code est personnel : il ne fonctionne que sur un seul numéro."
    )


def masque(phone):
    return f"…{str(phone)[-4:]}" if phone else "pas encore activé"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sous = parser.add_subparsers(dest="action", required=True)
    ajout = sous.add_parser("ajouter")
    ajout.add_argument("--nom", required=True)
    ajout.add_argument("--matieres", required=True)
    ajout.add_argument("--classes", required=True)
    sous.add_parser("lister")
    sig = sous.add_parser("signalements")
    sig.add_argument("--jours", type=int, default=14)
    rev = sous.add_parser("revoquer")
    rev.add_argument("code")
    args = parser.parse_args()

    from google.cloud import firestore
    db = firestore.Client(project=PROJET)
    codes = db.collection(prof.COLLECTION_CODES)

    if args.action == "ajouter":
        connues = matieres_connues()
        try:
            matieres, classes = preparer(args.nom, args.matieres, args.classes, connues)
        except ValueError as e:
            sys.exit(f"Erreur : {e}")
        existants = {d.id for d in codes.stream()}
        code = prof.nouveau_code(args.nom, existants)
        codes.document(code).create({
            "code": code, "nom": args.nom.strip(), "matieres": matieres, "classes": classes, "actif": True,
            "phone": "", "cree_le": datetime.now(timezone.utc).isoformat(),
        })
        print(f"Code créé : {code}\n\n--- Message à envoyer au professeur ---\n")
        print(message_pour_le_professeur(args.nom.strip(), code, matieres, classes, connues))

    elif args.action == "lister":
        for doc in sorted(codes.stream(), key=lambda d: (d.to_dict() or {}).get("cree_le", "")):
            d = doc.to_dict() or {}
            etat = "actif" if d.get("actif", True) else "révoqué"
            print(f"{doc.id:<22} {d.get('nom', ''):<20} {etat:<8} {masque(d.get('phone')):<18} "
                  f"{','.join(d.get('matieres', []))} | {', '.join(d.get('classes', []))}")

    elif args.action == "signalements":
        depuis = (datetime.now(timezone.utc) - timedelta(days=args.jours)).isoformat()
        docs = sorted((d.to_dict() or {} for d in db.collection(prof.COLLECTION_SIGNALEMENTS)
                       .where("cree_le", ">=", depuis).stream()), key=lambda d: d.get("cree_le", ""))
        print(f"{len(docs)} signalement(s) depuis {args.jours} jours\n")
        for d in docs:
            print(f"[{d.get('cree_le', '')[:16]}] {d.get('nom', '')} — {d.get('matiere', '')}, {d.get('classe', '')} "
                  f"(mode {d.get('mode_enseignant', '')})")
            print(f"  Remarque : {d.get('texte', '')}")
            print(f"  Réponse d'Akili concernée : {d.get('message_akili', '')[:500]}\n")

    elif args.action == "revoquer":
        reference = codes.document(args.code.strip().upper())
        snapshot = reference.get()
        if not snapshot.exists:
            sys.exit("Code introuvable.")
        phone = (snapshot.to_dict() or {}).get("phone")
        reference.update({"actif": False, "revoque_le": datetime.now(timezone.utc).isoformat()})
        if phone:
            etat = db.collection("whatsapp_state").document(str(phone))
            etat.update({champ: firestore.DELETE_FIELD for champ in CHAMPS_ENSEIGNANT})
            # Le profil repasse en eleve en mode etude (l'ancien mode "enseignant" n'existe pas cote eleve).
            etat.update({"mode": "etude"})
        print(f"Code {args.code} révoqué" + (f" ; profil enseignant retiré du numéro {masque(phone)}." if phone else "."))


if __name__ == "__main__":
    main()
