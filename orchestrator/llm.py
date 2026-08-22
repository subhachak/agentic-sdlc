"""Thin wrapper around the Anthropic client, shared by every agent node.

Kept deliberately small: nodes call `ask_json` with a system prompt and a
user payload and get back parsed JSON. All gate/scoring logic stays out of
here on purpose — see nodes/gate.py and nodes/test_plan.py for the
deterministic checks. This file never decides readiness, it only proposes.
"""
from __future__ import annotations

import json
import os

import anthropic

_MODEL = os.environ.get("QA_AGENT_MODEL", "claude-sonnet-4-6")

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def ask_json(system: str, user: str, max_tokens: int = 4000) -> dict:
    """Send a prompt, require a JSON object back, parse and return it.

    Raises on malformed output rather than guessing — a node that can't
    parse its own agent's output should fail loudly, not silently pass
    something malformed downstream.
    """
    client = _get_client()
    resp = client.messages.create(
        model=_MODEL,
        max_tokens=max_tokens,
        system=system + "\n\nRespond with ONLY a JSON object. No prose, no markdown fences.",
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(block.text for block in resp.content if block.type == "text").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)
