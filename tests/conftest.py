import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Tests must never touch the real database or a real API key.
os.environ["CHESS_COACH_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["NEBIUS_API_KEY"] = "test-key-not-real"
