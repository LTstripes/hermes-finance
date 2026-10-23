"""Fail-closed checks for exclusive backend CI lane ownership."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from _pytest.mark.expression import Expression
from _test_taxonomy import (
    CI_CORE_SHARD_MARKERS,
    CI_INTEGRATIONS_A_SHARD_MARKERS,
    CI_INTEGRATIONS_A_SHARD_WEIGHTS,
    CI_INTEGRATIONS_A_SPLIT_FILES,
    CI_INTEGRATIONS_B_SHARD_MARKERS,
    CI_INTEGRATIONS_B_SHARD_WEIGHTS,
    CI_INTEGRATIONS_B_SPLIT_FILES,
    CI_INTEGRATIONS_SHARD_MARKERS,
    CI_INTEGRATIONS_SHARD_WEIGHTS,
    CI_LANE_MARKERS,
    CI_PERSISTENCE_SHARD_MARKERS,
    CI_PERSISTENCE_SHARD_WEIGHTS,
    TESTS_ROOT,
    ci_core_shard_for_test_path,
    ci_integrations_a_shard_for_test_node,
    ci_integrations_b_shard_for_test_node,
    ci_integrations_shard_for_test_path,
    ci_lane_for_test_path,
    ci_persistence_shard_for_test_path,
    iter_backend_test_files,
    semantic_markers_for,
)

BACKEND_ROOT = TESTS_ROOT.parent
WORKFLOW_PATH = BACKEND_ROOT.parent / ".github" / "workflows" / "ci.yml"
_MATRIX_ENTRY = re.compile(
    r"- lane: (?P<lane>[A-Za-z0-9-]+)\n"
    r"\s+marker: (?P<marker>\"[^\"]+\"|[A-Za-z0-9_]+)\n"
    r"\s+timeout_minutes: (?P<timeout>\d+)\n"
)
_COLLECTOR = """
import os
import sys

import pytest


class Collector:
    def pytest_collection_finish(self, session):
        rows = []
        for item in session.items:
            names = ",".join(sorted({mark.name for mark in item.iter_markers()}))
            rows.append(f"{item.nodeid}\\t{names}")
        with open(os.environ["HERMES_COLLECT_OUT"], "w", encoding="utf-8") as handle:
            handle.write("\\n".join(rows))
            if rows:
                handle.write("\\n")


if __name__ == "__main__":
    raise SystemExit(pytest.main(sys.argv[1:], plugins=[Collector()]))
"""


def test_every_backend_test_file_has_one_ci_lane() -> None:
    unclassified = []
    invalid = []
    for test_path in iter_backend_test_files():
        lane = ci_lane_for_test_path(test_path)
        if lane is None:
            unclassified.append(test_path.relative_to(test_path.parents[1]).as_posix())
        elif lane not in CI_LANE_MARKERS:
            invalid.append(f"{test_path.name}: {lane}")

    assert not unclassified, "Unclassified backend test files: " + ", ".join(unclassified)
    assert not invalid, "Invalid backend CI lane markers: " + ", ".join(invalid)


def test_benchmark_files_are_isolated_from_normal_ci_lanes() -> None:
    benchmark_files = (
        test_path
        for test_path in iter_backend_test_files()
        if "benchmark" in semantic_markers_for(test_path)
    )

    assert all(ci_lane_for_test_path(test_path) == "ci_benchmark" for test_path in benchmark_files)


def test_core_files_have_one_stable_shard() -> None:
    core_files = (
        test_path
        for test_path in iter_backend_test_files()
        if ci_lane_for_test_path(test_path) == "ci_core"
    )

    shards = {ci_core_shard_for_test_path(test_path) for test_path in core_files}
    assert shards == set(CI_CORE_SHARD_MARKERS)


def test_accepted_core_shard_anchors_stay_put() -> None:
    assert ci_core_shard_for_test_path(TESTS_ROOT / "test_perf04a_attribution.py") == "ci_core_a"
    assert (
        ci_core_shard_for_test_path(TESTS_ROOT / "test_scenario_lab_equity_drawdown.py")
        == "ci_core_b"
    )
    assert ci_core_shard_for_test_path(TESTS_ROOT / "test_historical_source_xirr.py") == "ci_core_b"
    assert ci_core_shard_for_test_path(TESTS_ROOT / "domain" / "test_values.py") == "ci_core_b"
    assert ci_core_shard_for_test_path(TESTS_ROOT / "test_cash_api.py") == "ci_core_a"


def _report_duration_estimates(name: str, totals: dict[str, float]) -> None:
    """Optional `pytest -s` diagnostics; real workflow timeouts remain the gate."""
    ratio = max(totals.values()) / min(totals.values())
    print(f"{name}: estimated seconds={totals}, max/min={ratio:.3f}")


def test_persistence_shards_cover_the_lane_once() -> None:
    files = {
        path.relative_to(TESTS_ROOT).as_posix()
        for path in iter_backend_test_files()
        if ci_lane_for_test_path(path) == "ci_persistence"
    }
    assert set(CI_PERSISTENCE_SHARD_WEIGHTS) == files
    assert all(weight > 0 for weight in CI_PERSISTENCE_SHARD_WEIGHTS.values())
    totals = dict.fromkeys(CI_PERSISTENCE_SHARD_MARKERS, 0.0)
    for key, weight in CI_PERSISTENCE_SHARD_WEIGHTS.items():
        shard = ci_persistence_shard_for_test_path(TESTS_ROOT / key)
        assert shard in CI_PERSISTENCE_SHARD_MARKERS
        totals[shard] += weight
    assert min(totals.values()) > 0
    _report_duration_estimates("persistence", totals)
    assert ci_persistence_shard_for_test_path(TESTS_ROOT / "test_migrations.py") == (
        "ci_persistence_a"
    )


def _integration_files() -> tuple[Path, ...]:
    return tuple(
        test_path
        for test_path in iter_backend_test_files()
        if ci_lane_for_test_path(test_path) == "ci_integrations"
    )


def test_integration_weight_table_matches_files_exactly() -> None:
    files = {test_path.relative_to(TESTS_ROOT).as_posix() for test_path in _integration_files()}

    assert set(CI_INTEGRATIONS_SHARD_WEIGHTS) == files
    assert files


def test_unknown_integration_weight_fails_closed(monkeypatch) -> None:
    import _test_taxonomy as taxonomy

    weights = dict(CI_INTEGRATIONS_SHARD_WEIGHTS)
    removed = "test_statement_import_mybroker_endpoints.py"
    weights.pop(removed)
    monkeypatch.setattr(taxonomy, "CI_INTEGRATIONS_SHARD_WEIGHTS", weights)

    assert ci_integrations_shard_for_test_path(TESTS_ROOT / removed) is None


def test_integration_files_have_one_exclusive_shard() -> None:
    assert all(weight > 0 for weight in CI_INTEGRATIONS_SHARD_WEIGHTS.values())
    totals = {marker: 0.0 for marker in CI_INTEGRATIONS_SHARD_MARKERS}
    for test_path in _integration_files():
        shard = ci_integrations_shard_for_test_path(test_path)
        assert shard in CI_INTEGRATIONS_SHARD_MARKERS
        key = test_path.relative_to(TESTS_ROOT).as_posix()
        totals[shard] += CI_INTEGRATIONS_SHARD_WEIGHTS[key]

    assert set(totals) == set(CI_INTEGRATIONS_SHARD_MARKERS)
    assert min(totals.values()) > 0
    _report_duration_estimates("integrations", totals)


def test_integrations_a_weights_cover_only_the_original_a_group() -> None:
    files = {
        path.relative_to(TESTS_ROOT).as_posix()
        for path in _integration_files()
        if ci_integrations_shard_for_test_path(path) == "ci_integrations_a"
    }
    assert files
    assert {key.split("::", 1)[0] for key in CI_INTEGRATIONS_A_SHARD_WEIGHTS} == files
    assert CI_INTEGRATIONS_A_SPLIT_FILES <= files
    assert all(weight > 0 for weight in CI_INTEGRATIONS_A_SHARD_WEIGHTS.values())


def test_unknown_integrations_a_weight_fails_closed(monkeypatch) -> None:
    import _test_taxonomy as taxonomy

    weights = dict(CI_INTEGRATIONS_A_SHARD_WEIGHTS)
    removed = next(key for key in weights if "::" in key)
    weights.pop(removed)
    monkeypatch.setattr(taxonomy, "CI_INTEGRATIONS_A_SHARD_WEIGHTS", weights)

    assert (
        ci_integrations_a_shard_for_test_node(
            TESTS_ROOT / removed.split("::", 1)[0], f"tests/{removed}[parameter]"
        )
        is None
    )
    assert (
        ci_integrations_a_shard_for_test_node(
            TESTS_ROOT / "test_statement_import_mybroker_endpoints.py",
            "tests/test_statement_import_mybroker_endpoints.py::test_unweighted_function",
        )
        is None
    )


def test_integrations_a_shards_are_stable(monkeypatch) -> None:
    import _test_taxonomy as taxonomy

    totals = dict.fromkeys(CI_INTEGRATIONS_A_SHARD_MARKERS, 0.0)
    assignments = {}
    for path in iter_backend_test_files():
        if ci_integrations_shard_for_test_path(path) != "ci_integrations_a":
            assert ci_integrations_a_shard_for_test_node(path, "") is None
    for key, weight in CI_INTEGRATIONS_A_SHARD_WEIGHTS.items():
        path = TESTS_ROOT / key.split("::", 1)[0]
        shard = ci_integrations_a_shard_for_test_node(path, f"tests/{key}")
        assert shard in CI_INTEGRATIONS_A_SHARD_MARKERS
        assignments[key] = shard
        totals[shard] += weight
        if "::" in key:
            assert ci_integrations_a_shard_for_test_node(path, f"tests/{key}[first]") == shard
            assert ci_integrations_a_shard_for_test_node(path, f"tests/{key}[second]") == shard

    assert min(totals.values()) > 0
    _report_duration_estimates("integrations-a", totals)

    monkeypatch.setattr(
        taxonomy,
        "CI_INTEGRATIONS_A_SHARD_WEIGHTS",
        dict(reversed(list(CI_INTEGRATIONS_A_SHARD_WEIGHTS.items()))),
    )
    assert {
        key: ci_integrations_a_shard_for_test_node(
            TESTS_ROOT / key.split("::", 1)[0], f"tests/{key}"
        )
        for key in assignments
    } == assignments


def test_integrations_b_weights_cover_only_the_original_b_group() -> None:
    files = {
        path.relative_to(TESTS_ROOT).as_posix()
        for path in _integration_files()
        if ci_integrations_shard_for_test_path(path) == "ci_integrations_b"
    }
    assert files
    assert {key.split("::", 1)[0] for key in CI_INTEGRATIONS_B_SHARD_WEIGHTS} == files
    assert CI_INTEGRATIONS_B_SPLIT_FILES <= files
    assert all(weight > 0 for weight in CI_INTEGRATIONS_B_SHARD_WEIGHTS.values())


def test_unknown_integrations_b_weight_fails_closed(monkeypatch) -> None:
    import _test_taxonomy as taxonomy

    weights = dict(CI_INTEGRATIONS_B_SHARD_WEIGHTS)
    removed = next(key for key in weights if "::" in key)
    weights.pop(removed)
    monkeypatch.setattr(taxonomy, "CI_INTEGRATIONS_B_SHARD_WEIGHTS", weights)

    assert (
        ci_integrations_b_shard_for_test_node(
            TESTS_ROOT / removed.split("::", 1)[0], f"tests/{removed}[parameter]"
        )
        is None
    )
    assert (
        ci_integrations_b_shard_for_test_node(
            TESTS_ROOT / "test_statement_import_source_cash_coverage.py",
            "tests/test_statement_import_source_cash_coverage.py::test_unweighted_function",
        )
        is None
    )


def test_integrations_b_shards_are_stable(monkeypatch) -> None:
    import _test_taxonomy as taxonomy

    totals = dict.fromkeys(CI_INTEGRATIONS_B_SHARD_MARKERS, 0.0)
    assignments = {}
    for path in iter_backend_test_files():
        if ci_integrations_shard_for_test_path(path) != "ci_integrations_b":
            assert ci_integrations_b_shard_for_test_node(path, "") is None
    for key, weight in CI_INTEGRATIONS_B_SHARD_WEIGHTS.items():
        path = TESTS_ROOT / key.split("::", 1)[0]
        shard = ci_integrations_b_shard_for_test_node(path, f"tests/{key}")
        assert shard in CI_INTEGRATIONS_B_SHARD_MARKERS
        assignments[key] = shard
        totals[shard] += weight
        if "::" in key:
            assert ci_integrations_b_shard_for_test_node(path, f"tests/{key}[first]") == shard
            assert ci_integrations_b_shard_for_test_node(path, f"tests/{key}[second]") == shard

    assert min(totals.values()) > 0
    _report_duration_estimates("integrations-b", totals)

    monkeypatch.setattr(
        taxonomy,
        "CI_INTEGRATIONS_B_SHARD_WEIGHTS",
        dict(reversed(list(CI_INTEGRATIONS_B_SHARD_WEIGHTS.items()))),
    )
    assert {
        key: ci_integrations_b_shard_for_test_node(
            TESTS_ROOT / key.split("::", 1)[0], f"tests/{key}"
        )
        for key in assignments
    } == assignments


def test_shard_markers_are_not_parent_lanes() -> None:
    assert set(CI_CORE_SHARD_MARKERS).isdisjoint(CI_LANE_MARKERS)
    assert set(CI_PERSISTENCE_SHARD_MARKERS).isdisjoint(CI_LANE_MARKERS)
    assert set(CI_INTEGRATIONS_SHARD_MARKERS).isdisjoint(CI_LANE_MARKERS)
    assert set(CI_INTEGRATIONS_A_SHARD_MARKERS).isdisjoint(CI_LANE_MARKERS)
    assert set(CI_INTEGRATIONS_A_SHARD_MARKERS).isdisjoint(CI_INTEGRATIONS_SHARD_MARKERS)
    assert set(CI_INTEGRATIONS_A_SHARD_MARKERS).isdisjoint(CI_INTEGRATIONS_B_SHARD_MARKERS)
    assert set(CI_INTEGRATIONS_B_SHARD_MARKERS).isdisjoint(CI_LANE_MARKERS)
    assert set(CI_INTEGRATIONS_B_SHARD_MARKERS).isdisjoint(CI_INTEGRATIONS_SHARD_MARKERS)


def test_benchmark_files_do_not_enter_integration_shards() -> None:
    for test_path in iter_backend_test_files():
        if "benchmark" not in semantic_markers_for(test_path):
            continue
        assert ci_lane_for_test_path(test_path) == "ci_benchmark"
        assert ci_integrations_shard_for_test_path(test_path) is None
        assert ci_core_shard_for_test_path(test_path) is None


def _workflow_entries() -> list[tuple[str, str, int]]:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    return [
        (match.group("lane"), match.group("marker").strip('"'), int(match.group("timeout")))
        for match in _MATRIX_ENTRY.finditer(workflow)
    ]


def test_backend_matrix_keeps_full_lanes_and_duration_weighted_shards() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    entries = dict((lane, (marker, timeout)) for lane, marker, timeout in _workflow_entries())

    assert list(entries) == [
        "core-a",
        "core-b",
        "persistence-a",
        "persistence-b",
        "integrations-a1",
        "integrations-a2",
        "integrations-a3",
        "integrations-a4",
        "integrations-b1",
        "integrations-b2",
        "integrations-b3",
        "integrations-b4",
        "integrations-b5",
        "integrations-b6",
        "integrations-b7",
        "integrations-b8",
        "runtime-release",
        "benchmark",
    ]
    for index, shard in enumerate(CI_INTEGRATIONS_A_SHARD_MARKERS, start=1):
        assert entries[f"integrations-a{index}"] == (
            f"ci_integrations and ci_integrations_a and {shard}",
            10,
        )
    for index, shard in enumerate(CI_INTEGRATIONS_B_SHARD_MARKERS, start=1):
        assert entries[f"integrations-b{index}"] == (
            f"ci_integrations and ci_integrations_b and {shard}",
            10,
        )
    assert len(entries) == len(_workflow_entries())
    for index, shard in enumerate(CI_PERSISTENCE_SHARD_MARKERS, start=1):
        assert entries[f"persistence-{'ab'[index - 1]}"] == (
            f"ci_persistence and {shard}",
            10,
        )
    for lane in ("core-a", "core-b", "runtime-release", "benchmark"):
        assert entries[lane][1] == 10
    assert "\n          - lane: integrations\n" not in workflow
    assert "timeout-minutes: ${{ matrix.timeout_minutes }}" in workflow
    assert "matrix.lane == 'integrations'" not in workflow
    assert (
        'uv run --locked python -I -m pytest -q --durations=40 -m "${{ matrix.marker }}"'
        in workflow
    )
    assert "needs: docs-only-classify" in workflow
    assert "docs-only-classify.outputs.mode != 'docs-only'" in workflow


def test_pr_safety_job_ownership_and_docs_full_override() -> None:
    # Link lane ownership to behavioral checks of the actual workflow gates.
    # A scripts/PowerShell change must reach release safety without an opt-in label.
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            str(BACKEND_ROOT.parent / "scripts/tests/test-ci-paths.py"),
            "WorkflowTests.test_safety_paths_reach_windows_jobs_without_labels",
            "WorkflowTests.test_windows_jobs_follow_classifier_outputs_and_fail_closed",
            "WorkflowTests.test_full_label_bypasses_docs_area_and_visual_filters",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def _matches(expression: str, names: frozenset[str]) -> bool:
    return Expression.compile(expression).evaluate(lambda name, **_kwargs: name in names)


def _collected_nodes() -> list[tuple[str, frozenset[str]]]:
    with tempfile.TemporaryDirectory() as directory:
        script = Path(directory) / "collect_markers.py"
        output = Path(directory) / "nodes.txt"
        script.write_text(_COLLECTOR, encoding="utf-8")
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                str(script),
                "--collect-only",
                "-p",
                "no:cacheprovider",
                "--override-ini",
                "addopts=",
                "-q",
            ],
            cwd=BACKEND_ROOT,
            env={**os.environ, "HERMES_COLLECT_OUT": str(output)},
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr + completed.stdout
        rows = []
        for line in output.read_text(encoding="utf-8").splitlines():
            nodeid, names = line.split("\t")
            rows.append((nodeid, frozenset(filter(None, names.split(",")))))
        return rows


def test_collected_nodes_run_in_exactly_one_parent_and_integration_shard() -> None:
    rows = _collected_nodes()
    entries = dict((lane, marker) for lane, marker, _timeout in _workflow_entries())
    parent_expr = "ci_integrations"
    shard_exprs = tuple(
        expression for lane, expression in entries.items() if lane.startswith("integrations-")
    )

    parent = [nodeid for nodeid, names in rows if _matches(parent_expr, names)]
    shards = [
        [nodeid for nodeid, names in rows if _matches(expression, names)]
        for expression in shard_exprs
    ]
    combined: Counter[str] = Counter()
    for shard in shards:
        combined.update(shard)

    assert parent
    assert all(shards)
    assert len(parent) == len(set(parent))
    assert all(count == 1 for count in combined.values())
    assert Counter(parent) == combined

    for group, markers, split_files, weights in (
        (
            "a",
            CI_INTEGRATIONS_A_SHARD_MARKERS,
            CI_INTEGRATIONS_A_SPLIT_FILES,
            CI_INTEGRATIONS_A_SHARD_WEIGHTS,
        ),
        (
            "b",
            CI_INTEGRATIONS_B_SHARD_MARKERS,
            CI_INTEGRATIONS_B_SPLIT_FILES,
            CI_INTEGRATIONS_B_SHARD_WEIGHTS,
        ),
    ):
        original = [nodeid for nodeid, names in rows if f"ci_integrations_{group}" in names]
        split: Counter[str] = Counter()
        for marker in markers:
            split.update(nodeid for nodeid, names in rows if marker in names)
        assert original
        assert all(count == 1 for count in split.values())
        assert Counter(original) == split
        weighted_keys = set()
        for nodeid in original:
            file_key, test_key = nodeid.removeprefix("tests/").split("::", 1)
            key = file_key
            if file_key in split_files:
                key += "::" + test_key.split("[", 1)[0]
            weighted_keys.add(key)
        assert weighted_keys == set(weights)

    for nodeid, names in rows:
        assert sum(_matches(expression, names) for expression in entries.values()) == 1, nodeid
        for group, markers in (
            ("a", CI_INTEGRATIONS_A_SHARD_MARKERS),
            ("b", CI_INTEGRATIONS_B_SHARD_MARKERS),
        ):
            if f"ci_integrations_{group}" in names:
                assert len(names.intersection(markers)) == 1, nodeid
            else:
                assert names.isdisjoint(markers), nodeid
        lanes = names.intersection(CI_LANE_MARKERS)
        assert len(lanes) == 1, nodeid
        if "benchmark" in names or "ci_benchmark" in names:
            assert lanes == {"ci_benchmark"}
            assert names.isdisjoint(CI_INTEGRATIONS_SHARD_MARKERS)
            assert names.isdisjoint(CI_CORE_SHARD_MARKERS)
        if lanes == {"ci_integrations"}:
            assert len(names.intersection(CI_INTEGRATIONS_SHARD_MARKERS)) == 1
        else:
            assert names.isdisjoint(CI_INTEGRATIONS_SHARD_MARKERS)
        if lanes == {"ci_core"}:
            assert len(names.intersection(CI_CORE_SHARD_MARKERS)) == 1
        else:
            assert names.isdisjoint(CI_CORE_SHARD_MARKERS)
        if lanes == {"ci_persistence"}:
            assert len(names.intersection(CI_PERSISTENCE_SHARD_MARKERS)) == 1
        else:
            assert names.isdisjoint(CI_PERSISTENCE_SHARD_MARKERS)
