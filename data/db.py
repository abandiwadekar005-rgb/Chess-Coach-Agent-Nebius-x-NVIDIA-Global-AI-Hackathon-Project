"""All chess logic lives here: parsing games, running Stockfish, fetching games.

Nothing in this file talks to an LLM. Its job is to turn raw games into a list of
"the player made a significant mistake here" records that the rest of the app reasons over.
"""
import glob
import hashlib
import io
import os
import shutil
import sys

import chess
import chess.pgn
import requests
from stockfish import Stockfish

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

# Kept as module-level names so they're easy to find and tweak.
STOCKFISH_PATH = config.STOCKFISH_PATH
BLUNDER_THRESHOLD = config.BLUNDER_THRESHOLD

OPENING_MOVES = 10          # full moves
ENDGAME_MATERIAL = 20       # combined non-pawn material (N/B=3, R=5, Q=9) at or below this = endgame
PIECE_VALUES = {chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}

# White is up a queen and it is BLACK to move: the sign Stockfish reports tells us which
# perspective this version of the package uses (see Engine._probe).
PROBE_FEN = "4k3/8/8/8/8/8/8/4K1Q1 b - - 0 1"

USER_AGENT = {"User-Agent": "chess-coach-agent/1.0 (Nebius x NVIDIA hackathon project)"}


class EngineNotFoundError(RuntimeError):
    """Stockfish binary could not be located."""


class GameFetchError(RuntimeError):
    """Fetching games from Chess.com / Lichess failed."""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def parse_pgn(pgn_text):
    """Parse the first game in a PGN string. Returns a chess.pgn.Game, or None."""
    return chess.pgn.read_game(io.StringIO(pgn_text))


def split_games(pgn_text):
    """Split a (possibly multi-game) PGN string into a list of single-game PGN strings.

    Skips games with no moves and non-standard variants (Chess960 etc.), which this
    analysis does not support. Clock comments are stripped.
    """
    stream = io.StringIO(pgn_text)
    games = []
    while True:
        game = chess.pgn.read_game(stream)
        if game is None:
            break
        if game.next() is None:
            continue
        if game.headers.get("Variant", "Standard").lower() not in ("standard", "chess"):
            continue
        # A fresh exporter per game: exporters accumulate text across calls.
        exporter = chess.pgn.StringExporter(headers=True, variations=False, comments=False)
        games.append(game.accept(exporter))
    return games


def game_label(game):
    """Short human-readable label like 'Alice vs Bob (2026.10.01)'."""
    h = game.headers
    label = f"{h.get('White', '?')} vs {h.get('Black', '?')}"
    date = h.get("Date", "")
    return f"{label} ({date})" if date and "?" not in date else label


def color_for_user(game, username):
    """Return 'white' / 'black' depending on which side `username` played, else None."""
    name = username.strip().lower()
    if game.headers.get("White", "").lower() == name:
        return "white"
    if game.headers.get("Black", "").lower() == name:
        return "black"
    return None


# ---------------------------------------------------------------------------
# Game phase
# ---------------------------------------------------------------------------
def _non_pawn_material(board):
    return sum(
        len(board.pieces(piece_type, colour)) * value
        for piece_type, value in PIECE_VALUES.items()
        for colour in (chess.WHITE, chess.BLACK)
    )


def game_phase(move_number, total_moves, board=None):
    """Classify a position as 'opening', 'middlegame' or 'endgame'.

    `move_number` and `total_moves` are full moves. If `board` is given, material decides
    the endgame (more accurate); otherwise the last 10 moves of the game count as endgame.
    """
    if board is not None and _non_pawn_material(board) <= ENDGAME_MATERIAL:
        return "endgame"
    if move_number <= OPENING_MOVES:
        return "opening"
    if board is None and total_moves > OPENING_MOVES and move_number > total_moves - 10:
        return "endgame"
    return "middlegame"


# ---------------------------------------------------------------------------
# Stockfish
# ---------------------------------------------------------------------------
def find_stockfish(path=None):
    """Locate the Stockfish executable. Raises EngineNotFoundError with install hints."""
    candidates = [path, STOCKFISH_PATH, os.getenv("STOCKFISH_PATH"), shutil.which("stockfish")]
    candidates += [
        "/usr/games/stockfish",          # Debian/Ubuntu apt (incl. Streamlit Cloud packages.txt)
        "/usr/bin/stockfish",
        "/usr/local/bin/stockfish",
        "/opt/homebrew/bin/stockfish",   # macOS Homebrew
    ]
    # Windows: a downloaded stockfish*.exe dropped in the project folder or ./stockfish/
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for pattern in ("stockfish*.exe", os.path.join("stockfish", "**", "stockfish*.exe")):
        candidates += glob.glob(os.path.join(root, pattern), recursive=True)

    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise EngineNotFoundError(
        "Stockfish was not found. Install it (Windows: download from stockfishchess.org and set "
        "STOCKFISH_PATH in .env; macOS: `brew install stockfish`; Linux: `apt install stockfish`)."
    )


class Engine:
    """Thin wrapper around the `stockfish` package that always answers from White's point of view.

    Different versions of the package report scores either from White's perspective or from the
    side-to-move's perspective. Rather than assume, we measure it once on a known position.
    """

    def __init__(self, depth=None, path=None):
        exe = find_stockfish(path)
        depth = depth or config.ENGINE_DEPTH
        try:
            self._sf = Stockfish(path=exe, depth=depth, turn_perspective=False)
        except TypeError:  # older package versions have no turn_perspective option
            self._sf = Stockfish(path=exe, depth=depth)
        self._white_relative = self._probe()

    def _probe(self):
        self._sf.set_fen_position(PROBE_FEN)
        return self._sf.get_evaluation()["value"] > 0

    def eval_white(self, fen):
        """Evaluation in centipawns from White's perspective (mates become +/-MATE_SCORE-ish)."""
        self._sf.set_fen_position(fen)
        white_to_move = fen.split()[1] == "w"
        result = self._sf.get_evaluation()
        kind, value = result["type"], result["value"]

        if kind == "mate":
            if value == 0:  # checkmate on the board: the side to move has lost
                return -config.MATE_SCORE if white_to_move else config.MATE_SCORE
            score = (config.MATE_SCORE - 10 * abs(value)) * (1 if value > 0 else -1)
        else:
            score = value

        if self._white_relative or white_to_move:
            return score
        return -score

    def best_move(self, fen):
        self._sf.set_fen_position(fen)
        return self._sf.get_best_move()

    def close(self):
        try:
            self._sf.send_quit_command()
        except Exception:
            pass


def _clamp(cp):
    return max(-config.EVAL_CAP, min(config.EVAL_CAP, cp))


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
def analyze_game(pgn_text, player_color, threshold=None, depth=None, engine=None, username=None):
    """Find the moves where `player_color` lost significant ground.

    player_color: 'white', 'black', or 'auto' (use `username` to match the PGN headers).
    Returns a list of dicts, one per flagged move, each describing the position the player
    actually faced (`fen`), what they played, what Stockfish preferred, and how much it cost.
    """
    if player_color not in {"white", "black", "auto"}:
        raise ValueError("player_color must be 'white', 'black' or 'auto'")
    threshold = BLUNDER_THRESHOLD if threshold is None else threshold

    game = parse_pgn(pgn_text)
    if game is None:
        return []

    if player_color == "auto":
        player_color = color_for_user(game, username or "")
        if player_color is None:
            return []
    player_is_white = player_color == "white"
    sign = 1 if player_is_white else -1

    own_engine = engine is None
    engine = engine or Engine(depth=depth)
    try:
        board = game.board()
        moves = list(game.mainline_moves())
        total_full_moves = (len(moves) + 1) // 2
        label = game_label(game)
        results = []

        for move in moves:
            if board.turn != player_is_white:
                board.push(move)
                continue

            fen_before = board.fen()
            move_number = board.fullmove_number
            san = board.san(move)
            phase = game_phase(move_number, total_full_moves, board)

            before = sign * _clamp(engine.eval_white(fen_before))
            board.push(move)
            after = sign * _clamp(engine.eval_white(board.fen()))
            eval_loss = before - after

            if eval_loss > threshold:
                best_uci = engine.best_move(fen_before)
                best_san = None
                if best_uci:
                    best_san = chess.Board(fen_before).san(chess.Move.from_uci(best_uci))
                results.append({
                    "game": label,
                    "color": player_color,
                    "move_number": move_number,
                    "fen": fen_before,          # position BEFORE the player's move
                    "move": move.uci(),
                    "move_san": san,
                    "best_move": best_uci,
                    "best_move_san": best_san,
                    "eval_before": before,      # centipawns, from the player's point of view
                    "eval_after": after,
                    "eval_loss": eval_loss,
                    "phase": phase,
                })
        return results
    finally:
        if own_engine:
            engine.close()


def pgn_key(pgn_text):
    """Stable hash identifying a game (used as a cache key)."""
    return hashlib.sha256(pgn_text.strip().encode("utf-8")).hexdigest()


def analyze_multiple_games(pgn_texts, player_color, threshold=None, depth=None,
                           username=None, progress=None, cache=None):
    """Run analyze_game over many games using ONE Stockfish process.

    progress: optional callable(done, total) for UI progress bars.
    cache: optional object with get(key, color, threshold, depth) / put(...) (see data/store.py).
    """
    threshold = BLUNDER_THRESHOLD if threshold is None else threshold
    depth = depth or config.ENGINE_DEPTH
    pgn_texts = list(pgn_texts)[: config.MAX_GAMES]
    total = len(pgn_texts)
    all_results = []
    engine = None
    try:
        for done, pgn in enumerate(pgn_texts, start=1):
            # Resolve 'auto' to a real colour first so cache entries are never shared across sides.
            color = player_color
            if color == "auto":
                game = parse_pgn(pgn)
                color = color_for_user(game, username or "") if game else None

            if color is not None:
                key = pgn_key(pgn)
                cached = cache.get(key, color, threshold, depth) if cache else None
                if cached is not None:
                    all_results.extend(cached)
                else:
                    engine = engine or Engine(depth=depth)
                    found = analyze_game(pgn, color, threshold=threshold, depth=depth, engine=engine)
                    if cache:
                        cache.put(key, color, threshold, depth, found, username)
                    all_results.extend(found)
            if progress:
                progress(done, total)
    finally:
        if engine:
            engine.close()
    return all_results


def is_correct_answer(fen, answer, best_move_uci):
    """Check a user's puzzle answer (SAN like 'Nf3' or UCI like 'g1f3').

    Returns 'correct', 'incorrect', or 'invalid' (not a legal move in this position).
    """
    board = chess.Board(fen)
    text = answer.strip()
    move = None
    try:
        move = board.parse_san(text)
    except ValueError:
        try:
            candidate = chess.Move.from_uci(text.lower())
            move = candidate if candidate in board.legal_moves else None
        except ValueError:
            move = None
    if move is None:
        return "invalid"
    return "correct" if move.uci() == best_move_uci else "incorrect"


# ---------------------------------------------------------------------------
# Fetching games from public APIs
# ---------------------------------------------------------------------------
def fetch_games_from_chesscom(username, count=10):
    """Return up to `count` of the user's most recent standard-chess games as PGN strings."""
    username = username.strip().lower()
    base = f"https://api.chess.com/pub/player/{username}/games/archives"
    try:
        resp = requests.get(base, headers=USER_AGENT, timeout=15)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        pgns = []
        for archive_url in reversed(resp.json().get("archives", [])):
            month = requests.get(archive_url, headers=USER_AGENT, timeout=20)
            month.raise_for_status()
            for game in reversed(month.json().get("games", [])):
                if game.get("rules") == "chess" and game.get("pgn"):
                    pgns.append(game["pgn"])
                    if len(pgns) >= count:
                        return pgns
        return pgns
    except requests.RequestException as exc:
        raise GameFetchError(f"Could not reach Chess.com: {exc}") from exc


def fetch_games_from_lichess(username, count=10):
    """Return up to `count` of the user's most recent games from Lichess as PGN strings."""
    url = f"https://lichess.org/api/games/user/{username.strip()}"
    params = {"max": count, "moves": "true", "tags": "true", "clocks": "false",
              "evals": "false", "opening": "false"}
    headers = {**USER_AGENT, "Accept": "application/x-chess-pgn"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return split_games(resp.text)
    except requests.RequestException as exc:
        raise GameFetchError(f"Could not reach Lichess: {exc}") from exc
