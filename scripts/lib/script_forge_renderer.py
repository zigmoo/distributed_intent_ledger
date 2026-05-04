"""script_forge_renderer.py — Tool Forge shared CSV + DuckDB + J2 rendering library.

Renders markdown files from CSV data using DuckDB queries and Jinja2 templates.
Implements Tool Forge Standard #11 (CSV-Primary Data Pattern).

Usage:
    from script_forge_renderer import render_csv_to_markdown

    render_csv_to_markdown(
        csv_path="/path/to/data.csv",
        template_path="/path/to/data.md.j2",
        output_path="/path/to/data.md",
    )

    # With custom queries:
    render_csv_to_markdown(
        csv_path="/path/to/runs.csv",
        template_path="/path/to/dashboard.md.j2",
        output_path="/path/to/dashboard.md",
        queries={
            "recent_failures": "SELECT * FROM data WHERE status = 'failed' ORDER BY started_at DESC LIMIT 20",
            "success_rate": "SELECT ROUND(100.0 * SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) / COUNT(*), 1) AS percent FROM data",
        },
    )

Architecture (Standard #11):
    data.csv                  <- source of truth (DuckDB reads)
    data.md.j2                <- Jinja2 template (layout + embedded query results)
    data.md                   <- rendered output (never hand-edited, never parsed)

Dependencies: duckdb, jinja2 (both pip-installable, no transitive conflicts).
"""

from __future__ import annotations

import datetime as _datetime
from pathlib import Path
from typing import Any

import duckdb
import jinja2


def query_csv(csv_path: str | Path, sql: str) -> list[dict[str, Any]]:
    """Run a SQL query against a CSV file via DuckDB. The CSV is available as 'data' in the query."""
    csv_path = str(Path(csv_path).resolve())
    connection = duckdb.connect(":memory:")
    connection.execute(f"CREATE VIEW data AS SELECT * FROM read_csv_auto('{csv_path}')")
    result = connection.execute(sql)
    column_names = [description[0] for description in result.description]
    rows = []
    for raw_row in result.fetchall():
        rows.append(dict(zip(column_names, raw_row)))
    connection.close()
    return rows


def render_template(template_path: str | Path, template_variables: dict[str, Any]) -> str:
    """Render a Jinja2 template file with the given variables."""
    template_path = Path(template_path)
    template_loader = jinja2.FileSystemLoader(str(template_path.parent))
    template_environment = jinja2.Environment(
        loader=template_loader,
        keep_trailing_newline=True,
        undefined=jinja2.StrictUndefined,
    )
    template = template_environment.get_template(template_path.name)
    return template.render(template_variables)


def render_csv_to_markdown(
    csv_path: str | Path,
    template_path: str | Path,
    output_path: str | Path,
    queries: dict[str, str] | None = None,
) -> Path:
    """Render a markdown file from CSV data using DuckDB queries and a Jinja2 template.

    The CSV is automatically available as a table called 'data' in all queries.

    If no queries are provided, a default query 'SELECT * FROM data' is run
    and the result is available as 'rows' in the template.

    Each entry in the queries dict becomes a template variable containing
    a list of row dicts.

    Returns the path to the rendered output file.
    """
    csv_path = Path(csv_path)
    template_path = Path(template_path)
    output_path = Path(output_path)

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    if not template_path.exists():
        raise FileNotFoundError(f"Template file not found: {template_path}")

    template_variables: dict[str, Any] = {
        "rendered_at": _datetime.datetime.now(_datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "csv_path": str(csv_path),
    }

    if queries:
        for query_name, sql in queries.items():
            template_variables[query_name] = query_csv(csv_path, sql)
    else:
        template_variables["rows"] = query_csv(csv_path, "SELECT * FROM data")

    rendered_content = render_template(template_path, template_variables)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered_content, encoding="utf-8")
    return output_path
