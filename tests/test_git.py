"""Tests for git.py — git operations."""

import subprocess
from unittest.mock import patch

from guardrail.git import get_changed_model_paths, get_current_branch


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
