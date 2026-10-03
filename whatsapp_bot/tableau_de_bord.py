"""Tableau de bord quotidien d'Akili : calcul des chiffres et page HTML.

Aucune donnee personnelle n'est affichee : ni numero, ni nom, seulement des totaux
et des extraits d'avis sans leur auteur.
"""

import html
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

JOURS_FR = ["L", "M", "M", "J", "V", "S", "D"]
LIBELLES_NOTES = {"oui": "Oui 👍", "un_peu": "Un peu", "non": "Non"}


def jour_de(iso):
    try:
        return datetime.fromisoformat(str(iso)).astimezone(timezone.utc).date()
    except (TypeError, ValueError):
        return None


def calculer_stats(messages, avis, maintenant, nb_jours=7):
    """Chiffres des nb_jours derniers jours (jour UTC = jour d'Abidjan)."""
    aujourd_hui = maintenant.astimezone(timezone.utc).date()
    jours = [aujourd_hui - timedelta(days=i) for i in range(nb_jours - 1, -1, -1)]
    actifs = defaultdict(set)
    nb_messages = Counter()
    hier = aujourd_hui - timedelta(days=1)
    heure_actuelle = maintenant.astimezone(timezone.utc).time()
    actifs_hier_meme_heure, messages_hier_meme_heure = set(), 0
    derniere_matiere = {}
    for m in sorted(messages, key=lambda m: str(m.get("created_at", ""))):
        if m.get("direction") != "inbound" or not m.get("phone"):
            continue
        j = jour_de(m.get("created_at"))
        if j not in jours:
            continue
        actifs[j].add(m["phone"])
        nb_messages[j] += 1
        if j == hier and datetime.fromisoformat(str(m["created_at"])).astimezone(timezone.utc).time() <= heure_actuelle:
            actifs_hier_meme_heure.add(m["phone"])
            messages_hier_meme_heure += 1
        if j == aujourd_hui and m.get("matiere"):
            derniere_matiere[m["phone"]] = m["matiere"]

    serie = []
    for i, j in enumerate(jours):
        veille = actifs.get(jours[i - 1], set()) if i else None
        retour = None
        if veille:
            retour = round(100 * len(veille & actifs.get(j, set())) / len(veille), 1)
        serie.append({"jour": j, "actifs": len(actifs.get(j, set())), "messages": nb_messages[j], "retour": retour})

    notes = Counter()
    commentaires = []
    debut = jours[0]
    for a in sorted(avis, key=lambda a: str(a.get("created_at", "")), reverse=True):
        j = jour_de(a.get("created_at"))
        if not j or j < debut:
            continue
        if a.get("type") == "avis_seance" and a.get("note"):
            notes[a["note"]] += 1
        elif a.get("feedback") and a.get("statut") != "a_verifier" and len(commentaires) < 5:
            commentaires.append({"jour": j, "matiere": a.get("matiere_detectee", ""), "texte": str(a["feedback"])[:300],
                                 "note": a.get("note", "")})
    return {
        "aujourd_hui": serie[-1],
        "hier": serie[-2] if len(serie) > 1 else None,
        "serie": serie,
        "matieres": Counter(derniere_matiere.values()).most_common(6),
        # Comparaison juste en cours de journee : hier a la meme heure, pas hier en entier.
        "hier_meme_heure": {"actifs": len(actifs_hier_meme_heure), "messages": messages_hier_meme_heure},
        "notes": notes,
        "commentaires": commentaires,
    }


def _e(x):
    return html.escape(str(x if x is not None else "—"))


def _evolution(aujourd_hui, hier):
    if hier in (None, 0) or aujourd_hui is None:
        return ""
    diff = aujourd_hui - hier
    signe = "+" if diff > 0 else ""
    classe = "hausse" if diff > 0 else ("baisse" if diff < 0 else "")
    return f'<span class="evol {classe}">{signe}{diff:g} vs hier à la même heure</span>'


def _barres(serie, cle, suffixe=""):
    valeurs = [s[cle] or 0 for s in serie]
    plus_haut = max(valeurs) or 1
    barres = []
    for s, v in zip(serie, valeurs):
        hauteur = max(2, round(56 * v / plus_haut))
        etiquette = f"{JOURS_FR[s['jour'].weekday()]} {s['jour'].day}"
        texte = "—" if s[cle] is None else f"{round(v):d}{suffixe}"
        barres.append(
            f'<div class="barre"><span class="val">{_e(texte)}</span>'
            f'<div class="b" style="height:{hauteur}px"></div><span class="j">{_e(etiquette)}</span></div>'
        )
    return '<div class="barres">' + "".join(barres) + "</div>"


def rendre_html(stats, sante=None, echecs_jour=0, qualite=None, revisions_jour=0, genere_le=None, libelle=None):
    libelle = libelle or (lambda code: code)
    a = stats["aujourd_hui"]
    hm = stats.get("hier_meme_heure") or {}
    notes = stats["notes"]
    total_notes = sum(notes.values())
    satisfaits = round(100 * notes.get("oui", 0) / total_notes) if total_notes else None

    tuiles = [
        ("Élèves actifs aujourd'hui", a["actifs"], _evolution(a["actifs"], hm.get("actifs"))),
        ("Messages d'élèves", a["messages"], _evolution(a["messages"], hm.get("messages"))),
        ("Revenus depuis hier", "—" if a["retour"] is None else f"{a['retour']:g} %", ""),
        ("Révisions envoyées", revisions_jour, ""),
        ("Avis « Oui » (7 j)", "—" if satisfaits is None else f"{satisfaits} %", f'<span class="evol">{total_notes} avis</span>'),
        ("Messages non livrés", echecs_jour, ""),
    ]
    html_tuiles = "".join(
        f'<div class="tuile{" alerte" if titre == "Messages non livrés" and echecs_jour else ""}">'
        f'<div class="t">{_e(titre)}</div><div class="v">{_e(valeur)}</div>{extra}</div>'
        for titre, valeur, extra in tuiles
    )

    if sante:
        ok = sante.get("ok")
        lignes = "".join(
            f'<li class="{"ok" if c.get("ok") else "ko"}">{"✓" if c.get("ok") else "✗"} {_e(c.get("nom"))} '
            f'<span class="d">{_e(c.get("detail", ""))}</span></li>'
            for c in sante.get("verifications", [])
        )
        bloc_sante = (f'<section><h2>Santé du service <span class="pastille {"ok" if ok else "ko"}">'
                      f'{"tout fonctionne" if ok else "problème détecté"}</span></h2>'
                      f'<p class="petit">Dernière vérification : {_e(str(sante.get("at", ""))[:16].replace("T", " "))} UTC</p>'
                      f'<ul class="sante">{lignes}</ul></section>')
    else:
        bloc_sante = '<section><h2>Santé du service</h2><p class="petit">Pas encore de vérification.</p></section>'

    if qualite:
        bloc_qualite = (f'<section><h2>Contrôle qualité du {_e(qualite.get("jour"))}</h2>'
                        f'<p><b>{_e(qualite.get("moyenne"))} / 5</b> sur {_e(qualite.get("nb"))} conversations relues · '
                        f'{_e(qualite.get("graves"))} problème(s) grave(s)</p></section>')
    else:
        bloc_qualite = ('<section><h2>Contrôle qualité</h2><p class="petit">Lance <code>python3 controle_qualite.py</code> '
                        'dans Cloud Shell pour le voir ici.</p></section>')

    matieres = "".join(f"<li>{_e(libelle(m))} <b>{n}</b></li>" for m, n in stats["matieres"]) or "<li>—</li>"
    repartition = " · ".join(f"{_e(LIBELLES_NOTES.get(k, k))} : {v}" for k, v in notes.most_common()) or "aucun avis"
    commentaires = "".join(
        f'<li><span class="petit">{_e(c["jour"])} · {_e(c["matiere"])}</span><br>« {_e(c["texte"])} »</li>'
        for c in stats["commentaires"]
    ) or '<li class="petit">Aucun commentaire cette semaine.</li>'

    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="600"><title>Akili · Tableau de bord</title>
<style>
:root {{ --fond:#f6f7f9; --carte:#fff; --texte:#1c2430; --doux:#5b6675; --accent:#1f7a5a; --ko:#c0392b; --bord:#e3e6ea; }}
@media (prefers-color-scheme: dark) {{ :root {{ --fond:#12161c; --carte:#1b2129; --texte:#e8ecf1; --doux:#9aa5b4; --accent:#3fb98b; --ko:#ff6b5b; --bord:#2a323d; }} }}
* {{ box-sizing:border-box }} body {{ margin:0; background:var(--fond); color:var(--texte); font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif }}
main {{ max-width:880px; margin:0 auto; padding:16px }} h1 {{ font-size:20px; margin:4px 0 2px }} h2 {{ font-size:16px; margin:0 0 10px }}
.petit {{ color:var(--doux); font-size:13px }} section {{ background:var(--carte); border:1px solid var(--bord); border-radius:12px; padding:14px; margin-top:12px }}
.tuiles {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; margin-top:12px }}
.tuile {{ background:var(--carte); border:1px solid var(--bord); border-radius:12px; padding:12px }} .tuile.alerte {{ border-color:var(--ko) }}
.t {{ color:var(--doux); font-size:13px }} .v {{ font-size:26px; font-weight:650; margin-top:2px }}
.evol {{ font-size:12px; color:var(--doux) }} .hausse {{ color:var(--accent) }} .baisse {{ color:var(--ko) }}
.barres {{ display:flex; gap:6px; align-items:flex-end; height:100px }} .barre {{ flex:1; display:flex; flex-direction:column; align-items:center; justify-content:flex-end; gap:3px }}
.b {{ width:100%; max-width:42px; background:var(--accent); border-radius:4px 4px 0 0 }} .val, .j {{ white-space:nowrap }} .val {{ font-size:12px }} .j {{ font-size:11px; color:var(--doux) }}
ul {{ margin:0; padding-left:18px }} li {{ margin:4px 0 }} .sante {{ list-style:none; padding:0 }} .ok {{ color:var(--accent) }} .ko {{ color:var(--ko) }}
.sante .d {{ color:var(--doux); font-size:13px }} .pastille {{ font-size:12px; padding:2px 8px; border-radius:99px; border:1px solid currentColor; margin-left:6px }}
.deux {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:12px }} .deux section {{ margin-top:0 }}
</style></head><body><main>
<h1>Akili · Tableau de bord</h1><p class="petit">Mis à jour le {_e(genere_le or "")} UTC (heure d'Abidjan) · se rafraîchit toutes les 10 minutes</p>
<div class="tuiles">{html_tuiles}</div>
{bloc_sante}
<section><h2>Élèves actifs, 7 derniers jours</h2>{_barres(stats["serie"], "actifs")}</section>
<section><h2>Élèves revenus le lendemain</h2>{_barres(stats["serie"], "retour", "%")}</section>
<div class="deux" style="margin-top:12px">
<section><h2>Matières travaillées aujourd'hui</h2><ul>{matieres}</ul></section>
<section><h2>Avis des 7 derniers jours</h2><p>{repartition}</p><ul>{commentaires}</ul></section>
</div>
{bloc_qualite}
</main></body></html>"""
