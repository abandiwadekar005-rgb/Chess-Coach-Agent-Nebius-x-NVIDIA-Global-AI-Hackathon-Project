"""Tests for the Nebius client, orchestrator and puzzle prompts. No network: the model call is faked."""
from types import SimpleNamespace

import pytest

import config
from agent import orchestrator, puzzle_gen
from inference import nebius_client

MOVE = {
    "game": "Alice vs Bob", "color": "black", "move_number": 3, "fen": "rnbqkbnr/pppp1ppp/8/4p3/2B1P3/8/PPPP1PPP/RNBQK1NR b KQkq - 1 2",
    "move": "g8f6", "move_san": "Nf6", "best_move": "g7g6", "best_move_san": "g6",
    "eval_before": 29, "eval_after": -1000, "eval_loss": 1029, "phase": "opening",
}


@pytest.fixture
def fake_model(monkeypatch):
    calls = []

    def fake(messages, model=None, **kw):
        calls.append({"messages": messages, "model": model})
        return "FAKE REPLY"

    monkeypatch.setattr(orchestrator, "call_nemotron", fake)
    monkeypatch.setattr(puzzle_gen, "call_nemotron", fake)
    return calls


def test_summary_uses_ultra_and_includes_the_evidence(fake_model):
    assert orchestrator.generate_summary([MOVE]) == "FAKE REPLY"
    call = fake_model[0]
    assert call["model"] == config.MODEL_ULTRA
    text = " ".join(m["content"] for m in call["messages"])
    assert "Nf6" in text and "g6" in text and "opening" in text and "Alice vs Bob" in text


def test_empty_summary_makes_no_api_call(fake_model):
    assert "No significant mistakes" in orchestrator.generate_summary([])
    assert fake_model == []


def test_summary_prompt_is_bounded():
    many = [dict(MOVE, eval_loss=200 + i) for i in range(500)]
    prompt = orchestrator.build_summary_prompt(many)[1]["content"]
    assert prompt.count("played Nf6") == orchestrator.MAX_MOVES_IN_PROMPT


def test_chat_uses_fast_model_and_keeps_history(fake_model):
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    orchestrator.chat("What should I practise?", history, [MOVE], summary="Earlier report")
    call = fake_model[0]
    assert call["model"] == config.MODEL_FAST
    roles = [m["role"] for m in call["messages"]]
    assert roles == ["system", "user", "assistant", "user"]
    assert "Earlier report" in call["messages"][0]["content"]
    assert call["messages"][-1]["content"] == "What should I practise?"


def test_puzzle_prompt_treats_engine_move_as_ground_truth(fake_model):
    assert puzzle_gen.generate_puzzle(MOVE) == "FAKE REPLY"
    system, user = fake_model[0]["messages"]
    assert "ground truth" in system["content"] and "Do NOT suggest any other best" in system["content"]
    assert "Engine's best move: g6" in user["content"] and "Side to move: Black" in user["content"]


def test_puzzle_without_engine_move_does_not_call_model(fake_model):
    assert "No engine suggestion" in puzzle_gen.generate_puzzle(dict(MOVE, best_move_san=None))
    assert fake_model == []


# --- nebius_client ------------------------------------------------------------
def test_missing_key_gives_clear_error(monkeypatch):
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    nebius_client._get_client.cache_clear()
    with pytest.raises(nebius_client.NebiusError, match="NEBIUS_API_KEY"):
        nebius_client.call_nemotron([{"role": "user", "content": "hi"}])
    nebius_client._get_client.cache_clear()


def test_resolve_model_id_is_case_insensitive(monkeypatch):
    monkeypatch.setattr(nebius_client, "list_models", lambda: ["nvidia/Nemotron-3-Ultra-550b-a55b", "other/model"])
    assert nebius_client.resolve_model_id("nvidia/nemotron-3-ultra-550b-a55b") == "nvidia/Nemotron-3-Ultra-550b-a55b"
    assert nebius_client.resolve_model_id("something/else") == "something/else"   # unknown: passed through


def _client_returning(content=None, reasoning=None):
    message = SimpleNamespace(content=content, reasoning_content=reasoning)
    create = lambda **kw: SimpleNamespace(choices=[SimpleNamespace(message=message)])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


@pytest.mark.parametrize("content,reasoning,expected", [
    ("The answer", "my thinking", "The answer"),                 # answer preferred over reasoning
    (None, "only reasoning", "only reasoning"),                  # fallback
    ("<think>hidden</think>Visible", None, "Visible"),           # think tags stripped
])
def test_call_nemotron_reply_selection(monkeypatch, content, reasoning, expected):
    monkeypatch.setattr(nebius_client, "_get_client", lambda: _client_returning(content, reasoning))
    monkeypatch.setattr(nebius_client, "list_models", lambda: [])
    assert nebius_client.call_nemotron([{"role": "user", "content": "x"}]) == expected


def test_empty_model_reply_raises(monkeypatch):
    monkeypatch.setattr(nebius_client, "_get_client", lambda: _client_returning(None, None))
    monkeypatch.setattr(nebius_client, "list_models", lambda: [])
    with pytest.raises(nebius_client.NebiusError, match="empty"):
        nebius_client.call_nemotron([{"role": "user", "content": "x"}])
