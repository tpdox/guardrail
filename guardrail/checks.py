"""SQL check generation from manifest metadata."""

from __future__ import annotations

from dataclasses import dataclass

from guardrail.manifest import Manifest, ModelMeta


SAMPLE_LIMIT = 5


@dataclass
class Check:
    category: str       # grain, distribution, join, rowcount
    model: str          # model name
    check: str          # specific check name
    sql: str            # SQL to execute
    importance: str     # TIER0, HIGH, NORMAL
    metadata: dict | None = None  # extra info (e.g., expected values)
    sample_sql: str | None = None  # SQL to fetch example failing rows


def generate_checks(
    manifest: Manifest,
    model_names: list[str],
    categories: list[str] | None = None,
    join_key_overrides: dict[str, dict[str, list[str]]] | None = None,
) -> list[Check]:
    """Generate SQL checks for the given models based on manifest metadata.

    Categories: grain, distribution, join, rowcount. Defaults to all.
    """
    if categories is None:
        categories = ["grain", "distribution", "join", "rowcount"]

    checks: list[Check] = []

    for name in model_names:
        meta = manifest.get_model_by_name(name)
        if meta is None:
            continue

        if "grain" in categories:
            checks.extend(_grain_checks(meta))
        if "distribution" in categories:
            checks.extend(_distribution_checks(meta))
        if "join" in categories:
            checks.extend(_join_checks(manifest, meta, join_key_overrides or {}))
        if "rowcount" in categories:
            checks.extend(_rowcount_checks(meta))

    return checks


def _grain_checks(meta: ModelMeta) -> list[Check]:
    """Generate primary key duplicate and null checks from unique/not_null tests."""
    checks: list[Check] = []

    # PK duplicate check — one per unique-tested column
    for col in meta.unique_tests:
        checks.append(Check(
            category="grain",
            model=meta.name,
            check="pk_duplicates",
            sql=(
                f"SELECT '{col}' AS pk_column, "
                f"COUNT(*) AS total_rows, "
                f"COUNT(*) - COUNT(DISTINCT {col}) AS duplicate_count "
                f"FROM {meta.relation_name}"
            ),
            importance="TIER0",
            metadata={"column": col},
            sample_sql=(
                f"SELECT {col}, COUNT(*) AS occurrences "
                f"FROM {meta.relation_name} "
                f"GROUP BY {col} HAVING COUNT(*) > 1 "
                f"ORDER BY occurrences DESC LIMIT {SAMPLE_LIMIT}"
            ),
        ))

    # Null rate check — one per not_null-tested column
    for col in meta.not_null_tests:
        select_cols = _pick_sample_columns(meta, col_to_exclude=col)
        checks.append(Check(
            category="grain",
            model=meta.name,
            check="null_rate",
            sql=(
                f"SELECT '{col}' AS column_name, "
                f"COUNT(*) AS total_rows, "
                f"SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) AS null_count, "
                f"ROUND(SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*), 0), 4) AS null_pct "
                f"FROM {meta.relation_name}"
            ),
            importance="HIGH",
            metadata={"column": col},
            sample_sql=(
                f"SELECT {select_cols} "
                f"FROM {meta.relation_name} "
                f"WHERE {col} IS NULL LIMIT {SAMPLE_LIMIT}"
            ),
        ))

    return checks


def _distribution_checks(meta: ModelMeta) -> list[Check]:
    """Generate value distribution and unexpected value checks from accepted_values tests."""
    checks: list[Check] = []

    for col, expected_values in meta.accepted_values_tests.items():
        # Full distribution
        checks.append(Check(
            category="distribution",
            model=meta.name,
            check="value_distribution",
            sql=(
                f"SELECT {col} AS value, "
                f"COUNT(*) AS row_count, "
                f"ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct "
                f"FROM {meta.relation_name} "
                f"GROUP BY {col} "
                f"ORDER BY row_count DESC"
            ),
            importance="NORMAL",
            metadata={"column": col, "expected_values": expected_values},
        ))

        # Unexpected values only
        quoted = ", ".join(f"'{v.replace(chr(39), chr(39)+chr(39))}'" for v in expected_values)
        checks.append(Check(
            category="distribution",
            model=meta.name,
            check="unexpected_values",
            sql=(
                f"SELECT {col} AS unexpected_value, COUNT(*) AS row_count "
                f"FROM {meta.relation_name} "
                f"WHERE {col} NOT IN ({quoted}) "
                f"AND {col} IS NOT NULL "
                f"GROUP BY {col} "
                f"ORDER BY row_count DESC"
            ),
            importance="HIGH",
            metadata={"column": col, "expected_values": expected_values},
        ))

    return checks


def _join_checks(
    manifest: Manifest,
    meta: ModelMeta,
    join_key_overrides: dict[str, dict[str, list[str]]],
) -> list[Check]:
    """Generate FK match rate checks against parent models."""
    checks: list[Check] = []

    for parent_uid in meta.depends_on_models:
        parent = manifest.get_model(parent_uid)
        if parent is None:
            continue

        # Check for explicit join key overrides
        override_keys = join_key_overrides.get(meta.name, {}).get(parent.name)
        if override_keys:
            join_cols = override_keys
        else:
            # Infer: columns shared between child and parent where parent has unique test
            join_cols = [
                c for c in parent.unique_tests
                if c in meta.columns
            ]

        if not join_cols:
            continue

        join_cond = " AND ".join(f"c.{col} = p.{col}" for col in join_cols)
        join_col_str = ", ".join(join_cols)

        # Sample: show unmatched child rows
        sample_select = ", ".join(f"c.{col}" for col in join_cols)
        checks.append(Check(
            category="join",
            model=meta.name,
            check="fk_match_rate",
            sql=(
                f"SELECT '{parent.name}' AS parent_model, "
                f"'{join_col_str}' AS join_keys, "
                f"COUNT(*) AS child_rows, "
                f"SUM(CASE WHEN p.{join_cols[0]} IS NOT NULL THEN 1 ELSE 0 END) AS matched_rows, "
                f"ROUND(SUM(CASE WHEN p.{join_cols[0]} IS NOT NULL THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*), 0), 2) AS match_pct "
                f"FROM {meta.relation_name} c "
                f"LEFT JOIN {parent.relation_name} p ON {join_cond}"
            ),
            importance="NORMAL",
            metadata={"parent": parent.name, "join_cols": join_cols},
            sample_sql=(
                f"SELECT {sample_select}, COUNT(*) AS unmatched_rows "
                f"FROM {meta.relation_name} c "
                f"LEFT JOIN {parent.relation_name} p ON {join_cond} "
                f"WHERE p.{join_cols[0]} IS NULL "
                f"GROUP BY {sample_select} "
                f"ORDER BY unmatched_rows DESC LIMIT {SAMPLE_LIMIT}"
            ),
        ))

    return checks


def _rowcount_checks(meta: ModelMeta) -> list[Check]:
    """Generate simple row count check."""
    return [Check(
        category="rowcount",
        model=meta.name,
        check="row_count",
        sql=f"SELECT COUNT(*) AS row_count FROM {meta.relation_name}",
        importance="NORMAL",
    )]


def _pick_sample_columns(meta: ModelMeta, col_to_exclude: str | None) -> str:
    """Pick a handful of identifier columns for sample output.

    Returns a comma-separated SQL column list (up to 4 columns).
    Prefers columns with 'id' or 'name' in their name.
    """
    cols = [c for c in meta.columns if c != col_to_exclude]
    if not cols:
        return "*"

    # Prioritize identifier-like columns, then take the rest
    id_cols = [c for c in cols if "id" in c.lower() or "name" in c.lower() or "key" in c.lower()]
    other_cols = [c for c in cols if c not in id_cols]
    ordered = id_cols + other_cols

    selected = ordered[:4]
    return ", ".join(selected)
