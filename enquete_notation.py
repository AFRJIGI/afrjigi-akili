"""Enquete sur la notation mathematique dans les messages envoyes aux eleves (WhatsApp).

Compte, par matiere, les messages d'Akili ou il reste du LaTeX ou une notation cassee
(\\frac, $, ^{...}, x_1, accolades, "√(3)2", "danst"...), et les messages d'eleves qui
signalent ne pas comprendre une ecriture. Lecture seule. Les numeros sont masques.

  python3 enquete_notation.py               # 7 derniers jours
  python3 enquete_notation.py --jours 14 --matieres MATHS,PC

Le rapport complet (exemples) est ecrit dans ~/controle_qualite/, hors du depot.
"""
import argparse
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAUTS = {
    "commande LaTeX (\\frac, \\sqrt, \\leq...)": r"\\[A-Za-z]+",
    "signe $": r"\$",
    "exposant ^ non converti": r"\^",
    "indice avec _ (x_1, u_n)": r"[A-Za-z0-9)]_[A-Za-z0-9{(]",
    "accolades { }": r"[{}]",
    "racine collee (√(3)2)": r"√\([^)]*\)[\w(]",
    "fraction a parentheses vides ou doubles": r"\(\(\s*\d+\s*\)\)|\(\s*\)/|/\(\s*\)",
    "mot casse par l'ancien nettoyage (danst, mvecteur)": r"dans[a-z]|\wvecteur",
    "titre Markdown (###) ou **": r"(?m)^\s*#{1,6}\s|\*\*",
    "commande LaTeX restee en mot (setminus, mathbb...)":
        r"\b(setminus|mathbb|mathrm|frac|dfrac|sqrt|infty|leq|geq|neq|cdot|overrightarrow|text)\b",
}
# Traces du bot enregistrees comme messages (« [vector_formula_image] », « [audio_reply] ») : ce ne sont pas
# des textes recus par l'eleve. Le 7 oct., elles faisaient les 159 « indices avec _ » de l'enquete.
TRACE_DU_BOT = re.compile(r"^\[[a-z_]+\]$")
# Ensemble ecrit avec ses accolades (ℝ privé de {3}, {-1 ; 1}) : notation correcte, pas un reste de LaTeX.
ENSEMBLE = re.compile(r"(?<![\^_A-Za-z])\{[^{}^_\\]{1,40}\}")
PLAINTES = r"comprend(s|re)? (pas|rien)|c.est quoi (ce|cette|ça)|symbole|bizarre|illisible|je vois (des|un) |" \
           r"carr[ée]s? |racine|fraction|exposant|notation|écriture|ecriture|\\\\|\$"


def masque(phone):
    return "…" + str(phone)[-4:]


def analyser(messages, matieres):
    """messages : dicts de whatsapp_messages. Renvoie (par_matiere, exemples, plaintes)."""
    motifs = {nom: re.compile(m) for nom, m in DEFAUTS.items()}
    par_matiere = defaultdict(lambda: {"messages": 0, "avec_defaut": 0, "defauts": Counter()})
    exemples = defaultdict(list)
    plaintes = []
    regex_plainte = re.compile(PLAINTES, re.I)
    for m in messages:
        matiere = str(m.get("matiere") or "?").upper()
        texte = str(m.get("text") or "")
        if matieres and matiere not in matieres:
            continue
        if m.get("direction") == "outbound":
            if TRACE_DU_BOT.match(texte.strip()):
                continue
            stats = par_matiere[matiere]
            stats["messages"] += 1
            sans_ensembles = ENSEMBLE.sub("", texte)
            trouves = [nom for nom, motif in motifs.items()
                       if motif.search(sans_ensembles if nom.startswith("accolades") else texte)]
            if trouves:
                stats["avec_defaut"] += 1
                stats["defauts"].update(trouves)
                for nom in trouves:
                    if len(exemples[nom]) < 8:
                        debut = max(0, motifs[nom].search(texte).start() - 70)
                        exemples[nom].append((matiere, texte[debut:debut + 160].replace("\n", " ")))
        elif m.get("direction") == "inbound" and regex_plainte.search(texte) and len(texte) < 400:
            plaintes.append((m.get("created_at", "")[:16], masque(m.get("phone")), matiere, texte[:200].replace("\n", " ")))
    return par_matiere, exemples, plaintes


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jours", type=int, default=7)
    parser.add_argument("--matieres", default="MATHS,PC,PHYSIQUE_APPLIQUEE,MATHS_GENERAL,MATHS_FIN,SVT")
    args = parser.parse_args()
    from google.cloud import firestore
    db = firestore.Client(project="astute-curve-307922")
    depuis = (datetime.now(timezone.utc) - timedelta(days=args.jours)).isoformat()
    matieres = {m.strip().upper() for m in args.matieres.split(",") if m.strip()}
    messages = [d.to_dict() or {} for d in db.collection("whatsapp_messages").where("created_at", ">=", depuis)
                .select(["phone", "direction", "text", "matiere", "created_at"]).stream()]
    par_matiere, exemples, plaintes = analyser(messages, matieres)

    lignes = [f"Enquête notation — {args.jours} derniers jours (depuis {depuis[:16]} UTC)", ""]
    for matiere, s in sorted(par_matiere.items(), key=lambda x: -x[1]["messages"]):
        part = 100 * s["avec_defaut"] / s["messages"] if s["messages"] else 0
        lignes.append(f"{matiere:<20} {s['messages']:>6} messages d'Akili, {s['avec_defaut']:>5} avec défaut ({part:.0f} %)")
        for nom, n in s["defauts"].most_common():
            lignes.append(f"    {n:>5}  {nom}")
    lignes += ["", f"Messages d'élèves qui semblent signaler une écriture incomprise : {len(plaintes)}"]
    resume = "\n".join(lignes)
    print(resume)

    details = [resume, "", "=== Exemples de défauts ==="]
    for nom, liste in exemples.items():
        details.append(f"\n--- {nom} ---")
        details += [f"[{m}] …{t}…" for m, t in liste]
    details.append("\n=== Messages d'élèves ===")
    details += [f"{q} {p} [{m}] {t}" for q, p, m, t in plaintes[:80]]
    dossier = Path.home() / "controle_qualite"
    dossier.mkdir(exist_ok=True)
    chemin = dossier / f"enquete_notation_{datetime.now(timezone.utc):%Y%m%d_%H%M}.txt"
    chemin.write_text("\n".join(details), encoding="utf-8")
    print(f"\nRapport complet avec exemples : {chemin}")


if __name__ == "__main__":
    main()
