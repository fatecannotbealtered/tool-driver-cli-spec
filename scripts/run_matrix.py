#!/usr/bin/env python3
"""Run a behavior matrix on the real application: the matrix runner (DVER-030, DVER-042).

    python scripts/run_matrix.py <project> --command "<path>" --set doc=<file> [--set session=<id>]
        [--set device=<id>] [--set dir=<folder>] [--row normal,busy] [--mode session]
        [--kind part] [--pause 120] [--tamper "<command>"] [--application-version 10.0.1]

It fills the sample placeholders of each row with the ``--set`` values, runs the rows that
apply (all, or those named with ``--row``; rows marked ``unrunnable`` never run), and writes
one live record to ``docs/evidence/``. Each row then gets its actual result and its ``live:``
evidence reference. A row whose situation needs preparing, such as an open dialog, is run on
its own with ``--row`` after the person has prepared it.

``--kind`` names the kind of the document a run uses; a command that lists ``doc_kinds`` needs
it, and its ``normal`` row must pass on every kind (DVER-030). The ``read_back_mismatch`` row
makes the tool wait before its read-back for up to ``--pause`` seconds: during the wait a
person changes what was just written in the application, or ``--tamper`` runs a command that
does, with ``TOOL_DRIVER_PAUSE_FILE`` naming the tool's ``pause.json``. The run is marked
``tampered``. The ``normal`` row of a command registered with ``verify_after_save`` is followed
by ``doc save`` on the same document, and passes only when that save verified the change.

Every file, folder and device a run uses, through ``--set`` or written in a row, must be listed
under Authorized Targets in ``docs/E2E.md`` (DVER-050); otherwise nothing runs. The fake host is
never used, and a simulated result never counts as a pass (DVER-021).
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
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_project  # noqa: E402

NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
PLATFORMS = {"win32": "windows", "darwin": "macos", "linux": "linux"}
TIMEOUT_S = 300


def target_of(name: str, value: str) -> str:
    """The target key of one placeholder value, as the scope file and Authorized Targets write it."""
    if name == "device":
        return f"device:{value}"
    return Path(value).resolve().as_uri() + ("/" if name == "dir" else "")


def covered(target: str, authorized: list[str]) -> str | None:
    return next((a for a in authorized if check_project.target_covered(target, a)), None)


def path_like(value: str) -> bool:
    return bool(re.search(r"[\\/]|^[A-Za-z]:|^\.{1,2}$|\.[A-Za-z0-9]{1,8}$", value))


def mode_of(command: dict[str, Any], arguments: list[str], chosen: str | None) -> str:
    modes = command.get("modes", [])
    if chosen:
        if chosen not in modes:
            raise SystemExit(f"`{command['path']}` has no {chosen} mode; it has {', '.join(modes)}")
        return chosen
    if any(a == "--session" or a.startswith("--session=") for a in arguments):
        return "session"
    if any(a == "--device" or a.startswith("--device=") for a in arguments):
        return "device"
    if len(modes) == 1:
        return modes[0]
    raise SystemExit(f"cannot tell the mode of a row of `{command['path']}` from its arguments; pass --mode")


def simulated(value: Any) -> bool:
    if isinstance(value, dict):
        return value.get("simulated") is True or any(simulated(v) for v in value.values())
    if isinstance(value, list):
        return any(simulated(v) for v in value)
    return False


def pairs(arguments: list[str]) -> list[tuple[str, str]]:
    """(flag, value) for every flag that has a value, in both ``--flag value`` and ``--flag=value``."""
    out = []
    for i, argument in enumerate(arguments):
        if argument.startswith("--") and "=" in argument:
            flag, _, value = argument.partition("=")
            out.append((flag, value))
        elif argument.startswith("--") and i + 1 < len(arguments) and not arguments[i + 1].startswith("--"):
            out.append((argument, arguments[i + 1]))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", type=Path)
    parser.add_argument("--command", required=True)
    parser.add_argument("--set", action="append", default=[], metavar="NAME=VALUE")
    parser.add_argument("--row", default="")
    parser.add_argument("--mode", choices=["file", "session", "device"])
    parser.add_argument("--kind", help="the kind of the document, for a command that lists doc_kinds")
    parser.add_argument("--pause", type=int, default=120, help="seconds the tool waits before the read-back in read_back_mismatch")
    parser.add_argument("--tamper", help="a command that changes the written result while the tool waits")
    parser.add_argument("--application-version", help="default: the version context reports")
    args = parser.parse_args(argv)
    root = args.project.resolve()
    if PLATFORMS.get(sys.platform) is None:
        raise SystemExit(f"live records name windows, macos or linux; this is {sys.platform}")
    commit = _commit(root)
    if commit is None:
        raise SystemExit("live records name the exact build; run from a git checkout of the tool")
    facts = check_project.gather(root)
    if facts.reference is None:
        raise SystemExit(f"the tool could not run: {facts.tool_error}")
    command = next((c for c in facts.commands if c["path"] == args.command), None)
    if command is None:
        raise SystemExit(f"{args.command!r} is not a command of {facts.tool}")
    kinds = command.get("doc_kinds") or []
    if kinds and args.kind not in kinds:
        raise SystemExit(f"`{args.command}` works on {', '.join(kinds)}; name the kind of the document with --kind")
    if args.kind and not kinds:
        raise SystemExit(f"`{args.command}` lists no document kinds; leave out --kind")
    matrix_path = root / "tests" / "matrix" / (args.command.replace(" ", "-") + ".json")
    matrix = json.loads(check_project.read(matrix_path))
    problems = check_project.Checker(facts).validate(matrix, "behavior-matrix.schema.json")
    if problems:
        raise SystemExit(f"{matrix_path.name} does not validate: {problems[0]}")

    authorized = check_project.authorized_targets(root)
    if not authorized:
        raise SystemExit("docs/E2E.md lists no authorized target; only a person adds targets")
    values: dict[str, str] = {}
    used: set[str] = set()
    for item in args.set:
        name, _, value = item.partition("=")
        if f"{{{name}}}" not in facts.contract["sample_placeholders"] or not value:
            raise SystemExit(f"--set takes one of {facts.contract['sample_placeholders']} as name=value, not {item!r}")
        if name in ("doc", "dir") and path_like(value):
            value = str(Path(value).resolve())  # the tool runs in the project, not where this was started
        values[name] = value
        if name == "session" or (name == "doc" and not path_like(value)):
            continue
        target = target_of(name, value)
        if covered(target, authorized) is None:
            raise SystemExit(f"{name}={value} is not covered by Authorized Targets in docs/E2E.md; only a person adds targets")
        used.add(covered(target, authorized) or target)
    if not used:
        raise SystemExit("a live run names at least one authorized target with --set doc=, dir= or device=")

    wanted = {r.strip() for r in args.row.split(",") if r.strip()}
    rows = [r for r in matrix["rows"] if r["applies"] and not r.get("unrunnable") and (not wanted or r["row"] in wanted)]
    if not rows:
        raise SystemExit("no row to run")
    path_flags = {f["name"] for f in command.get("flags", []) if f.get("type") in ("path", "file") or f.get("output")}
    path_flags |= {"--doc", "--output", "--dir"}
    secret = {f["name"] for f in command.get("flags", []) if f.get("secret")}
    filled = []
    for row in rows:
        arguments = [_fill(a, values) for a in row["arguments"]]
        missing = sorted({m for a in arguments for m in re.findall(r"\{(session|doc|device|dir)\}", a)})
        if missing:
            raise SystemExit(f"row {row['row']} needs --set {', '.join(missing)}")
        for flag, value in pairs(arguments):
            if flag == "--device" and covered(f"device:{value}", authorized) is None:
                raise SystemExit(f"row {row['row']} uses device {value}, which is not an authorized target")
            if flag in path_flags and path_like(value) and covered(target_of("doc", value), authorized) is None:
                raise SystemExit(f"row {row['row']} uses {value}, which is not inside an authorized target")
        filled.append((row, arguments, mode_of(command, arguments, args.mode)))

    env = {k: v for k, v in os.environ.items() if not k.startswith(facts.prefix + "_FAKE_HOST")}
    tool = [sys.executable, "-m", facts.pkg]
    app_version = args.application_version or _context_version(tool, root, env)
    runs = []
    state_dir = Path(env.get(f"{facts.prefix}_STATE_DIR") or Path.home() / f".{facts.tool}")
    for row, arguments, mode in filled:
        notes = []
        tampered = row["row"] == "read_back_mismatch"
        if tampered:
            exit_code, stdout = _tampered(tool + args.command.split(" ") + arguments, root, env, facts, state_dir, args, notes)
        else:
            exit_code, stdout = _run(tool + args.command.split(" ") + arguments, root, env, notes)
        try:
            envelope = json.loads(stdout.decode("utf-8", "replace").strip().splitlines()[-1])
        except (ValueError, IndexError):
            envelope = None
        envelope = envelope if isinstance(envelope, dict) else {}
        error = envelope.get("error") if isinstance(envelope.get("error"), dict) else {}
        code = error.get("code") if isinstance(error.get("code"), str) else None
        shown_exit = exit_code if exit_code in (*range(10), 130) else 1  # the exit codes of DCLI-014
        actual = {"exit": shown_exit, **({"code": code} if shown_exit and code else {})}
        passed = exit_code >= 0 and check_project.same_result(actual, row["expected"])
        if passed and row["row"] == "normal" and command.get("verify_after_save") and mode == "session":
            passed = _save_verifies(tool, root, env, values, notes)
        if simulated(envelope):
            passed = False
            notes.append("the result is simulated, so it is not evidence (DVER-021)")
        shown = []
        for i, argument in enumerate(arguments):
            flag = argument.partition("=")[0]
            if argument.startswith("--") and "=" in argument and flag in secret:
                shown.append(f"{flag}=***")
            elif i > 0 and arguments[i - 1] in secret:
                shown.append("***")
            else:
                shown.append(argument)
        entry = {"command": args.command, "arguments": shown, "exit": exit_code, "result": "pass" if passed else "fail",
                 "matrix_row": row["row"], "mode": mode, "envelope_sha256": hashlib.sha256(stdout.strip()).hexdigest()}
        if args.kind:
            entry["doc_kind"] = args.kind
        if tampered:
            entry["tampered"] = True
        if notes:
            entry["notes"] = "; ".join(notes)
        runs.append(entry)
        row["actual"] = actual
        print(f"{row['row']}: {'pass' if passed else 'fail'} (exit {exit_code}{', ' + code if code else ''})"
              f"{' - ' + '; '.join(notes) if notes else ''}")
    now = datetime.datetime.now(datetime.timezone.utc)
    name = f"{now.strftime('%Y-%m-%d-%H%M%S')}-{args.command.replace(' ', '-')}.json"
    record = {"kind": "live", "tool": facts.tool, "tool_version": facts.version, "commit": commit,
              "application": {"name": facts.driver.get("application"), "version": app_version}, "os": platform.platform(),
              "platform": PLATFORMS[sys.platform], "recorded_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
              "targets": sorted(used), "runs": runs}
    folder = root / "docs" / "evidence"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for row, _, _ in filled:
        row["evidence"] = f"live:docs/evidence/{name}#{row['row']}"
    matrix_path.write_text(json.dumps(matrix, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote docs/evidence/{name} and updated {matrix_path.relative_to(root).as_posix()}.")
    return 0 if all(r["result"] == "pass" for r in runs) else 1


def _run(argv: list[str], root: Path, env: dict[str, str], notes: list[str]) -> tuple[int, bytes]:
    try:
        proc = subprocess.run(argv, cwd=root, env=env, capture_output=True, timeout=TIMEOUT_S, creationflags=NO_WINDOW)
        return proc.returncode, proc.stdout
    except subprocess.TimeoutExpired as exc:
        notes.append(f"no answer within {TIMEOUT_S} s")
        return -1, exc.stdout or b""


def _tampered(argv: list[str], root: Path, env: dict[str, str], facts: Any, state_dir: Path, args: Any,
              notes: list[str]) -> tuple[int, bytes]:
    """The read_back_mismatch row: the tool waits before its read-back while the result is
    changed from outside, by the person or by --tamper (DVER-030)."""
    pause = state_dir / facts.contract["matrix"]["pause_file"]
    seconds = min(args.pause, int(facts.contract["matrix"]["max_pause_seconds"]))
    env = {**env, facts.contract["matrix"]["pause_env"].replace("<PREFIX>", facts.prefix): str(seconds)}
    proc = subprocess.Popen(argv, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    end = datetime.datetime.now() + datetime.timedelta(seconds=TIMEOUT_S)
    while not pause.exists() and proc.poll() is None and datetime.datetime.now() < end:
        import time

        time.sleep(0.2)
    if pause.exists():
        info = json.loads(pause.read_text(encoding="utf-8"))
        if args.tamper:
            done = subprocess.run(args.tamper, shell=True, cwd=root, env={**env, "TOOL_DRIVER_PAUSE_FILE": str(pause)},
                                  creationflags=NO_WINDOW)
            notes.append(f"--tamper exited {done.returncode}")
        else:
            print(f"Now change {', '.join(info.get('fields') or ['the result'])} of {', '.join(info.get('targets', []))} "
                  f"in the application, or the file it made; the tool waits up to {seconds} s.", file=sys.stderr, flush=True)
    else:
        notes.append("the tool never paused before its read-back")
    try:
        stdout, _ = proc.communicate(timeout=TIMEOUT_S + seconds)
        return proc.returncode, stdout
    except subprocess.TimeoutExpired:
        proc.kill()
        notes.append(f"no answer within {TIMEOUT_S + seconds} s")
        return -1, b""


def _save_verifies(tool: list[str], root: Path, env: dict[str, str], values: dict[str, str], notes: list[str]) -> bool:
    """A verify_after_save command: doc save on the same document must verify the change (DVER-030)."""
    if "session" not in values or "doc" not in values:
        notes.append("verify_after_save needs --set session= and --set doc= to save the document")
        return False
    base = tool + ["doc", "save", "--session", values["session"], "--doc", values["doc"]]
    out = _envelope(_run(base, root, env, notes)[1])
    token = ((out.get("error") or {}).get("details") or {}).get("confirm_token")
    if token:
        out = _envelope(_run(base + ["--confirm", token], root, env, notes)[1])
    receipt = (out.get("data") or {}).get("receipt") or ((out.get("error") or {}).get("details") or {}).get("receipt") or {}
    verified = out.get("ok") is True and receipt.get("outcome", {}).get("verification") == "passed"
    notes.append("doc save verified the change" if verified else "doc save did not verify the change")
    return verified


def _envelope(stdout: bytes) -> dict[str, Any]:
    try:
        value = json.loads(stdout.decode("utf-8", "replace").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {}
    return value if isinstance(value, dict) else {}


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


def _commit(root: Path) -> str | None:
    try:
        proc = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=root, capture_output=True, text=True,
                              creationflags=NO_WINDOW)
    except OSError:
        return None
    commit = proc.stdout.strip()
    return commit if proc.returncode == 0 and re.fullmatch(r"[0-9a-f]{7,40}", commit) else None


if __name__ == "__main__":
    sys.exit(main())
