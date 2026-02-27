<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/logo.svg">
  <source media="(prefers-color-scheme: light)" srcset="assets/logo-dark.svg">
  <img alt="guardrail" src="assets/logo-dark.svg" width="480">
</picture>

<br/>

**Pre-merge impact analysis for dbt models.** guardrail answers the questions `dbt test` doesn't: *how many* rows are affected, *which* downstream models break, and *what changed* on your branch — surfaced conversationally inside Claude Code with an interactive HTML dashboard.

<br/>

```
/guardrail

  Reviewing fact_gtm_aql_spine on feature/aql-spine-v4-dbt...

  Blast radius: 113 downstream models
    fact_gtm_funnel → fact_gtm_funnel_aggregated → gtm_semantic_view
    qa_gtm_summary
    daily_channel_performance
    ...

  38 checks · 0 FAIL · 2 WARN · 36 PASS

  WARN  null_rate       lead_id    3,241 nulls (2.7%) out of 121,087 rows
        ↳ sample rows: entity_id=ACC-1042, form_date=2026-01-15, grain_type=Enrichment
                        entity_id=ACC-3891, form_date=2026-02-01, grain_type=48hr
  WARN  fk_match_rate   int_gtm_aql_cw_outcomes  118,432/121,087 rows match (97.81%)
        ↳ sample rows: unique_key=AQL-9981 (341 unmatched), unique_key=AQL-8832 (12 unmatched)
```

---

## Why not just `dbt test`?

guardrail reads your existing dbt tests (unique, not_null, accepted_values, relationships) and runs the same validations. The checks themselves aren't new. What's different is everything around them:

| | `dbt test` | guardrail |
|---|---|---|
| **Output** | Binary pass/fail | Quantitative: "3,241 nulls (2.7%) out of 121,087 rows" |
| **Failing rows** | Not shown | Sample of actual failing rows on WARN/FAIL |
| **Blast radius** | Not computed | Full downstream dependency graph of changed models |
| **Scope** | You specify `--select` | Auto-detects changed models from `git diff` |
| **Requires** | Full dbt environment | Just `manifest.json` + Snowflake creds |
| **Interface** | CLI output | Conversational + interactive HTML dashboard with Plotly charts |
| **Thresholds** | Pass or fail (with optional warn severity) | Configurable WARN/FAIL thresholds per check type |

The blast radius alone is worth it — knowing that your change to `int_gtm_aql_leads` affects 113 downstream models before you merge is the kind of context that prevents broken dashboards.

## How it works

```
manifest.json ──→ git diff (changed models) ──→ blast radius (BFS downstream)
                                                         │
                                               generate SQL checks
                                                         │
                                               execute against Snowflake
                                                         │
                                      quantitative PASS / WARN / FAIL
                                                         │
                                         ├── results.json
                                         ├── compare.csv (sorted by severity)
                                         └── dashboard.html (Plotly charts)
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
| `guardrail_review` | Full pipeline: generate checks, execute SQL, quantitative results |
| `guardrail_checks` | Preview generated SQL without executing |
| `guardrail_dashboard` | HTML dashboard with Plotly charts from last review |

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

| Status | When | Action |
|--------|------|--------|
| **FAIL** (TIER0) | PK duplicates or zero rows | Must fix before merge |
| **FAIL** (HIGH) | Null rate > 5% on not_null column | Investigate immediately |
| **WARN** | Unexpected values, low FK match, or null rate > 0.1% | Review before merge |
| **PASS** | All thresholds met | No action needed |

## Dashboard

Every review generates an interactive HTML dashboard at `<dbt_project>/.guardrail/dashboard.html`:

- **Dark theme** with collapsible sections per check category
- **Plotly bar charts** for value distributions (accepted_values checks)
- **Expandable sample rows** on FAIL/WARN results — click "show rows" to see the actual data
- **Blast radius** listed with downstream dependency arrows
- **Color-coded** FAIL (red) / WARN (yellow) / PASS (green) with auto-expansion of problem sections

Run `guardrail_dashboard` (or `/guardrail` which opens it automatically) to generate and open in your browser.

## Output files

After each review, guardrail writes to `<dbt_project>/.guardrail/`:

| File | Contents |
|------|----------|
| `results.json` | Structured results with timestamps, model list, blast radius |
| `compare.csv` | Sorted by severity (FAIL > WARN > PASS) for quick scanning |
| `dashboard.html` | Interactive dashboard with collapsible sections and Plotly distribution charts |

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
uv run pytest tests/ -v       # 56 tests
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
    └── dashboard.html   # Plotly + dark theme dashboard template
```

## License

MIT
