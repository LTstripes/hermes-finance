"""Test path bootstrap and semantic/CI lane marker registration."""

from __future__ import annotations

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))


def pytest_collection_modifyitems(items) -> None:
    """Apply additive markers and fail closed on ambiguous CI ownership."""

    import pytest
    from _test_taxonomy import CI_LANE_MARKERS, ci_lane_for_test_path, semantic_markers_for

    ownership_errors: list[str] = []
    for item in items:
        test_path = Path(str(item.path))
        for marker in semantic_markers_for(test_path):
            item.add_marker(marker)

        lane = ci_lane_for_test_path(test_path)
        existing_lanes = {
            marker.name for marker in item.iter_markers() if marker.name in CI_LANE_MARKERS
        }
        if lane is None:
            ownership_errors.append(f"unclassified: {item.nodeid}")
        elif existing_lanes and existing_lanes != {lane}:
            ownership_errors.append(
                f"ambiguous: {item.nodeid} has {sorted(existing_lanes)}, expected {lane}"
            )
        else:
            item.add_marker(lane)

    if ownership_errors:
        details = "\n".join(sorted(ownership_errors))
        raise pytest.UsageError(
            f"Every backend test must have exactly one CI lane marker:\n{details}"
        )
