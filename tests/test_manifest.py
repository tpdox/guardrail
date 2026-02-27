"""Tests for manifest.py — manifest parsing and model metadata extraction."""

from guardrail.manifest import Manifest


class TestManifestParsing:
    def test_model_count(self, two_models_manifest: Manifest):
        assert two_models_manifest.model_count == 3

    def test_test_count(self, two_models_manifest: Manifest):
        assert two_models_manifest.test_count == 5

    def test_get_model_by_name(self, two_models_manifest: Manifest):
        meta = two_models_manifest.get_model_by_name("fact_orders")
        assert meta is not None
        assert meta.name == "fact_orders"
        assert meta.relation_name == "DEV_DB.marts.fact_orders"
        assert meta.materialized == "table"

    def test_get_model_by_unique_id(self, two_models_manifest: Manifest):
        meta = two_models_manifest.get_model("model.test_project.stg_users")
        assert meta is not None
        assert meta.name == "stg_users"

    def test_resolve_file_path(self, two_models_manifest: Manifest):
        uid = two_models_manifest.resolve_file_path("models/marts/fact_orders.sql")
        assert uid == "model.test_project.fact_orders"

    def test_resolve_file_path_not_found(self, two_models_manifest: Manifest):
        uid = two_models_manifest.resolve_file_path("models/nonexistent.sql")
        assert uid is None

    def test_columns_extracted(self, two_models_manifest: Manifest):
        meta = two_models_manifest.get_model_by_name("fact_orders")
        assert "order_id" in meta.columns
        assert "user_id" in meta.columns
        assert "status" in meta.columns
        assert "amount" in meta.columns

    def test_unique_tests_extracted(self, two_models_manifest: Manifest):
        meta = two_models_manifest.get_model_by_name("fact_orders")
        assert "order_id" in meta.unique_tests

    def test_not_null_tests_extracted(self, two_models_manifest: Manifest):
        meta = two_models_manifest.get_model_by_name("fact_orders")
        assert "order_id" in meta.not_null_tests

    def test_accepted_values_tests_extracted(self, two_models_manifest: Manifest):
        meta = two_models_manifest.get_model_by_name("fact_orders")
        assert "status" in meta.accepted_values_tests
        assert "completed" in meta.accepted_values_tests["status"]
        assert len(meta.accepted_values_tests["status"]) == 4

    def test_depends_on_models(self, two_models_manifest: Manifest):
        meta = two_models_manifest.get_model_by_name("fact_orders")
        assert "model.test_project.stg_users" in meta.depends_on_models

    def test_child_models(self, two_models_manifest: Manifest):
        meta = two_models_manifest.get_model_by_name("fact_orders")
        assert "model.test_project.dim_user_summary" in meta.child_models

    def test_stg_users_unique_tests(self, two_models_manifest: Manifest):
        meta = two_models_manifest.get_model_by_name("stg_users")
        assert "user_id" in meta.unique_tests
        assert "user_id" in meta.not_null_tests
