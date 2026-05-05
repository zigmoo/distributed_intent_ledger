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
                host="test", server="lmstudio", provider="lmstudio", registry_key="k", api_model_id=mid
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
                host="test", server="lmstudio", provider="lmstudio", registry_key="k", api_model_id=mid
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
            lmt.remote_current_context("test", mid)
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
        lmt.remote_current_context("test", "any-model")
        shell_cmd = mock_run.call_args[0][0][-1]
        self.assertIn("sys.argv[1]", shell_cmd)
        self.assertNotIn("mid='", shell_cmd, "Old inline mid= pattern should be gone")

    @mock.patch("llm_matrix_tool.run")
    def test_context_len_is_int_in_load(self, mock_run):
        """context_len should be cast to int to prevent injection via that parameter."""
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        lmt.ARGS = lmt.parse_args(["--remote-timeout", "10"])
        record = lmt.ModelRuntimeRecord(
            host="test", server="lmstudio", provider="lmstudio", registry_key="k", api_model_id="safe-model"
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


class TestHarnessConfigurator(unittest.TestCase):
    """Verify OpenCode harness config generation and model selection helpers."""

    def test_build_opencode_config(self):
        row = {
            "backend_model_id": "qwen/qwen3.6-35b-a3b",
            "display_name": "Qwen3.6 35B A3B",
        }
        cfg = lmt.build_opencode_config("moosacrem1promax", "http://10.0.1.142:1234/v1", row)
        self.assertEqual(cfg["model"], "moosacrem1promax/qwen3.6-35b-a3b")
        provider = cfg["provider"]["moosacrem1promax"]
        self.assertEqual(provider["npm"], "@ai-sdk/openai-compatible")
        self.assertEqual(provider["options"]["baseURL"], "http://10.0.1.142:1234/v1")
        self.assertEqual(provider["models"]["qwen3.6-35b-a3b"]["id"], "qwen/qwen3.6-35b-a3b")

    @mock.patch("llm_matrix_tool.read_registry_rows")
    def test_choose_powerful_model_uses_size_with_tps_gate(self, mock_rows):
        mock_rows.return_value = [
            {
                "host": "moosacrem1promax",
                "server": "lmstudio",
                "backend_model_id": "small-fast",
                "downloaded": True,
                "status": "active",
                "size_bytes": 10,
                "tps": 100,
            },
            {
                "host": "moosacrem1promax",
                "server": "lmstudio",
                "backend_model_id": "large-responsive",
                "downloaded": True,
                "status": "active",
                "size_bytes": 100,
                "tps": 12,
            },
        ]
        selected = lmt.choose_registry_model("moosacrem1promax", "lmstudio", "powerful")
        self.assertEqual(selected["backend_model_id"], "large-responsive")

    @mock.patch("llm_matrix_tool.read_registry_rows")
    def test_choose_fastest_model_uses_tps(self, mock_rows):
        mock_rows.return_value = [
            {
                "host": "moosacrem1promax",
                "server": "lmstudio",
                "backend_model_id": "large-responsive",
                "downloaded": True,
                "status": "active",
                "size_bytes": 100,
                "tps": 12,
            },
            {
                "host": "moosacrem1promax",
                "server": "lmstudio",
                "backend_model_id": "small-fast",
                "downloaded": True,
                "status": "active",
                "size_bytes": 10,
                "tps": 100,
            },
        ]
        selected = lmt.choose_registry_model("moosacrem1promax", "lmstudio", "fastest")
        self.assertEqual(selected["backend_model_id"], "small-fast")

    @mock.patch("llm_matrix_tool.write_opencode_config_on_target")
    @mock.patch("llm_matrix_tool.verify_source_context")
    @mock.patch("llm_matrix_tool.load_source_model")
    @mock.patch("llm_matrix_tool.discover_base_url_from_target")
    @mock.patch("llm_matrix_tool.registry_candidates")
    @mock.patch("llm_matrix_tool.choose_registry_model")
    def test_configure_specific_preserves_requested_api_model_id(
        self, mock_choose, mock_candidates, mock_discover, mock_load, mock_context, mock_write
    ):
        args = lmt.parse_args([
            "--configure-harness", "opencode",
            "--target-host", "target",
            "--source-host", "moosacrem1promax",
            "--selection", "specific",
            "--specific-model", "qwen/qwen3.6-35b-a3b",
            "--configure-dry-run",
        ])
        mock_choose.return_value = {
            "model_id": "Qwen3.6-35B-A3B-GGUF",
            "backend_model_id": "Qwen3.6-35B-A3B-GGUF",
            "display_name": "Qwen3.6 35B A3B",
        }
        mock_candidates.return_value = []
        mock_discover.return_value = "http://source:1234/v1"
        lmt.configure_harness(args)
        cfg = mock_write.call_args.kwargs.get("cfg") or mock_write.call_args.args[2]
        self.assertEqual(cfg["model"], "moosacrem1promax/qwen3.6-35b-a3b")
        self.assertEqual(
            cfg["provider"]["moosacrem1promax"]["models"]["qwen3.6-35b-a3b"]["id"],
            "qwen/qwen3.6-35b-a3b",
        )

    def test_extract_context_error_from_opencode_message(self):
        text = (
            "The number of tokens to keep from the initial prompt is greater than "
            "the context length (n_keep: 10567 >= n_ctx: 4096)."
        )
        parsed = lmt.extract_context_error(text)
        self.assertEqual(parsed["n_keep"], 10567)
        self.assertEqual(parsed["n_ctx"], 4096)

    @mock.patch("llm_matrix_tool.record_registry_context")
    def test_record_opencode_context_failure_updates_registry(self, mock_record):
        text = "context length (n_keep: 10567 >= n_ctx: 4096)"
        self.assertTrue(lmt.record_opencode_context_failure(
            "qwen/qwen3.6-35b-a3b", stdout=text, source_host="moosacrem1promax"
        ))
        mock_record.assert_called_once_with(
            "qwen/qwen3.6-35b-a3b", "too_small", 4096, host="moosacrem1promax"
        )

    @mock.patch("llm_matrix_tool.record_registry_context")
    @mock.patch("llm_matrix_tool.remote_current_context")
    def test_verify_source_context_fails_below_expected(self, mock_context, mock_record):
        mock_context.return_value = "4096"
        ok = lmt.verify_source_context("moosacrem1promax", "qwen/qwen3.6-35b-a3b", 32768)
        self.assertFalse(ok)
        mock_record.assert_called_once_with(
            "qwen/qwen3.6-35b-a3b", "too_small", 4096, host="moosacrem1promax"
        )

    @mock.patch("llm_matrix_tool.record_registry_context")
    @mock.patch("llm_matrix_tool.remote_current_context")
    def test_verify_source_context_records_ok(self, mock_context, mock_record):
        mock_context.return_value = "32768"
        ok = lmt.verify_source_context("moosacrem1promax", "qwen/qwen3.6-35b-a3b", 32768)
        self.assertTrue(ok)
        mock_record.assert_called_once_with(
            "qwen/qwen3.6-35b-a3b", "ok", 32768, host="moosacrem1promax"
        )

    def test_model_identity_matches_api_and_registry_ids(self):
        row = {
            "model_id": "Qwen3.6-35B-A3B-GGUF",
            "backend_model_id": "Qwen3.6-35B-A3B-GGUF",
        }
        self.assertTrue(lmt.model_identity_matches(row, "qwen/qwen3.6-35b-a3b"))

    def test_record_registry_context_adds_alias_to_matching_row(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = Path(tmpdir) / "model_registry.jsonl"
            row = {
                "host": "moosacrem1promax",
                "server": "lmstudio",
                "model_id": "Qwen3.6-35B-A3B-GGUF",
                "backend_model_id": "Qwen3.6-35B-A3B-GGUF",
            }
            registry.write_text(json.dumps(row) + "\n")
            with mock.patch.object(lmt, "REGISTRY", registry):
                with mock.patch.object(lmt, "CONTEXT_CACHE", Path(tmpdir) / "cache.jsonl"):
                    lmt.record_registry_context("qwen/qwen3.6-35b-a3b", "too_small", 4096, host="moosacrem1promax")
            updated = json.loads(registry.read_text().splitlines()[0])
            self.assertEqual(updated["context_verification_status"], "too_small")
            self.assertEqual(updated["last_verified_context_length"], 4096)
            self.assertIn("qwen/qwen3.6-35b-a3b", updated["aliases"])

    def test_record_registry_context_does_not_update_other_hosts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = Path(tmpdir) / "model_registry.jsonl"
            rows = [
                {
                    "host": "moosacrem1promax",
                    "server": "lmstudio",
                    "model_id": "Qwen3.6-35B-A3B-GGUF",
                    "backend_model_id": "Qwen3.6-35B-A3B-GGUF",
                },
                {
                    "host": "framemoowork",
                    "server": "lmstudio",
                    "model_id": "Qwen3.6-35B-A3B-GGUF",
                    "backend_model_id": "Qwen3.6-35B-A3B-GGUF",
                },
            ]
            registry.write_text("".join(json.dumps(row) + "\n" for row in rows))
            with mock.patch.object(lmt, "REGISTRY", registry):
                with mock.patch.object(lmt, "CONTEXT_CACHE", Path(tmpdir) / "cache.jsonl"):
                    lmt.record_registry_context("qwen/qwen3.6-35b-a3b", "too_small", 4096, host="moosacrem1promax")
            updated = [json.loads(line) for line in registry.read_text().splitlines()]
            self.assertEqual(updated[0]["context_verification_status"], "too_small")
            self.assertNotIn("context_verification_status", updated[1])

    def test_record_registry_context_creates_row_when_unmatched(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = Path(tmpdir) / "model_registry.jsonl"
            registry.write_text("")
            with mock.patch.object(lmt, "REGISTRY", registry):
                with mock.patch.object(lmt, "CONTEXT_CACHE", Path(tmpdir) / "cache.jsonl"):
                    lmt.record_registry_context("new/model", "too_small", 4096, host="host-a")
            rows = [json.loads(line) for line in registry.read_text().splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["model_id"], "new/model")
            self.assertEqual(rows[0]["context_verification_status"], "too_small")


if __name__ == "__main__":
    unittest.main()
