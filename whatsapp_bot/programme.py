"""Programme personnalise de revision (« mon programme ») : un plan a rebours jusqu'a l'examen.

L'eleve choisit 1 a 3 matieres prioritaires et le temps dont il dispose ; Akili repartit des seances par
semaine selon les coefficients de sa serie (doubles pour les matieres prioritaires) et selon la phase de
l'annee (revoir le programme, sujets type examen, revision finale).

Ce module ne contient que la logique (dates, calcul, messages) ; l'envoi est dans main.py. Le programme est
garde dans le profil (cle « programme », sans nom ni numero), l'etape en cours dans « programme_etape ».
"""
from datetime import date

# Calendrier des examens 2027 : image diffusee en octobre 2026, a confirmer par un texte officiel du MENA
# ou de la DECO (le decoupage officiel de l'annee, publie sur gouv.ci, ne donne pas encore ces dates).
# Une seule table a corriger si les dates changent.
EXAMENS = {
    "BAC_GENERAL": {"libelle": "BAC", "ecrits": date(2027, 6, 14), "texte": "écrits du 14 au 18 juin 2027"},
    "BAC_TECHNIQUE": {"libelle": "BAC technique", "ecrits": date(2027, 6, 14),
                      "texte": "pratiques du 1er au 12 juin, écrits du 14 au 18 juin 2027"},
    "BEPC": {"libelle": "BEPC", "ecrits": date(2027, 7, 5), "texte": "écrits du 5 au 9 juillet 2027"},
}
FIN_REVOIR_PROGRAMME = date(2027, 3, 31)   # puis sujets type examen
JOURS_REVISION_FINALE = 21                  # les 3 dernieres semaines

# Coefficients officiels (DPFC 2024-2025) des classes d'examen : 3e et Terminale (overrides inclus).
# Les langues facultatives (« 1 Fac ») et la 2e langue des series A ne comptent que si l'eleve les choisit.
COEFFICIENTS = {
    "BEPC": {"MATHS": 3, "PC": 2, "SVT": 2, "FRANCAIS": 4, "HG": 2, "EDHC": 1, "ANGLAIS": 2,
             "ESPAGNOL": 1, "ALLEMAND": 1},
    "A1": {"MATHS": 4, "SVT": 2, "FRANCAIS": 4, "PHILO": 5, "HG": 3, "ANGLAIS": 4, "ESPAGNOL": 3, "ALLEMAND": 3},
    "A2": {"MATHS": 2, "SVT": 2, "FRANCAIS": 4, "PHILO": 5, "HG": 3, "ANGLAIS": 4, "ESPAGNOL": 3, "ALLEMAND": 3},
    "C": {"MATHS": 5, "PC": 5, "SVT": 2, "FRANCAIS": 3, "PHILO": 2, "HG": 2, "ANGLAIS": 1,
          "ESPAGNOL": 1, "ALLEMAND": 1},
    "D": {"MATHS": 4, "PC": 4, "SVT": 4, "FRANCAIS": 3, "PHILO": 2, "HG": 2, "ANGLAIS": 1,
          "ESPAGNOL": 1, "ALLEMAND": 1},
}
SEULEMENT_SI_CHOISIES = {"ESPAGNOL", "ALLEMAND"}
ORDRE_GENERAL = ["MATHS", "PC", "SVT", "FRANCAIS", "PHILO", "HG", "EDHC", "ANGLAIS", "ESPAGNOL", "ALLEMAND"]

TEMPS = [  # (lettre, code, libelle, seances par semaine)
    ("a", "30", "30 min par jour", 5),
    ("b", "60", "1 h par jour", 7),
    ("c", "120", "2 h par jour", 12),
    ("d", "WE", "Surtout le week-end", 4),
]
SEANCES_PAR_TEMPS = {code: n for _, code, _, n in TEMPS}
MAX_PRIORITAIRES = 3

COMMANDES = {"MON PROGRAMME", "MON PLANNING", "PLANNING", "MON PLAN", "PLAN DE REVISION",
             "MON PLAN DE REVISION", "MON PROGRAMME DE REVISION", "PROGRAMME DE REVISION",
             "MON PROGRAMME PERSONNALISE", "PROGRAMME PERSONNALISE"}

PAS_D_EXAMEN = ("Le programme de révision prépare un examen (BEPC ou BAC). Ta classe n'a pas d'examen "
                "national cette année : on continue ensemble, chapitre par chapitre. Écris menu pour "
                "changer de niveau si tu es en 3e ou en Terminale.")
EXAMEN_PASSE = "Les examens de cette session sont passés : ton programme reviendra pour la prochaine session."
PRIORITES_NON_COMPRISES = ("Réponds avec 1 à 3 lettres de la liste, par exemple : a c. "
                           "Ou écris fin pour arrêter.")


def examen_du_profil(profile):
    """Code d'examen (cle de EXAMENS) si l'eleve est dans une classe d'examen, sinon None."""
    examen = (profile.get("type_examen") or "").upper()
    if examen == "BEPC" or examen == "BAC_GENERAL":
        return examen
    if examen == "BAC_TECHNIQUE" and (profile.get("classe") or "").upper() in {"", "TERMINALE"}:
        return examen
    return None


def matieres_du_profil(profile, matieres_techniques=None):
    """[(code, libelle, coefficient)] des matieres de l'examen. BAC technique : coefficients du METFPA pas
    encore integres, poids egal (1) pour chaque matiere de la serie."""
    examen = examen_du_profil(profile)
    if examen == "BAC_TECHNIQUE":
        return [(code, libelle, 1) for code, libelle in (matieres_techniques or [])]
    cle = "BEPC" if examen == "BEPC" else (profile.get("serie") or "").upper()
    coefs = COEFFICIENTS.get(cle)
    if not coefs:
        return []
    return [(code, LIBELLES.get(code, code), coefs[code]) for code in ORDRE_GENERAL if code in coefs]


LIBELLES = {"MATHS": "Mathématiques", "PC": "Physique-Chimie", "SVT": "SVT", "FRANCAIS": "Français",
            "PHILO": "Philosophie", "HG": "Histoire-Géographie", "EDHC": "EDHC", "ANGLAIS": "Anglais",
            "ESPAGNOL": "Espagnol", "ALLEMAND": "Allemand"}
LETTRES = "abcdefghijklm"


def semaines_restantes(examen, aujourd_hui):
    """Semaines entieres (arrondies au-dessus) jusqu'au premier jour des ecrits ; 0 si c'est passe."""
    jours = (EXAMENS[examen]["ecrits"] - aujourd_hui).days
    return 0 if jours <= 0 else -(-jours // 7)


def phase(examen, aujourd_hui):
    jours = (EXAMENS[examen]["ecrits"] - aujourd_hui).days
    if jours <= JOURS_REVISION_FINALE:
        return "finale"
    if aujourd_hui > FIN_REVOIR_PROGRAMME:
        return "sujets"
    return "revoir"


TEXTE_PHASES = {
    "revoir": "Revoir le programme : chaque séance sur le chapitre que tu fais en classe, en mode étude.",
    "sujets": "Sujets type examen : au moins une épreuve complète par semaine, en mode examen.",
    "finale": "Révision finale : sujets complets et examens blancs, en mode examen, sur tes points faibles.",
}


def repartir(matieres, prioritaires, seances):
    """{code: nombre de seances} : poids = coefficient x 2 si prioritaire ; plus forts restes ; chaque
    matiere prioritaire a au moins une seance. Les langues facultatives n'entrent que si elles sont choisies."""
    poids = {code: coef * (2 if code in prioritaires else 1)
             for code, _, coef in matieres if coef and (code not in SEULEMENT_SI_CHOISIES or code in prioritaires)}
    total = sum(poids.values())
    if not total or seances <= 0:
        return {}
    exact = {code: seances * p / total for code, p in poids.items()}
    resultat = {code: int(v) for code, v in exact.items()}
    reste = seances - sum(resultat.values())
    ordre = sorted(poids, key=lambda c: (-(exact[c] - resultat[c]), -poids[c], c))
    for code in ordre[:reste]:
        resultat[code] += 1
    for code in prioritaires:  # une prioritaire sans seance la prend a la matiere la mieux servie non prioritaire
        if code in resultat and resultat[code] == 0:
            donneur = max((c for c in resultat if c not in prioritaires and resultat[c] > 0),
                          key=lambda c: resultat[c], default=None)
            if donneur:
                resultat[donneur] -= 1
                resultat[code] += 1
    return {code: n for code, n in resultat.items() if n > 0}


def question_prioritaires(matieres, examen, aujourd_hui):
    semaines = semaines_restantes(examen, aujourd_hui)
    avec_coef = examen != "BAC_TECHNIQUE"  # coefficients du METFPA pas encore integres
    lignes = [f"{LETTRES[i]}. {libelle}" + (f" (coef. {coef})" if avec_coef and coef else "")
              for i, (_, libelle, coef) in enumerate(matieres)]
    return (f"📅 Il te reste {semaines} semaines avant le {EXAMENS[examen]['libelle']} "
            f"({EXAMENS[examen]['texte']}).\n\nOn prépare ton programme de révision. Quelles matières "
            f"veux-tu renforcer en priorité ? Choisis jusqu'à {MAX_PRIORITAIRES} lettres, par exemple : a c\n\n"
            + "\n".join(lignes))


def lire_prioritaires(texte, matieres):
    """Codes choisis (1 a 3, sans doublon) depuis « a c », « a,c », « ac », « 1 3 » ; None si illisible."""
    t = (texte or "").strip().lower()
    for separateur in ",;/-.+&":
        t = t.replace(separateur, " ")
    t = t.replace(" et ", " ")
    morceaux = t.split()
    if len(morceaux) == 1 and morceaux[0].isalpha() and len(morceaux[0]) <= MAX_PRIORITAIRES:
        morceaux = list(morceaux[0])
    lettres = []
    for m in morceaux:
        if m.isdigit() and 1 <= int(m) <= len(matieres):
            m = LETTRES[int(m) - 1]
        if len(m) != 1 or m not in LETTRES[:len(matieres)]:
            return None
        if m not in lettres:
            lettres.append(m)
    if not 1 <= len(lettres) <= MAX_PRIORITAIRES:
        return None
    return [matieres[LETTRES.index(l)][0] for l in lettres]


def lire_temps(texte):
    t = (texte or "").strip().lower().rstrip(".")
    for lettre, code, libelle, _ in TEMPS:
        if t in {lettre, code.lower(), libelle.lower()}:
            return code
    chiffres = {"1": "a", "2": "b", "3": "c", "4": "d"}
    if t in chiffres:
        return next(code for lettre, code, _, _ in TEMPS if lettre == chiffres[t])
    return None


def texte_programme(profile, programme, matieres, aujourd_hui):
    """Message du programme : semaines restantes, phase, seances de la semaine."""
    examen = programme["examen"]
    semaines = semaines_restantes(examen, aujourd_hui)
    if semaines <= 0:
        return EXAMEN_PASSE
    libelles = {code: libelle for code, libelle, _ in matieres}
    seances = repartir(matieres, programme.get("prioritaires") or [], SEANCES_PAR_TEMPS.get(programme.get("temps"), 5))
    ordre = sorted(seances, key=lambda c: (c not in (programme.get("prioritaires") or []), -seances[c]))
    lignes = [f"• {libelles.get(c, c)} : {seances[c]} séance{'s' if seances[c] > 1 else ''}"
              + (" ⭐" if c in (programme.get("prioritaires") or []) else "") for c in ordre]
    serie = (profile.get("serie") or "").upper()
    titre = EXAMENS[examen]["libelle"] + (f" {serie}" if serie and serie != "BEPC" else "")
    etape = phase(examen, aujourd_hui)
    premiere = libelles.get(ordre[0], "") if ordre else ""
    actuelle = (profile.get("matiere") or "").upper()
    if not premiere:
        depart = ""
    elif ordre[0] == actuelle or actuelle.startswith(ordre[0] + "_"):
        depart = f"\n\nTu es déjà en {premiere} : envoie ton exercice ou demande un exercice pour commencer."
    else:
        depart = f"\n\nPour commencer, écris : « on passe en {premiere.lower()} »."
    return (f"🎯 *Ton programme {titre}* : {semaines} semaine{'s' if semaines > 1 else ''} avant les écrits.\n\n"
            f"*En ce moment* : {TEXTE_PHASES[etape]}\n\n"
            f"*Cette semaine* (⭐ = tes priorités) :\n" + "\n".join(lignes)
            + "\n\nUne séance = environ 30 minutes avec Akili, sur un exercice ou un chapitre."
            + depart
            + "\n\nTu peux revoir ce programme à tout moment : écris « mon programme ».")
