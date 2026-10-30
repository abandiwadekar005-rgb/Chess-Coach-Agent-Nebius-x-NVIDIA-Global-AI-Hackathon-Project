"""Drives the real Streamlit app headlessly with the model call faked."""
import os

import pytest
from streamlit.testing.v1 import AppTest

from agent import orchestrator, puzzle_gen
from data import db

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")

try:
    db.find_stockfish()
except db.EngineNotFoundError:
    pytest.skip("Stockfish binary not installed", allow_module_level=True)


@pytest.fixture(autouse=True)
def fake_model(monkeypatch):
    monkeypatch.setattr(orchestrator, "call_nemotron", lambda messages, model=None, **kw: f"REPLY from {model}")
    monkeypatch.setattr(puzzle_gen, "call_nemotron", lambda messages, model=None, **kw: "EXPLANATION")


def analyzed_app():
    at = AppTest.from_file(APP, default_timeout=120).run()
    assert not at.exception
    at.sidebar.button[0].click().run()
    assert not at.exception, at.exception
    return at


def test_first_load_shows_instructions():
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert any("Analyze my games" in i.value for i in at.info)


def test_sample_games_end_to_end():
    at = analyzed_app()
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Games analysed"] == "4"
    assert int(metrics["Mistakes flagged"]) >= 1
    assert any("REPLY from" in md.value for md in at.markdown)       # coaching report rendered
    assert len(at.tabs) == 4


def test_puzzle_check_and_reveal():
    at = analyzed_app()
    at.text_input(key="answer_0").set_value("zzzz").run()
    at.button(key="check_0").click().run()
    assert any("not a legal move" in e.value for e in at.error)       # invalid answer handled
    at.button(key="reveal_0").click().run()
    assert any(m.value == "EXPLANATION" for m in at.markdown)         # explanation shown after reveal


def test_chat_round_trip():
    at = analyzed_app()
    at.chat_input[0].set_value("What should I practise?").run()
    assert not at.exception
    assert any("REPLY from" in m.value for m in at.chat_message[-1].markdown)
