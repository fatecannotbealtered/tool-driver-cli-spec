"""Unit tests of ``update`` (DCLI-070 to DCLI-079).

A local HTTP server stands in for the npm registry and a small script for npm. The script
lays out a global install the way npm does, so the tests see the command entries, the
native program, the main package and its Skills where a real install puts them.
"""
from __future__ import annotations

import http.server
import io
import json
import os
import socketserver
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "sdk" / "python"))
sys.path.insert(0, str(REPO / "tests" / "sample"))
sys.path.insert(0, str(REPO / "conformance"))

from _driver import update  # noqa: E402
from sample_cli import build  # noqa: E402
from suites import schemas  # noqa: E402

WINDOWS = os.name == "nt"
PACKAGE = "@tool-driver/sample-cli"
PLATFORM = f"{PACKAGE}-{update._os()}-{update._cpu()}"

FAKE_NPM = r'''
import json, os, sys
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
    reported = os.environ.get("FAKE_NPM_REPORT", version)
    program = platform / "bin" / ("sample-cli.exe" if windows else "sample-cli")
    program.write_text("import json\nprint(json.dumps({'ok': True, 'data': {'tool': 'sample-cli', 'version': %r}}))\n"
                       % reported, encoding="utf-8")
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


def packument(versions, latest, deprecated=()):
    return {"name": PACKAGE, "dist-tags": {"latest": latest},
            "versions": {v: ({"version": v, "deprecated": "old"} if v in deprecated else {"version": v}) for v in versions}}


class Registry:
    """A local stand-in for the npm registry."""

    def __init__(self) -> None:
        self.answer: tuple[int, dict, dict] = (200, packument(["0.1.0"], "0.1.0"), {})
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                status, body, headers = owner.answer
                data = json.dumps(body).encode()
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class UpdateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = Registry()

    @classmethod
    def tearDownClass(cls):
        cls.registry.close()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="update-test-"))
        self.prefix = self.tmp / "npm-prefix"
        self.prefix.mkdir()
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.state = self.tmp / "state"
        self.log = self.tmp / "npm.log"
        self.log.write_text("", encoding="utf-8")
        script = self.tmp / "fake_npm.py"
        script.write_text(FAKE_NPM, encoding="utf-8")
        self.env = {
            "PATH": os.environ.get("PATH", ""), "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "SAMPLE_CLI_STATE_DIR": str(self.state), "npm_config_registry": self.registry.url,
            "HOME": str(self.home), "USERPROFILE": str(self.home), "FAKE_NPM_LOG": str(self.log),
            "FAKE_NPM_PREFIX": str(self.prefix), "FAKE_NPM_PLATFORM": PLATFORM,
        }
        self.patches = [mock.patch.object(update, "find_npm", lambda env: [sys.executable, str(script)]),
                        mock.patch.object(update, "RUNNER", [sys.executable])]
        for patch in self.patches:
            patch.start()
        self.tool = build()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def call(self, *args, **env):
        out = io.StringIO()
        code = self.tool.run(["update", *args], {**self.env, **env}, out)
        envelope = json.loads(out.getvalue())
        self.assertEqual(schemas.errors(envelope, "envelope.schema.json"), [], envelope)
        if envelope["ok"]:
            self.assertEqual(schemas.errors(envelope["data"], "update.schema.json"), [], envelope)
        return code, envelope

    def npm_calls(self):
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def installs(self):
        return [c for c in self.npm_calls() if c[:1] == ["install"]]

    def publish(self, versions, latest, **kw):
        self.registry.answer = (200, packument(versions, latest, **kw), {})

    def install_skill(self, folder, version="0.0.1"):
        skill = self.home / folder / "sample-cli"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"old {version}\n", encoding="utf-8")
        return skill

    def audit(self, *names, invalid=()):
        verified = [{"name": n, "version": "0.2.0", "attestations": {"provenance": {}}} for n in names]
        return json.dumps({"invalid": [{"name": n, "code": "EATTESTATIONVERIFY"} for n in invalid], "missing": [],
                           "verified": verified})

    # -------------------------------------------------------------- choosing the version (DCLI-071)

    def test_check_reports_a_newer_version_and_installs_nothing(self):
        self.publish(["0.1.0", "0.2.0"], "0.2.0")
        code, env = self.call("--check")
        self.assertEqual(code, 0)
        self.assertEqual(env["data"]["status"], "available")
        self.assertTrue(env["data"]["update_available"])
        self.assertEqual(env["data"]["target_version"], "0.2.0")
        self.assertEqual(self.installs(), [])
        cache = json.loads((self.state / "cache" / "update.json").read_text(encoding="utf-8"))
        self.assertEqual(cache["latest"], "0.2.0")

    def test_check_when_current(self):
        self.publish(["0.1.0"], "0.1.0")
        code, env = self.call("--check")
        self.assertEqual((code, env["data"]["status"], env["data"]["update_available"]), (0, "up_to_date", False))

    def test_versions_are_validated(self):
        for args in (["--target-version", "1.x"], ["--target-version", "1.0.0;rm -rf /"], ["--allow-downgrade"],
                     ["--check", "--target-version", "0.1.0", "--allow-downgrade"]):
            code, env = self.call(*args)
            self.assertEqual(env["error"]["code"], "E_USAGE", args)
        self.assertEqual(self.installs(), [])

    def test_unpublished_target_and_invalid_registry_versions(self):
        self.publish(["0.1.0", "0.3.0"], "not-a-version")
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
        self.assertEqual(self.installs(), [["install", "-g", f"{PACKAGE}@0.0.9", "--include=optional", "--no-fund", "--no-audit"]])

    # -------------------------------------------------------------- failures (DCLI-078)

    def test_registry_unreachable(self):
        code, env = self.call(npm_config_registry="http://127.0.0.1:9/")
        self.assertEqual((env["error"]["code"], env["error"]["retryable"]), ("E_NETWORK", True))
        self.registry.answer = (429, {}, {"Retry-After": "7"})
        code, env = self.call()
        self.assertEqual(env["error"]["code"], "E_NETWORK")
        self.assertEqual(env["error"]["details"]["retry_after_ms"], 7000)
        self.registry.answer = (404, {}, {})
        code, env = self.call()
        self.assertEqual(env["error"]["code"], "E_CONFIG")

    def test_npm_is_found_on_path_only(self):
        self.publish(["0.1.0", "0.2.0"], "0.2.0")
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
            # Neither a relative PATH entry nor the current directory counts.
            self.assertIsNone(update.find_npm({"PATH": f"{empty}{os.pathsep}.{os.pathsep}{planted}"}))
            code, env = self.call(PATH=str(empty))
        finally:
            self.patches[0].start()
            os.chdir(old)
        self.assertEqual(env["error"]["code"], "E_CONFIG")

    def test_install_failure_keeps_the_old_program(self):
        self.publish(["0.1.0", "0.2.0"], "0.2.0")
        old = self.old_install()
        with mock.patch.object(update, "MOVE_ASIDE", True):
            code, env = self.call(FAKE_NPM_FAIL="1")
        self.assertEqual(env["error"]["code"], "E_IO")
        self.assertIn(f"npm install -g {PACKAGE}@0.2.0", env["error"]["details"]["install_command"])
        self.assertEqual(old.read_text(encoding="utf-8"), "old program\n")

    def test_wrong_version_after_install(self):
        self.publish(["0.1.0", "0.2.0"], "0.2.0")
        code, env = self.call(FAKE_NPM_REPORT="0.1.5")
        self.assertEqual(env["error"]["code"], "E_IO")
        self.assertIn("0.1.5", env["error"]["message"])

    def test_running_program_not_movable(self):
        self.publish(["0.1.0", "0.2.0"], "0.2.0")
        self.old_install()
        with mock.patch.object(update, "MOVE_ASIDE", True), mock.patch.object(update.os, "rename", side_effect=PermissionError("in use")):
            code, env = self.call()
        self.assertEqual(env["error"]["code"], "E_IO")
        self.assertEqual(self.installs(), [])

    # -------------------------------------------------------------- a full update (DCLI-072 to DCLI-077)

    def old_install(self):
        root = self.prefix / "node_modules" if WINDOWS else self.prefix / "lib" / "node_modules"
        program = root / PACKAGE / "node_modules" / PLATFORM / "bin" / ("sample-cli.exe" if WINDOWS else "sample-cli")
        program.parent.mkdir(parents=True)
        program.write_text("old program\n", encoding="utf-8")
        return program

    def test_update_installs_points_entries_checks_provenance_and_syncs_skills(self):
        self.publish(["0.1.0", "0.2.0"], "0.2.0")
        self.old_install()
        installed = self.install_skill(".agents/skills")
        linked = self.home / ".claude" / "skills"
        linked.mkdir(parents=True)
        try:
            os.symlink(installed, linked / "sample-cli", target_is_directory=True)
        except OSError:
            linked = None  # symbolic links need a privilege on some Windows machines
        with mock.patch.object(update, "MOVE_ASIDE", True):
            code, env = self.call(FAKE_NPM_AUDIT=self.audit(PACKAGE, PLATFORM))
        self.assertEqual(code, 0, env)
        data = env["data"]
        self.assertEqual((data["status"], data["previous_version"], data["current_version"]), ("updated", "0.1.0", "0.2.0"))
        self.assertEqual((data["entry"], data["provenance_status"], data["skill_sync_status"]), ("direct", "verified", "synced"))
        self.assertFalse(data["update_available"])
        self.assertEqual(self.installs(), [["install", "-g", f"{PACKAGE}@0.2.0", "--include=optional", "--no-fund", "--no-audit"]])
        self.assertIn("version: 0.2.0", (installed / "SKILL.md").read_text(encoding="utf-8"))
        self.assertFalse((self.home / ".codex" / "skills" / "sample-cli").exists())
        if linked is not None:
            self.assertTrue((linked / "sample-cli").is_symlink())
        trash = [p for p in (self.state / "trash").rglob("*") if p.is_file()]
        self.assertEqual([p.read_text(encoding="utf-8") for p in trash], ["old program\n"])
        if WINDOWS:
            program = os.path.relpath(self.prefix / "node_modules" / PACKAGE / "node_modules" / PLATFORM / "bin" / "sample-cli.exe",
                                      self.prefix)
            for name in ("sample-cli.cmd", "sample-cli.ps1", "sample-cli"):
                text = (self.prefix / name).read_text(encoding="utf-8")
                self.assertIn(update.ENTRY_MARK, text)
                self.assertIn(program.replace("\\", "/"), text.replace("\\", "/"))
                self.assertIn("bin", text)
            self.assertIn(b"\r\n", (self.prefix / "sample-cli.cmd").read_bytes())
        else:
            entry = self.prefix / "bin" / "sample-cli"
            self.assertTrue(entry.is_symlink())
            self.assertTrue(str(entry.resolve()).endswith(os.path.join("bin", "sample-cli")))
            self.assertIn("node_modules", os.readlink(entry))
        # Running it again is safe: nothing to install, the trash is emptied, nothing changes.
        code, env = self.call()
        self.assertEqual(code, 0, env)

    def test_again_at_the_target_version_finishes_entries_and_skills(self):
        self.publish(["0.1.0"], "0.1.0")
        self.call("--target-version", "0.1.0")  # nothing installed yet: launcher entry, no Skills
        self.publish(["0.1.0", "0.2.0"], "0.2.0")
        self.call()
        # Leave the entries and a Skill as an interrupted update would.
        self.tool.version = "0.2.0"
        for name in (["sample-cli.cmd", "sample-cli.ps1", "sample-cli"] if WINDOWS else []):
            (self.prefix / name).write_text("npm launcher shim\n", encoding="utf-8")
        if not WINDOWS:
            entry = self.prefix / "bin" / "sample-cli"
            entry.unlink()
            entry.symlink_to("../lib/node_modules/@tool-driver/sample-cli/bin/sample-cli.js")
        skill = self.install_skill(".gemini/skills")
        code, env = self.call()
        self.assertEqual(code, 0, env)
        self.assertEqual((env["data"]["status"], env["data"]["entry"], env["data"]["skill_sync_status"]),
                         ("up_to_date", "direct", "synced"))
        self.assertIn("0.2.0", (skill / "SKILL.md").read_text(encoding="utf-8"))
        self.assertEqual(self.installs()[-1], ["install", "-g", f"{PACKAGE}@0.2.0", "--include=optional", "--no-fund", "--no-audit"])
        code, env = self.call()
        self.assertEqual(env["data"]["skill_sync_status"], "not_needed")

    def test_provenance_outcomes(self):
        self.publish(["0.1.0", "0.2.0"], "0.2.0")
        code, env = self.call(FAKE_NPM_AUDIT="npm error no registry keys")
        self.assertEqual(env["data"]["provenance_status"], "not_checked")
        self.tool.version = "0.1.0"
        code, env = self.call(FAKE_NPM_AUDIT=json.dumps({"invalid": [], "missing": []}))
        self.assertEqual(env["data"]["provenance_status"], "not_checked")
        code, env = self.call(FAKE_NPM_AUDIT=self.audit(PACKAGE, invalid=[PLATFORM]))
        self.assertEqual((env["error"]["code"], env["error"]["retryable"]), ("E_INTEGRITY", False))
        self.assertEqual(env["error"]["details"]["current_version"], "0.2.0")
        code, env = self.call(FAKE_NPM_AUDIT=self.audit(PACKAGE))
        self.assertEqual(env["error"]["code"], "E_INTEGRITY")
        self.assertIn("no provenance attestation", env["error"]["message"])

    def test_skill_sync_failure_is_partial(self):
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
        self.assertEqual((skill / "SKILL.md").read_text(encoding="utf-8"), "old 0.0.1\n")

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

    def test_doctor_compares_the_installed_skills_with_the_cli(self):
        def version_check():
            out = io.StringIO()
            self.tool.run(["doctor"], self.env, out)
            return next(c for c in json.loads(out.getvalue())["data"]["checks"] if c["check"] == "version")

        self.assertEqual(version_check()["status"], "warn")
        skill = self.install_skill(".claude/skills")
        (skill / "SKILL.md").write_text("---\nname: sample-cli\nmetadata:\n  version: 0.1.0\n---\n", encoding="utf-8")
        self.assertEqual(version_check()["status"], "pass")
        (skill / "SKILL.md").write_text("---\nname: sample-cli\nmetadata:\n  version: 0.0.9\n---\n", encoding="utf-8")
        check = version_check()
        self.assertEqual(check["status"], "fail")
        self.assertIn("sample-cli update", check["fix"])


class Versions(unittest.TestCase):
    def test_semver(self):
        self.assertTrue(update.newer("1.10.0", "1.9.9"))
        self.assertTrue(update.newer("1.0.0", "1.0.0-rc.1"))
        self.assertTrue(update.newer("1.0.0-rc.10", "1.0.0-rc.9"))
        self.assertFalse(update.newer("1.0.0", "1.0.0"))
        for bad in ("1.0", "v1.0.0", "01.0.0", "1.0.0 ", "1.0.0;x"):
            self.assertIsNone(update.semver_key(bad), bad)


if __name__ == "__main__":
    unittest.main()
