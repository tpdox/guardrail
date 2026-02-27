"""Tests for git.py — git operations."""

import subprocess
from unittest.mock import patch

from guardrail.git import get_changed_model_paths, get_current_branch, get_model_diffs


class TestGetCurrentBranch:
    @patch("guardrail.git.subprocess.run")
    def test_returns_branch_name(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="feature/aql-spine\n", stderr=""
        )
        assert get_current_branch("/some/path") == "feature/aql-spine"

    @patch("guardrail.git.subprocess.run")
    def test_returns_unknown_on_failure(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="error"
        )
        assert get_current_branch("/some/path") == "unknown"


class TestGetChangedModelPaths:
    @patch("guardrail.git.subprocess.run")
    def test_returns_model_paths(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="models/marts/gtm/fact_gtm_aql_spine.sql\nmodels/intermediate/gtm/int_gtm_aql_form_dates.sql\n",
            stderr=""
        )
        paths = get_changed_model_paths("/some/path", "main")
        assert len(paths) == 2
        assert "models/intermediate/gtm/int_gtm_aql_form_dates.sql" in paths
        assert "models/marts/gtm/fact_gtm_aql_spine.sql" in paths

    @patch("guardrail.git.subprocess.run")
    def test_filters_non_sql_files(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="models/marts/fact_orders.sql\nmodels/marts/schema.yml\n",
            stderr=""
        )
        paths = get_changed_model_paths("/some/path")
        assert len(paths) == 1
        assert paths[0] == "models/marts/fact_orders.sql"

    @patch("guardrail.git.subprocess.run")
    def test_filters_non_model_paths(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="macros/my_macro.sql\nmodels/marts/fact_orders.sql\n",
            stderr=""
        )
        paths = get_changed_model_paths("/some/path")
        assert len(paths) == 1

    @patch("guardrail.git.subprocess.run")
    def test_empty_diff_returns_empty(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        paths = get_changed_model_paths("/some/path")
        assert paths == []


class TestGetModelDiffs:
    SAMPLE_DIFF = (
        "diff --git a/models/marts/fact_orders.sql b/models/marts/fact_orders.sql\n"
        "index abc123..def456 100644\n"
        "--- a/models/marts/fact_orders.sql\n"
        "+++ b/models/marts/fact_orders.sql\n"
        "@@ -10,3 +10,3 @@\n"
        "-    LEFT JOIN {{ ref('stg_users') }} u ON o.user_id = u.user_id\n"
        "+    INNER JOIN {{ ref('stg_users') }} u ON o.user_id = u.user_id\n"
    )

    TWO_FILE_DIFF = (
        "diff --git a/models/marts/fact_orders.sql b/models/marts/fact_orders.sql\n"
        "index abc..def 100644\n"
        "--- a/models/marts/fact_orders.sql\n"
        "+++ b/models/marts/fact_orders.sql\n"
        "@@ -1,3 +1,3 @@\n"
        "-old line\n"
        "+new line\n"
        "diff --git a/models/staging/stg_users.sql b/models/staging/stg_users.sql\n"
        "index ghi..jkl 100644\n"
        "--- a/models/staging/stg_users.sql\n"
        "+++ b/models/staging/stg_users.sql\n"
        "@@ -5,2 +5,2 @@\n"
        "-old stg line\n"
        "+new stg line\n"
    )

    @patch("guardrail.git.subprocess.run")
    def test_returns_diff_content(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=self.SAMPLE_DIFF, stderr=""
        )
        diffs = get_model_diffs("/some/path", "main")
        assert "models/marts/fact_orders.sql" in diffs
        assert "INNER JOIN" in diffs["models/marts/fact_orders.sql"]
        assert "LEFT JOIN" in diffs["models/marts/fact_orders.sql"]

    @patch("guardrail.git.subprocess.run")
    def test_splits_multiple_files(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=self.TWO_FILE_DIFF, stderr=""
        )
        diffs = get_model_diffs("/some/path", "main")
        assert len(diffs) == 2
        assert "models/marts/fact_orders.sql" in diffs
        assert "models/staging/stg_users.sql" in diffs

    @patch("guardrail.git.subprocess.run")
    def test_empty_diff_returns_empty(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        diffs = get_model_diffs("/some/path")
        assert diffs == {}

    @patch("guardrail.git.subprocess.run")
    def test_filters_non_model_files(self, mock_run):
        diff_with_non_model = (
            "diff --git a/macros/my_macro.sql b/macros/my_macro.sql\n"
            "--- a/macros/my_macro.sql\n"
            "+++ b/macros/my_macro.sql\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=diff_with_non_model, stderr=""
        )
        diffs = get_model_diffs("/some/path")
        assert diffs == {}

    @patch("guardrail.git.subprocess.run")
    def test_fallback_on_three_dot_failure(self, mock_run):
        """Falls back to two-dot diff when three-dot fails."""
        mock_run.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=128, stdout="", stderr="error"),
            subprocess.CompletedProcess(args=[], returncode=0, stdout=self.SAMPLE_DIFF, stderr=""),
        ]
        diffs = get_model_diffs("/some/path", "main")
        assert "models/marts/fact_orders.sql" in diffs
        assert mock_run.call_count == 2
