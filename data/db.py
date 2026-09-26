from chess import Board, PGN
import chess.pgn
from chess import Board, PGN

def parse_pgn(pgn_text):
    import io
    pgn_io = io.StringIO(pgn_text)
    return chess.pgn.read_game(pgn_io)

def game_phase(move_number, total_moves):
    if move_number < 15:
        return "opening"
    elif move_number > total_moves - 15:
        return "endgame"
    else:
        return "middlegame"


STOCKFISH_PATH = "/path/to/stockfish"
BLUNDER_THRESHOLD = 150  # Adjust this: 100 is a mistake, 300+ is a blunder

def game_phase(move_number, total_moves):
    """Helper to categorize the game stage."""
    ratio = move_number / total_moves if total_moves > 0 else 0
    if ratio < 0.3: return "Opening"
    if ratio < 0.7: return "Middlegame"
    return "Endgame"

def analyze_game(pgn_text, player_color):
    """
    Analyzes a PGN game to identify blunders made by a specific player.
    """
    stockfish = Stockfish(path=STOCKFISH_PATH)
    board = Board()
    
    # Parse PGN using chess library
    import io
    pgn_io = io.StringIO(pgn_text)
    game = chess.pgn.read_game(pgn_io)
    
    if not game:
        return []

    results = []
    # Extract moves from the game
    moves = list(game.mainline_moves())
    total_moves = len(moves)

    for i, move in enumerate(moves):
        # Determine whose turn it is
        current_player_is_white = (i % 2 == 0)
        current_player_color = 'white' if current_player_is_white else 'black'

        if current_player_color == player_color:
            # 1. Evaluate position BEFORE the move
            stockfish.set_fen_position(board.fen())
            # Use 'cp' (centipawns) for easier math
            eval_before_dict = stockfish.get_evaluation()
            eval_before = eval_before_dict['value'] if eval_before_dict['type'] == 'cp' else 0

            # 2. Make the move
            board.push(move)
            
            # 3. Evaluate position AFTER the move
            stockfish.set_fen_position(board.fen())
            eval_after_dict = stockfish.get_evaluation()
            eval_after = eval_after_dict['value'] if eval_after_dict['type'] == 'cp' else 0

            # LOGIC FIX: 
            # If it was White's turn, a 'good' eval is positive. 
            # If White plays a move that makes eval go from +100 to -50, loss is 150.
            # If it was Black's turn, a 'good' eval is negative.
            # To make math easy, we convert everything to "advantage for white"
            
            # If it was Black's turn, we negate the evaluation to see it from White's perspective
            if current_player_is_white:
                # White wants high positive numbers
                eval_loss = eval_before - eval_after
            else:
                # Black wants high negative numbers. 
                # A blunder for black means the eval goes from -100 (good) to +50 (bad).
                # loss = (-100) - (+50) = -150. We take absolute for comparison.
                eval_loss = eval_before - eval_after 
                # Note: In stockfish, 'value' is relative to side to move. 
                # This is tricky. A safer way is to always convert to White's perspective:
                
            # REVISED SIMPLE LOGIC:
            # Let's assume 'eval_loss' is the drop in the player's own advantage.
            # If White's advantage drops by 200, eval_loss = 200.
            # If Black's advantage drops by 200, eval_loss = 200.
            
            # Correcting the math for Stockfish's "relative to side to move" evaluation:
            # If White moves: loss = eval_before - eval_after
            # If Black moves: loss = eval_after - eval_before (because Black's eval is negative)
            
            if current_player_is_white:
                actual_loss = eval_before - eval_after
            else:
                # If black's eval was -100 and becomes -300, they lost 200.
                # stockfish.get_evaluation() for black returns -100.
                # After blunder, it returns -300.
                # -100 - (-300) = 200.
                actual_loss = eval_before - eval_after

            if actual_loss > BLUNDER_THRESHOLD:
                # Get best move for the position BEFORE the blunder
                # The board currently has the move pushed, so we pop it to look at the state 
                # the player actually faced.
                board.pop() 
                stockfish.set_fen_position(board.fen())
                best_move = stockfish.get_best_move()
                
                # Re-apply the move to keep board in sync for next loop
                board.push(move)

                results.append({
                    "fen": board.fen(),
                    "move": move.uci(),
                    "eval_loss": actual_loss,
                    "phase": game_phase(i + 1, total_moves),
                    "best_move": best_move
                })
        else:
            # Just advance the board for the opponent's move
            board.push(move)

    return results