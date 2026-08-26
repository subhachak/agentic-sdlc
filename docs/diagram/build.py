"""Draw the framework as a polygon of ports.

Geometry is computed, not eyeballed: vertices from trigonometry, labels
rotated to their edge, chips placed along the outward normal. Each port is
emitted exactly once from a list extracted from the code, which is the
property an image model could not hold — the earlier attempt duplicated
BuildDeploy three times and invented a `TestProvider` that does not exist.

Two figures from one generator:

  full     one edge per port, seventeen sides. The honest shape.
  grouped  ports collected into families, eight sides. Legible at slide
           size, at the cost of the "every seam is equal" claim — which is
           why both exist rather than only the second.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import ports

# ── palette ───────────────────────────────────────────────────────────────
INK, INK2, INK3 = "#12211d", "#41544e", "#6f827c"
LINE, HAIR = "#c7d3ce", "#e0e8e5"
PAPER, RAISED, SUNK = "#ffffff", "#f4f7f6", "#eaf0ee"
ACCENT, ACCENT_SOFT = "#0e6f62", "#dceae7"
GATE, GATE_SOFT = "#9a5a12", "#f3e7d5"
EXEC_SOFT = "#eef3f8"
EXEC_LINE = "#8fa8bd"

SDLC = [
    ("Requirements intake", False), ("Requirements synthesis", False),
    ("Gate 1", True), ("Design", False), ("Gate 2", True),
    ("Implementation", False), ("QA execution", False), ("Gate 3", True),
    ("Release", False),
]

CORE = [
    ("Impact Engine", "one assessment: paths, confidence,\ntest obligations, blind spots", True),
    ("Design review", "a change may touch only\nwhat the design named", False),
    ("Change review", "what the agent actually did,\nchecked against it", False),
    ("Release gate", "required regressions must\nhave run and passed", False),
    ("Coverage & evidence", "a criterion is verified only\nby an observed run", False),
    ("Coherence checks", "configurations that build\nand cannot work", False),
    ("Snapshot & export", "the versioned projection the\nexecution plane reads", False),
    ("Reconciler", "pulls results for work\nrunning elsewhere", False),
    ("Audit trail", "every decision,\nwith its inputs", False),
]

CENTRE = [
    ("Ontology", "15 node types · 18 edge types · validated signatures"),
    ("Identity", "uuid5(type | system | external_id)"),
    ("Scope", "every read and write names its project"),
    ("Provenance", "every assertion carries how it was derived"),
    ("Truth classes", "authoritative · derived · observed · inferred"),
]


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@dataclass
class Edge:
    label: str
    chips: str
    tab: str | None
    execution: bool
    mid: tuple[float, float]
    angle: float          # degrees, along the edge
    normal: tuple[float, float]
    a: tuple[float, float]
    b: tuple[float, float]


def polygon(n: int, r: float, cx: float, cy: float) -> list[tuple[float, float]]:
    """Vertices, starting at the top and going clockwise.

    Offset by half a step so an *edge* is centred at the top rather than a
    vertex — the labels live on edges, and a vertex at twelve o'clock puts
    two half-labels there instead of one whole one.
    """
    step = 2 * math.pi / n
    start = -math.pi / 2 - step / 2
    return [(cx + r * math.cos(start + i * step), cy + r * math.sin(start + i * step))
            for i in range(n)]


def edges_of(names: list[str], chips: dict, tabs: dict, execution: set,
             r: float, cx: float, cy: float) -> list[Edge]:
    pts = polygon(len(names), r, cx, cy)
    out = []
    for i, name in enumerate(names):
        a, b = pts[i], pts[(i + 1) % len(names)]
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        angle = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        # Never upside down. Adding 180 once is not enough — it can land
        # outside the range again — so normalise into (-180, 180] first and
        # then fold into (-90, 90].
        angle = (angle + 180) % 360 - 180
        if angle > 90:
            angle -= 180
        elif angle <= -90:
            angle += 180
        length = math.hypot(mx - cx, my - cy) or 1
        out.append(Edge(name, chips.get(name, ""), tabs.get(name), name in execution,
                        (mx, my), angle, ((mx - cx) / length, (my - cy) / length), a, b))
    return out


def wrap(text: str, width: int) -> list[str]:
    """Greedy wrap that refuses to leave one word alone on the last line.

    "in-process agent · client's design agent" broke to a final line of just
    "agent", twice on the same figure. An orphan reads as a stray label
    rather than as the tail of the line above it.
    """
    words, lines, line = text.split(), [], ""
    for w in words:
        if len(line) + len(w) + 1 > width and line:
            lines.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        lines.append(line)

    if len(lines) > 1 and len(lines[-1].split()) == 1:
        # Pull a word down from the line above so the last one is not alone.
        head = lines[-2].split()
        if len(head) > 1:
            lines[-2] = " ".join(head[:-1])
            lines[-1] = f"{head[-1]} {lines[-1]}"
    return lines


def render(names, chips, tabs, execution, *, size, r_poly, r_sdlc_out, r_sdlc_in,
           r_core_out, r_centre, port_px, chip_px, title) -> str:
    cx = cy = size / 2
    edges = edges_of(names, chips, tabs, execution, r_poly, cx, cy)
    o: list[str] = []
    add = o.append

    add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'width="{size}" height="{size}" font-family="Inter, ui-sans-serif, system-ui, sans-serif" '
        f'role="img" aria-label="{esc(title)}">')
    add(f'<rect width="{size}" height="{size}" fill="{PAPER}"/>')

    # ── bands, painted outside in so each sits on the last ────────────────
    pts = polygon(len(names), r_poly, cx, cy)
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    add(f'<polygon points="{poly}" fill="{RAISED}" stroke="{LINE}" stroke-width="2"/>')
    # Outer first, then punch the middle back out — filling the *inner*
    # radius tints everything inside the ring instead of the ring itself,
    # which leaves the band invisible and the zones indistinguishable.
    add(f'<circle cx="{cx}" cy="{cy}" r="{r_sdlc_out}" fill="{SUNK}" stroke="{LINE}"/>')
    add(f'<circle cx="{cx}" cy="{cy}" r="{r_sdlc_in}" fill="{PAPER}" stroke="{LINE}"/>')

    # ── each edge: the port ───────────────────────────────────────────────
    for e in edges:
        if e.execution:
            add(f'<line x1="{e.a[0]:.1f}" y1="{e.a[1]:.1f}" x2="{e.b[0]:.1f}" y2="{e.b[1]:.1f}" '
                f'stroke="{EXEC_LINE}" stroke-width="6"/>')
            add(f'<line x1="{e.a[0]:.1f}" y1="{e.a[1]:.1f}" x2="{e.b[0]:.1f}" y2="{e.b[1]:.1f}" '
                f'stroke="{PAPER}" stroke-width="2"/>')
        else:
            add(f'<line x1="{e.a[0]:.1f}" y1="{e.a[1]:.1f}" x2="{e.b[0]:.1f}" y2="{e.b[1]:.1f}" '
                f'stroke="{INK2}" stroke-width="2.5"/>')

        mx, my = e.mid
        inx, iny = -e.normal[0], -e.normal[1]
        lx, ly = mx + inx * 16, my + iny * 16
        add(f'<g transform="translate({lx:.1f},{ly:.1f}) rotate({e.angle:.1f})">'
            f'<text text-anchor="middle" font-size="{port_px}" font-weight="600" '
            f'letter-spacing="0.4" fill="{INK}">{esc(e.label)}</text></g>')

        if e.tab:
            tx, ty = mx + e.normal[0] * 13, my + e.normal[1] * 13
            add(f'<g transform="translate({tx:.1f},{ty:.1f}) rotate({e.angle:.1f})">'
                f'<rect x="-58" y="-9" width="116" height="15" rx="7.5" fill="none" '
                f'stroke="{INK3}" stroke-width="1" stroke-dasharray="3 2"/>'
                f'<text text-anchor="middle" y="2" font-size="9" fill="{INK3}">'
                f'{esc(e.tab)}</text></g>')

        # chips, horizontal and anchored away from the centre
        ox, oy = mx + e.normal[0] * 30, my + e.normal[1] * 30
        anchor = "start" if e.normal[0] > 0.12 else ("end" if e.normal[0] < -0.12 else "middle")
        lines = wrap(e.chips, 34)
        for i, text in enumerate(lines):
            dy = oy + (i - (len(lines) - 1) / 2) * (chip_px + 3)
            add(f'<text x="{ox:.1f}" y="{dy:.1f}" text-anchor="{anchor}" font-size="{chip_px}" '
                f'fill="{INK3}">{esc(text)}</text>')

    # ── the SDLC cycle ────────────────────────────────────────────────────
    r_mid = (r_sdlc_out + r_sdlc_in) / 2
    for i, (label, is_gate) in enumerate(SDLC):
        a = -math.pi / 2 + i * (2 * math.pi / len(SDLC))
        px, py = cx + r_mid * math.cos(a), cy + r_mid * math.sin(a)
        deg = (math.degrees(a) + 90 + 180) % 360 - 180
        if deg > 90:
            deg -= 180
        elif deg <= -90:
            deg += 180
        if is_gate:
            half = (r_sdlc_out - r_sdlc_in) / 2
            add(f'<g transform="translate({px:.1f},{py:.1f}) rotate({math.degrees(a):.1f})">'
                f'<rect x="-{half:.0f}" y="-{half:.0f}" width="{half * 2:.0f}" '
                f'height="{half * 2:.0f}" fill="{GATE_SOFT}" stroke="{GATE}" stroke-width="1.5"/>'
                f'</g>')
        add(f'<g transform="translate({px:.1f},{py:.1f}) rotate({deg:.1f})">'
            f'<text text-anchor="middle" y="4" font-size="{port_px + 1}" '
            f'font-weight="{"700" if is_gate else "500"}" '
            f'fill="{GATE if is_gate else INK}">{esc(label)}</text></g>')

    # ── the deterministic core ────────────────────────────────────────────
    # Placed toward the band's outer edge rather than at its midpoint. Nine
    # labels on a small radius have too little arc between them: at the
    # midpoint "Coherence checks" and "Coverage & evidence" ran into each
    # other at the bottom of the octagon, where the circumference is
    # shortest in absolute terms.
    r_core_mid = r_core_out - 62
    for i, (name, blurb, big) in enumerate(CORE):
        a = -math.pi / 2 + i * (2 * math.pi / len(CORE))
        px, py = cx + r_core_mid * math.cos(a), cy + r_core_mid * math.sin(a)
        fill = ACCENT if big else INK
        add(f'<text x="{px:.1f}" y="{py:.1f}" text-anchor="middle" '
            f'font-size="{port_px + (2 if big else 0)}" font-weight="{"700" if big else "600"}" '
            f'fill="{fill}">{esc(name)}</text>')
        for j, line in enumerate(blurb.split("\n")):
            add(f'<text x="{px:.1f}" y="{py + 13 + j * 11:.1f}" text-anchor="middle" '
                f'font-size="{chip_px}" fill="{INK3}">{esc(line)}</text>')

    # ── the centre ────────────────────────────────────────────────────────
    add(f'<circle cx="{cx}" cy="{cy}" r="{r_centre}" fill="{ACCENT_SOFT}" '
        f'stroke="{ACCENT}" stroke-width="2"/>')
    # Vertically centred rather than hung from the top: anchoring at the top
    # of a circle leaves the bottom third empty, which reads as a mistake.
    closing = wrap("an LLM inference must never be indistinguishable "
                   "from a compiler-derived fact", 46)
    block = (port_px + 12) + len(CENTRE) * 34 + len(closing) * (chip_px + 3) + 10
    y = cy - block / 2 + port_px + 6
    add(f'<text x="{cx}" y="{y}" text-anchor="middle" font-size="{port_px + 6}" '
        f'font-weight="700" fill="{ACCENT}">Context Graph &amp; Ontology</text>')
    y += 30
    for name, blurb in CENTRE:
        add(f'<text x="{cx}" y="{y}" text-anchor="middle" font-size="{port_px}" '
            f'font-weight="600" fill="{INK}">{esc(name)}</text>')
        add(f'<text x="{cx}" y="{y + 14}" text-anchor="middle" font-size="{chip_px + 1}" '
            f'fill="{INK2}">{esc(blurb)}</text>')
        y += 34
    y += 8
    for line in closing:
        add(f'<text x="{cx}" y="{y}" text-anchor="middle" font-size="{chip_px + 1}" '
            f'font-style="italic" fill="{ACCENT}">{esc(line)}</text>')
        y += chip_px + 3

    add('</svg>')
    return "\n".join(o)
