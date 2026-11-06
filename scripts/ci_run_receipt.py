#!/usr/bin/env python3
"""One bounded Actions snapshot for the existing ci-ok receipt; no polling."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def get(path: str) -> dict:
    request = Request(
        f"{os.environ.get('GITHUB_API_URL', 'https://api.github.com')}/repos/"
        f"{os.environ['GITHUB_REPOSITORY']}/{path}",
        headers={
            "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
            "Accept": "application/vnd.github+json",
        },
    )
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def items(path: str, key: str) -> list[dict]:
    result = []
    for page in range(1, 11):
        rows = get(f"{path}{'&' if '?' in path else '?'}per_page=100&page={page}")[key]
        result.extend(rows)
        if len(rows) < 100:
            return result
    raise ValueError("Actions snapshot exceeds bounded pagination")


def inherited_verdict(runs: list[dict], current: dict, pr: int) -> dict:
    previous = [
        run
        for run in runs
        if run["id"] < current["id"]
        and run["head_sha"] == current["head_sha"]
        and run["event"] == "pull_request"
        and any(item["number"] == pr for item in run.get("pull_requests", []))
    ]
    if not previous:
        raise ValueError("No previous CI evidence for this PR/head")
    latest = max(previous, key=lambda run: run["id"])
    if latest["status"] != "completed" or latest["conclusion"] != "success":
        raise ValueError(
            f"Previous same-head CI is {latest['status']}/{latest['conclusion']}: "
            f"{latest['html_url']}"
        )
    return latest


def stamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def seconds(start: str, end: str) -> int:
    return max(0, int((stamp(end) - stamp(start)).total_seconds()))


def timing_summary(attempts: list[tuple[dict, list[dict]]], now: str) -> str:
    lines = [
        "## CI attempt timing",
        "",
        "Observed wall time, not CPU time or runner queue time. Current attempt ends at this snapshot.",
        "",
        "| Attempt | Observed attempt window (s) | Pause before rerun (s) |",
        "| --- | --- | --- |",
    ]
    previous_end = None
    expensive = []
    for run, jobs in attempts:
        start = run["run_started_at"]
        ends = [job["completed_at"] for job in jobs if job.get("completed_at")]
        end = max(ends) if run.get("status") == "completed" and ends else now
        pause = seconds(previous_end, start) if previous_end else "—"
        lines.append(f"| {run['run_attempt']} | {seconds(start, end)} | {pause} |")
        previous_end = end
        for job in jobs:
            if job.get("started_at") and job.get("completed_at"):
                expensive.append(
                    (
                        seconds(job["started_at"], job["completed_at"]),
                        f"attempt {run['run_attempt']} / {job['name']}",
                    )
                )
            for step in job.get("steps", []):
                if step.get("started_at") and step.get("completed_at"):
                    expensive.append(
                        (
                            seconds(step["started_at"], step["completed_at"]),
                            f"attempt {run['run_attempt']} / {job['name']} / {step['name']}",
                        )
                    )
    lines += ["", "Most expensive completed jobs/steps (overlapping; do not sum):", ""]
    for duration, name in sorted(expensive, reverse=True)[:6]:
        lines.append(f"- {duration}s — {name.replace('|', '/')}")
    return "\n".join(lines) + "\n"


def main() -> int:
    organizational = os.environ.get("ORGANIZATIONAL_LABEL") == "true"
    try:
        current = get(f"actions/runs/{os.environ['GITHUB_RUN_ID']}")
        if organizational:
            query = urlencode(
                {"head_sha": current["head_sha"], "event": "pull_request"}
            )
            runs = items(f"actions/workflows/ci.yml/runs?{query}", "workflow_runs")
            previous = inherited_verdict(runs, current, int(os.environ["PR_NUMBER"]))
            receipt = f"Organizational label: retained successful same-head CI {previous['html_url']}\n"
        else:
            count = int(current["run_attempt"])
            if count > 10:
                raise ValueError("Attempt count exceeds bounded snapshot")
            attempts = []
            for number in range(1, count + 1):
                path = f"actions/runs/{current['id']}/attempts/{number}"
                attempts.append((get(path), items(f"{path}/jobs", "jobs")))
            receipt = timing_summary(attempts, datetime.now(timezone.utc).isoformat())
        print(receipt)
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
            stream.write("\n" + receipt)
        return 0
    except (OSError, ValueError, KeyError) as error:
        print(f"CI receipt unavailable: {error}", file=sys.stderr)
        # Timing is advisory. Missing prior evidence cannot make a label green.
        return 1 if organizational else 0


if __name__ == "__main__":
    raise SystemExit(main())
