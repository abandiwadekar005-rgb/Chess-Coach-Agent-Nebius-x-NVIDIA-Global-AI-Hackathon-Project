import chess.pgn

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