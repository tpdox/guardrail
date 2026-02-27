"""HTML dashboard generation from check results via Jinja2."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from guardrail.evaluate import CheckResult


def generate_dashboard(
    results: list[CheckResult],
    branch: str,
    models_reviewed: list[str],
    blast_radius: list[str],
    output_path: str | Path,
    open_browser: bool = False,
) -> Path:
    """Generate an HTML dashboard from check results."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    template_dir = Path(__file__).parent / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)
    template = env.get_template("dashboard.html")

    # Organize results by section
    fail_count = sum(1 for r in results if r.status == "FAIL")
    warn_count = sum(1 for r in results if r.status == "WARN")
    pass_count = sum(1 for r in results if r.status == "PASS")

    grain_results = [r for r in results if r.category == "grain"]
    distribution_results = [r for r in results if r.category == "distribution"]
    join_results = [r for r in results if r.category == "join"]
    rowcount_results = [r for r in results if r.category == "rowcount"]

    # Build distribution chart data for Plotly
    dist_charts = _build_distribution_charts(distribution_results)

    html = template.render(
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        branch=branch,
        models_reviewed=models_reviewed,
        blast_radius=blast_radius,
        fail_count=fail_count,
        warn_count=warn_count,
        pass_count=pass_count,
        total_count=len(results),
        grain_results=grain_results,
        distribution_results=distribution_results,
        join_results=join_results,
        rowcount_results=rowcount_results,
        dist_charts=dist_charts,
    )

    output_path.write_text(html)

    if open_browser:
        if sys.platform == "darwin":
            subprocess.run(["open", str(output_path)], check=False)
        elif sys.platform == "linux":
            subprocess.run(["xdg-open", str(output_path)], check=False)

    return output_path


def _build_distribution_charts(results: list[CheckResult]) -> list[dict]:
    """Build Plotly chart data from value_distribution results."""
    charts = []
    for r in results:
        if r.check != "value_distribution" or not r.raw_data:
            continue
        labels = []
        values = []
        for row in r.raw_data:
            label = str(row.get("VALUE", row.get("value", "?")))
            count = row.get("ROW_COUNT", row.get("row_count", 0))
            labels.append(label)
            values.append(count)
        col = r.model
        if r.raw_data:
            col = f"{r.model}.{r.detail.split(' in ')[-1] if ' in ' in r.detail else 'column'}"
        charts.append({
            "title": col,
            "labels": labels,
            "values": values,
            "id": f"dist-{r.model}-{id(r)}",
        })
    return charts
