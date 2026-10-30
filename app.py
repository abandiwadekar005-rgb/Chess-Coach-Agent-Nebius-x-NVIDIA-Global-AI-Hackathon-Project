"""Chess Coach Agent - Streamlit UI.

UI only: every bit of chess or AI logic is delegated to data/, agent/ and inference/.
Run with:  streamlit run app.py
"""
import base64
import os
import sys

import chess
import chess.svg
import pandas as pd
import streamlit as st

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

# Streamlit Cloud keeps secrets in st.secrets; the rest of the app reads environment variables.
try:
    if "NEBIUS_API_KEY" in st.secrets:
        os.environ.setdefault("NEBIUS_API_KEY", st.secrets["NEBIUS_API_KEY"])
except Exception:  # no secrets file locally - that's fine, .env is used instead
    pass

import config  # noqa: E402
from agent.orchestrator import chat, generate_summary  # noqa: E402
from agent.puzzle_gen import generate_puzzle  # noqa: E402
from data import db  # noqa: E402
from data.store import AnalysisCache  # noqa: E402
from inference.nebius_client import NebiusError  # noqa: E402

SAMPLE_PATH = os.path.join(ROOT, "samples", "sample_games.pgn")
PHASES = ["opening", "middlegame", "endgame"]

st.set_page_config(page_title="Chess Coach Agent", page_icon="♟️", layout="wide")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@st.cache_resource
def get_cache():
    return AnalysisCache()


def render_board(fen, orientation=chess.WHITE, played=None, best=None, size=360):
    """Draw a position as an inline SVG. Red arrow = move played, green arrow = engine's choice."""
    arrows = []
    if played:
        m = chess.Move.from_uci(played)
        arrows.append(chess.svg.Arrow(m.from_square, m.to_square, color="#cc3333cc"))
    if best:
        m = chess.Move.from_uci(best)
        arrows.append(chess.svg.Arrow(m.from_square, m.to_square, color="#2e9d4fcc"))
    svg = chess.svg.board(chess.Board(fen), orientation=orientation, arrows=arrows, size=size)
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    st.markdown(f'<img src="data:image/svg+xml;base64,{b64}" width="{size}"/>', unsafe_allow_html=True)


def orientation_of(move):
    return chess.WHITE if move["color"] == "white" else chess.BLACK


def describe(move):
    return (f"{move['game']} - move {move['move_number']} ({move['phase']}): "
            f"{move['move_san']}  (-{move['eval_loss'] / 100:.1f})")


def gather_games(source, upload, pasted, username, count):
    """Return (list of PGN strings, username or None) for the chosen source."""
    if source == "Sample games":
        with open(SAMPLE_PATH, encoding="utf-8") as f:
            return db.split_games(f.read()), None
    if source == "Upload / paste PGN":
        texts = [f.getvalue().decode("utf-8", errors="replace") for f in (upload or [])]
        if pasted.strip():
            texts.append(pasted)
        games = [g for t in texts for g in db.split_games(t)]
        return games, None
    if not username.strip():
        return [], None
    fetch = db.fetch_games_from_chesscom if source == "Chess.com" else db.fetch_games_from_lichess
    return db.split_games("\n\n".join(fetch(username, count))), username.strip()


# ---------------------------------------------------------------------------
# Sidebar: inputs
# ---------------------------------------------------------------------------
st.sidebar.header("1. Your games")
source = st.sidebar.radio("Where are the games?", ["Sample games", "Upload / paste PGN", "Chess.com", "Lichess"])

upload, pasted, username = None, "", ""
color_choice = "auto"
if source == "Upload / paste PGN":
    upload = st.sidebar.file_uploader("PGN files", type="pgn", accept_multiple_files=True)
    pasted = st.sidebar.text_area("...or paste PGN text", height=120)
elif source in ("Chess.com", "Lichess"):
    username = st.sidebar.text_input(f"{source} username")
    color_choice = "auto"
if source in ("Sample games", "Upload / paste PGN"):
    color_choice = st.sidebar.selectbox("Which side were you?", ["black", "white"],
                                        help="Mistakes are only counted for the side you pick.")
if source in ("Chess.com", "Lichess"):
    st.sidebar.caption("Your colour is detected from your username in each game.")
    game_count = st.sidebar.slider("How many recent games?", 1, config.MAX_GAMES, 5)
else:
    game_count = config.MAX_GAMES

with st.sidebar.expander("Advanced"):
    threshold = st.slider("Mistake threshold (centipawns lost)", 50, 400, config.BLUNDER_THRESHOLD, 10,
                          help="100 cp = one pawn. Lower catches smaller inaccuracies.")
    depth = st.slider("Engine depth", 8, 18, config.ENGINE_DEPTH,
                      help="Higher is more accurate but slower.")
    ultra_model = st.text_input("Reasoning model (reports, puzzles)", config.MODEL_ULTRA)
    fast_model = st.text_input("Fast model (chat)", config.MODEL_FAST)

analyze_clicked = st.sidebar.button("Analyze my games", type="primary", use_container_width=True)


# ---------------------------------------------------------------------------
# Run analysis
# ---------------------------------------------------------------------------
if analyze_clicked:
    st.session_state.pop("analysis", None)
    st.session_state.update(chat_history=[], puzzle_state={})
    for stale in [k for k in st.session_state if k.startswith(("answer_", "check_", "reveal_"))]:
        del st.session_state[stale]  # puzzle widgets from a previous analysis
    try:
        pgns, user = gather_games(source, upload, pasted, username, game_count)
    except db.GameFetchError as exc:
        st.sidebar.error(str(exc))
        pgns, user = [], None

    if not pgns:
        st.sidebar.warning("No games found. Check the username, or upload a PGN file.")
    else:
        bar = st.progress(0.0, text="Starting Stockfish...")
        try:
            moves = db.analyze_multiple_games(
                pgns, color_choice, threshold=threshold, depth=depth, username=user, cache=get_cache(),
                progress=lambda done, total: bar.progress(done / total, text=f"Analysed {done}/{total} games"),
            )
        except db.EngineNotFoundError as exc:
            bar.empty()
            st.error(str(exc))
            st.stop()
        bar.empty()

        summary, summary_error = None, None
        with st.spinner("Nemotron is reading your mistakes..."):
            try:
                summary = generate_summary(moves, model=ultra_model)
            except NebiusError as exc:
                summary_error = str(exc)

        st.session_state.analysis = {
            "moves": moves, "games": min(len(pgns), config.MAX_GAMES), "summary": summary,
            "summary_error": summary_error, "ultra": ultra_model, "fast": fast_model,
        }


# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------
st.title("Chess Coach Agent")
st.caption("Stockfish finds your mistakes. NVIDIA Nemotron, served on Nebius Token Factory, finds the patterns behind them.")

analysis = st.session_state.get("analysis")
if not analysis:
    st.info("Pick a source in the sidebar and press **Analyze my games**. "
            "The sample games let you try the app without any files.")
    c1, c2, c3 = st.columns(3)
    c1.markdown("**1. Stockfish** replays every move and flags where you lost ground.")
    c2.markdown("**2. Nemotron** looks across all your games for recurring weaknesses.")
    c3.markdown("**3. You** train on puzzles from your own mistakes and ask the coach questions.")
    st.stop()

moves = analysis["moves"]
if not moves:
    st.success("No mistakes above the threshold - nice play! Try lowering the threshold in Advanced.")
    st.stop()

by_phase = pd.Series([m["phase"] for m in moves]).value_counts().reindex(PHASES, fill_value=0)
m1, m2, m3, m4 = st.columns(4)
m1.metric("Games analysed", analysis["games"])
m2.metric("Mistakes flagged", len(moves))
m3.metric("Average cost", f"{sum(m['eval_loss'] for m in moves) / len(moves) / 100:.1f} pawns")
m4.metric("Weakest phase", by_phase.idxmax().title())

tab_report, tab_mistakes, tab_puzzles, tab_chat = st.tabs(
    ["Coaching report", "Your mistakes", "Puzzles", "Ask the coach"]
)

with tab_report:
    if analysis["summary"]:
        st.markdown(analysis["summary"])
    else:
        st.error(analysis["summary_error"] or "No report was generated.")
        st.caption("The engine analysis below still works. Fix the issue above and press Analyze again.")
    st.subheader("Mistakes by game phase")
    # Numbered labels keep the bars in game order (Streamlit sorts category names alphabetically).
    chart = by_phase.rename(index={p: f"{i}. {p.title()}" for i, p in enumerate(PHASES, start=1)})
    st.bar_chart(chart, color="#76b900")

with tab_mistakes:
    table = pd.DataFrame([{
        "Game": m["game"], "Move": m["move_number"], "Phase": m["phase"], "You played": m["move_san"],
        "Engine preferred": m["best_move_san"], "Lost (pawns)": round(m["eval_loss"] / 100, 1),
    } for m in moves])
    st.dataframe(table, hide_index=True, use_container_width=True)

    st.subheader("See the position")
    pick = st.selectbox("Choose a mistake", range(len(moves)), format_func=lambda i: describe(moves[i]))
    chosen = moves[pick]
    left, right = st.columns([1, 1])
    with left:
        render_board(chosen["fen"], orientation_of(chosen), chosen["move"], chosen["best_move"])
    with right:
        st.markdown(f"**You played** {chosen['move_san']} (red arrow)")
        st.markdown(f"**Engine preferred** {chosen['best_move_san']} (green arrow)")
        st.markdown(f"Evaluation went from **{chosen['eval_before'] / 100:+.1f}** to "
                    f"**{chosen['eval_after'] / 100:+.1f}** (from your side's point of view).")

with tab_puzzles:
    st.write("Each puzzle is a position from your own games where you went wrong. "
             "Find the move the engine preferred.")
    puzzles = sorted(moves, key=lambda m: m["eval_loss"], reverse=True)
    idx = st.selectbox("Puzzle", range(len(puzzles)), key="puzzle_pick",
                       format_func=lambda i: f"#{i + 1}: {puzzles[i]['game']} - move {puzzles[i]['move_number']}")
    puzzle = puzzles[idx]
    state = st.session_state.setdefault("puzzle_state", {}).setdefault(
        idx, {"result": None, "revealed": False, "explanation": None})
    side = "White" if puzzle["color"] == "white" else "Black"

    left, right = st.columns([1, 1])
    with left:
        if state["revealed"]:
            render_board(puzzle["fen"], orientation_of(puzzle), puzzle["move"], puzzle["best_move"])
        else:
            render_board(puzzle["fen"], orientation_of(puzzle))
    with right:
        st.markdown(f"**{side} to move.** What is the best move?")
        answer = st.text_input("Your move (like Nf3 or g1f3)", key=f"answer_{idx}")
        b1, b2 = st.columns(2)
        if b1.button("Check", key=f"check_{idx}") and answer.strip():
            state["result"] = db.is_correct_answer(puzzle["fen"], answer, puzzle["best_move"])
            state["revealed"] = state["result"] == "correct"
            st.rerun()
        if b2.button("Show answer", key=f"reveal_{idx}"):
            state["revealed"] = True
            st.rerun()

        if state["result"] == "correct":
            st.success("Correct! That is the engine's choice.")
        elif state["result"] == "incorrect":
            st.warning("Not the best move. Try again, or show the answer.")
        elif state["result"] == "invalid":
            st.error("That is not a legal move here.")

        if state["revealed"]:
            st.markdown(f"**Best move:** {puzzle['best_move_san']} (green arrow). "
                        f"You played {puzzle['move_san']} (red arrow).")
            if state["explanation"] is None:
                with st.spinner("Nemotron is explaining why..."):
                    try:
                        state["explanation"] = generate_puzzle(puzzle, model=analysis["ultra"])
                    except NebiusError as exc:
                        state["explanation"] = f"Explanation unavailable: {exc}"
            st.markdown(state["explanation"])

with tab_chat:
    st.write("Ask about your games: *Why do I keep losing in the opening? What should I practise first?*")
    history = st.session_state.setdefault("chat_history", [])
    for turn in history:
        with st.chat_message(turn["role"]):
            st.markdown(turn["content"])
    if question := st.chat_input("Ask your coach"):
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    reply = chat(question, history, moves, summary=analysis["summary"], model=analysis["fast"])
                except NebiusError as exc:
                    reply = f"Sorry, I couldn't reach the model: {exc}"
            st.markdown(reply)
        history.extend([{"role": "user", "content": question}, {"role": "assistant", "content": reply}])
