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

    "Classe intermédiaire": {
        "series": ["6E", "5E", "4E", "SECONDE_A", "SECONDE_C", "PREMIERE_A", "PREMIERE_C", "PREMIERE_D"],
        "matieres_par_serie": {
            "6E": ["Mathématiques", "Français", "Histoire-Géographie", "Anglais", "SVT"],
            "5E": ["Mathématiques", "Français", "Histoire-Géographie", "Anglais", "SVT", "Physique-Chimie"],
            "4E": ["Mathématiques", "Français", "Histoire-Géographie", "Anglais", "SVT", "Physique-Chimie"],
            "SECONDE_A": ["Mathématiques", "Français", "Histoire-Géographie", "Anglais", "SVT", "Physique-Chimie"],
            "SECONDE_C": ["Mathématiques", "Français", "Histoire-Géographie", "Anglais", "SVT", "Physique-Chimie"],
            "PREMIERE_A": ["Mathématiques", "Français", "Histoire-Géographie", "Anglais"],
            "PREMIERE_C": ["Mathématiques", "Français", "Histoire-Géographie", "Anglais", "SVT", "Physique-Chimie"],
            "PREMIERE_D": ["Mathématiques", "Français", "Histoire-Géographie", "Anglais", "SVT", "Physique-Chimie"],
        }
    },

    "BAC Général": {
        "series": ["A1", "A2", "C", "D", "E"],
        "matieres_par_serie": {
            "A1": ["Français", "Mathématiques", "Histoire-Géographie",
                   "Anglais", "Allemand", "Espagnol"],
            "A2": ["Français", "Mathématiques", "Histoire-Géographie",
                   "Anglais", "Allemand", "Espagnol"],
            "C":  ["Français", "Mathématiques", "Histoire-Géographie",
                   "Anglais", "Physique-Chimie",
                   "Sciences de la Vie et de la Terre (SVT)"],
            "D":  ["Français", "Mathématiques", "Histoire-Géographie",
                   "Anglais", "Physique-Chimie",
                   "Sciences de la Vie et de la Terre (SVT)"],
            "E":  ["Français", "Mathématiques", "Histoire-Géographie",
                   "Anglais", "Physique-Chimie"],
        }
    },

    "BAC Technique": {
        "series": ["B", "E", "F1", "F2", "F3", "F4", "G1", "G2"],
        "matieres_par_serie": {
            "B": [
                "Comptabilité Financière",
                "Comptabilité des sociétés",
                "Comptabilité Analytique",
                "Mathématiques financières",
                "Mathématique Générale",
                "Économie",
                "Expression Professionnelle",
                "Physique Appliquée",
                "Étude des Systèmes Techniques Industriels",
                "Droit",
                "Histoire-Géographie",
                "Français",
            ],
            "E": [
                "Comptabilité Financière",
                "Comptabilité des sociétés",
                "Comptabilité Analytique",
                "Mathématiques financières",
                "Mathématique Générale",
                "Économie",
                "Expression Professionnelle",
                "Physique Appliquée",
                "Étude des Systèmes Techniques Industriels",
                "Droit",
                "Histoire-Géographie",
                "Français",
            ],
            "F1": [
                "Comptabilité Financière",
                "Comptabilité des sociétés",
                "Comptabilité Analytique",
                "Mathématiques financières",
                "Mathématique Générale",
                "Économie",
                "Expression Professionnelle",
                "Physique Appliquée",
                "Étude des Systèmes Techniques Industriels",
                "Droit",
                "Histoire-Géographie",
                "Français",
            ],
            "F2": [
                "Comptabilité Financière",
                "Comptabilité des sociétés",
                "Comptabilité Analytique",
                "Mathématiques financières",
                "Mathématique Générale",
                "Économie",
                "Expression Professionnelle",
                "Physique Appliquée",
                "Étude des Systèmes Techniques Industriels",
                "Droit",
                "Histoire-Géographie",
                "Français",
            ],
            "F3": [
                "Comptabilité Financière",
                "Comptabilité des sociétés",
                "Comptabilité Analytique",
                "Mathématiques financières",
                "Mathématique Générale",
                "Économie",
                "Expression Professionnelle",
                "Physique Appliquée",
                "Étude des Systèmes Techniques Industriels",
                "Droit",
                "Histoire-Géographie",
                "Français",
            ],
            "F4": [
                "Comptabilité Financière",
                "Comptabilité des sociétés",
                "Comptabilité Analytique",
                "Mathématiques financières",
                "Mathématique Générale",
                "Économie",
                "Expression Professionnelle",
                "Physique Appliquée",
                "Étude des Systèmes Techniques Industriels",
                "Droit",
                "Histoire-Géographie",
                "Français",
            ],
            "G1": [
                "Comptabilité Financière",
                "Comptabilité des sociétés",
                "Comptabilité Analytique",
                "Mathématiques financières",
                "Mathématique Générale",
                "Économie",
                "Expression Professionnelle",
                "Physique Appliquée",
                "Étude des Systèmes Techniques Industriels",
                "Droit",
                "Histoire-Géographie",
                "Français",
            ],
            "G2": [
                "Comptabilité Financière",
                "Comptabilité des sociétés",
                "Comptabilité Analytique",
                "Mathématiques financières",
                "Mathématique Générale",
                "Économie",
                "Expression Professionnelle",
                "Physique Appliquée",
                "Étude des Systèmes Techniques Industriels",
                "Droit",
                "Histoire-Géographie",
                "Français",
            ],
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
