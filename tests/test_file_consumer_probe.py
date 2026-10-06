"""Probe contract tests use explicit simulated_adapter evidence, never real browser claims."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_file_consumer_probe as probe
from validate_contract import validate_value


def state(result):
    """Driver objects live in data on success and in error.details on failure (COR-002)."""
    return result["data"] if result["ok"] else result["error"]["details"]


def simulated_readback(*_args):
    return {"user_agent": "simulated-consumer", "id": "body", "x": "12",
            "root_width": "40mm", "root_height": "30mm",
            "bbox": {"x": 12, "y": 4, "width": 10, "height": 6},
            "viewbox": {"x": 0, "y": 0, "width": 40, "height": 30}}


class FileConsumerProbeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.browser = self.root / "chrome.exe"
        self.browser.write_bytes(b"simulated-executable-never-launched")
        self.output = self.root / "new-output"
        self.version = patch.object(probe, "browser_version", return_value="simulated-version")
        self.commit = patch.object(probe, "source_commit", return_value="a" * 40)
        self.version.start()
        self.commit.start()
        self.addCleanup(self.version.stop)
        self.addCleanup(self.commit.stop)

    def run_simulated(self):
        result = probe.run_probe(self.browser, self.output, consumer_kind="simulated_adapter")
        self.assertEqual(validate_value("response", result), [])
        evidence = state(result).get("evidence")
        if evidence is not None:
            self.assertEqual(validate_value("evidence", evidence), [])
        return result

    def test_missing_browser_refuses_before_creating_output(self):
        result = probe.run_probe(self.root / "missing.exe", self.output)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "E_CONFIG")
        self.assertFalse(self.output.exists())
        self.assertNotIn("receipt", result["error"]["details"])
        self.assertEqual(validate_value("response", result), [])

    def test_existing_directory_is_never_overwritten(self):
        self.output.mkdir()
        sentinel = self.output / "user-content.svg"
        sentinel.write_text("existing user work", encoding="utf-8")
        result = self.run_simulated()
        self.assertEqual(result["error"]["code"], "E_VALIDATION")
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "existing user work")
        self.assertEqual(list(self.output.iterdir()), [sentinel])

    def test_plan_and_state_drift_never_rewrite_changed_file(self):
        path = self.root / "sample.svg"
        path.write_text(probe.SVG, encoding="utf-8")
        before = probe.digest(path)
        planned = probe.plan(path, "known-operation")
        self.assertEqual(probe.digest(path), before)
        path.write_text(probe.SVG.replace('x="5"', 'x="6"'), encoding="utf-8")
        changed = probe.digest(path)
        with self.assertRaises(probe.ProbeError) as caught:
            probe.apply_plan(planned)
        self.assertEqual(caught.exception.code, "E_CONFLICT")
        self.assertEqual(probe.digest(path), changed)

    def test_timeout_after_write_preserves_applied_state(self):
        with patch.object(probe, "read_browser", side_effect=probe.ProbeError("E_VERIFY_INCOMPLETE", "simulated timeout")):
            result = self.run_simulated()
        outcome = state(result)["receipt"]["outcome"]
        self.assertFalse(result["ok"])
        self.assertEqual(outcome["change"], "applied")
        self.assertEqual(outcome["persistence"], "saved")
        self.assertEqual(outcome["verification"]["status"], "incomplete")
        self.assertFalse(result["error"]["retryable"])
        self.assertEqual(state(result)["evidence"]["kind"], "simulated_adapter")

    def test_browser_timeout_retains_partial_output_without_claiming_observation(self):
        self.output.mkdir()
        svg = self.root / "sample.svg"
        svg.write_text(probe.SVG, encoding="utf-8")
        partial_dom = b'<pre id="observation">{"x":"12"}</pre>'
        browser_stderr = b"synthetic consumer diagnostic; no actual browser was launched"
        with patch.object(probe.subprocess, "Popen") as launch, patch.object(probe.subprocess, "run"):
            process = launch.return_value
            process.pid, process.returncode = 12345, -1
            process.poll.return_value = None
            process.wait.side_effect = [subprocess.TimeoutExpired([str(self.browser)], 30), -1]

            def emit_partial_output(_argv, **kwargs):
                kwargs["stdout"].write(partial_dom)
                kwargs["stderr"].write(browser_stderr)
                return process

            launch.side_effect = emit_partial_output
            with self.assertRaises(probe.ProbeError) as caught:
                probe.read_browser(self.browser, svg, self.output, "timed-out", 30)
        self.assertEqual(caught.exception.code, "E_VERIFY_INCOMPLETE")
        self.assertEqual((self.output / "timed-out-dom.html").read_bytes(), partial_dom)
        self.assertEqual((self.output / "timed-out-stderr.log").read_bytes(), browser_stderr)
        self.assertFalse((self.output / "timed-out-observation.json").exists())
        record = json.loads((self.output / "timed-out-process.json").read_text(encoding="utf-8"))
        self.assertEqual(record["wait"], "timed_out")
        self.assertIsNone(record["returncode_before_cleanup"])
        process.communicate.assert_not_called()

    def test_browser_readback_requires_clean_exit_in_a_disposable_tooling_profile(self):
        self.output.mkdir()
        svg = self.root / "sample.svg"
        svg.write_text(probe.SVG, encoding="utf-8")
        dom = ('<pre id="observation">' + json.dumps(simulated_readback()) + '</pre>').encode()
        with patch.object(probe.subprocess, "Popen") as launch:
            process = launch.return_value
            process.pid, process.returncode = 12345, 0
            process.wait.return_value = 0

            def emit_output(_argv, **kwargs):
                kwargs["stdout"].write(dom)
                kwargs["stderr"].write(b"synthetic consumer; not actual browser evidence")
                return process

            launch.side_effect = emit_output
            observation = probe.read_browser(self.browser, svg, self.output, "clean", 30)
            argv = launch.call_args.args[0]
            self.assertEqual(observation["process"]["argv"], argv)
            self.assertEqual(observation["process"]["returncode"], 0)
            self.assertTrue({"--test-type", "--password-store=basic", "--use-mock-keychain"} <= set(argv))
            profile = Path(next(arg.split("=", 1)[1] for arg in argv if arg.startswith("--user-data-dir=")))
            self.assertEqual(profile.parent, self.output)
            self.assertFalse(profile.exists())
            process.returncode = 1
            process.wait.return_value = 1
            with self.assertRaises(probe.ProbeError) as caught:
                probe.read_browser(self.browser, svg, self.output, "nonzero", 30)
            process.communicate.assert_not_called()
        self.assertEqual(caught.exception.code, "E_VERIFY_INCOMPLETE")
        self.assertFalse((self.output / "nonzero-observation.json").exists())
        record = json.loads((self.output / "nonzero-process.json").read_text(encoding="utf-8"))
        self.assertEqual(record["returncode"], 1)

    def test_exited_consumer_does_not_wait_for_descendant_stdio_closure(self):
        """Real Python process regression, explicitly not real browser evidence."""
        self.output.mkdir()
        svg = self.root / "sample.svg"
        svg.write_text(probe.SVG, encoding="utf-8")
        child_ready, child_done = self.root / "child-ready", self.root / "child-done"
        child_code = ("import sys,time; from pathlib import Path; "
                      "Path(sys.argv[1]).write_text('ready'); time.sleep(2); "
                      "Path(sys.argv[2]).write_text('done')")
        dom = '<pre id="observation">' + json.dumps(simulated_readback()) + '</pre>'
        parent_code = ("import subprocess,sys,time; from pathlib import Path; "
                       "subprocess.Popen([sys.executable,'-B','-c',sys.argv[1],sys.argv[2],sys.argv[3]], "
                       "stdout=sys.stdout,stderr=sys.stderr, "
                       "creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)); "
                       "print(sys.argv[4],flush=True); "
                       "deadline=time.monotonic()+2\n"
                       "while not Path(sys.argv[2]).exists() and time.monotonic()<deadline: time.sleep(0.01)\n")
        real_popen = subprocess.Popen

        def launch_python(_argv, **kwargs):
            return real_popen([sys.executable, "-B", "-c", parent_code, child_code,
                               str(child_ready), str(child_done), dom], **kwargs)

        def await_owned_child():
            deadline = time.monotonic() + 5
            while not child_done.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(child_done.exists(), "The bounded owned Python helper must finish.")
            time.sleep(0.1)

        self.addCleanup(await_owned_child)
        with patch.object(probe.subprocess, "Popen", side_effect=launch_python):
            observation = probe.read_browser(self.browser, svg, self.output, "inherited-stdio", 1)
        self.assertTrue(child_ready.exists())
        self.assertFalse(child_done.exists(), "The helper still holds stdio after the parent exits.")
        self.assertEqual(observation["process"]["returncode"], 0)
        self.assertEqual(observation["process"]["wait"], "completed")
        self.assertEqual(observation["process"]["capture"], "files")
        self.assertEqual(observation["user_agent"], "simulated-consumer")

    def test_failed_independent_check_does_not_claim_no_write(self):
        wrong = simulated_readback()
        wrong["bbox"]["x"] = 99
        with patch.object(probe, "read_browser", return_value=wrong):
            result = self.run_simulated()
        outcome = state(result)["receipt"]["outcome"]
        self.assertFalse(result["ok"])
        self.assertEqual(outcome["execution"], "completed")
        self.assertEqual(outcome["change"], "applied")
        self.assertEqual(outcome["verification"]["status"], "failed")

    def test_failure_logging_error_does_not_lose_stdout_receipt(self):
        original = probe.save_json

        def deny_failure_logs(path, value):
            if path.name in {"probe-error.json", "failure-response.json", "response.json", "evidence.json"}:
                raise PermissionError("simulated diagnostics permission failure")
            return original(path, value)

        with patch.object(probe, "save_json", side_effect=deny_failure_logs), patch.object(
                probe, "read_browser", side_effect=probe.ProbeError("E_VERIFY_INCOMPLETE", "simulated timeout")):
            result = self.run_simulated()
        self.assertFalse(result["ok"])
        self.assertEqual(state(result)["receipt"]["outcome"]["change"], "applied")
        self.assertEqual(state(result)["evidence"]["kind"], "simulated_adapter")
        self.assertTrue(result["error"]["details"]["retention_failures"])

    def test_incomplete_file_write_is_not_success_or_rollback(self):
        original = probe.apply_plan

        def partial_write(value):
            if value["operation_id"] == "operation-drift":
                return original(value)
            Path(value["path"]).write_text("<svg", encoding="utf-8")
            raise OSError("simulated partial write")

        with patch.object(probe, "apply_plan", side_effect=partial_write):
            result = self.run_simulated()
        outcome = state(result)["receipt"]["outcome"]
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "E_OUTCOME_UNKNOWN")
        self.assertEqual(outcome["change"], "unknown")
        self.assertEqual(outcome["persistence"], "unknown")
        self.assertEqual(outcome["verification"]["status"], "not_run")

    def test_mocked_success_is_marked_simulated_and_lost_reply_query_does_not_rewrite(self):
        with patch.object(probe, "read_browser", side_effect=simulated_readback) as reader:
            result = self.run_simulated()
        self.assertTrue(result["ok"])
        self.assertEqual(reader.call_count, 3)
        self.assertEqual(state(result)["evidence"]["kind"], "simulated_adapter")
        self.assertIn("mocked", " ".join(state(result)["evidence"]["limitations"]))
        record = json.loads((self.output / "operation-record.json").read_text(encoding="utf-8"))
        self.assertEqual(record["operation_id"], state(result)["receipt"]["operation_id"])
        self.assertEqual(record["writes"], 1)
        self.assertEqual(probe.digest(self.output / "sample.svg"), state(result)["receipt"]["snapshot_after"]["revision"][7:])

    def test_macos_browser_bundle_name_supports_simulated_consumer_contract(self):
        self.browser = self.root / "Google Chrome.app" / "Contents" / "MacOS" / "Google Chrome"
        self.browser.parent.mkdir(parents=True)
        self.browser.write_bytes(b"simulated-executable-never-launched")
        with patch.object(probe, "read_browser", side_effect=simulated_readback) as reader:
            result = self.run_simulated()
        self.assertTrue(result["ok"])
        self.assertEqual(reader.call_count, 3)
        evidence = state(result)["evidence"]
        self.assertEqual(evidence["kind"], "simulated_adapter")
        self.assertEqual(evidence["extensions"]["browser_executable"], str(self.browser))
        self.assertEqual(evidence["extensions"]["initial_browser_metadata"]["sha256"], probe.digest(self.browser))
        self.assertTrue(evidence["extensions"]["browser_identity"]["stable"])

    def test_missing_machine_metadata_preserves_valid_evidence_and_records_unknown(self):
        with patch.object(probe.platform, "machine", return_value=""), patch.object(
                probe, "read_browser", side_effect=simulated_readback):
            result = self.run_simulated()
        self.assertTrue(result["ok"])
        evidence = state(result)["evidence"]
        self.assertEqual(evidence["environment"]["arch"], "unknown")
        self.assertIn("CPU architecture could not be observed", " ".join(evidence["limitations"]))
        self.assertEqual(evidence["kind"], "simulated_adapter")

    def test_version_change_keeps_written_file_but_marks_identity_incomplete(self):
        with patch.object(probe, "browser_version", side_effect=["154.0.8037.59", "154.0.8037.93"]), patch.object(
                probe, "read_browser", side_effect=simulated_readback):
            result = self.run_simulated()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "E_VERIFY_INCOMPLETE")
        outcome = state(result)["receipt"]["outcome"]
        self.assertEqual(outcome["change"], "applied")
        self.assertEqual(outcome["persistence"], "saved")
        self.assertEqual(outcome["verification"]["status"], "incomplete")
        evidence = state(result)["evidence"]
        self.assertEqual(evidence["environment"]["components"][0]["identity_status"], "unavailable")
        self.assertIsNone(evidence["environment"]["components"][0]["version"])
        self.assertEqual(evidence["extensions"]["browser_identity"]["after"]["version"], "154.0.8037.93")

    def test_executable_hash_change_is_not_hidden_by_matching_version(self):
        self.assert_executable_hash_change_detected(self.browser)

    def test_executable_hash_change_is_injected_for_a_normalized_browser_alias(self):
        (self.root / "lexical-parent").mkdir()
        alias = self.root / "lexical-parent" / ".." / "chrome.exe"
        self.assertNotEqual(alias, self.browser)
        self.assertEqual(alias.resolve(), self.browser.resolve())
        self.assert_executable_hash_change_detected(alias)

    def assert_executable_hash_change_detected(self, browser):
        original = probe.digest
        browser_reads = 0
        normalized_browser = browser.resolve()

        def changed_digest(path):
            nonlocal browser_reads
            if Path(path).resolve() == normalized_browser:
                browser_reads += 1
                return ("a" if browser_reads == 1 else "b") * 64
            return original(path)

        with patch.object(probe, "digest", side_effect=changed_digest), patch.object(
                probe, "read_browser", side_effect=simulated_readback):
            result = probe.run_probe(browser, self.output, consumer_kind="simulated_adapter")
        self.assertGreaterEqual(browser_reads, 2, "Both browser identity observations must receive the injected hashes.")
        self.assertFalse(result["ok"])
        self.assertEqual(state(result)["receipt"]["outcome"]["verification"]["status"], "incomplete")
        identity = state(result)["evidence"]["extensions"]["browser_identity"]
        self.assertEqual(identity["before"]["version"], identity["after"]["version"])
        self.assertNotEqual(identity["before"]["sha256"], identity["after"]["sha256"])

    def test_stable_identity_is_a_required_seventh_check(self):
        with patch.object(probe, "read_browser", side_effect=simulated_readback):
            result = self.run_simulated()
        self.assertTrue(result["ok"])
        evidence = state(result)["evidence"]
        self.assertEqual(len(evidence["checks"]), 7)
        self.assertTrue(evidence["extensions"]["browser_identity"]["stable"])
        self.assertEqual(evidence["environment"]["components"][0]["identity_status"], "observed")

    def test_missing_cli_arguments_produce_one_json_error(self):
        stream = io.StringIO()
        # StringIO has no reconfigure method; preserve the same print boundary.
        with patch.object(sys, "argv", ["run_file_consumer_probe.py"]), patch.object(sys, "stdout") as stdout:
            stdout.write.side_effect = stream.write
            result = probe.main()
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(stream.getvalue())["error"]["code"], "E_VALIDATION")


if __name__ == "__main__":
    unittest.main()
