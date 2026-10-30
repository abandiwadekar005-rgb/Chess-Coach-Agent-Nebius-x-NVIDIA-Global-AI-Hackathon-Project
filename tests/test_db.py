import os

import pytest

from data import db

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples", "sample_games.pgn")

try:
    db.find_stockfish()
    HAVE_ENGINE = True
except db.EngineNotFoundError:
    HAVE_ENGINE = False

needs_engine = pytest.mark.skipif(not HAVE_ENGINE, reason="Stockfish binary not installed")


def sample_games():
    with open(SAMPLES, encoding="utf-8") as f:
        return db.split_games(f.read())


# --- pure logic -------------------------------------------------------------
def test_split_games_gives_one_game_per_string():
    games = sample_games()
    assert len(games) == 4
    assert all(g.count("[Event") == 1 for g in games)  # regression: exporter used to accumulate text


def test_split_games_skips_empty_and_variants():
    text = '[Event "empty"]\n\n*\n\n[Event "960"]\n[Variant "Chess960"]\n\n1. e4 e5 *\n\n[Event "ok"]\n\n1. e4 e5 *\n'
    games = db.split_games(text)
    assert len(games) == 1 and '"ok"' in games[0]


def test_game_phase():
    assert db.game_phase(5, 40) == "opening"
    assert db.game_phase(20, 40) == "middlegame"
    assert db.game_phase(35, 40) == "endgame"          # last 10 moves, no board given


def test_color_for_user():
    game = db.parse_pgn(sample_games()[0])
    assert db.color_for_user(game, "paul morphy") == "white"
    assert db.color_for_user(game, "Nobody") is None


def test_is_correct_answer():
    start = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    assert db.is_correct_answer(start, "e4", "e2e4") == "correct"
    assert db.is_correct_answer(start, "e2e4", "e2e4") == "correct"
    assert db.is_correct_answer(start, "d4", "e2e4") == "incorrect"
    assert db.is_correct_answer(start, "Ke5", "e2e4") == "invalid"
    assert db.is_correct_answer(start, "nonsense", "e2e4") == "invalid"


# --- the sign-convention bug: Engine must always report White's perspective --
class FakeStockfish:
    """Mimics both conventions the real package has used."""

    scores = {}  # fen -> white-perspective centipawns

    def __init__(self, path=None, depth=None, turn_perspective=False, side_relative=False):
        self.side_relative = side_relative
        self.fen = None

    def set_fen_position(self, fen):
        self.fen = fen

    def get_evaluation(self):
        white_cp = self.scores[self.fen]
        white_to_move = self.fen.split()[1] == "w"
        value = white_cp if (not self.side_relative or white_to_move) else -white_cp
        return {"type": "cp", "value": value}


@pytest.mark.parametrize("side_relative", [False, True])
def test_engine_always_returns_white_perspective(monkeypatch, side_relative):
    FakeStockfish.scores = {
        db.PROBE_FEN: 3400,
        "w_fen w - - 0 1": 120,
        "b_fen b - - 0 1": 120,
    }
    monkeypatch.setattr(db, "find_stockfish", lambda path=None: "fake")
    monkeypatch.setattr(db, "Stockfish", lambda **kw: FakeStockfish(side_relative=side_relative, **kw))
    engine = db.Engine()
    assert engine._white_relative is (not side_relative)
    assert engine.eval_white("w_fen w - - 0 1") == 120
    assert engine.eval_white("b_fen b - - 0 1") == 120   # same advantage for White, black to move


# --- real engine --------------------------------------------------------------
@needs_engine
def test_engine_probe_and_perspective_real_stockfish():
    engine = db.Engine(depth=10)
    try:
        white_up_queen_white_to_move = engine.eval_white("4k3/8/8/8/8/8/8/4K1Q1 w - - 0 1")
        white_up_queen_black_to_move = engine.eval_white("4k3/8/8/8/8/8/8/4K1Q1 b - - 0 1")
        assert white_up_queen_white_to_move > 500
        assert white_up_queen_black_to_move > 500        # the case eval_check.py could not catch
        assert engine.eval_white("4k1q1/8/8/8/8/8/8/4K3 w - - 0 1") < -500
    finally:
        engine.close()


@needs_engine
def test_black_blunders_are_found():
    games = sample_games()
    scholar = db.analyze_game(games[2], "black", depth=10)       # 3...Nf6?? allows Qxf7#
    assert [m["move_san"] for m in scholar] == ["Nf6"]
    assert scholar[0]["best_move_san"] == "g6" or scholar[0]["best_move"]
    assert scholar[0]["fen"].split()[1] == "b"                   # position BEFORE black's move


@needs_engine
def test_white_blunders_are_found_and_good_moves_are_not():
    games = sample_games()
    fools = db.analyze_game(games[3], "white", depth=10)         # 2.g4?? Qh4#
    assert "g4" in [m["move_san"] for m in fools]
    assert db.analyze_game(games[2], "white", depth=10) == []    # white delivered mate: no mistakes


@needs_engine
def test_multiple_games_cache_and_auto_color(tmp_path):
    from data.store import AnalysisCache

    cache = AnalysisCache(str(tmp_path / "cache.db"))
    games = sample_games()
    first = db.analyze_multiple_games(games, "black", depth=10, cache=cache)
    calls = []
    original = db.analyze_game
    db.analyze_game = lambda *a, **k: calls.append(1) or original(*a, **k)
    try:
        second = db.analyze_multiple_games(games, "black", depth=10, cache=cache)
    finally:
        db.analyze_game = original
    assert first == second and calls == []                        # second run served from cache

    auto = db.analyze_multiple_games(games, "auto", depth=10, username="Beginner")
    assert {m["color"] for m in auto} <= {"black", "white"} and auto  # Beginner = black in 3, white in 4


# --- fetching (mocked: Chess.com / Lichess are not reachable from every environment) --
class FakeResponse:
    def __init__(self, payload=None, text="", status=200):
        self._payload, self.text, self.status_code = payload, text, status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise db.requests.HTTPError(str(self.status_code))


def test_fetch_chesscom(monkeypatch):
    def fake_get(url, **kw):
        if url.endswith("/games/archives"):
            return FakeResponse({"archives": ["https://api.chess.com/pub/player/x/games/2026/09",
                                              "https://api.chess.com/pub/player/x/games/2026/10"]})
        return FakeResponse({"games": [
            {"rules": "chess", "pgn": "1. e4 e5 *"},
            {"rules": "bughouse", "pgn": "1. e4 *"},
            {"rules": "chess", "pgn": "1. d4 d5 *"},
        ]})
    monkeypatch.setattr(db.requests, "get", fake_get)
    assert db.fetch_games_from_chesscom("X", count=3) == ["1. d4 d5 *", "1. e4 e5 *", "1. d4 d5 *"]


def test_fetch_chesscom_unknown_user_and_network_error(monkeypatch):
    monkeypatch.setattr(db.requests, "get", lambda *a, **k: FakeResponse(status=404))
    assert db.fetch_games_from_chesscom("nobody") == []

    def boom(*a, **k):
        raise db.requests.ConnectionError("offline")
    monkeypatch.setattr(db.requests, "get", boom)
    with pytest.raises(db.GameFetchError):
        db.fetch_games_from_chesscom("x")


def test_fetch_lichess(monkeypatch):
    pgn = '[Event "a"]\n\n1. e4 e5 *\n\n[Event "b"]\n\n1. d4 d5 *\n'
    monkeypatch.setattr(db.requests, "get", lambda *a, **k: FakeResponse(text=pgn))
    assert len(db.fetch_games_from_lichess("x", 2)) == 2
