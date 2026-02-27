<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/logo.svg">
  <source media="(prefers-color-scheme: light)" srcset="assets/logo-dark.svg">
  <img alt="guardrail" src="assets/logo-dark.svg" width="480">
</picture>

<br/>

**Automated dbt model review that runs inside Claude Code.** Parses your manifest, detects changed models, generates SQL checks, executes them against Snowflake, and returns PASS/WARN/FAIL verdicts — all through MCP tools you can call conversationally.

<br/>

```
/guardrail

  Reviewing fact_gtm_aql_spine on feature/aql-spine-v4-dbt...

  38 checks generated:
    12 grain  ·  18 distribution  ·  7 join  ·  1 rowcount

  Results:  0 FAIL  ·  2 WARN  ·  36 PASS

  WARN  unexpected_values  product    2 unexpected value(s): 'Grader Pro' (341 rows), 'Unknown' (12 rows)
  WARN  fk_match_rate      int_gtm_aql_cw_outcomes  118,432/121,087 rows match (97.81%)
```

---

## What it checks

| Category | Check | Severity | What it validates |
|----------|-------|----------|-------------------|
| **Grain** | `pk_duplicates` | TIER0 | Zero duplicate values in unique-tested columns |
| **Grain** | `null_rate` | HIGH | Null rate under threshold for not_null-tested columns |
| **Distribution** | `value_distribution` | NORMAL | Full breakdown of distinct values (informational) |
| **Distribution** | `unexpected_values` | HIGH | No values outside accepted_values tests |
| **Join** | `fk_match_rate` | NORMAL | FK match rate against parent models via inferred or explicit join keys |
| **Rowcount** | `row_count` | NORMAL | Table is not empty |

Checks are generated automatically from your **dbt manifest** — unique tests become PK checks, not_null tests become null rate checks, accepted_values tests become distribution checks, and model dependencies become join checks. No configuration required for the basics.

## How it works

```
manifest.json ──→ detect changed models (git diff) ──→ generate SQL checks
                                                              │
                                                              ▼
                              PASS / WARN / FAIL  ◀── execute against Snowflake
                                     │
                                     ├──→ results.json
                                     ├──→ compare.csv
                                     └──→ dashboard.html (Plotly charts)
```

## Install

### As a Claude Code plugin (recommended)

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
# Defaults shown — override as needed
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
/guardrail status                           # project overview + last review
/guardrail fact_orders                      # review a specific model
/guardrail fact_orders,dim_customers        # review multiple models
```

### MCP tools

| Tool | Description |
|------|-------------|
| `guardrail_status` | Manifest age, model count, git branch, changed models, blast radius, last review summary |
| `guardrail_review` | Full pipeline: generate checks, execute SQL, evaluate results, write output files |
| `guardrail_checks` | Preview generated SQL without executing — useful for debugging |
| `guardrail_dashboard` | Generate HTML dashboard with Plotly charts from last review |

### Programmatic

```python
from guardrail.manifest import load_manifest
from guardrail.checks import generate_checks

manifest = load_manifest("~/dbt-project")
checks = generate_checks(manifest, ["fact_orders"])

for check in checks:
    print(f"[{check.category}] {check.check} — {check.sql[:80]}...")
```

## Interpreting results

| Status | When | Action |
|--------|------|--------|
| **FAIL** (TIER0) | PK duplicates or zero rows | Must fix before merge |
| **FAIL** (HIGH) | Null rate > 5% on not_null column | Investigate immediately |
| **WARN** | Unexpected values, low FK match, or null rate > 0.1% | Review before merge |
| **PASS** | All thresholds met | No action needed |

## Blast radius

guardrail computes the full downstream impact of your changes by walking the manifest's dependency graph (BFS, max depth 10). This tells you exactly which models, exposures, and dashboards could break.

```
Changed:  int_gtm_aql_leads
          ├── fact_gtm_aql_spine
          │   └── qa_gtm_summary
          ├── fact_gtm_funnel
          │   ├── fact_gtm_funnel_aggregated
          │   └── gtm_semantic_view
          └── ... (113 downstream models)
```

## Output files

After each review, guardrail writes to `<dbt_project>/.guardrail/`:

| File | Format | Contents |
|------|--------|----------|
| `results.json` | JSON | Full structured results with timestamps and metadata |
| `compare.csv` | CSV | Sorted by severity (FAIL > WARN > PASS) for quick scanning |
| `dashboard.html` | HTML | Interactive dashboard with collapsible sections and Plotly distribution charts |

## Plugin features

When installed as a Claude Code plugin, guardrail also includes:

- **PostToolUse hook** — after any `dbt build` or `dbt run` command, suggests running a guardrail review
- **`/guardrail` slash command** — conversational interface with guided workflow
- **Automatic model detection** — no need to specify models; guardrail diffs your branch against `main`

## Development

```bash
git clone https://github.com/tpdox/guardrail.git
cd guardrail
uv sync --extra dev
uv run pytest tests/ -v       # 48 tests
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
