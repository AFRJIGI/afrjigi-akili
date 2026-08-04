from pathlib import Path

p = Path("akili_api/main.py")
s = p.read_text(encoding="utf-8")

old = '''def load_db_from_gcs():
    """Charge la base de données depuis Google Cloud Storage."""
    try:
        print(f"⏳ Chargement de la base depuis gs://{BUCKET_NAME}/{BLOB_NAME}...")
        client = storage.Client()
        bucket = client.bucket(BUCKET_NAME)
        blob = bucket.blob(BLOB_NAME)
        
        content = blob.download_as_text()
        data = json.loads(content)
        
        # Filtrage des documents ayant du texte
        docs = [d for d in data.get("documents", []) if d.get("texte")]
        print(f"✅ {len(docs)} documents chargés avec succès.")
        return docs
    except Exception as e:
        print(f"❌ Erreur lors du chargement GCS : {e}")
        return []
'''

new = '''def load_db_from_gcs():
    """Charge la base de données depuis Google Cloud Storage."""
    try:
        print(f"⏳ Chargement de la base depuis gs://{BUCKET_NAME}/{BLOB_NAME}...")
        client = storage.Client()
        bucket = client.bucket(BUCKET_NAME)
        blob = bucket.blob(BLOB_NAME)

        content = blob.download_as_text()
        data = json.loads(content)

        docs = []
        for d in data.get("documents", []):
            texte = d.get("texte") or d.get("texte_extrait") or d.get("resume") or ""
            if isinstance(texte, list):
                texte = " ".join(str(x) for x in texte)
            texte = str(texte).strip()
            if texte:
                d["texte"] = texte
                docs.append(d)

        print(f"✅ {len(docs)} documents chargés avec succès.")
        return docs
    except Exception as e:
        print(f"❌ Erreur lors du chargement GCS : {e}")
        return []
'''

if old not in s:
    raise SystemExit("Bloc load_db_from_gcs introuvable")
s = s.replace(old, new)

old = '''def chercher_contexte(question, matiere=None, serie=None, max_docs=5):
    """Filtre les documents par matière/série et recherche par mots-clés."""
    if not documents or not question:
        return []

    filtered_docs = documents
    if matiere:
        filtered_docs = [d for d in filtered_docs if d.get("matiere") == matiere]
    if serie:
        filtered_docs = [d for d in filtered_docs if serie_match(d.get("serie"), serie)]

    mots_cles = [m.lower() for m in question.split() if len(m) > 3]
    
    results = []
    for doc in filtered_docs:
        texte_brut = doc.get("texte", "")
        if isinstance(texte_brut, list):
            texte_brut = " ".join(str(x) for x in texte_brut)
        texte = str(texte_brut).lower()
        score = sum(1 for mot in mots_cles if mot in texte)
        if score > 0:
            results.append((score, doc))

    results.sort(key=lambda x: x[0], reverse=True)
    return [doc for score, doc in results[:max_docs]]
'''

new = '''ETUDE_TYPES = {
    "PROGRAMME": 40,
    "PROGRESSION_2NDE": 38,
    "PROGRESSION_1ERE": 38,
    "PROGRESSION_TLE": 38,
    "GUIDE": 35,
    "DOCUMENT": 25,
    "TP": 25,
    "ANNALE": 10,
    "SUJET": 8,
    "CORRIGE": 6,
    "CORRIGÉ": 6,
    "BAC_BLANC": 6,
    "PREPA": 6,
    "TERMINALE": 5,
}

EXAMEN_TYPES = {
    "SUJET": 40,
    "ANNALE": 38,
    "BAC_BLANC": 36,
    "PREPA": 34,
    "TERMINALE": 32,
    "DOCUMENT": 28,
    "CORRIGE": 24,
    "CORRIGÉ": 24,
    "BARÈME": 22,
    "BAREME": 22,
    "SUJET CORRIGÉ": 22,
    "PROGRAMME": 5,
    "PROGRESSION_2NDE": 5,
    "PROGRESSION_1ERE": 5,
    "PROGRESSION_TLE": 5,
    "GUIDE": 4,
}

def normaliser_mode(mode, question=""):
    txt = f"{mode or ''} {question or ''}".lower()
    if any(x in txt for x in ["mode examen", "examen", "sujet type", "sujet d'examen", "entraîne", "entrainer", "corrige-moi", "note-moi", "barème", "bareme"]):
        return "examen"
    return "etude"

def normaliser_examen_requete(type_examen=None, serie=None):
    raw = f"{type_examen or ''} {serie or ''}".upper()
    s = (serie or "").upper().strip()

    if "BEPC" in raw or s == "BEPC":
        return "BEPC"

    if (
        "TECH" in raw
        or s in {"B", "G1", "G2", "G1G2", "BG1", "BG2", "BG1G2", "F", "F1", "F2", "F3", "F4", "STI"}
    ):
        return "BAC_TECHNIQUE"

    return "BAC_GENERAL"

def type_priority(type_doc, mode):
    t = (type_doc or "").upper().strip()
    table = EXAMEN_TYPES if mode == "examen" else ETUDE_TYPES
    return table.get(t, 0)

def chercher_contexte(question, matiere=None, serie=None, examen=None, mode="etude", max_docs=5):
    """Filtre les documents par examen/matière/série et recherche par mots-clés."""
    if not documents or not question:
        return []

    mode = normaliser_mode(mode, question)
    filtered_docs = documents

    if examen:
        filtered_docs = [d for d in filtered_docs if (d.get("examen") or "").upper().strip() == examen]

    if matiere:
        filtered_docs = [d for d in filtered_docs if (d.get("matiere") or "").upper().strip() == matiere]

    if serie:
        filtered_docs = [d for d in filtered_docs if serie_match(d.get("serie"), serie)]

    mots_cles = [m.lower() for m in re.findall(r"\\w+", question) if len(m) > 3]

    results = []
    for doc in filtered_docs:
        texte_brut = doc.get("texte", "")
        if isinstance(texte_brut, list):
            texte_brut = " ".join(str(x) for x in texte_brut)
        texte = str(texte_brut).lower()

        keyword_score = sum(1 for mot in mots_cles if mot in texte)
        meta_text = " ".join(str(doc.get(k, "")) for k in ["nom_fichier", "matiere", "serie", "type_doc", "annee"]).lower()
        meta_score = sum(1 for mot in mots_cles if mot in meta_text)

        if keyword_score > 0 or meta_score > 0:
            score = (keyword_score * 10) + (meta_score * 4) + type_priority(doc.get("type_doc"), mode)
            results.append((score, doc))

    results.sort(key=lambda x: x[0], reverse=True)
    return [doc for score, doc in results[:max_docs]]

def instructions_mode(mode, examen):
    if mode == "examen":
        return f"""
MODE EXAMEN ACTIVE.
- Mets l'élève en situation de {examen}.
- Priorise les sujets, annales, bac blanc, prépa, corrigés et barèmes.
- Ne donne pas toute la correction immédiatement si l'élève n'a pas encore essayé.
- Propose une question ou un exercice, puis attends sa tentative.
- Après sa réponse, corrige avec méthode, erreurs, points forts et barème indicatif.
"""
    return f"""
MODE ETUDE ACTIVE.
- Aide l'élève à comprendre progressivement pour le {examen}.
- Priorise programmes, progressions, guides, TP et documents pédagogiques.
- Explique en étapes courtes.
- Ne fais pas un cours complet sauf demande explicite.
- Termine par une petite question ou une action simple pour continuer.
"""
'''

if old not in s:
    raise SystemExit("Bloc chercher_contexte introuvable")
s = s.replace(old, new)

old = '''    mode_oral: Optional[str] = Form(None),
    history: Optional[str] = Form(None)
):'''
new = '''    mode_oral: Optional[str] = Form(None),
    history: Optional[str] = Form(None),
    mode: Optional[str] = Form("etude")
):'''
if old not in s:
    raise SystemExit("Signature ask_question introuvable")
s = s.replace(old, new)

old = '''        matiere_registre = MAP_MATIERE.get((matiere or "").strip().upper(), matiere)
        contexte_docs = chercher_contexte(question, matiere_registre, serie) if question else []
        contexte_texte = "\\n\\n".join([d.get('texte', '') for d in contexte_docs])
'''
new = '''        matiere_registre = MAP_MATIERE.get((matiere or "").strip().upper(), matiere)
        if matiere_registre:
            matiere_registre = matiere_registre.strip().upper()

        examen_registre = normaliser_examen_requete(type_examen, serie)
        mode_registre = normaliser_mode(mode, question)

        contexte_docs = chercher_contexte(
            question,
            matiere=matiere_registre,
            serie=serie,
            examen=examen_registre,
            mode=mode_registre,
            max_docs=6
        ) if question else []

        contexte_texte = "\\n\\n".join([str(d.get('texte', ''))[:3500] for d in contexte_docs])
'''
if old not in s:
    raise SystemExit("Bloc contexte_docs introuvable")
s = s.replace(old, new)

old = '''        # ─── 4. PRÉPARATION DU CONTENU MULTIMODAL POUR VERTEX AI ───
        contents = [system_prompt]
'''
new = '''        system_prompt = system_prompt + "\\n\\n" + instructions_mode(mode_registre, examen_registre)

        # ─── 4. PRÉPARATION DU CONTENU MULTIMODAL POUR VERTEX AI ───
        contents = [system_prompt]
'''
if old not in s:
    raise SystemExit("Bloc contents introuvable")
s = s.replace(old, new)

old = '''            "sources": [d.get("source", "Source officielle") for d in contexte_docs],
            "limit_reached": False,
'''
new = '''            "mode": mode_registre,
            "examen": examen_registre,
            "sources": [
                {
                    "source": d.get("source", "Source officielle"),
                    "nom_fichier": d.get("nom_fichier") or d.get("storage_path") or d.get("upload_path"),
                    "examen": d.get("examen"),
                    "serie": d.get("serie"),
                    "matiere": d.get("matiere"),
                    "type_doc": d.get("type_doc"),
                }
                for d in contexte_docs
            ],
            "limit_reached": False,
'''
if old not in s:
    raise SystemExit("Bloc return sources introuvable")
s = s.replace(old, new)

p.write_text(s, encoding="utf-8")
print("Patch Mode Etude / Mode Examen appliqué.")
