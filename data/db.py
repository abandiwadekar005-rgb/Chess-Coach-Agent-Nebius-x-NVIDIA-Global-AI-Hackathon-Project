import io
import chess.pgn
from chess import Board
from stockfish import Stockfish


STOCKFISH_PATH = "/path/to/stockfish"  # replace with real Stockfish executable
BLUNDER_THRESHOLD = 150


def parse_pgn(pgn_text):
    pgn_io = io.StringIO(pgn_text)
    return chess.pgn.read_game(pgn_io)


def game_phase(move_number, total_moves):
    """Categorize the stage of the game by move count."""
    if total_moves <= 0:
        return "opening"

    if move_number < 15:
        return "opening"
    elif move_number > total_moves - 15:
        return "endgame"
    else:
        return "middlegame"


def score_for_player(engine, board, player_color):
    """
    Convert Stockfish evaluation into the target player's perspective.

    In the installed Stockfish package behavior, the raw evaluation is already
    expressed relative to White in the simple test case used for verification.
    We therefore only flip the sign when the target player is Black.
    """
    evaluation = engine.get_evaluation()
    value = evaluation["value"]

    if evaluation["type"] == "mate":
        value = value * 1000

    if player_color == "black":
        value = -value

    return value


def analyze_game(pgn_text, player_color):
    """
    Analyzes a PGN game to identify blunders made by a specific player.
    Returns a list of dicts with FEN, move, eval loss, phase, and best move.
    """
    if player_color not in {"white", "black"}:
        raise ValueError("player_color must be 'white' or 'black'")

    stockfish = Stockfish(path=STOCKFISH_PATH)
    board = Board()

    game = parse_pgn(pgn_text)
    if not game:
        return []

    moves = list(game.mainline_moves())
    total_moves = len(moves)
    results = []

    for i, move in enumerate(moves):
        current_player_is_white = (i % 2 == 0)
        current_player_color = "white" if current_player_is_white else "black"

        # Only analyze the target player's moves
        if current_player_color != player_color:
            board.push(move)
            continue

        # Evaluate before the move from the player's perspective
        stockfish.set_fen_position(board.fen())
        before_score = score_for_player(stockfish, board, player_color)

        # Make the move
        board.push(move)

        # Evaluate after the move from the player's perspective
        stockfish.set_fen_position(board.fen())
        after_score = score_for_player(stockfish, board, player_color)

        # Loss in the player's own advantage
        eval_loss = before_score - after_score

        if eval_loss > BLUNDER_THRESHOLD:
            # Look at the position before the move to compute the best move.
            # This is the pre-move position the player actually faced.
            board.pop()
            pre_move_fen = board.fen()
            stockfish.set_fen_position(pre_move_fen)
            best_move = stockfish.get_best_move()

            # Restore board state for the next iteration
            board.push(move)

            results.append({
                "fen": pre_move_fen,
                "move": move.uci(),
                "eval_loss": eval_loss,
                "phase": game_phase(i + 1, total_moves),
                "best_move": best_move
            })

    return results


def analyze_multiple_games(pgn_texts, player_color):
    all_results = []
    for pgn in pgn_texts:
        all_results.extend(analyze_game(pgn, player_color))
    return all_results