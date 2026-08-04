"""Refresh the vendored main-opening catalog from Lichess + Chess.com extras."""

import csv
import io
import json
import re
import unicodedata
from pathlib import Path

import requests

LICHESS_TSV_URLS = [
    "https://raw.githubusercontent.com/lichess-org/chess-openings/master/a.tsv",
    "https://raw.githubusercontent.com/lichess-org/chess-openings/master/b.tsv",
    "https://raw.githubusercontent.com/lichess-org/chess-openings/master/c.tsv",
    "https://raw.githubusercontent.com/lichess-org/chess-openings/master/d.tsv",
    "https://raw.githubusercontent.com/lichess-org/chess-openings/master/e.tsv",
]

# Chess.com ECOUrl naming that differs from or extends Lichess families.
CHESS_COM_EXTRAS = [
    "Alapin Sicilian Defense",
    "Alekhines Defense",
    "Birds Opening",
    "Budapest Gambit",
    "Caro Kann Defense",
    "Center Game",
    "Closed Sicilian Defense",
    "Colle System",
    "Danish Gambit",
    "Englund Gambit",
    "Giuoco Piano",
    "Giuoco Piano Game",
    "Grunfeld Defense",
    "Indian Game",
    "Kings Fianchetto Opening",
    "London System",
    "Mieses Opening",
    "Modern Defense",
    "Nimzowitsch Larsen Attack",
    "Old Benoni Defense",
    "Owens Defense",
    "Petrovs Defense",
    "Queens Pawn Opening",
    "Reti Opening",
    "Ruy Lopez Opening",
    "Saragossa Opening",
    "Torre Attack",
    "Trompowsky Attack",
    "Van t Kruijs Opening",
]

OUTPUT_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "chess_com"
    / "data"
    / "main_openings.json"
)


def _normalize_display_name(name: str) -> str:
    """Normalize an opening family to Chess.com-style display text."""
    decomposed = unicodedata.normalize("NFKD", name)
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    cleaned = without_marks.replace("'", "").replace("’", "").replace("-", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _fetch_lichess_families() -> set[str]:
    """Download Lichess opening TSVs and collect family names."""
    families = set()
    for url in LICHESS_TSV_URLS:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        reader = csv.DictReader(io.StringIO(response.text), delimiter="\t")
        for row in reader:
            family = row["name"].split(":", 1)[0].strip()
            if family:
                families.add(_normalize_display_name(family))
    return families


def main() -> None:
    """Build and write the main openings catalog JSON file."""
    families = _fetch_lichess_families()
    for extra in CHESS_COM_EXTRAS:
        families.add(_normalize_display_name(extra))

    main_openings = sorted(families, key=lambda name: (name.lower(), name))
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(main_openings, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(main_openings)} main openings to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
