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

Run automated data quality checks and semantic edge case analysis against dbt models via the guardrail MCP server.

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

1. **Status**: Call `guardrail_status` to see manifest age, changed models, and blast radius
2. **Mechanical review**: Call `guardrail_review` to execute checks against Snowflake
3. **Get model context**: Call `guardrail_model_context` to get diffs, raw SQL, and metadata for changed models
4. **Analyze edge cases**: Read the diff and SQL for each model. Reason about what could go wrong given the specific changes. Generate targeted SQL queries to detect those issues.
5. **Execute edge cases**: Call `guardrail_run_edge_cases` with the edge cases you identified
6. **Interpret results**: Read every result from step 5. For each edge case, write a verdict explaining whether the result is expected or concerning, and why. Call `guardrail_interpret_results` with your verdicts. This is the most important step — the verdict is the intelligence.
7. **Generate dashboard**: Call `guardrail_dashboard` to produce HTML report with both mechanical and semantic results
8. **Summarize**: Present results to the user with actionable next steps

### Semantic Edge Case Analysis

After mechanical checks, use `guardrail_model_context` to get the diff and raw SQL for each changed model. Then reason about what could go wrong:

**What to look for:**
- **JOIN type changes**: LEFT→INNER drops rows where the join key doesn't match; INNER→LEFT introduces NULLs in joined columns
- **WHERE clause changes**: Filter added/removed/modified can expand or contract row counts unexpectedly
- **Column renames/removals**: Downstream models may reference the old column name and break silently
- **NULL handling changes**: COALESCE added/removed, IFNULL changes can alter aggregation results
- **Aggregation changes**: New GROUP BY columns change grain; modified window functions change row-level values
- **CTE restructuring**: Reordered joins or new intermediate steps can change which rows survive

**Writing verdicts (step 6):**

After `guardrail_run_edge_cases` returns results, read every result carefully. For each edge case, write a verdict and classify it:

| Status | When to use |
|--------|-------------|
| `clear` | Count is 0 — the hypothesized issue does not exist |
| `expected` | Numbers are non-zero but normal for the model's purpose (e.g., a filter excluding 58% is by design) |
| `investigate` | Surprising result that needs a closer look — explain what's unusual and what the developer should check |
| `action_required` | Definite problem — explain what's wrong and what to fix |

**Good verdicts reference specific numbers** from the result:
- "0 dropped entities — the INNER JOIN is safe, every entity_spine row has a matching lead."
- "58% of entity-months are filtered out. This is expected — the WHERE clause intentionally limits to AQL leads and CW-attributed records. Verify this matches the funnel definition."
- "93% NULL rate on FUNNEL_CW_LOCATIONS is high. Since CW outcomes are LEFT JOINed, NULLs are expected for non-CW leads, but 93% suggests most entities lack CW attribution. Confirm this aligns with the known CW coverage rate."

**Bad verdicts are vague**: "This looks fine" / "Might be an issue" / "Needs review"

**Edge case format:**
Each edge case MUST include:
- `model`: The model name
- `description`: Plain-english explanation of what could go wrong
- `risk`: HIGH, MEDIUM, or LOW
- `sql`: A concrete, executable Snowflake SQL query that detects the issue (e.g., COUNT of affected rows)
- `sample_sql` (optional): A query returning sample rows for investigation (LIMIT 5)

**Example edge cases:**
```json
[
  {
    "model": "fact_gtm_aql_spine",
    "description": "INNER JOIN on entity_spine may silently drop entities without matching leads",
    "risk": "HIGH",
    "sql": "SELECT COUNT(*) AS dropped_entities FROM DBT_ANALYTICS_PROD.ANALYTICS_GTM.INT_GTM_AQL_ENTITY_SPINE e LEFT JOIN DBT_ANALYTICS_PROD.ANALYTICS_GTM.INT_GTM_AQL_LEADS l ON e.entity_id = l.entity_id AND e.form_month = l.form_month WHERE l.entity_id IS NULL",
    "sample_sql": "SELECT e.entity_id, e.form_month FROM DBT_ANALYTICS_PROD.ANALYTICS_GTM.INT_GTM_AQL_ENTITY_SPINE e LEFT JOIN DBT_ANALYTICS_PROD.ANALYTICS_GTM.INT_GTM_AQL_LEADS l ON e.entity_id = l.entity_id AND e.form_month = l.form_month WHERE l.entity_id IS NULL LIMIT 5"
  },
  {
    "model": "int_gtm_aql_leads",
    "description": "New WHERE clause filtering lead_type may exclude valid AQL records",
    "risk": "MEDIUM",
    "sql": "SELECT lead_type, COUNT(*) AS cnt FROM DBT_ANALYTICS_PROD.ANALYTICS_GTM.INT_GTM_AQL_LEADS GROUP BY 1 ORDER BY 2 DESC"
  }
]
```

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
| **Semantic HIGH** | LLM-identified high-risk change with evidence | Investigate before merge |
| **Semantic MEDIUM** | LLM-identified moderate-risk change | Review recommended |
| **Semantic LOW** | LLM-identified low-risk observation | Informational |

### Implementation

```
# Step 1: Check project state
Call guardrail_status with dbt_project_dir

# Step 2: Run mechanical checks
Call guardrail_review with models list (or let it auto-detect from git diff)

# Step 3: Get model context for semantic analysis
Call guardrail_model_context to get diffs + raw SQL + metadata

# Step 4: Analyze the context
Read each model's diff and raw_code. Reason about edge cases.
Generate edge case descriptions + executable SQL queries.

# Step 5: Execute edge cases
Call guardrail_run_edge_cases with the edge cases array

# Step 6: Interpret results — THIS IS THE KEY STEP
Read the results from step 5. For each edge case:
- Look at the actual numbers returned
- Consider the model's purpose and the diff context
- Write a specific verdict explaining if this is expected or concerning
- Classify as: clear / expected / investigate / action_required
Call guardrail_interpret_results with your verdicts array

# Step 7: Generate dashboard
Call guardrail_dashboard to generate and open HTML with all results

# Step 8: Summarize
Present: N FAIL / N WARN / N PASS + N semantic findings with detail
```

### Arguments Handling

| Argument | MCP Call |
|----------|----------|
| (none) | `guardrail_review` with auto-detected git-changed models |
| `status` | `guardrail_status` |
| model name(s) | `guardrail_review` with `models: [...]` |
