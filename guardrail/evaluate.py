"""PASS/WARN/FAIL evaluation logic for check results."""

from __future__ import annotations

from dataclasses import dataclass

from guardrail.checks import Check
from guardrail.config import Thresholds


@dataclass
class CheckResult:
    status: str           # PASS, WARN, FAIL
    category: str
    model: str
    check: str
    detail: str
    importance: str
    raw_data: list[dict] | None = None


def evaluate_check(
    check: Check,
    rows: list[dict],
    thresholds: Thresholds | None = None,
) -> CheckResult:
    """Evaluate a check's SQL results and produce a PASS/WARN/FAIL result."""
    if thresholds is None:
        thresholds = Thresholds()

    evaluator = _EVALUATORS.get(check.check, _evaluate_default)
    return evaluator(check, rows, thresholds)


def _evaluate_pk_duplicates(
    check: Check, rows: list[dict], thresholds: Thresholds
) -> CheckResult:
    if not rows:
        return CheckResult(
            status="PASS", category=check.category, model=check.model,
            check=check.check, detail="No data returned", importance=check.importance,
        )
    row = rows[0]
    dupes = row.get("DUPLICATE_COUNT", row.get("duplicate_count", 0))
    total = row.get("TOTAL_ROWS", row.get("total_rows", 0))
    col = check.metadata.get("column", "unknown") if check.metadata else "unknown"

    if dupes > 0:
        return CheckResult(
            status="FAIL", category=check.category, model=check.model,
            check=check.check,
            detail=f"{dupes:,} duplicate {col} values out of {total:,} rows",
            importance=check.importance, raw_data=rows,
        )
    return CheckResult(
        status="PASS", category=check.category, model=check.model,
        check=check.check,
        detail=f"0 duplicate {col} values out of {total:,} rows",
        importance=check.importance, raw_data=rows,
    )


def _evaluate_null_rate(
    check: Check, rows: list[dict], thresholds: Thresholds
) -> CheckResult:
    if not rows:
        return CheckResult(
            status="PASS", category=check.category, model=check.model,
            check=check.check, detail="No data returned", importance=check.importance,
        )
    row = rows[0]
    null_pct = float(row.get("NULL_PCT", row.get("null_pct", 0)))
    null_count = row.get("NULL_COUNT", row.get("null_count", 0))
    total = row.get("TOTAL_ROWS", row.get("total_rows", 0))
    col = check.metadata.get("column", "unknown") if check.metadata else "unknown"

    rate = null_pct / 100.0

    if rate > thresholds.null_rate_fail:
        status = "FAIL"
    elif rate > thresholds.null_rate_warn:
        status = "WARN"
    else:
        status = "PASS"

    return CheckResult(
        status=status, category=check.category, model=check.model,
        check=check.check,
        detail=f"{null_count:,} nulls in {col} ({null_pct}%) out of {total:,} rows",
        importance=check.importance, raw_data=rows,
    )


def _evaluate_unexpected_values(
    check: Check, rows: list[dict], thresholds: Thresholds
) -> CheckResult:
    if not rows:
        return CheckResult(
            status="PASS", category=check.category, model=check.model,
            check=check.check, detail="No unexpected values found",
            importance=check.importance,
        )

    unexpected = []
    for row in rows:
        val = row.get("UNEXPECTED_VALUE", row.get("unexpected_value", "?"))
        count = row.get("ROW_COUNT", row.get("row_count", 0))
        unexpected.append(f"'{val}' ({count:,} rows)")

    detail = f"{len(rows)} unexpected value(s): {', '.join(unexpected)}"
    return CheckResult(
        status="WARN", category=check.category, model=check.model,
        check=check.check, detail=detail, importance=check.importance,
        raw_data=rows,
    )


def _evaluate_value_distribution(
    check: Check, rows: list[dict], thresholds: Thresholds
) -> CheckResult:
    """Distribution checks always PASS — they're informational."""
    col = check.metadata.get("column", "unknown") if check.metadata else "unknown"
    n_values = len(rows)
    return CheckResult(
        status="PASS", category=check.category, model=check.model,
        check=check.check,
        detail=f"{n_values} distinct values in {col}",
        importance=check.importance, raw_data=rows,
    )


def _evaluate_fk_match_rate(
    check: Check, rows: list[dict], thresholds: Thresholds
) -> CheckResult:
    if not rows:
        return CheckResult(
            status="PASS", category=check.category, model=check.model,
            check=check.check, detail="No data returned", importance=check.importance,
        )
    row = rows[0]
    match_pct = float(row.get("MATCH_PCT", row.get("match_pct", 100)))
    parent = row.get("PARENT_MODEL", row.get("parent_model", "unknown"))
    child_rows = row.get("CHILD_ROWS", row.get("child_rows", 0))
    matched = row.get("MATCHED_ROWS", row.get("matched_rows", 0))

    rate = match_pct / 100.0

    if rate < thresholds.fk_match_rate_fail:
        status = "FAIL"
    elif rate < thresholds.fk_match_rate_warn:
        status = "WARN"
    else:
        status = "PASS"

    return CheckResult(
        status=status, category=check.category, model=check.model,
        check=check.check,
        detail=f"{matched:,}/{child_rows:,} rows match {parent} ({match_pct}%)",
        importance=check.importance, raw_data=rows,
    )


def _evaluate_row_count(
    check: Check, rows: list[dict], thresholds: Thresholds
) -> CheckResult:
    if not rows:
        return CheckResult(
            status="FAIL", category=check.category, model=check.model,
            check=check.check, detail="No data returned", importance=check.importance,
        )
    row = rows[0]
    count = row.get("ROW_COUNT", row.get("row_count", 0))

    status = "FAIL" if count == 0 else "PASS"
    return CheckResult(
        status=status, category=check.category, model=check.model,
        check=check.check, detail=f"{count:,} rows",
        importance=check.importance, raw_data=rows,
    )


def _evaluate_default(
    check: Check, rows: list[dict], thresholds: Thresholds
) -> CheckResult:
    return CheckResult(
        status="PASS", category=check.category, model=check.model,
        check=check.check, detail=f"{len(rows)} row(s) returned",
        importance=check.importance, raw_data=rows,
    )


_EVALUATORS = {
    "pk_duplicates": _evaluate_pk_duplicates,
    "null_rate": _evaluate_null_rate,
    "unexpected_values": _evaluate_unexpected_values,
    "value_distribution": _evaluate_value_distribution,
    "fk_match_rate": _evaluate_fk_match_rate,
    "row_count": _evaluate_row_count,
}
