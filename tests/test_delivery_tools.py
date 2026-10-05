"""Actual CLI boundary tests using synthetic packages, not native-tool evidence."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
SOURCE_COMMIT = "a" * 40
SOURCE_PATH = "schemas/sample.schema.json"
MANAGED_PATH = ".agent/schemas/sample.schema.json"
BASE_BYTES = (ROOT / "base/base-lock.json").read_bytes()
BASE_LOCK = json.loads(BASE_BYTES)
sys.path.insert(0, str(ROOT / "scripts"))
from bundle_layout import required_payload
HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SCHEMA_BYTES = (json.dumps({"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "urn:synthetic:sample:1.0", "type": "object", "description": "合成契约样本", "properties": {"text": {"type": "string"}}, "additionalProperties": False}, ensure_ascii=False) + "\n").encode("utf-8")


class DeliveryCLITests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="spec-delivery-tests-")
        self.base = Path(self.temporary.name)
        self.project = self.base / "consumer"
        self.project.mkdir()
        self.bundle = self.base / "specification.zip"
        self.lock_path = self.base / "adoption.json"
        self.copy_path = self.project / MANAGED_PATH
        self.copy_path.parent.mkdir(parents=True)
        self.copy_path.write_bytes(SCHEMA_BYTES)
        self.payloads = {path: (ROOT / path).read_bytes() for path in required_payload()}
        self.payloads.update({"VERSION": (SPEC_VERSION + "\n").encode(), SOURCE_PATH: SCHEMA_BYTES,
                              "STATUS": b"experimental\n"})
        self.manifest = {
            "artifact_kind": "specification", "name": "synthetic-contract-package",
            "version": SPEC_VERSION, "spec_version": SPEC_VERSION, "base": {"spec": "ai-native-cli-spec", "version": "v1.6.3"}, "status": "experimental",
            "source_commit": SOURCE_COMMIT, "source_dirty": False,
            "target": {"os": "any", "arch": "any"},
            "components": [
                {"name": path, "version": SPEC_VERSION, "path": path, "sha256": hashlib.sha256(payload).hexdigest(), "role": "schema" if path.startswith("schemas/") else "base" if path.startswith("base/") else "documentation"}
                for path, payload in self.payloads.items()
            ],
            "compatibility": {"application": [], "plugin": [], "protocol": [], "skill": []},
            "external_requirements": [],
            "limitations": ["Synthetic package for CLI contract tests; no application or device was executed."],
        }
        self.write_bundle()
        self.lock = {
            "spec_version": SPEC_VERSION, "schema_version": "2.0", "source_kind": "bundle", "source_commit": SOURCE_COMMIT,
            "source_dirty": False, "package_sha256": self.bundle_digest(),
            "base": {key: BASE_LOCK[key] for key in ("spec", "tag", "commit")},
            "files": [{"path": MANAGED_PATH, "source_path": SOURCE_PATH, "sha256": hashlib.sha256(SCHEMA_BYTES).hexdigest()}],
        }
        self.write_lock()

    def tearDown(self):
        self.temporary.cleanup()

    def write_bundle(self, payloads=None, manifest=None, extra_entries=(), compression=zipfile.ZIP_STORED):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(self.bundle, "w", compression=compression) as archive:
                for path, payload in (self.payloads if payloads is None else payloads).items():
                    archive.writestr(path, payload)
                archive.writestr("manifest.json", json.dumps(self.manifest if manifest is None else manifest).encode("utf-8"))
                for path, payload in extra_entries:
                    archive.writestr(path, payload)

    def bundle_digest(self):
        return hashlib.sha256(self.bundle.read_bytes()).hexdigest()

    def write_lock(self):
        self.lock_path.write_text(json.dumps(self.lock), encoding="utf-8")

    def invoke(self, script, *arguments, expected=0):
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / script), *map(str, arguments)], capture_output=True, timeout=30, env=environment, cwd=self.base, creationflags=HIDDEN)
        self.assertEqual(result.returncode, expected, result.stderr.decode("utf-8", errors="replace") + result.stdout.decode("utf-8", errors="replace"))
        self.assertFalse(result.stdout.startswith(b"\xef\xbb\xbf"))
        response = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(set(response), {"ok", "schema_version", "meta", "data" if expected == 0 else "error"})
        self.assertEqual(response["schema_version"], "1.0")
        self.assertEqual(response["ok"], expected == 0)
        if expected:
            self.assertFalse(response["error"]["retryable"])
            self.assertIn("next_action", response["error"]["details"])
        return response

    def verify(self, *arguments, expected=0):
        return self.invoke("verify_spec_bundle.py", "--bundle", self.bundle, *arguments, expected=expected)

    def adopt(self, expected=0, root=None):
        return self.invoke("check_adoption.py", "--lock", self.lock_path, "--root", self.project if root is None else root, "--bundle", self.bundle, expected=expected)

    def test_expected_digest_and_components_are_checked(self):
        response = self.verify("--expected-sha256", self.bundle_digest())
        self.assertTrue(response["data"]["expected_digest_matched"])
        self.assertFalse(response["data"]["origin_authenticated"])
        self.assertEqual(response["data"]["component_count"], len(self.payloads))

    def test_no_expected_digest_reports_internal_consistency_only(self):
        response = self.verify()
        self.assertFalse(response["data"]["expected_digest_matched"])
        self.assertIn("No independent", response["data"]["limitations"][0])

    def test_checksum_file_selects_the_exact_package(self):
        checksum = self.base / "checksums.txt"
        checksum.write_text("0" * 64 + "  other.zip\n" + self.bundle_digest() + "  " + self.bundle.name + "\n", encoding="utf-8")
        self.verify("--checksum", checksum)
        checksum.write_text(self.bundle_digest() + "  " + self.bundle.name + "\n" + self.bundle_digest() + "  " + self.bundle.name + "\n", encoding="utf-8")
        self.verify("--checksum", checksum, expected=2)

    def test_wrong_package_digest_is_integrity_failure(self):
        self.assertEqual(self.verify("--expected-sha256", "0" * 64, expected=1)["error"]["code"], "E_INTEGRITY")

    def test_member_tampering_is_rejected_even_with_updated_archive_digest(self):
        payloads = dict(self.payloads)
        payloads[SOURCE_PATH] = SCHEMA_BYTES[:-1] + b" "
        self.write_bundle(payloads=payloads)
        response = self.verify("--expected-sha256", self.bundle_digest(), expected=1)
        self.assertEqual(response["error"]["code"], "E_INTEGRITY")

    def test_unlisted_or_missing_files_are_rejected(self):
        self.write_bundle(extra_entries=[("hidden.txt", b"not declared")])
        self.verify(expected=2)
        self.write_bundle(payloads={"VERSION": self.payloads["VERSION"]})
        self.verify(expected=2)

    def test_bad_zip_and_input_io_have_distinct_exits(self):
        self.bundle.write_bytes(b"not a ZIP")
        self.verify(expected=2)
        self.bundle.unlink()
        self.assertEqual(self.verify(expected=1)["error"]["code"], "E_IO")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX named-pipe input check")
    def test_implicit_pipe_inputs_are_rejected_without_waiting_for_a_writer(self):
        self.bundle.unlink()
        os.mkfifo(self.bundle)
        self.verify(expected=2)
        self.bundle.unlink()
        self.write_bundle()
        self.lock_path.unlink()
        os.mkfifo(self.lock_path)
        self.adopt(expected=2)

    def test_zip_traversal_and_noncanonical_paths_are_rejected(self):
        for path in ["../outside", "/absolute", "C:/drive", "schemas\\windows", "schemas/./alias", ".", "schemas/a.", "schemas/NUL"]:
            with self.subTest(path=path):
                self.write_bundle(extra_entries=[(path, b"malformed")])
                self.verify(expected=2)
        self.assertFalse((self.base / "outside").exists())

    def test_duplicate_and_case_colliding_entries_are_rejected(self):
        for path in [SOURCE_PATH, SOURCE_PATH.upper()]:
            with self.subTest(path=path):
                self.write_bundle(extra_entries=[(path, SCHEMA_BYTES)])
                self.assertIn("duplicate", self.verify(expected=2)["error"]["message"])

    def test_zip_symbolic_link_is_rejected_without_extracting_it(self):
        entry = zipfile.ZipInfo("link")
        entry.create_system = 3
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.write_bundle(extra_entries=[(entry, b"outside")])
        self.assertIn("links", self.verify(expected=2)["error"]["message"])
        self.assertFalse((self.base / "link").exists())

    def test_corrupt_member_crc_returns_a_structured_failure(self):
        archive = self.bundle.read_bytes()
        self.assertIn(SCHEMA_BYTES, archive)
        self.bundle.write_bytes(archive.replace(SCHEMA_BYTES, SCHEMA_BYTES[:-1] + b" ", 1))
        response = self.verify(expected=2)
        self.assertIn("ZIP", response["error"]["message"])

    def test_manifest_self_hash_and_component_version_are_rejected(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["components"].append({"name": "self", "version": SPEC_VERSION, "path": "manifest.json", "sha256": "0" * 64, "role": "documentation"})
        self.write_bundle(manifest=manifest)
        self.verify(expected=2)
        manifest = copy.deepcopy(self.manifest)
        manifest["components"][0]["version"] = "9.0.0"
        self.write_bundle(manifest=manifest)
        self.verify(expected=2)

    def test_uncompressed_limit_blocks_small_compressed_bomb(self):
        self.write_bundle(extra_entries=[("large.txt", b"x" * (2 * 1024 * 1024))], compression=zipfile.ZIP_DEFLATED)
        self.assertIn("uncompressed", self.verify("--max-uncompressed", "65536", expected=2)["error"]["message"])

    def test_manifest_identity_and_version_must_be_consistent(self):
        for field, value in [("source_commit", "not-a-commit"), ("version", "9.0.0"), ("source_dirty", True)]:
            with self.subTest(field=field):
                manifest = copy.deepcopy(self.manifest)
                manifest[field] = value
                self.write_bundle(manifest=manifest)
                self.verify(expected=2)

    def test_embedded_status_must_match_manifest_even_with_valid_hashes(self):
        payloads = dict(self.payloads, STATUS=b"experimental\n")
        manifest = copy.deepcopy(self.manifest)
        self.write_bundle(payloads=payloads, manifest=manifest)
        self.verify("--expected-sha256", self.bundle_digest())
        manifest["status"] = "stable"
        self.write_bundle(payloads=payloads, manifest=manifest)
        response = self.verify("--expected-sha256", self.bundle_digest(), expected=2)
        self.assertIn("STATUS", response["error"]["message"])

    def test_self_consistent_missing_required_payload_is_rejected(self):
        for missing in ("VERSION", "STATUS", "base/base-lock.json", "schemas/receipt.schema.json",
                        "docs/CORE-SPEC.md", "packages/tool_driver_sdk/runtime.py",
                        "starter/common/package/adapter.py"):
            with self.subTest(missing=missing):
                payloads = {path: payload for path, payload in self.payloads.items() if path != missing}
                manifest = copy.deepcopy(self.manifest)
                manifest["components"] = [item for item in manifest["components"] if item["path"] != missing]
                self.write_bundle(payloads=payloads, manifest=manifest)
                response = self.verify("--expected-sha256", self.bundle_digest(), expected=2)
                self.assertIn("missing required", response["error"]["message"])
                self.assertIn(missing, response["error"]["message"])

    def test_base_bytes_must_match_pinned_lock_even_when_manifest_hash_is_updated(self):
        path = BASE_LOCK["files"][0]["path"]
        payloads = dict(self.payloads)
        payloads[path] += b"\nchanged\n"
        manifest = copy.deepcopy(self.manifest)
        for component in manifest["components"]:
            if component["path"] == path:
                component["sha256"] = hashlib.sha256(payloads[path]).hexdigest()
        self.write_bundle(payloads=payloads, manifest=manifest)
        self.assertIn("pinned base", self.verify(expected=1)["error"]["message"])

    def test_base_lock_cannot_omit_a_present_normative_file(self):
        lock = copy.deepcopy(BASE_LOCK)
        lock['files'] = lock['files'][1:]
        payloads = dict(self.payloads)
        payloads['base/base-lock.json'] = json.dumps(lock).encode()
        manifest = copy.deepcopy(self.manifest)
        for component in manifest['components']:
            if component['path'] == 'base/base-lock.json':
                component['sha256'] = hashlib.sha256(payloads['base/base-lock.json']).hexdigest()
        self.write_bundle(payloads=payloads, manifest=manifest)
        self.assertIn('complete pinned base inventory', self.verify(expected=2)['error']['message'])

    def test_embedded_base_lock_must_match_manifest(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["base"]["version"] = "v1.6.4"
        self.write_bundle(manifest=manifest)
        response = self.verify("--expected-sha256", self.bundle_digest(), expected=2)
        self.assertIn("base lock", response["error"]["message"])

    def test_adoption_compares_source_and_copy_bytes_without_writing_project(self):
        before = {path.relative_to(self.project).as_posix(): path.read_bytes() for path in self.project.rglob("*") if path.is_file()}
        response = self.adopt()
        after = {path.relative_to(self.project).as_posix(): path.read_bytes() for path in self.project.rglob("*") if path.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(response["data"]["checked_files"][0]["sha256"], hashlib.sha256(SCHEMA_BYTES).hexdigest())
        self.assertFalse(response["data"]["origin_authenticated"])

    def test_same_size_schema_drift_is_rejected(self):
        self.copy_path.write_bytes(SCHEMA_BYTES[:-1] + b" ")
        self.assertEqual(self.adopt(expected=1)["error"]["code"], "E_INTEGRITY")

    def test_lock_base_pin_must_match_the_bundle(self):
        self.lock["base"]["commit"] = "e" * 40
        self.write_lock()
        self.assertEqual(self.adopt(expected=1)["error"]["code"], "E_INTEGRITY")

    def test_a_lock_taken_from_a_checkout_is_not_a_bundle_pin(self):
        self.lock.update(source_kind="git_checkout", source_dirty=True, package_sha256=None)
        self.write_lock()
        self.assertIn("not a specification bundle", self.adopt(expected=2)["error"]["message"])

    def test_lock_bundle_hash_source_commit_and_schema_hash_are_checked(self):
        original = copy.deepcopy(self.lock)
        for field in ["package_sha256", "source_commit", "sha256"]:
            with self.subTest(field=field):
                self.lock = copy.deepcopy(original)
                if field == "sha256":
                    self.lock["files"][0][field] = "0" * 64
                else:
                    self.lock[field] = "0" * (40 if field == "source_commit" else 64)
                self.write_lock()
                self.assertEqual(self.adopt(expected=1)["error"]["code"], "E_INTEGRITY")

    def test_unknown_sources_and_duplicate_destinations_are_rejected(self):
        original = copy.deepcopy(self.lock)
        self.lock["files"][0]["source_path"] = "schemas/missing.schema.json"
        self.write_lock()
        self.adopt(expected=2)
        for path in [MANAGED_PATH, MANAGED_PATH.upper()]:
            with self.subTest(path=path):
                self.lock = copy.deepcopy(original)
                duplicate = dict(self.lock["files"][0], path=path)
                self.lock["files"].append(duplicate)
                self.write_lock()
                self.adopt(expected=2)

    def test_bad_empty_or_corrupt_lock_cannot_pass(self):
        for value in [[], {}, dict(self.lock, files=[]), dict(self.lock, files=[dict(self.lock["files"][0], path="../outside.schema.json")])]:
            with self.subTest(value=value):
                self.lock_path.write_text(json.dumps(value), encoding="utf-8")
                self.adopt(expected=2)
        self.lock_path.write_bytes(b'{"spec_version":"1.0.0","spec_version":"1.0.0"}')
        self.adopt(expected=2)

    def test_missing_managed_copy_is_validation_failure(self):
        self.copy_path.unlink()
        self.adopt(expected=2)

    def test_managed_file_symlink_is_rejected(self):
        outside = self.base / "outside.schema.json"
        outside.write_bytes(SCHEMA_BYTES)
        self.copy_path.unlink()
        try:
            self.copy_path.symlink_to(outside)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"filesystem does not permit symbolic links: {exc}")
        self.adopt(expected=2)
        self.assertEqual(outside.read_bytes(), SCHEMA_BYTES)

    @unittest.skipUnless(os.name == "nt", "Windows junction check")
    def test_managed_directory_junction_is_rejected(self):
        outside = self.base / "external"
        outside.mkdir()
        (outside / "sample.schema.json").write_bytes(SCHEMA_BYTES)
        self.copy_path.unlink()
        directory = self.copy_path.parent
        directory.rmdir()
        created = subprocess.run(["cmd", "/c", "mklink", "/J", str(directory), str(outside)], capture_output=True, timeout=15, creationflags=HIDDEN)
        if created.returncode:
            self.skipTest("test filesystem does not permit junction creation")
        try:
            self.adopt(expected=2)
            self.assertEqual((outside / "sample.schema.json").read_bytes(), SCHEMA_BYTES)
        finally:
            directory.rmdir()


if __name__ == "__main__":
    unittest.main()
