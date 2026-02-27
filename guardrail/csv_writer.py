"""Generate compare.csv from check results."""

from __future__ import annotations

import csv
from pathlib import Path

from guardrail.evaluate import CheckResult

COLUMNS = [
    "status", "category", "model", "check", "importance", "detail",
]

STATUS_ORDER = {"FAIL": 0, "WARN": 1, "PASS": 2}
IMPORTANCE_ORDER = {"TIER0": 0, "HIGH": 1, "NORMAL": 2}


def write_compare_csv(
    results: list[CheckResult],
    output_path: str | Path,
) -> Path:
    """Write results to compare.csv, sorted by severity then importance."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sorted_results = sorted(
        results,
        key=lambda r: (
            STATUS_ORDER.get(r.status, 9),
            IMPORTANCE_ORDER.get(r.importance, 9),
            r.model,
            r.check,
        ),
    )

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for r in sorted_results:
            writer.writerow({
                "status": r.status,
                "category": r.category,
                "model": r.model,
                "check": r.check,
                "importance": r.importance,
                "detail": r.detail,
            })

    return output_path
