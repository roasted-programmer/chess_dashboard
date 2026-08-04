"""Split Chess.com opening names into main opening, variant, and subvariant."""

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Tuple

MAIN_OPENINGS_PATH = Path(__file__).resolve().parent / "data" / "main_openings.json"
UNDEFINED_OPENING = "Undefined"
# Chess.com sometimes glues black-move ellipsis to the family name
# (e.g. "Owens Defense...3.Nc3"). Digit-prefixed move notation like "2...Nc6"
# must remain intact.
FAMILY_ELLIPSIS_PATTERN = re.compile(r"(?<=[A-Za-z])\.{2,}")
MOVE_TOKEN_PATTERN = re.compile(r"^\d+\.")


def _normalize_opening_text(text: str) -> str:
    """Normalize opening text for catalog comparison."""
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    cleaned = without_marks.replace("'", "").replace("’", "").replace("-", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    return cleaned


@lru_cache(maxsize=1)
def _load_main_openings() -> Tuple[str, ...]:
    """Load main opening names sorted for longest-prefix matching."""
    raw_openings = json.loads(MAIN_OPENINGS_PATH.read_text(encoding="utf-8"))
    unique_openings = {_normalize_opening_text(name): name for name in raw_openings}
    sorted_openings = sorted(
        unique_openings.values(),
        key=lambda name: (len(_normalize_opening_text(name).split()), len(name)),
        reverse=True,
    )
    return tuple(sorted_openings)


def _split_variant_and_subvariant(remainder: str) -> Tuple[str, str]:
    """Split named variant text from trailing move notation."""
    remainder = remainder.strip()
    if not remainder:
        variant_parts = ("", "")
        return variant_parts

    tokens = remainder.split()
    move_tokens = list(enumerate(tokens))
    for index, token in move_tokens:
        if MOVE_TOKEN_PATTERN.match(token):
            opening_variant = " ".join(tokens[:index]).strip()
            opening_subvariant = " ".join(tokens[index:]).strip()
            variant_parts = (opening_variant, opening_subvariant)
            return variant_parts

    variant_parts = (remainder, "")
    return variant_parts


def split_opening(opening: str) -> Tuple[str, str, str]:
    """Split a full opening string into main, variant, and move subvariant.

    Args:
        opening (str): Full Chess.com-derived opening name.

    Returns:
        opening_parts (Tuple[str, str, str]): Main opening, named variant, and
            trailing move sequence. Empty strings are used when a part is absent.
    """
    opening = opening.strip()
    if not opening or _normalize_opening_text(opening) == _normalize_opening_text(
        UNDEFINED_OPENING
    ):
        opening_parts = ("", "", "")
        return opening_parts

    ellipsis_parts = FAMILY_ELLIPSIS_PATTERN.split(opening, maxsplit=1)
    prefix = ellipsis_parts[0].strip()
    ellipsis_remainder = ""
    if len(ellipsis_parts) > 1:
        ellipsis_remainder = ellipsis_parts[1].strip()

    if not prefix:
        opening_parts = (opening, "", "")
        return opening_parts

    tokens = prefix.split()
    normalized_tokens = [_normalize_opening_text(token) for token in tokens]
    main_openings = _load_main_openings()

    for candidate in main_openings:
        candidate_tokens = _normalize_opening_text(candidate).split()
        token_count = len(candidate_tokens)
        if normalized_tokens[:token_count] != candidate_tokens:
            continue
        main_opening = " ".join(tokens[:token_count])
        remainder_tokens = tokens[token_count:]
        remainder_parts = []
        if remainder_tokens:
            remainder_parts.append(" ".join(remainder_tokens))
        if ellipsis_remainder:
            remainder_parts.append(ellipsis_remainder)
        remainder = " ".join(remainder_parts).strip()
        opening_variant, opening_subvariant = _split_variant_and_subvariant(remainder)
        opening_parts = (main_opening, opening_variant, opening_subvariant)
        return opening_parts

    remainder_parts = []
    if ellipsis_remainder:
        remainder_parts.append(ellipsis_remainder)
    remainder = " ".join(remainder_parts).strip()
    opening_variant, opening_subvariant = _split_variant_and_subvariant(remainder)
    opening_parts = (prefix, opening_variant, opening_subvariant)
    return opening_parts
