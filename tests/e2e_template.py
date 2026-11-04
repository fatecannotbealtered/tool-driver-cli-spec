#!/usr/bin/env python3
"""End-to-end run of the project template: generate a tool, fill it in, check it, test it,
build it, pack it, deliver it, and update it from one version to the next.

    python tests/e2e_template.py [--modes file,session] [--host-component] [--no-build] [--keep]

Steps:

1. ``instantiate`` a new tool; ``check_project`` must report only the placeholders (DREPO-019)
   and the domain commands still to register.
2. Fill every placeholder and register two commands, as an author would; ``check_project``
   must then pass.
3. The generated project's unit tests and both conformance suites must pass.
4. Unless ``--no-build``: build the native program, pack the npm packages, and run platform
   delivery (``scripts/smoke.py --fake-host``).
5. Unless ``--no-build``: build version 0.2.0 too, serve both versions from a local registry,
   install 0.1.0 into a clean npm prefix and run ``update`` through the command entry of each
   shell: cmd, PowerShell and Git Bash on Windows, sh elsewhere. Each must end at 0.2.0 with a
   direct command entry that passes arguments through unchanged.

It needs Python with requirements-dev.txt of the template (jsonschema, PyInstaller) and npm.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
TOOL, PACKAGE, PKG, PREFIX = "demo-cli", "@tool-driver/demo-cli", "demo_cli", "DEMO_CLI"


def shell_line(shell: list[str], line: str) -> list[str] | str:
    """One command line for a shell. cmd gets the line verbatim: with /s it drops only the
    outer quotes, so the quoting inside reaches the command entry as a person typed it."""
    return f'cmd /d /s /c "{line}"' if shell[0] == "cmd" else shell + [line]


def run(cmd: list[str] | str, cwd: Path, env: dict[str, str] | None = None, check: bool = True, timeout: int = 1200) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, creationflags=NO_WINDOW)
    if check and proc.returncode != 0:
        raise SystemExit(f"FAILED: {cmd if isinstance(cmd, str) else ' '.join(cmd)}\n{proc.stdout[-4000:]}\n{proc.stderr[-4000:]}")
    return proc


def step(title: str) -> None:
    print(f"== {title}", flush=True)


def generate(work: Path, modes: str, host: bool) -> Path:
    project = work / TOOL
    args = [sys.executable, str(REPO / "scripts" / "instantiate.py"), str(project), "--tool", TOOL, "--package", PACKAGE,
            "--application", "FakeApp", "--versions", ">=1.0 <2", "--modes", modes, "--repo", "tool-driver/demo-cli",
            "--author", "The demo authors"]
    if host:
        args.append("--host-component")
    run(args, REPO)
    problems = json.loads(run([sys.executable, str(REPO / "scripts" / "check_project.py"), str(project), "--json"], REPO,
                              check=False).stdout)
    other = [p for p in problems if p["clause"] != "DREPO-019" and not (p["clause"] == "DREPO-061" and p["path"] == "contract/commands.json")]
    if other or not problems:
        raise SystemExit(f"FAILED: right after instantiate, check_project must report only placeholders: {other or 'none'}")
    print(f"   {len(problems)} things to fill in, nothing else")
    return project


COMMANDS = '''"""The domain commands of demo-cli."""
from __future__ import annotations

from typing import Any

PART = {"type": "object", "properties": {"id": {"type": "string"}, "x_mm": {"type": "number"}, "y_mm": {"type": "number"}}}
BOARD = "board: origin at the top-left corner, x right, y down"


def command(path: str, summary: str, effects: list[str], flags: list[dict[str, Any]], example: str, **extra: Any) -> dict[str, Any]:
    writes = effects != ["observe"]
    return {"path": path, "summary": summary, "effects": effects, "modes": ["file", "session"], "target_kind": "part",
            "flags": flags, "untrusted_fields": [], "survey_ids": ["CAP-001"], "irreversible": False, "halt": False,
            "adapter_capabilities": ["read", "preview", "apply", "read_back"] if writes else ["read"],
            "tolerances": extra.get("tolerances", {}), "default_fields": [], "related_knowledge": [],
            "output_schema": PART, "examples": [f"demo-cli {example}"], "maturity": "draft", "evidence": []}


ID = {"name": "--id", "type": "string", "summary": "The reference of the part.", "required": True}
COMMANDS = [
    command("part get", "Read one part.", ["observe"], [ID], "part get --doc board.fake --id R1"),
    command("part move", "Move one part.", ["change"],
            [ID, {"name": "--x", "type": "quantity", "quantity": "length", "summary": "X position.", "coordinate_system": BOARD},
             {"name": "--y", "type": "quantity", "quantity": "length", "summary": "Y position.", "coordinate_system": BOARD}],
            "part move --doc board.fake --id R1 --x 12.5mm --y 30mm", tolerances={"x_mm": 0.001, "y_mm": 0.001}),
]
'''
SAMPLES = {"part get": ["--session", "{session}", "--doc", "{doc}", "--id", "R1"],
           "part move": ["--session", "{session}", "--doc", "{doc}", "--id", "R1", "--x", "12.5mm", "--y", "30mm"]}


def register(project: Path) -> None:
    """Step 4 of onboarding: two domain commands, each with its behavior matrix."""
    (project / PKG / "commands" / "__init__.py").write_text(COMMANDS, encoding="utf-8", newline="\n")
    for path, sample in SAMPLES.items():
        rows = [{"row": "normal", "applies": True, "arguments": sample, "expected": {"exit": 0}}]
        rows += [{"row": r, "applies": False, "reason": "The demo tool drives no real application."}
                 for r in ["empty", "invalid_input", "not_found", "ambiguous", "conflict", "no_scope", "busy", "dialog",
                           "disconnect", "unsaved", "read_back_mismatch"]]
        matrix = project / "tests" / "matrix" / f"{path.replace(' ', '-')}.json"
        matrix.write_text(json.dumps({"command": path, "rows": rows}, indent=2) + "\n", encoding="utf-8", newline="\n")
    for name in ("docs/APPLICATION.md", "docs/APPLICATION_zh.md"):
        survey = project / name
        text = survey.read_text(encoding="utf-8")
        text = re.sub(r"\| CAP-001 \|[^\n]*", "| CAP-001 | Move parts | The automation API | provided | - |", text)
        survey.write_text(text, encoding="utf-8", newline="\n")


def fill(project: Path) -> None:
    pattern = re.compile(r"\{\{fill:[^}]*\}\}")
    for path in project.rglob("*"):
        if not path.is_file() or ".git" in path.parts or "_driver" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if pattern.search(text):
            path.write_text(pattern.sub("Filled in by the author", text), encoding="utf-8", newline="\n")
    run([sys.executable, str(REPO / "scripts" / "check_project.py"), str(project), "--fix"], REPO, check=False)
    proc = run([sys.executable, str(REPO / "scripts" / "check_project.py"), str(project)], REPO, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"FAILED: after filling the placeholders, check_project still reports:\n{proc.stdout}")


def build(project: Path, env: dict[str, str]) -> None:
    run([sys.executable, "scripts/build.py"], project, env)
    run([sys.executable, "scripts/pack.py"], project, env)


def bump(project: Path, version: str) -> None:
    package = json.loads((project / "package.json").read_text(encoding="utf-8"))
    old = package["version"]
    package["version"] = version
    package["optionalDependencies"] = {k: version for k in package["optionalDependencies"]}
    (project / "package.json").write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8", newline="\n")
    pyproject = project / "pyproject.toml"
    pyproject.write_text(pyproject.read_text(encoding="utf-8").replace(f'version = "{old}"', f'version = "{version}"'),
                         encoding="utf-8", newline="\n")
    for skill in project.glob("skills/*/SKILL.md"):
        skill.write_text(skill.read_text(encoding="utf-8").replace(f"version: {old}", f"version: {version}"),
                         encoding="utf-8", newline="\n")


def shells() -> list[tuple[str, list[str]]]:
    """How each shell runs a command line that finds the tool on PATH."""
    if os.name != "nt":
        return [("sh", ["sh", "-c"])]
    out = [("cmd", ["cmd", "/d", "/c"]), ("powershell", ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"])]
    git = shutil.which("git")
    bash = None
    for root in Path(git).resolve().parents if git else []:  # git.exe sits in cmd\ or mingw64\bin\ of Git for Windows
        bash = next((p for p in (root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe") if p.is_file()), None)
        if bash:
            break
    if bash is None:
        raise SystemExit("FAILED: Git Bash was not found; it is one of the three Windows shells to test")
    out.append(("git-bash", [str(bash), "-c"]))
    return out


def envelope(text: str) -> dict:
    try:
        return json.loads(text.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {}


def update_in_shells(project: Path, old: Path, work: Path, env: dict[str, str]) -> None:
    sys.path.insert(0, str(project / "scripts"))
    from smoke import Registry, tarballs  # the delivery script's local registry

    files_old = tarballs(json.loads((old / "package.json").read_text(encoding="utf-8")))
    files_new = tarballs(json.loads((project / "package.json").read_text(encoding="utf-8")))
    registry = Registry()
    registry.add(files_new, "0.2.0")
    registry.add(files_old, "0.1.0", latest=False)
    try:
        for name, prefix_cmd in shells():
            step(f"update 0.1.0 -> 0.2.0 in {name}")
            base = work / f"shell-{name}"
            prefix = base / "prefix"
            state = base / "state"
            if name == "cmd" and os.name == "nt" and Path(REPO.anchor) != Path(str(base)[:3]):
                state = REPO / "build" / "e2e-state-cmd"  # a state directory on another disk than npm
                shutil.rmtree(state, ignore_errors=True)
            bin_dir = prefix if os.name == "nt" else prefix / "bin"
            shell_env = {**{k: v for k, v in env.items() if not k.lower().startswith("npm_config_")},
                         "npm_config_prefix": str(prefix), "npm_config_registry": registry.url,
                         "npm_config_cache": str(base / "cache"), "npm_config_update_notifier": "false",
                         "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}", f"{PREFIX}_STATE_DIR": str(state),
                         "HOME": str(base / "home"), "USERPROFILE": str(base / "home")}
            skills = base / "home" / ".agents" / "skills" / TOOL
            skills.mkdir(parents=True)
            (skills / "SKILL.md").write_text("old copy\n", encoding="utf-8")
            npm = shutil.which("npm")
            run([npm, "install", "-g", f"{PACKAGE}@0.1.0", "--no-fund", "--no-audit"], base, shell_env)
            before = _timed(prefix_cmd, f"{TOOL} --version", base, shell_env)
            proc = run(shell_line(prefix_cmd, f"{TOOL} update"), base, shell_env, check=False)
            data = envelope(proc.stdout).get("data") or {}
            if (data.get("status"), data.get("previous_version"), data.get("current_version"), data.get("entry")) != \
                    ("updated", "0.1.0", "0.2.0", "direct"):
                raise SystemExit(f"FAILED in {name}: update returned {proc.returncode}\n{proc.stdout[-3000:]}\n{proc.stderr[-2000:]}")
            if "version: 0.2.0" not in (skills / "SKILL.md").read_text(encoding="utf-8"):
                raise SystemExit(f"FAILED in {name}: the installed Skill was not synced")
            trash_dirs = (state / "trash", prefix / ("node_modules" if os.name == "nt" else "lib/node_modules") / f".{TOOL}-trash")
            moved = [p for d in trash_dirs if d.is_dir() for p in d.rglob("*") if p.is_file()]
            if os.name == "nt" and not moved:
                raise SystemExit(f"FAILED in {name}: the running program was not moved aside before npm ran")
            after = _timed(prefix_cmd, f"{TOOL} --version", base, shell_env)
            version = envelope(after[1]).get("data", {}).get("version")
            if version != "0.2.0":
                raise SystemExit(f"FAILED in {name}: after update the entry runs version {version}")
            quoted = run(shell_line(prefix_cmd, f'{TOOL} reference --command "not a command 中文"'), base, shell_env, check=False)
            message = (envelope(quoted.stdout).get("error") or {}).get("message", "")
            if "'not a command 中文'" not in message:
                raise SystemExit(f"FAILED in {name}: an argument with spaces and Chinese did not arrive intact: {quoted.stdout[-800:]}")
            again = envelope(run(shell_line(prefix_cmd, f"{TOOL} update"), base, shell_env, check=False).stdout).get("data") or {}
            if again.get("status") != "up_to_date":
                raise SystemExit(f"FAILED in {name}: a second update is not up_to_date: {again}")
            trash = [p for d in trash_dirs if d.is_dir() for p in d.rglob("*") if p.is_file()]
            if trash:
                raise SystemExit(f"FAILED in {name}: the second update left {len(trash)} files in the trash")
            if state.is_relative_to(REPO):
                shutil.rmtree(state, ignore_errors=True)
            print(f"   updated, entry direct, Skill synced; --version {before[0]:.2f}s through the launcher, "
                  f"{after[0]:.2f}s direct")
    finally:
        registry.close()


def _timed(prefix_cmd: list[str], line: str, cwd: Path, env: dict[str, str]) -> tuple[float, str]:
    best = None
    out = ""
    for _ in range(3):
        started = time.perf_counter()
        proc = run(shell_line(prefix_cmd, line), cwd, env, check=False)
        took = time.perf_counter() - started
        best = took if best is None else min(best, took)
        out = proc.stdout
    return best or 0.0, out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--modes", default="file,session")
    parser.add_argument("--host-component", action="store_true")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--resume", type=Path, help="a work directory kept by --keep: build 0.2.0 again and test update")
    args = parser.parse_args()
    work = args.resume or Path(tempfile.mkdtemp(prefix="e2e-template-"))
    env = {**os.environ, "TOOL_DRIVER_SPEC": str(REPO)}
    if args.resume:
        project = work / TOOL
        bump(project, "0.2.0")
        build(project, env)
        for folder in work.glob("shell-*"):
            shutil.rmtree(folder, ignore_errors=True)
        update_in_shells(project, work / "demo-0.1.0", work, env)
        print("OK: the template works end to end.")
        return 0
    try:
        step("instantiate")
        project = generate(work, args.modes, args.host_component)
        step("register commands, fill the placeholders and check")
        register(project)
        fill(project)
        step("lint and unit tests of the generated project")
        run([sys.executable, "-m", "ruff", "check", "."], project, env)
        run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], project, env)
        step("conformance suites")
        print("   " + run([sys.executable, "scripts/spec.py", "suites"], project, env).stdout.strip().splitlines()[-1])
        if args.no_build:
            return 0
        step("build, pack and platform delivery of 0.1.0")
        build(project, env)
        run([sys.executable, "scripts/smoke.py", "--fake-host"], project, env)
        old = work / "demo-0.1.0"
        shutil.copytree(project, old, ignore=shutil.ignore_patterns("build"))
        step("build and pack 0.2.0")
        bump(project, "0.2.0")
        build(project, env)
        update_in_shells(project, old, work, env)
        print("OK: the template works end to end.")
        return 0
    finally:
        if args.keep:
            print(f"kept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
