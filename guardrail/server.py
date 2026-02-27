"""MCP server for guardrail — dbt model review tools."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

from guardrail.blast import compute_blast_radius
from guardrail.checks import generate_checks
from guardrail.config import GuardrailConfig, find_config_path, load_config
from guardrail.csv_writer import write_compare_csv
from guardrail.dashboard import generate_dashboard
from guardrail.evaluate import CheckResult, evaluate_check
from guardrail.git import get_changed_model_paths, get_current_branch, get_model_diffs
from guardrail.manifest import Manifest, load_manifest

server = Server("guardrail")

# Global state — initialized once per session
_config: GuardrailConfig | None = None
_sf_client = None  # lazy import to avoid import errors if snowflake not needed


def _format_number(v) -> str:
    """Format a number for human reading: commas, round percentages."""
    if isinstance(v, float):
        if v == int(v):
            return f"{int(v):,}"
        return f"{v:,.1f}"
    if isinstance(v, int):
        return f"{v:,}"
    # Handle Decimal
    from decimal import Decimal
    if isinstance(v, Decimal):
        if v == int(v):
            return f"{int(v):,}"
        return f"{float(v):,.1f}"
    return str(v)


def _format_result_row(row: dict) -> str:
    """Format a single-row result into plain English."""
    items = list(row.items())

    # Special case: single count column
    if len(items) == 1:
        k, v = items[0]
        label = k.lower().replace("_", " ")
        return f"{_format_number(v)} {label}"

    # Look for percentage columns to annotate
    parts = []
    pct_map = {}
    for k, v in items:
        kl = k.lower()
        if kl.endswith("_pct") or kl.endswith("_percent") or kl.endswith("_rate"):
            base = kl.replace("_pct", "").replace("_percent", "").replace("_rate", "")
            pct_map[base] = v

    for k, v in items:
        kl = k.lower()
        if kl.endswith("_pct") or kl.endswith("_percent") or kl.endswith("_rate"):
            continue  # skip — will be inlined with the base column
        label = kl.replace("_", " ")
        base = kl
        if base in pct_map:
            parts.append(f"{_format_number(v)} {label} ({_format_number(pct_map[base])}%)")
        else:
            parts.append(f"{_format_number(v)} {label}")

    return " · ".join(parts) if parts else ", ".join(f"{k}: {v}" for k, v in items)


def _format_result_table(rows: list[dict]) -> str:
    """Format multi-row results into a readable summary line."""
    if not rows:
        return "No rows returned"
    # Try to summarize as label: count pairs
    keys = list(rows[0].keys())
    # If 2-3 columns and looks like a grouped distribution
    if 2 <= len(keys) <= 3:
        label_key = keys[0]
        count_key = keys[1]
        parts = []
        for row in rows:
            label = str(row[label_key])
            count = row[count_key]
            suffix = ""
            if len(keys) == 3:
                pct = row[keys[2]]
                suffix = f" ({_format_number(pct)}%)"
            parts.append(f"{label}: {_format_number(count)}{suffix}")
        return " · ".join(parts)

    return f"{len(rows)} rows returned"


def _json_default(obj):
    """Handle Snowflake types (Decimal, datetime, etc.) for JSON serialization."""
    from decimal import Decimal
    if isinstance(obj, Decimal):
        return float(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _get_config() -> GuardrailConfig:
    global _config
    if _config is None:
        config_path = find_config_path()
        _config = load_config(config_path)
    return _config


def _get_snowflake_client():
    global _sf_client
    if _sf_client is None:
        from guardrail.snowflake_client import SnowflakeClient
        _sf_client = SnowflakeClient(_get_config().snowflake)
    return _sf_client


def _resolve_project_dir(arguments: dict) -> str:
    """Resolve dbt_project_dir from arguments or config."""
    return arguments.get("dbt_project_dir") or _get_config().dbt_project_dir


def _map_relation(relation_name: str) -> str:
    """Apply schema_map from config to fix relation_name accessibility.

    Many dbt projects compile with schemas like PUBLIC_accounts that differ
    from what a read-only Snowflake role can access (e.g. ANALYTICS_ACCOUNTS).
    The schema_map config option lets users bridge this gap.
    """
    config = _get_config()
    for old_schema, new_schema in config.schema_map.items():
        if old_schema in relation_name:
            relation_name = relation_name.replace(old_schema, new_schema)
            break
    return relation_name


def _guardrail_dir(dbt_project_dir: str) -> Path:
    return Path(dbt_project_dir) / ".guardrail"


def _load_last_review(dbt_project_dir: str) -> dict | None:
    results_path = _guardrail_dir(dbt_project_dir) / "results.json"
    if results_path.exists():
        with open(results_path) as f:
            return json.load(f)
    return None


# ── Tool Definitions ──


TOOLS = [
    types.Tool(
        name="guardrail_status",
        description=(
            "Quick metadata about the dbt project state: manifest age, model count, "
            "git branch, changed models, blast radius, and last review summary. "
            "Call this first to orient before running a full review."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "dbt_project_dir": {
                    "type": "string",
                    "description": "Path to dbt project root. Defaults to config value.",
                },
            },
        },
    ),
    types.Tool(
        name="guardrail_review",
        description=(
            "Full dbt model review pipeline. Parses manifest, detects changed models via git diff, "
            "generates SQL checks (grain, distribution, join, rowcount), executes against Snowflake, "
            "evaluates PASS/WARN/FAIL, and writes results. Returns structured JSON summary."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "dbt_project_dir": {
                    "type": "string",
                    "description": "Path to dbt project root.",
                },
                "models": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Model names to review. Defaults to git-changed models.",
                },
                "base_branch": {
                    "type": "string",
                    "description": "Git base branch for diff. Default: main.",
                },
                "skip_snowflake": {
                    "type": "boolean",
                    "description": "If true, generate checks but don't execute SQL.",
                },
                "checks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Check categories to run: grain, distribution, join, rowcount.",
                },
            },
        },
    ),
    types.Tool(
        name="guardrail_checks",
        description=(
            "Show generated SQL checks without executing them. "
            "Useful for reviewing or debugging the SQL that guardrail_review would run."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "dbt_project_dir": {"type": "string"},
                "models": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Model names. Defaults to git-changed models.",
                },
            },
        },
    ),
    types.Tool(
        name="guardrail_model_context",
        description=(
            "Return diff, raw SQL, and metadata for changed models. "
            "Use this to get everything needed to reason about semantic edge cases."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "dbt_project_dir": {
                    "type": "string",
                    "description": "Path to dbt project root.",
                },
                "models": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Model names. Defaults to git-changed models.",
                },
                "base_branch": {
                    "type": "string",
                    "description": "Git base branch for diff. Default: main.",
                },
            },
        },
    ),
    types.Tool(
        name="guardrail_run_edge_cases",
        description=(
            "Execute semantic edge case SQL queries against Snowflake and store results. "
            "Submit edge cases that Claude Code identified from analyzing model diffs."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "dbt_project_dir": {
                    "type": "string",
                    "description": "Path to dbt project root.",
                },
                "edge_cases": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "model": {"type": "string", "description": "Model name"},
                            "description": {"type": "string", "description": "What could go wrong"},
                            "risk": {
                                "type": "string",
                                "enum": ["HIGH", "MEDIUM", "LOW"],
                                "description": "Risk level",
                            },
                            "sql": {"type": "string", "description": "SQL to detect the issue"},
                            "sample_sql": {
                                "type": "string",
                                "description": "Optional SQL to fetch sample failing rows",
                            },
                        },
                        "required": ["model", "description", "risk", "sql"],
                    },
                    "description": "Edge cases to execute.",
                },
            },
            "required": ["edge_cases"],
        },
    ),
    types.Tool(
        name="guardrail_interpret_results",
        description=(
            "Write verdicts for semantic edge case results. Call this AFTER guardrail_run_edge_cases — "
            "read the results, reason about each finding in context of the model's purpose and diff, "
            "then submit your interpretation. Each verdict should say whether the result is expected, "
            "concerning, or needs investigation, and WHY."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "dbt_project_dir": {
                    "type": "string",
                    "description": "Path to dbt project root.",
                },
                "verdicts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "index": {
                                "type": "integer",
                                "description": "0-based index of the edge case in semantic_results",
                            },
                            "verdict": {
                                "type": "string",
                                "description": (
                                    "Plain English interpretation: is this expected or concerning? Why? "
                                    "What should the developer do? Be specific and reference the actual numbers."
                                ),
                            },
                            "status": {
                                "type": "string",
                                "enum": ["clear", "expected", "investigate", "action_required"],
                                "description": (
                                    "clear = no issue found (count is 0), "
                                    "expected = numbers look normal for this model, "
                                    "investigate = surprising result that needs a closer look, "
                                    "action_required = definite problem that should be fixed before merge"
                                ),
                            },
                        },
                        "required": ["index", "verdict", "status"],
                    },
                    "description": "Verdicts for each edge case result.",
                },
            },
            "required": ["verdicts"],
        },
    ),
    types.Tool(
        name="guardrail_dashboard",
        description=(
            "Generate an HTML dashboard from the last review results and open in browser."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "dbt_project_dir": {"type": "string"},
                "open_browser": {
                    "type": "boolean",
                    "description": "Open the dashboard in the default browser. Default: true.",
                },
            },
        },
    ),
]


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    handlers = {
        "guardrail_status": handle_status,
        "guardrail_review": handle_review,
        "guardrail_checks": handle_checks,
        "guardrail_model_context": handle_model_context,
        "guardrail_run_edge_cases": handle_run_edge_cases,
        "guardrail_interpret_results": handle_interpret_results,
        "guardrail_dashboard": handle_dashboard,
    }
    handler = handlers.get(name)
    if handler is None:
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]
    try:
        result = await handler(arguments)
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, default=_json_default))]
    except Exception as e:
        return [types.TextContent(type="text", text=json.dumps({"error": str(e)}))]


# ── Handlers ──


async def handle_status(arguments: dict) -> dict:
    project_dir = _resolve_project_dir(arguments)
    if not project_dir:
        return {"error": "dbt_project_dir not specified and not configured"}

    manifest_path = Path(project_dir) / "target" / "manifest.json"
    manifest_age = None
    model_count = 0
    test_count = 0
    manifest = None

    if manifest_path.exists():
        mtime = os.path.getmtime(manifest_path)
        manifest_age = round((time.time() - mtime) / 60, 1)
        manifest = load_manifest(project_dir)
        model_count = manifest.model_count
        test_count = manifest.test_count

    branch = get_current_branch(project_dir)
    base = arguments.get("base_branch", _get_config().base_branch)
    changed_paths = get_changed_model_paths(project_dir, base)

    changed_models = []
    blast_radius_names = []
    if changed_paths:
        changed_ids = []
        for p in changed_paths:
            if manifest is not None:
                uid = manifest.resolve_file_path(p)
                if uid:
                    changed_ids.append(uid)
                    meta = manifest.get_model(uid)
                    if meta:
                        changed_models.append(meta.name)
                    continue
            # New model not in manifest — extract name from filename
            changed_models.append(Path(p).stem)

        if manifest is not None and changed_ids:
            blast_ids = compute_blast_radius(manifest.child_map, changed_ids)
            for bid in blast_ids:
                meta = manifest.get_model(bid)
                if meta:
                    blast_radius_names.append(meta.name)

    last_review = _load_last_review(project_dir)
    last_review_time = None
    last_review_summary = None
    if last_review:
        last_review_time = last_review.get("timestamp")
        s = last_review.get("summary", {})
        last_review_summary = f"{s.get('fail', 0)} FAIL / {s.get('warn', 0)} WARN / {s.get('pass', 0)} PASS"

    return {
        "manifest_age_minutes": manifest_age,
        "manifest_models": model_count,
        "manifest_tests": test_count,
        "git_branch": branch,
        "git_base": base,
        "changed_models": changed_models,
        "blast_radius": blast_radius_names,
        "last_review": last_review_time,
        "last_review_summary": last_review_summary,
    }


async def handle_review(arguments: dict) -> dict:
    project_dir = _resolve_project_dir(arguments)
    if not project_dir:
        return {"error": "dbt_project_dir not specified and not configured"}

    start_time = time.time()
    manifest = load_manifest(project_dir)
    base = arguments.get("base_branch", _get_config().base_branch)
    skip_sf = arguments.get("skip_snowflake", False)
    check_categories = arguments.get("checks")

    # Resolve models to review
    model_names = arguments.get("models")
    if not model_names:
        changed_paths = get_changed_model_paths(project_dir, base)
        model_names = []
        changed_ids = []
        for p in changed_paths:
            uid = manifest.resolve_file_path(p)
            if uid:
                changed_ids.append(uid)
                meta = manifest.get_model(uid)
                if meta:
                    model_names.append(meta.name)
    else:
        changed_ids = []
        for name in model_names:
            meta = manifest.get_model_by_name(name)
            if meta:
                changed_ids.append(meta.unique_id)

    if not model_names:
        return {"error": "No models to review. Specify models or ensure git diff finds changed models."}

    # Blast radius
    blast_ids = compute_blast_radius(manifest.child_map, changed_ids)
    blast_names = []
    for bid in blast_ids:
        meta = manifest.get_model(bid)
        if meta:
            blast_names.append(meta.name)

    # Generate checks
    checks = generate_checks(
        manifest, model_names,
        categories=check_categories,
        join_key_overrides=_get_config().join_keys,
    )

    # Execute or dry-run
    results: list[CheckResult] = []
    if skip_sf:
        for check in checks:
            results.append(CheckResult(
                status="SKIP", category=check.category, model=check.model,
                check=check.check, detail="Skipped (dry-run mode)",
                importance=check.importance,
            ))
    else:
        client = _get_snowflake_client()
        for check in checks:
            try:
                rows = client.execute(check.sql)
                result = evaluate_check(check, rows, _get_config().thresholds)
                # Fetch sample rows for FAIL/WARN checks
                if result.status in ("FAIL", "WARN") and check.sample_sql:
                    try:
                        result.sample_data = client.execute(check.sample_sql)
                    except Exception:
                        pass  # sampling is best-effort
                results.append(result)
            except Exception as e:
                results.append(CheckResult(
                    status="FAIL", category=check.category, model=check.model,
                    check=check.check, detail=f"SQL error: {str(e)}",
                    importance=check.importance,
                ))

    # Summary
    summary = {
        "fail": sum(1 for r in results if r.status == "FAIL"),
        "warn": sum(1 for r in results if r.status == "WARN"),
        "pass": sum(1 for r in results if r.status == "PASS"),
    }

    duration = round(time.time() - start_time, 1)

    # Write results
    guardrail_dir = _guardrail_dir(project_dir)
    guardrail_dir.mkdir(parents=True, exist_ok=True)

    csv_path = write_compare_csv(results, guardrail_dir / "compare.csv")

    results_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "models_reviewed": model_names,
        "blast_radius": blast_names,
        "duration_seconds": duration,
        "results": [
            {
                "status": r.status,
                "category": r.category,
                "model": r.model,
                "check": r.check,
                "detail": r.detail,
                "importance": r.importance,
                **({"sample_data": r.sample_data} if r.sample_data else {}),
            }
            for r in results
        ],
    }

    with open(guardrail_dir / "results.json", "w") as f:
        json.dump(results_data, f, indent=2)

    return {
        "summary": summary,
        "models_reviewed": model_names,
        "blast_radius": blast_names,
        "results": results_data["results"],
        "csv_path": str(csv_path),
        "duration_seconds": duration,
    }


async def handle_checks(arguments: dict) -> dict:
    project_dir = _resolve_project_dir(arguments)
    if not project_dir:
        return {"error": "dbt_project_dir not specified and not configured"}

    manifest = load_manifest(project_dir)
    base = _get_config().base_branch

    model_names = arguments.get("models")
    if not model_names:
        changed_paths = get_changed_model_paths(project_dir, base)
        model_names = []
        for p in changed_paths:
            uid = manifest.resolve_file_path(p)
            if uid:
                meta = manifest.get_model(uid)
                if meta:
                    model_names.append(meta.name)

    if not model_names:
        return {"error": "No models specified and no git-changed models found."}

    checks = generate_checks(
        manifest, model_names,
        join_key_overrides=_get_config().join_keys,
    )

    return {
        "checks": [
            {
                "category": c.category,
                "model": c.model,
                "check": c.check,
                "sql": c.sql,
                "importance": c.importance,
                **({"sample_sql": c.sample_sql} if c.sample_sql else {}),
            }
            for c in checks
        ],
    }


def _extract_refs(sql_text: str) -> list[str]:
    """Extract model names from {{ ref('...') }} calls in raw SQL."""
    import re
    return re.findall(r"\{\{\s*ref\(\s*['\"](\w+)['\"]\s*\)\s*\}\}", sql_text)


def _build_context_for_new_model(
    name: str, file_path: str, diff: str, manifest, last_review: dict | None,
) -> dict:
    """Build model context for a model not yet in the manifest (new file)."""
    # Read the SQL directly from the file
    raw_code = ""
    full_path = Path(file_path)
    if full_path.exists():
        raw_code = full_path.read_text()

    # Extract upstream refs from the SQL
    refs = _extract_refs(raw_code)
    upstream = []
    upstream_tables = {}
    for ref_name in refs:
        ref_meta = manifest.get_model_by_name(ref_name)
        if ref_meta:
            upstream.append(ref_name)
            upstream_tables[ref_name] = _map_relation(ref_meta.relation_name)

    existing_results = []
    if last_review:
        for r in last_review.get("results", []):
            if r.get("model") == name:
                existing_results.append({
                    "check": r["check"],
                    "status": r["status"],
                    "detail": r["detail"],
                })

    return {
        "name": name,
        "relation_name": "(new model — not yet materialized)",
        "diff": diff,
        "raw_code": raw_code,
        "columns": [],
        "upstream": upstream,
        "upstream_tables": upstream_tables,
        "downstream": [],
        "existing_results": existing_results,
        "is_new": True,
    }


async def handle_model_context(arguments: dict) -> dict:
    project_dir = _resolve_project_dir(arguments)
    if not project_dir:
        return {"error": "dbt_project_dir not specified and not configured"}

    manifest = load_manifest(project_dir)
    base = arguments.get("base_branch", _get_config().base_branch)

    # Get diffs for all changed model files
    file_diffs = get_model_diffs(project_dir, base)

    # Resolve model names — handle both manifest models and new files
    model_names = arguments.get("models")
    new_model_paths = {}  # name -> file_path for models not in manifest
    if not model_names:
        changed_paths = get_changed_model_paths(project_dir, base)
        model_names = []
        for p in changed_paths:
            uid = manifest.resolve_file_path(p)
            if uid:
                meta = manifest.get_model(uid)
                if meta:
                    model_names.append(meta.name)
            else:
                # New model not in manifest — extract name from filename
                fname = Path(p).stem
                model_names.append(fname)
                full_path = Path(project_dir) / p
                new_model_paths[fname] = str(full_path)

    if not model_names:
        return {"error": "No models found. Specify models or ensure git diff finds changed models."}

    # Load existing review results summary if available
    last_review = _load_last_review(project_dir)

    models_context = []
    for name in model_names:
        # Check if this is a new model not in manifest
        if name in new_model_paths:
            diff = ""
            for diff_path, diff_content in file_diffs.items():
                if name in diff_path:
                    diff = diff_content
                    break
            ctx = _build_context_for_new_model(
                name, new_model_paths[name], diff, manifest, last_review
            )
            models_context.append(ctx)
            continue

        meta = manifest.get_model_by_name(name)
        if not meta:
            continue

        # Find diff for this model's file path
        diff = file_diffs.get(meta.original_file_path, "")

        # Downstream model names (first hop)
        downstream = []
        for child_uid in meta.child_models:
            child_meta = manifest.get_model(child_uid)
            if child_meta:
                downstream.append(child_meta.name)

        # Upstream model names + mapped relation_names
        upstream = []
        upstream_tables = {}
        for parent_uid in meta.depends_on_models:
            parent_meta = manifest.get_model(parent_uid)
            if parent_meta:
                upstream.append(parent_meta.name)
                upstream_tables[parent_meta.name] = _map_relation(
                    parent_meta.relation_name
                )

        # Existing mechanical check results for this model
        existing_results = []
        if last_review:
            for r in last_review.get("results", []):
                if r.get("model") == name:
                    existing_results.append({
                        "check": r["check"],
                        "status": r["status"],
                        "detail": r["detail"],
                    })

        models_context.append({
            "name": name,
            "relation_name": _map_relation(meta.relation_name),
            "diff": diff,
            "raw_code": meta.raw_code,
            "columns": meta.columns,
            "upstream": upstream,
            "upstream_tables": upstream_tables,
            "downstream": downstream,
            "existing_results": existing_results,
        })

    return {"models": models_context}


async def handle_run_edge_cases(arguments: dict) -> dict:
    project_dir = _resolve_project_dir(arguments)
    edge_cases = arguments.get("edge_cases", [])

    if not edge_cases:
        return {"error": "No edge cases provided."}

    client = _get_snowflake_client()
    results = []

    for ec in edge_cases:
        entry = {
            "model": ec["model"],
            "description": ec["description"],
            "risk": ec["risk"],
            "sql": ec["sql"],
        }
        try:
            rows = client.execute(ec["sql"])
            entry["raw_data"] = rows

            # Determine if the result indicates a problem
            flagged = False
            if rows:
                first_row = rows[0]
                has_numeric = False
                # Check for common count-based patterns
                for val in first_row.values():
                    if isinstance(val, (int, float)):
                        has_numeric = True
                        if val > 0:
                            flagged = True
                            break
                    from decimal import Decimal
                    if isinstance(val, Decimal):
                        has_numeric = True
                        if val > 0:
                            flagged = True
                            break
                # Multi-row results (distributions etc.) are always findings
                if not flagged and (len(rows) > 1 or not has_numeric):
                    flagged = True

            entry["flagged"] = flagged

            # Build a human-readable result summary
            if not rows:
                entry["result"] = "No issue detected"
            elif len(rows) == 1:
                entry["result"] = _format_result_row(rows[0])
            else:
                entry["result"] = _format_result_table(rows)

            # Fetch sample rows if flagged and sample_sql provided
            if flagged and ec.get("sample_sql"):
                try:
                    entry["sample_data"] = client.execute(ec["sample_sql"])
                except Exception:
                    pass  # sampling is best-effort

        except Exception as e:
            entry["result"] = f"SQL error: {e}"
            entry["flagged"] = True

        results.append(entry)

    # Merge into results.json
    if project_dir:
        guardrail_dir = _guardrail_dir(project_dir)
        guardrail_dir.mkdir(parents=True, exist_ok=True)
        results_path = guardrail_dir / "results.json"

        existing = {}
        if results_path.exists():
            with open(results_path) as f:
                existing = json.load(f)

        existing["semantic_results"] = results
        with open(results_path, "w") as f:
            json.dump(existing, f, indent=2, default=_json_default)

    return {
        "edge_cases_run": len(results),
        "flagged": sum(1 for r in results if r.get("flagged")),
        "results": results,
    }


async def handle_interpret_results(arguments: dict) -> dict:
    """Write verdicts into stored semantic results."""
    project_dir = _resolve_project_dir(arguments)
    if not project_dir:
        return {"error": "dbt_project_dir not specified and not configured"}

    verdicts = arguments.get("verdicts", [])
    if not verdicts:
        return {"error": "No verdicts provided."}

    results_path = _guardrail_dir(project_dir) / "results.json"
    if not results_path.exists():
        return {"error": "No results.json found. Run guardrail_run_edge_cases first."}

    with open(results_path) as f:
        data = json.load(f)

    semantic = data.get("semantic_results", [])
    updated = 0
    for v in verdicts:
        idx = v["index"]
        if 0 <= idx < len(semantic):
            semantic[idx]["verdict"] = v["verdict"]
            semantic[idx]["verdict_status"] = v["status"]
            # Fix flagged based on verdict status
            if v["status"] in ("clear", "expected"):
                semantic[idx]["flagged"] = False
            updated += 1

    data["semantic_results"] = semantic
    with open(results_path, "w") as f:
        json.dump(data, f, indent=2, default=_json_default)

    return {
        "updated": updated,
        "total": len(semantic),
    }


async def handle_dashboard(arguments: dict) -> dict:
    project_dir = _resolve_project_dir(arguments)
    if not project_dir:
        return {"error": "dbt_project_dir not specified and not configured"}

    last_review = _load_last_review(project_dir)
    if not last_review:
        return {"error": "No review results found. Run guardrail_review first."}

    # Reconstruct CheckResult objects for the dashboard
    results = []
    for r in last_review.get("results", []):
        results.append(CheckResult(
            status=r["status"],
            category=r["category"],
            model=r["model"],
            check=r["check"],
            detail=r["detail"],
            importance=r["importance"],
            sample_data=r.get("sample_data"),
        ))

    branch = get_current_branch(project_dir)
    open_browser = arguments.get("open_browser", True)
    semantic_results = last_review.get("semantic_results", [])

    dashboard_path = generate_dashboard(
        results=results,
        branch=branch,
        models_reviewed=last_review.get("models_reviewed", []),
        blast_radius=last_review.get("blast_radius", []),
        output_path=_guardrail_dir(project_dir) / "dashboard.html",
        open_browser=open_browser,
        semantic_results=semantic_results,
    )

    sections = sum(1 for x in [
        semantic_results,
        [r for r in results if r.category == "grain"],
        [r for r in results if r.category == "distribution"],
        [r for r in results if r.category == "join"],
        [r for r in results if r.category == "rowcount"],
        last_review.get("models_reviewed"),
        last_review.get("blast_radius"),
    ] if x)

    dist_charts = sum(
        1 for r in results
        if r.category == "distribution" and r.check == "value_distribution"
    )

    return {
        "dashboard_path": str(dashboard_path),
        "opened": open_browser,
        "sections": sections,
        "charts": dist_charts,
    }


# ── Entry Point ──


async def main_async():
    """Async entry point for the MCP server."""
    global _config

    # Parse --config flag
    config_path = None
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--config" and i + 1 < len(args):
            config_path = args[i + 1]
            break

    if config_path is None:
        config_path = find_config_path()

    _config = load_config(config_path)

    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main_sync():
    """Synchronous entry point for the console script."""
    asyncio.run(main_async())


if __name__ == "__main__":
    main_sync()
