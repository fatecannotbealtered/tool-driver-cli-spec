"""Unit tests of the driver runtime: the rules whose check line cites runtime unit tests.

Behavior across whole calls is covered by the conformance suites, which CI runs against the
sample tool in tests/sample/ with the fake host.
"""
from __future__ import annotations

import copy
import io
import json
import shlex
import os
import subprocess
import sys
import tempfile
import textwrap

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "sdk" / "python"))
sys.path.insert(0, str(REPO / "tests" / "sample"))
sys.path.insert(0, str(REPO / "conformance"))

from _driver import Adapter, AdapterError, RegistrationError, Tool  # noqa: E402
from _driver.args import Parser, quote  # noqa: E402
from _driver.contract import Contract  # noqa: E402
from _driver.errors import DriverError  # noqa: E402
from _driver.output import Envelopes, Result  # noqa: E402
from _driver.records import Locks, Mutex, Records  # noqa: E402
from _driver.registry import Tiers, domain_command  # noqa: E402
from _driver.scope import load as load_scope  # noqa: E402
from _driver.state import StateDir  # noqa: E402
from _driver.targets import conflict, covers, file_key, normalize  # noqa: E402
from _driver.units import FACTORS, convert, duration_seconds  # noqa: E402
from _driver.writes import Engine  # noqa: E402
from sample_cli import ROOT as SAMPLE  # noqa: E402
from sample_cli import build  # noqa: E402
from sample_cli.commands import COMMANDS  # noqa: E402

CONTRACT = Contract(REPO / "contract" / "driver-contract.json")
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
MODES = ["file", "session", "device"]


def registration(**changes):
    reg = copy.deepcopy(next(c for c in COMMANDS if c["path"] == "part move"))
    reg.update(changes)
    return reg


class Units(unittest.TestCase):
    def test_every_unit_has_a_factor(self):
        for unit in CONTRACT["units"]:
            self.assertEqual(sorted(FACTORS[unit["quantity"]]), sorted(unit["accepts"]), unit["quantity"])

    def test_conversion(self):
        length = CONTRACT.units["length"]["accepts"]
        self.assertEqual(convert("100mil", "length", length, "--x"), 2.54)
        self.assertEqual(convert("1in", "length", length, "--x"), 25.4)
        self.assertEqual(convert("-5mm", "length", length, "--x"), -5.0)
        temperature = CONTRACT.units["temperature"]["accepts"]
        self.assertEqual(convert("273.15K", "temperature", temperature, "--t"), 0.0)
        self.assertEqual(convert("32degF", "temperature", temperature, "--t"), 0.0)
        self.assertEqual(convert("60rpm", "angular_speed", CONTRACT.units["angular_speed"]["accepts"], "--w"), 360.0)

    def test_bare_number_lists_the_units(self):
        with self.assertRaises(DriverError) as ctx:
            convert("12.5", "length", CONTRACT.units["length"]["accepts"], "--x")
        self.assertEqual(ctx.exception.code, "E_USAGE")
        self.assertIn("mil", ctx.exception.details["problem"])
        with self.assertRaises(DriverError):
            convert("12.5furlong", "length", CONTRACT.units["length"]["accepts"], "--x")

    def test_durations(self):
        self.assertEqual(duration_seconds("90s", "--wait", ["ms", "s", "min", "h"]), 90.0)
        self.assertEqual(duration_seconds("2min", "--wait", ["ms", "s", "min", "h"]), 120.0)
        for bad in ("60", "1m", "-1s", "s"):
            with self.assertRaises(DriverError):
                duration_seconds(bad, "--wait", ["ms", "s", "min", "h"])


class SaveReadBack(unittest.TestCase):
    def test_an_object_deleted_before_the_save_is_read_only_for_being_gone(self):
        from _driver.standard import still_there

        doc = "file:///D:/e2e/drawing.drw"
        note, leader, other = f"{doc}#/notes/SPARE", f"{doc}#/notes/SPARE/leader", f"{doc}#/notes/SPARE_2"
        fields = [{"target": note, "field": "text", "after": "SPARE"}, {"target": leader, "field": "x_mm", "after": 1.0},
                  {"target": other, "field": "text", "after": "kept"}, {"target": note, "field": "exists", "after": False}]
        self.assertEqual([(c["target"], c["field"]) for c in still_there(fields)],
                         [(other, "text"), (note, "exists")])  # SPARE_2 only shares the prefix of the name
        again = [dict(c, after=True) if c["field"] == "exists" else c for c in fields]  # created again: all are read
        self.assertEqual(still_there(again), again)


class TargetKeys(unittest.TestCase):
    def test_prefix_matches_only_at_a_boundary(self):
        self.assertTrue(covers("file:///D:/proj", "file:///D:/proj/board.kicad_pcb"))
        self.assertFalse(covers("file:///D:/proj", "file:///D:/proj2/board.kicad_pcb"))
        self.assertTrue(covers("file:///D:/proj/board.kicad_pcb", "file:///D:/proj/board.kicad_pcb#/footprints/R1"))
        self.assertTrue(covers("untitled:", "untitled:kicad-1/2#/x"))
        self.assertTrue(covers("device:cnc-01", "device:cnc-01/axis-x"))
        self.assertFalse(covers("device:cnc-0", "device:cnc-01/axis-x"))
        self.assertTrue(conflict("file:///D:/proj/b.pcb#/R1", "file:///D:/proj/b.pcb"))
        self.assertFalse(conflict("file:///D:/proj/b.pcb#/R1", "file:///D:/proj/b.pcb#/R2"))

    def test_normalization(self):
        self.assertEqual(normalize("file:///D:/proj/./sub/../board.pcb"), normalize("file:///D:/proj/board.pcb"))
        if sys.platform == "win32":
            self.assertTrue(covers("file:///d:/PROJ/", "file:///D:/proj/board.pcb"))
            self.assertTrue(file_key("C:\\x\\y.txt").startswith("file:///C:/x/"))
        else:
            self.assertEqual(file_key("/tmp/a.txt"), "file:///tmp/a.txt")


class Scope(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "scope.json"

    def write(self, **data):
        base = {"scope_id": "s", "effects": ["change"], "dangerous": False, "targets": ["file:///D:/proj/"],
                "expires_at": "2099-01-01T00:00:00Z"}
        base.update(data)
        self.path.write_text(json.dumps({k: v for k, v in base.items() if v is not None}), encoding="utf-8")
        return load_scope(self.path, CONTRACT)

    def test_statuses(self):
        self.assertEqual(load_scope(self.path, CONTRACT).status, "missing")
        self.assertEqual(self.write().status, "granted")
        self.assertEqual(self.write(expires_at="2020-01-01T00:00:00Z").status, "expired")
        for bad in ({"effects": ["observe"]}, {"effects": []}, {"targets": ["D:/proj"]}, {"dangerous": "no"},
                    {"expires_at": "2099-01-01"}, {"confirm": "never"}, {"extra": 1}, {"scope_id": None}):
            self.assertEqual(self.write(**bad).status, "invalid", bad)
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(load_scope(self.path, CONTRACT).status, "invalid")

    def test_coverage(self):
        scope = self.write()
        self.assertIsNone(scope.missing(["change"], False, ["file:///D:/proj/b.pcb#/R1"]))
        missing = scope.missing(["change", "persist"], True, ["file:///D:/other/b.pcb"])
        self.assertEqual(missing["missing"], {"effects": ["persist"], "targets": ["file:///D:/other/b.pcb"], "dangerous": True})
        snippet = dict(missing["snippet"])  # a scope file that grants just this write (DSEC-015)
        self.assertTrue(snippet.pop("expires_at").endswith("Z"))
        self.assertEqual(snippet, {"scope_id": "grant", "effects": ["change", "persist"], "targets": ["file:///D:/other/b.pcb"],
                                   "dangerous": True})
        # A halt command needs only its targets (DSEC-018).
        self.assertIsNone(scope.missing(["lifecycle"], False, ["file:///D:/proj/b.pcb"], halt=True))
        self.assertIsNotNone(scope.missing(["lifecycle"], False, ["device:x"], halt=True))

    def test_missing_scope_lists_everything(self):
        missing = load_scope(self.path, CONTRACT).missing(["change"], False, ["file:///D:/a"])
        self.assertEqual(missing["missing"]["effects"], ["change"])
        self.assertEqual(missing["missing"]["targets"], ["file:///D:/a"])


class Derivation(unittest.TestCase):
    def derive(self, cause=None, **outcome):
        engine = Engine.__new__(Engine)
        engine.contract = CONTRACT
        full = {"execution": "completed", "change": "not_applicable", "delivery": "not_applicable",
                "persistence": "not_applicable", "verification": "not_applicable"}
        full.update(outcome)
        return engine.derive({"outcome": full}, cause)

    def test_every_rule(self):
        self.assertEqual(self.derive(execution="unknown"), (False, "E_OUTCOME_UNKNOWN"))
        self.assertEqual(self.derive(execution="running"), (False, "E_OUTCOME_UNKNOWN"))
        self.assertEqual(self.derive(change="partial", verification="passed"), (False, "E_PARTIAL"))
        self.assertEqual(self.derive(execution="failed", change="applied", verification="passed"), (False, "E_PARTIAL"))
        self.assertEqual(self.derive(execution="failed", change="not_applied"), (False, "E_NATIVE_FAILURE"))
        self.assertEqual(self.derive("E_VALIDATION", execution="not_started", change="not_applied"), (False, "E_VALIDATION"))
        self.assertEqual(self.derive(change="rolled_back"), (False, "E_NATIVE_FAILURE"))
        self.assertEqual(self.derive(delivery="rejected"), (False, "E_NATIVE_FAILURE"))
        self.assertEqual(self.derive(change="applied", verification="failed"), (False, "E_VERIFY_FAILED"))
        self.assertEqual(self.derive(change="applied", verification="incomplete"), (False, "E_VERIFY_INCOMPLETE"))
        self.assertEqual(self.derive(change="applied", verification="not_run"), (False, "E_VERIFY_INCOMPLETE"))
        self.assertEqual(self.derive(persistence="saved", verification="not_run"), (False, "E_VERIFY_INCOMPLETE"))
        self.assertEqual(self.derive(change="applied", verification="passed"), (True, None))


class Registration(unittest.TestCase):
    def assertRejected(self, reg, words):
        with self.assertRaises(RegistrationError) as ctx:
            domain_command(reg, CONTRACT, MODES)
        self.assertIn(words, str(ctx.exception))

    def test_physical_parameter_needs_its_quantity(self):
        flag = {"name": "--x", "type": "quantity"}
        self.assertRejected(registration(flags=[flag]), "quantity")
        self.assertRejected(registration(flags=[{"name": "--width-mm", "type": "number"}]), "quantity")
        self.assertRejected(registration(flags=[{"name": "--x", "type": "number", "quantity": "length"}]), "quantity")
        self.assertRejected(registration(flags=[{"name": "--x", "type": "quantity", "quantity": "lightyears"}]), "DCLI-080")

    def test_command_shape(self):
        self.assertRejected(registration(path="move"), "DCLI-020")
        self.assertRejected(registration(path="part show"), "DCLI-022")
        self.assertRejected(registration(path="session move"), "DCLI-024")
        self.assertRejected(registration(path="part get"), "observe")
        self.assertRejected(registration(path="part stop"), "DSEC-018")
        self.assertRejected(registration(halt=True), "DSEC-018")
        self.assertRejected(registration(adapter_capabilities=["read"]), "unknown")
        self.assertRejected(registration(survey_ids=["CAP-001"]), "unknown")
        self.assertRejected(registration(departures=[]), "unknown")
        self.assertRejected({k: v for k, v in registration().items() if k != "tolerances"}, "missing")
        self.assertRejected(registration(jobs=True, long=True), "DCLI-065")
        self.assertRejected(registration(path="part list", effects=["observe"], jobs=True), "DCLI-065")

    def test_flags(self):
        for flag, words in (({"name": "--dry-run", "type": "boolean"}, "global"), ({"name": "--version", "type": "string"}, "global"),
                            ({"name": "--session", "type": "string"}, "target flag"), ({"name": "--ids", "type": "string"}, "shared"),
                            ({"name": "--x", "type": "decimal"}, "type"), ({"name": "--out", "type": "string", "output": True}, "path")):
            self.assertRejected(registration(flags=[flag]), words)

    def test_tiers(self):
        tiers = Tiers(CONTRACT)
        move = domain_command(registration(), CONTRACT, MODES)
        self.assertEqual(tiers.per_mode(move), {"file": "two_step", "session": "direct"})
        delete = domain_command(registration(irreversible=True), CONTRACT, MODES)
        self.assertEqual(tiers.per_mode(delete), "dangerous")
        physical = domain_command(registration(path="axis move", effects=["physical"], modes=["device"]), CONTRACT, MODES)
        self.assertEqual(tiers.per_mode(physical), "dangerous")
        self.assertEqual(tiers.risk(physical), "T2")
        self.assertEqual(tiers.risk(move), "T1")

    def test_the_tool_s_document_kinds(self):
        def tool(kinds, reg=None):
            return Tool(root=SAMPLE, adapter=SampleAdapter, commands=[reg or registration()], application="Files",
                        versions="any", modes=MODES, contract=REPO / "contract" / "driver-contract.json", doc_kinds=kinds)

        parser = Parser(CONTRACT, tool(["board", "schematic"]).commands, "sample-cli")
        for argv in (["session", "open", "--kind", "board"], ["doc", "create", "--kind", "schematic", "--path", "a.fake"]):
            self.assertEqual(parser.parse(argv).values["--kind"], argv[3])
        for argv in (["session", "open", "--kind", "drawing"], ["doc", "create", "--kind", "drawing", "--path", "a.fake"]):
            with self.assertRaises(DriverError) as ctx:
                parser.parse(argv)  # refused before any job or dispatch starts
            self.assertEqual(ctx.exception.code, "E_USAGE")
            self.assertIn("board, schematic", ctx.exception.message)
        # A tool that lists no kinds leaves the kind to its adapter.
        self.assertEqual(Parser(CONTRACT, tool(None).commands, "sample-cli").parse(["session", "open", "--kind", "drawing"])
                         .values["--kind"], "drawing")
        with self.assertRaises(RegistrationError) as ctx:
            tool(["board"], registration(doc_kinds=["schematic"]))
        self.assertIn("not among the tool's doc_kinds", str(ctx.exception))
        with self.assertRaises(RegistrationError):
            tool(["Board"])

    def test_the_sample_registration_is_current(self):
        written = json.loads((SAMPLE / "contract" / "commands.json").read_text(encoding="utf-8"))
        self.assertEqual(written, build().registration())


class Parsing(unittest.TestCase):
    def setUp(self):
        self.tool = build()
        self.parser = Parser(CONTRACT, self.tool.commands, "sample-cli")

    def usage(self, *argv):
        with self.assertRaises(DriverError) as ctx:
            self.parser.parse(list(argv))
        self.assertEqual(ctx.exception.code, "E_USAGE")
        return ctx.exception

    def test_mistakes_suggest_the_right_form(self):
        self.assertIn("part move", self.usage("part", "mvoe").details["next_action"])
        self.assertIn("--x", self.usage("part", "move", "--xx", "1mm").details["next_action"])
        self.usage("context", "extra")
        self.usage("part", "move", "--x", "1mm", "--x", "2mm")
        self.usage("context", "--format", "yaml")
        self.usage("part")

    def test_values(self):
        call = self.parser.parse(["part", "move", "--x", "-5mm", "--y=100mil", "--ids", "R1,R2,R1", "--fields", "all"])
        self.assertEqual(call.values["--x"], -5.0)
        self.assertEqual(call.values["--y"], 2.54)
        self.assertEqual(call.values["--ids"], ["R1", "R2"])
        self.assertEqual(call.fields, "all")
        self.usage("part", "move", "--ids", ",")
        self.usage("operation", "list", "--limit", "101")

    def test_quote(self):
        self.assertEqual(quote("R1"), "R1")
        self.assertEqual(quote("-5mm"), "'-5mm'")
        self.assertEqual(quote("two words"), "'two words'")
        self.assertEqual(quote("$(touch x)"), "'$(touch x)'")
        self.assertEqual(quote("it's $x"), "'it'" + '"' + "'" + '"' + "'s $x'")


class Envelope(unittest.TestCase):
    def test_a_long_list_is_shortened(self):
        envelopes = Envelopes(CONTRACT)
        items = [{"id": f"item-{i}", "text": "x" * 100} for i in range(200)]
        env = envelopes.success(Result({"items": items, "count": 200, "has_more": False}, offset=0), [])
        self.assertLessEqual(len(json.dumps(env, separators=(",", ":"))), 8000)
        self.assertTrue(env["data"]["has_more"])
        self.assertEqual(env["data"]["next_offset"], env["data"]["count"])

    def test_untrusted_paths_point_at_values(self):
        env = Envelopes(CONTRACT).success(Result({"title": "x"}, [".title", ".missing"]), [])
        self.assertEqual(env["meta"]["untrusted"], ["$.data.title"])


class StateAndLocks(unittest.TestCase):
    def setUp(self):
        self.state = StateDir(Path(tempfile.mkdtemp()) / "state")

    def test_protection_is_what_is_in_place(self):
        self.assertEqual(self.state.protection(), "none")
        self.state.ensure()
        self.assertEqual(self.state.protection(), "windows_acl" if sys.platform == "win32" else "posix_0700")

    def test_two_processes_on_one_target(self):
        records = Records(self.state, 30, "op_")
        locks = Locks(self.state, records, Mutex(self.state), "sample-cli")
        script = textwrap.dedent(f"""
            import sys, time
            sys.path.insert(0, {str(REPO / 'sdk' / 'python')!r})
            from _driver.state import StateDir
            from _driver.records import Locks, Mutex, Records
            state = StateDir({str(self.state.path)!r})
            records = Records(state, 30, "op_")
            records.save({{"operation_id": "op_child", "state": "planned", "planned_at": "2026-01-01T00:00:00Z"}})
            Locks(state, records, Mutex(state), "x").acquire("op_child", ["file:///D:/proj/b.pcb"])
            print("locked", flush=True)
            time.sleep(30)
        """)
        child = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True, creationflags=FLAGS)
        try:
            self.assertEqual(child.stdout.readline().strip(), "locked")
            with self.assertRaises(DriverError) as ctx:
                locks.acquire("op_parent", ["file:///D:/proj/b.pcb#/R1"])
            self.assertEqual(ctx.exception.details["conflict"], "target_locked")
            locks.acquire("op_other", ["file:///D:/proj/c.pcb"])  # another target is free
        finally:
            child.kill()
            child.wait()
            child.stdout.close()
        # The holder died before dispatch: its lock is stale and goes away.
        locks.acquire("op_parent", ["file:///D:/proj/b.pcb#/R1"])

    def test_a_lock_after_dispatch_outlives_its_process(self):
        records = Records(self.state, 30, "op_")
        locks = Locks(self.state, records, Mutex(self.state), "sample-cli")
        records.save({"operation_id": "op_gone", "state": "dispatched", "planned_at": "2026-01-01T00:00:00Z"})
        (self.state.sub("locks") / "op_gone.json").write_text(json.dumps(
            {"operation_id": "op_gone", "keys": ["device:d/x"], "holder": "process", "pid": 999999999}), encoding="utf-8")
        with self.assertRaises(DriverError):
            locks.acquire("op_new", ["device:d/x"])
        self.assertEqual(records.load("op_gone")["state"], "unknown")


class SampleAdapter(Adapter):
    """A tiny in-process adapter over JSON files, to test the path without the fake host."""

    def probe(self, request):
        return {"found": True, "path": "builtin", "version": "1.0.0", "license": "not_required"}

    def documents(self, request):
        path = request.get("path")
        if not path or not os.path.isfile(path):
            return {"items": []}
        if SampleAdapter.slow_documents and SampleAdapter.hang is not None:
            SampleAdapter.hang.wait(10)  # the state read after a verified write does not answer
            raise Ended()
        data = Path(path).read_bytes()
        import hashlib

        return {"items": [{"id": path, "path": path, "session": None, "revision": hashlib.sha256(data).hexdigest()[:12],
                           "dirty": False, "readonly": False, "disk": "in_sync"}]}

    def _load(self, request):
        return json.loads(Path(request["document"]).read_text(encoding="utf-8"))

    def read(self, request):
        return {"result": self._load(request).get(request["inputs"].get("id"), {})}

    def preview(self, request):
        data, inputs = self._load(request), request["inputs"]
        key = file_key(request["document"], "/" + inputs["id"])
        if inputs["id"] == "missing":
            raise AdapterError("E_NOT_FOUND", "no such part", native_message="Part 'missing' not found")
        if inputs["id"] == "locked":
            raise AdapterError("E_NATIVE_FAILURE", "the part is locked", dispatch_state="not_started",
                               knowledge=["locked-parts"])
        if inputs["id"] == "reopen":  # a read that the application's state refuses, without a dispatch state
            raise AdapterError("E_CONFLICT", "the design must be opened again to read it", conflict="application_state")
        fields = {k: v for k, v in inputs.items() if k != "id"}
        before = data.get(inputs["id"], {})
        return {"action": f"Change {inputs['id']}", "targets": [{"key": key, "kind": "part"}],
                "changes": [{"target": key, "field": k, "before": before.get(k), "after": v} for k, v in fields.items()],
                "can_apply": True}

    def apply(self, request):
        data, inputs = self._load(request), request["inputs"]
        if inputs.get("value") == "refused":
            raise AdapterError("E_NATIVE_FAILURE", "the part is locked", dispatch_state="not_started", knowledge=["locked-parts"])
        if inputs.get("value") == "dialog":
            raise AdapterError("E_HUMAN_REQUIRED", "a license dialog opened", dispatch_state="dispatched",
                               action="dismiss_dialog", knowledge=["license-dialog"])
        data.setdefault(inputs["id"], {}).update({k: v for k, v in inputs.items() if k != "id"})
        Path(request["document"]).write_text(json.dumps(data), encoding="utf-8")
        if inputs.get("value") == "slowdoc":
            SampleAdapter.slow_documents = True
        return {"dispatch_state": "dispatched", "change": "applied", "delivery": "not_applicable", "persistence": "saved"}

    def read_back(self, request):
        data, inputs = self._load(request), request["inputs"]
        if inputs.get("value") == "slow" and self.hang is not None:
            self.hang.wait(10)  # the watchdog fires meanwhile; then the process is gone
            raise Ended()
        return {"observed": {file_key(request["document"], "/" + inputs["id"]): data.get(inputs["id"], {})}}

    hang = None
    slow_documents = False


class Ended(BaseException):
    """Stands for the end of the process in a test that cannot end it."""


class BatchAdapter(SampleAdapter):
    """Several parts at once; the read-back of R2 hangs while ``hang`` is set."""

    def preview(self, request):
        data, inputs = self._load(request), request["inputs"]
        keys = [(i, file_key(request["document"], "/" + i)) for i in inputs["ids"]]
        return {"action": "Change parts", "targets": [{"key": k, "kind": "part"} for _, k in keys],
                "changes": [{"target": k, "field": "value", "before": data.get(i, {}).get("value"), "after": inputs["value"]}
                            for i, k in keys], "can_apply": True}

    def apply(self, request):
        data, inputs = self._load(request), request["inputs"]
        for i in inputs["ids"]:
            data.setdefault(i, {})["value"] = inputs["value"]
        Path(request["document"]).write_text(json.dumps(data), encoding="utf-8")
        return {"dispatch_state": "dispatched", "change": "applied", "delivery": "not_applicable", "persistence": "saved"}

    def read_back(self, request):
        data, ids = self._load(request), request["inputs"]["ids"]
        if "R2" in ids and SampleAdapter.hang is not None:
            SampleAdapter.hang.wait(10)
            raise Ended()
        return {"observed": {file_key(request["document"], "/" + i): data.get(i, {}) for i in ids}}


class LibraryAdapter(SampleAdapter):
    """Its preview names a new library file that the apply does not make."""

    def preview(self, request):
        out = super().preview(request)
        library = file_key(str(Path(request["document"]).parent / "new.lib"))
        out["targets"].append({"key": library, "kind": "file"})
        return out


class InProcess(unittest.TestCase):
    """A file-mode tool with an in-process adapter, a secret flag and no fake host."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.doc = self.tmp / "board.json"
        self.doc.write_text(json.dumps({"R1": {"value": "1k"}}), encoding="utf-8")
        reg = registration(path="part update", modes=["file"], flags=[
            {"name": "--id", "type": "string", "required": True}, {"name": "--value", "type": "string"},
            {"name": "--token", "type": "string", "secret": True}], tolerances={})
        self.tool = Tool(root=SAMPLE, adapter=SampleAdapter, commands=[reg], application="Files", versions="any",
                         modes=["file"], contract=REPO / "contract" / "driver-contract.json")
        self.env = {"SAMPLE_CLI_STATE_DIR": str(self.tmp / "state"), "SAMPLE_CLI_SCOPE_FILE": str(self.tmp / "scope.json")}
        (self.tmp / "scope.json").write_text(json.dumps({"scope_id": "t", "effects": ["change"], "dangerous": False,
                                                         "targets": [file_key(str(self.tmp)) + "/"],
                                                         "expires_at": "2099-01-01T00:00:00Z"}), encoding="utf-8")

    def run_tool(self, *argv):
        out = io.StringIO()
        code = self.tool.run(list(argv), env=self.env, stdout=out)
        return code, json.loads(out.getvalue())

    def test_two_step_write_in_file_mode(self):
        args = ["part", "update", "--doc", str(self.doc), "--id", "R1", "--value", "2k", "--token", "s3cret"]
        code, env = self.run_tool(*args)
        self.assertEqual((code, env["error"]["code"]), (5, "E_CONFIRMATION_REQUIRED"))
        self.assertNotIn("s3cret", json.dumps(env))  # a secret never comes back (DSEC-040)
        code, env = self.run_tool(*args, "--confirm", env["error"]["details"]["confirm_token"])
        self.assertEqual(code, 0, env)
        self.assertEqual(env["data"]["receipt"]["outcome"]["persistence"], "saved")
        self.assertEqual(env["data"]["receipt"]["outcome"]["verification"], "passed")
        self.assertNotIn("simulated", env["data"]["receipt"])
        records = (self.tmp / "state" / "operations")
        for path in records.glob("*.json"):
            self.assertNotIn("s3cret", path.read_text(encoding="utf-8"), "a secret reached an operation record")

    def test_reference_says_what_input_and_ids_can_replace(self):
        reg = registration(path="part update", modes=["file"], flags=[
            {"name": "--id", "type": "string", "required": True}, {"name": "--value", "type": "string", "required": True},
            {"name": "--ids", "type": "list"}, {"name": "--input", "type": "input"}], tolerances={})
        self.tool = Tool(root=SAMPLE, adapter=SampleAdapter, commands=[reg], application="Files", versions="any",
                         modes=["file"], contract=REPO / "contract" / "driver-contract.json")
        code, env = self.run_tool("reference", "--command", "part update")
        self.assertEqual(code, 0, env)
        flags = {f["name"]: f for f in env["data"]["flags"]}
        self.assertEqual((flags["--id"].get("required"), flags["--id"]["required_without"]), (None, ["--ids", "--input"]))
        self.assertEqual((flags["--value"].get("required"), flags["--value"]["required_without"]), (None, ["--input"]))
        self.assertTrue(flags["--doc"].get("required") or "required_without" not in flags["--doc"])
        code, env = self.run_tool("reference", "--command", "reference")
        for example in env["data"]["examples"]:
            self.assertEqual(self.run_tool(*shlex.split(example)[1:])[0], 0, example)  # a file-mode tool runs its own examples

    def test_a_long_index_lists_the_paths_alone(self):
        nouns = [f"thing{n:02d}" for n in range(60)]
        regs = [registration(path=f"{noun} move", modes=["file"], summary="Move one thing to a new place, keeping its links and its labels.")
                for noun in nouns]
        self.tool = Tool(root=SAMPLE, adapter=SampleAdapter, commands=regs, application="Files", versions="any",
                         modes=["file"], contract=REPO / "contract" / "driver-contract.json")
        out = io.StringIO()
        self.assertEqual(self.tool.run(["reference"], env=self.env, stdout=out), 0)
        text = out.getvalue().strip()
        data = json.loads(text)["data"]
        self.assertLessEqual(len(text), CONTRACT["envelope"]["limits"]["reference_index_chars"])
        self.assertIn("reference --command", data["summaries"])
        self.assertEqual({tuple(i) for i in data["index"]}, {("path",)})
        self.assertIn({"path": "thing59 move"}, data["index"])

    def test_adapter_errors_keep_the_native_message_untrusted(self):
        code, env = self.run_tool("part", "update", "--doc", str(self.doc), "--id", "missing", "--value", "x")
        self.assertEqual((code, env["error"]["code"]), (3, "E_NOT_FOUND"))
        self.assertIn("$.error.details.native_message", env["meta"]["untrusted"])

    def test_a_batch_item_whose_read_back_hangs_ends_the_batch_with_the_outcome_known(self):
        import threading
        from unittest import mock

        reg = registration(path="part update", modes=["file"], flags=[
            {"name": "--ids", "type": "list"}, {"name": "--value", "type": "string"}], tolerances={})
        tool = Tool(root=SAMPLE, adapter=BatchAdapter, commands=[reg], application="Files", versions="any",
                    modes=["file"], contract=REPO / "contract" / "driver-contract.json")
        args = ["part", "update", "--doc", str(self.doc), "--ids", "R1,R2,R3", "--value", "5k"]
        out = io.StringIO()
        tool.run(args, env=self.env, stdout=out)
        token = json.loads(out.getvalue())["error"]["details"]["confirm_token"]
        exits = []
        SampleAdapter.hang = threading.Event()

        def end(code):
            exits.append(code)
            SampleAdapter.hang.set()

        out = io.StringIO()
        try:
            with mock.patch("_driver.runtime.READ_DEADLINE_MS", 300), mock.patch("_driver.tool.os._exit", end):
                with self.assertRaises(Ended):
                    tool.run([*args, "--confirm", token], env=self.env, stdout=out)
        finally:
            SampleAdapter.hang = None
        env = json.loads(out.getvalue())
        self.assertEqual(env["error"]["code"], "E_PARTIAL", env)
        items = env["error"]["details"]["batch"]["items"]
        self.assertEqual([(i.get("ok"), i.get("code"), i.get("skipped")) for i in items],
                         [(True, None, None), (False, "E_VERIFY_INCOMPLETE", None), (False, None, True)])
        self.assertTrue(exits)
        # Nothing stays locked: the next write to R2 asks for confirmation.
        out = io.StringIO()
        tool.run(["part", "update", "--doc", str(self.doc), "--ids", "R2", "--value", "6k"], env=self.env, stdout=out)
        self.assertEqual(json.loads(out.getvalue())["error"]["code"], "E_CONFIRMATION_REQUIRED")

    def test_a_file_the_preview_names_is_checked(self):
        reg = registration(path="part update", modes=["file"], effects=["change", "artifact"], flags=[
            {"name": "--id", "type": "string", "required": True}, {"name": "--value", "type": "string"}], tolerances={})
        tool = Tool(root=SAMPLE, adapter=LibraryAdapter, commands=[reg], application="Files", versions="any",
                    modes=["file"], contract=REPO / "contract" / "driver-contract.json")
        scope = json.loads((self.tmp / "scope.json").read_text(encoding="utf-8"))
        (self.tmp / "scope.json").write_text(json.dumps({**scope, "effects": ["change", "artifact"]}), encoding="utf-8")
        args = ["part", "update", "--doc", str(self.doc), "--id", "R1", "--value", "2k"]
        out = io.StringIO()
        tool.run(args, env=self.env, stdout=out)
        out2 = io.StringIO()
        tool.run([*args, "--confirm", json.loads(out.getvalue())["error"]["details"]["confirm_token"]], env=self.env, stdout=out2)
        env = json.loads(out2.getvalue())
        self.assertEqual(env["error"]["code"], "E_VERIFY_FAILED", env)  # new.lib was never made
        self.assertIn("exists@" + file_key(str(self.tmp / "new.lib")), env["error"]["details"]["receipt"]["mismatched"])

    def test_a_read_after_a_verified_write_that_hangs_keeps_the_outcome(self):
        import threading
        from unittest import mock

        args = ("part", "update", "--doc", str(self.doc), "--id", "R1", "--value", "slowdoc")
        _, env = self.run_tool(*args)
        token = env["error"]["details"]["confirm_token"]
        exits = []
        SampleAdapter.hang = threading.Event()

        def end(code):
            exits.append(code)
            SampleAdapter.hang.set()

        out = io.StringIO()
        try:
            with mock.patch("_driver.tool.os._exit", end):  # the state read waits 2 s at most
                with self.assertRaises(Ended):
                    self.tool.run([*args, "--confirm", token], env=self.env, stdout=out)
        finally:
            SampleAdapter.hang, SampleAdapter.slow_documents = None, False
        env = json.loads(out.getvalue())
        self.assertEqual((exits, env["ok"]), ([0], True), env)
        self.assertEqual(env["data"]["receipt"]["outcome"]["verification"], "passed")
        _, env = self.run_tool("part", "update", "--doc", str(self.doc), "--id", "R1", "--value", "3k")
        self.assertEqual(env["error"]["code"], "E_CONFIRMATION_REQUIRED")  # not locked

    def test_a_read_may_report_a_conflict_inside_the_application(self):
        code, env = self.run_tool("part", "update", "--doc", str(self.doc), "--id", "reopen", "--value", "x")
        self.assertEqual((env["error"]["code"], env["error"]["details"].get("conflict")), ("E_CONFLICT", "application_state"), env)

    def test_a_recognized_error_points_to_knowledge(self):
        code, env = self.run_tool("part", "update", "--doc", str(self.doc), "--id", "locked", "--value", "x")
        self.assertEqual(env["error"]["code"], "E_NATIVE_FAILURE")
        self.assertEqual(env["error"]["details"]["knowledge"], ["locked-parts"])
        self.assertIn("sample-cli knowledge get --id locked-parts", env["error"]["details"]["next_action"])

    def test_write_errors_keep_the_pointer_to_knowledge(self):
        for value, code, entry in (("refused", "E_NATIVE_FAILURE", "locked-parts"), ("dialog", "E_HUMAN_REQUIRED", "license-dialog")):
            with self.subTest(value=value):
                args = ("part", "update", "--doc", str(self.doc), "--id", "R1", "--value", value)
                _, env = self.run_tool(*args)
                _, env = self.run_tool(*args, "--confirm", env["error"]["details"]["confirm_token"])
                details = env["error"]["details"]
                self.assertEqual((env["error"]["code"], details["knowledge"]), (code, [entry]))
                self.assertIn(f"sample-cli knowledge get --id {entry}", details["next_action"])

    def test_a_read_back_that_hangs_leaves_the_outcome_known(self):
        import threading
        from unittest import mock

        args = ("part", "update", "--doc", str(self.doc), "--id", "R1", "--value", "slow")
        _, env = self.run_tool(*args)
        token = env["error"]["details"]["confirm_token"]
        exits = []
        SampleAdapter.hang = threading.Event()

        def end(code):
            exits.append(code)
            SampleAdapter.hang.set()

        out = io.StringIO()
        try:
            with mock.patch("_driver.runtime.READ_DEADLINE_MS", 300), mock.patch("_driver.tool.os._exit", end):
                with self.assertRaises(Ended):
                    self.tool.run([*args, "--confirm", token], env=self.env, stdout=out)
        finally:
            SampleAdapter.hang = None
        env = json.loads(out.getvalue())
        self.assertEqual((exits, env["error"]["code"]), ([1], "E_VERIFY_INCOMPLETE"))
        outcome = env["error"]["details"]["receipt"]["outcome"]
        self.assertEqual((outcome["change"], outcome["verification"]), ("applied", "incomplete"))
        self.assertIn("read_back", env["error"]["details"]["receipt"]["notes"][0])
        # The outcome is known, so the target is not locked: the next write goes through.
        _, env = self.run_tool("part", "update", "--doc", str(self.doc), "--id", "R1", "--value", "3k")
        self.assertEqual(env["error"]["code"], "E_CONFIRMATION_REQUIRED")

    def test_missing_capability_is_unsupported(self):
        code, env = self.run_tool("session", "list")
        self.assertEqual(code, 2)  # a file-mode tool has no session commands
        code, env = self.run_tool("job", "get", "--job", "1")
        self.assertEqual(env["error"]["code"], "E_NOT_FOUND")

    def test_version_help_and_changelog(self):
        code, env = self.run_tool("--version")
        self.assertEqual(env["data"]["version"], "0.1.0")
        code, env = self.run_tool("part", "update", "--help")
        self.assertIn("--value", env["data"]["usage"])
        code, env = self.run_tool("changelog", "--since", "0.0.1")
        self.assertEqual([e["version"] for e in env["data"]["entries"]], ["0.1.0"])
        self.assertEqual(env["data"]["entries"][0]["changes"]["added"][0][:10], "The sample")


class FolderOutputs(unittest.TestCase):
    """An output flag that names a folder the command writes its files into (DCLI-051)."""

    def test_a_folder_with_files_is_made_and_its_files_are_checked(self):
        from _driver.writes import made, verify_files

        tmp = Path(tempfile.mkdtemp(prefix="fab-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        folder = tmp / "fab"
        named = [{"target": file_key(str(folder)), "field": "exists"}]
        self.assertFalse(made(str(folder)))  # not there yet: the export is direct
        folder.mkdir()
        self.assertFalse(made(str(folder)))  # an empty folder holds nothing to overwrite
        self.assertEqual(verify_files({}, named).status, "failed")  # nothing was written into it
        (folder / "top.gbr").write_text("G04*", encoding="utf-8")
        self.assertTrue(made(str(folder)))
        result = verify_files({"files": [{"path": str(folder / "top.gbr")}]}, named)
        self.assertEqual(result.status, "passed", result.mismatched)
        self.assertTrue(result.observed[file_key(str(folder))]["folder"])
        self.assertEqual(result.observed[file_key(str(folder / "top.gbr"))]["bytes"], 4)
        missing = verify_files({"files": [{"path": str(folder / "bottom.gbr")}]}, named)
        self.assertEqual(missing.mismatched, ["exists@" + file_key(str(folder / "bottom.gbr"))])


class RenamedFilesAndLongResults(unittest.TestCase):
    """A file the application writes under another name (DCLI-057), and what a result too long can ask for (DCLI-008)."""

    def test_a_file_written_under_another_name_counts_for_the_given_path(self):
        from _driver.writes import verify_files

        tmp = Path(tempfile.mkdtemp(prefix="numbered-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        asked, written = tmp / "cover.prt", tmp / "cover.prt.2"
        written.write_text("x", encoding="utf-8")
        named = [{"target": file_key(str(asked)), "field": "exists"}]
        self.assertEqual(verify_files({"files": [{"path": str(written)}]}, named).status, "failed")  # cover.prt is not there
        result = verify_files({"files": [{"path": str(written), "requested_path": str(asked)}]}, named)
        self.assertEqual(result.status, "passed", result.mismatched)
        self.assertEqual(result.observed[file_key(str(written))]["bytes"], 1)
        lost = tmp / "cover.prt.3"
        missing = verify_files({"files": [{"path": str(lost), "requested_path": str(asked)}]}, named)
        self.assertEqual(missing.mismatched, ["exists@" + file_key(str(lost))])
        if os.name == "nt":  # the application may write the given path in another case or with other separators
            other = str(asked).upper().replace("\\", "/")
            self.assertEqual(verify_files({"files": [{"path": str(written), "requested_path": other}]}, named).status, "passed")
        odd = verify_files({"files": [{"path": str(written), "requested_path": ["not", "a", "path"]}]}, named)
        self.assertEqual(odd.status, "failed")  # an odd value counts for nothing and breaks nothing

    def test_a_result_too_long_names_only_what_the_command_offers(self):
        from _driver.tool import too_long_hint

        tool = build()
        job = too_long_hint("demo", tool.commands["job get"], {"id": "7", "operation_id": "op_1", "state": "completed"})
        self.assertNotIn("--limit", job)
        self.assertIn("--fields", job)
        self.assertIn("the full result in a file with --output", job)  # job get --output writes the whole job
        listing = too_long_hint("demo", tool.commands["job list"], {"items": []})
        self.assertEqual(listing, "Ask for fewer fields with --fields or a smaller page with --limit.")
        record = too_long_hint("demo", tool.commands["operation get"], {"operation_id": "op_1"})
        self.assertEqual(record, "Ask for fewer fields with --fields or the full result in a file with --output.")
        ran = too_long_hint("demo", tool.commands["part move"], {"operation_id": "op_2", "receipt": {}, "result": {}})
        self.assertIn("ran as operation op_2; do not send it again", ran)  # the write is done: never twice
        self.assertNotIn("--fields", ran)  # --fields does not apply to writes
        self.assertIn("fewer objects", too_long_hint("demo", tool.commands["part move"], {"preview": {}}))  # a dry run
        batch = too_long_hint("demo", tool.commands["part move"], {"operation_id": "op_3", "items": [], "summary": {}})
        self.assertIn("demo operation list --batch op_3", batch)
        self.assertNotIn("--dry-run", too_long_hint("demo", tool.commands["doc save-as"], {"preview": {}}))  # never drop it
        changes = [{"target": f"file:///D:/b.fake#/R{i}", "field": "x_mm", "before": 1, "after": "x" * 200} for i in range(60)]
        env = Envelopes(tool.contract).success(Result({"preview": {"action": "Move.", "changes": changes}}), [], "unused")
        self.assertTrue(env["data"]["preview"]["changes_truncated"])  # a dry run's preview is shortened first
        self.assertLess(len(env["data"]["preview"]["changes"]), 60)
        with self.assertRaises(DriverError) as caught:
            Envelopes(tool.contract).success(Result({"text": "x" * 9000}), [], listing)
        self.assertEqual(caught.exception.code, "E_USAGE")
        self.assertEqual(caught.exception.details["next_action"], listing)

    def test_a_listed_target_may_not_cover_a_drive_or_the_home_folder(self):
        sys.path.insert(0, str(REPO / "scripts"))
        import check_project

        home = Path.home().resolve()
        self.assertIsNotNone(check_project.unfit_target(file_key(str(home)) + "/"))
        self.assertIsNotNone(check_project.unfit_target(file_key(str(home.parent)) + "/"))
        self.assertIsNotNone(check_project.unfit_target(file_key(home.anchor) if os.name == "nt" else "file:///"))
        self.assertIsNotNone(check_project.unfit_target("untitled:"))
        self.assertIsNone(check_project.unfit_target(file_key(str(home / "e2e" / "demo")) + "/"))
        self.assertIsNone(check_project.unfit_target("device:cnc-01"))


class UpdateNotice(unittest.TestCase):
    def test_once_a_day_from_the_cache(self):
        tool = build()
        tmp = Path(tempfile.mkdtemp())
        cache = tmp / "state" / "cache"
        cache.mkdir(parents=True)
        (cache / "update.json").write_text(json.dumps({"latest": "1.0.0", "deprecated": False}), encoding="utf-8")
        env = {"SAMPLE_CLI_STATE_DIR": str(tmp / "state")}
        out = io.StringIO()
        tool.run(["context"], env=env, stdout=out)
        notices = [n for n in json.loads(out.getvalue()).get("meta", {}).get("notices", []) if n["type"] == "update_available"]
        self.assertEqual([n["severity"] for n in notices], ["warning"])
        out = io.StringIO()
        tool.run(["context"], env=env, stdout=out)
        notices = json.loads(out.getvalue()).get("meta", {}).get("notices", [])
        self.assertFalse([n for n in notices if n["type"] == "update_available"])
        stale = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ")
        (cache / "update.json").write_text(json.dumps({"latest": "0.1.1", "notified_at": stale}), encoding="utf-8")
        out = io.StringIO()
        tool.run(["context"], env=env, stdout=out)
        notices = json.loads(out.getvalue())["meta"]["notices"]
        self.assertEqual([n["severity"] for n in notices if n["type"] == "update_available"], ["info"])


if __name__ == "__main__":
    unittest.main()


