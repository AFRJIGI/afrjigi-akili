"""Route les réponses rapides du modèle de rétention sans appel externe."""
import unicodedata


def retention_template_text(message):
    if message.get("type") != "button":
        return None
    button = message.get("button") or {}
    # Le payload est choisi à l'envoi : il n'est pas connu depuis l'aperçu Meta.
    # Utiliser le libellé exact du bouton approuvé, jamais un payload arbitraire.
    label = str(button.get("text") or "").strip()
    normalized = "".join(
        c for c in unicodedata.normalize("NFKD", label) if not unicodedata.combining(c)
    ).casefold()
    return {
        "maths": "Maths",
        "autre matiere": "changer de matiere",
        "se desinscrire": "STOP",
    }.get(normalized)
