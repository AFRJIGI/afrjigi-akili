"""Decoupe le Support d'Economie (BTS tertiaire 2e annee, version preliminaire septembre 2026,
transmis par M. Diaby) en extraits par chapitre et par section, pour la base d'Akili.

  pdftotext "SUPPORT D'ECONOMIE.pdf" support.txt
  python3 donnees/construire_cours_economie_m_diaby.py support.txt donnees/cours_economie_m_diaby_2026.json <sha256 du PDF>
"""
import hashlib, json, re, sys

TAILLE_CIBLE, TAILLE_MAX = 2400, 3000
PUCES = {"-", "•", "▪", "➢", "*", "✓", "o", ""}
# (code, libelle, series)
PARTIES = [
    ("ECONOMIE GENERALE", "Économie générale", "BG1G2"),
    ("ECONOMIE ET ORGANISATION DES ENTREPRISES", "Économie et organisation des entreprises", "G1G2"),
]


def nettoyer(lignes):
    sortie, attente = [], ""
    for ligne in lignes:
        l = ligne.replace("\f", "").strip()
        if re.fullmatch(r"\d{1,3}", l):
            continue  # numero de page
        if l in PUCES and l:
            attente = "• "
            continue
        if not l:
            if sortie and sortie[-1] != "":
                sortie.append("")
            continue
        if attente:
            l, attente = attente + l, ""
        sortie.append(l)
    # Recolle les lignes coupees au milieu d'une phrase (sans changer les titres ni les puces).
    texte = "\n".join(sortie)
    texte = re.sub(r"(?<=[a-zàâçéèêëîïôûù,’'])\n\n(?=[a-zàâçéèêëîïôûù])", " ", texte)
    return re.sub(r"\n{3,}", "\n\n", texte).strip()


def est_section(ligne):
    return re.match(r"^(\d+)\s*[-.]\s*(?!\d)\S", ligne) is not None


def decouper(texte):
    """Morceaux de ~2400 caracteres, coupes aux sections (1-, 2-...), sinon aux paragraphes."""
    blocs, courant = [], []
    for ligne in texte.split("\n"):
        if est_section(ligne) and courant:
            blocs.append("\n".join(courant).strip())
            courant = []
        courant.append(ligne)
    if courant:
        blocs.append("\n".join(courant).strip())
    morceaux, actuel = [], ""
    for bloc in blocs:
        if len(bloc) > TAILLE_MAX:
            paras = bloc.split("\n\n")
        else:
            paras = [bloc]
        for para in paras:
            if actuel and len(actuel) + len(para) > TAILLE_CIBLE:
                morceaux.append(actuel.strip())
                actuel = ""
            actuel += ("\n\n" if actuel else "") + para
    if actuel.strip():
        morceaux.append(actuel.strip())
    return morceaux


def main(source, sortie):
    lignes = open(source, encoding="utf-8").read().split("\n")
    debuts = [i for i, l in enumerate(lignes)
              if re.match(r"^chapitre\s+\d+\s*:", l.replace("\f", ""), flags=re.I)
              and not any("...." in x for x in lignes[i:i + 7])]  # pas les lignes des sommaires
    # Les sommaires reprennent les titres : on garde les chapitres dont le numero suit l'ordre du corps.
    corps, attendu, partie = [], 1, 0
    for i in debuts:
        num = int(re.search(r"\d+", lignes[i]).group())
        if num == attendu:
            corps.append((i, partie, num))
            attendu += 1
        elif num == 1 and attendu > 1:
            partie, attendu = partie + 1, 2
            corps.append((i, partie, 1))
    fins = {}
    for k, (i, partie, num) in enumerate(corps):
        suivant = corps[k + 1][0] if k + 1 < len(corps) else len(lignes)
        # le chapitre s'arrete avant un sommaire / une table des matieres
        for j in range(i + 1, suivant):
            if re.match(r"^\f?(SOMMAIRE|TABLE DES MATI)", lignes[j]) or "TROISIEME PARTIE" == lignes[j].replace("\f", "").strip() \
                    or "DEUXIEME PARTIE" in lignes[j].replace("\f", "") and j > i + 5:
                suivant = j
                break
        fins[i] = suivant
    docs = []
    for i, partie, num in corps:
        titre = lignes[i].replace("\f", "").strip()
        debut_texte = i + 1
        suite = lignes[i + 1].replace("\f", "").strip()
        if suite and suite.upper() == suite and re.search(r"[A-Z]{3,}", suite) and not est_section(suite):
            titre += " " + suite  # titre sur deux lignes ("... ET AGREGATS" / "ECONOMIQUES")
            debut_texte = i + 2
        titre = re.sub(r"\s+", " ", re.sub(r"(?i)^chapitre", "Chapitre", titre))
        texte = nettoyer(lignes[debut_texte:fins[i]])
        morceaux = decouper(texte)
        code, libelle, series = PARTIES[partie][0], PARTIES[partie][1], PARTIES[partie][2]
        for k, m in enumerate(morceaux, 1):
            entete = f"COURS D'ÉCONOMIE — {libelle} — {titre} (partie {k}/{len(morceaux)})"
            docs.append({"partie": libelle, "chapitre": num, "titre": titre, "morceau": k, "nb_morceaux": len(morceaux),
                         "serie": series, "texte": f"{entete}\n\n{m}"})
    json.dump({"source": "Support d'Économie, BTS tertiaire 2e année, version préliminaire septembre 2026 "
                         "(Inspection de l'Économie, Côte d'Ivoire)",
               "transmis_par": "M. Diaby, enseignant d'économie", "recu_le": "2026-10-04",
               "sha256_pdf": sys.argv[3] if len(sys.argv) > 3 else "",
               "documents": docs}, open(sortie, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for d in docs:
        print(f"{d['partie'][:12]:12} ch{d['chapitre']} {d['morceau']}/{d['nb_morceaux']} {len(d['texte']):5}  {d['titre'][:60]}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
