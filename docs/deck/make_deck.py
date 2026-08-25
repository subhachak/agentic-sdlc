import sys
sys.path.insert(0, "/private/tmp/claude-501/-Users-subh-MyApps-agentic-sdlc/722f1229-c43d-4145-9de5-d6483e0de576/scratchpad")
from build_deck import *

prs = deck()

# ── 1 · title ────────────────────────────────────────────────────────────────
s = blank(prs, WHITE)
rule(s, Inches(2.55), TEAL, 3.0, x=M, w=Inches(2.2))
text(s, M, Inches(2.85), Inches(10.5), Inches(2.2), [
    ("Agentic SDLC Platform", 46, True, INK, 10),
    ("Letting AI agents do delivery work, without giving up control of what ships.",
     19, False, INK2, 0),
], spacing=1.05)
text(s, M, Inches(5.9), Inches(10.5), Inches(0.9), [
    ("Engineering leadership briefing   ·   Reference implementation complete   ·   "
     "Controls measured, not asserted", 12, False, MUTED, 0)])
notes(s, "Twelve slides, fifteen minutes. The argument is: agents make delivery faster "
         "and make it unauditable, and we have built the part that keeps it auditable. "
         "The evidence slide in the middle is the one that matters — it is where we say "
         "we tested our own claims and several failed.")

# ── 2 · the problem ──────────────────────────────────────────────────────────
s = blank(prs)
eyebrow(s, "The problem")
title(s, "An agent breaks the four things a delivery pipeline assumes")
table(s, M, Inches(2.5), CONTENT_W, [
    ["A pipeline assumes", "An agent does", "So you lose"],
    ["The same input gives the same output", "Different output every time", "The ability to replay or regression-test the pipeline"],
    ["Changes have a bounded blast radius", "Edits whatever looks relevant", "Containment — review effort grows with output"],
    ["Why something happened is recorded", "Reasoning is not an artifact", "The answer to “why did this ship”"],
    ["Failures are loud", "Produces confident wrong answers", "Early warning — it surfaces when expensive"],
], [0.28, 0.28, 0.44], row_h=Inches(0.66))
text(s, M, Inches(6.25), CONTENT_W, Inches(0.6), [
    ("Every control we built maps to one of these four rows. The fourth is the dangerous one.",
     14, True, INK2, 0)])
notes(s, "Do not frame this as a compliance problem. It is an engineering one: a pipeline "
         "that fails loudly is fine, one that ships a confident wrong answer is not. "
         "Row 2 — blast radius — is where most of our effort has gone, because it is the "
         "one we can now put a number against.")

# ── 3 · the principle ────────────────────────────────────────────────────────
s = blank(prs, WHITE)
eyebrow(s, "The governing principle")
text(s, M, Inches(2.1), Inches(11.0), Inches(2.4), [
    ("No model is ever in a position\nto approve its own work.", 40, True, INK, 16),
], spacing=1.12)
rule(s, Inches(4.7), TEAL, 2.5, x=M, w=Inches(1.6))
text(s, M, Inches(5.0), Inches(10.6), Inches(1.4), [
    ("Every yes/no decision in the system is made by code a person can read, or by a person "
     "whose name is recorded. Agents propose. They never decide.", 17, False, INK2, 0)])
notes(s, "If they remember one sentence, this is it. It also answers the question every "
         "risk function asks first, before they ask it.")

# ── 4 · how it works ─────────────────────────────────────────────────────────
s = blank(prs)
eyebrow(s, "How it works")
title(s, "Three roles, and only one of them is a model")
bands = [
    (TEAL_SOFT, TEAL, "Agents propose",
     "A design, a change, a test plan, a test.\nOurs or the client's own agent."),
    (WHITE, LINE, "Deterministic code decides",
     "Does every file named exist? Is the change inside\nthe approved scope? Did the required tests run and pass?"),
    (AMBER_SOFT, AMBER, "People approve what carries risk",
     "Three gates, each recorded against a named person."),
]
y = Inches(2.45)
for fill, border, head, body in bands:
    card(s, M, y, CONTENT_W, Inches(1.25), fill=fill, border=border, width=1.5)
    text(s, M + Inches(0.35), y + Inches(0.2), Inches(4.2), Inches(0.9),
         [(head, 20, True, INK, 0)], anchor=MSO_ANCHOR.MIDDLE)
    text(s, M + Inches(4.8), y + Inches(0.2), Inches(6.4), Inches(0.9),
         [(body, 13, False, INK2, 0)], anchor=MSO_ANCHOR.MIDDLE)
    y += Inches(1.5)
text(s, M, Inches(6.85), CONTENT_W, Inches(0.5), [
    ("The middle band is the product. It is the only part that cannot be swapped out.",
     14, True, INK2, 0)])
notes(s, "Keep this simple. The middle band is what we sell — the top band is increasingly "
         "the client's own agent, and the bottom is their existing approval culture.")

# ── 5 · what we can prove ────────────────────────────────────────────────────
s = blank(prs)
eyebrow(s, "Evidence")
title(s, "What we can now prove", "Each figure produced by a harness in the repository, not by assertion.")
table(s, M, Inches(2.6), CONTENT_W, [
    ["Claim", "Measured", "How"],
    ["We read the codebase accurately", "0 of 605 imports missed", "Compared against the language's own parser"],
    ["We resolve nearly all of it", "99.3% captured, 0 dropped", "Four counts that sum to the total"],
    ["Our impact analysis beats doing nothing", "1.4× the precision at 45% of the noise", "240 held-out cases from real commits"],
    ["Coverage claims are true", "Reconciled every run", "What each test actually requested"],
    ["Our tests catch real regressions", "3 of 3 deliberate bugs caught", "Mutation testing"],
], [0.34, 0.28, 0.38], row_h=Inches(0.62))
notes(s, "The point of this slide is not the individual numbers. It is that each one is "
         "produced by code that runs on demand, so it can be re-run in front of a client "
         "and it degrades visibly if we regress.")

# ── 6 · what measuring told us ───────────────────────────────────────────────
s = blank(prs)
eyebrow(s, "Credibility")
title(s, "We tested our own controls. Four were not working.")
table(s, M, Inches(2.45), CONTENT_W, [
    ["We had claimed", "Measurement found", "Now"],
    ["Our impact analysis was well tuned", "It scored below a do-nothing baseline", "Retuned; the table sits beside the code"],
    ["Our dependency data could not be wrong", "19 connections silently dropped", "Reported honestly — 99.3% captured"],
    ["Test scoping used derived data", "It read a hand-maintained file", "Generated, and pinned to a commit"],
    ["Our tests covered what they claimed", "None of the claims were right", "Measured from what each run did"],
], [0.30, 0.34, 0.36], row_h=Inches(0.66))
card(s, M, Inches(5.75), CONTENT_W, Inches(1.05), fill=CRIT_SOFT, border=CRIT, width=1.5)
text(s, M + Inches(0.35), Inches(5.95), CONTENT_W - Inches(0.7), Inches(0.7), [
    ("This slide is the reason to believe the previous one. We found these by building the "
     "thing that checks — not in a client engagement.", 15, True, INK, 0)],
     anchor=MSO_ANCHOR.MIDDLE)
notes(s, "Do not soften this and do not skip it. Four claims in an earlier version of this "
         "deck were false. Presenting that deliberately is what separates us from a demo, "
         "and every experienced engineer in the room will recognise it.")

# ── 7 · the mutation ─────────────────────────────────────────────────────────
s = blank(prs, WHITE)
eyebrow(s, "Why scoped testing matters")
title(s, "We broke the API on purpose. Only one test noticed.")
rows = [("Claims list renders", "passed", MUTED),
        ("Filter behaviour  (3 tests)", "passed", MUTED),
        ("API contract test", "FAILED", CRIT)]
y = Inches(2.6)
for label, result, colour in rows:
    card(s, M, y, Inches(8.6), Inches(0.78), fill=WHITE,
         border=CRIT if colour == CRIT else LINE, width=1.5 if colour == CRIT else 1.0)
    text(s, M + Inches(0.35), y, Inches(6.0), Inches(0.78),
         [(label, 16, colour == CRIT, INK, 0)], anchor=MSO_ANCHOR.MIDDLE)
    text(s, M + Inches(6.6), y, Inches(1.8), Inches(0.78),
         [(result, 14, True, colour, 0)], align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)
    y += Inches(0.95)
text(s, M, Inches(5.7), Inches(11.2), Inches(1.3), [
    ("Every user-facing test passed, because the page happens to send the exact value the "
     "broken code still accepted.", 16, False, INK2, 8),
    ("Without scoped testing, that release is green and the change breaks every other caller.",
     16, True, INK, 0)])
notes(s, "This is the most persuasive slide for a technical sceptic and the clearest for a "
         "non-technical one. It is not hypothetical — we introduced the bug and this is what "
         "happened. It is also exactly the failure mode the whole approach exists to catch: "
         "the damage is not where you changed the code.")

# ── 8 · fits any stack ───────────────────────────────────────────────────────
s = blank(prs)
eyebrow(s, "Portability")
title(s, "Three clients with nothing in common, one platform underneath")
clients = [
    ("Product organisation", ["Jira", "GitHub + Actions", "Their Copilot agent", "Model via our tenancy"]),
    ("Enterprise IT", ["Azure DevOps", "ADO Pipelines", "Our agents", "Model in their cloud"]),
    ("Regulated", ["ServiceNow", "Jenkins", "Their agents throughout", "We hold no model key"]),
]
cw = (CONTENT_W - Inches(0.6)) / 3
for i, (name, stack) in enumerate(clients):
    x = M + i * (cw + Inches(0.3))
    # Deliberately colourless. Amber means "needs care" on slides 4 and 9, and a
    # client's choice of tooling is not a warning. The dashed edge already says
    # "interchangeable"; leaving these neutral makes the teal core below the only
    # saturated thing on the slide, which is the argument.
    card(s, x, Inches(2.45), cw, Inches(2.5), fill=WHITE, border=LINE, width=1.5, dash=True)
    text(s, x + Inches(0.3), Inches(2.65), cw - Inches(0.6), Inches(0.4),
         [(name, 15, True, INK, 8)])
    text(s, x + Inches(0.3), Inches(3.15), cw - Inches(0.6), Inches(1.6),
         [(l, 13, False, INK2, 5) for l in stack], spacing=1.2)
card(s, M, Inches(5.3), CONTENT_W, Inches(1.2), fill=TEAL_SOFT, border=TEAL, width=2.0)
text(s, M, Inches(5.3), CONTENT_W, Inches(1.2), [
    ("One platform core — identical for all three", 20, True, INK, 4),
    ("A new client is a set of connectors and a configuration record. It is not a new version "
     "of the product.", 13, False, INK2, 0)], align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
notes(s, "The third column is the interesting one commercially: that client's agents do all "
         "the AI work and we hold none of their model credentials. It is a settings change, "
         "not a bespoke build — which is what makes this an accelerator rather than a project.")

# ── 9 · where it stands ──────────────────────────────────────────────────────
s = blank(prs)
eyebrow(s, "Status")
title(s, "Where it stands today")
groups = [
    (TEAL, "Working, end to end",
     "Design · Implementation · Test scoping · Test generation\nExecution · Evidence · Release gate"),
    (AMBER, "Partial",
     "Requirements intake · Test-case management\nDeployment (records what shipped; does not deploy)"),
    (MUTED, "Proven once, with a live model",
     "Requirement → design → approval → code → scoped tests → release,\nagainst a real application producing real evidence"),
]
y = Inches(2.45)
for colour, head, body in groups:
    rule(s, y, colour, 3.0, x=M, w=Inches(0.55))
    text(s, M + Inches(0.85), y - Inches(0.12), Inches(4.0), Inches(0.5),
         [(head, 18, True, INK, 0)])
    text(s, M + Inches(5.2), y - Inches(0.14), Inches(6.3), Inches(1.0),
         [(body, 13, False, INK2, 0)], spacing=1.25)
    y += Inches(1.35)
text(s, M, Inches(6.5), CONTENT_W, Inches(0.5), [
    ("583 automated tests, including assertions that fail the build if the architecture is violated.",
     14, True, INK2, 0)])
notes(s, "Be precise about 'proven once'. One full cycle, live model, real application, real "
         "browser evidence. That is a reference implementation, not a production rollout, "
         "and saying so protects us.")

# ── 10 · limits ──────────────────────────────────────────────────────────────
s = blank(prs, WHITE)
eyebrow(s, "Known limits")
title(s, "What it does not do yet", "Stated before anyone asks — each is a decided position, not a gap we have missed.")
table(s, M, Inches(2.7), CONTENT_W, [
    ["Limit", "What it means in practice"],
    ["Analysis works at file level, not function level", "A small internal change and a breaking public change look the same to it"],
    ["Coverage is measured at request level", "It knows a test never touched an area; not which branch inside it ran"],
    ["Accuracy measured on our own codebase", "The number is a floor and a regression check, not an industry claim"],
    ["No access control yet", "Client work is separated; who may see or approve it is not yet enforced"],
], [0.42, 0.58], row_h=Inches(0.72))
notes(s, "Putting this in front of the sceptic before they ask changes the conversation. "
         "Every row is a limit we can describe precisely, which reads very differently from "
         "one discovered during a client pilot.")

# ── 11 · next ────────────────────────────────────────────────────────────────
s = blank(prs)
eyebrow(s, "Next")
title(s, "Three things, in order of what changes the argument")
items = [
    ("Measure against a real client codebase",
     "Our accuracy numbers come from one repository. Read access to a client's history turns a "
     "self-measurement into evidence. Low cost, highest value."),
    ("Function-level analysis",
     "The change that separates a cosmetic edit from a breaking one. Expensive, so we are not "
     "starting it until the measurement above says where the gap actually is."),
    ("Identity and access",
     "Approvals attributable to a named person. It rewrites the audit records, so it is "
     "cheaper now than after the first engagement."),
]
y = Inches(2.4)
for i, (head, body) in enumerate(items, 1):
    text(s, M, y, Inches(0.6), Inches(0.6), [(str(i), 26, True, TEAL, 0)])
    text(s, M + Inches(0.75), y, Inches(10.6), Inches(1.2),
         [(head, 19, True, INK, 5), (body, 13.5, False, INK2, 0)], spacing=1.25)
    y += Inches(1.45)
notes(s, "Item 1 is a small ask with a large payoff and should be the thing you leave the "
         "room having agreed. Item 2 is deliberately gated on item 1 — say that, it "
         "demonstrates we are not just building the interesting thing.")

# ── 12 · asks ────────────────────────────────────────────────────────────────
s = blank(prs, WHITE)
eyebrow(s, "What we need")
title(s, "Three asks")
asks = [
    ("A client repository", "Read access to one codebase and its history. Turns our accuracy "
                            "figure into evidence, and costs the client nothing."),
    ("An identity decision", "Which provider we build access control against. It is the one "
                             "enterprise gap we will not close by guessing."),
    ("One real change", "A candidate change on a system we do not control. Everything so far "
                        "is proven on an application we own."),
]
cw = (CONTENT_W - Inches(0.6)) / 3
for i, (head, body) in enumerate(asks):
    x = M + i * (cw + Inches(0.3))
    card(s, x, Inches(2.5), cw, Inches(2.9), fill=WHITE, border=TEAL, width=2.0)
    text(s, x + Inches(0.35), Inches(2.85), cw - Inches(0.7), Inches(0.6),
         [(head, 20, True, INK, 10)])
    text(s, x + Inches(0.35), Inches(3.65), cw - Inches(0.7), Inches(1.5),
         [(body, 13.5, False, INK2, 0)], spacing=1.3)
text(s, M, Inches(6.0), CONTENT_W, Inches(0.6), [
    ("None of these is a platform decision. They are read access, one architectural answer, "
     "and one candidate change.", 15, True, INK2, 0)])
notes(s, "Close here. Keep the asks small and concrete — we are not asking for a budget line "
         "or a platform commitment today.")

prs.save("/Users/subh/MyApps/agentic-sdlc/docs/agentic-sdlc-leadership.pptx")
print("saved:", len(prs.slides.__iter__.__self__._sldIdLst), "slides")
