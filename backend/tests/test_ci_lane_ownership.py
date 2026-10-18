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
    CI_INTEGRATIONS_SHARD_MARKERS,
    CI_INTEGRATIONS_SHARD_WEIGHTS,
    CI_LANE_MARKERS,
    TESTS_ROOT,
    ci_core_shard_for_test_path,
    ci_integrations_shard_for_test_path,
    ci_lane_for_test_path,
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


def test_integration_files_have_one_exclusive_balanced_shard() -> None:
    totals = {marker: 0.0 for marker in CI_INTEGRATIONS_SHARD_MARKERS}
    for test_path in _integration_files():
        shard = ci_integrations_shard_for_test_path(test_path)
        assert shard in CI_INTEGRATIONS_SHARD_MARKERS
        key = test_path.relative_to(TESTS_ROOT).as_posix()
        totals[shard] += CI_INTEGRATIONS_SHARD_WEIGHTS[key]

    assert set(totals) == set(CI_INTEGRATIONS_SHARD_MARKERS)
    heavier = max(totals.values())
    lighter = min(totals.values())
    assert lighter > 0
    assert heavier / lighter <= 1.15
    largest = max(CI_INTEGRATIONS_SHARD_WEIGHTS.values())
    assert largest * 2 < sum(CI_INTEGRATIONS_SHARD_WEIGHTS.values())


def test_shard_markers_are_not_parent_lanes() -> None:
    assert set(CI_CORE_SHARD_MARKERS).isdisjoint(CI_LANE_MARKERS)
    assert set(CI_INTEGRATIONS_SHARD_MARKERS).isdisjoint(CI_LANE_MARKERS)


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


def test_backend_matrix_keeps_full_lanes_and_forty_minute_integration_shards() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    entries = dict((lane, (marker, timeout)) for lane, marker, timeout in _workflow_entries())

    assert list(entries) == [
        "core-a",
        "core-b",
        "persistence",
        "integrations-a",
        "integrations-b",
        "runtime-release",
        "benchmark",
    ]
    assert entries["integrations-a"] == ("ci_integrations and ci_integrations_a", 40)
    assert entries["integrations-b"] == ("ci_integrations and ci_integrations_b", 40)
    for lane in ("core-a", "core-b", "persistence", "runtime-release", "benchmark"):
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
    shard_exprs = (entries["integrations-a"], entries["integrations-b"])

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
    assert set(shards[0]).isdisjoint(shards[1])
    assert Counter(parent) == combined

    for nodeid, names in rows:
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
