"""Test path bootstrap and semantic/CI lane marker registration."""

from __future__ import annotations

import sys
from pathlib import Path
from shutil import copyfile

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))


@pytest.fixture(scope="session")
def source_returns_database_factory(tmp_path_factory):
    """Build the source-reader schema once; keep real commits isolated per case."""
    from hermes_finance.database import create_database
    from hermes_finance.persistence import Base

    template = create_database(tmp_path_factory.mktemp("source-returns-schema") / "empty.db")
    try:
        Base.metadata.create_all(template.engine)
    finally:
        # Close every SQLite handle before copying the pristine, committed schema.
        template.engine.dispose()

    def factory(directory):
        database_path = directory / "unbound-provisional.db"
        copyfile(template.database_path, database_path)
        return create_database(database_path)

    return factory


def pytest_collection_modifyitems(items) -> None:
    """Apply additive markers and fail closed on ambiguous CI ownership."""

    import pytest
    from _test_taxonomy import (
        CI_CORE_SHARD_MARKERS,
        CI_INTEGRATIONS_A_SHARD_MARKERS,
        CI_INTEGRATIONS_B_SHARD_MARKERS,
        CI_INTEGRATIONS_SHARD_MARKERS,
        CI_LANE_MARKERS,
        CI_PERSISTENCE_SHARD_MARKERS,
        ci_core_shard_for_test_path,
        ci_integrations_a_shard_for_test_node,
        ci_integrations_b_shard_for_test_node,
        ci_integrations_shard_for_test_path,
        ci_lane_for_test_path,
        ci_persistence_shard_for_test_path,
        semantic_markers_for,
    )

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
            if lane == "ci_core":
                shard = ci_core_shard_for_test_path(test_path)
                shard_markers = CI_CORE_SHARD_MARKERS
                kind = "core"
            elif lane == "ci_persistence":
                shard = ci_persistence_shard_for_test_path(test_path)
                shard_markers = CI_PERSISTENCE_SHARD_MARKERS
                kind = "persistence"
            elif lane == "ci_integrations":
                shard = ci_integrations_shard_for_test_path(test_path)
                shard_markers = CI_INTEGRATIONS_SHARD_MARKERS
                kind = "integrations"
            else:
                shard = None
                shard_markers = ()
                kind = ""
            if kind and shard not in shard_markers:
                ownership_errors.append(
                    f"unsharded {kind} test: {item.nodeid} has no valid {kind} shard"
                )
            elif kind:
                item.add_marker(shard)
                if shard == "ci_integrations_a":
                    a_shard = ci_integrations_a_shard_for_test_node(test_path, item.nodeid)
                    if a_shard not in CI_INTEGRATIONS_A_SHARD_MARKERS:
                        ownership_errors.append(f"unsharded integrations-a test: {item.nodeid}")
                    else:
                        item.add_marker(a_shard)
                elif shard == "ci_integrations_b":
                    b_shard = ci_integrations_b_shard_for_test_node(test_path, item.nodeid)
                    if b_shard not in CI_INTEGRATIONS_B_SHARD_MARKERS:
                        ownership_errors.append(f"unsharded integrations-b test: {item.nodeid}")
                    else:
                        item.add_marker(b_shard)

    if ownership_errors:
        details = "\n".join(sorted(ownership_errors))
        raise pytest.UsageError(
            f"Every backend test must have exactly one CI lane marker:\n{details}"
        )
