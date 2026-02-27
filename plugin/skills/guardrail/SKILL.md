---
name: guardrail
description: Run dbt model review checks via the guardrail MCP server
user-invocable: true
arguments:
  - name: models
    description: Comma-separated model names, or "status" to check project state
    required: false
---

# guardrail — dbt Model Review

Run automated data quality checks against dbt models via the guardrail MCP server.

## Prerequisites

- `dbt build` or `dbt compile` run recently (manifest.json must exist)
- Snowflake connection configured in `~/.config/guardrail/guardrail.yml`

---

## Usage

### When Invoked as `/guardrail`

| User Request | Action |
|--------------|--------|
| `/guardrail` | Review all git-changed models |
| `/guardrail status` | Show project status and last review |
| `/guardrail fact_gtm_aql_spine` | Review specific model |
| `/guardrail fact_gtm_aql_spine,int_gtm_funnel` | Review multiple models |

### Workflow

1. **Start with status**: Call `guardrail_status` to see manifest age, changed models, and blast radius
2. **Run review**: Call `guardrail_review` to execute checks against Snowflake
3. **Generate dashboard**: Call `guardrail_dashboard` to produce HTML report
4. **Summarize**: Present results to the user with actionable next steps

### After `dbt build` on Feature Branches

When the user runs `dbt build` on a non-main branch, suggest running guardrail:

> "Your dbt build succeeded. Want me to run `guardrail` to validate the changes?"

### Interpreting Results

| Status | Meaning | Action |
|--------|---------|--------|
| **FAIL** (TIER0) | Primary key violation or zero rows | Must fix before merge |
| **FAIL** (HIGH) | Null rate > 5% on not_null column | Investigate immediately |
| **WARN** | Unexpected values or low FK match | Review before merge |
| **PASS** | Check passed thresholds | No action needed |

### Implementation

```
# Step 1: Check project state
Call guardrail_status with dbt_project_dir

# Step 2: Run full review (or specific models)
Call guardrail_review with models list (or let it auto-detect from git diff)

# Step 3: If user wants a visual report
Call guardrail_dashboard to generate and open HTML

# Step 4: Summarize
Present: N FAIL / N WARN / N PASS with detail on any FAIL/WARN items
```

### Arguments Handling

| Argument | MCP Call |
|----------|----------|
| (none) | `guardrail_review` with auto-detected git-changed models |
| `status` | `guardrail_status` |
| model name(s) | `guardrail_review` with `models: [...]` |
