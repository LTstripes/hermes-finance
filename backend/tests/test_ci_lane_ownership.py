"""Fail-closed checks for exclusive backend CI lane ownership."""

from __future__ import annotations

from _test_taxonomy import (
    CI_LANE_MARKERS,
    ci_lane_for_test_path,
    iter_backend_test_files,
    semantic_markers_for,
)


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
