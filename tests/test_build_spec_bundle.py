"""Tests for scripts/build_spec_bundle.py."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_spec_bundle as bundle  # noqa: E402


class BuildTest(unittest.TestCase):
    def test_build_is_reproducible_and_complete(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            path_a, digest_a = bundle.build(Path(a))
            path_b, digest_b = bundle.build(Path(b))
            self.assertEqual(digest_a, digest_b)
            self.assertEqual(hashlib.sha256(path_a.read_bytes()).hexdigest(), digest_a)
            sha_line = (Path(a) / f"tool-driver-cli-spec-{bundle.version()}.sha256").read_text(encoding="utf-8")
            self.assertEqual(sha_line, f"{digest_a}  {path_a.name}\n")
            prefix = f"tool-driver-cli-spec-{bundle.version()}/"
            with zipfile.ZipFile(path_a) as archive:
                names = archive.namelist()
                self.assertIn(prefix + "contract/driver-contract.json", names)
                self.assertIn(prefix + "VERSION", names)
                # A tool project gets everything it needs from the bundle: the runtime, the
                # suites with the fake host, the evaluation questions, the template, the
                # project scripts and the development Skill.
                for needed in ("sdk/python/_driver/tool.py", "sdk/python/_driver/update.py", "conformance/suites/__main__.py",
                               "conformance/fakehost/server.py", "template/package.json", "template/scripts/spec.py",
                               "scripts/check_project.py", "scripts/sync_spec.py", "scripts/instantiate.py",
                               "scripts/run_matrix.py", "scripts/run_eval.py", "conformance/eval/read_answer.py",
                               "skills/build-driver-cli/SKILL.md"):
                    self.assertIn(prefix + needed, names)
                self.assertFalse([n for n in names if "__pycache__" in n or n.endswith(".pyc")])
                self.assertTrue(all(n.startswith(prefix) for n in names))
                manifest = json.loads(archive.read(prefix + "MANIFEST.json"))
                self.assertEqual(manifest["version"], bundle.version())
                for name, digest in manifest["files"].items():
                    self.assertEqual(hashlib.sha256(archive.read(prefix + name)).hexdigest(), digest, name)


class LocalFilesTest(unittest.TestCase):
    def test_a_file_git_does_not_track_never_ships(self):
        cache = ROOT / "template" / ".ruff_cache-bundle-test"
        cache.mkdir(exist_ok=True)
        try:
            (cache / "entry").write_text("local", encoding="utf-8")
            names = {p.relative_to(ROOT).as_posix() for p in bundle.bundle_files()}
            self.assertNotIn("template/.ruff_cache-bundle-test/entry", names)
            self.assertIn("template/package.json", names)
        finally:
            (cache / "entry").unlink(missing_ok=True)
            cache.rmdir()


class NotesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_root = bundle.ROOT
        bundle.ROOT = Path(self.tmp.name)
        (bundle.ROOT / "CHANGELOG.md").write_text(
            "# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - 2026-12-01\n\n### Added\n\n- One.\n\n## [0.9.0] - 2026-11-01\n\n- Old.\n",
            encoding="utf-8",
        )

    def tearDown(self):
        bundle.ROOT = self.old_root
        self.tmp.cleanup()

    def test_notes_of_a_version(self):
        self.assertEqual(bundle.notes("1.0.0"), "### Added\n\n- One.\n")
        self.assertEqual(bundle.notes("0.9.0"), "- Old.\n")

    def test_missing_version(self):
        with self.assertRaises(SystemExit):
            bundle.notes("2.0.0")


if __name__ == "__main__":
    unittest.main()
