"""Parse dbt manifest.json into structured ModelMeta dataclasses."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ModelMeta:
    unique_id: str
    name: str
    original_file_path: str
    relation_name: str
    database: str
    schema: str
    materialized: str
    columns: list[str]
    tags: list[str]
    unique_tests: list[str] = field(default_factory=list)
    not_null_tests: list[str] = field(default_factory=list)
    accepted_values_tests: dict[str, list[str]] = field(default_factory=dict)
    depends_on_models: list[str] = field(default_factory=list)
    child_models: list[str] = field(default_factory=list)
    raw_code: str = ""


class Manifest:
    """Parsed dbt manifest with model metadata and relationships."""

    def __init__(self, data: dict):
        self._data = data
        self._nodes = data.get("nodes", {})
        self._child_map = data.get("child_map", {})
        self._parent_map = data.get("parent_map", {})
        self._file_index: dict[str, str] = {}  # file_path -> unique_id
        self._models: dict[str, ModelMeta] = {}
        self._build()

    def _build(self) -> None:
        """Build file index and extract model metadata."""
        # Build file index: original_file_path -> unique_id
        for uid, node in self._nodes.items():
            if uid.startswith("model."):
                path = node.get("original_file_path", "")
                self._file_index[path] = uid

        # Extract model metadata
        for uid, node in self._nodes.items():
            if uid.startswith("model."):
                self._models[uid] = self._extract_model(uid, node)

    def _extract_model(self, uid: str, node: dict) -> ModelMeta:
        """Extract ModelMeta from a manifest node."""
        columns = list(node.get("columns", {}).keys())
        depends_on = [
            d for d in node.get("depends_on", {}).get("nodes", [])
            if d.startswith("model.")
        ]

        # Get direct model children from child_map
        child_models = [
            c for c in self._child_map.get(uid, [])
            if c.startswith("model.")
        ]

        meta = ModelMeta(
            unique_id=uid,
            name=node.get("name", ""),
            original_file_path=node.get("original_file_path", ""),
            relation_name=node.get("relation_name", ""),
            database=node.get("database", ""),
            schema=node.get("schema", ""),
            materialized=node.get("config", {}).get("materialized", ""),
            columns=columns,
            tags=node.get("tags", []),
            depends_on_models=depends_on,
            child_models=child_models,
            raw_code=node.get("raw_code", ""),
        )

        # Extract tests from child_map
        self._extract_tests(uid, meta)
        return meta

    def _extract_tests(self, model_uid: str, meta: ModelMeta) -> None:
        """Extract test metadata for a model from its child_map tests."""
        for child_uid in self._child_map.get(model_uid, []):
            if not child_uid.startswith("test."):
                continue
            test_node = self._nodes.get(child_uid, {})
            test_meta = test_node.get("test_metadata", {})
            test_name = test_meta.get("name", "")
            column = test_node.get("column_name", "")

            if not column:
                continue

            if test_name == "unique":
                meta.unique_tests.append(column)
            elif test_name == "not_null":
                meta.not_null_tests.append(column)
            elif test_name == "accepted_values":
                values = test_meta.get("kwargs", {}).get("values", [])
                if values:
                    meta.accepted_values_tests[column] = values

    @property
    def model_count(self) -> int:
        return len(self._models)

    @property
    def test_count(self) -> int:
        return sum(1 for k in self._nodes if k.startswith("test."))

    def get_model(self, unique_id: str) -> ModelMeta | None:
        return self._models.get(unique_id)

    def get_model_by_name(self, name: str) -> ModelMeta | None:
        for meta in self._models.values():
            if meta.name == name:
                return meta
        return None

    def resolve_file_path(self, file_path: str) -> str | None:
        """Map a file path (from git diff) to a model unique_id."""
        return self._file_index.get(file_path)

    def all_models(self) -> dict[str, ModelMeta]:
        return dict(self._models)

    @property
    def child_map(self) -> dict[str, list[str]]:
        return self._child_map


def load_manifest(dbt_project_dir: str | Path) -> Manifest:
    """Load and parse manifest.json from a dbt project's target/ directory."""
    manifest_path = Path(dbt_project_dir) / "target" / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"manifest.json not found at {manifest_path}. "
            f"Run `dbt compile` or `dbt build` first."
        )
    with open(manifest_path) as f:
        data = json.load(f)
    return Manifest(data)
