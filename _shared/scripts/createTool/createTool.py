#!/usr/bin/env python3
"""createTool.py — Scaffold a new Tool Forge tool with all standards pre-wired.

Generates a tool drawer with bash wrapper, Python implementation, test suite stub,
golden baselines directory, j2_templates documentation, and extensionless symlink
— all compliant with Tool Forge Standards #1, #2, #10, #12, #13, #14, #16.
"""

from __future__ import annotations

import argparse
import os
import re
import stat
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR / "lib"))

from resolve_base import resolve_dil_base

try:
    from tool_forge_log import ToolForgeLogger
except ImportError:
    ToolForgeLogger = None

try:
    import jinja2
except ImportError:
    jinja2 = None

SCRIPT_NAME = "createTool"
TEMPLATE_DIR = SCRIPT_DIR / "j2_templates"
VALID_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def validate_tool_name(name: str) -> str | None:
    if not name:
        return "tool name is required"
    if not VALID_NAME_PATTERN.match(name):
        return f"tool name must match [a-z][a-z0-9_]* — got: {name}"
    if name == "createTool":
        return "cannot scaffold over createTool itself"
    return None


def render_template(template_name: str, variables: dict) -> str:
    template_path = TEMPLATE_DIR / template_name
    if not template_path.exists():
        raise FileNotFoundError(f"template not found: {template_path}")
    loader = jinja2.FileSystemLoader(str(TEMPLATE_DIR))
    environment = jinja2.Environment(loader=loader, keep_trailing_newline=True)
    template = environment.get_template(template_name)
    return template.render(variables)


def make_executable(file_path: Path) -> None:
    current_mode = file_path.stat().st_mode
    file_path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def should_be_executable(file_path: Path) -> bool:
    return file_path.suffix in {".bash", ".py", ".sh"}


def scaffold_tool(
    tool_name: str,
    description: str,
    base: Path,
    bash_only: bool = False,
    dry_run: bool = False,
    log=None,
) -> dict:
    scripts_directory = base / "_shared" / "scripts"
    tool_drawer = scripts_directory / tool_name
    bin_directory = scripts_directory / "bin"

    if tool_drawer.exists():
        return {"ok": False, "error": f"drawer already exists: {tool_drawer}"}

    template_variables = {
        "tool_name": tool_name,
        "description": description or f"{tool_name} — a Tool Forge tool",
    }

    files_to_create: dict[Path, str] = {}

    bash_wrapper_content = render_template("tool_name.bash.j2", template_variables)
    files_to_create[tool_drawer / f"{tool_name}.bash"] = bash_wrapper_content

    if not bash_only:
        python_content = render_template("tool_name.py.j2", template_variables)
        files_to_create[tool_drawer / f"{tool_name}.py"] = python_content

    test_content = render_template("tool_name.test_script.bash.j2", template_variables)
    files_to_create[tool_drawer / f"{tool_name}.test_script.bash"] = test_content

    j2_readme_content = render_template("j2_templates_README.md.j2", template_variables)
    files_to_create[tool_drawer / "j2_templates" / "README.md"] = j2_readme_content

    symlink_path = bin_directory / tool_name
    symlink_target = f"../{tool_name}/{tool_name}.bash"
    golden_directory = tool_drawer / f"{tool_name}.test_golden"
    j2_templates_directory = tool_drawer / "j2_templates"

    if dry_run:
        result = {"ok": True, "dry_run": True, "files": [str(path) for path in files_to_create]}
        result["symlink"] = f"{symlink_path} → {symlink_target}"
        result["golden_directory"] = str(golden_directory)
        result["j2_templates_directory"] = str(j2_templates_directory)
        if log:
            log.info("DRY RUN — no files written")
            for file_path in files_to_create:
                log.info(f"  would create: {file_path}")
            log.info(f"  would symlink: {symlink_path} → {symlink_target}")
            log.info(f"  would mkdir: {golden_directory}")
            log.info(f"  would mkdir: {j2_templates_directory}")
        return result

    tool_drawer.mkdir(parents=True, exist_ok=True)
    golden_directory.mkdir(parents=True, exist_ok=True)
    j2_templates_directory.mkdir(parents=True, exist_ok=True)

    for file_path, content in files_to_create.items():
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        if should_be_executable(file_path):
            make_executable(file_path)
        if log:
            log.info(f"created: {file_path}")

    if symlink_path.exists() or symlink_path.is_symlink():
        symlink_path.unlink()
    symlink_path.symlink_to(symlink_target)
    if log:
        log.info(f"symlink: {symlink_path} → {symlink_target}")

    return {
        "ok": True,
        "tool_name": tool_name,
        "drawer": str(tool_drawer),
        "files": [str(path) for path in files_to_create],
        "symlink": str(symlink_path),
        "golden_directory": str(golden_directory),
        "j2_templates_directory": str(j2_templates_directory),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="createTool",
        description="Scaffold a new Tool Forge tool with all standards pre-wired",
    )
    parser.add_argument("--name", required=True, help="tool name (lowercase, underscores)")
    parser.add_argument("--description", default="", help="one-line tool description")
    parser.add_argument("--bash-only", action="store_true", help="generate bash wrapper only, no Python pair")
    parser.add_argument("--base", required=True, help="DIL base path")
    parser.add_argument("--dry-run", action="store_true", help="show what would be created without writing")
    arguments = parser.parse_args()

    base = Path(arguments.base).expanduser().resolve()

    log = ToolForgeLogger(SCRIPT_NAME, "create", str(base)) if ToolForgeLogger else None

    if log:
        log.section("Validation")
        log.info(f"tool_name: {arguments.name}")
        log.info(f"description: {arguments.description or '(none)'}")
        log.info(f"bash_only: {arguments.bash_only}")
        log.info(f"dry_run: {arguments.dry_run}")

    validation_error = validate_tool_name(arguments.name)
    if validation_error:
        if log:
            log.error(validation_error)
            log.close()
        print(f"ERR | 2 | {validation_error}", file=sys.stderr)
        return 2

    if jinja2 is None:
        message = "jinja2 is required but not installed (pip install jinja2)"
        if log:
            log.error(message)
            log.close()
        print(f"ERR | 4 | {message}", file=sys.stderr)
        return 4

    if log:
        log.section("Scaffolding")

    result = scaffold_tool(
        tool_name=arguments.name,
        description=arguments.description,
        base=base,
        bash_only=arguments.bash_only,
        dry_run=arguments.dry_run,
        log=log,
    )

    if not result["ok"]:
        if log:
            log.error(result["error"])
            log.close()
        print(f"ERR | 3 | {result['error']}", file=sys.stderr)
        return 3

    if log:
        log.section("Result")
        if arguments.dry_run:
            log.info("DRY RUN complete")
        else:
            log.info(f"tool drawer: {result['drawer']}")
            log.info(f"symlink: {result['symlink']}")
            log.info(f"files: {len(result['files'])}")
        log.close()

    if arguments.dry_run:
        print(f"DRY RUN | {arguments.name}")
        for file_path in result["files"]:
            print(f"  would create: {file_path}")
        print(f"  would symlink: {result['symlink']}")
        print(f"  would mkdir: {result['golden_directory']}")
        print(f"  would mkdir: {result['j2_templates_directory']}")
    else:
        print(f"OK | {arguments.name} | {result['drawer']}")
        for file_path in result["files"]:
            print(f"  created: {file_path}")
        print(f"  symlink: {result['symlink']}")
        print(f"  golden: {result['golden_directory']}")
        print(f"  j2 templates: {result['j2_templates_directory']}")
        print(f"\nNext steps:")
        print(f"  {arguments.name} --help")
        print(f"  bash {result['drawer']}/{arguments.name}.test_script.bash --rebuild")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
