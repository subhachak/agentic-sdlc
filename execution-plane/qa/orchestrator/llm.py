"""Thin wrapper around the Anthropic client, shared by every agent node.

Kept deliberately small: nodes call `ask` with a system prompt, a user
payload, and the Pydantic shape they expect back. All gate/scoring logic
stays out of here on purpose — see nodes/gate.py and nodes/test_plan.py for
the deterministic checks. This file never decides readiness, it only
proposes.
"""
from __future__ import annotations

import os
from typing import TypeVar

import anthropic
from pydantic import BaseModel

_MODEL = os.environ.get("QA_AGENT_MODEL", "claude-opus-5")

# Safety classifiers can decline a request outright. With server-side
# fallbacks the API reroutes those by refusal category instead of handing
# back an unusable turn, which matters here because the model is reading
# arbitrary PR diffs.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

T = TypeVar("T", bound=BaseModel)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. In GitHub Actions this usually means the "
                "workflow ran without repository secrets — pull requests from forks do "
                "not receive them."
            )
        _client = anthropic.Anthropic(api_key=key, max_retries=5, timeout=120.0)
    return _client


def ask(system: str, user: str, schema: type[T], max_tokens: int = 16000) -> T:
    """Send a prompt and get back a validated instance of `schema`.

    Raises with a readable message rather than guessing — a node that cannot
    trust its own agent's output should fail loudly, not pass something
    malformed downstream.
    """
    client = _get_client()

    try:
        resp = client.beta.messages.parse(
            model=_MODEL,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=schema,
            betas=[_FALLBACK_BETA],
            fallbacks="default",
        )
    except anthropic.NotFoundError as exc:
        raise RuntimeError(f"model {_MODEL!r} is not available to this API key") from exc
    except anthropic.RateLimitError as exc:
        raise RuntimeError("rate limited by the Anthropic API after retries") from exc
    except anthropic.APIStatusError as exc:
        raise RuntimeError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise RuntimeError("could not reach the Anthropic API") from exc

    if resp.stop_reason == "refusal":
        detail = getattr(resp.stop_details, "explanation", None) or "no explanation given"
        raise RuntimeError(f"the model declined this request: {detail}")

    if resp.parsed_output is None:
        raise RuntimeError("the model returned no parsable output")

    return resp.parsed_output
