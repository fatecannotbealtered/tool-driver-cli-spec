"""Unit tests of ``update`` (DCLI-070 to DCLI-079).

A small script stands in for npm. It answers ``npm view`` from a JSON file that plays the
registry, and lays out a global install the way npm does, so the tests see the command
entries, the native program, the main package and its Skills where a real install puts them.
"""
from __future__ import annotations

import errno
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "sdk" / "python"))
sys.path.insert(0, str(REPO / "tests" / "sample"))
sys.path.insert(0, str(REPO / "conformance"))

from _driver import builtin, update  # noqa: E402
from sample_cli import build  # noqa: E402
from suites import schemas  # noqa: E402

WINDOWS = os.name == "nt"
PACKAGE = "@tool-driver/sample-cli"
PLATFORM = f"{PACKAGE}-{update._os()}-{update._cpu()}"
INSTALL = ["install", "-g"]

FAKE_NPM = r'''
import json, os, sys, time
from pathlib import Path

args = sys.argv[1:]
with open(os.environ["FAKE_NPM_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(args) + "\n")
prefix = Path(os.environ["FAKE_NPM_PREFIX"])
windows = os.name == "nt"
root = prefix / "node_modules" if windows else prefix / "lib" / "node_modules"
if args[:2] == ["prefix", "-g"]:
    print(prefix)
    sys.exit(0)
if args[:1] == ["view"]:
    registry = json.loads(Path(os.environ["FAKE_NPM_REGISTRY"]).read_text(encoding="utf-8"))
    time.sleep(registry.get("sleep", 0))
    if registry.get("error"):
        print(json.dumps({"error": {"code": registry["error"], "summary": "registry trouble"}}))
        sys.exit(1)
    spec = args[1]
    name, version = (spec.rsplit("@", 1) if spec.count("@") > spec.startswith("@") else (spec, ""))
    if version and version not in registry["versions"]:
        print(json.dumps({"error": {"code": "E404", "summary": f"No match found for version {version}"}}))
        sys.exit(1)
    out = {"versions": registry["versions"], "dist-tags": {"latest": registry["latest"]}}
    if version in registry.get("deprecated", []):
        out["deprecated"] = "use a newer version"
    print(json.dumps(out))
    sys.exit(0)
if args[:2] == ["audit", "signatures"]:
    print(os.environ.get("FAKE_NPM_AUDIT", "not json"))
    sys.exit(0)
if args[:2] == ["install", "-g"]:
    if os.environ.get("FAKE_NPM_FAIL"):
        sys.stderr.write("npm error code E500\n")
        sys.exit(1)
    package, version = args[2].rsplit("@", 1)
    main = root / Path(*package.split("/"))
    platform = main / "node_modules" / Path(*os.environ["FAKE_NPM_PLATFORM"].split("/"))
    for folder in (main, platform):
        folder.mkdir(parents=True, exist_ok=True)
    (main / "package.json").write_text(json.dumps({"name": package, "version": version,
                                                   "bin": {"sample-cli": "bin/sample-cli.js"}}), encoding="utf-8")
    (main / "bin").mkdir(exist_ok=True)
    (main / "bin" / "sample-cli.js").write_text("// launcher\n", encoding="utf-8")
    skill = main / "skills" / "sample-cli"
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(f"---\nname: sample-cli\nmetadata:\n  version: {version}\n---\n", encoding="utf-8")
    (platform / "bin").mkdir(exist_ok=True)
    (platform / "package.json").write_text(json.dumps({"name": os.environ["FAKE_NPM_PLATFORM"], "version": version}),
                                           encoding="utf-8")
    wrong = dict(item.split("=") for item in os.environ.get("FAKE_NPM_WRONG", "").split(",") if item)
    program = platform / "bin" / ("sample-cli.exe" if windows else "sample-cli")
    program.write_text("import json\nprint(json.dumps({'ok': True, 'data': {'tool': 'sample-cli', 'version': %r}}))\n"
                       % wrong.get(version, version), encoding="utf-8")
    if windows:
        for name in ("sample-cli.cmd", "sample-cli.ps1", "sample-cli"):
            (prefix / name).write_text("npm launcher shim\n", encoding="utf-8")
    else:
        (prefix / "bin").mkdir(exist_ok=True)
        entry = prefix / "bin" / "sample-cli"
        if entry.is_symlink() or entry.exists():
            entry.unlink()
        os.symlink(os.path.relpath(main / "bin" / "sample-cli.js", entry.parent), entry)
    sys.exit(0)
sys.stderr.write("unexpected npm call\n")
sys.exit(2)
'''


class UpdateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="update-test-"))
        self.prefix = self.tmp / "npm-prefix"
        self.prefix.mkdir()
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.state = self.tmp / "state"
        self.log = self.tmp / "npm.log"
        self.log.write_text("", encoding="utf-8")
        self.registry = self.tmp / "registry.json"
        self.publish(["0.1.0"], "0.1.0")
        script = self.tmp / "fake_npm.py"
        script.write_text(FAKE_NPM, encoding="utf-8")
        self.env = {
            "PATH": os.environ.get("PATH", ""), "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "SAMPLE_CLI_STATE_DIR": str(self.state), "HOME": str(self.home), "USERPROFILE": str(self.home),
            "FAKE_NPM_LOG": str(self.log), "FAKE_NPM_PREFIX": str(self.prefix), "FAKE_NPM_PLATFORM": PLATFORM,
            "FAKE_NPM_REGISTRY": str(self.registry),
        }
        self.patches = [mock.patch.object(update, "find_npm", lambda env: [sys.executable, str(script)]),
                        mock.patch.object(update, "RUNNER", [sys.executable])]
        for patch in self.patches:
            patch.start()
        self.tool = build()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -------------------------------------------------------------- helpers

    def call(self, *args, **env):
        out = io.StringIO()
        code = self.tool.run(["update", *args], {**self.env, **env}, out)
        envelope = json.loads(out.getvalue())
        self.assertEqual(schemas.errors(envelope, "envelope.schema.json"), [], envelope)
        if envelope["ok"]:
            self.assertEqual(schemas.errors(envelope["data"], "update.schema.json"), [], envelope)
        return code, envelope

    def installs(self):
        calls = [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]
        return [c[2] for c in calls if c[:2] == INSTALL]

    def publish(self, versions, latest, **extra):
        self.registry.write_text(json.dumps({"versions": versions, "latest": latest, **extra}), encoding="utf-8")

    def install_skill(self, folder, text="old copy\n"):
        skill = self.home / folder / "sample-cli"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(text, encoding="utf-8")
        return skill

    def audit(self, *names, invalid=()):
        verified = [{"name": n, "version": "0.2.0", "attestations": {"provenance": {}}} for n in names]
        return json.dumps({"invalid": [{"name": n, "code": "EATTESTATIONVERIFY"} for n in invalid], "missing": [],
                           "verified": verified})

    @property
    def root(self):
        return self.prefix / "node_modules" if WINDOWS else self.prefix / "lib" / "node_modules"

    @property
    def program(self):
        return self.root / PACKAGE / "node_modules" / PLATFORM / "bin" / ("sample-cli.exe" if WINDOWS else "sample-cli")

    def old_install(self, *extra_files):
        self.program.parent.mkdir(parents=True)
        self.program.write_text("old program\n", encoding="utf-8")
        for name in extra_files:
            (self.program.parent / name).write_text(f"old {name}\n", encoding="utf-8")
        return self.program

    def trash(self):
        dirs = (self.state / "trash", self.root / ".sample-cli-trash")
        return [p for d in dirs if d.is_dir() for p in d.rglob("*") if p.is_file()]

    # -------------------------------------------------------------- choosing the version (DCLI-071)

    def test_check_reports_a_newer_version_and_installs_nothing(self):
        self.publish(["0.1.0", "0.2.0"], "0.2.0")
        code, env = self.call("--check")
        self.assertEqual(code, 0)
        self.assertEqual((env["data"]["status"], env["data"]["update_available"], env["data"]["target_version"]),
                         ("available", True, "0.2.0"))
        self.assertEqual(self.installs(), [])
        cache = json.loads((self.state / "cache" / "update.json").read_text(encoding="utf-8"))
        self.assertEqual(cache["latest"], "0.2.0")

    def test_check_when_current(self):
        code, env = self.call("--check")
        self.assertEqual((code, env["data"]["status"], env["data"]["update_available"]), (0, "up_to_date", False))

    def test_versions_are_validated(self):
        for args in (["--target-version", "1.x"], ["--target-version", "1.0.0;rm -rf /"], ["--target-version", "1.0.0\n"],
                     ["--allow-downgrade"], ["--check", "--target-version", "0.1.0", "--allow-downgrade"]):
            code, env = self.call(*args)
            self.assertEqual(env["error"]["code"], "E_USAGE", args)
        self.assertEqual(self.installs(), [])

    def test_unpublished_target_and_invalid_registry_versions(self):
        self.publish(["0.1.0", "0.3.0", "0.4.0\n", "nope"], "not-a-version")
        code, env = self.call("--target-version", "0.2.0")
        self.assertEqual(env["error"]["code"], "E_USAGE")
        code, env = self.call("--check")
        self.assertEqual(env["data"]["target_version"], "0.3.0")

    def test_downgrade_needs_both_flags(self):
        self.publish(["0.0.9", "0.1.0"], "0.1.0")
        code, env = self.call("--target-version", "0.0.9")
        self.assertEqual(env["error"]["code"], "E_USAGE")
        self.assertEqual(self.installs(), [])
        code, env = self.call("--target-version", "0.0.9", "--allow-downgrade", FAKE_NPM_AUDIT="{}")
        self.assertEqual(code, 0, env)
        self.assertEqual(env["data"]["current_version"], "0.0.9")
        self.assertEqual(self.installs(), [f"{PACKAGE}@0.0.9"])

    def test_a_version_newer_than_latest_stays(self):
        self.tool.version = "0.3.0-rc.1"
        self.publish(["0.1.0", "0.2.0", "0.3.0-rc.1"], "0.2.0")
        code, env = self.call()
        self.assertEqual((code, env["data"]["status"], env["data"]["target_version"]), (0, "up_to_date", "0.3.0-rc.1"))
        self.assertEqual(self.installs(), [])

    # -------------------------------------------------------------- failures (DCLI-078)

    def test_registry_failures(self):
        for error, code, retryable in (("ETIMEDOUT", "E_NETWORK", True), ("E429", "E_NETWORK", True),
                                       ("E404", "E_CONFIG", False), ("E401", "E_CONFIG", False)):
            self.publish([], None, error=error)
            _, env = self.call()
            self.assertEqual((env["error"]["code"], env["error"]["retryable"]), (code, retryable), error)
        self.assertEqual(env["error"]["details"]["dispatch_state"], "not_started")

    def test_npm_is_found_on_path_only(self):
        planted = self.tmp / "work"
        planted.mkdir()
        for name in ("npm", "npm.cmd", "npm.exe"):
            (planted / name).write_text("planted\n", encoding="utf-8")
            os.chmod(planted / name, 0o755)
        empty = self.tmp / "empty"
        empty.mkdir()
        old = os.getcwd()
        os.chdir(planted)
        self.patches[0].stop()
        try:
            # Neither a relative PATH entry nor the current directory counts, not even through a link.
            self.assertIsNone(update.find_npm({"PATH": f"{empty}{os.pathsep}.{os.pathsep}{planted}"}))
            link = self.tmp / "link-to-work"
            try:
                os.symlink(planted, link, target_is_directory=True)
            except OSError:
                link = None  # symbolic links need a privilege on some Windows machines
            if link is not None:
                self.assertIsNone(update.find_npm({"PATH": str(link)}))
            code, env = self.call(PATH=str(empty))
        finally:
            self.patches[0].start()
            os.chdir(old)
        self.assertEqual(env["error"]["code"], "E_CONFIG")

    def test_install_failure_keeps_the_old_program(self):
        self.publish(["0.1.0", "0.2.0"], "0.2.0")
        self.old_install("python3.dll")
        with mock.patch.object(update, "MOVE_ASIDE", True):
            code, env = self.call(FAKE_NPM_FAIL="1")
        self.assertEqual(env["error"]["code"], "E_IO")
        self.assertIn(f"npm install -g {PACKAGE}@0.2.0", env["error"]["details"]["install_command"])
        self.assertEqual(self.program.read_text(encoding="utf-8"), "old program\n")
        self.assertTrue((self.program.parent / "python3.dll").is_file())

    def test_wrong_version_after_install_puts_the_old_version_back(self):
        self.publish(["0.1.0", "0.2.0"], "0.2.0")
        self.old_install()
        with mock.patch.object(update, "MOVE_ASIDE", True):
            code, env = self.call(FAKE_NPM_WRONG="0.2.0=0.1.5")
        self.assertEqual(env["error"]["code"], "E_IO")
        self.assertIn("0.1.5", env["error"]["message"])
        self.assertEqual(env["error"]["details"]["current_version"], "0.1.0")
        self.assertEqual(self.installs(), [f"{PACKAGE}@0.2.0", f"{PACKAGE}@0.1.0"])
        self.assertIn("'0.1.0'", self.program.read_text(encoding="utf-8"))

    def test_wrong_version_of_an_unpublished_build_puts_the_moved_program_back(self):
        self.tool.version = "0.1.1"  # a development build, not in the registry
        self.publish(["0.1.0", "0.2.0"], "0.2.0")
        self.old_install()
        real = update.Install.npm_install

        def install_without_program(install, version):
            failure = real(install, version)
            shutil.rmtree(install.platform_dir)  # the platform package was left out
            return failure

        with mock.patch.object(update, "MOVE_ASIDE", True), mock.patch.object(update.Install, "npm_install", install_without_program):
            code, env = self.call()
        self.assertEqual(env["error"]["code"], "E_IO")
        self.assertEqual(self.program.read_text(encoding="utf-8"), "old program\n")

    def test_running_program_not_movable(self):
        self.publish(["0.1.0", "0.2.0"], "0.2.0")
        self.old_install()
        with mock.patch.object(update, "MOVE_ASIDE", True), mock.patch.object(update.os, "rename", side_effect=PermissionError("in use")):
            code, env = self.call()
        self.assertEqual(env["error"]["code"], "E_IO")
        self.assertEqual(self.installs(), [])

    def test_a_partial_move_aside_is_put_back(self):
        self.publish(["0.1.0", "0.2.0"], "0.2.0")
        self.old_install("a.dll", "b.dll")
        real = os.rename

        def second_fails(src, dst):
            if Path(src).name == "b.dll" and "trash" in str(dst):
                raise PermissionError(13, "in use")
            return real(src, dst)

        with mock.patch.object(update, "MOVE_ASIDE", True), mock.patch.object(update.os, "rename", side_effect=second_fails):
            code, env = self.call()
        self.assertEqual(env["error"]["code"], "E_IO")
        self.assertEqual(sorted(p.name for p in self.program.parent.iterdir()),
                         sorted(["a.dll", "b.dll", self.program.name]))

    def test_trash_on_another_disk_falls_back_to_the_npm_folder(self):
        self.publish(["0.1.0", "0.2.0"], "0.2.0")
        self.old_install()
        real = os.rename

        def cross_disk(src, dst):
            if str(dst).startswith(str(self.state)):
                raise OSError(errno.EXDEV, "cross-device link")
            return real(src, dst)

        with mock.patch.object(update, "MOVE_ASIDE", True), mock.patch.object(update.os, "rename", side_effect=cross_disk):
            code, env = self.call(FAKE_NPM_AUDIT="{}")
        self.assertEqual(code, 0, env)
        self.assertEqual([p.read_text(encoding="utf-8") for p in (self.root / ".sample-cli-trash").rglob("*") if p.is_file()],
                         ["old program\n"])

    # -------------------------------------------------------------- a full update (DCLI-072 to DCLI-077)

    def test_update_installs_checks_provenance_points_entries_and_syncs_skills(self):
        self.publish(["0.1.0", "0.2.0"], "0.2.0")
        self.old_install()
        installed = self.install_skill(".agents/skills")
        elsewhere = self.tmp / "elsewhere" / "sample-cli"
        elsewhere.mkdir(parents=True)
        (elsewhere / "SKILL.md").write_text("linked copy\n", encoding="utf-8")
        linked = self.home / ".claude" / "skills"
        linked.mkdir(parents=True)
        try:
            os.symlink(elsewhere, linked / "sample-cli", target_is_directory=True)
        except OSError:
            linked = None  # symbolic links need a privilege on some Windows machines
        with mock.patch.object(update, "MOVE_ASIDE", True):
            code, env = self.call(FAKE_NPM_AUDIT=self.audit(PACKAGE, PLATFORM))
        self.assertEqual(code, 0, env)
        data = env["data"]
        self.assertEqual((data["status"], data["previous_version"], data["current_version"]), ("updated", "0.1.0", "0.2.0"))
        self.assertEqual((data["entry"], data["provenance_status"], data["skill_sync_status"]), ("direct", "verified", "synced"))
        self.assertFalse(data["update_available"])
        self.assertEqual(self.installs(), [f"{PACKAGE}@0.2.0"])
        self.assertIn("version: 0.2.0", (installed / "SKILL.md").read_text(encoding="utf-8"))
        self.assertFalse((self.home / ".codex" / "skills" / "sample-cli").exists())
        self.assertEqual([p.name for p in installed.parent.iterdir()], ["sample-cli"])
        if linked is not None:
            self.assertTrue((linked / "sample-cli").is_symlink())
            self.assertEqual((elsewhere / "SKILL.md").read_text(encoding="utf-8"), "linked copy\n")
        self.assertEqual([p.read_text(encoding="utf-8") for p in self.trash()], ["old program\n"])
        if WINDOWS:
            program = os.path.relpath(self.program, self.prefix)
            for name in ("sample-cli.cmd", "sample-cli.ps1", "sample-cli"):
                text = (self.prefix / name).read_text(encoding="utf-8")
                self.assertIn(update.ENTRY_MARK, text)
                self.assertIn(program.replace("\\", "/"), text.replace("\\", "/"))
            self.assertIn(b"\r\n", (self.prefix / "sample-cli.cmd").read_bytes())
        else:
            entry = self.prefix / "bin" / "sample-cli"
            self.assertTrue(entry.is_symlink())
            self.assertEqual(entry.resolve(), self.program.resolve())
        # Running it again from the new program is safe: nothing is installed and the trash is emptied.
        self.tool.version = "0.2.0"
        code, env = self.call()
        self.assertEqual((code, env["data"]["status"]), (0, "up_to_date"))
        self.assertEqual(self.trash(), [])
        self.assertEqual(self.installs(), [f"{PACKAGE}@0.2.0"])

    def test_again_at_the_target_version_finishes_entries_and_skills(self):
        self.publish(["0.1.0", "0.2.0"], "0.2.0")
        self.call(FAKE_NPM_AUDIT="{}")
        self.tool.version = "0.2.0"
        # Leave the entries and a Skill as an interrupted update would.
        for name in (["sample-cli.cmd", "sample-cli.ps1", "sample-cli"] if WINDOWS else []):
            (self.prefix / name).write_text("npm launcher shim\n", encoding="utf-8")
        if not WINDOWS:
            entry = self.prefix / "bin" / "sample-cli"
            entry.unlink()
            entry.symlink_to("../lib/node_modules/@tool-driver/sample-cli/bin/sample-cli.js")
        skill = self.install_skill(".gemini/skills")
        aside = self.home / ".cursor" / "skills" / ".sample-cli.old-99"
        aside.mkdir(parents=True)
        (aside / "SKILL.md").write_text("interrupted\n", encoding="utf-8")
        code, env = self.call()
        self.assertEqual(code, 0, env)
        self.assertEqual((env["data"]["status"], env["data"]["entry"], env["data"]["skill_sync_status"]),
                         ("up_to_date", "direct", "synced"))
        self.assertIn("0.2.0", (skill / "SKILL.md").read_text(encoding="utf-8"))
        self.assertIn("0.2.0", (self.home / ".cursor" / "skills" / "sample-cli" / "SKILL.md").read_text(encoding="utf-8"))
        self.assertEqual(self.installs(), [f"{PACKAGE}@0.2.0"])
        code, env = self.call()
        self.assertEqual(env["data"]["skill_sync_status"], "not_needed")

    def test_another_install_on_path_is_reported(self):
        self.publish(["0.1.0", "0.2.0"], "0.2.0")
        other = self.tmp / "other-bin"
        other.mkdir()
        for name in ("sample-cli", "sample-cli.cmd"):
            (other / name).write_text("another install\n", encoding="utf-8")
        mine = self.prefix if WINDOWS else self.prefix / "bin"
        code, env = self.call(PATH=f"{other}{os.pathsep}{mine}", FAKE_NPM_AUDIT="{}")
        self.assertEqual(env["error"]["code"], "E_IO")
        self.assertIn(str(other), env["error"]["message"])

    def test_provenance_outcomes(self):
        self.publish(["0.1.0", "0.2.0"], "0.2.0")
        code, env = self.call(FAKE_NPM_AUDIT="npm error no registry keys")
        self.assertEqual(env["data"]["provenance_status"], "not_checked")
        code, env = self.call(FAKE_NPM_AUDIT=json.dumps({"invalid": [], "missing": []}))
        self.assertEqual(env["data"]["provenance_status"], "not_checked")
        code, env = self.call(FAKE_NPM_AUDIT=self.audit(PACKAGE))
        self.assertEqual(env["error"]["code"], "E_INTEGRITY")
        self.assertIn("no provenance attestation", env["error"]["message"])
        code, env = self.call(FAKE_NPM_AUDIT=self.audit(PACKAGE, invalid=[PLATFORM]))
        self.assertEqual((env["error"]["code"], env["error"]["retryable"]), ("E_INTEGRITY", False))
        self.assertEqual(env["error"]["details"]["current_version"], "0.2.0")

    def test_a_failed_provenance_check_sticks(self):
        self.publish(["0.1.0", "0.2.0"], "0.2.0")
        skill = self.install_skill(".agents/skills")
        code, env = self.call(FAKE_NPM_AUDIT=self.audit(PACKAGE, invalid=[PLATFORM]))
        self.assertEqual(env["error"]["code"], "E_INTEGRITY")
        self.tool.version = "0.2.0"  # the next call comes from the new program
        code, env = self.call()
        self.assertEqual(env["error"]["code"], "E_INTEGRITY")
        self.assertEqual((skill / "SKILL.md").read_text(encoding="utf-8"), "old copy\n")
        if WINDOWS:
            self.assertNotIn(update.ENTRY_MARK, (self.prefix / "sample-cli.cmd").read_text(encoding="utf-8"))

    def test_skill_sync_failure_is_partial_and_leaves_no_copy(self):
        self.publish(["0.1.0", "0.2.0"], "0.2.0")
        skill = self.install_skill(".agents/skills")
        real_replace = os.replace

        def refuse(src, dst):
            if Path(src) == skill:
                raise PermissionError(13, "in use")
            return real_replace(src, dst)

        with mock.patch.object(update.os, "replace", side_effect=refuse):
            code, env = self.call(FAKE_NPM_AUDIT=self.audit(PACKAGE, PLATFORM))
        self.assertEqual(env["error"]["code"], "E_PARTIAL")
        details = env["error"]["details"]["update"]
        self.assertEqual((details["current_version"], details["skill_sync_status"]), ("0.2.0", "failed"))
        self.assertIn("update", env["error"]["details"]["next_action"])
        self.assertEqual((skill / "SKILL.md").read_text(encoding="utf-8"), "old copy\n")
        self.assertEqual([p.name for p in skill.parent.iterdir()], ["sample-cli"])

    def test_host_component_tools_are_told_about_plugin_install(self):
        self.publish(["0.1.0", "0.2.0"], "0.2.0")
        with mock.patch.dict(os.environ, {"SAMPLE_CLI_VARIANT": "host"}):
            self.tool = build()
        code, env = self.call(FAKE_NPM_AUDIT="{}")
        self.assertEqual(code, 0, env)
        self.assertTrue(any("plugin install" in n["message"] for n in env["meta"]["notices"]))

    def test_windows_entries_run_the_program_and_fall_back_to_the_launcher(self):
        cmd, ps1, sh = update._windows_entries("kicad-cli", r"node_modules\kicad-cli\node_modules\kicad-cli-win32-x64\bin\kicad-cli.exe",
                                               r"node_modules\kicad-cli\bin\kicad-cli.js")
        self.assertIn(r'"%dp0%\node_modules\kicad-cli\node_modules\kicad-cli-win32-x64\bin\kicad-cli.exe" %*', cmd)
        self.assertIn(r'node "%dp0%\node_modules\kicad-cli\bin\kicad-cli.js" %*', cmd)
        self.assertIn("exit $LASTEXITCODE", ps1)
        self.assertIn('exec "$basedir/node_modules/kicad-cli/node_modules/kicad-cli-win32-x64/bin/kicad-cli.exe" "$@"', sh)
        self.assertIn('exec node "$basedir/node_modules/kicad-cli/bin/kicad-cli.js" "$@"', sh)

    # -------------------------------------------------------------- doctor and the notices (DCLI-079)

    def doctor_check(self, name):
        out = io.StringIO()
        self.tool.run(["doctor"], self.env, out)
        return next(c for c in json.loads(out.getvalue())["data"]["checks"] if c["check"] == name)

    def test_doctor_compares_the_installed_skills_with_the_cli(self):
        self.assertEqual(self.doctor_check("version")["status"], "warn")
        skill = self.install_skill(".claude/skills", "---\nname: sample-cli\nmetadata:\n  version: 0.1.0\n---\n")
        self.assertEqual(self.doctor_check("version")["status"], "pass")
        (skill / "SKILL.md").write_text("---\nname: sample-cli\nmetadata:\n  version: 0.0.9\n---\n", encoding="utf-8")
        check = self.doctor_check("version")
        self.assertEqual(check["status"], "fail")
        self.assertIn("sample-cli update", check["fix"])

    def test_doctor_waits_at_most_the_contract_time(self):
        self.publish(["0.1.0", "0.2.0"], "0.2.0", sleep=10)
        started = time.monotonic()
        check = self.doctor_check("update")
        self.assertLess(time.monotonic() - started, 9)
        self.assertEqual(check["status"], "warn")
        seen = []
        with mock.patch.object(update, "query", side_effect=lambda run, npm, timeout: seen.append(timeout) or
                               {"versions": [], "latest": None, "deprecated": False}):
            self.doctor_check("update")
        self.assertEqual(seen, [CONTRACT_TIMEOUT])

    def test_only_update_and_doctor_ask_the_registry(self):
        with mock.patch.object(update, "query", side_effect=AssertionError("went online")):
            for args in (["context"], ["reference"], ["changelog"], ["operation", "list"], ["knowledge", "list"]):
                out = io.StringIO()
                self.tool.run(args, self.env, out)
                self.assertTrue(json.loads(out.getvalue())["ok"], args)

    def test_notices_follow_the_version_they_were_given_for(self):
        self.publish(["0.1.0"], "0.1.0", deprecated=["0.1.0"])
        self.assertEqual(self.doctor_check("update")["status"], "warn")
        notices = self.notices()
        self.assertEqual([n["severity"] for n in notices if n["type"] == "update_available"], ["warning"])
        self.tool.version = "0.2.0"  # after updating away from the deprecated version
        cache = json.loads((self.state / "cache" / "update.json").read_text(encoding="utf-8"))
        cache.pop("notified_at", None)
        (self.state / "cache" / "update.json").write_text(json.dumps(cache), encoding="utf-8")
        self.assertEqual([n for n in self.notices() if n["type"] == "update_available"], [])

    def notices(self):
        out = io.StringIO()
        self.tool.run(["context"], self.env, out)
        return json.loads(out.getvalue()).get("meta", {}).get("notices", [])

    def test_doctor_reports_a_host_component_older_than_the_bundled_one(self):
        manifest = self.tmp / "plugin" / "manifest.json"
        manifest.parent.mkdir()
        manifest.write_text(json.dumps({"version": "2.0.0", "protocol_version": "1.0", "files": {}}), encoding="utf-8")
        with mock.patch.dict(os.environ, {"SAMPLE_CLI_VARIANT": "host"}):
            self.tool = build()
        self.tool.plugin_manifest = manifest
        self.assertEqual(builtin.bundled_plugin_version(self.tool), "2.0.0")
        with mock.patch.object(builtin, "_plugin", return_value={"version_on_disk": "1.0.0", "loaded": []}):
            check = self.doctor_check("plugin")
        self.assertEqual(check["status"], "warn")
        self.assertIn("plugin install", check["fix"])


CONTRACT_TIMEOUT = json.loads((REPO / "contract" / "driver-contract.json").read_text(encoding="utf-8"))["update"][
    "doctor_registry_timeout_ms"] / 1000


class Versions(unittest.TestCase):
    def test_semver(self):
        self.assertTrue(update.newer("1.10.0", "1.9.9"))
        self.assertTrue(update.newer("1.0.0", "1.0.0-rc.1"))
        self.assertTrue(update.newer("1.0.0-rc.10", "1.0.0-rc.9"))
        self.assertFalse(update.newer("1.0.0", "1.0.0"))
        for bad in ("1.0", "v1.0.0", "01.0.0", "1.0.0 ", "1.0.0;x", "1.0.0\n"):
            self.assertIsNone(update.semver_key(bad), repr(bad))


if __name__ == "__main__":
    unittest.main()
