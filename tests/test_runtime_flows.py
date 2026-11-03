"""Whole-call tests of the runtime against the fake host, for failures the conformance suites
do not cause: racing confirms, outcomes the adapter reports as unknown, hostile document IDs."""
from __future__ import annotations


import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "conformance"))

from suites.harness import Case, Subject  # noqa: E402

SUBJECT = None


def subject() -> Subject:
    global SUBJECT
    if SUBJECT is None:
        SUBJECT = Subject([sys.executable, "-m", "sample_cli"], REPO / "tests" / "sample")
    return SUBJECT


DELETE = ["part", "delete", "--session", "fake-1", "--doc", "doc-1", "--id", "R9"]


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
                        self.assertIn(out.details.get("conflict"), ("token_used", "target_locked", "document_changed"), out.stdout[:400])
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


if __name__ == "__main__":
    unittest.main()


