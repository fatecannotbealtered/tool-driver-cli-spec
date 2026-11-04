#!/usr/bin/env python3
"""Run a behavior matrix on the real application: the matrix runner (DVER-030, DVER-042).

    python scripts/run_matrix.py <project> --command "<path>" --set doc=<file> [--set session=<id>]
        [--set device=<id>] [--set dir=<folder>] [--row normal,busy] [--application-version 10.0.1]

It fills the sample placeholders of each row with the ``--set`` values, runs the rows that
apply (all, or those named with ``--row``; rows marked ``unrunnable`` never run), and writes
one live record to ``docs/evidence/``. Each row then gets its actual result and its ``live:``
evidence reference. A row whose situation needs preparing, such as an open dialog, is run on
its own with ``--row`` after the person has prepared it.

Every file, folder and device a row uses must be listed under Authorized Targets in
``docs/E2E.md`` (DVER-050); otherwise nothing runs. The fake host is never used here.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_project  # noqa: E402

NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def authorized_targets(root: Path) -> list[str]:
    text = check_project.read(root / "docs" / "E2E.md")
    body = next((b for h, _, b in check_project.sections(text) if h == "Authorized Targets"), [])
    return [m.group(1) for line in body if (m := re.match(r"^\s*[-*]\s+`([^`]+)`", line))]


def file_path(target: str) -> Path | None:
    if not target.startswith("file://"):
        return None
    path = unquote(urlparse(target).path)
    if re.match(r"^/[A-Za-z]:", path):
        path = path[1:]
    return Path(path)


def covered(value: str, kind: str, targets: list[str]) -> str | None:
    """The authorized target that covers one placeholder value, or ``None``."""
    if kind == "device":
        return next((t for t in targets if t == f"device:{value}"), None)
    candidate = Path(value).resolve()
    for target in targets:
        base = file_path(target)
        if base is None:
            continue
        base = base.resolve()
        if candidate == base or (target.endswith("/") and candidate.is_relative_to(base)):
            return target
    return None


def mode_of(arguments: list[str]) -> str:
    if "--device" in arguments:
        return "device"
    if "--session" in arguments:
        return "session"
    return "file"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", type=Path)
    parser.add_argument("--command", required=True)
    parser.add_argument("--set", action="append", default=[], metavar="NAME=VALUE")
    parser.add_argument("--row", default="")
    parser.add_argument("--application-version", help="default: the version context reports")
    args = parser.parse_args(argv)
    root = args.project.resolve()
    facts = check_project.gather(root)
    if facts.reference is None:
        raise SystemExit(f"the tool could not run: {facts.tool_error}")
    command = next((c for c in facts.commands if c["path"] == args.command), None)
    if command is None:
        raise SystemExit(f"{args.command!r} is not a command of {facts.tool}")
    matrix_path = root / "tests" / "matrix" / (args.command.replace(" ", "-") + ".json")
    matrix = json.loads(check_project.read(matrix_path))
    values: dict[str, str] = {}
    for item in args.set:
        name, _, value = item.partition("=")
        if f"{{{name}}}" not in facts.contract["sample_placeholders"] or not value:
            raise SystemExit(f"--set takes one of {facts.contract['sample_placeholders']} as name=value, not {item!r}")
        values[name] = value
    targets = authorized_targets(root)
    used = []
    for name, value in values.items():
        if name == "session":
            continue
        target = covered(value, "device" if name == "device" else "file", targets)
        if target is None:
            raise SystemExit(f"{name}={value} is not covered by Authorized Targets in docs/E2E.md; only a person adds targets")
        used.append(target)
    wanted = {r.strip() for r in args.row.split(",") if r.strip()}
    rows = [r for r in matrix["rows"] if r.get("applies") and not r.get("unrunnable") and (not wanted or r["row"] in wanted)]
    if not rows:
        raise SystemExit("no row to run")
    env = {k: v for k, v in os.environ.items() if not k.startswith(facts.prefix + "_FAKE_HOST")}
    secret = {f["name"] for f in command.get("flags", []) if f.get("secret")}
    tool = [sys.executable, "-m", facts.pkg]
    app_version = args.application_version or _context_version(tool, root, env)
    runs = []
    for row in rows:
        arguments = [_fill(a, values) for a in row["arguments"]]
        missing = sorted({m for a in arguments for m in re.findall(r"\{(session|doc|device|dir)\}", a)})
        if missing:
            raise SystemExit(f"row {row['row']} needs --set {', '.join(missing)}")
        proc = subprocess.run(tool + args.command.split(" ") + arguments, cwd=root, env=env, capture_output=True,
                              timeout=300, creationflags=NO_WINDOW)
        try:
            envelope = json.loads(proc.stdout.decode("utf-8").strip().splitlines()[-1])
        except (ValueError, IndexError):
            envelope = {}
        code = (envelope.get("error") or {}).get("code")
        actual = {"exit": proc.returncode, **({"code": code} if proc.returncode and code else {})}
        passed = check_project.same_result(actual, row["expected"])
        shown = [("***" if i > 0 and arguments[i - 1] in secret else a) for i, a in enumerate(arguments)]
        runs.append({"command": args.command, "arguments": shown, "exit": proc.returncode,
                     "result": "pass" if passed else "fail", "matrix_row": row["row"], "mode": mode_of(arguments),
                     "envelope_sha256": hashlib.sha256(proc.stdout.strip()).hexdigest()})
        row["actual"] = actual
        print(f"{row['row']}: {'pass' if passed else 'fail'} (exit {proc.returncode}{', ' + code if code else ''})")
    now = datetime.datetime.now(datetime.timezone.utc)
    name = f"{now.strftime('%Y-%m-%d-%H%M%S')}-{args.command.replace(' ', '-')}.json"
    record = {"kind": "live", "tool": facts.tool, "tool_version": facts.version, "commit": _commit(root),
              "application": {"name": facts.driver.get("application"), "version": app_version}, "os": platform.platform(),
              "platform": {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux"),
              "recorded_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "targets": sorted(set(used)) or targets[:1], "runs": runs}
    folder = root / "docs" / "evidence"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for row in rows:
        row["evidence"] = f"live:docs/evidence/{name}#{row['row']}"
    matrix_path.write_text(json.dumps(matrix, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote docs/evidence/{name} and updated {matrix_path.relative_to(root).as_posix()}.")
    return 0 if all(r["result"] == "pass" for r in runs) else 1


def _fill(argument: str, values: dict[str, str]) -> str:
    for name, value in values.items():
        argument = argument.replace(f"{{{name}}}", value)
    return argument


def _context_version(tool: list[str], root: Path, env: dict[str, str]) -> str:
    proc = subprocess.run(tool + ["context"], cwd=root, env=env, capture_output=True, timeout=120, creationflags=NO_WINDOW)
    try:
        version = json.loads(proc.stdout.decode("utf-8"))["data"]["application"]["version"]
    except (ValueError, KeyError, TypeError):
        version = None
    if not version:
        raise SystemExit("context did not report the application version; pass --application-version")
    return str(version)


def _commit(root: Path) -> str:
    proc = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=root, capture_output=True, text=True,
                          creationflags=NO_WINDOW)
    return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else "0000000"


if __name__ == "__main__":
    sys.exit(main())
