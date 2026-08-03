"""Tests for Chess.com archive and PGN parsing."""

import pytest

from src.chess_com.parser import (
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
    assert parsed["pgn"] == SAMPLE_PGN


def test_rules_comes_from_api_game_object():
    game = {
        "uuid": "abc-123",
        "pgn": '[Link "https://www.chess.com/game/live/1"]\n\n1. e4 1-0',
        "rules": "chess960",
    }
    parsed = parse_game(game)
    assert parsed is not None
    assert parsed["rules"] == "chess960"
