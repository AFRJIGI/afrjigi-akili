"""Progressions officielles METFPA des matieres techniques des series E et F.

Les progressions viennent de l'inventaire reports/bac_technique_progressions_inventory.json
(miroir Fomesoutra). Chaque titre est classe dans une matiere du menu WhatsApp
(memes codes que le bot : CMI, AUTOMATISME, RDM...), avec sa serie et sa classe.

Par defaut : audit sans ecriture (affiche ce qui serait ajoute).
  python3 injecter_progressions_techniques_e_f.py
  python3 injecter_progressions_techniques_e_f.py --serie F1 --limite 2 --apply   (essai)
  python3 injecter_progressions_techniques_e_f.py --apply                        (tout)

--apply sauvegarde d'abord la base dans GCS, puis telecharge chaque PDF, extrait son
texte (pypdf, ou Gemini si le PDF est scanne) et ajoute les documents absents.
Aucun document existant n'est modifie ni supprime. Redeployer akili-api ensuite :
l'API charge la base au demarrage.
"""

import argparse
import hashlib
import html
import io
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ID = "astute-curve-307922"
LOCATION = "us-central1"
BUCKET_NAME = "akili-database-storage-astute-curve-307922"
DB_BLOB = "data/jigi_global_database.json"
INVENTAIRE = Path(__file__).with_name("reports") / "bac_technique_progressions_inventory.json"
TYPES_MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "doc": "application/msword",
}
TEXTE_MINIMUM = 400  # en dessous, le PDF est sans doute scanne : extraction par Gemini

SERIE_PAR_CATEGORIE = {
    "BAC_E": "E", "BAC_F1": "F1", "BAC_F2": "F2", "BAC_F3": "F3", "BAC_F4": "F4", "BAC_F7": "F7",
}

# (motif sur le titre normalise, code matiere du bot). Le premier motif qui correspond gagne.
# Un titre sans motif (progression generale, autre matiere, classe de seconde commune) est ignore.
REGLES = {
    "BAC_E": [
        (r"\bCMI\b", "CMI"),
        (r"ETUDE\s+(DE\s+)?FABRICATION", "ETUDE_FABRICATION"),
        (r"TOURNAGE|FRAISAGE", "FABRICATION"),
        (r"AUTOMATISME", "AUTOMATISME"),
        (r"\bTG\b|TECHNOLOGIE GLE", "TECHNO_GENERALE"),
    ],
    "BAC_F1": [
        (r"\bCMI\b", "CMI"),
        (r"OUTILLAGE", "ETUDE_OUTILLAGE"),
        (r"BUREAU DES METHODES", "BUREAU_METHODES"),
        (r"TOURNAGE|FRAISAGE|AFFUTAGE|MACHINES SPECIALES", "FABRICATION"),
        (r"AUTOMATISME", "AUTOMATISME"),
        (r"TECHNOLOGIE GLE", "TECHNO_GENERALE"),
        (r"\bMECA(NIQUE)?\b", "MECANIQUE"),
    ],
    "BAC_F2": [
        (r"\bCMI\b", "CMI"),
        (r"INFORMATIQUE", "INFORMATIQUE_INDUSTRIELLE"),
        (r"TECHNOLOGIE SCHEMAS", "TECHNO_SCHEMAS"),
        (r"\bMESURES\b", "ELECTRONIQUE"),
    ],
    "BAC_F3": [
        (r"\bCMI\b", "CMI"),
        (r"ESSAI|MESURES", "MESURES_ESSAIS"),
        (r"SCHEMA|TF3 TECHNOLOGIE|PROGRESSION TECHNOLOGIE 1ERE", "TECHNO_SCHEMAS"),
        (r"CABLAGE", "CABLAGE"),
    ],
    "BAC_F4": [
        (r"\bTOPO\b", "TOPOGRAPHIE"),
        (r"\bRDM\b", "RDM"),
        (r"LEGISLATION", "LEGISLATION"),
        (r"DESSIN", "DESSIN_GENIE_CIVIL"),
        (r"\bLABO\b", "LABO_MATERIAUX"),
        (r"METHODES", "METHODES"),
        (r"\bTECHNO\b", "TECHNO_GENIE_CIVIL"),
    ],
    "BAC_F7": [
        (r"BIOCHIMIE", "BIOCHIMIE"),
        (r"MICROBIO", "MICROBIOLOGIE"),
        (r"BIOLOGIE", "BIOLOGIE"),
        (r"CHIMIE", "CHIMIE"),
    ],
    # Physique appliquee F1 (rangee dans le dossier Physique-Chimie de l'inventaire).
    "PHYSIQUE_CHIMIE": [
        (r"PHYSIQUE APPLIQUEE.*\bF1\b", "PHYSIQUE_APPLIQUEE"),
    ],
}

NIVEAUX = [
    ("SECONDE", r"\b2\s*T\d\b|\b2ND\b|\b2NDE\b|\b2E\b|\b2F\d\b|\bSECONDE\b"),
    ("PREMIERE", r"\b1ERE\b|\b1IERE\b|\b1E\b|\b1F\d|\bPREMIERE\b"),
    ("TERMINALE", r"\bTLE\b|\bTE\b|\bTF\d|\bTERMINALE\b"),
]


def normaliser(texte):
    texte = unicodedata.normalize("NFKD", texte or "")
    texte = "".join(c for c in texte if not unicodedata.combining(c)).upper()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", texte)).strip()


def niveau_du_titre(titre):
    """SECONDE, PREMIERE, TERMINALE, PREMIERE_TERMINALE ou TOUS (2e, 1e, Tle)."""
    t = normaliser(titre)
    trouves = [nom for nom, motif in NIVEAUX if re.search(motif, t)]
    if not trouves:
        return None
    if len(trouves) == 3:
        return "TOUS"
    return "_".join(trouves)


def classer(categorie, titre):
    """(matiere, serie, niveau) d'un titre de l'inventaire, ou None s'il est hors champ."""
    t = normaliser(titre)
    for motif, matiere in REGLES.get(categorie, []):
        if re.search(motif, t):
            serie = SERIE_PAR_CATEGORIE.get(categorie) or ("F1" if categorie == "PHYSIQUE_CHIMIE" else None)
            # Sans classe dans le titre ("9 2 Mesures"), la progression vaut pour toutes les classes.
            niveau = niveau_du_titre(titre) or "TOUS"
            if not serie:
                return None
            return matiere, serie, niveau
    return None


def identifiant_source(url):
    m = re.search(r"/(\d+)-[^/]+/file$", url or "")
    return m.group(1) if m else hashlib.sha1((url or "").encode()).hexdigest()[:10]


def plan_documents(inventaire):
    """Liste des progressions a ajouter, sans doublon d'URL."""
    vus = set()
    plan = []
    for item in inventaire:
        url = item.get("url")
        classe = classer(item.get("categorie"), item.get("titre"))
        if not classe or url in vus:
            continue
        vus.add(url)
        matiere, serie, niveau = classe
        plan.append({
            "id": f"metfpa_progression_tech_{identifiant_source(url)}_{matiere.lower()}_{serie.lower()}",
            "titre": item["titre"],
            "url": url,
            "matiere": matiere,
            "serie": serie,
            "niveau": niveau,
        })
    return plan


def _telecharger_brut(url, essais=6):
    """(contenu, adresse finale apres redirections)."""
    requete = urllib.request.Request(url, headers={
        "User-Agent": "AfrJigi-Akili/1.0", "Accept-Encoding": "identity", "Connection": "close",
    })
    derniere = None
    for essai in range(1, essais + 1):
        try:
            with urllib.request.urlopen(requete, timeout=120) as reponse:
                return reponse.read(), reponse.geturl()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            derniere = exc
            if essai == essais:
                break
            time.sleep(min(5 * essai, 30))
    raise RuntimeError(f"Echec du telechargement : {url}") from derniere


def adresses_google(adresse, contenu=b""):
    """Le miroir renvoie parfois vers Google Drive ou Google Docs, qui affichent une page
    web au lieu du fichier. On en deduit les adresses de telechargement direct."""
    texte = adresse + " " + contenu[:200000].decode("utf-8", "ignore")
    adresses = []
    # Visionneuse Google (docs.google.com/viewer?url=...) : le vrai fichier est dans "url".
    if "docs.google.com/viewer" in adresse:
        interne = urllib.parse.parse_qs(urllib.parse.urlparse(adresse).query).get("url", [""])[0]
        if interne:
            adresses.append(interne)
    for genre, ident in re.findall(r"docs\.google\.com/(document|spreadsheets|presentation)/d/([\w-]{20,})", texte):
        format_export = {"document": "docx", "spreadsheets": "xlsx", "presentation": "pdf"}[genre]
        adresses.append(f"https://docs.google.com/{genre}/d/{ident}/export?format={format_export}")
    for ident in re.findall(r"drive\.google\.com/(?:file/d/|open\?id=|uc\?(?:[^\"' ]*?&)?id=)([\w-]{20,})", texte):
        adresses.append(f"https://drive.usercontent.google.com/download?id={ident}&export=download&confirm=t")
    vus = []
    for a in adresses:
        if a not in vus:
            vus.append(a)
    return vus[:4]


def telecharger(url, essais=6):
    """Contenu du fichier. Suit les renvois vers Google Drive / Google Docs."""
    contenu, adresse = _telecharger_brut(url, essais)
    if type_fichier(contenu) != "html":
        return contenu
    alternatives = adresses_google(adresse, contenu)
    if "force_download" not in url:
        alternatives.append(url + ("&" if "?" in url else "?") + "force_download=1")
    for alternative in alternatives:
        try:
            fichier, _ = _telecharger_brut(alternative, 3)
        except Exception as exc:
            print(f"  Google : echec {alternative} ({exc})")
            continue
        if type_fichier(fichier) != "html":
            print(f"  fichier recupere via Google ({type_fichier(fichier)})")
            return fichier
    print(f"  adresse finale : {adresse}")
    return contenu


def type_fichier(contenu):
    """pdf, docx, xlsx, pptx, doc (Word 97-2003), html ou inconnu, d'apres les premiers octets."""
    if contenu.startswith(b"%PDF-"):
        return "pdf"
    if contenu.startswith(b"PK"):
        try:
            noms = zipfile.ZipFile(io.BytesIO(contenu)).namelist()
        except zipfile.BadZipFile:
            return "inconnu"
        if "word/document.xml" in noms:
            return "docx"
        if any(n.startswith("xl/") for n in noms):
            return "xlsx"
        if any(n.startswith("ppt/") for n in noms):
            return "pptx"
        return "zip"
    if contenu.startswith(b"\xd0\xcf\x11\xe0"):
        return "doc"
    debut = contenu[:500].lstrip().lower()
    if debut.startswith(b"<!doctype html") or debut.startswith(b"<html") or b"<html" in debut:
        return "html"
    return "inconnu"


def _texte_xml(xml, balise_texte, balise_ligne):
    """Texte d'un XML Office : une ligne par paragraphe (Word) ou par ligne de tableau (Excel)."""
    lignes = []
    for bloc in re.findall(rf"<{balise_ligne}[ >].*?</{balise_ligne}>", xml, flags=re.S):
        morceaux = re.findall(rf"<{balise_texte}(?: [^>]*)?>([^<]*)</{balise_texte}>", bloc)
        ligne = html.unescape("".join(morceaux)).strip()
        if ligne:
            lignes.append(ligne)
    return lignes


def texte_docx(contenu):
    archive = zipfile.ZipFile(io.BytesIO(contenu))
    xml = archive.read("word/document.xml").decode("utf-8", "ignore")
    # Une ligne de tableau Word = une ligne de texte, cellules separees par " | ".
    def ligne_tableau(m):
        cellules = []
        for cellule in re.findall(r"<w:tc[ >].*?</w:tc>", m.group(0), flags=re.S):
            texte = " ".join(_texte_xml(cellule, "w:t", "w:p"))
            if texte:
                cellules.append(texte)
        return "<w:p><w:t>" + html.escape(" | ".join(cellules)) + "</w:t></w:p>"
    xml = re.sub(r"<w:tr[ >].*?</w:tr>", ligne_tableau, xml, flags=re.S)
    return "\n".join(_texte_xml(xml, "w:t", "w:p"))


def texte_xlsx(contenu):
    archive = zipfile.ZipFile(io.BytesIO(contenu))
    partages = []
    if "xl/sharedStrings.xml" in archive.namelist():
        xml = archive.read("xl/sharedStrings.xml").decode("utf-8", "ignore")
        for si in re.findall(r"<si>.*?</si>", xml, flags=re.S):
            partages.append(html.unescape("".join(re.findall(r"<t(?: [^>]*)?>([^<]*)</t>", si))))
    lignes = []
    for nom in sorted(n for n in archive.namelist() if n.startswith("xl/worksheets/sheet")):
        xml = archive.read(nom).decode("utf-8", "ignore")
        for ligne in re.findall(r"<row[ >].*?</row>", xml, flags=re.S):
            cellules = []
            for attributs, corps in re.findall(r"<c([^>]*)>(.*?)</c>", ligne, flags=re.S):
                valeur = re.search(r"<v>([^<]*)</v>", corps)
                inline = re.findall(r"<t(?: [^>]*)?>([^<]*)</t>", corps)
                if 't="s"' in attributs and valeur:
                    index = int(valeur.group(1))
                    cellules.append(partages[index] if index < len(partages) else "")
                elif inline:
                    cellules.append(html.unescape("".join(inline)))
                elif valeur:
                    cellules.append(valeur.group(1))
            texte = " | ".join(c.strip() for c in cellules if c and c.strip())
            if texte:
                lignes.append(texte)
    return "\n".join(lignes)


def texte_doc(contenu):
    """Word 97-2003 : on recupere les suites de texte lisibles (UTF-16 puis cp1252)."""
    utf16 = "\n".join(m.decode("utf-16-le", "ignore")
                       for m in re.findall(rb"(?:[\x20-\x7e\xa0-\xff]\x00){4,}", contenu))
    cp1252 = "\n".join(m.decode("cp1252", "ignore")
                        for m in re.findall(rb"[\x20-\x7e\xc0-\xff]{6,}", contenu))

    def propre(texte):
        return "\n".join(l.strip() for l in texte.splitlines() if sum(c.isalpha() for c in l) >= 3)

    return max(propre(utf16), propre(cp1252), key=len)


def texte_pypdf(contenu):
    try:
        from pypdf import PdfReader
        lecteur = PdfReader(io.BytesIO(contenu))
        return "\n".join((page.extract_text() or "") for page in lecteur.pages).strip()
    except Exception as exc:
        print(f"  pypdf indisponible ou en echec : {exc!r}")
        return ""


def texte_gemini(modele, contenu, doc, essais=4):
    from vertexai.generative_models import Part
    consigne = (
        f"Extrais fidelement le texte utile de cette progression METFPA ({doc['titre']}). "
        "Conserve les mois, semaines, themes, lecons, competences et volumes horaires, "
        "dans l'ordre. Ne produis aucun commentaire en dehors du texte extrait."
    )
    for essai in range(1, essais + 1):
        try:
            reponse = modele.generate_content([Part.from_data(data=contenu, mime_type="application/pdf"), consigne])
            texte = (reponse.text or "").strip()
            if texte:
                return texte
        except Exception as exc:
            print(f"  Gemini ({essai}/{essais}) : {exc!r}")
        time.sleep(min(10 * essai, 30))
    return ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="ecrire dans la base (sinon audit)")
    parser.add_argument("--serie", help="limiter a une serie (E, F1, F2, F3, F4, F7)")
    parser.add_argument("--limite", type=int, default=0, help="nombre maximum d'ajouts (essai)")
    args = parser.parse_args()

    inventaire = json.loads(INVENTAIRE.read_text(encoding="utf-8"))["inventaire"]
    plan = plan_documents(inventaire)
    if args.serie:
        plan = [d for d in plan if d["serie"] == args.serie.upper()]

    from google.cloud import storage
    bucket = storage.Client(project=PROJECT_ID).bucket(BUCKET_NAME)
    data = json.loads(bucket.blob(DB_BLOB).download_as_text(timeout=600))
    docs = data.get("documents", [])
    ids = {d.get("id") for d in docs}
    urls = {d.get("source_url") for d in docs}
    a_ajouter = [d for d in plan if d["id"] not in ids and d["url"] not in urls]

    print(f"Base actuelle : {len(docs)} documents")
    print(f"Progressions techniques prevues : {len(plan)} ; deja presentes : {len(plan) - len(a_ajouter)} ; a ajouter : {len(a_ajouter)}")
    for d in plan:
        etat = "CREATE" if d in a_ajouter else "SKIP  "
        print(f"{etat} | {d['serie']:<3} | {d['matiere']:<26} | {d['niveau']:<18} | {d['titre']}")
    if not args.apply:
        print("Audit termine. Relancer avec --apply pour ecrire.")
        return
    if args.limite:
        a_ajouter = a_ajouter[:args.limite]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sauvegarde = f"data/backups/jigi_global_database_before_progressions_tech_ef_{stamp}.json"
    bucket.copy_blob(bucket.blob(DB_BLOB), bucket, sauvegarde)
    print(f"Sauvegarde : gs://{BUCKET_NAME}/{sauvegarde}")

    modele = None
    empreintes = {d.get("sha256") for d in docs if d.get("sha256")}
    ajoutes_par_empreinte = {}  # meme PDF pour plusieurs series (ex : CMI 2T1 en E, F1 et F3)
    ajouts = echecs = 0
    for doc in a_ajouter:
        print(f"→ {doc['serie']} {doc['matiere']} {doc['niveau']} : {doc['titre']}")
        try:
            contenu = telecharger(doc["url"])
        except Exception as exc:
            print(f"  ECHEC telechargement : {exc}")
            echecs += 1
            continue
        empreinte = hashlib.sha256(contenu).hexdigest()
        deja = ajoutes_par_empreinte.get(empreinte)
        if deja is not None:
            if doc["serie"] not in deja["serie"]:
                deja["serie"] += doc["serie"]
            print(f"  meme PDF que {deja['id']} : series {deja['serie']}")
            continue
        if empreinte in empreintes:
            print("  doublon (meme PDF deja dans la base)")
            continue
        sorte = type_fichier(contenu)
        if sorte in {"html", "inconnu", "zip", "pptx"}:
            apercu = re.sub(r"\s+", " ", contenu[:300].decode("utf-8", "ignore"))
            print(f"  ECHEC : fichier recu de type {sorte} ({len(contenu)} octets) : {apercu[:200]}")
            echecs += 1
            continue
        if sorte == "docx":
            texte, methode = texte_docx(contenu), "docx"
        elif sorte == "xlsx":
            texte, methode = texte_xlsx(contenu), "xlsx"
        elif sorte == "doc":
            texte, methode = texte_doc(contenu), "doc"
        else:
            texte, methode = texte_pypdf(contenu), "pypdf"
        if sorte == "pdf" and len(texte) < TEXTE_MINIMUM:
            if modele is None:
                import vertexai
                from vertexai.generative_models import GenerativeModel
                vertexai.init(project=PROJECT_ID, location=LOCATION)
                modele = GenerativeModel("gemini-2.5-flash")
            texte = texte_gemini(modele, contenu, doc)
            methode = "gemini"
        if len(texte) < 100:
            print("  ECHEC extraction (texte vide)")
            echecs += 1
            continue

        nom = f"METFPA_PROGRESSION_{doc['matiere']}_{doc['serie']}_{doc['niveau']}_{identifiant_source(doc['url'])}.{sorte}"
        chemin = f"knowledge_base/{doc['matiere']}/{doc['serie']}/{nom}"
        bucket.blob(chemin).upload_from_string(contenu, content_type=TYPES_MIME[sorte])
        docs.append({
            "id": doc["id"],
            "nom_fichier": nom,
            "titre_source": doc["titre"],
            "chemin": chemin,
            "matiere": doc["matiere"],
            "serie": doc["serie"],
            "examen": "BAC_TECHNIQUE",
            "niveau": doc["niveau"],
            "type_doc": "PROGRESSION_ANNUELLE",
            "source": "METFPA_OFFICIEL",
            "institution": "METFPA",
            "portail_source": "FOMESOUTRA",
            "statut_source": "MIROIR_FOMESOUTRA",
            "source_url": doc["url"],
            "sha256": empreinte,
            "score": 5,
            "texte": texte,
            "extraction": methode,
            "resume": f"Progression METFPA {doc['matiere']} {doc['niveau']} serie {doc['serie']}",
            "integre_le": datetime.now(timezone.utc).isoformat(),
        })
        empreintes.add(empreinte)
        ajoutes_par_empreinte[empreinte] = docs[-1]
        ajouts += 1
        print(f"  ajoute ({len(texte)} caracteres, {methode})")
        time.sleep(1)

    if not ajouts:
        print(f"Termine : aucun ajout, {echecs} echecs. Base inchangee.")
        return
    data["documents"] = docs
    data["total"] = len(docs)
    data["generated_at"] = datetime.now(timezone.utc).isoformat()
    bucket.blob(DB_BLOB).upload_from_string(json.dumps(data, ensure_ascii=False, indent=2), content_type="application/json")
    print(f"Termine : {ajouts} ajouts, {echecs} echecs, total {data['total']} documents.")
    print("Redeploie maintenant akili-api pour que l'API charge les nouvelles progressions.")


if __name__ == "__main__":
    main()
