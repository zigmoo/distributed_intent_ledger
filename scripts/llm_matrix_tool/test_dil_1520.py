#!/usr/bin/env python3
"""Tests for DIL-1520: shell injection fixes and file handle leak fix in llm_matrix_tool."""

import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import llm_matrix_tool as lmt


class TestShellEscaping(unittest.TestCase):
    """Verify model IDs with shell metacharacters are properly escaped."""

    MALICIOUS_IDS = [
        "model'; rm -rf /; echo '",
        'model"; rm -rf /; echo "',
        "model$(whoami)",
        "model`whoami`",
        "model;echo pwned",
        "model|cat /etc/passwd",
        "model&& echo pwned",
        "model\necho pwned",
        "model with spaces",
        "normal-model-id",
    ]

    @mock.patch("llm_matrix_tool.run")
    def test_load_remote_model_escapes_model_id(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        lmt.ARGS = lmt.parse_args(["--remote-timeout", "10"])

        for mid in self.MALICIOUS_IDS:
            record = lmt.ModelRuntimeRecord(
                host="test", server="lmstudio", registry_key="k", api_model_id=mid
            )
            lmt.load_remote_model(record, 8192)
            call_args = mock_run.call_args
            cmd_list = call_args[0][0]
            shell_cmd = cmd_list[-1]
            safe = shlex.quote(mid)
            self.assertIn(safe, shell_cmd, f"Model ID {mid!r} not properly quoted in: {shell_cmd}")

    @mock.patch("llm_matrix_tool.run")
    def test_retry_with_unload_all_escapes_model_id(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        lmt.ARGS = lmt.parse_args(["--remote-timeout", "10", "--probe-timeout", "10"])

        for mid in self.MALICIOUS_IDS:
            record = lmt.ModelRuntimeRecord(
                host="test", server="lmstudio", registry_key="k", api_model_id=mid
            )
            with mock.patch("llm_matrix_tool.probe_model") as mock_probe:
                mock_probe.return_value = lmt.ProbeResult(
                    model_ref="lmstudio/k", status="ok", reason="test",
                    output_tokens=10, elapsed_s=1.0, returncode=0
                )
                lmt.retry_with_unload_all(record, 8192, probe_timeout=10)

            load_calls = [c for c in mock_run.call_args_list if "load" in str(c)]
            for call in load_calls:
                cmd_list = call[0][0]
                shell_cmd = cmd_list[-1]
                if "lms load" in shell_cmd:
                    safe = shlex.quote(mid)
                    self.assertIn(safe, shell_cmd,
                                  f"Model ID {mid!r} not properly quoted in retry: {shell_cmd}")
            mock_run.reset_mock()

    @mock.patch("llm_matrix_tool.run")
    def test_remote_current_context_escapes_model_id(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout="4096\n", stderr="")

        for mid in self.MALICIOUS_IDS:
            lmt.remote_current_context(mid)
            call_args = mock_run.call_args
            cmd_list = call_args[0][0]
            shell_cmd = cmd_list[-1]
            safe = shlex.quote(mid)
            self.assertIn(safe, shell_cmd,
                          f"Model ID {mid!r} not properly quoted in context query: {shell_cmd}")
            self.assertNotIn(mid.replace("'", ""), shell_cmd if "'" in mid else "",
                             f"Old band-aid strip detected for {mid!r}")
            mock_run.reset_mock()

    @mock.patch("llm_matrix_tool.run")
    def test_remote_current_context_uses_sys_argv(self, mock_run):
        """The Python one-liner should use sys.argv[1], not string interpolation."""
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        lmt.remote_current_context("any-model")
        shell_cmd = mock_run.call_args[0][0][-1]
        self.assertIn("sys.argv[1]", shell_cmd)
        self.assertNotIn("mid='", shell_cmd, "Old inline mid= pattern should be gone")

    @mock.patch("llm_matrix_tool.run")
    def test_context_len_is_int_in_load(self, mock_run):
        """context_len should be cast to int to prevent injection via that parameter."""
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        lmt.ARGS = lmt.parse_args(["--remote-timeout", "10"])
        record = lmt.ModelRuntimeRecord(
            host="test", server="lmstudio", registry_key="k", api_model_id="safe-model"
        )
        lmt.load_remote_model(record, 8192)
        shell_cmd = mock_run.call_args[0][0][-1]
        self.assertIn("--context-length 8192", shell_cmd)


class TestFileHandleLeak(unittest.TestCase):
    """Verify print_summary uses a with-block for the run ledger."""

    def test_print_summary_closes_file_handle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = Path(tmpdir) / "test_runs.jsonl"
            with mock.patch.object(lmt, "RUN_LEDGER", ledger):
                lmt.ok = lmt.fail = lmt.retry_ok = lmt.retry_fail = 0
                lmt.ratchet_retry_ok = lmt.ratchet_retry_fail = 0
                lmt.optimize_ok = lmt.optimize_fail = 0
                lmt.guardrail = lmt.bad_id = lmt.ctx_err = 0
                lmt.print_summary(10, 5, run_mode="test")

            self.assertTrue(ledger.exists(), "Ledger file should be created")
            content = ledger.read_text()
            record = json.loads(content.strip())
            self.assertEqual(record["tool"], "llm_matrix_tool")
            self.assertEqual(record["total"], 10)
            self.assertEqual(record["selected"], 5)
            self.assertEqual(record["mode"], "test")

    def test_print_summary_source_in_inspect(self):
        """Verify the source code uses a with-block (static check)."""
        import inspect
        source = inspect.getsource(lmt.print_summary)
        self.assertIn("with RUN_LEDGER.open", source,
                      "print_summary should use 'with RUN_LEDGER.open(...)' pattern")
        self.assertNotIn("RUN_LEDGER.open(\"a\"", source.replace("with RUN_LEDGER", ""),
                         "There should be no bare RUN_LEDGER.open() outside a with-block")


class TestContextLadder(unittest.TestCase):
    """Sanity checks for build_context_ladder used by ratchet retry."""

    def test_basic_ladder(self):
        ladder = lmt.build_context_ladder(8192, 65536)
        self.assertEqual(ladder[0], 8192)
        self.assertEqual(ladder[-1], 65536)
        for i in range(1, len(ladder)):
            self.assertGreater(ladder[i], ladder[i - 1])

    def test_min_equals_max(self):
        ladder = lmt.build_context_ladder(8192, 8192)
        self.assertEqual(ladder, [8192])


if __name__ == "__main__":
    unittest.main()
