# Chess Coach Agent

**Stockfish finds your mistakes. NVIDIA Nemotron, served on Nebius Token Factory, finds the patterns behind them.**

Built for the **Nebius x NVIDIA Global AI Hackathon** (track: *Best Apps and Agents*).

Most chess tools tell you "you blundered on move 23". A coach tells you *why you keep doing it*. Chess Coach Agent replays your games with Stockfish, flags every move where you lost significant ground, then asks Nemotron to look across all of those mistakes for recurring weaknesses and turn them into a short coaching plan, training puzzles and a chat you can ask follow-up questions.

## What you can do

| Tab | What it does |
|---|---|
| **Coaching report** | Nemotron 3 Ultra reads your flagged mistakes and writes the 2-3 recurring patterns it can see, with a thing to practise for each. |
| **Your mistakes** | Every flagged move in a table, plus a board showing the position you faced: red arrow = what you played, green arrow = what Stockfish preferred. |
| **Puzzles** | Your own mistakes as puzzles. Type the move you'd play; reveal the answer and get a plain-language explanation of why it's better. |
| **Ask the coach** | Chat grounded in your actual mistakes ("Why do I keep losing in the opening?"). |

Games can come from the built-in **sample games** (no setup), an uploaded/pasted **PGN**, or a **Chess.com** / **Lichess** username (your colour is detected automatically in each game).

## How it works

```
 PGN / Chess.com / Lichess
          |
          v
  data/db.py  ------------->  Stockfish: evaluate the position before and after each of YOUR moves
          |                   flag moves that cost more than the threshold (default 1.5 pawns)
          v
   flagged moves  (position, move played, engine's best move, eval before/after, game phase)
          |
          v
  agent/orchestrator.py  --->  Nemotron 3 Ultra: find patterns across games, write the report
  agent/puzzle_gen.py    --->  Nemotron 3 Ultra: explain why the engine's move is better
  agent/orchestrator.py  --->  Nemotron (fast model): answer chat questions
          |
          v
        app.py   (Streamlit UI only)
```

**Design rule: the engine is the source of truth, the LLM is the explainer.** Stockfish decides what is a mistake and what the best move was. Nemotron is only ever given those facts and asked to explain or find patterns; the prompts forbid it from suggesting a different "best" move, so it cannot invent chess advice about which move is correct.

### How NVIDIA Nemotron and Nebius are used

- **Nemotron 3 Ultra** (550B hybrid MoE, via Nebius Token Factory) does the reasoning-heavy work: finding patterns across many mistakes and explaining puzzle solutions.
- A **smaller, faster Nemotron model** handles the conversational chat turns, so the app stays responsive and credits go further.
- **Nebius Token Factory** serves the models through an OpenAI-compatible API, so the whole integration is one small module, `inference/nebius_client.py`. It is the only file that knows about the API; model IDs are resolved against the account's live model list (case-insensitive), so a wrong guess at an ID doesn't break the app.
- The app is deployed on Streamlit Community Cloud. It does not use Nebius Serverless Endpoints or Jobs.

## Run it locally

You need **Python 3.10+**, **git**, and a **Nebius Token Factory API key**.

```bash
git clone <this repo>
cd <repo folder>
python -m venv venv
venv\Scripts\activate          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
```

**Install the Stockfish engine** (the `stockfish` pip package is only a wrapper; it needs the real binary):

- **Windows:** download from <https://stockfishchess.org/download/>, unzip, and either drop the `.exe` in the project folder or set `STOCKFISH_PATH` in `.env`.
- **macOS:** `brew install stockfish`
- **Linux:** `sudo apt install stockfish`

**Add your key:** copy `.env.example` to `.env` and set `NEBIUS_API_KEY`. (`.env` is gitignored.)

**Check the connection and find your model IDs:**

```bash
python inference/nebius_client.py --models   # lists the model IDs your key can use
python inference/nebius_client.py            # sends a test message
```

If the defaults in `config.py` don't match what your account lists, set `NEMOTRON_MODEL_ULTRA` / `NEMOTRON_MODEL_FAST` in `.env` (or change them in the app's *Advanced* panel).

**Start the app:**

```bash
streamlit run app.py
```

Pick *Sample games*, press **Analyze my games**.

## Deploy on Streamlit Community Cloud

1. Push this repo to GitHub (public).
2. At <https://share.streamlit.io>, create an app from the repo with `app.py` as the entry point.
3. Under **Advanced settings -> Secrets**, add: `NEBIUS_API_KEY = "your key"`.
4. `packages.txt` already tells Streamlit Cloud to install the Stockfish binary; the app finds it at `/usr/games/stockfish` automatically.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

The suite covers parsing, the engine's score-perspective handling (tested against a fake engine in both conventions and against real Stockfish), mistake detection for both colours, caching, Chess.com/Lichess fetching (mocked), the prompts, the Nebius client and the full UI flow. Model calls are faked, so no API key is needed. Tests that need the Stockfish binary are skipped if it isn't installed.

## Project layout

```
app.py                     Streamlit UI (no chess or AI logic)
config.py                  settings and environment variables
inference/nebius_client.py the only code that talks to Nebius Token Factory
data/db.py                 parsing, Stockfish analysis, Chess.com/Lichess fetching
data/store.py              SQLite cache of analysis results
agent/orchestrator.py      coaching report + chat prompts
agent/puzzle_gen.py        puzzle explanation prompts
samples/sample_games.pgn   four short famous games for the demo
tests/                     pytest suite
```

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `NEBIUS_API_KEY` | (required) | Token Factory key |
| `NEMOTRON_MODEL_ULTRA` | `nvidia/nemotron-3-ultra-550b-a55b` | model for reports and puzzles |
| `NEMOTRON_MODEL_FAST` | `nvidia/nemotron-3.5-lightning` | model for chat |
| `STOCKFISH_PATH` | auto-detect | path to the Stockfish binary |
| `ENGINE_DEPTH` | `12` | Stockfish search depth (higher = slower, more accurate) |
| `BLUNDER_THRESHOLD` | `150` | centipawns lost to count as a mistake (100 = one pawn) |

## Known limitations

- Standard chess only (Chess960 and other variants are skipped). Up to 15 games per run.
- Evaluations are clamped at +/-10 pawns, so moving from "winning" to "still winning" is not counted as a mistake.
- The engine depth is a trade-off: the default of 12 is fast, but a deeper search can disagree on subtle positions.
- Nemotron explains and summarises; it does not calculate. Its explanations of *why* a move is better are plausible coaching, not engine-verified analysis.

## License

[MIT](LICENSE)
