<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/logo.svg">
  <source media="(prefers-color-scheme: light)" srcset="assets/logo-dark.svg">
  <img alt="guardrail" src="assets/logo-dark.svg" width="480">
</picture>

<br/>

**Pre-merge impact analysis for dbt models.** guardrail reads your SQL diffs, reasons about what could break, runs targeted detection queries, interprets the results, and delivers a curated verdict — not just numbers, but what they mean and what to do about them.

<br/>

```
/guardrail

  Reviewing fact_gtm_aql_spine on feature/aql-spine-v4-dbt...

  Blast radius: 113 downstream models

  ── Semantic Edge Cases ──────────────────── 2 investigate · 4 clear ──

  INVESTIGATE  93.2% NULL on FUNNEL_CW_LOCATIONS (113,509 of 121,839 rows)
    verdict: Only 6.8% of entity-months have CW attribution. If CW
    coverage should be higher, check the ENTITY_ID + FORM_MONTH join
    condition on INT_GTM_AQL_CW_OUTCOMES.

  EXPECTED  58% of entity-months filtered out by WHERE clause
    verdict: By design — the spine limits to AQL leads and CW-attributed
    records. The 50,886 kept rows are the valid funnel population.

  CLEAR  0 dropped entities from INNER JOIN to aql_leads
  CLEAR  0 duplicate ENTITY_ID || FORM_MONTH keys

  ── Mechanical Checks ────────────────────────────────────────────────
  38 checks · 0 FAIL · 2 WARN · 36 PASS
```

---

## Why not just `dbt test`?

dbt test runs the checks you've already defined. guardrail does that too — but it also reads your actual SQL diff, reasons about what could go wrong, runs queries to check, and **writes a verdict explaining what the results mean**:

| | `dbt test` | guardrail |
|---|---|---|
| **Semantic analysis** | None — only runs predefined tests | Reads the diff, generates edge case SQL, executes it, interprets the results |
| **Verdicts** | Pass/fail | "93% NULL rate is expected from LEFT JOIN — but verify CW coverage rate" |
| **Catches what you didn't test for** | No | Yes — "your LEFT→INNER JOIN change drops 341 rows" |
| **Failing rows** | Not shown | Sample of actual failing rows on WARN/FAIL |
| **Blast radius** | Not computed | Full downstream dependency graph |
| **Scope** | You specify `--select` | Auto-detects changed models from `git diff` |
| **Interface** | CLI output | Conversational + interactive HTML dashboard |

The semantic analysis is the main differentiator. A developer changes a LEFT JOIN to INNER JOIN — dbt test won't catch the silently dropped rows unless there's a specific test for it. guardrail reads the diff, reasons "this could drop rows where the join key doesn't match," generates a COUNT query, executes it, and writes a verdict: "341 dropped rows — investigate before merge."

## How it works

```
manifest.json ──→ git diff (changed models) ──→ blast radius (BFS downstream)
                         │                                │
                         │                      generate mechanical checks
                         │                                │
                    full unified diff              execute against Snowflake
                    + raw SQL + metadata                  │
                         │                    quantitative PASS / WARN / FAIL
                         │
                  Claude Code reads the diff
                  and reasons about edge cases
                         │
                  generates targeted SQL queries
                         │
                  executes against Snowflake
                         │
                  Claude Code reads the results back
                  and writes a verdict for each one
                         │
               ┌─────────┼─────────┐
               │         │         │
            clear    expected   investigate / action_required
               │         │         │
               └─────────┼─────────┘
                         │
                  dashboard.html (sorted by severity, verdicts front and center)
```

## Install

### As a Claude Code plugin

```bash
claude plugin marketplace add tpdox/guardrail
claude plugin install guardrail@tpdox
```

### Standalone

```bash
uv tool install guardrail@git+https://github.com/tpdox/guardrail
```

## Configure

Create `~/.config/guardrail/guardrail.yml`:

```yaml
dbt_project_dir: ~/path/to/dbt-project
base_branch: main

snowflake:
  account: your-account
  user: YOUR_USER
  warehouse: YOUR_WH
  role: YOUR_ROLE
  private_key_file: ~/path/to/rsa_key.p8
```

Config is searched in order: `$GUARDRAIL_CONFIG` env var > `~/.config/guardrail/guardrail.yml` > `guardrail.yml` in cwd.

<details>
<summary><b>Optional: custom thresholds and join keys</b></summary>

```yaml
thresholds:
  null_rate_fail: 0.05      # > 5% nulls = FAIL
  null_rate_warn: 0.001     # > 0.1% nulls = WARN
  fk_match_rate_fail: 0.95  # < 95% FK match = FAIL
  fk_match_rate_warn: 0.99  # < 99% FK match = WARN

# Explicit join key overrides when automatic inference
# from manifest tests is insufficient
join_keys:
  fact_orders:
    stg_users: [user_id]
```

</details>

## Usage

### Slash command

```
/guardrail                                  # review all git-changed models
/guardrail status                           # project overview + blast radius
/guardrail fact_orders                      # review a specific model
/guardrail fact_orders,dim_customers        # review multiple models
```

### MCP tools

| Tool | Description |
|------|-------------|
| `guardrail_status` | Changed models, blast radius, manifest age, last review summary |
| `guardrail_review` | Mechanical checks: generate SQL, execute, quantitative PASS/WARN/FAIL |
| `guardrail_model_context` | Returns diff + raw SQL + metadata for semantic analysis |
| `guardrail_run_edge_cases` | Executes LLM-generated edge case SQL and stores results |
| `guardrail_interpret_results` | Writes verdicts (clear/expected/investigate/action_required) for each edge case |
| `guardrail_checks` | Preview generated SQL without executing |
| `guardrail_dashboard` | HTML dashboard with verdicts, semantic + mechanical results |

### Programmatic

```python
from guardrail.manifest import load_manifest
from guardrail.checks import generate_checks

manifest = load_manifest("~/dbt-project")
checks = generate_checks(manifest, ["fact_orders"])

for check in checks:
    print(f"[{check.category}] {check.check} — {check.sql[:80]}...")
```

## What it checks

guardrail generates checks from your existing dbt test metadata — no extra configuration needed:

| dbt test | guardrail check | What you get back |
|----------|----------------|-------------------|
| `unique` | `pk_duplicates` | "847 duplicate order_id values" + sample of duplicate keys |
| `not_null` | `null_rate` | "3,241 nulls in lead_id (2.7%)" + sample rows where column is null |
| `accepted_values` | `unexpected_values` | "'Grader Pro' (341 rows), 'Unknown' (12 rows)" |
| `accepted_values` | `value_distribution` | Full value breakdown with Plotly chart |
| model `depends_on` | `fk_match_rate` | "118,432/121,087 match (97.81%)" + sample unmatched rows |
| *(always)* | `row_count` | "121,087 rows" or FAIL if empty |

## Interpreting results

### Mechanical checks

| Status | When | Action |
|--------|------|--------|
| **FAIL** (TIER0) | PK duplicates or zero rows | Must fix before merge |
| **FAIL** (HIGH) | Null rate > 5% on not_null column | Investigate immediately |
| **WARN** | Unexpected values, low FK match, or null rate > 0.1% | Review before merge |
| **PASS** | All thresholds met | No action needed |

### Semantic verdicts

The LLM reads each edge case result and classifies it:

| Verdict | What it means | Dashboard |
|---------|--------------|-----------|
| **action_required** | Definite problem — explains what's wrong and what to fix | Red accent, sorted first |
| **investigate** | Surprising result — explains what's unusual and what to check | Yellow accent |
| **expected** | Non-zero but normal — explains why the numbers are fine | Green accent |
| **clear** | Count is zero, no issue exists | Dimmed, sorted last |

Each verdict references specific numbers from the query results and explains the reasoning.

## Dashboard

Every review generates an interactive HTML dashboard at `<dbt_project>/.guardrail/dashboard.html`:

- **Semantic verdicts at the top** — sorted by severity (action_required → investigate → expected → clear)
- **Verdict blocks** on every edge case — the LLM's interpretation in plain English
- **Result data inline** — formatted numbers, distribution tables, sample rows
- **SQL collapsed** behind "show sql" toggles — evidence is available but doesn't dominate
- **Dark theme** with collapsible sections per check category
- **Plotly bar charts** for value distributions (accepted_values checks)
- **Blast radius** listed with downstream dependency count
- **Color-coded** FAIL (red) / WARN (yellow) / PASS (green) with auto-expansion of problem sections

## Output files

After each review, guardrail writes to `<dbt_project>/.guardrail/`:

| File | Contents |
|------|----------|
| `results.json` | Mechanical + semantic results with verdicts, timestamps, model list, blast radius |
| `compare.csv` | Sorted by severity (FAIL > WARN > PASS) for quick scanning |
| `dashboard.html` | Interactive dashboard with verdict blocks, collapsible sections, Plotly charts |

## Plugin extras

When installed as a Claude Code plugin:

- **PostToolUse hook** — after `dbt build` or `dbt run`, suggests running a review
- **`/guardrail` slash command** — conversational interface with guided workflow
- **Auto model detection** — diffs your branch against `main` automatically

## Development

```bash
git clone https://github.com/tpdox/guardrail.git
cd guardrail
uv sync --extra dev
uv run pytest tests/ -v       # 63 tests
```

## Architecture

```
guardrail/
├── server.py            # MCP server — tool definitions and handlers
├── manifest.py          # dbt manifest parser → ModelMeta dataclasses
├── checks.py            # SQL check generation from manifest metadata
├── evaluate.py          # PASS/WARN/FAIL evaluation with configurable thresholds
├── blast.py             # BFS blast radius computation over child_map
├── snowflake_client.py  # Lightweight Snowflake connector (RSA key auth)
├── dashboard.py         # Jinja2 HTML dashboard generation
├── csv_writer.py        # CSV output sorted by severity
├── config.py            # YAML config loading with env var expansion
├── git.py               # Git diff for changed model detection
└── templates/
    └── dashboard.html   # Dark theme dashboard with verdict rendering
```

## License

MIT
