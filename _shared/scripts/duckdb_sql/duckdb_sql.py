# file path: _shared/scripts/duckdb_sql/duckdb_sql.py

import sys
import os
import re
import argparse
import tabulate
import duckdb
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).resolve().parent
LIB_DIR = SCRIPT_DIR.parent / "lib"
sys.path.insert(0, str(LIB_DIR))

from resolve_base import resolve_dil_base
from tool_forge_log import ToolForgeLogger

_logger = None


def resolve_base_dir():
    """Marker-based resolution per Script Forge Standard #16."""
    return resolve_dil_base(script_dir=SCRIPT_DIR)


def setup_logging(base_dir, verbose):
    """Set up ToolForgeLogger per Tool Forge Standard #12."""
    global _logger
    if not verbose:
        return None
    _logger = ToolForgeLogger("duckdb_sql", "query", base_dir)
    return str(_logger.path)


def log_info(msg, verbose):
    if verbose and _logger:
        _logger.info(msg)


def log_error(msg, verbose):
    if verbose and _logger:
        _logger.error(msg)


def make_table_name(data_file):
    """Derive a SQL-safe table name from the data filename."""
    table_name = Path(data_file).stem
    table_name = re.sub(r"[^a-zA-Z0-9_]", "_", table_name)
    if table_name and table_name[0].isdigit():
        table_name = "_" + table_name
    return table_name


def is_jsonl(filepath):
    """Check if file is JSONL/JSON by extension."""
    return Path(filepath).suffix.lower() in (".jsonl", ".json", ".ndjson")


def create_table_from_file(con, filepath, table_name, sep=",", verbose=False):
    """Create an ephemeral table from a CSV or JSONL file."""
    if is_jsonl(filepath):
        log_info(f"Creating ephemeral table '{table_name}' from JSONL {filepath}", verbose)
        con.execute(
            f"CREATE TABLE {table_name} AS SELECT * FROM read_json_auto('{filepath}')"
        )
    else:
        log_info(f"Creating ephemeral table '{table_name}' from CSV {filepath}", verbose)
        con.execute(
            f"CREATE TABLE {table_name} AS SELECT * FROM read_csv('{filepath}', header=true, delim='{sep}', strict_mode=false, ignore_errors=true)"
        )


def auto_inject_from(sql_query, table_name):
    """If SQL has no FROM clause, inject one before WHERE/GROUP/ORDER/LIMIT."""
    sql_lower = sql_query.lower()
    if "from" in sql_lower:
        return sql_query
    keywords = [" where ", " group by ", " having ", " order by ", " limit ", " offset "]
    insert_pos = len(sql_query)
    for kw in keywords:
        pos = sql_lower.find(kw)
        if pos != -1 and pos < insert_pos:
            insert_pos = pos
    return sql_query[:insert_pos] + f" FROM {table_name}" + sql_query[insert_pos:]


def print_results(rows, columns, args, output_mode="table"):
    """Print results based on output mode and flags."""
    separator = args.sep

    if not rows:
        output = "No results found."
    elif len(columns) == 2 and columns[0] == "" and columns[1] == "":
        # .show output
        output_lines = []
        for r in rows:
            output_lines.append(f"{r[0]:>14}: {r[1]}")
        output = "\n".join(output_lines)
    elif args.single_value and len(rows) == 1 and len(columns) == 1:
        output = str(rows[0][0])
    elif args.json:
        import json
        result = []
        for row in rows:
            result.append(dict(zip(columns, [str(v) for v in row])))
        output = json.dumps(result, indent=2)
    else:
        headers = None if args.no_headers else columns
        if args.no_grid and args.no_headers:
            output_lines = []
            for row in rows:
                output_lines.append(separator.join(str(cell) for cell in row))
            output = "\n".join(output_lines)
        else:
            tablefmt = "plain" if args.no_grid else "grid"
            if headers is None:
                output_lines = []
                for row in rows:
                    output_lines.append(separator.join(str(cell) for cell in row))
                output = "\n".join(output_lines)
            else:
                output = tabulate.tabulate(rows, headers=headers, tablefmt=tablefmt)

    # Handle output destination
    should_display = not (hasattr(args, "output_file_only") and args.output_file_only)

    if args.output_file or (hasattr(args, "output_file_only") and args.output_file_only):
        base_dir = resolve_base_dir()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        import subprocess
        hostname = subprocess.check_output(["hostname", "-s"], text=True).strip().lower()
        data_dir = os.path.join(base_dir, "_shared", "data", "duckdb_sql")
        os.makedirs(data_dir, exist_ok=True)
        output_file = os.path.join(data_dir, f"{hostname}.duckdb_sql.results.{timestamp}.txt")
        with open(output_file, "w") as f:
            f.write(output)
        print(f"Output written to: {output_file}", file=sys.stderr)

    if should_display:
        print(output)


def handle_dot_command(command, con, csv_file, args):
    """Handle DuckDB dot commands."""
    cmd = command.lower().strip()
    if cmd == ".schema":
        tables_result = con.execute("SHOW TABLES").fetchall()
        if not tables_result:
            return [], []
        all_schemas = []
        columns = ["table_name", "column_name", "column_type", "nullable"]
        for (table_name,) in tables_result:
            sample_result = con.execute(f"SELECT * FROM {table_name} LIMIT 1")
            col_names = [desc[0] for desc in sample_result.description]
            for col_name in col_names:
                all_schemas.append((table_name, col_name, "VARCHAR", "YES"))
        return all_schemas, columns
    elif cmd == ".show":
        settings = [
            ("echo", "off"),
            ("headers", "on"),
            ("mode", "table"),
            ("nullvalue", '"NULL"'),
            ("output", "stdout"),
            ("colseparator", f'"{args.sep}"'),
            ("rowseparator", '"\\n"'),
            ("width", ""),
            ("filename", csv_file),
        ]
        return settings, ["", ""]
    elif cmd.startswith(".mode "):
        mode = cmd.split()[1]
        print(f"Output mode set to: {mode}")
        return None, None
    else:
        print(f"Unknown dot command: {command}")
        return None, None


def main():
    parser = argparse.ArgumentParser(
        description="Execute SQL queries against CSV/JSONL files using DuckDB",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
    Examples:
      duckdb_sql -d data.csv -s "SELECT * FROM data LIMIT 5"
      duckdb_sql -d data.csv -s ".schema"
      duckdb_sql -d data.csv -s "SELECT COUNT(*)" -S
      duckdb_sql -d data.csv -s "SELECT * FROM data" -g -H
      duckdb_sql -d data.csv -s "SELECT * FROM data" --sep "|"
      duckdb_sql -d data.csv -s "SELECT * FROM data" -j

      # JSONL support (auto-detected by extension)
      duckdb_sql -d bookmarks.jsonl -s "SELECT COUNT(*)" -S
      duckdb_sql -d accounts.jsonl -s "SELECT handle FROM accounts"

      # Multi-file joins (each -d creates a named table from the filename stem)
      duckdb_sql -d people.csv -d orders.csv -s "SELECT p.name, SUM(o.amount) FROM people p JOIN orders o ON p.name = o.name GROUP BY p.name"
      duckdb_sql -d accounts.jsonl -d account_posts.jsonl -s "SELECT a.handle, ap.role FROM account_posts ap JOIN accounts a ON ap.accountId = a.accountId"

    Required arguments:
      -d DATA             Path to data file (CSV, JSONL). Repeatable for multi-file joins.
      -s SQL              SQL query or DuckDB dot command

    Optional arguments:
      -g, --no-grid            Remove grid formatting from output
      -H, --no-headers         Remove column labels from output
      -S, --single-value       For single-cell results, output just the value
      -j, --json               Output results as JSON array
      -f, --output-file        Write output to data directory file AND display
      -F, --output-file-only   Write output to data directory file only
      --sep SEP                Column separator for CSV files (default: ,)
      -v, --verbose            Enable verbose logging
        """,
    )
    parser.add_argument("-d", "--data", required=True, action="append", help="Path to data file (CSV/JSONL). Repeat for multi-file joins.")
    parser.add_argument("-s", "--sql", required=True, help="SQL query or dot command")
    parser.add_argument("-g", "--no-grid", action="store_true", help="Remove grid formatting")
    parser.add_argument("-H", "--no-headers", action="store_true", help="Remove column labels")
    parser.add_argument("-S", "--single-value", action="store_true", help="Single-cell value only")
    parser.add_argument("-j", "--json", action="store_true", help="Output as JSON array")
    parser.add_argument("-f", "--output-file", action="store_true", help="Write to file AND stdout")
    parser.add_argument("-F", "--output-file-only", action="store_true", help="Write to file only")
    parser.add_argument("--sep", "--delimiter", default=",", help="Column separator (default: ,)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()
    data_files = args.data
    sql_query = args.sql
    verbose = args.verbose

    base_dir = resolve_base_dir()
    log_file = setup_logging(base_dir, verbose)

    if log_file:
        script_args = " ".join(f'"{a}"' if " " in a else a for a in sys.argv[1:])
        log_info(f"Command: duckdb_sql {script_args}", verbose)
        log_info(f"Data files: {data_files}", verbose)
        log_info(f"SQL query: {sql_query}", verbose)
        log_info(f"Log file: {log_file}", verbose)

    # Dot commands — load all files, then run
    if sql_query.startswith("."):
        log_info(f"Executing dot command: {sql_query}", verbose)
        con = duckdb.connect()
        for df in data_files:
            if os.path.exists(df):
                create_table_from_file(con, df, make_table_name(df), args.sep, verbose)
        rows, columns = handle_dot_command(sql_query, con, data_files[0], args)
        con.close()
        if rows is not None and columns is not None:
            print_results(rows, columns, args)
        sys.exit(0)

    # Validate all files exist
    for df in data_files:
        if not os.path.exists(df):
            log_error(f"Data file not found: {df}", verbose)
            print(f"Error: Data file '{df}' does not exist.", file=sys.stderr)
            sys.exit(1)

    # Load all data files as named tables
    con = duckdb.connect()
    first_table_name = None
    for df in data_files:
        tname = make_table_name(df)
        if first_table_name is None:
            first_table_name = tname
        create_table_from_file(con, df, tname, args.sep, verbose)

    sql_query = auto_inject_from(sql_query, first_table_name)
    log_info(f"Executing: {sql_query}", verbose)

    try:
        result = con.execute(sql_query)
        rows = result.fetchall()
        columns = [desc[0] for desc in result.description]
        log_info(f"Returned {len(rows)} rows, {len(columns)} columns", verbose)
        print_results(rows, columns, args)
    except Exception as e:
        log_error(f"SQL error: {e}", verbose)
        print(f"Error executing SQL: {e}", file=sys.stderr)
        con.close()
        sys.exit(1)

    con.close()
    log_info("Execution completed", verbose)
    if _logger:
        _logger.close()


if __name__ == "__main__":
    main()
