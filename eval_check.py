import chess
from stockfish import Stockfish

board = chess.Board('4k3/8/8/8/8/8/8/4K1Q1 w - - 0 1')
print('FEN:', board.fen())
print('TURN:', board.turn)
engine = Stockfish()
engine.set_fen_position(board.fen())
print('EVAL:', engine.get_evaluation())
print('BEST:', engine.get_best_move())
