"""The coaching brain: turns Stockfish's flagged moves into a coaching summary and chat answers.

This file builds prompts and calls Nemotron via inference/nebius_client.py. It contains no
chess-engine code and no UI code.
"""
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402
from inference.nebius_client import call_nemotron  # noqa: E402

MAX_MOVES_IN_PROMPT = 40  # keep the prompt bounded: worst mistakes first

COACH_RULES = (
    "You are a friendly, precise chess coach. You are given mistakes that a chess engine "
    "(Stockfish) flagged in a player's own games. The engine's 'best move' is ground truth: never "
    "contradict it and never invent a different best move. Only make claims the data supports; "
    "if you are unsure why a move was bad, say so rather than guessing. Evaluations are in "
    "pawns from the player's point of view (+1.0 = a pawn up)."
)


def _pawns(cp):
    return f"{cp / 100:+.1f}"


def summarize_stats(flagged_moves):
    """Cheap, factual aggregates the model can lean on (counts and averages by phase/colour)."""
    by_phase = defaultdict(list)
    for m in flagged_moves:
        by_phase[m["phase"]].append(m["eval_loss"])
    lines = []
    for phase in ("opening", "middlegame", "endgame"):
        losses = by_phase.get(phase)
        if losses:
            lines.append(
                f"- {phase}: {len(losses)} mistakes, average loss {sum(losses) / len(losses) / 100:.1f} pawns, "
                f"worst {max(losses) / 100:.1f}"
            )
    games = Counter(m.get("game", "?") for m in flagged_moves)
    lines.append(f"- games with flagged mistakes: {len(games)}")
    return "\n".join(lines)


def format_moves(flagged_moves, limit=MAX_MOVES_IN_PROMPT):
    worst = sorted(flagged_moves, key=lambda m: m["eval_loss"], reverse=True)[:limit]
    lines = []
    for m in worst:
        lines.append(
            f"- [{m.get('game', '?')}] move {m['move_number']} ({m['phase']}): played {m['move_san']}, "
            f"engine preferred {m['best_move_san']}; eval {_pawns(m['eval_before'])} -> {_pawns(m['eval_after'])} "
            f"(lost {m['eval_loss'] / 100:.1f} pawns)"
        )
    return "\n".join(lines)


def build_summary_prompt(flagged_moves):
    """Return the chat messages asking the model to find patterns across the mistakes."""
    user = (
        f"Here is a summary of the player's flagged mistakes:\n{summarize_stats(flagged_moves)}\n\n"
        f"The most costly individual mistakes:\n{format_moves(flagged_moves)}\n\n"
        "Write a short coaching report (about 200-300 words):\n"
        "1. The 2-3 recurring patterns you can actually see in this data (phase, type of mistake, "
        "repeated ideas) - do not just list the moves.\n"
        "2. For each pattern, one concrete thing to practise.\n"
        "3. One encouraging sentence.\n"
        "Cite specific moves from the data as evidence."
    )
    return [{"role": "system", "content": COACH_RULES}, {"role": "user", "content": user}]


def generate_summary(flagged_moves, model=None):
    """Coaching summary for a list of flagged moves (from data.db.analyze_multiple_games)."""
    if not flagged_moves:
        return "No significant mistakes found - solid play! Try lowering the mistake threshold or analysing more games."
    return call_nemotron(build_summary_prompt(flagged_moves), model=model or config.MODEL_ULTRA)


def chat(user_message, history, flagged_moves, summary=None, model=None):
    """Answer a follow-up question grounded in the player's flagged moves.

    history: list of {"role": "user"|"assistant", "content": str} for earlier turns.
    Uses the faster model by default so replies feel responsive.
    """
    context = (
        f"{COACH_RULES}\n\nPlayer data you can rely on:\n{summarize_stats(flagged_moves)}\n\n"
        f"Most costly mistakes:\n{format_moves(flagged_moves, limit=20)}"
    )
    if summary:
        context += f"\n\nYour earlier coaching report:\n{summary}"
    messages = [{"role": "system", "content": context}]
    messages += [{"role": m["role"], "content": m["content"]} for m in history[-10:]]
    messages.append({"role": "user", "content": user_message})
    return call_nemotron(messages, model=model or config.MODEL_FAST)
