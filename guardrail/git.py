"""Git operations for detecting changed dbt model files."""

from __future__ import annotations

import subprocess
from pathlib import Path


def get_current_branch(dbt_project_dir: str | Path) -> str:
    """Get the current git branch name."""
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(dbt_project_dir),
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or "unknown"


def get_changed_model_paths(
    dbt_project_dir: str | Path,
    base_branch: str = "main",
) -> list[str]:
    """Return list of changed .sql model file paths relative to the dbt project root.

    Uses `git diff base_branch...HEAD` to find files changed on the current branch.
    Only returns files under models/ that end in .sql.
    """
    cwd = str(dbt_project_dir)

    # Try three-dot diff (branch comparison)
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_branch}...HEAD", "--", "models/"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        # Fallback: diff against base branch directly (works for uncommitted changes)
        result = subprocess.run(
            ["git", "diff", "--name-only", base_branch, "--", "models/"],
            cwd=cwd,
            capture_output=True,
            text=True,
        )

    if result.returncode != 0:
        return []

    paths = []
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if line.endswith(".sql") and line.startswith("models/"):
            paths.append(line)
    return sorted(paths)
