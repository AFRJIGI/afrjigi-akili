# coefficients.py
# Source : DPFC, "Coefficients du 1er et du 2nd cycles de l'enseignement 
# secondaire general", Annee scolaire 2024-2025 (BEPC + BAC General uniquement,
# le BAC Technique n'est pas couvert par ce document officiel).

COEFFICIENTS = {
    "6EME": {"ANGLAIS": 2, "ARTS": 1, "EDHC": 1, "EPS": 1, "FRENCH": 3, "HG": 2, "ALLEMAND": None, "ESPAGNOL": None, "MATHS": 3, "PHILO": None, "PC": 2, "SVT": 2, "CONDUITE": 1},
    "5EME": {"ANGLAIS": 2, "ARTS": 1, "EDHC": 1, "EPS": 1, "FRENCH": 3, "HG": 2, "ALLEMAND": None, "ESPAGNOL": None, "MATHS": 3, "PHILO": None, "PC": 2, "SVT": 2, "CONDUITE": 1},
    "4EME": {"ANGLAIS": 2, "ARTS": 1, "EDHC": 1, "EPS": 1, "FRENCH": 4, "HG": 2, "ALLEMAND": 1, "ESPAGNOL": 1, "MATHS": 3, "PHILO": None, "PC": 2, "SVT": 2, "CONDUITE": 1},
    "3EME": {"ANGLAIS": 2, "ARTS": 1, "EDHC": 1, "EPS": 1, "FRENCH": 4, "HG": 2, "ALLEMAND": 1, "ESPAGNOL": 1, "MATHS": 3, "PHILO": None, "PC": 2, "SVT": 2, "CONDUITE": 1},

    "A": {"ANGLAIS": 3, "ARTS": 1, "EDHC": None, "EPS": 1, "FRENCH": 4, "HG": 3, "ALLEMAND": 3, "ESPAGNOL": 3, "MATHS": 3, "PHILO": None, "PC": 2, "SVT": 2, "CONDUITE": 1},   # 2ndeA
    "C": {"ANGLAIS": 3, "ARTS": 1, "EDHC": None, "EPS": 1, "FRENCH": 3, "HG": 2, "ALLEMAND": 1, "ESPAGNOL": 1, "MATHS": 5, "PHILO": None, "PC": 4, "SVT": 2, "CONDUITE": 1},   # 2ndeC

    "A1": {"ANGLAIS": 4, "ARTS": 1, "EDHC": None, "EPS": 1, "FRENCH": 4, "HG": 3, "ALLEMAND": 3, "ESPAGNOL": 3, "MATHS": 3, "PHILO": 3, "PC": 1, "SVT": 1, "CONDUITE": 1},   # 1ereA / TA
    "A2": {"ANGLAIS": 4, "ARTS": 1, "EDHC": None, "EPS": 1, "FRENCH": 4, "HG": 3, "ALLEMAND": 3, "ESPAGNOL": 3, "MATHS": 2, "PHILO": 3, "PC": 1, "SVT": 1, "CONDUITE": 1},   # 1ereA / TA

    "D": {"ANGLAIS": 2, "ARTS": 1, "EDHC": None, "EPS": 1, "FRENCH": 3, "HG": 2, "ALLEMAND": "1 Fac", "ESPAGNOL": "1 Fac", "MATHS": 4, "PHILO": 2, "PC": 4, "SVT": 4, "CONDUITE": 1},   # 1ereD / TD
}

# Cas particuliers Terminale (differents de 1ere pour C et pour A1/A2 sur certaines matieres)
COEFFICIENTS_TERMINALE_OVERRIDES = {
    "C": {"ANGLAIS": 1, "HG": 2, "ALLEMAND": "1 Fac", "ESPAGNOL": "1 Fac", "MATHS": 5, "PHILO": 2, "PC": 5, "SVT": 2},   # TC
    "A1": {"MATHS": 4, "PC": None, "PHILO": 5, "SVT": 2},  # TA : A1=4, PC absent, Philo=5, SVT=2
    "A2": {"MATHS": 2, "PC": None, "PHILO": 5, "SVT": 2},  # TA : A2=2, PC absent, Philo=5, SVT=2
    "D": {"ANGLAIS": 1},  # TD : Anglais=1 en Terminale D
}


def normaliser_serie(serie):
    """Normalise un libelle de serie vers une cle du dict COEFFICIENTS."""
    s = (serie or "").upper().strip()
    if s in ("6EME", "6E", "6È", "6ÈME"):
        return "6EME"
    if s in ("5EME", "5E", "5È", "5ÈME"):
        return "5EME"
    if s in ("4EME", "4E", "4È", "4ÈME"):
        return "4EME"
    if s in ("3EME", "3E", "3È", "3ÈME"):
        return "3EME"
    if s in ("A1",):
        return "A1"
    if s in ("A2",):
        return "A2"
    if s in ("A",):
        return "A"
    if s in ("C",):
        return "C"
    if s in ("D",):
        return "D"
    return None


def get_coefficient(matiere, serie, niveau="TERMINALE"):
    """
    Retourne le coefficient officiel DPFC pour une matiere et une serie donnees.
    niveau : "SECONDE", "PREMIERE" ou "TERMINALE" (utile pour les series A1/A2/C
    qui ont des coefficients differents en Terminale).
    Retourne None si la matiere n'est pas enseignee dans cette serie, ou si la
    combinaison n'est pas couverte par le document officiel (ex: BAC Technique).
    """
    s = normaliser_serie(serie)
    if not s or s not in COEFFICIENTS:
        return None

    matiere = (matiere or "").upper().strip()
    coef = COEFFICIENTS[s].get(matiere)

    if niveau == "TERMINALE" and s in COEFFICIENTS_TERMINALE_OVERRIDES:
        override = COEFFICIENTS_TERMINALE_OVERRIDES[s].get(matiere)
        if override is not None or matiere in COEFFICIENTS_TERMINALE_OVERRIDES[s]:
            coef = override

    return coef


def get_toutes_matieres_serie(serie, niveau="TERMINALE"):
    """Retourne un dict {matiere: coefficient} pour toutes les matieres d'une serie,
    en excluant celles a None (non enseignees)."""
    s = normaliser_serie(serie)
    if not s or s not in COEFFICIENTS:
        return {}
    result = {}
    for matiere in COEFFICIENTS[s]:
        c = get_coefficient(matiere, serie, niveau)
        if c is not None:
            result[matiere] = c
    return result
