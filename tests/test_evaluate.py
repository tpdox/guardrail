"""Tests for evaluate.py — PASS/WARN/FAIL evaluation logic."""

from guardrail.checks import Check
from guardrail.config import Thresholds
from guardrail.evaluate import evaluate_check


class TestPkDuplicates:
    def _make_check(self):
        return Check(
            category="grain", model="fact_orders", check="pk_duplicates",
            sql="", importance="TIER0", metadata={"column": "order_id"},
        )

    def test_no_duplicates_passes(self):
        rows = [{"DUPLICATE_COUNT": 0, "TOTAL_ROWS": 1000}]
        result = evaluate_check(self._make_check(), rows)
        assert result.status == "PASS"

    def test_duplicates_fails(self):
        rows = [{"DUPLICATE_COUNT": 5, "TOTAL_ROWS": 1000}]
        result = evaluate_check(self._make_check(), rows)
        assert result.status == "FAIL"
        assert "5" in result.detail

    def test_empty_rows_passes(self):
        result = evaluate_check(self._make_check(), [])
        assert result.status == "PASS"


class TestNullRate:
    def _make_check(self):
        return Check(
            category="grain", model="fact_orders", check="null_rate",
            sql="", importance="HIGH", metadata={"column": "user_id"},
        )

    def test_zero_nulls_passes(self):
        rows = [{"NULL_PCT": 0, "NULL_COUNT": 0, "TOTAL_ROWS": 1000}]
        result = evaluate_check(self._make_check(), rows)
        assert result.status == "PASS"

    def test_low_null_rate_warns(self):
        rows = [{"NULL_PCT": 0.5, "NULL_COUNT": 5, "TOTAL_ROWS": 1000}]
        result = evaluate_check(self._make_check(), rows)
        assert result.status == "WARN"

    def test_high_null_rate_fails(self):
        rows = [{"NULL_PCT": 10.0, "NULL_COUNT": 100, "TOTAL_ROWS": 1000}]
        result = evaluate_check(self._make_check(), rows)
        assert result.status == "FAIL"

    def test_custom_thresholds(self):
        rows = [{"NULL_PCT": 1.0, "NULL_COUNT": 10, "TOTAL_ROWS": 1000}]
        thresholds = Thresholds(null_rate_fail=0.02, null_rate_warn=0.005)
        result = evaluate_check(self._make_check(), rows, thresholds)
        assert result.status == "WARN"


class TestUnexpectedValues:
    def _make_check(self):
        return Check(
            category="distribution", model="fact_orders", check="unexpected_values",
            sql="", importance="HIGH", metadata={"column": "status"},
        )

    def test_no_unexpected_passes(self):
        result = evaluate_check(self._make_check(), [])
        assert result.status == "PASS"

    def test_unexpected_values_warns(self):
        rows = [{"UNEXPECTED_VALUE": "unknown", "ROW_COUNT": 42}]
        result = evaluate_check(self._make_check(), rows)
        assert result.status == "WARN"
        assert "unknown" in result.detail


class TestFkMatchRate:
    def _make_check(self):
        return Check(
            category="join", model="fact_orders", check="fk_match_rate",
            sql="", importance="NORMAL", metadata={"parent": "stg_users"},
        )

    def test_full_match_passes(self):
        rows = [{"MATCH_PCT": 100.0, "PARENT_MODEL": "stg_users", "CHILD_ROWS": 1000, "MATCHED_ROWS": 1000}]
        result = evaluate_check(self._make_check(), rows)
        assert result.status == "PASS"

    def test_low_match_warns(self):
        rows = [{"MATCH_PCT": 97.5, "PARENT_MODEL": "stg_users", "CHILD_ROWS": 1000, "MATCHED_ROWS": 975}]
        result = evaluate_check(self._make_check(), rows)
        assert result.status == "WARN"

    def test_very_low_match_fails(self):
        rows = [{"MATCH_PCT": 80.0, "PARENT_MODEL": "stg_users", "CHILD_ROWS": 1000, "MATCHED_ROWS": 800}]
        result = evaluate_check(self._make_check(), rows)
        assert result.status == "FAIL"


class TestRowCount:
    def _make_check(self):
        return Check(
            category="rowcount", model="fact_orders", check="row_count",
            sql="", importance="NORMAL",
        )

    def test_nonzero_passes(self):
        rows = [{"ROW_COUNT": 52557}]
        result = evaluate_check(self._make_check(), rows)
        assert result.status == "PASS"
        assert "52,557" in result.detail

    def test_zero_fails(self):
        rows = [{"ROW_COUNT": 0}]
        result = evaluate_check(self._make_check(), rows)
        assert result.status == "FAIL"
