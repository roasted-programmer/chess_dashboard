"""Tests for Chess.com archive and PGN parsing."""

import pytest

from src.chess_com.openings import split_opening
from src.chess_com.parser import (
    extract_opening_from_eco_url,
    is_missing_link_tag,
    parse_archive_year_month,
    parse_game,
    parse_pgn_headers,
)

SAMPLE_PGN = '''[Event "Live Chess"]
[White "LindaW25"]
[Black "donkaszak"]
[Result "1-0"]
[Link "https://www.chess.com/game/live/172488671824"]
[UTCDate "2026.08.03"]
[UTCTime "18:47:29"]
[WhiteElo "1638"]
[BlackElo "1627"]
[TimeControl "180"]
[Termination "LindaW25 won by resignation"]

1. d4 d5 2. c4 e6 1-0
'''

SAMPLE_PGN_WITH_ECO_URL = '''[Event "Live Chess"]
[White "Supersonic_Whisper"]
[Black "LindaW25"]
[Result "1-0"]
[ECOUrl "https://www.chess.com/openings/Bishops-Opening-2...Nc6"]
[Link "https://www.chess.com/game/live/2903831481"]
[UTCDate "2018.06.27"]
[UTCTime "08:19:18"]

1. e4 e5 2. Bc4 Nc6 1-0
'''


def test_parse_archive_year_month():
    url = "https://api.chess.com/pub/player/lindaw25/games/2026/08"
    assert parse_archive_year_month(url) == (2026, 8)


def test_parse_pgn_headers():
    headers = parse_pgn_headers(SAMPLE_PGN)
    assert headers["White"] == "LindaW25"
    assert headers["Black"] == "donkaszak"
    assert headers["Result"] == "1-0"
    assert headers["Link"] == "https://www.chess.com/game/live/172488671824"
    assert headers["UTCDate"] == "2026.08.03"
    assert headers["TimeControl"] == "180"


def test_missing_link_tag_is_rejected():
    minimal_pgn = '[White "alice"]\n\n1. e4 e5 1-0'
    game = {"uuid": "abc-123", "pgn": minimal_pgn}
    assert is_missing_link_tag(game)
    assert parse_game(game) is None


def test_game_missing_uuid_is_rejected():
    game = {"pgn": SAMPLE_PGN}
    assert parse_game(game) is None


def test_game_missing_pgn_is_rejected():
    game = {"uuid": "abc-123"}
    assert parse_game(game) is None


def test_parse_game_normalized_structure():
    game = {
        "uuid": "c75ab801-8f6b-11f1-bf80-6a5c6501000f",
        "pgn": SAMPLE_PGN,
        "time_control": "180",
        "rules": "chess",
    }
    parsed = parse_game(game)
    assert parsed["uuid"] == "c75ab801-8f6b-11f1-bf80-6a5c6501000f"
    assert parsed["white_username"] == "LindaW25"
    assert parsed["black_username"] == "donkaszak"
    assert parsed["result"] == "1-0"
    assert parsed["rules"] == "chess"
    assert parsed["game_url"] == "https://www.chess.com/game/live/172488671824"
    assert parsed["opening"] == ""
    assert parsed["pgn"] == SAMPLE_PGN


def test_extract_opening_from_eco_url():
    assert extract_opening_from_eco_url(
        "https://www.chess.com/openings/Bishops-Opening-2...Nc6"
    ) == "Bishops Opening 2...Nc6"
    assert extract_opening_from_eco_url(
        "https://www.chess.com/openings/Modern-Defense-with-1-e4-2.d4-d6-3.f4-Bg7"
    ) == "Modern Defense with 1 e4 2.d4 d6 3.f4 Bg7"
    assert extract_opening_from_eco_url("") == ""
    assert extract_opening_from_eco_url("https://example.com/openings/Foo") == ""


def test_opening_extracted_for_standard_chess():
    game = {
        "uuid": "2b9d6fda-7ac9-11e3-8000-000000010001",
        "pgn": SAMPLE_PGN_WITH_ECO_URL,
        "rules": "chess",
    }
    parsed = parse_game(game)
    assert parsed["opening"] == "Bishops Opening 2...Nc6"
    assert parsed["main_opening"] == "Bishops Opening"
    assert parsed["opening_variant"] == ""
    assert parsed["opening_subvariant"] == "2...Nc6"


def test_opening_blank_for_non_standard_chess():
    pgn = (
        '[Link "https://www.chess.com/game/live/3073171177"]\n'
        '[ECOUrl "https://www.chess.com/openings/Some-Opening"]\n\n'
        "1. e4 1-0"
    )
    game = {"uuid": "abc-123", "pgn": pgn, "rules": "chess960"}
    parsed = parse_game(game)
    assert parsed["opening"] == ""
    assert parsed["main_opening"] == ""
    assert parsed["opening_variant"] == ""
    assert parsed["opening_subvariant"] == ""


def test_opening_blank_when_eco_url_missing():
    game = {
        "uuid": "abc-123",
        "pgn": SAMPLE_PGN,
        "rules": "chess",
    }
    parsed = parse_game(game)
    assert parsed["opening"] == ""
    assert parsed["main_opening"] == ""
    assert parsed["opening_variant"] == ""
    assert parsed["opening_subvariant"] == ""


def test_split_opening_sicilian_variants():
    assert split_opening("Sicilian Defense Bowdler Attack") == (
        "Sicilian Defense",
        "Bowdler Attack",
        "",
    )
    assert split_opening(
        "Sicilian Defense Old Sicilian Variation 3.Bc4 e6"
    ) == ("Sicilian Defense", "Old Sicilian Variation", "3.Bc4 e6")
    assert split_opening("Sicilian Defense") == ("Sicilian Defense", "", "")


def test_split_opening_moves_keep_api_castling():
    assert split_opening("Ruy Lopez Opening Old Steinitz Defense 4.O O") == (
        "Ruy Lopez Opening",
        "Old Steinitz Defense",
        "4.O O",
    )
    assert split_opening("Pirc Defense Main Line 4.h3 Bg7 5.Be3 O O") == (
        "Pirc Defense",
        "Main Line",
        "4.h3 Bg7 5.Be3 O O",
    )
    assert split_opening("Sicilian Defense Old Sicilian Variation 3.Bc4 e6 4.O O") == (
        "Sicilian Defense",
        "Old Sicilian Variation",
        "3.Bc4 e6 4.O O",
    )


def test_split_opening_preserves_move_ellipsis():
    assert split_opening("Bishops Opening 2...Nc6") == (
        "Bishops Opening",
        "",
        "2...Nc6",
    )


def test_split_opening_family_ellipsis_boundary():
    assert split_opening("Owens Defense...3.Nc3 e6 4.Bd3 Bb4") == (
        "Owens Defense",
        "",
        "3.Nc3 e6 4.Bd3 Bb4",
    )


def test_split_opening_ruy_lopez_and_queens_gambit():
    assert split_opening("Ruy Lopez Opening Classical Defense") == (
        "Ruy Lopez Opening",
        "Classical Defense",
        "",
    )
    assert split_opening("Queens Gambit Declined Exchange Variation") == (
        "Queens Gambit Declined",
        "Exchange Variation",
        "",
    )


def test_split_opening_undefined_is_blank():
    assert split_opening("Undefined") == ("", "", "")


def test_extract_opening_keeps_api_castling():
    assert extract_opening_from_eco_url(
        "https://www.chess.com/openings/Ruy-Lopez-Opening-Old-Steinitz-Defense-4.O-O"
    ) == "Ruy Lopez Opening Old Steinitz Defense 4.O O"
    assert extract_opening_from_eco_url(
        "https://www.chess.com/openings/Sicilian-Defense-Open-Dragon-Variation-6.Bc4-Bg7-7.O-O-O-O"
    ) == "Sicilian Defense Open Dragon Variation 6.Bc4 Bg7 7.O O O O"


def test_rules_comes_from_api_game_object():
    game = {
        "uuid": "abc-123",
        "pgn": '[Link "https://www.chess.com/game/live/1"]\n\n1. e4 1-0',
        "rules": "chess960",
    }
    parsed = parse_game(game)
    assert parsed is not None
    assert parsed["rules"] == "chess960"
