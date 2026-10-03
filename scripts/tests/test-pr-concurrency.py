#!/usr/bin/env python3
"""Expression regressions for ordinary pull-request concurrency.

The workflow expression is the source of truth. These tests parse that
expression and evaluate the cancellation matrix. They do not start runners,
cancel live runs, or touch product suites.
"""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CI_PATH = ROOT / ".github" / "workflows" / "ci.yml"
UI_PATH = ROOT / ".github" / "workflows" / "ui-v2-evidence.yml"
RELEASE_PATH = ROOT / ".github" / "workflows" / "release.yml"

PREDICATE = (
    "github.event_name == 'pull_request' "
    "&& !startsWith(github.head_ref || '', 'integration/') "
    "&& !startsWith(github.base_ref || '', 'integration/')"
)
RELEASE_GROUP = "hermes-finance-guarded-release"
CHECKOUT_PIN = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1"


def group_expression(workflow_file: str) -> str:
    return (
        "format('{0}--{1}--"
        + workflow_file
        + "--{2}', github.repository, github.workflow, case("
        + PREDICATE
        + ", format('pr-{0}', github.event.pull_request.number || github.run_id), "
        + "format('run-{0}', github.run_id)))"
    )


def extract_concurrency(text: str) -> tuple[str, str]:
    match = re.search(
        r"(?m)^concurrency:\n"
        r"  group: \$\{\{ (?P<group>.+) \}\}\n"
        r"  cancel-in-progress: \$\{\{ (?P<cancel>.+) \}\}\n",
        text,
    )
    if match is None:
        raise AssertionError("workflow is missing a one-line concurrency expression")
    return match.group("group"), match.group("cancel")


class ExprError(Exception):
    pass


class Parser:
    """Subset of GitHub Actions expressions used by the concurrency block."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.length = len(text)
        self.index = 0

    def parse(self) -> tuple:
        expression = self._parse_or()
        self._skip()
        if self.index != self.length:
            raise ExprError(f"trailing input: {self.text[self.index:]!r}")
        return expression

    def _skip(self) -> None:
        while self.index < self.length and self.text[self.index].isspace():
            self.index += 1

    def _starts(self, token: str) -> bool:
        self._skip()
        return self.text.startswith(token, self.index)

    def _eat(self, token: str) -> bool:
        if self._starts(token):
            self.index += len(token)
            return True
        return False

    def _parse_or(self) -> tuple:
        left = self._parse_and()
        while self._eat("||"):
            right = self._parse_and()
            left = ("or", left, right)
        return left

    def _parse_and(self) -> tuple:
        left = self._parse_not()
        while self._eat("&&"):
            right = self._parse_not()
            left = ("and", left, right)
        return left

    def _parse_not(self) -> tuple:
        if self._eat("!"):
            if self._starts("="):
                raise ExprError("'!=' is outside the supported expression subset")
            return ("not", self._parse_not())
        return self._parse_eq()

    def _parse_eq(self) -> tuple:
        left = self._parse_primary()
        if self._eat("=="):
            return ("eq", left, self._parse_primary())
        return left

    def _parse_primary(self) -> tuple:
        self._skip()
        if self.index >= self.length:
            raise ExprError("unexpected end")
        if self._eat("("):
            expression = self._parse_or()
            if not self._eat(")"):
                raise ExprError("missing ')'")
            return expression
        if self.text[self.index] == "'":
            return ("lit", self._parse_string())
        if self.text[self.index].isdigit():
            return ("lit", self._parse_number())
        return self._parse_call_or_path()

    def _parse_string(self) -> str:
        self.index += 1
        chars: list[str] = []
        while self.index < self.length:
            char = self.text[self.index]
            if char == "'":
                if self.index + 1 < self.length and self.text[self.index + 1] == "'":
                    chars.append("'")
                    self.index += 2
                    continue
                self.index += 1
                return "".join(chars)
            chars.append(char)
            self.index += 1
        raise ExprError("unterminated string")

    def _parse_number(self) -> int:
        start = self.index
        while self.index < self.length and self.text[self.index].isdigit():
            self.index += 1
        return int(self.text[start : self.index])

    def _parse_call_or_path(self) -> tuple:
        name = self._parse_ident()
        if self._eat("("):
            args: list[tuple] = []
            if not self._starts(")"):
                while True:
                    args.append(self._parse_or())
                    if not self._eat(","):
                        break
            if not self._eat(")"):
                raise ExprError(f"missing ')' after {name}")
            return ("call", name, tuple(args))
        path = [name]
        while self._eat("."):
            path.append(self._parse_ident())
        return ("path", tuple(path))

    def _parse_ident(self) -> str:
        self._skip()
        if self.index >= self.length or not (
            self.text[self.index].isalpha() or self.text[self.index] == "_"
        ):
            raise ExprError(f"expected identifier at {self.text[self.index : self.index + 20]!r}")
        start = self.index
        self.index += 1
        while self.index < self.length and (
            self.text[self.index].isalnum() or self.text[self.index] == "_"
        ):
            self.index += 1
        return self.text[start : self.index]


def _truthy(value: object) -> bool:
    return value not in (False, 0, "", None)


def _github_string(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return str(value)


def _lookup(path: tuple[str, ...], context: dict) -> object:
    current: object = context
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def evaluate(expression: str, context: dict) -> object:
    return _eval_node(Parser(expression).parse(), context)


def _eval_node(node: tuple, context: dict) -> object:
    kind = node[0]
    if kind == "lit":
        return node[1]
    if kind == "path":
        return _lookup(node[1], context)
    if kind == "not":
        return not _truthy(_eval_node(node[1], context))
    if kind == "eq":
        left = _eval_node(node[1], context)
        right = _eval_node(node[2], context)
        if isinstance(left, str) and isinstance(right, str):
            return left.casefold() == right.casefold()
        return left == right
    if kind == "and":
        left = _eval_node(node[1], context)
        if not _truthy(left):
            return left
        return _eval_node(node[2], context)
    if kind == "or":
        left = _eval_node(node[1], context)
        if _truthy(left):
            return left
        return _eval_node(node[2], context)
    if kind == "call":
        return _eval_call(node[1], node[2], context)
    raise ExprError(f"unknown node {kind}")


def _eval_call(name: str, args: tuple, context: dict) -> object:
    if name == "startsWith":
        if len(args) != 2:
            raise ExprError("startsWith expects 2 arguments")
        haystack = _github_string(_eval_node(args[0], context))
        needle = _github_string(_eval_node(args[1], context))
        return haystack.casefold().startswith(needle.casefold())
    if name == "format":
        if len(args) < 2:
            raise ExprError("format expects a template and at least one value")
        template = _github_string(_eval_node(args[0], context))
        values = [_github_string(_eval_node(arg, context)) for arg in args[1:]]

        def replace(match: re.Match[str]) -> str:
            index = int(match.group(1))
            if index >= len(values):
                raise ExprError(f"format index {{{index}}} is missing")
            return values[index]

        return re.sub(r"\{(\d+)\}", replace, template)
    if name == "case":
        if len(args) < 3 or len(args) % 2 == 0:
            raise ExprError("case expects predicate/value pairs and a default")
        index = 0
        while index + 1 < len(args):
            if _truthy(_eval_node(args[index], context)):
                return _eval_node(args[index + 1], context)
            index += 2
        return _eval_node(args[-1], context)
    raise ExprError(f"unsupported function {name}")


@dataclass(frozen=True)
class Run:
    workflow_file: str
    workflow: str
    event_name: str
    run_id: int
    repository: str = "LTstripes/hermes-finance"
    head_ref: str | None = None
    base_ref: str | None = None
    pr_number: int | None = None
    sha: str | None = None

    def context(self) -> dict:
        event: dict = {}
        if self.pr_number is not None:
            event["pull_request"] = {"number": self.pr_number}
        github = {
            "repository": self.repository,
            "workflow": self.workflow,
            "event_name": self.event_name,
            "run_id": self.run_id,
            "event": event,
        }
        if self.head_ref is not None:
            github["head_ref"] = self.head_ref
        if self.base_ref is not None:
            github["base_ref"] = self.base_ref
        if self.sha is not None:
            github["sha"] = self.sha
        return {"github": github}


def policy(run: Run, expressions: dict[str, tuple[str, str]]) -> tuple[str, bool]:
    group_expr, cancel_expr = expressions[run.workflow_file]
    context = run.context()
    group = evaluate(group_expr, context)
    cancel = evaluate(cancel_expr, context)
    if not isinstance(group, str) or group == "":
        raise AssertionError(f"group must be a non-empty string, got {group!r}")
    if not isinstance(cancel, bool):
        raise AssertionError(f"cancel-in-progress must be a boolean, got {cancel!r}")
    return group, cancel


def same_group(left: str, right: str) -> bool:
    # GitHub compares concurrency group names without case sensitivity.
    return left.casefold() == right.casefold()


def cancels(older: tuple[str, bool], newer: tuple[str, bool], older_id: int, newer_id: int) -> bool:
    return newer_id != older_id and same_group(older[0], newer[0]) and newer[1]


def waits(older: tuple[str, bool], newer: tuple[str, bool], older_id: int, newer_id: int) -> bool:
    return newer_id != older_id and same_group(older[0], newer[0]) and not newer[1]


def artifact_name(head_sha: str) -> str:
    return f"ui-v2-evidence-{head_sha}"


def accepted_success_evidence(conclusion: str, artifact: str, candidate_sha: str) -> bool:
    """A cancelled or failed run is not success evidence, and its artifact stays on its own SHA."""
    return conclusion == "success" and artifact == artifact_name(candidate_sha)


class ExpressionSemanticsTests(unittest.TestCase):
    def test_and_or_return_operands_and_case_selects_only_the_matching_value(self) -> None:
        context = {"github": {"event_name": "push", "run_id": 7, "event": {}}}
        self.assertIs(evaluate("github.event_name == 'pull_request' && 'pr'", context), False)
        # The failed comparison is falsy, so the or-branch supplies the value.
        self.assertEqual(
            evaluate("github.event_name == 'pull_request' && 'pr' || 'other'", context),
            "other",
        )
        self.assertEqual(
            evaluate(
                "github.event_name == 'pull_request' && 'pr' || format('run-{0}', github.run_id)",
                context,
            ),
            "run-7",
        )
        self.assertEqual(
            evaluate(
                "case(github.event_name == 'pull_request', format('pr-{0}', github.event.pull_request.number), format('run-{0}', github.run_id))",
                context,
            ),
            "run-7",
        )

    def test_startswith_follows_github_case_insensitive_string_rules(self) -> None:
        context = {"github": {"head_ref": "Integration/Milestone"}}
        self.assertIs(
            evaluate("startsWith(github.head_ref || '', 'integration/')", context),
            True,
        )
        self.assertIs(
            evaluate("startsWith(github.head_ref || '', 'integration/')", {"github": {}}),
            False,
        )


class PullRequestConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ci = CI_PATH.read_text(encoding="utf-8")
        cls.ui = UI_PATH.read_text(encoding="utf-8")
        cls.release = RELEASE_PATH.read_text(encoding="utf-8")
        cls.expressions = {
            "ci.yml": extract_concurrency(cls.ci),
            "ui-v2-evidence.yml": extract_concurrency(cls.ui),
        }

    def test_workflow_expressions_are_the_ordinary_pr_contract(self) -> None:
        self.assertEqual(self.expressions["ci.yml"][0], group_expression("ci.yml"))
        self.assertEqual(
            self.expressions["ui-v2-evidence.yml"][0],
            group_expression("ui-v2-evidence.yml"),
        )
        self.assertEqual(self.expressions["ci.yml"][1], PREDICATE)
        self.assertEqual(self.expressions["ui-v2-evidence.yml"][1], PREDICATE)
        self.assertNotEqual(self.expressions["ci.yml"][0], self.expressions["ui-v2-evidence.yml"][0])
        self.assertEqual(len(re.findall(r"(?m)^concurrency:", self.ci)), 1)
        self.assertEqual(len(re.findall(r"(?m)^concurrency:", self.ui)), 1)

    def test_triggers_checkout_artifacts_and_diagnostics_stay_in_place(self) -> None:
        self.assertIn("on:\n  push:\n    branches: [main]\n  pull_request:\n", self.ci)
        self.assertNotIn("paths:", self.ci.split("jobs:", 1)[0])
        self.assertIn(
            'on:\n  pull_request:\n    paths:\n      - "frontend/**"\n'
            '      - ".github/workflows/ui-v2-evidence.yml"\n',
            self.ui,
        )
        self.assertNotIn("\n  push:\n", self.ui)
        self.assertEqual(self.ci.count(CHECKOUT_PIN), 12)
        self.assertEqual(self.ui.count(CHECKOUT_PIN), 1)
        self.assertEqual(self.release.count(CHECKOUT_PIN), 1)
        self.assertIn("name: ui-v2-evidence-${{ github.event.pull_request.head.sha }}", self.ui)
        self.assertEqual(self.ui.count("if: success()"), 2)
        self.assertIn("name: native-v2-real-backend-evidence", self.ci)
        self.assertIn("if: always()", self.ci)
        self.assertIn("!cancelled()", self.ci)
        self.assertIn("python3 scripts/tests/test-pr-concurrency.py", self.ci)
        for workflow in (self.ci, self.ui, self.release):
            for forbidden in ("taskkill", "Stop-Process", "pkill", "killall"):
                self.assertNotIn(forbidden, workflow)

    def test_release_workflow_keeps_its_own_non_cancelling_group(self) -> None:
        match = re.search(
            r"(?m)^concurrency:\n  group: (?P<group>\S+)\n  cancel-in-progress: (?P<cancel>true|false)\n",
            self.release,
        )
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.group("group"), RELEASE_GROUP)
        self.assertEqual(match.group("cancel"), "false")
        self.assertNotIn("cancel-in-progress: true", self.release)
        self.assertNotIn("pull_request.number", self.release)
        self.assertNotIn("integration/", self.release)

    def _policy(self, run: Run) -> tuple[str, bool]:
        return policy(run, self.expressions)

    def test_one_pr_two_candidates_cancel_only_the_older_candidate(self) -> None:
        older = self._policy(
            Run("ci.yml", "CI", "pull_request", 100, head_ref="task/one", base_ref="main", pr_number=10, sha="aaa")
        )
        newer = self._policy(
            Run("ci.yml", "CI", "pull_request", 101, head_ref="task/one", base_ref="main", pr_number=10, sha="bbb")
        )
        self.assertEqual(older, ("LTstripes/hermes-finance--CI--ci.yml--pr-10", True))
        self.assertTrue(cancels(older, newer, 100, 101))
        self.assertFalse(waits(older, newer, 100, 101))
        self.assertFalse(
            accepted_success_evidence("cancelled", artifact_name("aaa"), "bbb")
        )
        self.assertTrue(accepted_success_evidence("success", artifact_name("bbb"), "bbb"))
        self.assertNotEqual(artifact_name("aaa"), artifact_name("bbb"))

    def test_different_prs_do_not_share_a_cancel_group(self) -> None:
        first = self._policy(
            Run("ci.yml", "CI", "pull_request", 100, head_ref="task/one", base_ref="main", pr_number=10, sha="aaa")
        )
        second = self._policy(
            Run("ci.yml", "CI", "pull_request", 101, head_ref="task/two", base_ref="main", pr_number=11, sha="bbb")
        )
        self.assertFalse(same_group(first[0], second[0]))
        self.assertFalse(cancels(first, second, 100, 101))
        self.assertFalse(waits(first, second, 100, 101))

    def test_different_workflows_of_one_pr_do_not_cancel_each_other(self) -> None:
        ci_run = self._policy(
            Run("ci.yml", "CI", "pull_request", 100, head_ref="task/one", base_ref="main", pr_number=10, sha="aaa")
        )
        ui_run = self._policy(
            Run(
                "ui-v2-evidence.yml",
                "UI comparison evidence",
                "pull_request",
                101,
                head_ref="task/one",
                base_ref="main",
                pr_number=10,
                sha="aaa",
            )
        )
        self.assertIn("--ci.yml--", ci_run[0])
        self.assertIn("--ui-v2-evidence.yml--", ui_run[0])
        self.assertFalse(same_group(ci_run[0], ui_run[0]))
        self.assertFalse(cancels(ci_run, ui_run, 100, 101))
        self.assertFalse(cancels(ui_run, ci_run, 101, 100))

    def test_repository_identity_is_part_of_the_group(self) -> None:
        ours = self._policy(
            Run("ci.yml", "CI", "pull_request", 100, head_ref="task/one", base_ref="main", pr_number=10)
        )
        other = self._policy(
            Run(
                "ci.yml",
                "CI",
                "pull_request",
                101,
                repository="Other/hermes-finance",
                head_ref="task/one",
                base_ref="main",
                pr_number=10,
            )
        )
        self.assertFalse(same_group(ours[0], other[0]))

    def test_main_push_is_not_cancelled_or_queued_by_a_pr_or_another_main_push(self) -> None:
        main_old = self._policy(Run("ci.yml", "CI", "push", 200))
        main_new = self._policy(Run("ci.yml", "CI", "push", 201))
        pull = self._policy(
            Run("ci.yml", "CI", "pull_request", 202, head_ref="task/one", base_ref="main", pr_number=10)
        )
        self.assertEqual(main_old, ("LTstripes/hermes-finance--CI--ci.yml--run-200", False))
        self.assertEqual(main_new[0], "LTstripes/hermes-finance--CI--ci.yml--run-201")
        self.assertFalse(same_group(main_old[0], main_new[0]))
        self.assertFalse(same_group(main_old[0], pull[0]))
        self.assertFalse(cancels(main_old, pull, 200, 202))
        self.assertFalse(cancels(pull, main_new, 202, 201))
        self.assertFalse(waits(main_old, main_new, 200, 201))
        self.assertFalse(same_group(main_old[0], RELEASE_GROUP))

    def test_integration_push_expression_is_isolated_and_ci_does_not_trigger_it(self) -> None:
        first = self._policy(Run("ci.yml", "CI", "push", 300, head_ref="integration/m10"))
        second = self._policy(Run("ci.yml", "CI", "push", 301, head_ref="integration/m10"))
        self.assertFalse(first[1])
        self.assertFalse(same_group(first[0], second[0]))
        self.assertFalse(cancels(first, second, 300, 301))
        self.assertFalse(waits(first, second, 300, 301))
        trigger = self.ci.split("permissions:", 1)[0]
        self.assertIn("branches: [main]", trigger)
        self.assertNotIn("integration/", trigger)

    def test_integration_and_uat_prs_are_not_cancelled_or_queued(self) -> None:
        scenarios = (
            Run("ci.yml", "CI", "pull_request", 400, head_ref="integration/m10", base_ref="main", pr_number=20),
            Run("ci.yml", "CI", "pull_request", 401, head_ref="task/uat", base_ref="integration/m10", pr_number=21),
            Run(
                "ci.yml",
                "CI",
                "pull_request",
                402,
                head_ref="Integration/Milestone",
                base_ref="main",
                pr_number=22,
            ),
            Run(
                "ui-v2-evidence.yml",
                "UI comparison evidence",
                "pull_request",
                403,
                head_ref="task/uat",
                base_ref="integration/owner-uat",
                pr_number=21,
            ),
        )
        described = [self._policy(run) for run in scenarios]
        for described_run in described:
            self.assertFalse(described_run[1])
            self.assertIn("--run-", described_run[0])
            self.assertNotIn("--pr-", described_run[0])
        groups = [item[0] for item in described]
        self.assertEqual(len(groups), len(set(groups)))
        ordinary = self._policy(
            Run("ci.yml", "CI", "pull_request", 404, head_ref="task/uat", base_ref="main", pr_number=21)
        )
        self.assertFalse(same_group(described[1][0], ordinary[0]))
        self.assertFalse(cancels(described[1], ordinary, 401, 404))
        self.assertFalse(waits(described[0], described[2], 400, 402))

    def test_names_that_only_contain_integration_remain_ordinary(self) -> None:
        branches = ("integration", "integration-fix", "feature/integration/child", "my-integration/topic")
        for branch in branches:
            with self.subTest(branch=branch):
                described = self._policy(
                    Run(
                        "ci.yml",
                        "CI",
                        "pull_request",
                        500,
                        head_ref=branch,
                        base_ref="main",
                        pr_number=30,
                    )
                )
                self.assertEqual(described, ("LTstripes/hermes-finance--CI--ci.yml--pr-30", True))

    def test_same_sha_repeat_cancels_only_the_older_attempt_of_that_pr_workflow(self) -> None:
        older = self._policy(
            Run("ci.yml", "CI", "pull_request", 600, head_ref="task/one", base_ref="main", pr_number=10, sha="abc")
        )
        newer = self._policy(
            Run("ci.yml", "CI", "pull_request", 601, head_ref="task/one", base_ref="main", pr_number=10, sha="abc")
        )
        other_workflow = self._policy(
            Run(
                "ui-v2-evidence.yml",
                "UI comparison evidence",
                "pull_request",
                602,
                head_ref="task/one",
                base_ref="main",
                pr_number=10,
                sha="abc",
            )
        )
        self.assertTrue(cancels(older, newer, 600, 601))
        self.assertFalse(cancels(other_workflow, newer, 602, 601))
        self.assertEqual(artifact_name("abc"), artifact_name("abc"))
        self.assertFalse(accepted_success_evidence("cancelled", artifact_name("abc"), "abc"))
        self.assertTrue(accepted_success_evidence("success", artifact_name("abc"), "abc"))

    def test_cancelled_old_sha_is_not_evidence_for_the_passing_new_sha(self) -> None:
        self.assertFalse(accepted_success_evidence("cancelled", artifact_name("old"), "new"))
        self.assertFalse(accepted_success_evidence("success", artifact_name("old"), "new"))
        self.assertFalse(accepted_success_evidence("failure", artifact_name("new"), "new"))
        self.assertTrue(accepted_success_evidence("success", artifact_name("new"), "new"))

    def test_group_comparison_is_case_insensitive_without_collapsing_distinct_workflows(self) -> None:
        lower = self._policy(
            Run("ci.yml", "ci", "pull_request", 700, head_ref="task/one", base_ref="main", pr_number=10)
        )
        upper = self._policy(
            Run("ci.yml", "CI", "pull_request", 701, head_ref="task/one", base_ref="main", pr_number=10)
        )
        ui = self._policy(
            Run(
                "ui-v2-evidence.yml",
                "ui comparison evidence",
                "pull_request",
                702,
                head_ref="task/one",
                base_ref="main",
                pr_number=10,
            )
        )
        self.assertTrue(same_group(lower[0], upper[0]))
        self.assertTrue(cancels(lower, upper, 700, 701))
        self.assertFalse(same_group(upper[0], ui[0]))
        self.assertFalse(same_group(upper[0], RELEASE_GROUP))
        self.assertFalse(same_group(ui[0], RELEASE_GROUP))


if __name__ == "__main__":
    unittest.main(verbosity=2)
