"""Whole-call tests of the runtime against the fake host, for failures the conformance suites
do not cause: racing confirms, outcomes the adapter reports as unknown, hostile document IDs."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "conformance"))

from suites.harness import FLAGS, Case, Subject  # noqa: E402

SUBJECT = None


def subject() -> Subject:
    global SUBJECT
    if SUBJECT is None:
        SUBJECT = Subject([sys.executable, "-m", "sample_cli"], REPO / "tests" / "sample")
    return SUBJECT


DELETE = ["part", "delete", "--session", "fake-1", "--doc", "doc-1", "--id", "R9"]
MOVE = ["part", "move", "--session", "fake-1", "--doc", "doc-1"]


def start(case: Case, *args: str) -> subprocess.Popen:
    """Start the tool and return while it runs."""
    return subprocess.Popen(case.subject.argv + list(args), cwd=case.subject.project, env=case.env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, creationflags=FLAGS)


def wait_for(case: Case, method: str, count: int = 1) -> None:
    end = time.monotonic() + 30
    while len(case.calls(method)) < count:
        if time.monotonic() > end:
            raise AssertionError(f"no {method} call arrived")
        time.sleep(0.05)


class RacingConfirms(unittest.TestCase):
    def test_one_token_dispatches_once(self):
        for _ in range(3):
            with Case(subject()) as case:
                first = case.run(*DELETE)
                token = first.details["confirm_token"]
                with ThreadPoolExecutor(3) as pool:
                    outs = list(pool.map(lambda _: case.run(*DELETE, "--confirm", token, "--dangerous"), range(3)))
                self.assertEqual(sum(o.ok for o in outs), 1, [o.stdout[:300] for o in outs])
                for out in outs:
                    if not out.ok:
                        self.assertIn(out.details.get("conflict"), ("token_used", "target_locked", "document_changed", "preview_changed"), out.stdout[:400])
                self.assertEqual(len(case.applied()), 1)


class UnknownOutcomes(unittest.TestCase):
    def test_an_unknown_dimension_keeps_the_record_resolvable(self):
        with Case(subject()) as case:
            case.control("fault", rule={"method": "apply", "command": "part move", "action": "result", "result": {"change": "unknown"}})
            args = ["part", "move", "--session", "fake-1", "--doc", "doc-1", "--id", "R1", "--x", "1mm", "--y", "2mm"]
            out = case.run(*args)
            self.assertEqual(out.code, "E_OUTCOME_UNKNOWN", out.stdout[:400])
            listed = case.run("operation", "list", "--state", "unknown")
            self.assertEqual(listed.data["count"], 1)
            again = case.run(*args)
            self.assertEqual(again.details.get("conflict"), "target_locked")
            resolved = case.run(*out.details["lookup"].split()[1:])
            self.assertTrue(resolved.ok, resolved.stdout[:400])
            self.assertEqual(resolved.data["resolution"]["outcome"], "applied")
            self.assertTrue(case.run(*args).ok)

    def test_an_invalid_dispatch_state_is_unknown(self):
        with Case(subject()) as case:
            case.control("fault", rule={"method": "apply", "command": "part move", "action": "result",
                                        "result": {"dispatch_state": "maybe"}})
            out = case.run("part", "move", "--session", "fake-1", "--doc", "doc-1", "--id", "R1", "--x", "1mm", "--y", "2mm")
            self.assertEqual(out.code, "E_OUTCOME_UNKNOWN", out.stdout[:400])

    def test_a_read_back_that_matches_neither_side_needs_the_agent(self):
        with Case(subject()) as case:
            case.control("fault", rule={"method": "apply", "command": "part move", "action": "close", "apply_first": True})
            out = case.run("part", "move", "--session", "fake-1", "--doc", "doc-1", "--id", "R1", "--x", "1mm", "--y", "2mm")
            self.assertEqual(out.code, "E_OUTCOME_UNKNOWN")
            case.control("edit", document="doc-1", object="R1", field="x_mm", value=99.0)
            op = out.details["lookup"].split()[-1]
            resolved = case.run("operation", "resolve", "--id", op)
            self.assertEqual(resolved.code, "E_UNSUPPORTED", resolved.stdout[:400])
            self.assertIn("--outcome", resolved.details["next_action"])
            done = case.run("operation", "resolve", "--id", op, "--outcome", "partial", "--evidence", "x is 99 mm in the app")
            self.assertTrue(done.ok, done.stdout[:400])
            self.assertEqual(done.data["resolution"]["resolved_by"], "agent")


HUNG = '''
import sys, time
sys.path[:0] = [REPO_TESTS, REPO_SAMPLE]
from test_runtime import SampleAdapter, registration, SAMPLE, REPO
from _driver import Tool
import _driver.writes as w


class Hung(SampleAdapter):
    def apply(self, request):
        time.sleep(20)


w.WRITE_DEADLINE_MS = 500
reg = registration(path="part update", modes=["file"], flags=[{"name": "--id", "type": "string", "required": True},
                   {"name": "--value", "type": "string"}], tolerances={})
Tool(root=SAMPLE, adapter=Hung, commands=[reg], application="Files", versions="any", modes=["file"],
     contract=REPO / "contract" / "driver-contract.json").main()
'''


class KilledProcesses(unittest.TestCase):
    """An Agent harness may kill a tool that takes too long; the write it was sending is then
    an unknown outcome the Agent can settle, never a lock that stays forever (DCLI-060, DCLI-063)."""

    def kill_during(self, case: Case, args: list[str], count: int = 1) -> None:
        proc = start(case, *args)
        try:
            wait_for(case, "apply", count)
        finally:
            proc.kill()
            proc.communicate()

    def test_a_single_write(self):
        with Case(subject()) as case:
            case.control("fault", rule={"method": "apply", "command": "part move", "action": "hang"})
            self.kill_during(case, MOVE + ["--id", "R1", "--x", "1mm", "--y", "2mm"])
            again = case.run(*MOVE, "--id", "R1", "--x", "1mm", "--y", "2mm")
            self.assertEqual(again.details.get("conflict"), "target_locked", again.stdout[:400])
            self.assertIn("operation resolve", again.details["next_action"])
            unknown = case.run("operation", "list", "--state", "unknown")
            self.assertEqual(unknown.data["count"], 1)
            resolved = case.run("operation", "resolve", "--id", unknown.data["items"][0]["operation_id"])
            self.assertEqual(resolved.data["resolution"]["outcome"], "not_applied", resolved.stdout[:400])
            self.assertTrue(case.run(*MOVE, "--id", "R1", "--x", "1mm", "--y", "2mm").ok)

    def test_a_batch(self):
        with Case(subject()) as case:
            case.control("fault", rule={"method": "apply", "command": "part move", "action": "hang", "target": "R2"})
            self.kill_during(case, MOVE + ["--ids", "R1,R2,R3", "--x", "1mm", "--y", "2mm"], count=2)
            self.assertTrue(case.run(*MOVE, "--id", "R3", "--x", "1mm", "--y", "2mm").ok)
            locked = case.run(*MOVE, "--id", "R2", "--x", "1mm", "--y", "2mm")
            self.assertEqual(locked.details.get("conflict"), "target_locked", locked.stdout[:400])
            records = case.run("operation", "list", "--limit", "100").data["items"]
            batch = [r for r in records if isinstance(r.get("target"), list)][0]
            unknown = case.run("operation", "list", "--state", "unknown", "--batch", batch["operation_id"])
            self.assertEqual([i["target"]["key"].split("/")[-1] for i in unknown.data["items"]], ["R2"])


class OddReplies(unittest.TestCase):
    def test_an_unknown_dimension_value_is_unknown(self):
        with Case(subject()) as case:
            case.control("fault", rule={"method": "apply", "command": "part move", "action": "result", "result": {"change": "done"}})
            out = case.run(*MOVE, "--id", "R1", "--x", "1mm", "--y", "2mm")
            self.assertEqual(out.code, "E_OUTCOME_UNKNOWN", out.stdout[:400])

    def test_a_preview_without_targets_is_refused(self):
        with Case(subject()) as case:
            case.control("fault", rule={"method": "preview", "command": "part move", "action": "result", "result": {"targets": []}})
            out = case.run(*MOVE, "--id", "R1", "--x", "1mm", "--y", "2mm")
            self.assertEqual(out.code, "E_PROTOCOL", out.stdout[:400])
            case.grant(targets=["device:"])
            case.control("fault", rule={"method": "preview", "command": "analysis run", "action": "result",
                                        "result": {"targets": [], "changes": []}})
            out = case.run("analysis", "run", "--session", "fake-1", "--doc", "doc-1", "--depth", "3")
            self.assertEqual(out.code, "E_FORBIDDEN", out.stdout[:400])
            self.assertFalse(case.applied())

    def test_an_unreadable_field_is_not_a_known_outcome(self):
        with Case(subject()) as case:
            case.control("fault", rule={"method": "apply", "command": "part move", "action": "close", "apply_first": True})
            out = case.run(*MOVE, "--id", "R1", "--x", "1mm", "--y", "2mm")
            case.control("fault", rule={"method": "read_back", "command": "part move", "action": "unreadable", "fields": ["x_mm"]})
            resolved = case.run(*out.details["lookup"].split()[1:])
            self.assertEqual(resolved.code, "E_UNSUPPORTED", resolved.stdout[:400])


class Undo(unittest.TestCase):
    def test_a_second_undo_takes_the_change_before(self):
        with Case(subject()) as case:
            first = case.run(*MOVE, "--id", "R1", "--x", "1mm", "--y", "2mm")
            second = case.run(*MOVE, "--id", "R2", "--x", "3mm", "--y", "4mm")
            case.control("fault", rule={"method": "read_back", "command": "part move", "action": "unreadable", "fields": ["x_mm", "y_mm"]})
            undo = case.run("doc", "undo", "--session", "fake-1", "--doc", "doc-1")
            self.assertEqual(undo.code, "E_VERIFY_INCOMPLETE", undo.stdout[:400])
            case.control("clear_faults")
            dry = case.run("doc", "undo", "--session", "fake-1", "--doc", "doc-1", "--dry-run")
            self.assertIn(first.data["operation_id"], dry.data["preview"]["action"], dry.stdout[:400])
            self.assertNotIn(second.data["operation_id"], dry.data["preview"]["action"])


class Drift(unittest.TestCase):
    def test_a_token_does_not_run_a_change_nobody_saw(self):
        axis = ["axis", "move", "--device", "dev-1", "--id", "x"]
        with Case(subject()) as case:
            token = case.run(*axis, "--position", "10mm").details["confirm_token"]
            other = case.run(*axis, "--position", "500mm")
            self.assertTrue(case.run(*axis, "--position", "500mm", "--confirm", other.details["confirm_token"], "--dangerous").ok)
            out = case.run(*axis, "--position", "10mm", "--confirm", token, "--dangerous")
            self.assertEqual(out.details.get("conflict"), "preview_changed", out.stdout[:400])
            self.assertEqual(len(case.applied()), 1)


class HungAdapter(unittest.TestCase):
    def test_a_hung_in_process_call_ends_as_unknown(self):
        tmp = Path(tempfile.mkdtemp())
        doc = tmp / "board.json"
        doc.write_text("{}", encoding="utf-8")
        (tmp / "scope.json").write_text(json.dumps({"scope_id": "t", "effects": ["change"], "dangerous": False,
                                                    "targets": ["file:///"], "expires_at": "2099-01-01T00:00:00Z"}))
        script = HUNG.replace("REPO_TESTS", repr(str(REPO / "tests"))).replace("REPO_SAMPLE", repr(str(REPO / "tests" / "sample")))
        env = {**os.environ, "SAMPLE_CLI_STATE_DIR": str(tmp / "state"), "SAMPLE_CLI_SCOPE_FILE": str(tmp / "scope.json")}
        args = ["part", "update", "--doc", str(doc), "--id", "R1", "--value", "2k"]
        first = subprocess.run([sys.executable, "-c", script, *args], env=env, capture_output=True, text=True, creationflags=FLAGS)
        token = json.loads(first.stdout)["error"]["details"]["confirm_token"]
        started = time.monotonic()
        done = subprocess.run([sys.executable, "-c", script, *args, "--confirm", token], env=env, capture_output=True, text=True,
                              timeout=15, creationflags=FLAGS)
        self.assertLess(time.monotonic() - started, 10)
        envelope = json.loads(done.stdout)
        self.assertEqual((done.returncode, envelope["error"]["code"]), (8, "E_OUTCOME_UNKNOWN"), done.stdout)


class GeneratedCommands(unittest.TestCase):
    def test_a_hostile_document_id_stays_literal(self):
        hostile = "$(touch pwned)"
        config = {"instances": [{"id": "fake-1", "documents": [{"id": hostile, "name": "x.fake"}]}]}
        with Case(subject(), config) as case:
            case.control("edit", document=hostile, object="R1", field="note", value="x")
            out = case.run("doc", "save", "--session", "fake-1")
            self.assertEqual(out.code, "E_CONFIRMATION_REQUIRED", out.stdout[:400])
            self.assertIn("--doc '$(touch pwned)'", out.details["next_action"])
            self.assertIn("$.error.details.next_action", out.envelope["meta"]["untrusted"])

    def test_dry_run_and_confirm_together_are_refused(self):
        with Case(subject()) as case:
            out = case.run(*DELETE, "--dry-run", "--confirm", "anything")
            self.assertEqual(out.code, "E_USAGE")
            self.assertFalse(case.applied())

    def test_a_blocked_session_resumes_with_its_document(self):
        with Case(subject()) as case:
            case.control("set_session", session="fake-1", state="blocked")
            out = case.run("part", "move", "--id", "R1", "--x", "1mm", "--y", "2mm")
            self.assertEqual(out.code, "E_HUMAN_REQUIRED")
            self.assertIn("--session fake-1 --doc doc-1", out.details["resume"])


class UntitledDocuments(unittest.TestCase):
    def test_an_untitled_document_has_its_key(self):
        with Case(subject()) as case:
            created = case.run("doc", "create", "--session", "fake-1")
            self.assertTrue(created.ok, created.stdout[:400])
            doc = created.data["result"]
            self.assertIsNone(doc["path"])
            self.assertTrue(doc["key"].startswith("untitled:fake-1/"))
            closed = case.run("doc", "close", "--session", "fake-1", "--doc", doc["id"])
            self.assertTrue(closed.ok, closed.stdout[:400])
            self.assertEqual(closed.data["receipt"]["target"]["key"], doc["key"])





class LongJobsAndKinds(unittest.TestCase):
    """Long jobs run in the tool's own worker (DCLI-065); document kinds (DCLI-210)."""

    def test_a_long_write_returns_a_job_and_the_worker_settles_it(self):
        with Case(subject()) as case:
            out = case.run("route", "run", "--session", "fake-1", "--doc", "doc-1", "--net", "GND")
            self.assertTrue(out.ok, out.stdout[:400])
            job = out.data["result"]["job"]
            self.assertEqual(out.data["receipt"]["outcome"]["change"], "not_applicable")
            done = case.run("job", "get", "--job", job["id"], "--wait", "60s")
            self.assertEqual(done.data["state"], "completed", done.stdout[:600])
            self.assertTrue(done.data["ok"], done.stdout[:600])
            self.assertEqual(done.data["receipt"]["outcome"]["verification"], "passed", done.stdout[:600])
            self.assertEqual(len(case.applied()), 1)

    def test_a_long_read_needs_no_scope_and_returns_its_result_later(self):
        with Case(subject()) as case:
            case.revoke()
            out = case.run("design", "check", "--session", "fake-1", "--doc", "doc-1")
            self.assertTrue(out.ok, out.stdout[:400])
            job = out.data["job"]
            done = case.run("job", "get", "--job", job["id"], "--wait", "60s")
            self.assertEqual(done.data["state"], "completed", done.stdout[:600])
            self.assertIsNone(done.data["operation_id"])
            self.assertIn("result", done.data)
            listed = case.run("job", "list")
            self.assertIn(job["id"], [j["id"] for j in listed.data["items"]])

    def test_a_document_of_another_kind_is_refused(self):
        with Case(subject()) as case:
            made = case.run("doc", "create", "--session", "fake-1", "--kind", "drawing")
            self.assertTrue(made.ok, made.stdout[:400])
            doc = made.data["result"]["id"]
            out = case.run("design", "check", "--session", "fake-1", "--doc", doc)
            self.assertEqual(out.code, "E_VALIDATION", out.stdout[:400])


class ReadBackPause(unittest.TestCase):
    """The read_back_mismatch row: a change made while the tool waits is found (DVER-030)."""

    def test_a_change_made_during_the_pause_fails_the_verification(self):
        with Case(subject()) as case:
            env = {**case.env, f"{case.subject.prefix}_TEST_PAUSE_BEFORE_READ_BACK": "30"}
            proc = subprocess.Popen(case.subject.argv + MOVE + ["--id", "R1", "--x", "1mm", "--y", "2mm"], cwd=case.subject.project,
                                    env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=FLAGS)
            pause = case.state_dir / "pause.json"
            end = time.monotonic() + 30
            while not pause.exists():
                self.assertLess(time.monotonic(), end, "the tool never paused")
                time.sleep(0.05)
            self.assertIn("targets", json.loads(pause.read_text(encoding="utf-8")))
            case.control("edit", document="doc-1", object="R1", field="x_mm", value=99.0)
            stdout, _ = proc.communicate(timeout=60)
            env_out = json.loads(stdout.decode("utf-8"))
            self.assertEqual(env_out["error"]["code"], "E_VERIFY_FAILED", stdout[:600])
            self.assertFalse(pause.exists())


class CreateDocuments(unittest.TestCase):
    """doc create with --path in file mode makes the file (DCLI-212)."""

    def test_file_mode_creates_the_file_and_verifies_it(self):
        with Case(subject()) as case:
            path = str(case.work / "new-board.fake")
            first = case.run("doc", "create", "--path", path, "--kind", "board")
            self.assertTrue(first.ok, first.stdout[:400])
            self.assertTrue(os.path.isfile(path))
            self.assertEqual(first.data["receipt"]["outcome"]["verification"], "passed", first.stdout[:600])
            again = case.run("doc", "create", "--path", path)
            self.assertEqual(again.code, "E_CONFIRMATION_REQUIRED", again.stdout[:400])



class ReviewFixes(unittest.TestCase):
    """Edges the 1.0.1 review found."""

    def test_a_write_job_the_tool_runs_cannot_be_cancelled_midway(self):
        with Case(subject()) as case:
            out = case.run("route", "run", "--session", "fake-1", "--doc", "doc-1", "--net", "GND")
            job = out.data["result"]["job"]["id"]
            cancel = case.run("job", "cancel", "--job", job)
            self.assertIn(cancel.code, ("E_UNSUPPORTED", "E_VALIDATION"), cancel.stdout[:400])
            done = case.run("job", "get", "--job", job, "--wait", "60s")
            self.assertTrue(done.data["ok"], done.stdout[:400])

    def test_a_job_id_never_names_a_path(self):
        with Case(subject()) as case:
            for args in (("job", "get", "--job", "../../planted"), ("job", "cancel", "--job", "../../planted")):
                out = case.run(*args)
                self.assertEqual(out.code, "E_NOT_FOUND", out.stdout[:400])
            self.assertFalse(list(case.state_dir.rglob("*planted*")))

    def test_doc_create_refuses_a_file_an_instance_has_open(self):
        with Case(subject()) as case:
            path = case.doc_path("doc-1")
            out = case.run("doc", "create", "--path", path)
            self.assertEqual(out.details.get("conflict"), "file_open_in_session", out.stdout[:400])

    def test_a_change_shown_only_after_a_save_is_verified_by_the_save(self):
        with Case(subject()) as case:
            out = case.run("net", "update", "--session", "fake-1", "--doc", "doc-1", "--id", "N1", "--name", "GND")
            self.assertTrue(out.ok, out.stdout[:400])
            self.assertEqual(out.data["receipt"]["outcome"]["verification"], "deferred")
            operation = out.data["operation_id"]
            first = case.run("doc", "save", "--session", "fake-1", "--doc", "doc-1")
            saved = case.run("doc", "save", "--session", "fake-1", "--doc", "doc-1", "--confirm", first.details["confirm_token"])
            self.assertTrue(saved.ok, saved.stdout[:600])
            self.assertEqual(saved.data["receipt"]["outcome"]["verification"], "passed", saved.stdout[:600])
            record = case.run("operation", "get", "--id", operation)
            self.assertEqual(record.data["receipt"]["outcome"]["verification"], "passed", record.stdout[:600])

    def test_a_deferred_change_that_did_not_land_fails_the_save(self):
        with Case(subject()) as case:
            out = case.run("net", "update", "--session", "fake-1", "--doc", "doc-1", "--id", "N1", "--name", "GND")
            self.assertTrue(out.ok, out.stdout[:400])
            case.control("edit", document="doc-1", object="N1", field="name", value="OTHER")
            first = case.run("doc", "save", "--session", "fake-1", "--doc", "doc-1")
            saved = case.run("doc", "save", "--session", "fake-1", "--doc", "doc-1", "--confirm", first.details["confirm_token"])
            self.assertEqual(saved.code, "E_VERIFY_FAILED", saved.stdout[:600])

    def test_discarding_a_deferred_change_settles_it_as_not_run(self):
        with Case(subject()) as case:
            out = case.run("net", "update", "--session", "fake-1", "--doc", "doc-1", "--id", "N1", "--name", "GND")
            operation = out.data["operation_id"]
            first = case.run("doc", "close", "--session", "fake-1", "--doc", "doc-1", "--discard")
            closed = case.run("doc", "close", "--session", "fake-1", "--doc", "doc-1", "--discard",
                              "--confirm", first.details["confirm_token"], "--dangerous")
            self.assertTrue(closed.ok, closed.stdout[:600])
            record = case.run("operation", "get", "--id", operation)
            self.assertEqual(record.data["receipt"]["outcome"]["verification"], "not_run", record.stdout[:600])


    def test_a_json_flag_takes_a_structured_value(self):
        with Case(subject()) as case:
            out = case.run("net", "update", "--session", "fake-1", "--doc", "doc-1", "--id", "N1",
                           "--pins", '[{"pin": "1"}, {"pin": "2"}]', "--dry-run")
            self.assertTrue(out.ok, out.stdout[:400])
            echoed = out.data["preview"]["inputs"]["pins"]
            self.assertEqual(set(echoed), {"sha256", "bytes"}, out.stdout[:400])
            wrong = case.run("net", "update", "--session", "fake-1", "--doc", "doc-1", "--id", "N1", "--pins", '{"pin": "1"}')
            self.assertEqual(wrong.code, "E_USAGE", wrong.stdout[:400])


if __name__ == "__main__":
    unittest.main()
