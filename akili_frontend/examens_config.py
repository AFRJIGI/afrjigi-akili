# examens_config.py
# Structure de configuration des examens : type d'examen -> series -> matieres
# Valide avec Daouda le 17/07/2026 (donnees terrain BAC Technique ivoirien)

EXAMENS = {
    "BEPC": {
        "series": None,  # pas de choix de serie pour le BEPC
        "matieres": [
            "Mathématiques", "Physique-Chimie", "SVT", "Français",
            "Histoire-Géographie", "Anglais", "Allemand", "Espagnol",
            "EDHC", "Arts Plastiques", "Éducation Musicale"
        ]
    },

    "BAC Général": {
        "series": ["A1", "A2", "C", "D"],
        "matieres_par_serie": {
            "A1": ["Français", "Mathématiques", "Philosophie", "Histoire-Géographie",
                   "Anglais", "Allemand", "Espagnol"],
            "A2": ["Français", "Mathématiques", "Philosophie", "Histoire-Géographie",
                   "Anglais", "Allemand", "Espagnol"],
            "C":  ["Français", "Mathématiques", "Philosophie", "Histoire-Géographie",
                   "Anglais", "Physique-Chimie",
                   "Sciences de la Vie et de la Terre (SVT)"],
            "D":  ["Français", "Mathématiques", "Philosophie", "Histoire-Géographie",
                   "Anglais", "Physique-Chimie",
                   "Sciences de la Vie et de la Terre (SVT)"],
        }
    },

    "BAC Technique": {
        "series": ["B", "E", "F1", "F2", "F3", "F4", "F7", "G1", "G2"],
        "matieres_par_serie": {
            "B": ["Économie", "Mathématiques", "Français", "Philosophie", "Histoire-Géographie",
                  "Anglais", "Allemand", "Espagnol"],

            "E": ["Mathématiques", "Physique-Chimie", "Électrotechnique", "Mécanique",
                  "Dessin de construction", "Sciences Industrielles", "Français",
                  "Philosophie", "Histoire-Géographie", "Anglais"],

            "F1": ["Dessin technique", "Construction mécanique", "Technologie",
                   "Mathématiques", "Physique-Chimie", "Français", "Philosophie",
                   "Histoire-Géographie", "Anglais"],

            "F2": ["ESTI", "Électronique", "Électrotechnique", "Physique appliquée",
                   "Mesure", "Analyse fonctionnelle", "Mathématiques", "Français",
                   "Philosophie", "Histoire-Géographie", "Anglais"],

            "F3": ["Électrotechnique", "Électronique", "Construction électrique",
                   "Physique appliquée", "Mathématiques", "Français", "Philosophie",
                   "Histoire-Géographie", "Anglais"],

            "F4": ["Technologie de construction", "Topographie", "Résistance des matériaux",
                   "Physique", "Mathématiques", "Français", "Philosophie",
                   "Histoire-Géographie", "Anglais"],

            "F7": ["Mathématiques", "Physique-Chimie", "Français", "Philosophie",
                   "Histoire-Géographie", "Anglais"],

            "G1": ["Étude de cas", "Techniques d'organisation", "Correspondance commerciale",
                   "Droit", "Économie", "Outils de communication", "Mathématiques",
                   "Français", "Philosophie", "Histoire-Géographie", "Anglais"],

            "G2": ["Comptabilité", "Mathématiques financières", "Étude de cas",
                   "Droit", "Économie", "Mathématiques", "Français", "Philosophie",
                   "Histoire-Géographie", "Anglais"],
        }
    }
}


def get_series(type_examen):
    """Retourne la liste des series pour un type d'examen (ou None si pas de serie, ex. BEPC)."""
    return EXAMENS.get(type_examen, {}).get("series")


def get_matieres(type_examen, serie=None):
    """Retourne la liste des matieres pour un type d'examen (et une serie si applicable)."""
    config = EXAMENS.get(type_examen, {})
    if "matieres" in config:
        return config["matieres"]
    if "matieres_par_serie" in config and serie:
        return config["matieres_par_serie"].get(serie, [])
    return []
