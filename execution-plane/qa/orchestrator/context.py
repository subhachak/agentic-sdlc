"""The QA pipeline's view of the context graph.

Two halves, matching the two directions context flows:

  read  — the code-intelligence graph, used to widen regression scope from
          "what the diff touched" to "what depends on what the diff touched".
  write — the assertions this run observed, emitted for the control plane to
          ingest as traceability edges with provenance attached.

Node ids are computed here rather than requested, using the same derivation
the control plane uses. That is what lets the two planes talk about the same
criterion without a round trip.
"""

from __future__ import annotations

import json
from typing import Any

from orchestrator.identity import node_id
from orchestrator.paths import CODE_GRAPH_FILE, FEATURES_FILE

FEATURES_SYSTEM = "features"
QA_SYSTEM = "qa"
CODE_SYSTEM = "code"


# --------------------------------------------------------------------- read


def _load_code_graph() -> dict[str, Any]:
    if not CODE_GRAPH_FILE.exists():
        return {"modules": [], "depends_on": []}
    return json.loads(CODE_GRAPH_FILE.read_text())


def modules_for_paths(changed_paths: list[str]) -> set[str]:
    """Which modules a set of changed files belongs to."""
    graph = _load_code_graph()
    hits: set[str] = set()
    for module in graph.get("modules", []):
        for path in module.get("paths", []):
            if any(path in changed for changed in changed_paths):
                hits.add(module["id"])
    return hits


def blast_radius(module_ids: set[str]) -> set[str]:
    """Components that depend on the ones given, plus the ones given.

    One hop. Unbounded traversal over a real dependency graph is the query
    that would justify a graph database; this is what the seeded index can
    support honestly.
    """
    graph = _load_code_graph()
    dependents = {
        edge["from"]
        for edge in graph.get("depends_on", [])
        if edge["to"] in module_ids
    }
    return module_ids | dependents


def scenarios_covering(module_ids: set[str]) -> set[str]:
    graph = _load_code_graph()
    return {
        scenario
        for module in graph.get("modules", [])
        if module["id"] in module_ids
        for scenario in module.get("covered_by", [])
    }


def regression_candidates(changed_paths: list[str]) -> dict[str, Any]:
    """Scenarios worth re-running for a change, and why.

    The `why` matters: a scenario proposed because a module two hops away
    changed is a claim the test plan should be able to justify.
    """
    direct = modules_for_paths(changed_paths)
    widened = blast_radius(direct)
    return {
        "changed_components": sorted(direct),
        "impacted_components": sorted(widened),
        "scenarios": sorted(scenarios_covering(widened)),
    }


# -------------------------------------------------------------- identity


def criterion_ids() -> dict[str, dict[str, Any]]:
    """Every acceptance criterion the feature context declares, by id."""
    import yaml

    if not FEATURES_FILE.exists():
        return {}
    data = yaml.safe_load(FEATURES_FILE.read_text()) or {}
    out: dict[str, dict[str, Any]] = {}
    for feature in data.get("features", []):
        for criterion in feature.get("acceptance_criteria", []) or []:
            if isinstance(criterion, dict) and criterion.get("id"):
                out[criterion["id"]] = {
                    "feature": feature.get("id"),
                    "module": feature.get("module"),
                    "text": criterion.get("text", ""),
                }
    return out


def ui_contract() -> str:
    """The selectors the generator may use, by route, with their values.

    Read from features.yaml rather than written into the prompt, so the
    contract lives with the requirements it describes and a change to the app
    is a change to one file rather than to a string constant in a node.
    """
    import yaml

    if not FEATURES_FILE.exists():
        return ""
    data = yaml.safe_load(FEATURES_FILE.read_text()) or {}
    lines: list[str] = []
    for route, elements in (data.get("ui") or {}).items():
        lines.append(f"{route}")
        for element in elements or []:
            note = " ".join((element.get("note") or "").split())
            lines.append(f"  data-testid={element['testid']}" + (f" — {note}" if note else ""))
    return "\n".join(lines)


def api_contract() -> str:
    """The endpoints the generator may assert against, and their shapes."""
    import yaml

    if not FEATURES_FILE.exists():
        return ""
    data = yaml.safe_load(FEATURES_FILE.read_text()) or {}
    lines: list[str] = []
    for entry in data.get("api") or []:
        note = " ".join((entry.get("note") or "").split())
        lines.append(f"{entry['endpoint']}" + (f" — {note}" if note else ""))
        testing = " ".join((entry.get("testing") or "").split())
        if testing:
            lines.append(f"  testing: {testing}")
    return "\n".join(lines)


def _node(node_type: str, system: str, external_id: str, projection: dict) -> dict:
    return {
        "id": node_id(node_type, system, external_id),
        "type": node_type,
        "system": system,
        "external_id": external_id,
        "projection": projection,
    }


# -------------------------------------------------------------------- write


def build_assertions(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Everything this run observed, as ontology edges.

    Emitted as plain dicts: the control plane is a separate package, and a
    shared schema across that boundary would have to be versioned in two
    places at once.
    """
    known = criterion_ids()
    assignments = {a["scenario_id"]: a for a in state.get("test_assignments", [])}
    failing = set(state.get("failing_scenarios", []))
    run_external = f"{state.get('repo', 'local')}#{state.get('pr_number', 0)}"
    passed = bool(state.get("gate_passed"))

    run_node = _node(
        "TEST_RUN", QA_SYSTEM, run_external,
        {"status": "passed" if passed else "failed",
         "evidence": state.get("evidence_summary", {})},
    )

    assertions: list[dict[str, Any]] = []

    for scenario in state.get("test_plan", []):
        scenario_id = scenario.get("id")
        if not scenario_id:
            continue
        scenario_node = _node(
            "TEST_SCENARIO", QA_SYSTEM, scenario_id,
            {"title": scenario.get("title", ""), "type": scenario.get("type", "")},
        )

        # criterion -> scenario, only when the reference actually resolves
        ac_ref = scenario.get("ac_ref")
        if ac_ref in known:
            assertions.append({
                "edge": "VERIFIED_BY",
                "src": _node("ACCEPTANCE_CRITERION", FEATURES_SYSTEM, ac_ref, known[ac_ref]),
                "dst": scenario_node,
            })
            module = known[ac_ref].get("module")
            if module:
                assertions.append({
                    "edge": "COVERS",
                    "src": scenario_node,
                    "dst": _node("MODULE", CODE_SYSTEM, module, {}),
                })

        assignment = assignments.get(scenario_id)
        if not assignment:
            continue

        script_node = _node(
            "TEST_SCRIPT", QA_SYSTEM, assignment["file_path"].split("/")[-1],
            {"mode": assignment.get("mode", "")},
        )
        assertions.append({"edge": "IMPLEMENTED_BY", "src": scenario_node, "dst": script_node})
        assertions.append({"edge": "EXERCISED_IN", "src": script_node, "dst": run_node})

    evidence = state.get("evidence_summary", {})
    if evidence.get("html_report"):
        assertions.append({
            "edge": "PRODUCED",
            "src": run_node,
            "dst": _node("EVIDENCE", QA_SYSTEM, evidence["html_report"],
                         {"screenshots": evidence.get("screenshot_count", 0),
                          "traces": evidence.get("trace_count", 0)}),
        })

    for title in sorted(failing):
        assertions.append({
            "edge": "RAISED",
            "src": run_node,
            "dst": _node("DEFECT", QA_SYSTEM, title, {"title": title}),
        })

    # module dependency edges, so blast radius is queryable centrally too
    for edge in _load_code_graph().get("depends_on", []):
        assertions.append({
            "edge": "DEPENDS_ON",
            "src": _node("MODULE", CODE_SYSTEM, edge["from"], {}),
            "dst": _node("MODULE", CODE_SYSTEM, edge["to"], {}),
        })

    return assertions
