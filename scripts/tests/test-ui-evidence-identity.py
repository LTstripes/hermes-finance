#!/usr/bin/env python3
"""Identity regressions for exact-head UI evidence (#669).

These tests do not launch runners, browsers, or the product suites.
"""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from ui_evidence_identity import (  # noqa: E402
    BUILD_MEANING,
    EVIDENCE_GREP,
    EVIDENCE_VISUAL_COMMAND,
    OMIT_ENV,
    SCREENSHOT_MEANING,
    SCREENSHOT_RUNTIME,
    build_provenance,
    duplicate_visual_paths,
    evidence_patterns_from_workflow,
    main,
    omit_duplicate_1440,
    package_errors,
    provenance_errors,
    publication_allowed,
    publish_package,
)

CI_PATH = ROOT / ".github" / "workflows" / "ci.yml"
UI_PATH = ROOT / ".github" / "workflows" / "ui-v2-evidence.yml"
CONFIG_PATH = ROOT / "frontend" / "playwright.visual.config.ts"
HEAD = "a" * 40
BASE = "b" * 40
MERGE_COMMIT = "c" * 40
TREE = "d" * 40
OTHER_TREE = "e" * 40
PATTERNS = ("frontend/**", ".github/workflows/ui-v2-evidence.yml")


def _same_tree(**overrides: object) -> bool:
    facts: dict[str, object] = {
        "event_name": "pull_request",
        "duplicate_paths": True,
        "head_sha": HEAD,
        "resolved_head_sha": HEAD,
        "base_sha": BASE,
        "checkout_sha": MERGE_COMMIT,
        "head_tree": TREE,
        "merge_tree": TREE,
        "checkout_tree": TREE,
    }
    facts.update(overrides)
    return omit_duplicate_1440(**facts)  # type: ignore[arg-type]


class DuplicateDecisionTests(unittest.TestCase):
    def test_equal_trees_omit_only_the_proven_1440_duplicate(self) -> None:
        self.assertTrue(_same_tree())
        self.assertTrue(_same_tree(checkout_sha=HEAD))

    def test_different_head_and_merge_trees_stay_separate(self) -> None:
        self.assertFalse(_same_tree(merge_tree=OTHER_TREE))
        self.assertFalse(_same_tree(checkout_tree=OTHER_TREE))
        self.assertFalse(_same_tree(head_tree=OTHER_TREE))

    def test_head_sha_metadata_alone_is_not_tree_proof(self) -> None:
        self.assertFalse(_same_tree(head_tree=OTHER_TREE, merge_tree=OTHER_TREE))
        self.assertFalse(_same_tree(resolved_head_sha=MERGE_COMMIT))
        self.assertFalse(_same_tree(head_sha="", resolved_head_sha=""))
        self.assertFalse(_same_tree(merge_tree=""))
        self.assertFalse(_same_tree(checkout_tree="not-a-sha"))
        self.assertFalse(_same_tree(base_sha="0" * 40))

    def test_push_and_privileged_events_do_not_omit(self) -> None:
        self.assertFalse(_same_tree(event_name="push"))
        self.assertFalse(_same_tree(event_name="pull_request_target"))
        self.assertFalse(_same_tree(event_name="workflow_run"))
        self.assertFalse(_same_tree(duplicate_paths=False))

    def test_fork_uses_the_same_tree_rule_without_a_privileged_path(self) -> None:
        self.assertTrue(_same_tree())
        self.assertFalse(_same_tree(event_name="pull_request_target"))
        self.assertNotIn("pull_request_target", CI_PATH.read_text(encoding="utf-8"))
        self.assertNotIn("pull_request_target", UI_PATH.read_text(encoding="utf-8"))


class PathOverlapTests(unittest.TestCase):
    def test_patterns_come_from_the_evidence_workflow(self) -> None:
        self.assertEqual(
            evidence_patterns_from_workflow(UI_PATH.read_text(encoding="utf-8")),
            PATTERNS,
        )

    def test_no_ui_changes_are_not_a_duplicate(self) -> None:
        for paths in (
            [],
            ["README.md"],
            ["docs/VERIFICATION_POLICY.md"],
            ["backend/src/hermes_finance/api.py"],
            ["frontend/README.md"],
            [".github/workflows/ci.yml"],
            [".github/workflows/ui-v2-evidence.yml"],
        ):
            with self.subTest(paths=paths):
                self.assertFalse(duplicate_visual_paths(paths, PATTERNS))

    def test_ui_backend_and_workflow_changes_that_run_both_sides(self) -> None:
        overlapping = (
            ["frontend/src/App.tsx"],
            ["frontend/e2e/ui-v2.visual.spec.ts", "backend/tests/test_health.py"],
            ["frontend/playwright.visual.config.ts"],
            [".github/workflows/ci.yml", ".github/workflows/ui-v2-evidence.yml"],
            ["frontend\\src\\App.tsx"],
            ["./frontend/src/App.tsx"],
        )
        for paths in overlapping:
            with self.subTest(paths=paths):
                self.assertTrue(duplicate_visual_paths(paths, PATTERNS))

    def test_path_text_is_not_executed(self) -> None:
        self.assertFalse(
            duplicate_visual_paths(
                ["frontend/../backend/src/api.py", "$(rm -rf /)"],
                PATTERNS,
            )
        )


class ProvenanceTests(unittest.TestCase):
    def expected(self, **overrides: object) -> dict[str, object]:
        document: dict[str, object] = build_provenance(
            candidate_sha=HEAD,
            base_sha=BASE,
            checked_out_sha=HEAD,
            checked_out_tree=TREE,
            event_sha=MERGE_COMMIT,
            merge_tree=TREE,
            run_id="371000",
            run_attempt="1",
        )
        document.update(overrides)
        return document

    def test_equal_trees_keep_the_head_distinct_from_the_merge_commit(self) -> None:
        document = self.expected()
        self.assertEqual(document["candidate_sha"], HEAD)
        self.assertEqual(document["checked_out_sha"], HEAD)
        self.assertEqual(document["event_sha"], MERGE_COMMIT)
        self.assertNotEqual(document["candidate_sha"], document["event_sha"])
        self.assertIs(document["head_tree_equals_merge_tree"], True)
        self.assertEqual(document["screenshot_runtime"], SCREENSHOT_RUNTIME)
        self.assertEqual(document["screenshot_meaning"], SCREENSHOT_MEANING)
        self.assertEqual(document["build_meaning"], BUILD_MEANING)
        self.assertEqual(provenance_errors(document, document), [])

    def test_different_merge_tree_is_recorded_and_not_called_equal(self) -> None:
        document = self.expected(merge_tree=OTHER_TREE, head_tree_equals_merge_tree=False)
        self.assertEqual(provenance_errors(document, document), [])
        forged = dict(document)
        forged["head_tree_equals_merge_tree"] = True
        self.assertIn(
            "tree equality flag does not match the recorded trees",
            provenance_errors(forged, document),
        )

    def test_missing_or_wrong_identity_is_rejected(self) -> None:
        document = self.expected()
        for key in (
            "candidate_sha",
            "base_sha",
            "checked_out_sha",
            "checked_out_tree",
            "head_tree",
            "run_id",
            "run_attempt",
            "screenshot_runtime",
            "build_meaning",
        ):
            broken = dict(document)
            del broken[key]
            with self.subTest(key=key):
                self.assertTrue(provenance_errors(broken, document))
        wrong_sha = dict(document)
        wrong_sha["candidate_sha"] = MERGE_COMMIT
        self.assertIn("wrong candidate_sha", provenance_errors(wrong_sha, document))
        wrong_run = dict(document)
        wrong_run["run_id"] = "999"
        self.assertIn("wrong run_id", provenance_errors(wrong_run, document))
        wrong_attempt = dict(document)
        wrong_attempt["run_attempt"] = "2"
        self.assertIn("wrong run_attempt", provenance_errors(wrong_attempt, document))
        claimed_build = dict(document)
        claimed_build["screenshot_runtime"] = "production-dist"
        claimed_build["screenshot_meaning"] = "production-build-browser-verification"
        errors = provenance_errors(claimed_build, document)
        self.assertTrue(any("production" in error or "wrong screenshot" in error for error in errors))

    def test_failed_capture_and_incomplete_package_are_not_success(self) -> None:
        self.assertFalse(publication_allowed(capture_succeeded=False, errors=[]))
        self.assertFalse(publication_allowed(capture_succeeded=True, errors=["missing screenshot"]))
        self.assertTrue(publication_allowed(capture_succeeded=True, errors=[]))
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            package = Path(tmp)
            self.assertIn("missing screenshots", package_errors(package, self.expected()))


class GitPackageTests(unittest.TestCase):
    def _repo(self, root: Path) -> tuple[Path, str, str]:
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "identity-test@example.com"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.name", "identity-test"],
            check=True,
        )
        (repo / "README.md").write_text("synthetic\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "synthetic head"],
            check=True,
            capture_output=True,
        )
        sha = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
        ).strip()
        tree = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD:"], text=True
        ).strip()
        return repo, sha, tree

    def _package(self, root: Path) -> Path:
        package = root / "ui-v2-evidence"
        (package / "screenshots").mkdir(parents=True)
        (package / "frontend-dist").mkdir()
        for name in ("dashboard.png", "monthly-close.png", "ui-v2-home.png"):
            (package / "screenshots" / name).write_bytes(b"png")
        (package / "frontend-dist" / "index.html").write_text("<html></html>\n", encoding="utf-8")
        return package

    def test_publish_binds_the_package_to_the_checked_out_head(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            repo, sha, tree = self._repo(root)
            package = self._package(root)
            errors = publish_package(
                package,
                repo,
                candidate_sha=sha,
                base_sha=BASE,
                event_sha=MERGE_COMMIT,
                merge_tree=tree,
                run_id="371001",
                run_attempt="1",
            )
            self.assertEqual(errors, [])
            document = json.loads((package / "provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(document["candidate_sha"], sha)
            self.assertEqual(document["checked_out_tree"], tree)
            self.assertEqual(document["event_sha"], MERGE_COMMIT)
            self.assertIs(document["head_tree_equals_merge_tree"], True)
            self.assertNotEqual(document["candidate_sha"], document["event_sha"])

    def test_wrong_sha_missing_artifact_and_private_file_do_not_publish(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            repo, sha, tree = self._repo(root)
            package = self._package(root)
            wrong = publish_package(
                package,
                repo,
                candidate_sha=MERGE_COMMIT,
                base_sha=BASE,
                event_sha=MERGE_COMMIT,
                merge_tree=tree,
                run_id="371001",
                run_attempt="1",
            )
            self.assertIn("candidate_sha is not the checked-out head", wrong)
            self.assertFalse((package / "provenance.json").exists())

            missing = self._package(root / "missing")
            (missing / "screenshots" / "dashboard.png").unlink()
            errors = publish_package(
                missing,
                repo,
                candidate_sha=sha,
                base_sha=BASE,
                event_sha=sha,
                merge_tree="",
                run_id="371001",
                run_attempt="1",
            )
            self.assertTrue(any("dashboard.png" in error for error in errors))
            self.assertFalse((missing / "provenance.json").exists())

            bad_run = self._package(root / "run")
            errors = publish_package(
                bad_run,
                repo,
                candidate_sha=sha,
                base_sha=BASE,
                event_sha=sha,
                merge_tree="",
                run_id="",
                run_attempt="0",
            )
            self.assertTrue(any("run_id" in error for error in errors))
            self.assertTrue(any("run_attempt" in error for error in errors))
            self.assertFalse((bad_run / "provenance.json").exists())

            private = self._package(root / "private")
            (private / "frontend-dist" / ".env").write_text("TOKEN=nope\n", encoding="utf-8")
            errors = publish_package(
                private,
                repo,
                candidate_sha=sha,
                base_sha=BASE,
                event_sha=sha,
                merge_tree=None,
                run_id="371001",
                run_attempt="2",
            )
            self.assertTrue(any("private evidence path" in error for error in errors))
            self.assertFalse((private / "provenance.json").exists())


class WorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ci = CI_PATH.read_text(encoding="utf-8")
        cls.ui = UI_PATH.read_text(encoding="utf-8")
        cls.config = CONFIG_PATH.read_text(encoding="utf-8")

    def test_evidence_command_remains_the_exact_head_producer(self) -> None:
        self.assertIn(EVIDENCE_VISUAL_COMMAND, self.ui)
        self.assertIn("ref: ${{ github.event.pull_request.head.sha }}", self.ui)
        self.assertIn("name: ui-v2-evidence-${{ github.event.pull_request.head.sha }}", self.ui)
        self.assertEqual(self.ui.count("if: success()"), 2)
        self.assertNotIn(OMIT_ENV, self.ui)
        self.assertNotIn("continue-on-error", self.ui)
        self.assertIn("permissions:\n  contents: read\n", self.ui)
        self.assertNotIn("secrets.", self.ui)

    def test_ci_omits_only_through_the_identity_decision(self) -> None:
        self.assertIn("scripts/ui_evidence_identity.py paths", self.ci)
        self.assertIn("scripts/ui_evidence_identity.py trees", self.ci)
        self.assertIn(f"{OMIT_ENV}: ${{{{ steps.identity.outputs.omit }}}}", self.ci)
        self.assertNotIn(f"{OMIT_ENV}: true", self.ci)
        self.assertNotIn(f'{OMIT_ENV}: "true"', self.ci)
        self.assertIn("npm run audit:visual", self.ci)
        self.assertIn("python3 scripts/tests/test-ui-evidence-identity.py", self.ci)
        self.assertIn(
            "duplicate_paths: ${{ steps.filter.outputs.duplicate_paths }}",
            self.ci,
        )
        self.assertIn("g04-smoke.spec.ts performance-real-backend.spec.ts", self.ci)
        visual_job = self.ci.split("  visual-audit:\n", 1)[1].split("\n  release-safety:", 1)[0]
        self.assertIn("npm run audit:visual", visual_job)
        self.assertNotIn("continue-on-error", visual_job)
        self.assertNotIn("--grep", visual_job)

    def test_viewport_ownership_stays_and_the_omit_is_1440_only(self) -> None:
        self.assertIn("grepInvert: /@viewport-owned/", self.config)
        self.assertIn(OMIT_ENV, self.config)
        self.assertIn("dashboard:|monthly-close:|ui-v2", self.config)
        self.assertIn('process.env.HERMES_VISUAL_AUDIT_OMIT_DUPLICATE_EVIDENCE === "true"', self.config)
        self.assertIn("testIgnore: repeatedViewportSpecs", self.config)
        other_projects = re.search(
            r"omitDuplicateEvidence\s*\?\s*\{ grepInvert: duplicateEvidenceGrep \}\s*:\s*\{\}\s*:\s*\{(?P<body>.*?)\s*\}",
            self.config,
            re.DOTALL,
        )
        self.assertIsNotNone(other_projects)
        assert other_projects is not None
        self.assertNotIn(OMIT_ENV, other_projects.group("body"))
        self.assertIn("grepInvert: /@viewport-owned/", other_projects.group("body"))
        workflow_grep = re.compile(EVIDENCE_GREP)
        config_grep = re.compile(r"(?:dashboard:|monthly-close:|ui-v2)")
        samples = (
            "dashboard: synthetic layout and owner copy",
            "monthly-close: synthetic layout and owner copy",
            "ui-v2 Home desktop: closed financial picture",
            "v1 dashboard and month detail show partial source coverage",
            "loading, empty and error states stay bounded",
            "native months 1440x900: clone, refresh, delete and keyboard",
            "Owner preparation keyboard and layout 1440px",
        )
        expected = (True, True, True, False, False, False, False)
        for sample, matches in zip(samples, expected, strict=True):
            self.assertEqual(bool(workflow_grep.search(sample)), matches)
            self.assertEqual(bool(config_grep.search(sample)), matches)

    def test_cli_fail_closed_and_publish_interface(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path_file = Path(tmp) / "paths.txt"
            path_file.write_text("docs/README.md\n", encoding="utf-8")
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(
                    main(["paths", "--from-file", str(path_file), "--workflow", str(UI_PATH)]),
                    0,
                )
            self.assertEqual(stdout.getvalue().strip(), "false")
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(
                    main(
                        [
                            "trees",
                            "--event-name",
                            "pull_request_target",
                            "--duplicate-paths",
                            "true",
                            "--head-sha",
                            HEAD,
                            "--resolved-head-sha",
                            HEAD,
                            "--base-sha",
                            BASE,
                            "--checkout-sha",
                            MERGE_COMMIT,
                            "--head-tree",
                            TREE,
                            "--merge-tree",
                            TREE,
                            "--checkout-tree",
                            TREE,
                        ]
                    ),
                    0,
                )
            self.assertEqual(stdout.getvalue().strip(), "false")


if __name__ == "__main__":
    unittest.main(verbosity=2)
