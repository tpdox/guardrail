"""Tests for checks.py — SQL check generation."""

from guardrail.checks import generate_checks, _pick_sample_columns
from guardrail.manifest import Manifest


class TestCheckGeneration:
    def test_grain_checks_for_fact_orders(self, two_models_manifest: Manifest):
        checks = generate_checks(two_models_manifest, ["fact_orders"], categories=["grain"])
        # Should have pk_duplicates for order_id (unique test) and null_rate for order_id (not_null test)
        pk_checks = [c for c in checks if c.check == "pk_duplicates"]
        null_checks = [c for c in checks if c.check == "null_rate"]
        assert len(pk_checks) == 1
        assert len(null_checks) == 1
        assert "order_id" in pk_checks[0].sql
        assert pk_checks[0].importance == "TIER0"

    def test_distribution_checks_for_fact_orders(self, two_models_manifest: Manifest):
        checks = generate_checks(two_models_manifest, ["fact_orders"], categories=["distribution"])
        # Should have value_distribution and unexpected_values for status column
        dist_checks = [c for c in checks if c.check == "value_distribution"]
        unexpected_checks = [c for c in checks if c.check == "unexpected_values"]
        assert len(dist_checks) == 1
        assert len(unexpected_checks) == 1
        assert "status" in dist_checks[0].sql
        assert "'pending'" in unexpected_checks[0].sql
        assert "'completed'" in unexpected_checks[0].sql

    def test_join_checks_for_fact_orders(self, two_models_manifest: Manifest):
        checks = generate_checks(two_models_manifest, ["fact_orders"], categories=["join"])
        # fact_orders depends on stg_users, stg_users has unique test on user_id,
        # and user_id is in fact_orders columns -> should generate FK check
        fk_checks = [c for c in checks if c.check == "fk_match_rate"]
        assert len(fk_checks) == 1
        assert "stg_users" in fk_checks[0].sql
        assert "user_id" in fk_checks[0].sql

    def test_rowcount_check(self, two_models_manifest: Manifest):
        checks = generate_checks(two_models_manifest, ["fact_orders"], categories=["rowcount"])
        assert len(checks) == 1
        assert checks[0].check == "row_count"
        assert "COUNT(*)" in checks[0].sql

    def test_all_categories_default(self, two_models_manifest: Manifest):
        checks = generate_checks(two_models_manifest, ["fact_orders"])
        categories = {c.category for c in checks}
        assert "grain" in categories
        assert "distribution" in categories
        assert "join" in categories
        assert "rowcount" in categories

    def test_nonexistent_model_returns_empty(self, two_models_manifest: Manifest):
        checks = generate_checks(two_models_manifest, ["nonexistent_model"])
        assert checks == []

    def test_join_key_override(self, two_models_manifest: Manifest):
        overrides = {"fact_orders": {"stg_users": ["user_id"]}}
        checks = generate_checks(
            two_models_manifest, ["fact_orders"],
            categories=["join"],
            join_key_overrides=overrides,
        )
        fk_checks = [c for c in checks if c.check == "fk_match_rate"]
        assert len(fk_checks) == 1

    def test_model_with_no_tests(self, two_models_manifest: Manifest):
        checks = generate_checks(two_models_manifest, ["dim_user_summary"], categories=["grain"])
        # dim_user_summary has no unique or not_null tests
        assert len(checks) == 0

    def test_sql_uses_relation_name(self, two_models_manifest: Manifest):
        checks = generate_checks(two_models_manifest, ["fact_orders"], categories=["rowcount"])
        assert "DEV_DB.marts.fact_orders" in checks[0].sql

    def test_pk_duplicates_has_sample_sql(self, two_models_manifest: Manifest):
        checks = generate_checks(two_models_manifest, ["fact_orders"], categories=["grain"])
        pk_checks = [c for c in checks if c.check == "pk_duplicates"]
        assert pk_checks[0].sample_sql is not None
        assert "GROUP BY" in pk_checks[0].sample_sql
        assert "HAVING COUNT(*) > 1" in pk_checks[0].sample_sql

    def test_null_rate_has_sample_sql(self, two_models_manifest: Manifest):
        checks = generate_checks(two_models_manifest, ["fact_orders"], categories=["grain"])
        null_checks = [c for c in checks if c.check == "null_rate"]
        assert null_checks[0].sample_sql is not None
        assert "IS NULL" in null_checks[0].sample_sql

    def test_fk_match_rate_has_sample_sql(self, two_models_manifest: Manifest):
        checks = generate_checks(two_models_manifest, ["fact_orders"], categories=["join"])
        fk_checks = [c for c in checks if c.check == "fk_match_rate"]
        assert fk_checks[0].sample_sql is not None
        assert "IS NULL" in fk_checks[0].sample_sql

    def test_distribution_checks_no_sample_sql(self, two_models_manifest: Manifest):
        checks = generate_checks(two_models_manifest, ["fact_orders"], categories=["distribution"])
        for c in checks:
            assert c.sample_sql is None

    def test_rowcount_no_sample_sql(self, two_models_manifest: Manifest):
        checks = generate_checks(two_models_manifest, ["fact_orders"], categories=["rowcount"])
        assert checks[0].sample_sql is None


class TestPickSampleColumns:
    def test_excludes_target_column(self, two_models_manifest: Manifest):
        meta = two_models_manifest.get_model_by_name("fact_orders")
        result = _pick_sample_columns(meta, col_to_exclude="order_id")
        assert "order_id" not in result

    def test_prioritizes_id_columns(self, two_models_manifest: Manifest):
        meta = two_models_manifest.get_model_by_name("fact_orders")
        result = _pick_sample_columns(meta, col_to_exclude=None)
        # order_id and user_id should come first
        cols = [c.strip() for c in result.split(",")]
        id_cols = [c for c in cols if "id" in c.lower()]
        assert len(id_cols) >= 1

    def test_limits_to_four_columns(self, two_models_manifest: Manifest):
        meta = two_models_manifest.get_model_by_name("fact_orders")
        result = _pick_sample_columns(meta, col_to_exclude=None)
        cols = [c.strip() for c in result.split(",")]
        assert len(cols) <= 4
