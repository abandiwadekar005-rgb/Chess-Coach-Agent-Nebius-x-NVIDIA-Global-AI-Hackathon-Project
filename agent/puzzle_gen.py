"""Turns a flagged mistake into a training puzzle explanation.

Safety rule baked into the prompt: Stockfish decides what the correct move is; Nemotron only
explains WHY. The model is never asked to find or judge the best move itself.
"""
import os
import sys

import chess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402
from inference.nebius_client import call_nemotron  # noqa: E402


def puzzle_prompt(flagged_move):
    """Build the chat messages for explaining one flagged move."""
    board = chess.Board(flagged_move["fen"])
    side = "White" if board.turn == chess.WHITE else "Black"
    system = (
        "You are a chess coach writing a short explanation for a training puzzle. The engine has "
        "already determined the correct move; treat it as ground truth. Explain in plain language "
        "why that move is better than the move the player chose. Do NOT suggest any other best "
        "move, and do not state specific variations or evaluations beyond those provided. If you "
        "cannot tell why from the information given, describe the general idea instead."
    )
    user = (
        f"Position (FEN): {flagged_move['fen']}\n"
        f"Side to move: {side}\n"
        f"Move the player chose: {flagged_move['move_san']} "
        f"(evaluation after it: {flagged_move['eval_after'] / 100:+.1f} pawns for the player)\n"
        f"Engine's best move: {flagged_move['best_move_san']} "
        f"(evaluation before the move: {flagged_move['eval_before'] / 100:+.1f} pawns for the player)\n"
        f"Game phase: {flagged_move['phase']}\n\n"
        "In 3-4 sentences: why was the best move better, and what should the player look for "
        "next time in positions like this?"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def generate_puzzle(flagged_move, model=None):
    """Return the model's explanation of why `best_move` beats the played move."""
    if not flagged_move.get("best_move_san"):
        return "No engine suggestion is available for this position."
    return call_nemotron(puzzle_prompt(flagged_move), model=model or config.MODEL_ULTRA)
