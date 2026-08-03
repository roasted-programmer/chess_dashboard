"""Tests for Chess.com archive and PGN parsing."""

import pytest

from src.chess_com.parser import parse_archive_year_month, parse_game, parse_pgn_headers

SAMPLE_PGN = '''[Event "Live Chess"]
[White "LindaW25"]
[Black "donkaszak"]
[Result "1-0"]
[ECOUrl "https://www.chess.com/openings/Queen-s-Gambit-Declined-Exchange-Variation-5...Bc5-6.Nf3-Nc6-7.Bd3"]
[UTCDate "2026.08.03"]
[UTCTime "18:47:29"]
[WhiteElo "1638"]
[BlackElo "1627"]
[TimeControl "180"]
[Termination "LindaW25 won by resignation"]

1. d4 d5 2. c4 e6 1-0
'''


def test_parse_archive_year_month():
    url = "https://api.chess.com/pub/player/lindaw25/games/2026/08"
    assert parse_archive_year_month(url) == (2026, 8)


def test_parse_pgn_headers():
    headers = parse_pgn_headers(SAMPLE_PGN)
    assert headers["White"] == "LindaW25"
    assert headers["Black"] == "donkaszak"
    assert headers["Result"] == "1-0"
    assert headers["UTCDate"] == "2026.08.03"
    assert headers["TimeControl"] == "180"


def test_missing_optional_pgn_headers_do_not_fail():
    minimal_pgn = '[White "alice"]\n\n1. e4 e5 1-0'
    game = {"uuid": "abc-123", "pgn": minimal_pgn}
    parsed = parse_game(game)
    assert parsed is not None
    assert parsed["white_username"] == "alice"
    assert parsed["black_username"] == ""
    assert parsed["variant"] == ""


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
    }
    parsed = parse_game(game)
    assert parsed["uuid"] == "c75ab801-8f6b-11f1-bf80-6a5c6501000f"
    assert parsed["white_username"] == "LindaW25"
    assert parsed["black_username"] == "donkaszak"
    assert parsed["result"] == "1-0"
    assert parsed["pgn"] == SAMPLE_PGN
