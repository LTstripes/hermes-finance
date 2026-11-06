#!/usr/bin/env python3
"""Behavioral and Git/workflow regressions for conservative PR area filters."""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ci_paths import (
    AREAS,
    AUTONOMOUS_BACKEND_TESTS,
    AUTONOMOUS_SCRIPT_TESTS,
    BACKEND_AREAS,
    BACKEND_TEST_AREAS,
    FRONTEND_AREAS,
    classify_repo,
    selected_areas,
)
from ci_run_receipt import inherited_verdict, timing_summary
from ci_run_receipt import main as receipt_main
from docs_only_ci import DiffRecord

ROOT = Path(__file__).resolve().parents[2]
FULL = frozenset(AREAS)
OWNERS = {
    "backend-quality": "backend",
    "backend-tests": "backend",
    "backend-timezone-windows": "windows",
    "frontend": "frontend",
    "g04-browser": "browser",
    "release-safety": "release",
    "release-runtime-safety": "release",
    "windows-production-smoke": "windows",
}

# These inputs must select both Windows and release checks, even when nested
# beneath an otherwise narrow product/prose prefix.
SAFETY_PATHS = (
    "scripts/prepare-runtime.ps1",
    "scripts/ci_paths.py",
    "scripts/nested/helper.py",
    "start-local.ps1",
    "frontend/src/repair.PS1",
    "frontend/src/scripts/build.ts",
    "packaging/package.json",
    "release/manifest.json",
    "installer/setup.wxs",
    "frontend/src/packaging/package.ts",
    "frontend/src/release/manifest.ts",
    "frontend/src/installer/setup.ts",
    "docs/history/installer/README.md",
    "backend/src/hermes_finance/runtime.py",
    "backend/src/hermes_finance/services/backups.py",
    "backend/src/hermes_finance/services/recovery.py",
    "backend/tests/test_startup.py",
    "backend/tests/test_recovery_process.py",
)


def record(path: str, **overrides: object) -> DiffRecord:
    fields = {
        "old_mode": "100644",
        "new_mode": "100644",
        "status": "M",
        "old_path": path,
        "new_path": path,
    }
    fields.update(overrides)
    return DiffRecord(**fields)


class SelectionTests(unittest.TestCase):
    def test_autonomous_test_consumers_and_unverified_tests(self) -> None:
        for name in AUTONOMOUS_BACKEND_TESTS:
            self.assertTrue((ROOT / "backend/tests" / name).is_file())
            self.assertEqual(
                selected_areas([record("backend/tests/" + name)]), {"backend"}
            )
        for path in AUTONOMOUS_SCRIPT_TESTS:
            self.assertTrue((ROOT / path).is_file())
            self.assertIn(
                "python3 " + path, (ROOT / ".github/workflows/ci.yml").read_text()
            )
            self.assertEqual(selected_areas([record(path)]), {"checks"})
        for path in (
            "frontend/src/lib/money.test.ts",
            "frontend/src/ui-v2/UiV2MonthSources.test.tsx",
        ):
            self.assertEqual(selected_areas([record(path)]), {"frontend"})
        self.assertEqual(
            selected_areas([record("backend/tests/test_unverified.py")]),
            BACKEND_TEST_AREAS,
        )
        for path in [*(ROOT / "frontend/src").rglob("*"),
                     *(ROOT / "frontend/e2e").rglob("*"),
                     *(ROOT / "frontend").glob("*.ts")]:
            if path.suffix not in {".ts", ".tsx"} or ".test." in path.name:
                continue
            # Product source must not consume unit tests. A new dependency must
            # be classified before standalone test changes can remain narrow.
            self.assertNotRegex(
                path.read_text(encoding="utf-8"),
                r'(?:from\s*|import\s*\()["\'][^"\']*\.test(?:[.\'"/])',
                str(path),
            )

    def test_backend_test_only_pr_omits_heavy_browser_and_visual(self) -> None:
        selected = selected_areas([record("backend/tests/test_accounts.py")])
        self.assertEqual(selected, frozenset({"backend"}))

    def test_frontend_source_selects_both_heavy_areas(self) -> None:
        selected = selected_areas([record("frontend/src/App.tsx")])
        self.assertTrue({"browser", "visual"}.issubset(selected))

    def test_product_owners_keep_both_runtime_consumers(self) -> None:
        for path in (
            "backend/src/app.py",
            "backend/migrations/README",
        ):
            with self.subTest(path=path):
                self.assertEqual(selected_areas([record(path)]), BACKEND_AREAS)
        self.assertEqual(
            selected_areas([record("backend/tests/test_api.py")]), BACKEND_TEST_AREAS
        )
        for path in (
            "frontend/src/App.tsx",
            "frontend/public/logo.svg",
            "frontend/e2e/journey.ts",
        ):
            with self.subTest(path=path):
                self.assertEqual(selected_areas([record(path)]), FRONTEND_AREAS)
        self.assertEqual(
            selected_areas([record("frontend/src/App.tsx"), record("backend/src/app.py")]),
            FULL,
        )
        self.assertEqual(
            selected_areas([record("README.md"), record("frontend/src/App.tsx")]),
            FRONTEND_AREAS,
        )
        self.assertEqual(
            selected_areas(
                [
                    record(
                        "frontend/src/New.tsx",
                        status="A",
                        old_mode="000000",
                        old_path=None,
                    )
                ]
            ),
            FRONTEND_AREAS,
        )

    def test_browser_fixture_import_closure_keeps_browser_coverage(self) -> None:
        # Inspect source only; never import/execute financial fixtures. Include
        # nested imports and traverse shared backend test helpers transitively.
        modules = {path.stem: path for path in (ROOT / "backend/tests").glob("*.py")}
        pending = list((ROOT / "frontend/e2e").rglob("*.py"))
        config = (ROOT / "frontend/playwright.config.ts").read_text(encoding="utf-8")
        for name in re.findall(r"-m uvicorn ([a-z_]+):", config):
            if name in modules:
                pending.append(modules[name])
        seen: set[Path] = set()
        while pending:
            path = pending.pop()
            if path in seen:
                continue
            seen.add(path)
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                elif isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                else:
                    continue
                for name in names:
                    module = modules.get(name.split(".")[0])
                    if module is None:
                        continue
                    relative = module.relative_to(ROOT).as_posix()
                    with self.subTest(consumer=path.name, dependency=relative):
                        self.assertIn("browser", selected_areas([record(relative)]))
                    pending.append(module)

    def test_backend_shared_fixture_and_configuration_inputs_keep_browser(self) -> None:
        for path in (
            "backend/tests/conftest.py",
            "backend/tests/_statement_pdf.py",
            "backend/tests/fixtures/synthetic.json",
            "backend/tests/payout_browser_fixture.py",
            "backend/tests/test_statement_import_apply.py",
            "backend/tests/test_instrument_trades_service.py",
        ):
            with self.subTest(path=path):
                self.assertEqual(selected_areas([record(path)]), BACKEND_AREAS)

    def test_shared_build_dependency_release_and_unknown_inputs_are_full(self) -> None:
        for path in (
            "scripts/prepare-runtime.ps1",
            "scripts/ci_paths.py",
            ".github/workflows/ci.yml",
            ".github/workflows/release.yml",
            ".github/actions/tool/action.yml",
            "backend/uv.lock",
            "backend/pyproject.toml",
            "backend/README.md",
            "backend/alembic.ini",
            "frontend/package.json",
            "frontend/package-lock.json",
            "frontend/vite.config.ts",
            "frontend/playwright.config.ts",
            "frontend/index.html",
            "frontend/scripts/audit.mjs",
            "docs/schemas/private_seed.schema.json",
            "docs/release-notes-1.3.0.md",
            "docs/release-notes/release-notes-1.2.0.md",
            "docs/unknown.md",
            ".gitattributes",
            "Backend/src/app.py",
            "new-product/file.py",
        ):
            with self.subTest(path=path):
                self.assertEqual(selected_areas([record(path)]), FULL)

    def test_safety_inputs_retain_release_and_windows(self) -> None:
        for path in SAFETY_PATHS:
            with self.subTest(path=path):
                self.assertTrue({"release", "windows"}.issubset(selected_areas([record(path)])))

    def test_unsafe_records_and_empty_evidence_cannot_omit_suites(self) -> None:
        for records in (
            None,
            [],
            [record("frontend/src/App.tsx", binary=True)],
            [record("frontend/src/App.tsx", status="D", new_mode="000000")],
            [record("frontend/src/App.tsx", status="R100", old_path="backend/src/app.py")],
            [
                record(
                    "frontend/src/App.tsx",
                    status="C100",
                    old_path="frontend/src/Old.tsx",
                )
            ],
            [record("frontend/src/App.tsx", new_mode="100755")],
            [record("frontend/src/App.tsx", old_mode="120000")],
            [record("frontend/src/App.tsx", new_mode="120000")],
            [record("frontend/src/submodule", new_mode="160000")],
            [record("frontend/src/../config.ts")],
            [record("frontend/src/bad\nname.ts")],
            [record("frontend/src/App.tsx", old_path="backend/src/app.py")],
        ):
            with self.subTest(records=records):
                self.assertEqual(selected_areas(records), FULL)

    def test_prose_retains_existing_narrow_policy(self) -> None:
        self.assertEqual(selected_areas([record("README.md")]), frozenset())
        self.assertEqual(selected_areas([record("docs/history/README.md")]), frozenset())
        self.assertEqual(selected_areas([record("docs/schemas/example.md")]), FULL)


class GitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.email", "ci-paths@example.com")
        self.git("config", "user.name", "ci-paths-synthetic")
        self.git("config", "core.autocrlf", "false")
        self.base = self.commit("README.md", b"synthetic base\n")

    def git(self, *args: str) -> str:
        return (
            subprocess.check_output(["git", "-C", str(self.repo), *args], stderr=subprocess.PIPE)
            .decode()
            .strip()
        )

    def commit(self, path: str, data: bytes) -> str:
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        self.git("add", "--", path)
        self.git("commit", "-m", "synthetic path fixture")
        return self.git("rev-parse", "HEAD")

    def test_actual_diff_cli_and_reclassification_after_synchronize(self) -> None:
        frontend = self.commit("frontend/src/App.tsx", b"synthetic frontend\n")
        self.assertEqual(classify_repo(self.repo, self.base, frontend), FRONTEND_AREAS)
        output = subprocess.check_output(
            [
                sys.executable,
                "-B",
                str(ROOT / "scripts/ci_paths.py"),
                "--repo",
                str(self.repo),
                "--base",
                self.base,
                "--head",
                frontend,
            ],
            text=True,
        )
        self.assertEqual(
            output.splitlines(),
            [
                "mode=full",
                "backend=false",
                "frontend=true",
                "browser=true",
                "visual=true",
                "release=false",
                "windows=true",
            ],
        )
        backend = self.commit("backend/src/app.py", b"synthetic backend\n")
        self.assertEqual(classify_repo(self.repo, self.base, backend), FULL)
        self.assertEqual(classify_repo(self.repo, self.base, frontend), FRONTEND_AREAS)

    def test_standalone_backend_test_and_shared_fixture_actual_diffs(self) -> None:
        head = self.commit("backend/tests/test_accounts.py", b"synthetic test module\n")
        self.assertEqual(
            classify_repo(self.repo, self.base, head), frozenset({"backend"})
        )
        docs = self.commit("README.md", b"synthetic docs\n")
        self.assertEqual(
            classify_repo(self.repo, self.base, docs), frozenset({"backend"})
        )
        fixture = self.commit("backend/tests/_statement_pdf.py", b"synthetic helper\n")
        self.assertEqual(classify_repo(self.repo, docs, fixture), BACKEND_AREAS)
        source = self.commit(
            "backend/src/hermes_finance/services/accounts.py", b"synthetic service\n"
        )
        self.assertEqual(classify_repo(self.repo, fixture, source), BACKEND_AREAS)

    def test_safety_inputs_from_actual_git_diffs(self) -> None:
        for path in (
            "scripts/prepare-runtime.ps1",
            "frontend/src/repair.ps1",
            "frontend/src/installer/setup.ts",
            "backend/src/hermes_finance/services/recovery.py",
        ):
            with self.subTest(path=path):
                head = self.commit(path, b"synthetic safety input\n")
                self.assertTrue(
                    {"release", "windows"}.issubset(classify_repo(self.repo, self.base, head))
                )
                self.base = head

    def test_bad_shas_missing_git_empty_diff_and_binary_are_full(self) -> None:
        head = self.commit("frontend/src/App.tsx", b"binary\0payload")
        self.assertEqual(classify_repo(self.repo, self.base, head), FULL)
        for base, candidate in (
            (self.base, self.base),
            ("not-a-sha", head),
            ("f" * 40, head),
        ):
            self.assertEqual(classify_repo(self.repo, base, candidate), FULL)
        with patch("ci_paths._load_records", side_effect=OSError("git unavailable")):
            self.assertEqual(classify_repo(self.repo, self.base, head), FULL)

    def test_rename_and_delete_are_full(self) -> None:
        previous = self.commit("frontend/src/Old.tsx", b"synthetic frontend\n")
        self.git("mv", "frontend/src/Old.tsx", "frontend/src/New.tsx")
        self.git("commit", "-m", "synthetic rename")
        renamed = self.git("rev-parse", "HEAD")
        self.assertEqual(classify_repo(self.repo, previous, renamed), FULL)
        self.git("rm", "frontend/src/New.tsx")
        self.git("commit", "-m", "synthetic delete")
        self.assertEqual(classify_repo(self.repo, renamed, self.git("rev-parse", "HEAD")), FULL)

    def test_base_advance_cannot_hide_shared_inputs_in_pr_history(self) -> None:
        self.commit("scripts/helper.py", b"synthetic shared input\n")
        head = self.commit("README.md", b"PR prose\n")
        self.git("checkout", "-b", "advanced-base", self.base)
        self.commit("README.md", b"advanced main prose\n")
        advanced = self.commit("scripts/helper.py", b"synthetic shared input\n")
        # Endpoint diff is docs-only; PR-owned history still contains scripts.
        self.assertEqual(classify_repo(self.repo, advanced, head), FULL)

    def test_prose_blobs_and_disconnected_history_fail_closed(self) -> None:
        prose = self.commit("README.md", b"ordinary prose\n")
        self.assertEqual(classify_repo(self.repo, self.base, prose), frozenset())
        output = subprocess.check_output(
            [
                sys.executable,
                "-B",
                str(ROOT / "scripts/ci_paths.py"),
                "--repo",
                str(self.repo),
                "--base",
                self.base,
                "--head",
                prose,
            ],
            text=True,
        )
        self.assertEqual(
            output.splitlines(),
            ["mode=docs-only"] + [f"{area}=false" for area in AREAS],
        )
        binary = self.commit("README.md", b"prose\0hidden")
        self.assertEqual(classify_repo(self.repo, self.base, binary), FULL)
        self.git("checkout", "--orphan", "disconnected")
        self.git("rm", "-rf", ".")
        orphan = self.commit("frontend/src/App.tsx", b"synthetic orphan\n")
        self.assertEqual(classify_repo(self.repo, self.base, orphan), FULL)


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    def job(self, job: str) -> str:
        return re.split(r"\n  [a-z][a-z0-9-]*:\n", self.workflow.split(f"  {job}:\n", 1)[1])[0]

    def condition(self, job: str) -> str:
        expr = self.job(job).split("    if:", 1)[1].split("    runs-on:", 1)[0].strip()
        return expr.removeprefix(">-").strip()

    def runs(
        self,
        job: str,
        *,
        event: str = "pull_request",
        result: str = "success",
        mode: str = "full",
        areas: dict[str, str] | None = None,
        labels: tuple[str, ...] = (),
        visual_run: str = "false",
        visual_result: str = "success",
        cancelled: bool = False,
        action: str = "synchronize",
        label: str = "",
    ) -> bool:
        expr = self.condition(job)
        for control_label in ("ci:full", "ci:windows"):
            expr = expr.replace(
                f"contains(github.event.pull_request.labels.*.name, '{control_label}')",
                str(control_label in {value.lower() for value in labels}),
            )
        values = {
            "github.event_name": event,
            "github.event.action": action,
            "github.event.label.name": label.lower(),
            "needs.docs-only-classify.result": result,
            "needs.docs-only-classify.outputs.mode": mode,
            "needs.visual-audit-paths.outputs.run": visual_run,
            "needs.visual-audit-paths.result": visual_result,
        }
        values.update(
            {
                f"needs.docs-only-classify.outputs.{area}": (areas or {}).get(area, "")
                for area in AREAS
            }
        )
        for name in sorted(values, key=len, reverse=True):
            expr = expr.replace(name, repr(values[name]))
        expr = expr.replace("!(", "not (")
        expr = expr.replace("always()", "True").replace(
            "!cancelled()", str(not cancelled)
        )
        expr = expr.replace("!True", "False").replace("!False", "True")
        expr = " ".join(expr.replace("&&", " and ").replace("||", " or ").split())
        return bool(eval(expr, {"__builtins__": {}}, {}))

    def test_label_event_matrix_and_failed_same_head_cannot_turn_green(self) -> None:
        for job in (*OWNERS, "visual-audit", "docs-fast-path"):
            for label in ("triage", "ci:full-extra", ""):
                self.assertFalse(
                    self.runs(
                        job,
                        action="labeled",
                        label=label,
                        labels=("ci:full", "ci:windows"),
                    )
                )
            for label in ("ci:full", "ci:windows"):
                self.assertEqual(
                    self.runs(job, action="labeled", label=label, labels=(label,)),
                    self.runs(job, labels=(label,)),
                )
        current = {"id": 20, "head_sha": "synthetic"}
        previous = {
            "id": 19,
            "head_sha": "synthetic",
            "event": "pull_request",
            "pull_requests": [{"number": 3}],
            "status": "completed",
            "conclusion": "success",
            "html_url": "synthetic-run",
        }
        self.assertEqual(inherited_verdict([previous], current, 3), previous)
        for status, conclusion in (
            ("completed", "failure"),
            ("completed", "cancelled"),
            ("in_progress", None),
            ("queued", None),
            ("completed", "skipped"),
        ):
            with self.assertRaises(ValueError):
                inherited_verdict(
                    [
                        {**previous, "id": 18},
                        {**previous, "status": status, "conclusion": conclusion},
                    ],
                    current,
                    3,
                )
        for runs in (
            [],
            [{**previous, "head_sha": "other"}],
            [{**previous, "pull_requests": []}],
        ):
            with self.assertRaises(ValueError):
                inherited_verdict(runs, current, 3)
        final = self.job("ci-ok")
        self.assertIn("run: python3 scripts/ci_run_receipt.py", final)
        self.assertIn("ORGANIZATIONAL_LABEL:", final)
        self.assertIn("actions: read", final)

    def test_attempt_receipt_separates_rerun_pause_from_execution(self) -> None:
        def run(number, start):
            return {
                "run_attempt": number,
                "run_started_at": f"2040-01-01T{start}Z",
                "status": "completed",
            }

        def job(start, end):
            return {
                "name": "synthetic",
                "started_at": f"2040-01-01T{start}Z",
                "completed_at": f"2040-01-01T{end}Z",
                "steps": [],
            }

        summary = timing_summary(
            [
                (run(1, "00:00:00"), [job("00:00:00", "00:19:00")]),
                (run(2, "01:21:31"), [job("01:21:31", "01:29:56")]),
            ],
            "2040-01-01T01:29:56Z",
        )
        self.assertIn("| 1 | 1140 | — |", summary)
        self.assertIn("| 2 | 505 | 3751 |", summary)
        self.assertIn("1140s", summary)

    def test_receipt_api_unavailable_cannot_green_an_organizational_label(self) -> None:
        for organizational, expected in (("true", 1), ("false", 0)):
            with patch.dict(os.environ, {"ORGANIZATIONAL_LABEL": organizational, "GITHUB_RUN_ID": "20"}), patch("ci_run_receipt.get", side_effect=OSError("synthetic unavailable")):
                self.assertEqual(receipt_main(), expected)

    def test_linux_job_conditions_for_every_area_and_failure_state(self) -> None:
        for job in ("backend-quality", "backend-tests", "frontend", "g04-browser"):
            owner = OWNERS[job]
            for selected in (FRONTEND_AREAS, BACKEND_AREAS, BACKEND_TEST_AREAS, FULL):
                areas = {area: str(area in selected).lower() for area in AREAS}
                with self.subTest(job=job, selected=selected):
                    self.assertEqual(self.runs(job, areas=areas), owner in selected)
            for result in ("failure", "cancelled", "skipped", ""):
                self.assertTrue(
                    self.runs(job, result=result, areas={area: "false" for area in AREAS})
                )
            for output in ("", "garbage", "TRUE", "true"):
                self.assertTrue(self.runs(job, areas={owner: output}))
            self.assertTrue(self.runs(job, event="push", mode="docs-only", areas={owner: "false"}))
            self.assertFalse(self.runs(job, cancelled=True))
            self.assertFalse(self.runs(job, mode="docs-only"))

    def test_windows_jobs_follow_classifier_outputs_and_fail_closed(self) -> None:
        for job in (
            "backend-timezone-windows",
            "release-safety",
            "release-runtime-safety",
            "windows-production-smoke",
        ):
            owner = OWNERS[job]
            for mode in ("full", "docs-only", ""):
                for result in ("success", "failure", "cancelled", "skipped", ""):
                    for enabled in ("true", "false", "", "garbage", "TRUE"):
                        areas = {area: "false" for area in AREAS}
                        areas[owner] = enabled
                        args = {"mode": mode, "result": result, "areas": areas}
                        with self.subTest(job=job, **args):
                            self.assertEqual(
                                self.runs(job, **args),
                                result != "success" or enabled != "false",
                            )
                            for label in ("ci:windows", "ci:full"):
                                self.assertTrue(self.runs(job, labels=(label,), **args))
                            self.assertTrue(self.runs(job, event="push", **args))
                            self.assertFalse(self.runs(job, cancelled=True, **args))
                            self.assertFalse(
                                self.runs(job, labels=("ci:full",), cancelled=True, **args)
                            )
            # The other output must not own this job.
            areas = {area: "true" for area in AREAS}
            areas[owner] = "false"
            self.assertFalse(self.runs(job, areas=areas))
            self.assertFalse(
                self.runs(job, areas=areas, labels=("ci:windows-extra", "ci:full-extra"))
            )
            self.assertTrue(self.runs(job, areas=areas, labels=("CI:FULL",)))

    def test_safety_paths_reach_windows_jobs_without_labels(self) -> None:
        for path in SAFETY_PATHS:
            selected = selected_areas([record(path)])
            areas = {area: str(area in selected).lower() for area in AREAS}
            for job in (
                "backend-timezone-windows",
                "release-safety",
                "release-runtime-safety",
                "windows-production-smoke",
            ):
                with self.subTest(path=path, job=job):
                    self.assertTrue(self.runs(job, areas=areas))

    def test_classifier_to_heavy_job_acceptance_matrix(self) -> None:
        for paths, browser, visual in (
            (("backend/tests/test_accounts.py",), False, False),
            (("docs/DEVELOPMENT.md",), False, False),
            (("frontend/src/App.tsx",), True, True),
            (("backend/src/hermes_finance/api/accounts.py",), True, False),
            (("backend/src/hermes_finance/services/accounts.py",), True, False),
            (("backend/migrations/versions/9999_synthetic.py",), True, False),
            (("backend/tests/test_api.py", "frontend/src/App.tsx"), True, True),
            (("backend/uv.lock",), True, True),
            (("scripts/ci_paths.py",), True, True),
            (("unknown/input",), True, True),
        ):
            selected = selected_areas([record(path) for path in paths])
            areas = {area: str(area in selected).lower() for area in AREAS}
            mode = "full" if selected else "docs-only"
            with self.subTest(paths=paths):
                self.assertEqual(self.runs("g04-browser", mode=mode, areas=areas), browser)
                self.assertEqual(
                    self.runs("visual-audit", visual_run=areas["visual"]), visual
                )

    def test_visual_gate_fails_closed_and_cancellation_is_respected(self) -> None:
        for result in ("failure", "cancelled", "skipped", ""):
            self.assertTrue(self.runs("visual-audit", visual_result=result))
        for output in ("", "garbage", "true", "TRUE"):
            self.assertTrue(self.runs("visual-audit", visual_run=output))
        for event in ("pull_request", "push"):
            self.assertFalse(self.runs("visual-audit", event=event, cancelled=True))
        visual_filter = self.job("visual-audit-paths")
        self.assertIn("needs: docs-only-classify", visual_filter)
        self.assertIn("set -euo pipefail", visual_filter)
        self.assertIn(
            "CLASSIFICATION_RESULT: $" + "{{ needs.docs-only-classify.result }}", visual_filter
        )
        self.assertIn(
            "VISUAL_AREA: $" + "{{ needs.docs-only-classify.outputs.visual }}", visual_filter
        )
        self.assertIn(
            'if [ "$CLASSIFICATION_RESULT" != "success" ] || [ "$VISUAL_AREA" != "false" ]; then',
            visual_filter,
        )
        visual_job = self.job("visual-audit")
        self.assertIn(
            "FORCE_FULL: $" + "{{ contains(github.event.pull_request.labels.*.name, 'ci:full') }}",
            visual_job,
        )
        self.assertIn('[ "$FORCE_FULL" != "true" ]', visual_job)
        self.assertNotIn("continue-on-error", visual_job)

    def test_visual_shell_fallback_and_full_label_without_network(self) -> None:
        bash = shutil.which("bash")
        if bash is None:
            git = shutil.which("git")
            candidate = Path(git or "").parent.parent / "bin/bash.exe"
            if candidate.is_file():
                bash = str(candidate)
        if bash is None:
            self.skipTest("Bash unavailable for workflow shell regression")
        filter_job = self.job("visual-audit-paths")
        decision = filter_job.split('          if [ "$CLASSIFICATION_RESULT"', 1)[1]
        decision = 'if [ "$CLASSIFICATION_RESULT"' + decision.split(
            '          echo "run=$should_run"', 1
        )[0]
        for result, area, legacy, expected in (
            ("success", "false", "false", "false"),
            ("success", "false", "true", "true"),
            ("success", "true", "false", "true"),
            ("success", "", "false", "true"),
            ("success", "garbage", "false", "true"),
            ("failure", "false", "false", "true"),
            ("skipped", "false", "false", "true"),
            ("", "false", "false", "true"),
        ):
            with self.subTest(result=result, area=area, legacy=legacy):
                output = subprocess.check_output(
                    [bash, "-c", decision + '\nprintf "%s" "$should_run"'],
                    env={
                        **os.environ,
                        "CLASSIFICATION_RESULT": result,
                        "VISUAL_AREA": area,
                        "should_run": legacy,
                    },
                    text=True,
                )
                self.assertEqual(output, expected)
        identity = self.job("visual-audit").split(
            "          set -euo pipefail\n", 1
        )[1].split("\n      - name: Run synthetic visual audit", 1)[0]
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            output_file = Path(directory) / "outputs"
            completed = subprocess.run(
                [bash, "-c", 'git() { echo "unexpected git" >&2; return 1; }\n' + identity],
                env={
                    **os.environ,
                    "EVENT_NAME": "pull_request",
                    "DUPLICATE_PATHS": "true",
                    "FORCE_FULL": "true",
                    "GITHUB_OUTPUT": str(output_file),
                },
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stderr, "")
            self.assertEqual(output_file.read_text().strip(), "omit=false")

    def test_full_label_bypasses_docs_area_and_visual_filters(self) -> None:
        for job in (*OWNERS, "visual-audit"):
            with self.subTest(job=job):
                self.assertTrue(
                    self.runs(
                        job,
                        mode="docs-only",
                        areas={area: "false" for area in AREAS},
                        labels=("ci:full",),
                        visual_run="false",
                    )
                )
        self.assertFalse(self.runs("visual-audit"))
        self.assertTrue(self.runs("visual-audit", visual_run="true"))
        self.assertTrue(self.runs("visual-audit", event="push"))
        self.assertTrue(self.runs("docs-fast-path", mode="docs-only"))
        for label in ("ci:full", "ci:windows"):
            # The docs verdict requires all product jobs skipped; opt-in jobs
            # are judged by ci-ok rather than a false documentation verdict.
            self.assertFalse(self.runs("docs-fast-path", mode="docs-only", labels=(label,)))
        for job in ("privacy", "docs-only-classify", "visual-audit-paths", "ci-ok"):
            if job == "privacy":
                self.assertNotIn("    if:", self.job(job))
            else:
                self.assertTrue(self.runs(job, labels=("ci:full",)))

    def test_ci_ok_waits_for_every_job_and_executes_the_actual_verdict(self) -> None:
        jobs = set(
            re.findall(
                r"^  ([a-z][a-z0-9-]*):$",
                self.workflow.split("jobs:\n", 1)[1],
                re.MULTILINE,
            )
        )
        final = self.job("ci-ok")
        dependencies = re.findall(r"^      - ([a-z][a-z0-9-]*)$", final, re.MULTILINE)
        self.assertCountEqual(dependencies, jobs - {"ci-ok"})
        self.assertEqual(self.condition("ci-ok"), "always()")
        self.assertIn("    name: ci-ok\n", final)
        self.assertIn("    runs-on: ubuntu-latest\n", final)
        self.assertIn("NEEDS_JSON: $" + "{{ toJSON(needs) }}", final)
        script = textwrap.dedent(
            final.split("python3 - <<'PY'\n", 1)[1].split("          PY", 1)[0]
        )
        for job in dependencies:
            for result in ("success", "skipped", "failure", "cancelled", "unknown"):
                results = {name: {"result": "skipped"} for name in dependencies}
                results[job] = {"result": result}
                completed = subprocess.run(
                    [sys.executable, "-c", script],
                    capture_output=True,
                    text=True,
                    env={**os.environ, "NEEDS_JSON": json.dumps(results)},
                    check=False,
                )
                with self.subTest(job=job, result=result):
                    self.assertEqual(completed.returncode == 0, result in {"success", "skipped"})
                    self.assertIn(f"{job}: {result}", completed.stdout)

    def test_ci_ok_summary_preserves_skips_and_failure_results(self) -> None:
        final = self.job("ci-ok")
        script = textwrap.dedent(
            final.split("python3 - <<'PY'\n", 1)[1].split("          PY", 1)[0]
        )
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            summary = Path(directory) / "summary.md"
            results = {
                "privacy": {"result": "success"},
                "visual-audit": {"result": "skipped"},
                "g04-browser": {"result": "failure"},
            }
            completed = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "NEEDS_JSON": json.dumps(results),
                    "GITHUB_STEP_SUMMARY": str(summary),
                },
                check=False,
            )
            self.assertNotEqual(completed.returncode, 0)
            content = summary.read_text(encoding="utf-8")
            for name, job in results.items():
                self.assertIn(f"| {name} | {job['result']} |", content)
            self.assertIn("g04-browser", completed.stderr)

    def test_wiring_preserves_triggers_and_full_shared_inputs(self) -> None:
        trigger = self.workflow.split("jobs:", 1)[0]
        self.assertIn(
            "\n  pull_request:\n    types: [opened, synchronize, reopened, labeled]",
            trigger,
        )
        self.assertIn("branches: [main]", trigger)
        self.assertNotIn("paths:", trigger)
        self.assertNotIn("paths-ignore", trigger)
        self.assertIn("python3 scripts/tests/test-ci-paths.py", self.workflow)
        self.assertIn(
            'python3 scripts/ci_paths.py --base "$BASE_SHA" --head "$HEAD_SHA" >> "$GITHUB_OUTPUT"',
            self.workflow,
        )
        for area in AREAS:
            self.assertIn("steps.classify.outputs." + area, self.workflow)
        for job in OWNERS:
            expected_needs = (
                "needs: [docs-only-classify, privacy]"
                if job == "g04-browser"
                else "needs: docs-only-classify"
            )
            self.assertIn(expected_needs, self.job(job))
        release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertNotIn("ci_paths.py", release)
        for action in re.findall(r"uses: ([^\s]+)", self.workflow):
            self.assertRegex(action, r"@[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
