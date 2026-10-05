"""The starter: a new project gets the rules, the pinned copies, tests, CI, CHANGELOG and a SKILL-SPEC Skill."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "instantiate_starter.py"
HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run(argv, cwd, timeout=180):
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, "-B", *argv], cwd=cwd, capture_output=True, timeout=timeout, env=environment,
                          creationflags=HIDDEN)


class StarterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="starter-tests-")
        cls.base = Path(cls.temporary.name).resolve()
        cls.project = cls.base / "demo-cad-cli"
        result = run([str(SCRIPT), "--name", "demo-cad-cli", "--profile", "session", "--output", str(cls.project)], cls.base)
        cls.response = json.loads(result.stdout.decode("utf-8"))
        cls.returncode = result.returncode

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_instantiation_reports_a_base_envelope_and_self_check(self):
        self.assertEqual(self.returncode, 0, self.response)
        self.assertEqual(set(self.response), {"ok", "schema_version", "data", "meta"})
        self.assertEqual([item["ok"] for item in self.response["data"]["self_check"]], [True, True, True, False])
        self.assertEqual(self.response["data"]["base"]["tag"], "v1.6.3")

    def test_each_mode_generates_an_unimplemented_backend_with_real_cli_guards(self):
        for profile in ("file", "session", "device"):
            with self.subTest(profile=profile):
                name = f"sample-{profile}-driver"
                project = self.base / name
                result = run([str(SCRIPT), "--name", name, "--profile", profile, "--output", str(project)], self.base)
                response = json.loads(result.stdout)
                self.assertEqual(result.returncode, 0, response)
                self.assertEqual(response["data"]["native_status"], "not_implemented")
                package = name.replace("-", "_")
                result = run(["-m", package, "reference"], project)
                self.assertEqual(result.returncode, 0, result.stdout)
                reference = json.loads(result.stdout)["data"]
                self.assertEqual(reference["release_readiness"]["level"], "unpublishable")
                targets = [command for command in reference["commands"] if command["path"].startswith("target ")]
                self.assertEqual({command["path"] for command in targets}, {"target inspect", "target apply"})
                for command in targets:
                    self.assertEqual(command["driver"]["modes"], [profile])
                    self.assertEqual(command["driver"]["maturity"], "draft")
                    self.assertEqual(command["driver"]["evidence_refs"], [])
                    self.assertNotIn("physical", command["driver"]["effects"])
                result = run(["-m", package, "context"], project)
                self.assertEqual(result.returncode, 0, result.stdout)
                components = json.loads(result.stdout)["data"]["environment"]["components"]
                backend = next(item for item in components if item["name"] == f"unimplemented {profile} adapter")
                self.assertEqual((backend["role"], backend["identity_status"]), ("adapter", "unavailable"))
                self.assertEqual(run(["check_project.py"], project).returncode, 0)
                # Generated tests exercise real subprocess CLI boundaries: native refusal, scope/confirmation,
                # forged tokens, discovery and FCC. Passing them does not claim that a backend exists.
                result = run(["-m", "unittest", "discover", "-s", "tests", "-v"], project, timeout=600)
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace")[-3000:])

    def test_extracted_source_does_not_borrow_an_ancestor_checkout_identity(self):
        sys.path.insert(0, str(ROOT / 'scripts'))
        import instantiate_starter
        replies = [subprocess.CompletedProcess([], 0, str(ROOT.parent), ''),
                   subprocess.CompletedProcess([], 0, 'a' * 40, ''),
                   subprocess.CompletedProcess([], 0, '', '')]
        with patch.object(instantiate_starter.subprocess, 'run', side_effect=replies):
            observed = instantiate_starter.source_identity()
        self.assertEqual(observed['kind'], 'unversioned_copy')
        self.assertIsNone(observed['source_commit'])

    def test_project_carries_rules_tests_ci_changelog_and_skill(self):
        for relative in ["AGENTS.md", ".agent/AGENT.md", ".agent/driver/docs/CORE-SPEC.md", ".agent/driver/docs/SKILL-ADDENDUM.md",
                         ".agent/driver/base/ai-native-cli-spec/CLI-SPEC.md", ".agent/driver/base/ai-native-cli-spec/SKILL-SPEC_zh.md", ".agent/driver/contract/driver-contract.json",
                         ".agent/vendor/sdk/tool_driver_sdk/runtime.py", "tests/test_contract.py", ".github/workflows/ci.yml",
                         "CHANGELOG.md", "pyproject.toml", "skills/demo-cad-cli/SKILL.md", "skills/demo-cad-cli/test-prompts.json",
                         "demo_cad_cli/adapter.py", "demo_cad_cli/generated/product_contract.json"]:
            with self.subTest(path=relative):
                self.assertTrue((self.project / relative).is_file())
        for path in self.project.rglob("*"):
            if path.is_file() and path.suffix in {".md", ".py", ".json", ".toml", ".yml"} and ".agent" not in path.parts:
                text = path.read_text(encoding="utf-8")
                leftovers = [match for match in re.findall(r"\{\{[A-Z_]+\}\}", text)]
                self.assertEqual(leftovers, [], path)

    def test_skill_versions_and_binary_agree_with_the_product(self):
        skill = (self.project / "skills" / "demo-cad-cli" / "SKILL.md").read_text(encoding="utf-8")
        front = skill.split("---")[1]
        self.assertIn('version: "0.1.0"', front)
        metadata = json.loads(re.search(r"metadata: (\{.*\})", front).group(1))
        self.assertEqual(metadata["requires"], {"bins": ["demo-cad-cli"], "min_version": "0.1.0"})
        self.assertIn("STOP CHECKPOINT", skill)
        prompts = json.loads((self.project / "skills" / "demo-cad-cli" / "test-prompts.json").read_text(encoding="utf-8"))
        ids = {item["id"] for item in prompts}
        for required in ["missing-scope", "lost-reply", "ambiguous-target", "injected-note", "modal-dialog", "dangerous-command"]:
            self.assertIn(required, ids)

    def test_lock_lists_every_pinned_copy(self):
        lock = json.loads((self.project / ".agent" / "driver" / "starter-lock.json").read_text(encoding="utf-8"))
        for item in lock["files"]:
            self.assertEqual(hashlib.sha256((self.project / item["path"]).read_bytes()).hexdigest(), item["sha256"])
            self.assertEqual((ROOT / item["source_path"]).read_bytes(), (self.project / item["path"]).read_bytes())

    def test_check_project_detects_drift(self):
        result = run(["check_project.py"], self.project)
        self.assertEqual(result.returncode, 0, result.stdout)
        target = self.project / ".agent" / "driver" / "docs" / "CORE-SPEC.md"
        original = target.read_bytes()
        try:
            target.write_bytes(original + b"\nlocal edit\n")
            result = run(["check_project.py"], self.project)
            response = json.loads(result.stdout)
            self.assertEqual((result.returncode, response["error"]["code"]), (1, "E_INTEGRITY"))
            self.assertIn(".agent/driver/docs/CORE-SPEC.md", response["error"]["details"]["drifted"])
        finally:
            target.write_bytes(original)

    def test_generated_project_passes_its_own_tests(self):
        result = run(["-m", "unittest", "discover", "-s", "tests"], self.project, timeout=600)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace")[-3000:])

    def test_product_metadata_version_drift_is_detected_and_synchronized(self):
        project = self.project / 'pyproject.toml'
        skill = self.project / 'skills/demo-cad-cli/SKILL.md'
        originals = {project:project.read_bytes(), skill:skill.read_bytes()}
        try:
            project.write_bytes(originals[project].replace(b'version = "0.1.0"', b'version = "0.2.0"'))
            skill.write_bytes(originals[skill].replace(b'"0.1.0"', b'"0.2.0"'))
            response = run(['check_project.py'], self.project)
            self.assertEqual(response.returncode,1)
            drift = json.loads(response.stdout)['error']['details']['version_drift']
            self.assertEqual(set(drift), {'pyproject.toml','Skill.version','Skill.requires.min_version'})
            synchronized = run(['sync_version.py'], self.project)
            self.assertEqual(synchronized.returncode,0,synchronized.stdout)
            self.assertEqual(run(['check_project.py'], self.project).returncode,0)
        finally:
            for path, content in originals.items():
                path.write_bytes(content)

    def test_refusals_create_nothing(self):
        cases = [(["--name", "Bad_Name", "--profile", "file"], 2, "E_VALIDATION"),
                 (["--name", "ok-name", "--profile", "robot"], 2, "E_USAGE")]
        for arguments, code, error in cases:
            with self.subTest(arguments=arguments):
                output = self.base / ("refused-" + str(code) + arguments[1])
                result = run([str(SCRIPT), *arguments, "--output", str(output)], self.base)
                response = json.loads(result.stdout)
                self.assertEqual((result.returncode, response["error"]["code"]), (code, error))
                self.assertFalse(output.exists())
        result = run([str(SCRIPT), "--name", "again", "--profile", "file", "--output", str(self.project)], self.base)
        self.assertEqual((result.returncode, json.loads(result.stdout)["error"]["code"]), (6, "E_CONFLICT"))


if __name__ == "__main__":
    unittest.main()
