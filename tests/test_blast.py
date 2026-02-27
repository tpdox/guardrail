"""Tests for blast.py — blast radius computation."""

from guardrail.blast import compute_blast_radius


class TestBlastRadius:
    def test_single_model_downstream(self, two_models_manifest):
        child_map = two_models_manifest.child_map
        result = compute_blast_radius(
            child_map,
            ["model.test_project.stg_users"],
        )
        # stg_users -> fact_orders -> dim_user_summary
        assert "model.test_project.fact_orders" in result
        assert "model.test_project.dim_user_summary" in result

    def test_leaf_model_no_downstream(self, two_models_manifest):
        child_map = two_models_manifest.child_map
        result = compute_blast_radius(
            child_map,
            ["model.test_project.dim_user_summary"],
        )
        assert result == []

    def test_excludes_input_models(self, two_models_manifest):
        child_map = two_models_manifest.child_map
        result = compute_blast_radius(
            child_map,
            ["model.test_project.stg_users"],
        )
        assert "model.test_project.stg_users" not in result

    def test_max_depth_limits_traversal(self, two_models_manifest):
        child_map = two_models_manifest.child_map
        result = compute_blast_radius(
            child_map,
            ["model.test_project.stg_users"],
            max_depth=1,
        )
        assert "model.test_project.fact_orders" in result
        # dim_user_summary is depth 2, should be excluded
        assert "model.test_project.dim_user_summary" not in result

    def test_multiple_input_models(self, two_models_manifest):
        child_map = two_models_manifest.child_map
        result = compute_blast_radius(
            child_map,
            ["model.test_project.stg_users", "model.test_project.fact_orders"],
        )
        assert "model.test_project.dim_user_summary" in result
        # Input models excluded
        assert "model.test_project.stg_users" not in result
        assert "model.test_project.fact_orders" not in result

    def test_empty_child_map(self):
        result = compute_blast_radius({}, ["model.x"])
        assert result == []
