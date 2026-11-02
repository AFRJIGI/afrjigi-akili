"""Ecoles partenaires : codes eleves et professeurs, classes, rapport par classe (sans Firestore ni WhatsApp).

Une ecole (ex. LKU) remet a Akili une liste de codes SANS NOM : un code par eleve (LKU-K7M4Q) avec sa classe,
un code par professeur avec ses classes. L'eleve ecrit son code une fois sur WhatsApp : son numero est lie au
code (par le meme hachage pseudonyme que les resultats), son niveau et sa serie sont ceux de la classe.
Seule l'ecole sait quel eleve porte quel code ; Akili ne voit jamais de nom.

Collections Firestore :
  ecoles/{ECOLE}                  nom, actif, cree_le
  ecoles_codes/{CODE}             ecole, role (eleve|prof), classe | classes, matieres, nom, actif,
                                  eleve_hash, lie_le
  enseignants_codes/{CODE}        (professeurs) meme document que l'espace enseignant existant
  ecoles_activite/{CODE}__{JOUR}  echanges du jour, par matiere (une ecriture par echange d'un eleve d'ecole)
"""
import csv
import io
import random
import re
import unicodedata
from datetime import datetime, timedelta, timezone

import espace_enseignant as prof

COLLECTION_ECOLES = "ecoles"
COLLECTION_CODES = "ecoles_codes"
COLLECTION_ACTIVITE = "ecoles_activite"
ROLE_ELEVE = "eleve"
ROLE_PROF = "prof"

# Sans I, L, O, 0, 1 : un code recopie a la main ne se confond pas.
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
LONGUEUR_CODE = 5
MOTS_MAX_MESSAGE = 6

RE_ECOLE = re.compile(r"^[A-Z]{3,4}$")
RE_CODE = re.compile(r"^([A-Z]{3,4})-([A-Z0-9]{5,8})$")
RE_DANS_TEXTE = re.compile(r"(?<![A-Z0-9])([A-Z]{3,4}) ([A-Z0-9]{5,8})(?![A-Z0-9])")

MESSAGE_CODE_INVALIDE = ("Je ne reconnais pas ce code. Vérifie-le (il ressemble à LKU-K7M4Q) ou redemande-le à "
                         "ton école. Tu peux aussi continuer sans code : écris ta question.")
MESSAGE_CODE_DEJA_UTILISE = ("Ce code est déjà utilisé avec un autre numéro. Si tu as changé de téléphone, "
                             "demande à ton école de le réinitialiser.")
MESSAGE_ERREUR = "Désolé, je n'arrive pas à vérifier ce code pour le moment. Réessaie dans un instant."


def simple(texte):
    return prof.simple(texte)


def extraire_code(texte):
    """« lku-k7m4q », « code : LKU K7M4Q » -> « LKU-K7M4Q ». Seulement un message court qui contient un chiffre
    dans la partie variable (« bonjour akili » ne passe pas). None sinon."""
    s = simple(texte)
    if not s or len(s.split()) > MOTS_MAX_MESSAGE:
        return None
    for ecole, reste in RE_DANS_TEXTE.findall(s):
        if any(c.isdigit() for c in reste):
            return f"{ecole}-{reste}"
    return None


def code_valide(code):
    return bool(RE_CODE.match(str(code or "")))


def ecole_du_code(code):
    m = RE_CODE.match(str(code or ""))
    return m.group(1) if m else ""


def nouveau_code(ecole, existants=(), rng=random):
    if not RE_ECOLE.match(ecole):
        raise ValueError(f"Code d'ecole invalide : {ecole!r} (3 ou 4 lettres majuscules)")
    for _ in range(200):
        reste = "".join(rng.choice(ALPHABET) for _ in range(LONGUEUR_CODE))
        code = f"{ecole}-{reste}"
        if any(c.isdigit() for c in reste) and code not in existants:
            return code
    raise RuntimeError("Impossible de trouver un code libre")


def classe_id(libelle):
    """'2nde C' -> '2NDE_C' ; sert de cle de regroupement dans les rapports."""
    return simple(libelle).replace(" ", "_")


def profil_de_classe(libelle):
    """Champs du profil WhatsApp pour une classe d'ecole ('Tle D', '3e', '6e'). ValueError si inconnue."""
    try:
        return prof.classe_vers_profil(libelle)
    except ValueError:
        # Classes de college avec leur division : « 6e A », « 3eme 2 » -> le niveau suffit.
        mots = simple(libelle).split()
        if len(mots) > 1 and re.fullmatch(r"[3-6](?:E|EME|IEME)", mots[0]):
            return prof.classe_vers_profil(mots[0])
        raise


# ─── Import d'une liste ────────────────────────────────────────────────────────

COLONNES = ("role", "code", "classe", "classes", "matieres", "nom")


def _separer(valeur):
    return [x.strip() for x in re.split(r"[;|]", str(valeur or "")) if x.strip()]


def lire_liste(texte_csv, ecole, connues_matieres=None, rng=random):
    """Lit le CSV remis par l'ecole. Colonnes : role (eleve|prof, 'eleve' par defaut), code (facultatif : sinon
    genere), classe (eleve), classes (prof, separees par ;), matieres (prof, codes Akili separes par ;), nom
    (prof, facultatif : 'M. Koffi'). Renvoie (lignes, erreurs) ; une ligne fausse n'empeche pas les autres."""
    lecteur = csv.DictReader(io.StringIO(texte_csv.lstrip("﻿")), delimiter=_delimiteur(texte_csv))
    lignes, erreurs, pris = [], [], set()
    for i, brut in enumerate(lecteur, start=2):
        ligne = {(k or "").strip().lower(): (v or "").strip() for k, v in brut.items()}
        role = (ligne.get("role") or ROLE_ELEVE).lower()
        role = {"eleve": ROLE_ELEVE, "élève": ROLE_ELEVE, "prof": ROLE_PROF, "professeur": ROLE_PROF}.get(role, role)
        try:
            if role not in (ROLE_ELEVE, ROLE_PROF):
                raise ValueError(f"role inconnu : {role!r}")
            code = simple(ligne.get("code", "")).replace(" ", "-")
            if code:
                if not code_valide(code) or ecole_du_code(code) != ecole or not any(c.isdigit() for c in code):
                    raise ValueError(f"code {code!r} refuse (attendu {ecole}-XXXXX avec un chiffre)")
            if role == ROLE_ELEVE:
                libelle = ligne.get("classe", "")
                profil_de_classe(libelle)
                entree = {"role": role, "code": code, "classe": libelle}
            else:
                classes = _separer(ligne.get("classes") or ligne.get("classe"))
                for libelle in classes:
                    profil_de_classe(libelle)
                matieres = [m.upper() for m in _separer(ligne.get("matieres"))]
                inconnues = [m for m in matieres if connues_matieres is not None and m not in connues_matieres]
                if not matieres or inconnues:
                    raise ValueError(f"matieres inconnues : {inconnues or 'aucune'}")
                entree = {"role": role, "code": code, "classes": classes[:10], "matieres": matieres[:10],
                          "nom": ligne.get("nom") or "Professeur"}
            if code:
                if code in pris:
                    raise ValueError(f"code {code} en double dans le fichier")
                pris.add(code)
            lignes.append(entree)
        except ValueError as e:
            erreurs.append(f"ligne {i} : {e}")
    # Codes manquants : generes une fois les codes fournis connus
    for entree in lignes:
        if not entree["code"]:
            entree["code"] = nouveau_code(ecole, pris, rng)
            pris.add(entree["code"])
    return lignes, erreurs


def _delimiteur(texte):
    premiere = texte.lstrip("﻿").splitlines()[0] if texte.strip() else ""
    return ";" if premiere.count(";") > premiere.count(",") else ","


# ─── Rapport par classe ────────────────────────────────────────────────────────

def _jour(valeur):
    return str(valeur or "")[:10]


def rapport_classes(codes, etat_actif, activite, mini_tests, revisions, du, au):
    """Chiffres par classe pour la periode [du, au] (dates 'AAAA-MM-JJ').
    codes : documents ecoles_codes ; activite : documents ecoles_activite ; mini_tests / revisions : resultats
    (champ 'eleve' = hachage) ; etat_actif : inutilise ici, reserve (derniere activite par hachage)."""
    par_classe, hash_vers_code = {}, {}
    for c in codes:
        if c.get("role") != ROLE_ELEVE or c.get("actif", True) is False:
            continue
        cl = par_classe.setdefault(c.get("classe") or "?", {
            "classe": c.get("classe") or "?", "codes": 0, "lies": 0, "actifs": set(), "echanges": 0,
            "matieres": {}, "tests_debut": 0, "tests_fin": 0, "gains": [], "revisions": 0, "revisions_justes": 0,
            "chapitres": {}, "inactifs": [], "non_lies": []})
        cl["codes"] += 1
        if c.get("eleve_hash"):
            cl["lies"] += 1
            hash_vers_code[c["eleve_hash"]] = c
        else:
            cl["non_lies"].append(c["code"])
    code_vers_classe = {c["code"]: c.get("classe") or "?" for c in codes if c.get("role") == ROLE_ELEVE}
    for a in activite:
        if not (du <= _jour(a.get("jour")) <= au):
            continue
        cl = par_classe.get(code_vers_classe.get(a.get("code")))
        if not cl or not a.get("echanges"):
            continue
        cl["actifs"].add(a["code"])
        cl["echanges"] += int(a["echanges"])
        for m, n in (a.get("matieres") or {}).items():
            cl["matieres"][m] = cl["matieres"].get(m, 0) + int(n)
    for t in mini_tests:
        c = hash_vers_code.get(t.get("eleve"))
        if not c or not (du <= _jour(t.get("cree_le")) <= au):
            continue
        cl = par_classe[c.get("classe") or "?"]
        if t.get("phase") == "debut":
            cl["tests_debut"] += 1
            cle = (t.get("matiere"), t.get("chapitre"))
            cl["chapitres"].setdefault(cle, []).append(t.get("score", 0) / max(t.get("total") or 3, 1))
        else:
            cl["tests_fin"] += 1
            if t.get("score_debut") is not None:
                cl["gains"].append(int(t.get("score", 0)) - int(t["score_debut"]))
    for r in revisions:
        c = hash_vers_code.get(r.get("eleve"))
        if not c or not (du <= _jour(r.get("envoyee_le")) <= au) or not r.get("repondu"):
            continue
        cl = par_classe[c.get("classe") or "?"]
        if r.get("juste") is not None:
            cl["revisions"] += 1
            cl["revisions_justes"] += 1 if r["juste"] else 0
    for cl in par_classe.values():
        actifs_codes = cl["actifs"]
        cl["inactifs"] = sorted(c["code"] for c in hash_vers_code.values()
                                if (c.get("classe") or "?") == cl["classe"] and c["code"] not in actifs_codes)
        cl["actifs"] = len(actifs_codes)
        cl["gain_moyen"] = round(sum(cl["gains"]) / len(cl["gains"]), 2) if cl["gains"] else None
        faibles = sorted(((sum(v) / len(v), k, len(v)) for k, v in cl["chapitres"].items() if len(v) >= 2))
        cl["chapitres_faibles"] = [(m, ch, round(100 * moy), n) for moy, (m, ch), n in faibles[:3]]
        del cl["chapitres"], cl["gains"]
    return sorted(par_classe.values(), key=lambda x: x["classe"])


def texte_rapport(nom_ecole, classes, du, au):
    lignes = [f"Akili — {nom_ecole} — du {du} au {au}", ""]
    if not classes:
        return "\n".join(lignes + ["Aucun élève enregistré pour le moment."])
    for cl in classes:
        pc = round(100 * cl["lies"] / cl["codes"]) if cl["codes"] else 0
        lignes.append(f"{cl['classe']} : {cl['lies']}/{cl['codes']} élèves connectés ({pc} %), "
                      f"{cl['actifs']} actifs cette période, {cl['echanges']} échanges")
        if cl["matieres"]:
            top = sorted(cl["matieres"].items(), key=lambda x: -x[1])[:3]
            lignes.append("  matières les plus travaillées : " + ", ".join(f"{m} ({n})" for m, n in top))
        if cl["tests_debut"] or cl["tests_fin"]:
            gain = f", progression moyenne {cl['gain_moyen']:+g} point(s) sur 3" if cl["gain_moyen"] is not None else ""
            lignes.append(f"  mini-tests : {cl['tests_debut']} de début, {cl['tests_fin']} de fin{gain}")
        if cl["revisions"]:
            lignes.append(f"  révisions : {cl['revisions_justes']}/{cl['revisions']} bonnes réponses")
        for m, ch, pct, n in cl["chapitres_faibles"]:
            lignes.append(f"  à reprendre en classe : {m} — {ch} ({pct} % de réussite, {n} élèves)")
        if cl["inactifs"]:
            lignes.append(f"  connectés mais inactifs : {', '.join(cl['inactifs'][:15])}"
                          + (" …" if len(cl["inactifs"]) > 15 else ""))
        if cl["non_lies"]:
            lignes.append(f"  codes pas encore utilisés : {len(cl['non_lies'])}")
        lignes.append("")
    return "\n".join(lignes).rstrip() + "\n"


def periode(jours, maintenant=None):
    fin = (maintenant or datetime.now(timezone.utc)).date()
    return (fin - timedelta(days=jours - 1)).isoformat(), fin.isoformat()
