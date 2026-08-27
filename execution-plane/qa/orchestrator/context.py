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
from orchestrator.paths import CODE_GRAPH_FILE, FEATURES_FILE, MANIFEST_FILE

FEATURES_SYSTEM = "features"
QA_SYSTEM = "qa"
CODE_SYSTEM = "code"

DEFAULT_PROJECT = "default"


def graph_project() -> str:
    """Which project this run's graph belongs to.

    Read from the export rather than configured here. The control plane
    scopes node identity by project, so a COVERS edge emitted against an
    unqualified `code` system would land in the default project's graph —
    pointing at a module that, for any client running more than one project,
    is not the one this run tested.
    """
    return _load_code_graph().get("project") or DEFAULT_PROJECT


def _scoped(system: str) -> str:
    project = graph_project()
    return system if project == DEFAULT_PROJECT else f"{system}@{project}"


# --------------------------------------------------------------------- read


# The export shapes this plane knows how to read. A versioned artefact
# nobody validates is an unversioned artefact: export_version went 2 to 3
# and no reader noticed, because this function read the file and trusted its
# shape. A newer control plane reaching an older pipeline would have
# produced wrong scope rather than an error.
SUPPORTED_EXPORT_VERSIONS = frozenset({2, 3})


class IncompatibleGraphExport(RuntimeError):
    """The control plane speaks a version of the contract this cannot read."""


def _load_code_graph() -> dict[str, Any]:
    if not CODE_GRAPH_FILE.exists():
        return {"modules": [], "depends_on": []}
    graph = json.loads(CODE_GRAPH_FILE.read_text())

    version = graph.get("export_version")
    if version is None:
        # A hand-maintained file rather than a generated export. Allowed, and
        # already reported by graph_warnings as unindexed scope.
        return graph
    if version not in SUPPORTED_EXPORT_VERSIONS:
        raise IncompatibleGraphExport(
            f"the code graph declares export_version {version}; this pipeline reads "
            f"{sorted(SUPPORTED_EXPORT_VERSIONS)}. Upgrade the execution plane, or "
            f"re-export from a control plane that matches it — scoping against a "
            f"contract this does not understand is worse than not scoping."
        )
    return graph


def _normalise(path: str) -> str:
    """One canonical repository-relative form for a path.

    Both sides of the comparison have to agree on what a path *is* before
    equality means anything: git emits repository-relative paths, the graph
    holds whatever was written into it, and a leading `./` or `/` in either
    turns a match into a miss.
    """
    return path.strip().lstrip("/").removeprefix("./")


def modules_for_paths(changed_paths: list[str]) -> set[str]:
    """Which modules a set of changed files belongs to.

    Matched by exact path, or by directory prefix for a module that names a
    directory rather than files. The previous check asked whether a graph path
    appeared anywhere inside a changed path — so `app/claims` matched
    `vendor/app/claims-archive/x.ts`, and a module could be pulled into scope
    by a file that has nothing to do with it.
    """
    graph = _load_code_graph()
    changed = {_normalise(path) for path in changed_paths}
    hits: set[str] = set()

    for module in graph.get("modules", []):
        for raw in module.get("paths", []):
            owned = _normalise(raw)
            if owned in changed or any(c.startswith(f"{owned}/") for c in changed):
                hits.add(module["id"])
                break
    return hits


def impact_policy() -> dict[str, Any]:
    """The traversal contract the control plane exported.

    Read rather than assumed. This plane used to traverse modules one hop
    while the design gate traversed files two, so a change could pass a
    containment check and then be tested against a different set — on one
    real file the gate named a module QA never required a test for, and QA
    required one the gate never named.
    """
    impact = _load_code_graph().get("impact") or {}
    policy = impact.get("policy") or {}
    return {
        "engine_version": impact.get("engine_version"),
        "max_depth": policy.get("max_depth", 2),
        "edges": set(policy.get("edges") or ["IMPORTS", "CALLS_ENDPOINT"]),
    }


def impacted_modules(
    changed_paths: list[str], impact: dict[str, Any] | None = None
) -> set[str]:
    """Which modules this change reaches, from the assessment it was given.

    This plane used to traverse for itself: a flat walk over file_dependents,
    depth-capped by the exported policy. It agreed with the control plane on
    every commit measured — but incidentally. The graph carries one edge type
    and an IMPORTS path stays above the confidence floor until nine hops
    while the policy stops at two, so every distinction the canonical engine
    draws collapsed to the same answer. Populate CALLS_ENDPOINT, register
    anything `inferred`, or raise max_depth, and the two separate — and the
    run's design gate and its QA scope would then disagree about what the
    change touches, which is not a disagreement either side could detect.

    So the traversal is gone rather than kept in sync. Reach is decided once,
    in the control plane's impact engine, and travels with the request.

    Without an assessment this returns the directly changed modules and the
    caller reports that scope was not widened. Guessing is the one thing it
    will not do: a walk this plane invents is the duplicate that was just
    deleted, and it would come back with no one deciding to bring it back.
    """
    direct = modules_for_paths(changed_paths)
    affected = (impact or {}).get("affected") or []
    if not affected:
        return direct
    return direct | modules_for_paths(list(affected))


def _scope_warnings(impact: dict[str, Any] | None) -> list[str]:
    """Reasons this run's regression scope is narrower than it should be.

    Loud, because narrow is the dangerous direction. A scope missing what a
    change reaches requires fewer regressions and passes more easily, so
    silence reads as a cleaner run rather than a less-informed one.
    """
    if (impact or {}).get("affected"):
        return []
    return [
        "no impact assessment was supplied, so regression scope is the changed "
        "modules only and does not include what the change reaches"
    ]


def _load_manifest() -> list[dict[str, Any]]:
    if not MANIFEST_FILE.exists():
        return []
    return json.loads(MANIFEST_FILE.read_text()).get("scripts", [])


def library_script_ids() -> set[str]:
    """Every test script the library actually holds."""
    return {entry["id"] for entry in _load_manifest() if entry.get("id")}


def scripts_covering(module_ids: set[str]) -> set[str]:
    """Which library scripts claim to exercise any of these modules.

    Read from the manifest rather than from the code graph. Which modules a
    script covers is a property of the script, and asserting it in the graph
    is how modules came to claim coverage from scripts nobody had written —
    every entry in the hand-authored graph named a script that did not exist.
    """
    return {
        entry["id"]
        for entry in _load_manifest()
        if entry.get("id") and set(entry.get("covers_modules") or []) & module_ids
    }


def graph_provenance() -> dict[str, Any]:
    """Which snapshot the code graph describes, and whether it was derived.

    A hand-maintained graph has no answer to either question. Both are
    reported so a run can say what its scoping was based on instead of
    presenting a blast radius as though its source were beyond question.
    """
    graph = _load_code_graph()
    provenance = dict(graph.get("provenance") or {})
    provenance["generated"] = bool(graph.get("generated"))
    provenance["scope"] = graph.get("scope", "")
    return provenance


def graph_warnings(head_sha: str = "") -> list[str]:
    """Reasons to distrust the scoping this graph produced.

    Not failures. A stale graph still scopes better than no graph, and
    refusing the run would make an out-of-date export worse than never having
    generated one. They are surfaced so the answer is qualified rather than
    presented as certain.
    """
    provenance = graph_provenance()
    warnings: list[str] = []

    if not provenance.get("generated"):
        warnings.append(
            "the code graph was not generated from an index — regression scope "
            "is based on a hand-maintained file"
        )
        return warnings

    commit = provenance.get("commit_sha")
    if not commit:
        warnings.append("the code graph names no commit, so it cannot be checked for staleness")
    elif head_sha and commit != head_sha:
        warnings.append(
            f"the code graph describes {commit[:7]}, not the {head_sha[:7]} under test — "
            f"re-export it after seeding"
        )

    capture = provenance.get("internal_capture_rate")
    if capture is not None and capture < 0.8:
        warnings.append(
            f"the index behind this graph resolved only {capture:.1%} of internal "
            f"imports, so the blast radius is likely to be missing edges"
        )
    return warnings


def regression_candidates(
    changed_paths: list[str],
    head_sha: str = "",
    impact: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """What a change obliges this run to re-test, and what it cannot.

    Three separate answers, because they carry different weight:

      required        — scripts that exist and cover an impacted module. These
                        are not suggestions to an agent. They are run, and the
                        gate fails if any of them does not pass.
      uncovered       — impacted modules nothing in the library covers. Not a
                        failure by default, because it would refuse every
                        change to a codebase that has not finished building a
                        regression suite. Always reported, because "we did not
                        test this" is the answer a release decision needs and
                        silence is not.
      dangling        — a script claiming to cover a module the graph does not
                        contain. A hard error: coverage recorded against a
                        module that no longer exists is coverage nothing has.

    The `why` matters too: a scenario required because a module two hops away
    changed is a claim the test plan should be able to justify.
    """
    direct = modules_for_paths(changed_paths)
    widened = impacted_modules(changed_paths, impact)
    known_modules = {m["id"] for m in _load_code_graph().get("modules", [])}

    required = scripts_covering(widened)
    covered_modules = {
        module
        for entry in _load_manifest()
        if entry.get("id") in required
        for module in entry.get("covers_modules") or []
    }
    dangling = sorted(
        f"{entry['id']} -> {module}"
        for entry in _load_manifest()
        for module in entry.get("covers_modules") or []
        if module not in known_modules
    )

    return {
        "changed_components": sorted(direct),
        "impacted_components": sorted(widened),
        "required_scripts": sorted(required),
        "uncovered_components": sorted(widened - covered_modules),
        "dangling_coverage": dangling,
        # Passed, at last. The staleness branch inside graph_warnings tests
        # `head_sha and commit != head_sha`, and nothing in production ever
        # supplied one — so the check that catches a graph describing the
        # wrong commit could not fire outside its own test. A control that
        # cannot fire is not a control.
        # Two different doubts, kept apart. graph_warnings asks whether the
        # graph can be trusted; this asks whether this run was told how far
        # its change reaches. A run against a perfect graph with no
        # assessment is still scoped to the edit alone.
        "graph_warnings": graph_warnings(head_sha=head_sha) + _scope_warnings(impact),
        # Which engine decided the reach, so a scope can be traced back to
        # the rules that produced it rather than to whoever ran it.
        "impact_engine_version": (impact or {}).get("engine_version", ""),
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
    # Scoped here rather than at each call site, so a new assertion cannot be
    # written that quietly targets the wrong project's graph.
    system = _scoped(system)
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

    # Required regressions are not planned scenarios, so the loop above never
    # saw them — they ran, the gate enforced them, and the control plane heard
    # nothing. Their COVERS edges are the stronger kind: not a claim that a
    # script covers a module, but a record that it did, in this run, at this
    # commit.
    scope = state.get("regression_scope") or {}
    impacted = set(scope.get("impacted_components") or [])

    for assignment in state.get("test_assignments", []):
        if assignment.get("mode") != "required-regression":
            continue
        script_id = assignment.get("source_script_id")
        scenario_id = assignment.get("scenario_id") or f"regression:{script_id}"
        scenario_node = _node(
            "TEST_SCENARIO", QA_SYSTEM, scenario_id,
            {"title": f"required regression: {script_id}", "type": "regression",
             "required_by_blast_radius": True},
        )
        script_node = _node(
            "TEST_SCRIPT", QA_SYSTEM, assignment["file_path"].split("/")[-1],
            {"mode": assignment.get("mode", ""), "library_id": script_id},
        )
        assertions.append({"edge": "IMPLEMENTED_BY", "src": scenario_node, "dst": script_node})
        assertions.append({"edge": "EXERCISED_IN", "src": script_node, "dst": run_node})

        # Observed first, declared as the fallback. A COVERS edge derived from
        # what the run actually requested is evidence; one derived from the
        # manifest is a restatement of someone's intent, and the two should
        # not be indistinguishable to whatever reads the graph later.
        name = (assignment.get("file_path") or "").replace("/", "|").split("|")[-1]
        seen = (state.get("observed_coverage") or {}).get(name) or {}
        entry = next((e for e in _load_manifest() if e.get("id") == script_id), {})
        modules = seen.get("modules")
        provenance = "runtime-observed" if modules else "declared"
        for module in sorted(modules or entry.get("covers_modules") or []):
            if module in impacted:
                assertions.append({
                    "edge": "COVERS",
                    "src": scenario_node,
                    "dst": _node("MODULE", CODE_SYSTEM, module, {}),
                    "attributes": {"provenance": provenance},
                })

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
