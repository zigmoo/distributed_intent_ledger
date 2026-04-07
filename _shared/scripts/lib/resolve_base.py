#!/usr/bin/env python3
"""
resolve_base.py — Canonical DIL base resolver for Python scripts.

Resolution order:
  1) explicit argument
  2) BASE_DIL / DIL_BASE / CLAWVAULT_BASE env vars
  3) repo-relative from script location
  4) legacy fallback: $HOME/Documents/dil_agentic_memory_0001
"""

from __future__ import annotations

import os
from pathlib import Path


def resolve_dil_base(script_dir: str | Path | None = None, explicit: str | None = None) -> str:
    if explicit:
        return str(Path(explicit).expanduser())

    env_base = os.environ.get("BASE_DIL") or os.environ.get("DIL_BASE") or os.environ.get(
        "CLAWVAULT_BASE"
    )
    if env_base:
        return str(Path(env_base).expanduser())

    if script_dir:
        repo_base = Path(script_dir).resolve().parent.parent
        if (repo_base / "_shared").is_dir():
            return str(repo_base)

    legacy = Path.home() / "Documents" / "dil_agentic_memory_0001"
    if (legacy / "_shared").is_dir():
        return str(legacy)

    raise RuntimeError("Could not resolve DIL base. Set BASE_DIL to your vault path.")

