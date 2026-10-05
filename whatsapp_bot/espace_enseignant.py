"""Espace enseignant : codes d'acces, classes et textes (sans Firestore ni WhatsApp).

Un code (PROF-SIDIBE-4821) est cree par gerer_enseignants.py et envoye au professeur.
Il l'ecrit une fois sur WhatsApp : son numero devient un profil enseignant verifie,
rattache a son nom, a ses matieres et a ses classes.
"""
import random
import re
import unicodedata

COLLECTION_CODES = "enseignants_codes"
COLLECTION_SIGNALEMENTS = "signalements_enseignants"
MODE_ELEVE = "eleve"          # l'enseignant voit Akili exactement comme ses eleves
MODE_ASSISTANT = "assistant"  # Akili l'aide a preparer cours, exercices, evaluations
MODE_PROFIL_ASSISTANT = "enseignant"  # valeur de profile["mode"] : historique separe du mode eleve

SERIES_GENERALES = {"A", "A1", "A2", "C", "D"}
SERIES_TECHNIQUES = {"B", "G1", "G2", "E", "F1", "F2", "F3", "F4", "F7"}
CLASSES_TECHNIQUES = {"SECONDE": "2nde", "PREMIERE": "1ère", "TERMINALE": "Tle"}


def simple(texte):
    texte = unicodedata.normalize("NFKD", str(texte or ""))
    texte = "".join(c for c in texte if not unicodedata.combining(c)).upper()
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", texte).split())


def slug_nom(nom):
    """'M. Sidibé' -> 'SIDIBE' (premier mot du nom hors civilité, 12 lettres au plus)."""
    mots = [m for m in simple(nom).split() if m not in {"M", "MR", "MME", "MLLE", "DR", "PROF"} and m.isalpha()]
    return (mots[0] if mots else "PROF")[:12]


def nouveau_code(nom, existants=(), rng=random):
    for _ in range(50):
        code = f"PROF-{slug_nom(nom)}-{rng.randint(1000, 9999)}"
        if code not in existants:
            return code
    raise RuntimeError("Impossible de trouver un code libre")


def extraire_code(texte):
    """Code enseignant dans un message ("PROF-SIDIBE-4821", "code : prof sidibe 4821"), sinon None."""
    trouve = re.search(r"(?<![A-Z0-9])PROF ([A-Z]{2,12}) (\d{4})(?![A-Z0-9])", simple(texte))
    return f"PROF-{trouve.group(1)}-{trouve.group(2)}" if trouve else None


def classe_vers_profil(libelle):
    """'2nde F2' -> champs du profil WhatsApp. ValueError si la classe n'est pas reconnue."""
    mots = re.sub(r"(\d)(?:EME|IEME|E|ER|ERE)\b", r"\1E", simple(libelle)).split()
    if not mots:
        raise ValueError(f"Classe vide : {libelle!r}")
    niveau, serie = mots[0], (mots[1] if len(mots) > 1 else "")
    niveau = {"2NDE": "SECONDE", "2ND": "SECONDE", "2E": "SECONDE", "1E": "PREMIERE", "1RE": "PREMIERE", "TLE": "TERMINALE", "TERM": "TERMINALE", "3E": "3E", "TROISIEME": "3E",
              "6E": "6E", "5E": "5E", "4E": "4E"}.get(niveau, niveau)
    if niveau in {"6E", "5E", "4E"} and not serie:
        return {"type_examen": "CLASSE_INTERMEDIAIRE", "serie": niveau, "classe": ""}
    if niveau in {"3E", "BEPC"} and not serie:
        return {"type_examen": "BEPC", "serie": "BEPC", "classe": ""}
    if serie in SERIES_TECHNIQUES and niveau in CLASSES_TECHNIQUES:
        return {"type_examen": "BAC_TECHNIQUE", "serie": serie, "classe": niveau}
    if serie in SERIES_GENERALES:
        lettre = serie[0]
        if niveau == "TERMINALE":
            return {"type_examen": "BAC_GENERAL", "serie": "A1" if serie == "A" else serie, "classe": ""}
        if niveau == "SECONDE" and lettre in {"A", "C"}:
            return {"type_examen": "CLASSE_INTERMEDIAIRE", "serie": f"SECONDE_{lettre}", "classe": ""}
        if niveau == "PREMIERE" and lettre in {"A", "C", "D"}:
            return {"type_examen": "CLASSE_INTERMEDIAIRE", "serie": f"PREMIERE_{lettre}", "classe": ""}
    raise ValueError(f"Classe non reconnue : {libelle!r} (exemples : 2nde F2, 1ère D, Tle C, 3e, 6e)")


def options_menu(nom):
    return (
        f"Espace enseignant de {nom}. Que voulez-vous faire ?",
        [
            ("a", "Voir comme vos élèves", "Akili vous répond comme à un élève (mode étude)"),
            ("b", "Préparer cours, évals", "Fiche de leçon, exercices, évaluation, corrigé, barème"),
            ("c", "Matière ou classe", "Changer la matière ou la classe de travail"),
            ("d", "Signaler une erreur", "Une réponse d'Akili à corriger"),
            ("e", "Élève en mode examen", "Akili vous fait passer un sujet, puis corrige et note"),
        ],
    )


def message_bienvenue(nom, resume_matieres, resume_classes):
    return (
        f"Bonjour {nom}, votre espace enseignant Akili est activé.\n"
        f"Matières : {resume_matieres}\nClasses : {resume_classes}\n\n"
        "Merci pour les documents que vous partagez : Akili s'en sert déjà avec les élèves."
    )


def message_mode_eleve(resume, examen=False):
    if examen:
        debut = (f"Mode élève, examen activé ({resume}) : Akili vous traite comme un élève qui s'entraîne "
                 "pour l'examen. Il vous tutoie, vous fait résoudre seul, puis corrige et note avec le barème. "
                 "Demandez un sujet ou envoyez le vôtre.\n\n")
    else:
        debut = (f"Mode élève activé : Akili vous répond exactement comme à un élève ({resume}). "
                 "Il va vous tutoyer et vous guider pas à pas. Posez une question ou envoyez un exercice.\n\n")
    return (
        debut +
        "Pour signaler une erreur : écrivez « correction : » suivi de votre remarque.\n"
        "Pour revenir à votre espace : écrivez « menu prof »."
    )


def message_mode_assistant(resume):
    return (
        f"Mode préparation activé ({resume}). Exemples de demandes :\n"
        "• Prépare la leçon de cette semaine selon la progression\n"
        "• Une évaluation de 30 min sur ce chapitre, avec corrigé et barème\n"
        "• 3 exercices gradués sur cette notion\n"
        "• Corrige cette copie (envoyez une photo)\n\n"
        "Les réponses longues arrivent en plusieurs messages : écrivez « suite ».\n"
        "Pour revenir à votre espace : « menu prof »."
    )


MESSAGE_CODE_INVALIDE = ("Ce code enseignant n'est pas valide. Vérifiez-le, ou contactez l'équipe AfrJigi "
                         "qui vous l'a envoyé.")
MESSAGE_CODE_DEJA_UTILISE = ("Ce code enseignant a déjà été activé sur un autre numéro. "
                             "Contactez l'équipe AfrJigi pour en recevoir un nouveau.")
MESSAGE_DEMANDE_SIGNALEMENT = (
    "Décrivez l'erreur en un message : ce qui est faux et, si possible, la bonne réponse. "
    "Je transmets à l'équipe Akili avec la dernière réponse d'Akili.\n\n(Écrivez « annuler » pour revenir.)"
)
MESSAGE_DEMANDE_CLASSES = (
    "Dans quelles classes enseignez-vous ? Écrivez-les séparées par des virgules.\n"
    "Exemples : 2nde F2, 1ère F2, Tle F2 — ou : Tle D, 1ère C — ou : 3e, 4e"
)
COMMANDES_CLASSES = {"MES CLASSES", "MODIFIER MES CLASSES", "CHANGER MES CLASSES", "AJOUTER UNE CLASSE"}
COMMANDES_MENU = {"MENU PROF", "ESPACE PROF", "ESPACE ENSEIGNANT", "MENU ENSEIGNANT", "MENU PROFESSEUR"}
PREFIXES_SIGNALEMENT = ("CORRECTION", "ERREUR", "SIGNALEMENT", "SIGNALER")


def lire_classes(texte):
    """'2nde F2, 1ère F2 et Tle F2' -> (['2nde F2', '1ère F2', 'Tle F2'], [classes non reconnues])."""
    reconnues, inconnues = [], []
    for morceau in re.split(r"[,;/\n]+|\s+et\s+", str(texte or ""), flags=re.I):
        morceau = " ".join(morceau.split()).strip(" .")
        if not morceau:
            continue
        try:
            classe_vers_profil(morceau)
        except ValueError:
            inconnues.append(morceau)
            continue
        if morceau not in reconnues:
            reconnues.append(morceau)
    return reconnues[:10], inconnues


def est_commande_classes(texte):
    return simple(texte) in COMMANDES_CLASSES


def est_commande_menu(texte):
    return simple(texte) in COMMANDES_MENU


def texte_signalement(texte):
    """'correction : la reponse est 40 N.m' -> 'la reponse est 40 N.m' ; None si ce n'est pas un signalement."""
    brut = str(texte or "").strip()
    mots = simple(brut).split()
    if not mots or mots[0] not in PREFIXES_SIGNALEMENT or len(mots) < 3:
        return None
    reste = re.sub(r"^\W*\w+\s*(?:d'une\s+|une\s+)?(?:erreur\s*)?[:\-–]?\s*", "", brut, count=1, flags=re.I)
    return reste.strip() or brut


def message_merci_signalement(nom):
    return (f"Merci {nom}, c'est noté. Votre remarque est transmise à l'équipe Akili, "
            "qui corrigera la base. Vous pouvez continuer.")
