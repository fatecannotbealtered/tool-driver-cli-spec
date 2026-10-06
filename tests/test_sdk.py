"""The Python SDK runtime at its call boundary, with a small text-file adapter and isolated state."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))
sys.path.insert(0, str(ROOT / "scripts"))
from generate_product import build_contract  # noqa: E402
from tool_driver_sdk import ContractValidator, DriverCLI, DriverError, StateStore  # noqa: E402
from tool_driver_sdk.scope import Scope, file_path_of  # noqa: E402
from tool_driver_sdk.store import target_key  # noqa: E402

VALIDATOR = ContractValidator(ROOT)
ENV = {"application": "text files", "application_version": "1", "platform": "any", "arch": "any", "adapter_version": "1.2.0",
       "mode": "file", "limitations": []}
WRITE_ERRORS = ["E_USAGE", "E_VALIDATION", "E_FORBIDDEN", "E_CONFIRMATION_REQUIRED", "E_CONFLICT", "E_BUSY", "E_NATIVE_FAILURE",
                "E_PARTIAL", "E_OUTCOME_UNKNOWN", "E_VERIFY_FAILED", "E_VERIFY_INCOMPLETE", "E_HUMAN_REQUIRED"]


def command(path, ctype, effects, phases, params, output, examples, dangerous=None, profiles=("core",), errors=None):
    value = {"path": path, "type": ctype, "description": f"{path} for tests", "params": params, "output_schema": output,
             "examples": examples,
             "driver": {"capability_id": path.replace(" ", "-"), "effects": effects, "phases": phases, "modes": ["file"],
                        "maturity": "draft", "environments": [ENV], "limits": [],
                        "recovery": {"atomicity": "whole", "undo": False, "idempotent": False, "cancel": False},
                        "profiles": list(profiles),
                        "error_codes": errors or (WRITE_ERRORS if ctype == "write" else ["E_USAGE", "E_VALIDATION", "E_FORBIDDEN", "E_HUMAN_REQUIRED"]),
                        "evidence_refs": []}}
    if dangerous is not None:
        value["dangerous"] = dangerous
    return value


def param(name, kind="string", required=True, multiple=False, **extra):
    return {"name": name, "type": kind, "required": required, "multiple": multiple, **extra}


def pair(path, args, dangerous=False):
    suffix = " --dangerous" if dangerous else ""
    return [f"text-driver {path} {args} --dry-run{suffix}", f"text-driver {path} {args} --confirm <confirm_token>{suffix}"]


REGISTRY = {
    "registry_version": "2.0", "name": "text-driver", "product_version": "1.2.0", "description": "Text files for SDK tests.",
    "risk_tier": "T1", "changelog": "CHANGELOG.md",
    "record": {"store": "SQLite file in the test state directory", "retain_days": 30, "survives_cli_exit": True,
               "survives_reconnect": True, "survives_instance_restart": True, "limitations": ["Test record."]},
    "schemas": {
        "doc_view": {"shape": "object", "fields": ["path", "text", "words", "snapshot"], "untrusted_fields": ["text"]},
        "doc_page": {"shape": "object", "fields": ["items", "count"], "untrusted_fields": ["items"]},
        "receipt": {"shape": "object", "fields": ["receipt", "preview", "confirm_token", "expires_at"], "untrusted_fields": [],
                    "json_schema": {"$ref": "urn:tool-driver-cli-spec:receipt:2.0"}},
        "status": {"shape": "object", "fields": ["operation_status", "preview", "confirm_token", "expires_at"], "untrusted_fields": []},
        "stamp_batch": {"shape": "object", "fields": ["items", "summary", "preview", "confirm_token", "expires_at"], "untrusted_fields": []},
        "update_result": {"shape": "object", "fields": ["status", "current_version", "target_version", "update_available"],
                          "untrusted_fields": []},
    },
    "commands": [
        command("doc show", "read", ["observe"], ["observe"], [param("path", "path"), param("tags", multiple=True, required=False),
                                                              param("limit", "integer", required=False, default=10),
                                                              param("mode", required=False, enum=["plain", "words"]),
                                                              param("meta", "json", required=False)],
                "doc_view", ["text-driver doc show --path <file> --compact"]),
        command("doc export", "write", ["artifact"], ["plan", "apply"], [param("path", "path"), param("output", "path")], "receipt",
                pair("doc export", "--path <file> --output <new file>")),
        command("doc edit", "write", ["change", "persist"], ["plan", "apply"],
                [param("path", "path"), param("text"), param("meta", "json", required=False), param("force", "boolean", required=False)],
                "receipt", pair("doc edit", "--path <file> --text x")),
        command("doc publish", "write", ["deliver"], ["plan", "apply"], [param("path", "path"), param("share")], "receipt",
                pair("doc publish", "--path <file> --share s", dangerous=True), dangerous=True),
        command("doc render", "write", ["change"], ["plan", "submit", "status", "result"], [param("path", "path")], "status",
                pair("doc render", "--path <file>"), profiles=("core", "operation_status")),
        command("doc stamp", "write", ["change", "persist"], ["plan", "apply"],
                [param("paths", "path", multiple=True), param("continue-on-error", "boolean", required=False, default=True)],
                "stamp_batch", pair("doc stamp", "--paths <file> --paths <file>"), profiles=("core", "batch")),
        command("update", "write", ["observe"], ["apply"], [param("check", "boolean", required=False, default=False)], "update_result",
                ["text-driver update --check --compact", "text-driver update --compact"], errors=["E_USAGE", "E_NETWORK", "E_INTEGRITY"]),
    ],
}
CHANGELOG = "# Changelog\n\n## [Unreleased]\n\n## [1.2.0] - 2026-10-04\n\n### Added\n\n- doc render\n\n## [1.1.0] - 2026-09-01\n\n### Fixed\n\n- doc edit reads back\n"


def now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def target(path: Path) -> dict:
    return {"mode": "file", "engine_id": "text", "instance_id": None, "object_id": path.name, "locator": path.resolve().as_uri()}


def snapshot(path: Path, sid: str) -> dict:
    return {"id": sid, "source": "disk", "revision": digest(path), "observed_at": now_iso(), "dependencies": []}


def verification(status="passed", sid="after"):
    return {"status": status, "scope": "text read back from disk", "snapshot_id": sid, "coverage": "complete",
            "checks": [{"id": "readback", "status": status if status in ("passed", "failed") else "passed", "required": True,
                        "evidence_ref": "readback"}],
            "not_checked": [], "evidence_refs": ["readback"]}


def path_of(locator: str) -> Path:
    return Path(file_path_of(locator))


class TextAdapter:
    def __init__(self):
        self.mode = "normal"
        self.applied = 0
        self.submitted = {}
        self.status_mode = "normal"
        self.lease_seen = None
        self.state_dir = None
        self.revision_calls = 0
        self.failing_revisions = set()

    def environment(self):
        if self.mode == "broken-hooks":
            raise RuntimeError("environment probe crashed")
        return {"components": [{"name": "text-adapter", "role": "adapter", "version": "1.2.0", "build_id": "test", "location": "disk",
                                "identity_status": "observed"}],
                "connection": {"status": "not_connected", "instance_id": None, "generation": None, "ownership": None, "reason": "file mode"}}

    def doctor_checks(self):
        if self.mode == "broken-hooks":
            return [{"check": "native_backend", "status": "maybe"}]
        return [{"check": "native_backend", "status": "pass", "fix": None}]

    def revision(self, value):
        self.revision_calls += 1
        if self.revision_calls in self.failing_revisions:
            raise DriverError("E_BACKEND_UNAVAILABLE", "The application stopped answering.")
        path = path_of(value["locator"])
        return digest(path) if path.exists() else None

    def update(self, call):
        return {"status": "up_to_date", "current_version": "1.2.0", "target_version": "1.2.0", "update_available": False,
                "dry_run": call.dry_run}

    def run(self, call):
        if self.mode == "not-a-dict":
            return ["not", "a", "dict"]
        path = Path(call.params["path"])
        if not path.exists():
            raise DriverError("E_NOT_FOUND", "No such document.", details={"parameter": "--path", "next_action": "Pass an existing file."})
        text = path.read_text(encoding="utf-8")
        return {"path": str(path), "text": text, "words": len(text.split()), "snapshot": snapshot(path, "read")}

    def plan(self, call):
        if self.mode == "human-plan":
            raise DriverError("E_HUMAN_REQUIRED", "A licence window is open.",
                              details={"action": "licence", "resume": "text-driver doctor", "blocked_by": "Licence expired",
                                       "next_action": "Ask the user to renew the licence.", "_untrusted": ["blocked_by"]})
        if self.mode == "interrupt-plan":
            raise KeyboardInterrupt
        if call.command == "doc stamp":
            items = []
            for raw in call.params["paths"]:
                path = Path(raw)
                items.append({"key": path.name, "target": target(path), "base_snapshot": snapshot(path, "before-" + path.stem),
                              "changes": [{"action": "append", "resource": "text", "summary": "append a stamp"}],
                              "outputs": [{"path": str(path), "effect": "persist", "exists": True}],
                              "can_apply": not (self.mode == "batch-unknown" and "READONLY" in path.read_text(encoding="utf-8"))})
            if self.mode == "batch-unknown":
                return {"items": items, "level": "plan", "unknowns": ["A read-only file cannot be stamped."]}
            return {"items": items, "level": "plan"}
        path = Path(call.params["path"])
        if call.command == "doc export":
            outputs = [{"path": call.params["output"], "effect": "artifact", "exists": Path(call.params["output"]).exists()}]
        elif call.command == "doc publish":
            outputs = [{"path": f"share://{call.params['share']}/{path.name}", "effect": "deliver", "exists": False}]
        elif "persist" in call.effects:
            outputs = [{"path": str(path), "effect": "persist", "exists": True}]
        else:
            outputs = []
        return {"target": target(path), "base_snapshot": snapshot(path, "before"), "level": "plan",
                "changes": [{"action": "set", "resource": "text", "summary": "replace the text"}], "outputs": outputs}

    def apply(self, call, plan):
        path = path_of(plan["target"]["locator"])
        if self.mode == "busy":
            raise DriverError("E_BUSY", "The editor is busy.", dispatch_state="not_started")
        if self.mode == "interrupt-apply":
            raise KeyboardInterrupt
        if self.mode == "crash-before-write":
            raise ConnectionResetError("reply lost before anything was written")
        if self.mode == "hang":
            time.sleep(120)
        if self.mode == "bare-error":
            path.write_text("half written", encoding="utf-8")
            raise DriverError("E_NATIVE_FAILURE", "Read-back failed after the write.")
        if self.mode == "lost-with-hints":
            raise DriverError("E_TIMEOUT", "No reply.", dispatch_state="dispatched",
                              details={"next_action": "just retry", "lookup": "some other command", "native_code": 42})
        if self.mode == "slow":
            time.sleep(1.0)
            with _Probe(self.state_dir) as probe:
                self.lease_seen = (probe.lease(call.operation_id), time.time())
        self.applied += 1
        if call.command == "doc stamp":
            if "LOCKED" in path.read_text(encoding="utf-8"):
                raise DriverError("E_NATIVE_FAILURE", "The file is locked.", dispatch_state="not_started")
            path.write_text(path.read_text(encoding="utf-8") + " [stamped]", encoding="utf-8")
            return {"snapshot_after": snapshot(path, "after"),
                    "outcome": {"execution": "completed", "change": "applied", "persistence": "saved", "delivery": "not_applicable",
                                "verification": verification()},
                    "changed_items": [{"id": "text", "change": "stamped", "evidence_ref": "readback"}],
                    "recovery": {"action": "none", "reason": "read back from disk", "supported": True}}
        if call.command == "doc publish":
            return {"snapshot_after": plan["base_snapshot"],
                    "outcome": {"execution": "completed", "change": "not_applied", "persistence": "unchanged", "delivery": "delivered",
                                "verification": verification(sid="before")},
                    "deliveries": [{"destination": "share://" + call.params["share"], "artifact_id": None, "status": "delivered",
                                    "evidence_ref": "listing"}],
                    "recovery": {"action": "none", "reason": "listed by the share", "supported": True}}
        if call.command == "doc export":
            output = Path(call.params["output"])
            output.write_text(path.read_text(encoding="utf-8").upper(), encoding="utf-8")
            return {"snapshot_after": plan["base_snapshot"],
                    "outcome": {"execution": "completed", "change": "not_applied", "persistence": "unchanged", "delivery": "not_applicable",
                                "verification": verification(sid="before")},
                    "artifacts": [{"id": "export-1", "path": str(output), "sha256": digest(output)[7:], "source_snapshot_id": "before"}],
                    "recovery": {"action": "none", "reason": "export read back", "supported": True}}
        path.write_text(call.params["text"], encoding="utf-8")
        if self.mode == "crash":
            raise ConnectionResetError("reply lost after the write")
        outcome = {"execution": "completed", "change": "applied", "persistence": "saved", "delivery": "not_applicable",
                   "verification": verification()}
        failed_stage = None
        if self.mode == "partial":
            outcome.update(execution="failed", persistence="unchanged")
            failed_stage = "persist"
        if self.mode == "verify-fail":
            outcome["verification"] = verification("failed")
            failed_stage = "verify"
        receipt = {"snapshot_after": snapshot(path, "after"), "outcome": outcome, "failed_stage": failed_stage,
                   "changed_items": [{"id": "text", "change": "replaced", "evidence_ref": "readback"}],
                   "recovery": {"action": "none" if self.mode == "normal" else "inspect", "reason": "read back from disk", "supported": True}}
        if self.mode == "invalid":
            receipt["outcome"]["execution"] = "done"
        return receipt

    def submit(self, call, plan):
        self.submitted[call.operation_id] = path_of(plan["target"]["locator"])
        if self.mode == "submit-queued":
            return {"status": "queued"}
        return {"status": "pending", "stage": "queued"}

    def status(self, record):
        if self.status_mode == "raise":
            raise ConnectionError("status endpoint down")
        if self.status_mode == "garbage":
            return {"status": "finished-ish"}
        path = self.submitted[record["operation_id"]]
        return {"status": "succeeded", "stage": "finished",
                "receipt": {"snapshot_after": snapshot(path, "after"),
                            "outcome": {"execution": "completed", "change": "applied", "persistence": "unsaved", "delivery": "not_applicable",
                                        "verification": verification()},
                            "recovery": {"action": "none", "reason": "rendered", "supported": True}}}


class _Probe:
    """Reads the lease of an operation through its own connection, as another process would."""

    def __init__(self, state_dir):
        self.store = StateStore(state_dir)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.store.close()

    def lease(self, operation_id):
        return self.store.get(operation_id)["lease_until"]


class SDKTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="sdk-contract-")
        base = Path(cls.temporary.name).resolve()
        (base / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
        cls.contract = build_contract(REGISTRY, registry_dir=base)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sdk-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "work"
        self.root.mkdir()
        self.out = self.base / "out"
        self.out.mkdir()
        self.doc = self.root / "doc.txt"
        self.doc.write_text("hello world", encoding="utf-8")
        self.adapter = TextAdapter()
        self.adapter.state_dir = self.base / "state"
        self.clock = [datetime.now(timezone.utc)]
        self.environ = {"TEXT_DRIVER_STATE_DIR": str(self.base / "state")}
        self.cli = self.make_cli()

    def make_cli(self, **options):
        options.setdefault("now", lambda: self.clock[0])
        cli = DriverCLI(self.contract, self.adapter, validator=VALIDATOR, environ=self.environ, home=self.base / "home", **options)
        self.addCleanup(cli.close)
        return cli

    def grant(self, **changes):
        scope = {"scope_id": "scope-1", "tool": "text-driver", "granted_by": "tests", "granted_at": "2026-01-01T00:00:00Z",
                 "expires_at": None, "effects": ["observe", "change", "persist", "artifact"], "dangerous": False,
                 "roots": [str(self.root)], "outputs": [str(self.out)]}
        scope.update(changes)
        folder = self.base / "home" / ".text-driver"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "scope.json").write_text(json.dumps(scope), encoding="utf-8")
        return scope

    def call(self, *argv, code=0, cli=None):
        result = (cli or self.cli).run(list(argv))
        self.assertFalse(result.stdout.startswith(b"\xef\xbb\xbf"))
        envelope = result.envelope
        if envelope is not None:
            self.assertEqual(json.loads(result.stdout.decode("utf-8")), envelope)
            VALIDATOR.validate("response", envelope)
            if not envelope["ok"]:
                self.assertIn("next_action", envelope["error"]["details"])
                self.assertIn("dispatch_state", envelope["error"]["details"])
        self.assertEqual(result.exit_code, code, result.stdout.decode("utf-8")[:2000])
        return envelope

    def edit(self, text="new text", *extra, code=0, path=None):
        return self.call("doc", "edit", "--path", str(path or self.doc), "--text", text, *extra, code=code)

    def plan(self, text="new text", *extra, path=None):
        return self.edit(text, "--dry-run", *extra, path=path)["data"]

    def show(self, operation_id):
        return self.call("operation", "show", "--id", operation_id)["data"]["operation_status"]

    def store(self) -> StateStore:
        return self.cli._store_open()

    # ---------------------------------------------------------------- discovery

    def test_version_and_reference_views(self):
        self.assertEqual(self.call("--version")["data"]["version"], "1.2.0")
        full = self.call("reference")["data"]
        VALIDATOR.validate("reference", full)
        index = self.call("reference", "--index")["data"]
        VALIDATOR.validate("reference-index", index)
        self.assertEqual(len(index["commands"]), len(full["commands"]))
        detail = self.call("reference", "--command", "doc edit")["data"]
        VALIDATOR.validate("reference-command", detail)
        self.assertEqual(detail["command"]["path"], "doc edit")
        self.assertEqual(detail["json_schemas"], {})
        self.assertIn("urn:tool-driver-cli-spec:receipt:2.0", detail["public_schemas"])
        self.assertLess(len(json.dumps(detail)), 6000)
        problem = self.call("reference", "--command", "doc nope", code=2)["error"]["details"]
        self.assertEqual(problem["problem"], "unknown_capability")
        self.call("reference", "--index", "--command", "doc edit", code=2)
        states = next(c for c in full["commands"] if c["path"] == "operation list")["params"][0]["enum"]
        self.assertEqual(states, ["planned", "pending", "running", "cancel_requested", "succeeded", "partial", "failed", "cancelled", "unknown"])

    def test_help_is_text_for_people(self):
        result = self.cli.run(["--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn(b"reference --index", result.stdout)
        detail = self.cli.run(["doc", "export", "--help"]).stdout.decode("utf-8")
        self.assertIn("--dry-run", detail)

    def test_context_and_doctor_follow_the_scope(self):
        context = self.call("context")["data"]
        VALIDATOR.validate("context", context)
        self.assertEqual(context["authorization"]["status"], "read_only")
        self.assertEqual(context["environment"]["components"][0]["role"], "cli")
        doctor = self.call("doctor")["data"]
        VALIDATOR.validate("doctor", doctor)
        checks = {check["check"]: check["status"] for check in doctor["checks"]}
        self.assertEqual(checks["authorization"], "warn")
        self.grant(destinations=["share://release/"])
        authorization = self.call("context")["data"]["authorization"]
        self.assertEqual((authorization["status"], authorization["destinations"]), ("granted", ["share://release/"]))
        self.grant(expires_at="2026-01-02T00:00:00Z")
        context = self.call("context")["data"]
        self.assertEqual(context["authorization"]["status"], "expired")
        self.assertEqual(context["authorization"]["effects"], ["observe"])
        checks = {check["check"]: check["status"] for check in self.call("doctor")["data"]["checks"]}
        self.assertEqual(checks["authorization"], "fail")

    def test_scope_file_states(self):
        self.grant(revoked=True)
        self.assertEqual(self.call("context")["data"]["authorization"]["status"], "revoked")
        self.grant(tool="other-tool")
        self.assertEqual(self.call("context")["data"]["authorization"]["status"], "invalid")
        (self.base / "home" / ".text-driver" / "scope.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(self.call("context")["data"]["authorization"]["status"], "invalid")
        self.environ["TEXT_DRIVER_SCOPE_FILE"] = str(self.base / "missing.json")
        authorization = self.call("context")["data"]["authorization"]
        self.assertEqual((authorization["status"], authorization["source"]["kind"]), ("invalid", "env_file"))

    def test_scope_without_time_zone_or_with_relative_roots_is_invalid(self):
        self.grant(expires_at="2099-01-01T00:00:00")
        self.assertEqual(self.call("context")["data"]["authorization"]["status"], "invalid")
        self.grant(roots=["work"])
        authorization = self.call("context")["data"]["authorization"]
        self.assertEqual(authorization["status"], "invalid")
        self.assertIn("absolute", authorization["reason"])
        self.assertEqual(self.edit("x", "--dry-run", code=4)["error"]["code"], "E_FORBIDDEN")

    def test_failing_adapter_hooks_degrade_context_and_doctor(self):
        self.adapter.mode = "broken-hooks"
        context = self.call("context")["data"]
        adapter = context["environment"]["components"][1]
        self.assertEqual((adapter["identity_status"], adapter["role"]), ("unavailable", "adapter"))
        self.assertIn("environment() failed", adapter["reason"])
        checks = {check["check"]: check for check in self.call("doctor")["data"]["checks"]}
        self.assertEqual(checks["native_backend"]["status"], "fail")

    def test_changelog_since(self):
        data = self.call("changelog")["data"]
        self.assertEqual([entry["version"] for entry in data["entries"]], ["1.2.0", "1.1.0"])
        data = self.call("changelog", "--since", "1.1.0")["data"]
        self.assertEqual([entry["version"] for entry in data["entries"]], ["1.2.0"])
        self.assertEqual(self.call("changelog", "--since", "latest", code=2)["error"]["details"]["problem"], "invalid_value")

    def test_context_manager_closes_the_store(self):
        with DriverCLI(self.contract, self.adapter, validator=VALIDATOR, environ=self.environ, home=self.base / "home") as cli:
            self.call("operation", "list", cli=cli)
            self.assertIsNotNone(cli._store)
        self.assertIsNone(cli._store)

    # ---------------------------------------------------------------- parsing

    def test_usage_problems_are_specific(self):
        cases = [
            (["frobnicate"], "unknown_command"),
            (["doc", "show"], "missing_parameter"),
            (["doc", "show", "--path", str(self.doc), "--bogus", "1"], "unknown_flag"),
            (["doc", "show", "--path", str(self.doc), "--limit", "ten"], "invalid_value"),
            (["doc", "show", "--path", str(self.doc), "--mode", "fancy"], "invalid_value"),
            (["doc", "show", "--path", str(self.doc), "--format", "raw"], "invalid_value"),
            (["doc", "show", "--path", str(self.doc), "--dry-run"], "conflicting_flags"),
            (["doc", "edit", "--path", str(self.doc), "--text", "x", "--fields", "receipt", "--dry-run"], "conflicting_flags"),
            (["doc", "show", "--path", str(self.doc), "--version"], "conflicting_flags"),
            (["doc", "edit", "--path", str(self.doc), "--text", "x", "--phase", "apply"], "unknown_flag"),
            (["doc", "edit", "--path", str(self.doc), "--text", "--dry-run"], "missing_parameter"),
            (["doc", "show", "--path", str(self.doc), "-x"], "unknown_flag"),
        ]
        seen = set()
        for argv, problem in cases:
            with self.subTest(argv=argv):
                details = self.call(*argv, code=2)["error"]["details"]
                self.assertEqual(details["problem"], problem)
                self.assertEqual(details["dispatch_state"], "not_started")
                seen.add((problem, details.get("parameter")))
        self.assertGreaterEqual(len(seen), 9, "different mistakes must be distinguishable")

    def test_values_that_look_like_flags_stay_values(self):
        self.grant()
        details = self.call("doc", "edit", "--path", str(self.doc), "--text=--dry-run", code=5)["error"]["details"]
        self.assertEqual(details["problem"], "confirmation_required")
        details = self.call("doc", "edit", "--path", str(self.doc), "--text", "x", "--confirm", "--dry-run", code=2)["error"]["details"]
        self.assertEqual((details["problem"], details["parameter"]), ("missing_parameter", "--confirm"))
        data = self.call("doc", "edit", "--path", str(self.doc), "--text=-5", "--dry-run=true")["data"]
        self.assertIn("preview", data)
        self.assertEqual(self.call("doc", "show", "--path", str(self.doc), "--dry-run=maybe", code=2)["error"]["details"]["parameter"], "--dry-run")
        self.assertEqual(self.call("doc", "show", "--path", str(self.doc), "--limit", "-5")["data"]["words"], 2)

    def test_values_are_converted_checked_and_lists_deduplicated(self):
        data = self.call("doc", "show", "--path", str(self.doc), "--tags", "a,b", "--tags", "b", "--tags", "c")["data"]
        self.assertEqual(data["words"], 2)
        self.assertEqual(data["_untrusted"], ["text"])
        for value in ["99999999999999999999", "1e5"]:
            self.assertEqual(self.call("doc", "show", "--path", str(self.doc), "--limit", value, code=2)["error"]["code"], "E_VALIDATION")
        for meta in ["[" * 100000 + "]" * 100000, "1e999", "NaN"]:
            with self.subTest(meta=meta[:10]):
                details = self.call("doc", "show", "--path", str(self.doc), "--meta", meta, code=2)["error"]["details"]
                self.assertEqual((details["problem"], details["parameter"]), ("invalid_value", "--meta"))
        details = self.call("doc", "show", "--path", "bad\udc80path", code=2)["error"]["details"]
        self.assertEqual(details["parameter"], "--path")
        result = self.cli.run(["doc", "show", "--path", str(self.doc), "stray-value"])
        self.assertNotIn(b"stray-value", result.stdout, "diagnostics do not echo input values")
        meta = self.base / "meta.json"
        meta.write_text('{"k": 1}', encoding="utf-8")
        self.grant()
        preview = self.edit("x", "--meta", "@" + str(meta), "--force", "--dry-run")["data"]["preview"]
        self.assertEqual(preview["capability_id"], "doc-edit")

    def test_path_lists_are_not_split_on_commas(self):
        comma = self.root / "a,b.txt"
        comma.write_text("one", encoding="utf-8")
        self.grant()
        preview = self.call("doc", "stamp", "--paths", str(comma), "--dry-run")["data"]["preview"]
        self.assertEqual(preview["targets"], ["a,b.txt"])

    def test_fields_projection(self):
        data = self.call("doc", "show", "--path", str(self.doc), "--fields", "words,text")["data"]
        self.assertEqual(set(data), {"words", "text", "_untrusted"})
        details = self.call("doc", "show", "--path", str(self.doc), "--fields", "nope", code=2)["error"]["details"]
        self.assertIn("words", details["expected"])

    def test_text_and_compact_rendering(self):
        compact = self.cli.run(["doc", "show", "--path", str(self.doc), "--compact"]).stdout
        self.assertEqual(compact.count(b"\n"), 1)
        text = self.cli.run(["doc", "show", "--path", str(self.doc), "--format", "text"]).stdout.decode("utf-8")
        self.assertIn("ok: true", text)

    def test_request_id_is_checked_before_dispatch(self):
        self.grant()
        data = self.plan()
        details = self.edit("new text", "--confirm", data["confirm_token"], "--request-id", "k" * 600, code=2)["error"]["details"]
        self.assertEqual(details["parameter"], "--request-id")
        self.assertEqual(self.adapter.applied, 0)
        self.assertEqual(self.show(data["preview"]["operation_id"])["status"], "planned")

    # ---------------------------------------------------------------- write gate and scope

    def test_write_gate_order(self):
        self.assertEqual(self.edit(code=5)["error"]["details"]["problem"], "confirmation_required")
        self.assertEqual(self.edit("x", "--dry-run", "--confirm", "ct_x", code=2)["error"]["details"]["problem"], "conflicting_flags")
        forbidden = self.edit("x", "--dry-run", code=4)["error"]["details"]
        self.assertEqual(forbidden["scope"]["missing"]["effects"], ["change", "persist"])
        self.assertTrue(forbidden["scope"]["grant_file"].endswith("scope.json"))
        self.assertEqual(self.adapter.applied, 0)

    def test_creating_a_file_is_a_confirmed_write(self):
        target_file = self.out / "doc.txt"
        self.assertEqual(self.call("doc", "export", "--path", str(self.doc), "--output", str(target_file), code=5)["error"]["code"],
                         "E_CONFIRMATION_REQUIRED")
        self.grant()
        outside = self.call("doc", "export", "--path", str(self.doc), "--output", str(self.base / "elsewhere.txt"), "--dry-run", code=4)
        self.assertEqual(outside["error"]["details"]["scope"]["missing"]["paths"], [str(self.base / "elsewhere.txt")])
        data = self.call("doc", "export", "--path", str(self.doc), "--output", str(target_file), "--dry-run")["data"]
        self.assertFalse(target_file.exists(), "a dry-run creates nothing")
        receipt = self.call("doc", "export", "--path", str(self.doc), "--output", str(target_file), "--confirm", data["confirm_token"])["data"]["receipt"]
        self.assertEqual(receipt["artifacts"][0]["path"], str(target_file))
        self.assertEqual(target_file.read_text(encoding="utf-8"), "HELLO WORLD")

    def test_dangerous_commands_need_flag_scope_and_destination(self):
        self.grant()
        argv = ["doc", "publish", "--path", str(self.doc), "--share", "release", "--dry-run"]
        self.assertEqual(self.call(*argv, code=5)["error"]["details"]["problem"], "dangerous_flag_required")
        missing = self.call(*argv, "--dangerous", code=4)["error"]["details"]["scope"]["missing"]
        self.assertTrue(missing["dangerous"])
        self.grant(effects=["observe", "deliver"], dangerous=True, destinations=["share://archive/"])
        missing = self.call(*argv, "--dangerous", code=4)["error"]["details"]["scope"]["missing"]
        self.assertEqual(missing["destinations"], ["share://release/doc.txt"])
        self.grant(effects=["observe", "deliver"], dangerous=True, destinations=["share://release/"])
        data = self.call(*argv, "--dangerous")["data"]
        receipt = self.call("doc", "publish", "--path", str(self.doc), "--share", "release", "--confirm", data["confirm_token"],
                            "--dangerous")["data"]["receipt"]
        self.assertEqual(receipt["outcome"]["delivery"], "delivered")

    def test_paths_outside_the_scope_are_refused(self):
        self.grant()
        outside = self.base / "outside.txt"
        outside.write_text("x", encoding="utf-8")
        missing = self.call("doc", "edit", "--path", str(outside), "--text", "y", "--dry-run", code=4)["error"]["details"]["scope"]["missing"]
        self.assertTrue(missing["paths"])

    def test_file_locators_are_decoded_once_and_fail_closed(self):
        if os.name == "nt":
            self.assertEqual(file_path_of("file:///D:/work/a%2541.txt"), "D:\\work\\a%41.txt")
        else:
            self.assertEqual(file_path_of("file:///work/a%2541.txt"), "/work/a%41.txt")
        with self.assertRaises(ValueError):
            file_path_of("file://server/share/doc.txt")
        summary = {"status": "granted", "scope_id": "s", "source": {"kind": "file", "path": "x"}, "effects": ["observe", "change"],
                   "roots": [str(self.root)], "outputs": [], "destinations": [], "dangerous": False, "expires_at": None, "reason": None}
        scope = Scope(summary, {"targets": []}, "scope.json")
        for locator in ["file://server/share/doc.txt", "session://instance/doc", (self.root / "doc.txt").as_uri()]:
            with self.subTest(locator=locator):
                missing = scope.missing(effects=["change"], target={"mode": "file", "engine_id": "text", "instance_id": None,
                                                                     "object_id": "doc", "locator": locator})
                self.assertEqual(bool(missing.get("paths")), not locator.startswith("file:///"))

    def test_operation_budget_from_the_scope(self):
        self.grant(limits={"max_operations": 1})
        data = self.plan()
        self.edit("new text", "--confirm", data["confirm_token"])
        details = self.edit("again", "--dry-run", code=4)["error"]["details"]
        self.assertIn("max_operations", details["scope"]["missing"]["limit"])

    # ---------------------------------------------------------------- plan and confirm

    def test_dry_run_then_confirm(self):
        self.grant()
        data = self.plan()
        preview = data["preview"]
        self.assertEqual(data["expires_at"], preview["expires_at"])
        self.assertEqual(self.doc.read_text(encoding="utf-8"), "hello world", "a dry-run never changes the target")
        status = self.show(preview["operation_id"])
        self.assertEqual(status["status"], "planned")
        self.assertEqual(status["plan"], preview, "operation show returns the plan that was reviewed")
        receipt = self.edit("new text", "--confirm", data["confirm_token"])["data"]["receipt"]
        self.assertEqual((receipt["operation_id"], receipt["plan_id"]), (preview["operation_id"], preview["plan_id"]))
        self.assertEqual(receipt["outcome"]["persistence"], "saved")
        self.assertEqual(self.show(preview["operation_id"])["status"], "succeeded")
        conflict = self.edit("new text", "--confirm", data["confirm_token"], code=6)["error"]["details"]
        self.assertEqual(conflict["conflict"], "token_used")
        self.assertEqual(self.adapter.applied, 1)

    def test_tokens_bind_arguments_and_expire(self):
        self.grant()
        data = self.plan()
        self.assertEqual(self.edit("other", "--confirm", data["confirm_token"], code=6)["error"]["details"]["conflict"], "token_mismatch")
        forged = data["confirm_token"][:-4] + ("AAAA" if not data["confirm_token"].endswith("AAAA") else "BBBB")
        self.assertEqual(self.edit("new text", "--confirm", forged, code=6)["error"]["details"]["conflict"], "token_mismatch")
        self.clock[0] = self.clock[0] + timedelta(hours=1)
        self.assertEqual(self.edit("new text", "--confirm", data["confirm_token"], code=6)["error"]["details"]["conflict"], "token_expired")
        self.assertEqual(self.adapter.applied, 0)

    def test_scope_changes_between_plan_and_confirm(self):
        self.grant()
        data = self.plan()
        self.grant(scope_id="scope-2")
        self.assertEqual(self.edit("new text", "--confirm", data["confirm_token"], code=6)["error"]["details"]["conflict"], "scope_changed")
        data = self.plan()
        self.grant(revoked=True)
        self.assertEqual(self.edit("new text", "--confirm", data["confirm_token"], code=4)["error"]["code"], "E_FORBIDDEN")
        self.assertEqual(self.adapter.applied, 0)

    def test_drift_stops_before_dispatch(self):
        self.grant()
        data = self.plan()
        self.doc.write_text("edited in the GUI", encoding="utf-8")
        details = self.edit("new text", "--confirm", data["confirm_token"], code=6)["error"]["details"]
        self.assertEqual(details["conflict"], "state_drift")
        self.assertEqual(self.adapter.applied, 0)
        self.assertEqual(self.doc.read_text(encoding="utf-8"), "edited in the GUI")

    # ---------------------------------------------------------------- outcomes

    def test_lost_reply_is_unknown_until_resolved(self):
        self.grant()
        data = self.plan()
        operation = data["preview"]["operation_id"]
        self.adapter.mode = "crash"
        error = self.edit("new text", "--confirm", data["confirm_token"], code=6)["error"]
        self.assertEqual(error["code"], "E_OUTCOME_UNKNOWN")
        self.assertFalse(error["retryable"])
        self.assertEqual(error["details"]["operation_id"], operation)
        self.assertIn("operation show", error["details"]["lookup"])
        self.adapter.mode = "normal"
        blocked = self.edit("again", "--dry-run", code=6)["error"]["details"]
        self.assertEqual((blocked["conflict"], blocked["active_operation"]), ("unresolved_operation", operation))
        listed = self.call("operation", "list", "--status", "unknown")["data"]
        self.assertEqual([item["operation_id"] for item in listed["items"]], [operation])
        resolved = self.call("operation", "resolve", "--id", operation, "--outcome", "applied", "--evidence", "doc show printed new text")
        self.assertEqual(resolved["data"]["operation_status"]["resolution"]["outcome"], "applied")
        self.call("operation", "resolve", "--id", operation, "--outcome", "applied", "--evidence", "again", code=2)
        self.edit("again", "--dry-run")

    def test_a_plan_made_earlier_cannot_dispatch_past_an_unresolved_operation(self):
        self.grant()
        first = self.plan("first")
        second = self.plan("second")
        self.adapter.mode = "crash-before-write"
        self.edit("first", "--confirm", first["confirm_token"], code=6)
        self.adapter.mode = "normal"
        details = self.edit("second", "--confirm", second["confirm_token"], code=6)["error"]["details"]
        self.assertEqual((details["conflict"], details["active_operation"]), ("unresolved_operation", first["preview"]["operation_id"]))
        self.assertEqual(self.show(second["preview"]["operation_id"])["status"], "planned", "the refused plan was not dispatched")

    def test_adapter_hints_never_replace_the_lookup_after_a_lost_reply(self):
        self.grant()
        data = self.plan()
        self.adapter.mode = "lost-with-hints"
        details = self.edit("new text", "--confirm", data["confirm_token"], code=6)["error"]["details"]
        self.assertEqual(details["lookup_argv"], ["operation", "show", "--id", data["preview"]["operation_id"]])
        self.assertNotEqual(details["next_action"], "just retry")
        self.assertEqual((details["native_code"], details["reported_code"]), (42, "E_TIMEOUT"))

    def test_partial_verify_failed_and_invalid_receipts(self):
        self.grant()
        for mode, code, exit_code, status in [("partial", "E_PARTIAL", 1, "partial"), ("verify-fail", "E_VERIFY_FAILED", 1, "failed"),
                                              ("invalid", "E_OUTCOME_UNKNOWN", 6, "unknown")]:
            with self.subTest(mode=mode):
                self.adapter.mode = "normal"
                self.doc.write_text("hello world", encoding="utf-8")
                for record in self.store().list("unknown")[0] + self.store().list("partial")[0]:
                    if record.get("resolution") is None:
                        self.call("operation", "resolve", "--id", record["operation_id"], "--outcome", "applied", "--evidence", "test")
                data = self.plan(mode)
                self.adapter.mode = mode
                error = self.edit(mode, "--confirm", data["confirm_token"], code=exit_code)["error"]
                self.assertEqual(error["code"], code)
                if code != "E_OUTCOME_UNKNOWN":
                    self.assertEqual(error["details"]["receipt"]["operation_id"], data["preview"]["operation_id"])
                self.assertEqual(self.show(data["preview"]["operation_id"])["status"], status)

    def test_a_refusal_before_dispatch_keeps_the_token_usable(self):
        self.grant()
        data = self.plan()
        self.adapter.mode = "busy"
        error = self.edit("new text", "--confirm", data["confirm_token"], code=7)["error"]
        self.assertEqual((error["code"], error["retryable"], error["details"]["dispatch_state"]), ("E_BUSY", True, "not_started"))
        self.assertEqual(self.show(data["preview"]["operation_id"])["status"], "planned")
        self.adapter.mode = "normal"
        receipt = self.edit("new text", "--confirm", data["confirm_token"])["data"]["receipt"]
        self.assertEqual(receipt["operation_id"], data["preview"]["operation_id"])
        self.assertEqual(self.adapter.applied, 1)

    def test_errors_before_native_dispatch_keep_their_code(self):
        self.grant()
        self.adapter.mode = "human-plan"
        error = self.edit("new text", "--dry-run", code=9)["error"]
        self.assertEqual(error["details"]["action"], "licence")
        self.adapter.mode = "not-a-dict"
        self.assertEqual(self.call("doc", "show", "--path", str(self.doc), code=1)["error"]["code"], "E_UNKNOWN")

    def test_interrupts_report_whether_anything_was_dispatched(self):
        self.grant()
        self.adapter.mode = "interrupt-plan"
        error = self.edit("x", "--dry-run", code=130)["error"]
        self.assertEqual((error["code"], error["details"]["dispatch_state"]), ("E_INTERRUPTED", "not_started"))
        self.adapter.mode = "normal"
        data = self.plan()
        self.adapter.mode = "interrupt-apply"
        error = self.edit("new text", "--confirm", data["confirm_token"], code=6)["error"]
        self.assertEqual(error["code"], "E_OUTCOME_UNKNOWN")
        self.assertEqual(self.show(data["preview"]["operation_id"])["status"], "unknown")

    def test_idempotency_key_replays_only_recorded_outcomes(self):
        self.grant()
        data = self.plan()
        first = self.edit("new text", "--confirm", data["confirm_token"], "--request-id", "key-1")["data"]["receipt"]
        self.assertEqual(first["request_id"], "key-1")
        for _ in range(2):
            data = self.plan()
            replay = self.edit("new text", "--confirm", data["confirm_token"], "--request-id", "key-1")["data"]["receipt"]
            self.assertTrue(replay["replayed"])
            self.assertEqual(replay["operation_id"], first["operation_id"])
        self.assertEqual(self.adapter.applied, 1)
        data = self.plan("different")
        conflict = self.edit("different", "--confirm", data["confirm_token"], "--idempotency-key", "key-1", code=6)["error"]["details"]
        self.assertEqual(conflict["conflict"], "idempotency_mismatch")

    def test_a_key_whose_operation_provably_did_not_start_runs_again(self):
        self.grant()
        data = self.plan("v1")
        self.adapter.mode = "crash-before-write"
        self.edit("v1", "--confirm", data["confirm_token"], "--request-id", "key-2", code=6)
        self.adapter.mode = "normal"
        self.call("operation", "resolve", "--id", data["preview"]["operation_id"], "--outcome", "not_applied", "--evidence", "file unchanged")
        again = self.plan("v1")
        receipt = self.edit("v1", "--confirm", again["confirm_token"], "--request-id", "key-2")["data"]["receipt"]
        self.assertNotIn("replayed", receipt)
        self.assertEqual(self.doc.read_text(encoding="utf-8"), "v1")

    def test_a_key_resolved_as_applied_is_not_run_again(self):
        self.grant()
        data = self.plan("v1")
        self.adapter.mode = "crash"
        self.edit("v1", "--confirm", data["confirm_token"], "--request-id", "key-3", code=6)
        self.adapter.mode = "normal"
        self.call("operation", "resolve", "--id", data["preview"]["operation_id"], "--outcome", "applied", "--evidence", "file says v1")
        applied = self.adapter.applied
        again = self.plan("v1")
        details = self.edit("v1", "--confirm", again["confirm_token"], "--request-id", "key-3", code=6)["error"]["details"]
        self.assertEqual((details["conflict"], details["active_operation"]), ("token_used", data["preview"]["operation_id"]))
        self.assertEqual(self.adapter.applied, applied)

    # ---------------------------------------------------------------- leases and records

    def test_a_running_operation_holds_the_target_until_its_lease_expires(self):
        self.grant()
        data = self.plan()
        operation = data["preview"]["operation_id"]
        store = self.store()
        record = store.get(operation)
        store.dispatch(operation, fingerprint="f" * 64, token_expires=self.clock[0].timestamp() + 600, key=None,
                       digest=record["request_digest"], target_keys=[record["target_key"]], lease=30)
        self.assertEqual(self.show(operation)["status"], "running")
        self.assertEqual([item["operation_id"] for item in self.call("operation", "list", "--status", "running")["data"]["items"]], [operation])
        details = self.edit("again", "--dry-run", code=6)["error"]["details"]
        self.assertEqual((details["conflict"], details["active_operation"]), ("lock_held", operation))
        details = self.call("operation", "resolve", "--id", operation, "--outcome", "applied", "--evidence", "x", code=6)["error"]["details"]
        self.assertEqual(details["conflict"], "lock_held")
        self.clock[0] += timedelta(seconds=31)
        status = self.show(operation)
        self.assertEqual((status["status"], status["stage"]), ("unknown", "dispatched_without_result"))
        self.assertEqual([item["operation_id"] for item in self.call("operation", "list", "--status", "unknown")["data"]["items"]], [operation])
        self.call("operation", "resolve", "--id", operation, "--outcome", "applied", "--evidence", "read back")
        late = {"operation_id": operation}
        self.assertFalse(store.finish(operation, "succeeded", late), "a late result never overwrites a resolution")
        record = store.get(operation)
        self.assertEqual((record["status"], record["receipt"]), ("unknown", None))
        self.assertEqual(record["extra"]["late_result"]["receipt"], late)
        self.show(operation)

    def test_the_lease_is_renewed_while_the_native_call_runs(self):
        self.grant()
        cli = self.make_cli(now=None, lease_seconds=0.3)
        data = self.call("doc", "edit", "--path", str(self.doc), "--text", "slow", "--dry-run", cli=cli)["data"]
        self.adapter.mode = "slow"
        self.call("doc", "edit", "--path", str(self.doc), "--text", "slow", "--confirm", data["confirm_token"], cli=cli)
        lease, observed = self.adapter.lease_seen
        self.assertGreater(lease, observed, "after 1 s the 0.3 s lease was still live")

    def test_a_killed_cli_leaves_unknown_not_running(self):
        self.grant()
        data = self.plan()
        operation = data["preview"]["operation_id"]
        contract_file = self.base / "contract.json"
        contract_file.write_text(json.dumps(self.contract), encoding="utf-8")
        child = self.base / "child.py"
        child.write_text("\n".join([
            "import json, sys",
            f"sys.path[:0] = [{str(ROOT / 'packages')!r}, {str(ROOT / 'scripts')!r}, {str(ROOT / 'tests')!r}]",
            "import test_sdk",
            "from tool_driver_sdk import DriverCLI, load_contract",
            "adapter = test_sdk.TextAdapter()",
            "adapter.mode = 'hang'",
            "cli = DriverCLI(load_contract(sys.argv[1]), adapter, validator=test_sdk.VALIDATOR, environ=json.loads(sys.argv[2]),",
            "                home=sys.argv[3], lease_seconds=1.0)",
            "cli.run(sys.argv[4:])",
        ]) + "\n", encoding="utf-8")
        process = subprocess.Popen([sys.executable, str(child), str(contract_file), json.dumps(self.environ), str(self.base / "home"),
                                    "doc", "edit", "--path", str(self.doc), "--text", "new text", "--confirm", data["confirm_token"]],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            deadline = time.monotonic() + 60
            while self.store().get(operation)["status"] != "dispatched":
                self.assertLess(time.monotonic(), deadline, "the child never dispatched")
                time.sleep(0.1)
        finally:
            process.kill()
            process.wait(timeout=30)
        self.clock[0] = datetime.now(timezone.utc)
        self.assertEqual(self.edit("again", "--dry-run", code=6)["error"]["details"]["conflict"], "lock_held")
        self.clock[0] = datetime.now(timezone.utc) + timedelta(seconds=2)
        status = self.show(operation)
        self.assertEqual((status["status"], status["stage"]), ("unknown", "dispatched_without_result"))
        self.assertEqual(self.edit("again", "--dry-run", code=6)["error"]["details"]["conflict"], "unresolved_operation")
        self.call("operation", "resolve", "--id", operation, "--outcome", "not_applied", "--evidence", "doc still says hello world")
        self.edit("again", "--dry-run")

    def test_rejected_results_are_demoted_consistently(self):
        self.grant()
        data = self.plan()
        receipt = self.edit("new text", "--confirm", data["confirm_token"])["data"]["receipt"]
        self.store().demote(receipt["operation_id"], "result_failed_contract")
        status = self.show(receipt["operation_id"])
        self.assertEqual((status["status"], status["receipt"]), ("unknown", None))

    def test_long_operation_is_queried_not_resubmitted(self):
        self.grant()
        data = self.call("doc", "render", "--path", str(self.doc), "--dry-run")["data"]
        status = self.call("doc", "render", "--path", str(self.doc), "--confirm", data["confirm_token"])["data"]["operation_status"]
        self.assertEqual(status["status"], "pending")
        self.adapter.status_mode = "raise"
        result = self.cli.run(["operation", "show", "--id", status["operation_id"]])
        self.assertEqual(result.envelope["data"]["operation_status"]["status"], "pending")
        self.assertIn("status query failed", result.stderr)
        self.adapter.status_mode = "garbage"
        self.assertEqual(self.show(status["operation_id"])["status"], "pending")
        self.adapter.status_mode = "normal"
        self.assertEqual(self.show(status["operation_id"])["status"], "succeeded")
        self.assertEqual(len(self.adapter.submitted), 1)

    def test_an_unknown_submission_status_is_not_stored_as_pending(self):
        self.grant()
        data = self.call("doc", "render", "--path", str(self.doc), "--dry-run")["data"]
        self.adapter.mode = "submit-queued"
        error = self.call("doc", "render", "--path", str(self.doc), "--confirm", data["confirm_token"], code=6)["error"]
        self.assertEqual(error["code"], "E_OUTCOME_UNKNOWN")
        self.assertEqual(self.show(data["preview"]["operation_id"])["status"], "unknown")

    def test_unavailable_store_refuses_before_dispatch(self):
        self.grant()
        (self.base / "state").write_text("not a directory", encoding="utf-8")
        error = self.edit("x", "--dry-run", code=1)["error"]
        self.assertEqual((error["code"], error["details"]["dispatch_state"]), ("E_IO", "not_started"))
        context = self.call("context")["data"]
        self.assertFalse(context["state"]["available"])

    def test_a_damaged_secret_is_replaced(self):
        store = self.store()
        first = store.secret()
        (self.base / "state" / "confirm.secret").write_text("short", encoding="ascii")
        second = store.secret()
        self.assertEqual(len(second), 32)
        self.assertNotEqual(first, second)

    def test_target_keys_use_the_normalized_locator(self):
        alias = self.root / "sub" / ".." / "doc.txt"
        (self.root / "sub").mkdir()
        self.assertEqual(target_key({"mode": "file", "engine_id": "text", "instance_id": None, "object_id": "a",
                                     "locator": self.doc.as_uri()}),
                         target_key({"mode": "file", "engine_id": "text", "instance_id": None, "object_id": "b",
                                     "locator": "file:///" + str(alias).replace("\\", "/").lstrip("/")}))

    def test_operation_commands_validate_their_inputs(self):
        self.assertEqual(self.call("operation", "show", "--id", "op-none", code=3)["error"]["code"], "E_NOT_FOUND")
        self.grant()
        data = self.plan()
        self.edit("new text", "--confirm", data["confirm_token"])
        details = self.call("operation", "resolve", "--id", data["preview"]["operation_id"], "--outcome", "applied",
                            "--evidence", "x", code=2)["error"]["details"]
        self.assertEqual(details["problem"], "invalid_value")
        self.assertEqual(self.call("operation", "list", "--limit", "500", code=2)["error"]["details"]["parameter"], "--limit")
        self.assertEqual(self.call("operation", "list", "--offset", "-1", code=2)["error"]["details"]["parameter"], "--offset")

    # ---------------------------------------------------------------- review findings

    def test_a_revision_failure_inside_a_batch_never_claims_nothing_was_sent(self):
        self.grant()
        paths = self.make_docs("a", "b", "c")
        preview = self.stamp(paths, "--dry-run")["data"]
        self.adapter.revision_calls = 0
        self.adapter.failing_revisions = {5}
        data = self.stamp(paths, "--confirm", preview["confirm_token"])["data"]
        self.assertEqual([item["ok"] for item in data["items"]], [True, False, True])
        self.assertEqual(data["items"][1]["error"]["code"], "E_BACKEND_UNAVAILABLE")
        self.assertEqual(paths[0].read_text(encoding="utf-8"), "a [stamped]")
        self.assertEqual(self.store().started_under("scope-1"), 2, "the item that never started gives its unit back")

    def test_a_bare_error_after_dispatch_is_unknown_and_the_token_stays_spent(self):
        self.grant()
        data = self.plan()
        self.adapter.mode = "bare-error"
        error = self.edit("new text", "--confirm", data["confirm_token"], code=6)["error"]
        self.assertEqual((error["code"], error["details"]["reported_code"]), ("E_OUTCOME_UNKNOWN", "E_NATIVE_FAILURE"))
        self.adapter.mode = "normal"
        self.assertEqual(self.edit("new text", "--confirm", data["confirm_token"], code=6)["error"]["details"]["conflict"], "token_used")
        self.assertEqual(self.show(data["preview"]["operation_id"])["status"], "unknown")

    def test_destinations_match_whole_url_segments(self):
        self.grant(effects=["observe", "deliver"], dangerous=True, destinations=["share://release"])
        for share, allowed in [("release", True), ("release-evil", False)]:
            with self.subTest(share=share):
                argv = ["doc", "publish", "--path", str(self.doc), "--share", share, "--dry-run", "--dangerous"]
                self.call(*argv, code=0 if allowed else 4)
        self.grant(effects=["observe", "deliver"], dangerous=True, destinations=["share://user@release/"])
        self.assertEqual(self.call("context")["data"]["authorization"]["status"], "invalid")

    def test_network_paths_are_refused_without_being_resolved(self):
        from unittest import mock
        from tool_driver_sdk.scope import inside
        with mock.patch("tool_driver_sdk.scope.os.path.realpath", side_effect=AssertionError("resolved a network path")):
            self.assertFalse(inside("\\\\attacker\\share\\x.txt", [str(self.root)]))
            self.assertFalse(inside("//attacker/share/x.txt", [str(self.root)]))
        with self.assertRaises(ValueError):
            file_path_of("file:////attacker/share/x.txt")
        if os.name == "nt":
            with self.assertRaises(ValueError):
                file_path_of("file:///D:/a:b")

    def test_a_long_operation_nobody_can_observe_becomes_unknown(self):
        self.grant()
        cli = self.make_cli(status_lease_seconds=60)
        data = self.call("doc", "render", "--path", str(self.doc), "--dry-run", cli=cli)["data"]
        operation = data["preview"]["operation_id"]
        self.call("doc", "render", "--path", str(self.doc), "--confirm", data["confirm_token"], cli=cli)
        self.adapter.status_mode = "raise"
        self.assertEqual(self.call("doc", "edit", "--path", str(self.doc), "--text", "x", "--dry-run", code=6, cli=cli)
                         ["error"]["details"]["conflict"], "lock_held")
        self.clock[0] += timedelta(seconds=61)
        self.assertEqual(self.call("operation", "show", "--id", operation, cli=cli)["data"]["operation_status"]["status"], "unknown")
        self.assertEqual(self.call("doc", "edit", "--path", str(self.doc), "--text", "x", "--dry-run", code=6, cli=cli)
                         ["error"]["details"]["conflict"], "unresolved_operation")
        self.call("operation", "resolve", "--id", operation, "--outcome", "not_applied", "--evidence", "render output absent", cli=cli)
        self.call("doc", "edit", "--path", str(self.doc), "--text", "x", "--dry-run", cli=cli)
        store = self.store()
        self.assertFalse(store.update_status(operation, "running", {}, 60), "a resolved record never becomes active again")

    def test_empty_keys_and_unpaired_surrogates_are_refused(self):
        self.grant()
        data = self.plan()
        details = self.edit("new text", "--confirm", data["confirm_token"], "--request-id=", code=2)["error"]["details"]
        self.assertEqual(details["parameter"], "--request-id")
        details = self.call("doc", "show", "--path", str(self.doc), "--meta", '"\\ud800"', code=2)["error"]["details"]
        self.assertEqual((details["problem"], details["parameter"]), ("invalid_value", "--meta"))
        self.assertEqual(self.adapter.applied, 0)

    def test_batch_items_inherit_the_batch_unknowns(self):
        self.grant()
        paths = self.make_docs("a", "READONLY b")
        self.adapter.mode = "batch-unknown"
        preview = self.stamp(paths, "--dry-run")["data"]["preview"]
        self.assertFalse(preview["can_apply"])
        item = self.show(preview["items"][1]["operation_id"])["plan"]
        self.assertIn("A read-only file cannot be stamped.", item["unknowns"])

    def test_an_interrupted_batch_settles_from_its_items(self):
        self.grant()
        paths = self.make_docs("a", "b")
        preview = self.stamp(paths, "--dry-run")["data"]["preview"]
        store = self.store()
        batch = store.get(preview["operation_id"])
        items = store.items_of(preview["operation_id"])
        store.dispatch(batch["operation_id"], fingerprint="b" * 64, token_expires=self.clock[0].timestamp() + 600, key=None,
                       digest=batch["request_digest"], target_keys=[item["target_key"] for item in items],
                       exclude=[item["operation_id"] for item in items], units=2, lease=30)
        store.start_item(items[0]["operation_id"], items[0]["target_key"], 30)
        store.finish(items[0]["operation_id"], "failed", None, {"stage": "test"})
        self.assertEqual(self.show(preview["operation_id"])["status"], "running")
        self.clock[0] += timedelta(seconds=31)
        status = self.show(preview["operation_id"])
        self.assertEqual((status["status"], [item["status"] for item in status["items"]]), ("failed", ["failed", "planned"]))
        self.assertEqual(store.get(preview["operation_id"])["status"], "failed", "the stored record was settled")

    def test_records_go_with_their_batch_and_the_budget_survives_retention(self):
        self.grant(limits={"max_operations": 3})
        paths = self.make_docs("a", "b")
        preview = self.stamp(paths, "--dry-run")["data"]
        self.stamp(paths, "--confirm", preview["confirm_token"])
        batch_id = preview["preview"]["operation_id"]
        self.cli.close()
        self.clock[0] += timedelta(days=40)
        store = self.store()
        self.assertIsNone(store.get(batch_id))
        self.assertEqual(store.items_of(batch_id), [])
        self.assertEqual(store.started_under("scope-1"), 2)
        self.grant(limits={"max_operations": 3}, expires_at=None)
        data = self.plan()
        self.edit("new text", "--confirm", data["confirm_token"])
        self.assertIn("max_operations", self.edit("again", "--dry-run", code=4)["error"]["details"]["scope"]["missing"]["limit"])

    def test_late_results_are_shown(self):
        self.grant()
        data = self.plan()
        operation = data["preview"]["operation_id"]
        self.adapter.mode = "crash-before-write"
        self.edit("new text", "--confirm", data["confirm_token"], code=6)
        self.call("operation", "resolve", "--id", operation, "--outcome", "not_applied", "--evidence", "unchanged")
        self.store().finish(operation, "succeeded", {"operation_id": operation})
        self.assertEqual(self.show(operation)["extensions"]["late_result"]["status"], "succeeded")

    def test_old_record_stores_are_migrated(self):
        import sqlite3
        folder = self.base / "old-state"
        folder.mkdir()
        connection = sqlite3.connect(str(folder / "operations.sqlite3"))
        connection.executescript(
            "CREATE TABLE operations (operation_id TEXT PRIMARY KEY, plan_id TEXT, capability_id TEXT NOT NULL, command TEXT NOT NULL,"
            " target_key TEXT, request_digest TEXT, scope_id TEXT, idempotency_key TEXT, status TEXT NOT NULL, effects TEXT NOT NULL,"
            " plan TEXT, receipt TEXT, extra TEXT, resolution TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL, started_at REAL,"
            " finished_at REAL, plan_expires_at REAL);"
            "CREATE INDEX operations_target ON operations(target_key, status);")
        connection.close()
        store = StateStore(folder)
        try:
            store.connection()
            self.assertEqual(store.list()[1], 0)
        finally:
            store.close()

    def test_a_damaged_record_is_a_store_failure(self):
        self.grant()
        data = self.plan()
        self.store().connection().execute("UPDATE operations SET plan = '{broken' WHERE operation_id = ?", (data["preview"]["operation_id"],))
        error = self.call("operation", "show", "--id", data["preview"]["operation_id"], code=1)["error"]
        self.assertEqual(error["code"], "E_IO")

    # ---------------------------------------------------------------- batch and update

    def make_docs(self, *texts):
        paths = []
        for index, text in enumerate(texts):
            path = self.root / f"d{index}.txt"
            path.write_text(text, encoding="utf-8")
            paths.append(path)
        return paths

    def stamp(self, paths, *extra, code=0):
        argv = ["doc", "stamp"]
        for path in paths:
            argv += ["--paths", str(path)]
        return self.call(*argv, *extra, code=code)

    def test_batch_plans_once_and_reports_every_item(self):
        self.grant()
        paths = self.make_docs("a", "LOCKED b", "c")
        preview = self.stamp(paths, "--dry-run")["data"]
        plan = preview["preview"]
        self.assertEqual((plan["total"], plan["targets"]), (3, ["d0.txt", "d1.txt", "d2.txt"]))
        self.assertEqual(len({item["operation_id"] for item in plan["items"]}), 3)
        self.assertEqual(paths[0].read_text(encoding="utf-8"), "a")
        data = self.stamp(paths, "--confirm", preview["confirm_token"])["data"]
        self.assertEqual(data["summary"], {"total": 3, "succeeded": 2, "failed": 1})
        failed = data["items"][1]
        self.assertEqual((failed["ok"], failed["error"]["code"]), (False, "E_NATIVE_FAILURE"))
        self.assertEqual(paths[2].read_text(encoding="utf-8"), "c [stamped]")
        batch = self.show(plan["operation_id"])
        self.assertEqual((batch["status"], [item["status"] for item in batch["items"]]), ("partial", ["succeeded", "failed", "succeeded"]))
        self.assertEqual(self.show(plan["items"][0]["operation_id"])["receipt"]["operation_id"], plan["items"][0]["operation_id"])
        self.call("operation", "resolve", "--id", plan["operation_id"], "--outcome", "applied", "--evidence", "x", code=2)
        self.assertEqual(self.stamp(paths, "--confirm", preview["confirm_token"], code=6)["error"]["details"]["conflict"], "token_used")

    def test_batch_stops_on_first_failure_when_asked(self):
        self.grant()
        paths = self.make_docs("LOCKED a", "b")
        preview = self.stamp(paths, "--continue-on-error=false", "--dry-run")["data"]
        data = self.stamp(paths, "--continue-on-error=false", "--confirm", preview["confirm_token"])["data"]
        self.assertEqual(data["summary"], {"total": 1, "succeeded": 0, "failed": 1, "skipped": 1})
        self.assertIn("skipped_reason", data["items"][1])
        self.assertEqual(paths[1].read_text(encoding="utf-8"), "b")
        self.assertEqual(self.show(preview["preview"]["operation_id"])["status"], "failed")

    def test_batch_refuses_idempotency_keys_and_checks_every_item_scope(self):
        self.grant()
        paths = self.make_docs("a")
        outside = self.base / "outside.txt"
        outside.write_text("x", encoding="utf-8")
        missing = self.stamp([paths[0], outside], "--dry-run", code=4)["error"]["details"]["scope"]["missing"]
        self.assertTrue(missing["paths"])
        preview = self.stamp(paths, "--dry-run")["data"]
        details = self.stamp(paths, "--confirm", preview["confirm_token"], "--request-id", "k", code=2)["error"]["details"]
        self.assertEqual(details["parameter"], "--request-id")

    def test_update_is_one_call_without_a_token(self):
        data = self.call("update", "--check")["data"]
        self.assertEqual(data["status"], "up_to_date")
        self.assertTrue(self.call("update", "--dry-run")["data"]["dry_run"])
        self.assertEqual(self.call("update", "--confirm", "ct_x", code=2)["error"]["details"]["parameter"], "--confirm")


if __name__ == "__main__":
    unittest.main()
