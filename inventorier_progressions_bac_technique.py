"""Inventaire en lecture seule des progressions BAC Technique sur Fomesoutra."""

import argparse
import json
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin


BASE = (
    "https://www.fomesoutra.com/livres/"
    "metfpa-ministere-de-lenseignement-technique-de-la-formation-professionnelle-et-de-lapprentissage/"
    "progressions-de-lenseignement-technique-et-professionnel/"
)

DOSSIERS = {
    "BAC_E": "progressions-bac-e",
    "BAC_F1": "progressions-bac-f1",
    "BAC_F2": "progressions-bac-f2",
    "BAC_F3": "progressions-bac-f3",
    "BAC_F4": "progressions-bac-f4",
    "BAC_F7": "progressions-bac-f7",
    "ANGLAIS": "anglais-du-technique",
    "PHILOSOPHIE": "progressions-de-philosophie-du-technique",
    "DROIT_ECONOMIE_COMPTABILITE": "progressions-droits-economie-et-comptabilite",
    "EPS": "progressions-eps-filieres-tertiaires",
    "FRANCAIS_EXPRESSION": "progression-francais-techniques-dexpression",
    "HISTOIRE_GEOGRAPHIE": "histoire-geographie-du-technique",
    "MATHEMATIQUES": "maths-du-technique",
    "PHYSIQUE_CHIMIE": "progression-physique-chimie-du-technique",
}


class DownloadLinkParser(HTMLParser):
    def __init__(self, folder):
        super().__init__()
        self.folder_marker = f"/{folder.strip('/')}/"
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        values = dict(attrs)
        href = values.get("href", "")
        title = (values.get("data-title") or values.get("title") or "").strip()
        if (
            values.get("data-id")
            and href
            and title
            and self.folder_marker in href
            and not href.endswith("/file")
        ):
            self.links.append((title, urljoin(BASE, href.rstrip("/") + "/file")))


def fetch_folder(folder):
    request = urllib.request.Request(
        urljoin(BASE, folder),
        headers={"User-Agent": "AfrJigi-Akili-Inventory/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        html = response.read().decode("utf-8", errors="replace")
    parser = DownloadLinkParser(folder)
    parser.feed(html)
    unique = {}
    for title, url in parser.links:
        unique[url] = title
    return [{"titre": title, "url": url} for url, title in unique.items()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", help="Chemin JSON optionnel pour enregistrer l'inventaire")
    args = parser.parse_args()

    inventory = []
    failures = []
    for category, folder in DOSSIERS.items():
        try:
            documents = fetch_folder(folder)
            inventory.extend(
                {"categorie": category, "titre": item["titre"], "url": item["url"]}
                for item in documents
            )
            print(f"{category}: {len(documents)} documents", flush=True)
        except Exception as exc:
            failures.append({"categorie": category, "erreur": str(exc)})
            print(f"{category}: ERREUR {exc}", flush=True)

    result = {
        "source": urljoin(BASE, ".."),
        "categories": len(DOSSIERS),
        "documents": len(inventory),
        "inventaire": inventory,
        "erreurs": failures,
    }
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")
        print(f"Inventaire JSON: {args.output}")
    else:
        print("---JSON---")
        print(payload)


if __name__ == "__main__":
    main()
