"""Explicit local forward recovery; publication and Start are separate operations."""

import argparse
import json
from pathlib import Path

from hermes_finance.services import forward_recovery as recovery


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    qualify = commands.add_parser("qualify")
    for name in ("database", "artifact", "inventory", "checkout", "control", "work"):
        qualify.add_argument("--" + name, required=True, type=Path)
    qualify.add_argument("--selected-sha", required=True)
    qualify.add_argument("--protection-state", required=True)
    qualify.add_argument("--protection-mode", required=True)
    for action in ("recover", "resume", "finish"):
        command = commands.add_parser(action)
        command.add_argument("--plan", required=True, type=Path)
        command.add_argument("--plan-sha256", required=True)
        command.add_argument("--accept-checkpoint", required=True)
    values = vars(parser.parse_args(arguments))
    action = values.pop("action")
    try:
        if action == "qualify":
            result = recovery.qualify(**values)
        else:
            plan = values.pop("plan")
            result = (
                recovery.finish(plan, **values)
                if action == "finish"
                else recovery.recover(plan, resume=action == "resume", **values)
            )
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        # Unexpected OS/SQLite/Git errors must not echo private paths or payloads.
        print(json.dumps({"status": "action_required", "fenced_state_requires_readback": True}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
