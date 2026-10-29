"""Command-level contract tests for {{NAME}}.

Run the optional full FCC check with {{ENV_PREFIX}}_CHECK_FULL_FCC=1; report it as skipped otherwise.
Each call runs the real CLI in a subprocess without a console window and validates the envelope against the
pinned contract. Replace the E_UNSUPPORTED expectations as the adapter gains real behaviour.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".agent" / "vendor" / "sdk"))
from tool_driver_sdk import ContractValidator  # noqa: E402

HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PREFIX = "{{ENV_PREFIX}}"
REFERENCE = json.loads((ROOT / "{{PACKAGE}}" / "generated" / "reference.json").read_text(encoding="utf-8"))
COMMANDS = {tuple(command["path"].split()) for command in REFERENCE["commands"]}
EXERCISED: set[tuple[str, ...]] = set()
VALIDATOR = ContractValidator(ROOT / ".agent" / "driver")


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="{{NAME}}-tests-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.scope_file = self.base / "scope.json"

    def run_cli(self, *argv, scope: dict | None = None):
        environment = dict(os.environ)
        environment.update({PREFIX + "_STATE_DIR": str(self.base / "state"), PREFIX + "_SCOPE_FILE": str(self.scope_file),
                            "PYTHONDONTWRITEBYTECODE": "1"})
        if scope is not None:
            self.scope_file.write_text(json.dumps(scope), encoding="utf-8")
        result = subprocess.run([sys.executable, "-m", "{{PACKAGE}}", *argv], cwd=ROOT, env=environment, capture_output=True,
                                timeout=60, creationflags=HIDDEN)
        for length in range(len(argv), 0, -1):
            if tuple(argv[:length]) in COMMANDS:
                EXERCISED.add(tuple(argv[:length]))
                break
        envelope = json.loads(result.stdout.decode("utf-8"))
        VALIDATOR.validate("response", envelope)
        return envelope, result.returncode

    def scope(self, effects=("observe", "change")):
        return {"scope_id": "scope-tests", "tool": "{{NAME}}", "granted_by": "contract tests", "granted_at": "2026-01-01T00:00:00Z",
                "expires_at": None, "effects": list(effects), "dangerous": False, "roots": [str(self.base)],
                "outputs": [str(self.base / "out")], "targets": [{"engine_id": "any"}]}

    # ------------------------------------------------------------ self-description

    def test_reference_views(self):
        full, code = self.run_cli("reference")
        self.assertEqual(code, 0)
        VALIDATOR.validate("reference", full["data"])
        index, _ = self.run_cli("reference", "--index")
        self.assertEqual({item["path"] for item in index["data"]["commands"]}, {" ".join(path) for path in COMMANDS})
        one, _ = self.run_cli("reference", "--command", "target apply")
        self.assertEqual(one["data"]["command"]["path"], "target apply")
        self.assertNotIn("urn:tool-driver-cli-spec:receipt:2.0", one["data"]["json_schemas"])

    def test_context_reports_a_missing_scope_file(self):
        envelope, code = self.run_cli("context")
        self.assertEqual(code, 0)
        VALIDATOR.validate("context", envelope["data"])
        self.assertEqual(envelope["data"]["authorization"]["status"], "invalid")

    def test_doctor_has_the_driver_checks(self):
        envelope, code = self.run_cli("doctor")
        self.assertEqual(code, 0)
        VALIDATOR.validate("doctor", envelope["data"])

    def test_changelog_since(self):
        envelope, code = self.run_cli("changelog", "--since", "0.0.0")
        self.assertEqual(code, 0)
        self.assertEqual(envelope["data"]["entries"][0]["version"], REFERENCE["version"])

    def test_operation_records(self):
        listed, code = self.run_cli("operation", "list")
        self.assertEqual((code, listed["data"]["count"]), (0, 0))
        shown, code = self.run_cli("operation", "show", "--id", "op-missing")
        self.assertEqual((code, shown["error"]["code"]), (3, "E_NOT_FOUND"))
        resolved, code = self.run_cli("operation", "resolve", "--id", "op-missing", "--outcome", "applied", "--evidence", "none")
        self.assertEqual((code, resolved["error"]["code"]), (3, "E_NOT_FOUND"))

    # ------------------------------------------------------------ product commands

    def test_target_inspect_refuses_until_the_adapter_exists(self):
        envelope, code = self.run_cli("target", "inspect", "--target-id", "t1")
        self.assertEqual((code, envelope["error"]["code"]), (2, "E_UNSUPPORTED"))
        missing, code = self.run_cli("target", "inspect")
        self.assertEqual((code, missing["error"]["details"]["problem"]), (2, "missing_parameter"))
        unknown, code = self.run_cli("target", "inspect", "--target-id", "t1", "--phase", "observe")
        self.assertEqual((code, unknown["error"]["details"]["problem"]), (2, "unknown_flag"))

    def test_target_apply_needs_a_plan_and_a_scope(self):
        envelope, code = self.run_cli("target", "apply", "--target-id", "t1", "--change", "{}")
        self.assertEqual((code, envelope["error"]["code"]), (5, "E_CONFIRMATION_REQUIRED"))
        envelope, code = self.run_cli("target", "apply", "--target-id", "t1", "--change", "{}", "--dry-run")
        self.assertEqual((code, envelope["error"]["code"]), (4, "E_FORBIDDEN"))
        self.assertIn("change", envelope["error"]["details"]["scope"]["missing"]["effects"])
        envelope, code = self.run_cli("target", "apply", "--target-id", "t1", "--change", "{}", "--dry-run", scope=self.scope())
        self.assertEqual((code, envelope["error"]["code"]), (2, "E_UNSUPPORTED"))
        envelope, code = self.run_cli("target", "apply", "--target-id", "t1", "--change", "{}", "--confirm", "ct_forged.token")
        self.assertEqual((code, envelope["error"]["details"]["conflict"]), (6, "token_mismatch"))

    # ------------------------------------------------------------ functional contract coverage

    def test_zz_every_command_has_a_test(self):
        if os.environ.get("{{ENV_PREFIX}}_CHECK_FULL_FCC") != "1":
            self.skipTest(f"Full FCC not checked; commands not exercised: {sorted(COMMANDS - EXERCISED)}")
        self.assertEqual(sorted(COMMANDS - EXERCISED), [], "every reference command needs a command-level test")


if __name__ == "__main__":
    unittest.main()
