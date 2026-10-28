"""SQLite persistence: caches Stockfish results so re-analysing the same games is instant,
and keeps a running history of flagged moves per username.

Uses only the standard library. The database file (chess_coach.db) is gitignored.
"""
import json
import os
import sqlite3
import sys
from contextlib import closing

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

DB_PATH = config.DB_PATH


def _connect(path=None):
    return sqlite3.connect(path or DB_PATH)


def init_db(path=None):
    with closing(_connect(path)) as conn, conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS analyses (
                   game_key   TEXT NOT NULL,
                   color      TEXT NOT NULL,
                   threshold  INTEGER NOT NULL,
                   depth      INTEGER NOT NULL,
                   username   TEXT,
                   results    TEXT NOT NULL,
                   analyzed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                   PRIMARY KEY (game_key, color, threshold, depth)
               )"""
        )


class AnalysisCache:
    """Pass an instance to db.analyze_multiple_games(cache=...)."""

    def __init__(self, path=None):
        self.path = path
        init_db(path)

    def get(self, key, color, threshold, depth):
        with closing(_connect(self.path)) as conn:
            row = conn.execute(
                "SELECT results FROM analyses WHERE game_key=? AND color=? AND threshold=? AND depth=?",
                (key, color, threshold, depth),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key, color, threshold, depth, results, username=None):
        with closing(_connect(self.path)) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO analyses (game_key, color, threshold, depth, username, results) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (key, color, threshold, depth, (username or "").lower() or None, json.dumps(results)),
            )
