"""The only module that talks to Nebius Token Factory.

Everything else calls `call_nemotron(messages)`; nothing else imports `openai` or touches the key.

Run it directly to test the connection:
    python inference/nebius_client.py            # sends a hello message
    python inference/nebius_client.py --models   # lists the model IDs your key can use
"""
import os
import re
import sys
from functools import lru_cache

# Allow `python inference/nebius_client.py` (script mode) as well as `python -m inference.nebius_client`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai import OpenAI  # noqa: E402

import config  # noqa: E402


class NebiusError(RuntimeError):
    """Raised for configuration or API problems, with a message safe to show to the user."""


@lru_cache(maxsize=1)
def _get_client():
    key = os.getenv(config.NEBIUS_API_KEY_ENV, "").strip()
    if not key:
        raise NebiusError(
            f"{config.NEBIUS_API_KEY_ENV} is not set. Put it in your .env file locally, "
            "or in the app's Secrets on Streamlit Cloud."
        )
    return OpenAI(base_url=config.NEBIUS_BASE_URL, api_key=key, timeout=120, max_retries=2)


@lru_cache(maxsize=1)
def list_models():
    """Return the model IDs this key can use (empty list if the call fails)."""
    try:
        return sorted(m.id for m in _get_client().models.list().data)
    except NebiusError:
        raise
    except Exception:
        return []


def resolve_model_id(name):
    """Match `name` against the account's real model IDs, ignoring case.

    Falls back to `name` unchanged if the list is unavailable or nothing matches,
    so a wrong guess produces the API's own "model not found" error rather than ours.
    """
    available = list_models()
    lowered = name.lower()
    for model_id in available:
        if model_id.lower() == lowered:
            return model_id
    tail = lowered.split("/")[-1]
    tail_matches = [m for m in available if m.lower().split("/")[-1] == tail]
    return tail_matches[0] if len(tail_matches) == 1 else name


def _clean(text):
    """Strip <think>...</think> blocks some reasoning models include in their output."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def call_nemotron(messages, model=None, max_tokens=4096, temperature=0.3):
    """Send a chat `messages` list to Nemotron and return the reply text.

    `model` defaults to Nemotron 3 Ultra. Reasoning models may put their answer in
    `content` and their thinking in `reasoning_content`; we prefer the answer and only
    fall back to the reasoning text if the answer is empty.
    """
    client = _get_client()
    model_id = resolve_model_id(model or config.MODEL_ULTRA)
    try:
        response = client.chat.completions.create(
            model=model_id,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except Exception as exc:  # network, auth, unknown model...
        raise NebiusError(f"Nebius request failed for model '{model_id}': {exc}") from exc

    message = response.choices[0].message
    text = message.content or getattr(message, "reasoning_content", None) or getattr(message, "reasoning", None)
    if not text:
        raise NebiusError(f"Model '{model_id}' returned an empty response.")
    return _clean(text)


if __name__ == "__main__":
    try:
        if "--models" in sys.argv:
            models = list_models()
            print("\n".join(models) if models else "No models returned (check your key).")
        else:
            reply = call_nemotron([{"role": "user", "content": "Say hello in one sentence."}], max_tokens=256)
            print(f"Response: {reply}")
    except NebiusError as exc:
        print(f"Error: {exc}")
        sys.exit(1)
