#!/usr/bin/env python3
"""Regression matrix for the docs-only pull-request gate.

Synthetic diff records cover the fail-closed cases. A temporary repository
checks real git evidence: renames, modes, symlinks, submodules and a second
commit that must be classified again instead of reusing the first decision.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docs_only_ci import (  # noqa: E402
    EXACT_DOCS,
    OMITTED_JOBS,
    PROSE_PREFIXES,
    RETAINED_JOBS,
    SUCCESS_TEXT,
    DiffRecord,
    classify_records,
    classify_repo,
    documentation_fast_path_ok,
    ordinary_doc_path,
    parse_raw_diff_z,
    product_suites_required,
    whitespace_ok,
)
from ui_evidence_identity import evidence_patterns_from_workflow, path_matches_pattern  # noqa: E402
from visual_audit_paths import is_visual_audit_path  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CI_PATH = ROOT / ".github" / "workflows" / "ci.yml"
UI_PATH = ROOT / ".github" / "workflows" / "ui-v2-evidence.yml"
RELEASE_PATH = ROOT / ".github" / "workflows" / "release.yml"
ZERO = "0" * 40
OLD = "a" * 40
NEW = "b" * 40
PRODUCT_IF = (
    "always() &&\n"
    "      !cancelled() &&\n"
    "      (github.event_name != 'pull_request' || "
    "needs.docs-only-classify.result != 'success' || "
    "needs.docs-only-classify.outputs.mode != 'docs-only')"
)


def record(
    path: str,
    *,
    status: str = "M",
    old_mode: str = "100644",
    new_mode: str = "100644",
    old_path: str | None = None,
    binary: bool = False,
) -> DiffRecord:
    return DiffRecord(
        old_mode=old_mode,
        new_mode=new_mode,
        status=status,
        old_path=path if old_path is None and status != "A" else old_path,
        new_path=path,
        binary=binary,
    )


def raw(
    path: str,
    *,
    status: str = "M",
    old_mode: str = "100644",
    new_mode: str = "100644",
    old_path: str | None = None,
) -> bytes:
    old_sha = ZERO if status == "A" else OLD
    new_sha = ZERO if status == "D" else NEW
    meta = f":{old_mode} {new_mode} {old_sha} {new_sha} {status}".encode()
    if status[:1] in {"R", "C"}:
        if old_path is None:
            raise AssertionError("rename fixture needs an old path")
        return meta + b"\0" + old_path.encode() + b"\0" + path.encode() + b"\0"
    return meta + b"\0" + path.encode() + b"\0"


class AllowlistTests(unittest.TestCase):
    def test_explicit_prose_is_docs_only(self) -> None:
        samples = [
            "README.md",
            "AGENTS.md",
            "CHANGELOG.md",
            "backend/README.md",
            "frontend/README.md",
            "docs/VERIFICATION_POLICY.md",
            "docs/WORKSPACE_JANITOR.md",
            "docs/adr/0001-architecture.md",
            "docs/agents/grok.md",
            "docs/releases/1.1.0.md",
            "docs/history/README.md",
            "sketches/README.md",
        ]
        for path in samples:
            with self.subTest(path=path):
                self.assertTrue(ordinary_doc_path(path))
                self.assertEqual(classify_records([record(path)]), "docs-only")

    def test_new_file_is_docs_only_only_on_an_explicit_rule(self) -> None:
        self.assertTrue(ordinary_doc_path("docs/adr/0099-new-decision.md"))
        self.assertTrue(ordinary_doc_path("docs/README.md"))
        self.assertEqual(
            classify_records(
                [record("docs/adr/0099-new-decision.md", status="A", old_mode="000000")]
            ),
            "docs-only",
        )
        self.assertFalse(ordinary_doc_path("docs/NEW_ROOT_NOTE.md"))
        self.assertEqual(
            classify_records([record("docs/NEW_ROOT_NOTE.md", status="A", old_mode="000000")]),
            "full",
        )

    def test_unsafe_and_unknown_paths_are_full(self) -> None:
        unsafe = [
            "backend/src/hermes_finance/api/app.py",
            "frontend/src/App.tsx",
            "frontend/src/ui-v2/MonthEditorIntegration.md",
            "backend/tests/fixtures/case.md",
            "scripts/privacy_check.py",
            "scripts/history/README.md",
            "scripts/docs_only_ci.py",
            "scripts/tests/test-docs-only-ci.py",
            ".github/workflows/ci.yml",
            ".github/workflows/ui-v2-evidence.yml",
            ".github/workflows/release.yml",
            "frontend/package.json",
            "frontend/package-lock.json",
            "backend/uv.lock",
            "docs/private_seed.schema.json",
            "docs/ai_analysis_bundle.synthetic.json",
            "docs/schemas/owner-workspace-registry.schema.json",
            "docs/release-notes-1.1.0.md",
            "docs/release-notes-9.9.9.md",
            "launcher/windows/README.md",
            "launcher/windows/package.ps1",
            "notes.txt",
            "docs/adr/nested/extra.md",
            "docs/adr/helper.py",
            "Docs/VERIFICATION_POLICY.md",
        ]
        for path in unsafe:
            with self.subTest(path=path):
                self.assertFalse(ordinary_doc_path(path))
                self.assertEqual(classify_records([record(path)]), "full")

    def test_mixed_docs_and_code_is_full(self) -> None:
        self.assertEqual(
            classify_records(
                [record("README.md"), record("backend/src/hermes_finance/api/app.py")]
            ),
            "full",
        )
        self.assertEqual(
            classify_records([record("docs/IDEA.md"), record("frontend/src/main.tsx")]),
            "full",
        )

    def test_markdown_inputs_and_gate_files_are_full(self) -> None:
        self.assertEqual(
            classify_records(
                [record("docs/release-notes-1.2.0.md", status="A", old_mode="000000")]
            ),
            "full",
        )
        self.assertEqual(classify_records([record(".github/workflows/ci.yml")]), "full")
        self.assertEqual(classify_records([record("scripts/docs_only_ci.py")]), "full")
        self.assertEqual(classify_records([record("backend/uv.lock")]), "full")

    def test_rename_delete_mode_symlink_and_submodule_are_full(self) -> None:
        cases = [
            record("README.md", status="D", new_mode="000000"),
            record("docs/adr/0002-new.md", status="R100", old_path="docs/adr/0001-architecture.md"),
            record("README.md", old_mode="100644", new_mode="100755"),
            record("README.md", status="A", old_mode="000000", new_mode="120000"),
            record("docs/link.md", status="M", old_mode="120000", new_mode="120000"),
            record("vendor/lib", status="M", old_mode="160000", new_mode="160000"),
            record("README.md", status="T", old_mode="100644", new_mode="120000"),
            record("README.md", binary=True),
        ]
        for item in cases:
            with self.subTest(item=item):
                self.assertEqual(classify_records([item]), "full")

    def test_empty_unparsed_and_odd_paths_are_full(self) -> None:
        self.assertEqual(classify_records([]), "full")
        self.assertEqual(classify_records(None), "full")
        self.assertIsNone(parse_raw_diff_z(b":not-a-diff\0README.md\0"))
        self.assertEqual(classify_records(parse_raw_diff_z(b"")), "full")
        self.assertFalse(ordinary_doc_path("../README.md"))
        self.assertFalse(ordinary_doc_path("/README.md"))
        self.assertFalse(ordinary_doc_path("docs/adr/../IDEA.md"))
        self.assertEqual(
            classify_records(
                [record("README.md"), record("docs/secret.md", status="D", new_mode="000000")]
            ),
            "full",
        )

    def test_raw_diff_preserves_rename_and_accepts_a_prose_edit(self) -> None:
        prose = parse_raw_diff_z(raw("README.md"))
        self.assertEqual(classify_records(prose), "docs-only")
        renamed = parse_raw_diff_z(
            raw("docs/adr/0002-new.md", status="R100", old_path="docs/adr/0001-architecture.md")
        )
        self.assertEqual(classify_records(renamed), "full")
        self.assertIsNone(parse_raw_diff_z(raw("README.md") + b"not-a-record"))


class DecisionTests(unittest.TestCase):
    def test_push_and_ordinary_code_pull_requests_stay_full(self) -> None:
        self.assertTrue(
            product_suites_required(
                event_name="push",
                classify_result="success",
                mode="docs-only",
                cancelled=False,
            )
        )
        self.assertTrue(
            product_suites_required(
                event_name="pull_request",
                classify_result="success",
                mode="full",
                cancelled=False,
            )
        )
        self.assertTrue(
            product_suites_required(
                event_name="pull_request",
                classify_result="failure",
                mode="docs-only",
                cancelled=False,
            )
        )
        self.assertFalse(
            product_suites_required(
                event_name="pull_request",
                classify_result="success",
                mode="docs-only",
                cancelled=False,
            )
        )
        self.assertFalse(
            product_suites_required(
                event_name="pull_request",
                classify_result="success",
                mode="docs-only",
                cancelled=True,
            )
        )

    def test_retained_failure_cancel_or_skip_is_not_docs_success(self) -> None:
        retained = {name: "success" for name in RETAINED_JOBS}
        omitted = {name: "skipped" for name in OMITTED_JOBS}
        self.assertTrue(
            documentation_fast_path_ok(
                classification="docs-only",
                retained_results=retained,
                omitted_results=omitted,
                whitespace_ok=True,
            )
        )
        for result in ("failure", "cancelled", "skipped"):
            broken = dict(retained)
            broken["privacy"] = result
            with self.subTest(privacy=result):
                self.assertFalse(
                    documentation_fast_path_ok(
                        classification="docs-only",
                        retained_results=broken,
                        omitted_results=omitted,
                        whitespace_ok=True,
                    )
                )
        self.assertFalse(
            documentation_fast_path_ok(
                classification="docs-only",
                retained_results=retained,
                omitted_results=omitted,
                whitespace_ok=False,
            )
        )
        ran = dict(omitted)
        ran["frontend"] = "success"
        self.assertFalse(
            documentation_fast_path_ok(
                classification="docs-only",
                retained_results=retained,
                omitted_results=ran,
                whitespace_ok=True,
            )
        )
        self.assertFalse(
            documentation_fast_path_ok(
                classification="full",
                retained_results=retained,
                omitted_results=omitted,
                whitespace_ok=True,
            )
        )

    def test_allowlist_does_not_use_a_blanket_docs_or_markdown_rule(self) -> None:
        self.assertNotIn("docs", PROSE_PREFIXES)
        self.assertTrue(
            all(prefix.startswith("docs/") and prefix.endswith("/") for prefix in PROSE_PREFIXES)
        )
        for path in EXACT_DOCS:
            self.assertTrue(path.endswith(".md"))
            self.assertFalse(path.startswith(".github/"))
            self.assertFalse(path.startswith("scripts/"))
            self.assertIsNone(_release(path))
        self.assertIn(SUCCESS_TEXT, CI_PATH.read_text(encoding="utf-8"))


def _release(path: str) -> object:
    import re

    return re.fullmatch(r"docs/release-notes-.+\.md", path)


class RepositoryTests(unittest.TestCase):
    def test_git_evidence_fails_closed_and_does_not_reuse_a_stale_mode(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo = Path(tmp) / "repo"
            _git_repo(repo)
            base = _commit(repo, "README.md", "base\n")
            docs_head = _commit(repo, "README.md", "base\n\nA prose note.\n")
            self.assertEqual(classify_repo(repo, base, docs_head), "docs-only")
            self.assertTrue(whitespace_ok(repo, base, docs_head))

            code_head = _commit(repo, "backend/src/app.py", "print('synthetic')\n")
            self.assertEqual(classify_repo(repo, base, code_head), "full")
            self.assertEqual(classify_repo(repo, base, docs_head), "docs-only")

            missing = "1234567890abcdef1234567890abcdef12345678"
            self.assertEqual(classify_repo(repo, missing, docs_head), "full")
            self.assertEqual(classify_repo(repo, "not-a-sha", docs_head), "full")
            self.assertEqual(classify_repo(repo, base, base), "full")

            dirty = _commit(repo, "docs/IDEA.md", "trailing \n")
            self.assertEqual(classify_repo(repo, code_head, dirty), "docs-only")
            self.assertFalse(whitespace_ok(repo, code_head, dirty))

            (repo / "docs" / "adr").mkdir(parents=True, exist_ok=True)
            _git(repo, "mv", "README.md", "docs/adr/README-renamed.md")
            renamed = _commit_index(repo, "rename prose")
            self.assertEqual(classify_repo(repo, dirty, renamed), "full")

            _git(repo, "rm", "docs/IDEA.md")
            deleted = _commit_index(repo, "delete prose")
            self.assertEqual(classify_repo(repo, renamed, deleted), "full")

            executable = _mode_commit(repo, "CHANGELOG.md", "100755", "changelog\n")
            self.assertEqual(classify_repo(repo, deleted, executable), "full")
            link = _mode_commit(repo, "docs/link.md", "120000", "README.md\n")
            self.assertEqual(classify_repo(repo, executable, link), "full")
            submodule = _mode_commit(repo, "vendor/lib", "160000", executable + "\n", gitlink=True)
            self.assertEqual(classify_repo(repo, link, submodule), "full")

            binary = _commit_bytes(repo, "docs/history/README.md", b"prose\0hidden\n")
            self.assertEqual(classify_repo(repo, submodule, binary), "full")

    def test_tracked_prose_directories_match_the_allowlist(self) -> None:
        tracked = subprocess.check_output(["git", "-C", str(ROOT), "ls-files", "-z"])
        for path in tracked.decode("utf-8").split("\0"):
            if path == "":
                continue
            for prefix in PROSE_PREFIXES:
                if path.startswith(prefix):
                    self.assertTrue(ordinary_doc_path(path), path)
            if path.startswith("docs/release-notes-") or path.startswith("docs/schemas/"):
                self.assertFalse(ordinary_doc_path(path), path)
            if path.startswith("docs/") and path.endswith(".json"):
                self.assertFalse(ordinary_doc_path(path), path)


class WorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ci = CI_PATH.read_text(encoding="utf-8")
        cls.ui = UI_PATH.read_text(encoding="utf-8")
        cls.release = RELEASE_PATH.read_text(encoding="utf-8")

    def test_product_jobs_skip_only_after_a_successful_docs_only_classification(self) -> None:
        trigger = self.ci.split("jobs:", 1)[0]
        self.assertNotIn("paths-ignore", trigger)
        self.assertNotIn("\n    paths:", trigger)
        self.assertIn("\n  pull_request:\n", trigger)
        self.assertIn("\n    branches: [main]\n", trigger)
        self.assertIn("docs-only-classify", self.ci)
        self.assertIn("github.event.pull_request.base.sha", self.ci)
        self.assertIn("github.event.pull_request.head.sha", self.ci)
        self.assertNotIn("actions/cache@", self.ci)
        for job_id in (
            "backend-quality",
            "backend-tests",
            "backend-timezone-windows",
            "frontend",
            "g04-browser",
            "release-safety",
            "windows-production-smoke",
        ):
            body = _job(self.ci, job_id)
            with self.subTest(job=job_id):
                self.assertIn("needs: docs-only-classify", body)
                self.assertIn(PRODUCT_IF, body)
        privacy = _job(self.ci, "privacy")
        self.assertNotIn("docs-only-classify", privacy)
        self.assertIn("python3 scripts/tests/test-docs-only-ci.py", privacy)
        launcher = _job(self.ci, "windows-launcher-paths")
        self.assertNotIn("mode != 'docs-only'", launcher)
        visual = _job(self.ci, "visual-audit")
        self.assertIn(
            "github.event_name == 'push' || needs.visual-audit-paths.outputs.run == 'true'",
            visual,
        )
        self.assertIn("scripts/ui_evidence_identity.py trees", visual)
        fast = _job(self.ci, "docs-fast-path")
        self.assertIn("scripts/docs_only_ci.py verdict", fast)
        for name in (*RETAINED_JOBS, *OMITTED_JOBS):
            self.assertIn(f'--job "{name}=${{{{ needs.{name}.result }}}}"', fast)
        self.assertNotIn("docs-only", self.release)

    def test_ui_evidence_does_not_run_for_allowlisted_docs(self) -> None:
        patterns = evidence_patterns_from_workflow(self.ui)
        self.assertEqual(patterns, ("frontend/**", ".github/workflows/ui-v2-evidence.yml"))
        for path in ("README.md", "docs/VERIFICATION_POLICY.md", "docs/adr/0001-architecture.md"):
            self.assertFalse(any(path_matches_pattern(path, pattern) for pattern in patterns))
            self.assertFalse(is_visual_audit_path(path))


def _job(workflow: str, job_id: str) -> str:
    marker = f"  {job_id}:\n"
    start = workflow.find(marker)
    if start < 0:
        raise AssertionError(f"missing job {job_id}")
    rest = workflow[start + len(marker) :]
    lines = []
    for line in rest.splitlines(keepends=True):
        if line.startswith("  ") and not line.startswith("   ") and line.rstrip().endswith(":"):
            break
        lines.append(line)
    return "".join(lines)


def _git(repo: Path, *args: str) -> None:
    completed = subprocess.run(["git", "-C", str(repo), *args], check=False, capture_output=True)
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace")
        raise AssertionError(f"git {args[0]} failed: {detail}")


def _git_repo(repo: Path) -> None:
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _git(repo, "config", "user.email", "docs-only-test@example.com")
    _git(repo, "config", "user.name", "docs-only-test")
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "config", "core.filemode", "false")


def _commit(repo: Path, path: str, text: str) -> str:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")
    _git(repo, "add", "--", path)
    return _commit_index(repo, path)


def _commit_bytes(repo: Path, path: str, content: bytes) -> str:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    _git(repo, "add", "--", path)
    return _commit_index(repo, path)


def _commit_index(repo: Path, message: str) -> str:
    _git(repo, "commit", "-m", message)
    return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()


def _mode_commit(repo: Path, path: str, mode: str, content: str, *, gitlink: bool = False) -> str:
    if gitlink:
        object_id = content.strip()
    else:
        object_id = (
            subprocess.check_output(
                ["git", "-C", str(repo), "hash-object", "-w", "--stdin"],
                input=content.encode("utf-8"),
            )
            .decode()
            .strip()
        )
    _git(repo, "update-index", "--add", "--cacheinfo", f"{mode},{object_id},{path}")
    return _commit_index(repo, f"mode {mode} {path}")


if __name__ == "__main__":
    unittest.main()
