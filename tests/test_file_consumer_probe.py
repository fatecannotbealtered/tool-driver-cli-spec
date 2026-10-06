"""Probe contract tests use explicit simulated_adapter evidence, never real browser claims."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import socket
import sys
import tempfile
import threading
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
        with patch.object(probe.subprocess, "Popen") as launch, patch.object(probe.subprocess, "run") as run, patch.object(
                probe.sys, "platform", "linux"):
            run.return_value.returncode = 0
            process = launch.return_value
            process.pid, process.returncode = 12345, -1
            process.poll.side_effect = [None, -1]
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

    def test_macos_graceful_close_still_requires_a_real_zero_exit(self):
        self.output.mkdir()
        svg = self.root / "sample.svg"
        svg.write_text(probe.SVG, encoding="utf-8")
        dom = ('<pre id="observation">' + json.dumps(simulated_readback()) + '</pre>').encode()
        close = {"method": "Browser.close", "response_received": True, "transport": "owned_profile_loopback"}
        with patch.object(probe.sys, "platform", "darwin"), patch.object(
                probe.subprocess, "Popen") as launch, patch.object(probe, "close_owned_browser", return_value=close) as closer:
            process = launch.return_value
            process.pid, process.returncode = 12345, None
            process.poll.side_effect = lambda: process.returncode

            def emit_output(_argv, **kwargs):
                kwargs["stdout"].write(dom)
                kwargs["stdout"].flush()
                profile = Path(next(arg.split("=", 1)[1] for arg in _argv if arg.startswith("--user-data-dir=")))
                (profile / "DevToolsActivePort").write_text("12345\n/devtools/browser/" + "a" * 36)
                return process

            def exited_zero(**_kwargs):
                process.returncode = 0
                return 0

            launch.side_effect, process.wait.side_effect = emit_output, exited_zero
            observed = probe.read_browser(self.browser, svg, self.output, "mac-clean", 30)
            self.assertEqual(observed["process"]["graceful_close"], close)
            self.assertEqual(observed["process"]["returncode"], 0)
            self.assertEqual(closer.call_count, 1)
            self.assertIn("--remote-debugging-address=127.0.0.1", launch.call_args.args[0])
            self.assertIn("--remote-debugging-port=0", launch.call_args.args[0])
            process.returncode = None

            def exited_nonzero(**_kwargs):
                process.returncode = 1
                return 1

            process.wait.side_effect = exited_nonzero
            with self.assertRaises(probe.ProbeError) as caught:
                probe.read_browser(self.browser, svg, self.output, "mac-nonzero", 30)
        self.assertEqual(caught.exception.code, "E_VERIFY_INCOMPLETE")
        self.assertFalse((self.output / "mac-nonzero-observation.json").exists())

    def test_graceful_close_refuses_invalid_owned_endpoints_before_connecting(self):
        profile = self.root / "owned-profile"
        profile.mkdir()
        for content in ("80\n/devtools/browser/" + "a" * 36,
                        "12345\nws://external.example/browser",
                        "12345\n/devtools/browser/" + "a" * 36 + "\nextra"):
            with self.subTest(content=content), patch.object(probe.socket, "create_connection") as connect:
                (profile / "DevToolsActivePort").write_text(content, encoding="ascii")
                with self.assertRaises(probe.ProbeError):
                    probe.close_owned_browser(profile, 1)
                connect.assert_not_called()

    def test_graceful_close_protocol_verifies_handshake_masked_request_and_response(self):
        """Owned synthetic loopback server, never actual browser evidence."""
        for scenario in ("success", "bad-handshake", "refused-close"):
            with self.subTest(scenario=scenario):
                profile = self.root / scenario
                profile.mkdir()
                listener = socket.socket()
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
                listener.settimeout(5)
                port = listener.getsockname()[1]
                (profile / "DevToolsActivePort").write_text(str(port) + "\n/devtools/browser/" + "a" * 36)
                failures, requests = [], []

                def serve():
                    try:
                        with listener, listener.accept()[0] as channel:
                            channel.settimeout(5)

                            def receive(count):
                                data = b""
                                while len(data) < count:
                                    part = channel.recv(count - len(data))
                                    if not part:
                                        raise AssertionError("Incomplete synthetic client request")
                                    data += part
                                return data

                            header = b""
                            while not header.endswith(b"\r\n\r\n") and len(header) < 16384:
                                header += receive(1)
                            fields = dict(line.split(": ", 1) for line in header.decode("ascii").split("\r\n")[1:] if ": " in line)
                            nonce = fields["Sec-WebSocket-Key"]
                            accept = probe.base64.b64encode(probe.hashlib.sha1(
                                (nonce + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
                            if scenario == "bad-handshake":
                                accept = "incorrect"
                            channel.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                                             "Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept + "\r\n\r\n").encode())
                            if scenario == "bad-handshake":
                                return
                            flags, length = receive(2)
                            self.assertEqual(flags, 0x81)
                            self.assertTrue(length & 0x80)
                            mask = receive(4)
                            payload = receive(length & 127)
                            requests.append(json.loads(bytes(value ^ mask[i % 4] for i, value in enumerate(payload))))
                            response = ({"id": 1, "result": {}} if scenario == "success"
                                        else {"id": 1, "error": {"message": "synthetic refusal"}})
                            payload = json.dumps(response).encode()
                            channel.sendall(bytes([0x81, len(payload)]) + payload)
                    except Exception as error:
                        failures.append(error)

                thread = threading.Thread(target=serve, daemon=True)
                thread.start()
                try:
                    if scenario == "success":
                        result = probe.close_owned_browser(profile, 3)
                        self.assertEqual(result["method"], "Browser.close")
                        self.assertTrue(result["response_received"])
                    else:
                        with self.assertRaises(probe.ProbeError):
                            probe.close_owned_browser(profile, 3)
                finally:
                    thread.join(timeout=5)
                    listener.close()
                self.assertFalse(thread.is_alive())
                self.assertEqual(failures, [])
                self.assertEqual(requests, [] if scenario == "bad-handshake" else [{"id": 1, "method": "Browser.close"}])

    def test_exited_consumer_does_not_wait_for_descendant_stdio_closure(self):
        """Real Python process regression, explicitly not real browser evidence."""
        self.output.mkdir()
        svg = self.root / "sample.svg"
        svg.write_text(probe.SVG, encoding="utf-8")
        dom = '<pre id="observation">' + json.dumps(simulated_readback()) + '</pre>'
        launch_python, child_ready, child_done = self.owned_python_with_inherited_stdio(dom, "readback")
        with patch.object(probe.subprocess, "Popen", side_effect=launch_python):
            observation = probe.read_browser(self.browser, svg, self.output, "inherited-stdio", 1)
        self.assertTrue(child_ready.exists())
        self.assertFalse(child_done.exists(), "The helper still holds stdio after the parent exits.")
        self.assertEqual(observation["process"]["returncode"], 0)
        self.assertEqual(observation["process"]["wait"], "completed")
        self.assertEqual(observation["process"]["capture"], "files")
        self.assertEqual(observation["user_agent"], "simulated-consumer")

    def test_version_query_does_not_wait_for_descendant_stdio_closure(self):
        launch_python, child_ready, child_done = self.owned_python_with_inherited_stdio("simulated-version", "version")
        with patch.object(probe.subprocess, "Popen", side_effect=launch_python):
            version = probe.command_version([str(self.browser), "--version"])
        self.assertEqual(version, "simulated-version")
        self.assertTrue(child_ready.exists())
        self.assertFalse(child_done.exists(), "Version metadata waits for the parent, not helper stdio.")

    @unittest.skipUnless(probe.os.name == "nt", "Windows native file version API")
    def test_windows_version_reads_real_python_metadata_without_starting_a_process(self):
        with patch.object(probe.subprocess, "Popen") as launch:
            version = self.version.temp_original(Path(sys.executable))
        launch.assert_not_called()
        self.assertRegex(version, r"^\d+\.\d+\.\d+\.\d+$")
        self.assertEqual(tuple(map(int, version.split(".")[:2])), sys.version_info[:2])

    @unittest.skipUnless(probe.os.name == "nt", "Windows native file version API")
    def test_windows_version_rejects_unversioned_file_without_starting_a_process(self):
        with patch.object(probe.subprocess, "Popen") as launch:
            with self.assertRaises(probe.ProbeError) as caught:
                self.version.temp_original(self.browser)
        launch.assert_not_called()
        self.assertEqual(caught.exception.code, "E_CONFIG")

    def test_windows_version_resource_bounds_and_signature_are_checked_before_dereferencing(self):
        """Synthetic resource API; never real browser or Windows acceptance evidence."""
        for scenario in ("valid", "missing", "oversized", "unreadable", "missing-root", "outside", "short", "signature"):
            with self.subTest(scenario=scenario):
                def size(_path, _handle):
                    return 0 if scenario == "missing" else 1024 * 1024 + 1 if scenario == "oversized" else 128

                def read(_path, _handle, _size, buffer):
                    fields = (probe.ctypes.c_uint32 * 13).from_buffer(buffer)
                    fields[0] = 0 if scenario == "signature" else 0xFEEF04BD
                    fields[4], fields[5] = (152 << 16) | 7, (123 << 16) | 9
                    return scenario != "unreadable"

                def query(buffer, block, value, length):
                    self.assertEqual(block, "\\")
                    address = probe.ctypes.addressof(buffer) + (256 if scenario == "outside" else 0)
                    probe.ctypes.cast(value, probe.ctypes.POINTER(probe.ctypes.c_void_p)).contents.value = address
                    probe.ctypes.cast(length, probe.ctypes.POINTER(probe.ctypes.c_uint32)).contents.value = 4 if scenario == "short" else 52
                    return scenario != "missing-root"

                with patch.object(probe.ctypes, "WinDLL", create=True) as load:
                    api = load.return_value
                    api.GetFileVersionInfoSizeW, api.GetFileVersionInfoW, api.VerQueryValueW = size, read, query
                    if scenario == "valid":
                        self.assertEqual(probe.windows_product_version(self.browser), "152.7.123.9")
                    else:
                        with self.assertRaises(probe.ProbeError) as caught:
                            probe.windows_product_version(self.browser)
                        self.assertEqual(caught.exception.code, "E_CONFIG")
                    load.assert_called_once_with("version.dll", use_last_error=True, winmode=0x800)

    def owned_python_with_inherited_stdio(self, payload, label):
        child_ready, child_done = self.root / (label + "-child-ready"), self.root / (label + "-child-done")
        child_code = ("import sys,time; from pathlib import Path; "
                      "Path(sys.argv[1]).write_text('ready'); time.sleep(2); "
                      "Path(sys.argv[2]).write_text('done')")
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
                               str(child_ready), str(child_done), payload], **kwargs)

        def await_owned_child():
            deadline = time.monotonic() + 5
            while not child_done.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(child_done.exists(), "The bounded owned Python helper must finish.")
            time.sleep(0.1)

        self.addCleanup(await_owned_child)
        return launch_python, child_ready, child_done

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

    def test_macos_testing_browser_bundle_supports_simulated_consumer_contract(self):
        self.browser = self.root / "Google Chrome for Testing.app" / "Contents" / "MacOS" / "Google Chrome for Testing"
        self.browser.parent.mkdir(parents=True)
        self.browser.write_bytes(b"simulated-executable-never-launched")
        with patch.object(probe, "read_browser", side_effect=simulated_readback):
            result = self.run_simulated()
        self.assertTrue(result["ok"])
        self.assertEqual(state(result)["evidence"]["kind"], "simulated_adapter")
        self.assertEqual(state(result)["evidence"]["extensions"]["browser_executable"], str(self.browser))

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
