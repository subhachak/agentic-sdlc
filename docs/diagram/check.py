"""What went wrong when a model drew this, checked mechanically.

Gemini's attempt duplicated BuildDeploy three times, TestRunner and
TestManagement twice each, invented a `TestProvider` that is not a port,
attached RequirementsSource's implementations to EntityResolver's label, and
lost RequirementsSource entirely. None of that is a rendering problem — it
is a bookkeeping problem, and bookkeeping is checkable.
"""
from __future__ import annotations

import pathlib
import re
import sys

import ports

FAILURES: list[str] = []


def check(path: pathlib.Path, expected: list[str], label: str) -> None:
    svg = path.read_text()
    texts = re.findall(r">([^<>]+)</text>", svg)

    for name in expected:
        n = sum(1 for t in texts if t.strip() == name)
        if n == 0:
            FAILURES.append(f"{label}: {name} is missing")
        elif n > 1:
            FAILURES.append(f"{label}: {name} appears {n} times")

    # Nothing that is not a real port may be drawn as one.
    known = set(ports.discovered()) | {n for n, _ in ports.FAMILIES}
    for t in texts:
        word = t.strip()
        if re.fullmatch(r"[A-Z][A-Za-z]+(?:[A-Z][A-Za-z]+)+", word) and word not in known:
            FAILURES.append(f"{label}: {word!r} looks like a port and is not one")

    # Whole wrapped lines, not substrings. Matching on a substring flags
    # "SQLite" in ContextGraphStore against "SQLite" in AuditSink — two ports
    # legitimately offering the same implementation is not a duplicate.
    import build

    for name, chips in ports.CHIPS.items():
        if name not in expected:
            continue
        for line in build.wrap(chips, 34):
            # Very short fragments repeat legitimately across ports.
            n = sum(1 for t in texts if t.strip() == line)
            if n > 1 and len(line) >= 10:
                FAILURES.append(
                    f"{label}: {name}'s chip line {line!r} is drawn {n} times"
                )


check(pathlib.Path("framework-17.svg"), ports.required(), "17-gon")
check(pathlib.Path("framework-8.svg"), [n for n, _ in ports.FAMILIES], "octagon")

if FAILURES:
    print("\n".join(f"  {f}" for f in FAILURES))
    sys.exit(1)
print("  both figures: every label once, nothing invented, nothing missing")
