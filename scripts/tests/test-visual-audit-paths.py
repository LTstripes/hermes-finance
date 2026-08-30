#!/usr/bin/env python3
"""Deterministic regression tests for synthetic visual-audit path filtering."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from visual_audit_paths import is_visual_audit_path, should_run  # noqa: E402


class VisualAuditPathTests(unittest.TestCase):
    def test_frontend_ui_and_harness_paths_run_the_audit(self) -> None:
        paths = [
            "frontend/src/pages/DashboardPage.tsx",
            "frontend/src/styles/global.css",
            "frontend/e2e/visual-fixtures.ts",
            "frontend/scripts/run-visual-audit.mjs",
            "frontend/playwright.visual.config.ts",
            "frontend/package-lock.json",
            ".github/workflows/ci.yml",
        ]
        for path in paths:
            with self.subTest(path=path):
                self.assertTrue(is_visual_audit_path(path))

    def test_backend_and_documentation_only_paths_skip_the_audit(self) -> None:
        paths = [
            "backend/src/hermes_finance/api.py",
            "backend/tests/test_health.py",
            "docs/RELEASE_AUTOMATION.md",
            "README.md",
            "frontend/README.md",
        ]
        for path in paths:
            with self.subTest(path=path):
                self.assertFalse(is_visual_audit_path(path))
        self.assertFalse(should_run(paths))

    def test_windows_separators_and_empty_changes_are_deterministic(self) -> None:
        self.assertTrue(is_visual_audit_path(r"frontend\src\App.tsx"))
        self.assertTrue(is_visual_audit_path("./frontend/src/App.tsx"))
        self.assertFalse(should_run([]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
