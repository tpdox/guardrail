#!/usr/bin/env python3
"""
Claude Code Hook: guardrail reminder after dbt build on feature branches.

PostToolUse hook that fires after Bash commands containing `dbt build` or `dbt run`
on non-main branches. Outputs a gentle reminder to run guardrail review.
"""

import json
import subprocess
import sys


def is_dbt_build(command: str) -> bool:
    """Check if command is a dbt build or run."""
    cmd = command.strip().lower()
    return any(x in cmd for x in ["dbt build", "dbt run"])


def get_current_branch() -> str:
    """Get the current git branch name."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def main():
    try:
        input_data = json.load(sys.stdin)
        tool_input = input_data.get("tool_input", {})
        command = tool_input.get("command", "")

        if not is_dbt_build(command):
            sys.exit(0)

        branch = get_current_branch()
        if not branch or branch in ("main", "master"):
            sys.exit(0)

        # Check if the tool succeeded
        tool_result = input_data.get("tool_result", {})
        if tool_result.get("returncode", 1) != 0:
            sys.exit(0)

        output = {
            "hookSpecificOutput": {
                "additionalContext": (
                    f"dbt build completed on branch `{branch}`. "
                    f"Consider running `/guardrail` to validate your changes."
                )
            },
            "continue": True,
        }
        print(json.dumps(output))
        sys.exit(0)

    except Exception as e:
        print(f"Hook error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
