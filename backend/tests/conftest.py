"""Test path bootstrap and semantic lane marker registration."""

from __future__ import annotations

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))


def pytest_collection_modifyitems(items) -> None:
    """Apply additive semantic markers from the test file's stable ownership lane."""

    from _test_taxonomy import semantic_markers_for

    for item in items:
        for marker in semantic_markers_for(Path(str(item.path))):
            item.add_marker(marker)
