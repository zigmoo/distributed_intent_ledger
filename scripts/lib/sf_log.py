"""sf_log.py — Script Forge shared logging library (Python).

Stdlib-only. Produces logs compatible with log_river harvest and identical
in format to sf_log.sh output.

Usage:
    from sf_log import SFLogger

    log = SFLogger("tool_name", "action", base)
    log.info("processed 42 items")
    log.section("Validation")
    log.info("all checks passed")
    log.error("something broke")
    log.close()

    # Or as context manager:
    with SFLogger("tool_name", "action", base) as log:
        log.info("doing work")

Log file: $LOG_DIR/<tool_name>/<tool_name>.<action>.<YYYYMMDD_HHMMSS>.log
Format: YYYY-MM-DD HH:MM:SS.mmm | LEVEL | message
"""

from __future__ import annotations

import datetime as dt
import os
import platform
import subprocess
from pathlib import Path


class SFLogger:
    def __init__(self, tool_name: str, action: str = "run", base: str | Path | None = None):
        self.tool_name = tool_name
        self.action = action
        self.section_num = 0
        self.timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")

        if base:
            log_dir = Path(base) / "_shared" / "logs" / tool_name
        else:
            log_dir = Path("/tmp/sf_logs") / tool_name
        log_dir.mkdir(parents=True, exist_ok=True)

        self.log_file = log_dir / f"{tool_name}.{action}.{self.timestamp}.log"
        self._handle = self.log_file.open("w", encoding="utf-8")

        machine = "unknown"
        try:
            machine = subprocess.check_output(
                ["hostname", "-s"], text=True, timeout=2
            ).strip().lower()
        except Exception:
            machine = platform.node().split(".")[0].lower()

        agent = (
            os.environ.get("AGENT_NAME")
            or os.environ.get("AGENT_ID")
            or os.environ.get("ASSISTANT_ID")
            or "unknown"
        )

        self._write("=" * 80)
        self._write(f"LOG_FILE: {self.log_file}")
        self._write("=" * 80)
        self._write("")
        self.section("Configuration")
        self._write(f"timestamp:  {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self._write(f"tool:       {tool_name}")
        self._write(f"action:     {action}")
        self._write(f"machine:    {machine}")
        self._write(f"agent:      {agent}")
        self._write(f"pid:        {os.getpid()}")
        self._write("")

    def _write(self, line: str) -> None:
        self._handle.write(line + "\n")
        self._handle.flush()

    def _ts(self) -> str:
        now = dt.datetime.now()
        return now.strftime("%Y-%m-%d %H:%M:%S.") + f"{now.microsecond // 1000:03d}"

    def info(self, msg: str) -> None:
        self._write(f"{self._ts()} | INFO | {msg}")

    def warn(self, msg: str) -> None:
        self._write(f"{self._ts()} | WARN | {msg}")

    def error(self, msg: str) -> None:
        self._write(f"{self._ts()} | ERROR | {msg}")

    def section(self, name: str) -> None:
        self.section_num += 1
        self._write(f"Section {self.section_num}: {name}")
        self._write("-" * 80)

    def close(self) -> None:
        self._write("")
        self._write("=" * 80)
        self._write(f"LOG_FILE: {self.log_file}")
        self._write("=" * 80)
        self._handle.close()

    @property
    def path(self) -> Path:
        return self.log_file

    def __enter__(self) -> "SFLogger":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
