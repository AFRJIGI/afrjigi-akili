"""Conversion du LaTeX des reponses d'Akili en notation lisible sur WhatsApp.

WhatsApp n'affiche pas le LaTeX. L'ancien nettoyage, fait d'expressions regulieres, cassait
les cas imbriques (\\frac{\\sqrt{3}}{2} devenait "√(3)2", \\int devenait "danst") et laissait
passer \\leq, \\text, \\overrightarrow... Ici on lit vraiment la structure (accolades
equilibrees), on garde les parentheses necessaires et on n'emploie que des symboles
courants sur Android. Pas de "_" ni de "~" en sortie : WhatsApp les prend pour de
l'italique et du barre.
"""
import re

SYMBOLES = {
    "leq": "≤", "le": "≤", "leqslant": "≤", "geq": "≥", "ge": "≥", "geqslant": "≥", "neq": "≠", "ne": "≠",
    "approx": "≈", "simeq": "≈", "sim": "∼", "equiv": "≡", "propto": "∝", "pm": "±", "mp": "∓",
    "times": "×", "cdot": "·", "div": "÷", "ast": "*", "infty": "∞", "to": "→", "rightarrow": "→",
    "longrightarrow": "→", "mapsto": "↦", "leftarrow": "←", "Rightarrow": "⇒", "implies": "⇒",
    "Longrightarrow": "⇒", "Leftarrow": "⇐", "Leftrightarrow": "⇔", "iff": "⇔", "Longleftrightarrow": "⇔",
    "in": "∈", "notin": "∉", "ni": "∋", "subset": "⊂", "subseteq": "⊂", "supset": "⊃", "cup": "∪",
    "cap": "∩", "emptyset": "∅", "varnothing": "∅", "forall": "∀", "exists": "∃", "neg": "¬",
    "wedge": "∧", "land": "∧", "vee": "∨", "lor": "∨", "mid": "|", "vert": "|", "lvert": "|", "rvert": "|",
    "Vert": "‖", "lVert": "‖", "rVert": "‖", "parallel": "∥", "perp": "⊥", "angle": "∠", "widehat": "",
    "circ": "°", "degree": "°", "ldots": "…", "cdots": "…", "dots": "…", "dotsc": "…", "vdots": "⋮",
    "partial": "∂", "nabla": "∇", "ell": "ℓ", "hbar": "ħ", "lt": "<", "gt": ">", "prime": "′",
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "varepsilon": "ε",
    "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "θ", "iota": "ι", "kappa": "κ", "lambda": "λ",
    "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π", "varpi": "π", "rho": "ρ", "varrho": "ρ", "sigma": "σ",
    "tau": "τ", "upsilon": "υ", "phi": "φ", "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π", "Sigma": "Σ",
    "Upsilon": "Υ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
    "quad": "  ", "qquad": "   ", ",": " ", ";": " ", ":": " ", "!": "", " ": " ", "%": "%", "&": "&",
    "#": "#", "$": "$", "{": "{", "}": "}", "_": " ", "|": "‖", "backslash": "\\",
}
FONCTIONS = {"sin", "cos", "tan", "cot", "sinh", "cosh", "tanh", "arcsin", "arccos", "arctan", "ln", "log",
             "exp", "lim", "max", "min", "sup", "inf", "det", "arg", "deg", "gcd", "dim", "ker", "Im", "Re",
             "limsup", "liminf", "sgn", "pgcd", "ppcm", "card", "mod", "bmod", "ch", "sh", "th"}
GROS_OPERATEURS = {"sum": "Σ", "prod": "Π", "int": "∫", "iint": "∬", "oint": "∮", "bigcup": "∪", "bigcap": "∩"}
ENSEMBLES = {"R": "ℝ", "N": "ℕ", "Z": "ℤ", "Q": "ℚ", "C": "ℂ"}
SANS_EFFET = {"left", "right", "big", "Big", "bigg", "Bigg", "bigl", "bigr", "Bigl", "Bigr", "displaystyle",
              "textstyle", "limits", "nolimits", "middle", "nonumber", "notag", "label", "tag"}
STYLES = {"text", "textrm", "textnormal", "mathrm", "mathbf", "textbf", "mathit", "textit", "emph", "mathsf",
          "mathtt", "texttt", "operatorname", "boldsymbol", "bm", "mbox", "hbox", "mathcal", "mathscr",
          "underline", "textup", "unit", "si", "mathring"}
EXPOSANTS = str.maketrans("0123456789+-=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")
INDICES = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")
# Seuls les indices lettres bien affiches sur Android (ᵢ et ⱼ manquent sur beaucoup de telephones).
INDICE_N = {"n": "ₙ", "k": "ₖ", "p": "ₚ"}


def _atome(texte):
    """Vrai si le texte peut s'ecrire sans parentheses dans une fraction ou une racine."""
    t = texte.strip()
    return bool(re.fullmatch(r"[-−]?[\w.,′'!°πθαβγλμσωΔ√²³⁰¹⁴⁵⁶⁷⁸⁹ⁿ⁻⁺]+", t)) and not re.search(r"[+\-−*/=]", t[1:])


def _denominateur_simple(texte):
    """2, 3,5, x, π, √3, x² : pas de parentheses ; 2a, x+1, 4ac : parentheses."""
    return bool(re.fullmatch(r"\d+(?:[.,]\d+)?|[A-Za-zα-ωΔΩ][²³ⁿ]?|√\w+|d[a-zθ]|d[a-zθ]²", texte.strip()))


def _paren(texte, denominateur=False):
    t = texte.strip()
    if denominateur and not _denominateur_simple(t) and not (t.startswith("(") and t.endswith(")") and _equilibre(t[1:-1])):
        return f"({t})"
    if _atome(t) or (t.startswith("(") and t.endswith(")") and _equilibre(t[1:-1])):
        return t
    return f"({t})"


def _equilibre(t):
    n = 0
    for c in t:
        n += c == "("
        n -= c == ")"
        if n < 0:
            return False
    return n == 0


def _exposant(texte):
    t = texte.strip()
    if t in {"°", "\\circ"}:
        return "°"
    if t == "′" or t == "'":
        return "′"
    if t and all(c in "0123456789+-−=()n" for c in t):
        return t.replace("−", "-").translate(EXPOSANTS)
    return "^" + (_paren(t) if len(t) > 1 else t)


def _indice(texte):
    t = texte.strip()
    if not t:
        return ""
    if all(c in "0123456789+-−=()" for c in t):
        return t.replace("−", "-").translate(INDICES)
    # indices de suites et de sommes : n, k, i, n+1, 2n, k-1...
    if re.fullmatch(r"\d*[nkp]([+\-−]\d+)?", t):
        return "".join(INDICE_N.get(c, c) for c in t.replace("−", "-")).translate(INDICES)
    return t  # lettres sans indice lisible : collees (CxHyOz), jamais de "_"


class _Lecteur:
    def __init__(self, texte):
        self.s, self.i = texte, 0

    def fini(self):
        return self.i >= len(self.s)

    def espaces(self):
        while not self.fini() and self.s[self.i] == " ":
            self.i += 1

    def groupe(self):
        """Argument : {..} equilibre, ou un seul symbole / une commande."""
        self.espaces()
        if self.fini():
            return ""
        c = self.s[self.i]
        if c == "{":
            n, debut = 0, self.i
            while not self.fini():
                if self.s[self.i] == "\\":
                    self.i += 2
                    continue
                n += self.s[self.i] == "{"
                n -= self.s[self.i] == "}"
                self.i += 1
                if n == 0:
                    return convertir(self.s[debut + 1:self.i - 1])
            return convertir(self.s[debut + 1:])
        if c == "\\":
            debut = self.i
            self.i += 1
            m = re.match(r"[A-Za-z]+", self.s[self.i:])
            self.i += len(m.group(0)) if m else 1
            return convertir(self.s[debut:self.i])
        self.i += 1
        return c

    def optionnel(self):
        self.espaces()
        if not self.fini() and self.s[self.i] == "[":
            fin = self.s.find("]", self.i)
            if fin > 0:
                contenu = self.s[self.i + 1:fin]
                self.i = fin + 1
                return convertir(contenu)
        return None

    def bornes(self):
        """_ et ^ qui suivent un gros operateur ou une limite."""
        bas = haut = None
        for _ in range(2):
            self.espaces()
            if not self.fini() and self.s[self.i] in "_^":
                signe = self.s[self.i]
                self.i += 1
                valeur = self.groupe()
                if signe == "_":
                    bas = valeur
                else:
                    haut = valeur
        return bas, haut


def convertir(texte):
    """LaTeX (sans les $) -> texte lisible."""
    lecteur, sortie = _Lecteur(texte), []
    while not lecteur.fini():
        s, i = lecteur.s, lecteur.i
        c = s[i]
        if c == "\\":
            m = re.match(r"\\([A-Za-z]+|.)", s[i:])
            nom = m.group(1)
            lecteur.i += len(m.group(0))
            sortie.append(_commande(nom, lecteur, sortie))
        elif c in "^_":
            lecteur.i += 1
            valeur = lecteur.groupe()
            sortie.append(_exposant(valeur) if c == "^" else _indice(valeur))
        elif c in "{}":
            lecteur.i += 1  # accolades de regroupement
        elif c in "~&":
            sortie.append(" ")
            lecteur.i += 1
        else:
            sortie.append(c)
            lecteur.i += 1
    return "".join(sortie)


def _commande(nom, lecteur, sortie):
    if nom in ("frac", "dfrac", "tfrac", "cfrac"):
        haut, bas = lecteur.groupe(), lecteur.groupe()
        fraction = f"{_paren(haut)}/{_paren(bas, denominateur=True)}"
        suite = re.sub(r"^(?:\s*\\(?:right|left|big|Big|bigg|Bigg)\b)+", "", lecteur.s[lecteur.i:]).lstrip(" ")
        avant = "".join(sortie)[-1:]
        if (suite and re.match(r"[\w(\\√]", suite)) or (avant and re.match(r"[\w)]", avant)):
            return f"({fraction})"  # 1/2 a t² -> (1/2)at² ; 2·1/3 -> 2(1/3)
        return fraction
    if nom == "sqrt":
        indice = lecteur.optionnel()
        contenu = lecteur.groupe()
        racine = {"3": "∛", "4": "∜"}.get((indice or "").strip(), "√")
        prefixe = "" if indice in (None, "3", "4") else _exposant(indice).lstrip("^")
        return f"{prefixe}{racine}{_paren(contenu)}"
    if nom in ("vec", "overrightarrow", "overline", "bar", "hat", "widehat", "tilde", "dot", "ddot", "underrightarrow"):
        contenu = lecteur.groupe().strip()
        if nom in ("vec", "overrightarrow", "underrightarrow"):
            espace = " " if sortie and re.search(r"\w$", sortie[-1]) else ""
            return f"{espace}vecteur {contenu}"
        if nom in ("overline", "bar"):
            return f"{contenu}̄" if len(contenu) == 1 else f"conj({contenu})"
        if nom in ("hat", "widehat"):
            return f"angle {contenu}"
        return contenu
    if nom == "binom":
        n, k = lecteur.groupe(), lecteur.groupe()
        return f"C({n.strip()}, {k.strip()})"
    if nom == "ce":
        return chimie(lecteur.groupe())
    if nom in ("mathbb", "Bbb"):
        contenu = lecteur.groupe().strip()
        return ENSEMBLES.get(contenu, contenu)
    if nom in STYLES:
        return lecteur.groupe()
    if nom in ("begin", "end"):
        lecteur.groupe()
        if nom == "begin" and not lecteur.fini() and lecteur.s[lecteur.i] == "{":
            lecteur.groupe()  # {cc} des tableaux
        return "\n" if nom == "end" else ""
    if nom == "\\":
        return "\n"
    if nom in GROS_OPERATEURS:
        bas, haut = lecteur.bornes()
        signe = GROS_OPERATEURS[nom]
        if nom.endswith("int") and (bas or haut):
            return f"{signe} de {(bas or '').strip()} à {(haut or '').strip()} "
        if bas and haut:
            return f"{signe}({bas.strip()} → {haut.strip()}) "
        return f"{signe}({bas.strip()}) " if bas else f"{signe} "
    if nom in FONCTIONS:
        if nom == "lim":
            bas, _ = lecteur.bornes()
            return f"lim({bas.strip()}) " if bas else "lim "
        return nom if nom not in ("bmod", "mod") else " mod "
    if nom in SANS_EFFET:
        if nom in ("label", "tag"):
            lecteur.groupe()
        return ""
    if nom in SYMBOLES:
        return SYMBOLES[nom]
    return nom  # commande inconnue : on garde le mot, sans le backslash


def chimie(formule):
    """\\ce{H2SO4} / SO4^2- : chiffres en indice apres une lettre ou une parenthese, charges en exposant."""
    formule = re.sub(r"\^\{?([0-9]*[+\-])\}?", lambda m: m.group(1).translate(EXPOSANTS), formule)
    formule = re.sub(r"(?<=[A-Za-z)\]])(\d+)", lambda m: m.group(1).translate(INDICES), formule)
    return formule.replace("->", "→").replace("<=>", "⇌")


DELIMITEURS = re.compile(r"\$\$(.+?)\$\$|\$(.+?)\$|\\\((.+?)\\\)|\\\[(.+?)\\\]", re.S)
COMMANDE_NUE = re.compile(r"\\[A-Za-z]+|\\[{}|,;!% ]")


def latex_vers_whatsapp(texte):
    """Convertit les formules ($...$, \\(...\\), \\[...\\]) et les commandes LaTeX restees seules."""
    texte = str(texte or "")
    if "\\" not in texte and "$" not in texte and not re.search(r"[\^_]\{|[A-Za-z0-9)][\^_][A-Za-z0-9(]", texte):
        return texte

    converties = []

    def formule(m):
        contenu = next(g for g in m.groups() if g is not None)
        converties.append(convertir(contenu.replace("{,}", ",")))
        return f"\x00{len(converties) - 1}\x00"

    texte = DELIMITEURS.sub(formule, texte)
    # Liens et adresses e-mail : jamais touches.
    texte = re.sub(r"https?://\S+|www\.\S+|[\w.+-]+@[\w-]+\.[\w.]+",
                   lambda m: (converties.append(m.group(0)), f"\x00{len(converties) - 1}\x00")[1], texte)
    texte = texte.replace("{,}", ",")
    # Commandes et ^ _ restes hors des $ (Akili en ecrit parfois sans delimiteurs).
    if COMMANDE_NUE.search(texte) or re.search(r"[\^_]", texte):
        lignes = []
        for ligne in texte.split("\n"):
            if COMMANDE_NUE.search(ligne) or re.search(r"[A-Za-z0-9)}\]][\^_][{A-Za-z0-9(\\+\-]", ligne):
                ligne = _convertir_hors_formule(ligne)
            lignes.append(ligne)
        texte = "\n".join(lignes)
    texte = texte.replace("$", "")
    texte = re.sub(r"\x00(\d+)\x00", lambda m: converties[int(m.group(1))], texte)
    return re.sub(r"[ \t]{2,}", " ", texte)


def _convertir_hors_formule(ligne):
    """Ligne de texte avec des morceaux de LaTeX : on convertit sans toucher aux mots normaux.
    Les * et _ de mise en forme WhatsApp (*gras*, _italique_) ne sont pas des formules."""
    morceaux = re.split(r"(\*[^*\n]+\*|(?<!\w)_[^_\n]+_(?!\w))", ligne)
    resultat = []
    for morceau in morceaux:
        if morceau.startswith("*") and morceau.endswith("*") and len(morceau) > 2:
            resultat.append("*" + _convertir_hors_formule(morceau[1:-1]) + "*")
        elif re.fullmatch(r"_[^_]+_", morceau):
            resultat.append(morceau)
        else:
            resultat.append(convertir(morceau))
    return "".join(resultat)
