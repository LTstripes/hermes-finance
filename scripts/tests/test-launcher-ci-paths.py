#!/usr/bin/env python3
"""Deterministic regression tests for Windows launcher CI path filtering."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from launcher_ci_paths import is_launcher_ci_path, should_run  # noqa: E402


class LauncherCiPathTests(unittest.TestCase):
    def test_launcher_package_schema_and_ci_wiring_run_the_harness(self) -> None:
        paths = [
            "launcher/windows/package.ps1",
            "launcher/windows/install.ps1",
            "launcher/windows/HermesFinance.Launcher/MainForm.cs",
            "launcher/windows/HermesFinance.Launcher.SafetyTests/Program.cs",
            "launcher/windows/assets/hermes-finance-cat.ico",
            "launcher/windows/config.example.json",
            "launcher/windows/README.md",
            "scripts/launcher-schema-check.py",
            "scripts/tests/test-windows-launcher-package.ps1",
            "scripts/launcher_ci_paths.py",
            ".github/workflows/ci.yml",
        ]
        for path in paths:
            with self.subTest(path=path):
                self.assertTrue(is_launcher_ci_path(path))
        self.assertTrue(should_run(paths))

    def test_schema_check_or_package_smoke_alone_runs_the_harness(self) -> None:
        self.assertTrue(should_run(["scripts/launcher-schema-check.py"]))
        self.assertTrue(should_run(["scripts/tests/test-windows-launcher-package.ps1"]))
        self.assertTrue(should_run(["launcher/windows/HermesFinance.Launcher/ProfileValidator.cs"]))

    def test_frontend_backend_and_runtime_smoke_paths_skip_the_harness(self) -> None:
        paths = [
            "frontend/src/pages/DashboardPage.tsx",
            "frontend/src/styles/global.css",
            "frontend/package.json",
            "backend/src/hermes_finance/api/routes.py",
            "backend/tests/test_health.py",
            "backend/tests/test_launcher_schema_check.py",
            "backend/migrations/versions/0001_example.py",
            "docs/MASTER_SPEC.md",
            "README.md",
            "scripts/start-local.ps1",
            "scripts/prepare-runtime.ps1",
            "scripts/prepare-runtime-dependencies.ps1",
            "scripts/tests/test-prepared-runtime.ps1",
            "scripts/launcher-production-backup.py",
        ]
        for path in paths:
            with self.subTest(path=path):
                self.assertFalse(is_launcher_ci_path(path))
        self.assertFalse(should_run(paths))

    def test_one_relevant_path_among_frontend_changes_runs_the_harness(self) -> None:
        self.assertTrue(
            should_run(
                [
                    "frontend/src/pages/DashboardPage.tsx",
                    "scripts/launcher-schema-check.py",
                ]
            )
        )

    def test_windows_separators_and_empty_changes_are_deterministic(self) -> None:
        self.assertTrue(is_launcher_ci_path(r"launcher\windows\package.ps1"))
        self.assertTrue(is_launcher_ci_path("./launcher/windows/package.ps1"))
        self.assertTrue(is_launcher_ci_path("launcher/windows"))
        self.assertFalse(is_launcher_ci_path("launcher/windows-extra/package.ps1"))
        self.assertFalse(should_run([]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
