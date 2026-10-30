"""Central settings. Everything configurable lives here (or in environment variables)."""
import os

from dotenv import load_dotenv

load_dotenv()

# --- Nebius Token Factory ---------------------------------------------------
NEBIUS_BASE_URL = os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/")
NEBIUS_API_KEY_ENV = "NEBIUS_API_KEY"  # name of the env variable / Streamlit secret

# Model IDs. Override with env vars if your account lists them differently.
# Run `python -m inference.nebius_client --models` to print the IDs your key can see.
# (IDs are matched case-insensitively against that list at runtime.)
MODEL_ULTRA = os.getenv("NEMOTRON_MODEL_ULTRA", "nvidia/nemotron-3-ultra-550b-a55b")
MODEL_FAST = os.getenv("NEMOTRON_MODEL_FAST", "nvidia/nemotron-3.5-lightning")

# --- Chess analysis ---------------------------------------------------------
# Stockfish binary location. Leave unset to auto-detect (PATH, /usr/games, common Windows folders).
STOCKFISH_PATH = os.getenv("STOCKFISH_PATH", "")
ENGINE_DEPTH = int(os.getenv("ENGINE_DEPTH", "12"))      # lower = faster, higher = more accurate
BLUNDER_THRESHOLD = int(os.getenv("BLUNDER_THRESHOLD", "150"))  # centipawns lost to flag a move
EVAL_CAP = 1000          # evals are clamped to +/- this so "winning -> still winning" isn't a mistake
MATE_SCORE = 10000       # centipawn value used to represent a forced mate
MAX_GAMES = 15           # hard cap per analysis run (keeps the hosted demo responsive)

# --- Storage ----------------------------------------------------------------
DB_PATH = os.getenv("CHESS_COACH_DB", "chess_coach.db")
