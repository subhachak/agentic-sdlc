"""Static checks on agent-generated Playwright specs before they touch disk.

The threat: PR diffs are untrusted input, they are fed to an LLM, and the
LLM's output is written out as TypeScript and executed on a runner that
holds an API key. A comment in a source file can carry instructions to the
generation agent.

This is defense in depth, not a sandbox — it is a text scan, and a
determined author can phrase around it. The structural control is the
privilege split in .github/workflows/agentic-qa.yml: the job that executes
these specs holds no write token, and the job that writes to GitHub
executes none of this code.
"""
from __future__ import annotations

import re

ALLOWED_IMPORTS = {"@playwright/test"}

_IMPORT_FROM = re.compile(r"""(?m)^\s*import\b[^;\n]*?\bfrom\s*['"]([^'"]+)['"]""")
_IMPORT_BARE = re.compile(r"""(?m)^\s*import\s*['"]([^'"]+)['"]""")

# (pattern, why it is refused)
_BANNED = [
    (re.compile(r"\bprocess\s*\.\s*env\b"), "reads environment variables (the runner holds an API key)"),
    (re.compile(r"\brequire\s*\("), "uses require() to load a module outside the import allowlist"),
    (re.compile(r"(?<![.\w])import\s*\("), "uses a dynamic import()"),
    (re.compile(r"\bchild_process\b|\bexecSync\b|\bspawnSync\b|\bspawn\s*\("), "starts a subprocess"),
    (re.compile(r"""\bnode:(?:fs|os|net|http|https|dns|dgram|vm|worker_threads)\b"""), "uses a Node builtin"),
    (re.compile(r"\beval\s*\("), "calls eval()"),
    (re.compile(r"\bnew\s+Function\s*\("), "builds code with new Function()"),
    (re.compile(r"(?<![.\w])fetch\s*\("), "makes a raw network call (use the Playwright `request` fixture)"),
    (re.compile(r"\bXMLHttpRequest\b|\bWebSocket\b"), "opens its own network transport"),
]


def validate_spec(code: str) -> list[str]:
    """Return a list of reasons the spec must not be executed. Empty means OK."""
    violations: list[str] = []

    for match in list(_IMPORT_FROM.finditer(code)) + list(_IMPORT_BARE.finditer(code)):
        module = match.group(1)
        if module not in ALLOWED_IMPORTS:
            violations.append(f"imports {module!r}, which is not in the allowlist {sorted(ALLOWED_IMPORTS)}")

    for pattern, why in _BANNED:
        if pattern.search(code):
            violations.append(why)

    if not re.search(r"\btest\s*\(", code):
        violations.append("declares no Playwright test()")

    # Preserve order but drop repeats, so one spec importing two bad modules
    # does not produce the same sentence twice.
    return list(dict.fromkeys(violations))
