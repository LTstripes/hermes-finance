#!/usr/bin/env python3
"""Behavioral and Git/workflow regressions for conservative PR area filters."""

from __future__ import annotations

import json
import os
import re
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
    BACKEND_AREAS,
    FRONTEND_AREAS,
    classify_repo,
    selected_areas,
)
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
    def test_product_owners_keep_both_runtime_consumers(self) -> None:
        for path in (
            "backend/src/app.py",
            "backend/tests/test_api.py",
            "backend/migrations/README",
        ):
            with self.subTest(path=path):
                self.assertEqual(selected_areas([record(path)]), BACKEND_AREAS)
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

    def test_shared_build_dependency_release_and_unknown_inputs_are_full(self) -> None:
        for path in (
            "scripts/prepare-runtime.ps1",
            "scripts/tests/test-ci-paths.py",
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
                "release=false",
                "windows=true",
            ],
        )
        backend = self.commit("backend/src/app.py", b"synthetic backend\n")
        self.assertEqual(classify_repo(self.repo, self.base, backend), FULL)
        self.assertEqual(classify_repo(self.repo, self.base, frontend), FRONTEND_AREAS)

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
        cancelled: bool = False,
    ) -> bool:
        expr = self.condition(job)
        for label in ("ci:full", "ci:windows"):
            expr = expr.replace(
                f"contains(github.event.pull_request.labels.*.name, '{label}')",
                str(label in {value.lower() for value in labels}),
            )
        values = {
            "github.event_name": event,
            "needs.docs-only-classify.result": result,
            "needs.docs-only-classify.outputs.mode": mode,
            "needs.visual-audit-paths.outputs.run": visual_run,
        }
        values.update(
            {
                f"needs.docs-only-classify.outputs.{area}": (areas or {}).get(area, "")
                for area in AREAS
            }
        )
        for name in sorted(values, key=len, reverse=True):
            expr = expr.replace(name, repr(values[name]))
        expr = expr.replace("always()", "True").replace("!cancelled()", str(not cancelled))
        expr = expr.replace("!True", "False").replace("!False", "True")
        expr = " ".join(expr.replace("&&", " and ").replace("||", " or ").split())
        return bool(eval(expr, {"__builtins__": {}}, {}))

    def test_linux_job_conditions_for_every_area_and_failure_state(self) -> None:
        for job in ("backend-quality", "backend-tests", "frontend", "g04-browser"):
            owner = OWNERS[job]
            for selected in (FRONTEND_AREAS, BACKEND_AREAS, FULL):
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
        script = textwrap.dedent(final.split("python3 - <<'PY'\n", 1)[1]).split("\nPY", 1)[0]
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
