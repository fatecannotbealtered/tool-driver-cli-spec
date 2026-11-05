#!/usr/bin/env python3
"""Run a behavior matrix on the real application: the matrix runner (DVER-030, DVER-042).

    python scripts/run_matrix.py <project> --command "<path>" --set doc=<file> [--set session=<id>]
        [--set device=<id>] [--set dir=<folder>] [--set job=<id>] [--job-from "<long command>"]
        [--row normal,busy] [--mode session] [--kind part] [--pause 120] [--tamper "<command>"]
        [--application-version 10.0.1]

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

``{inputs}`` is the project's ``tests/inputs/`` folder. ``{job}`` is the ``--set job=`` value, or
else the job that the ``normal`` row of a long command starts at the beginning of the run: the
command ``--job-from`` names, or the tool's only long command.

Every file, folder and device a run uses, through ``--set`` or written in a row, must be listed
under Authorized Targets in ``docs/E2E.md`` (DVER-050); otherwise nothing runs. A file a command
only reads from ``tests/inputs/`` is not a target. The fake host is never used, and a simulated
result never counts as a pass (DVER-021).
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import platform
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_project  # noqa: E402

NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
PLATFORMS = {"win32": "windows", "darwin": "macos", "linux": "linux"}
TIMEOUT_S = 300
JOB_WAIT_S = 3600  # how long the runner follows a long job (DCLI-065)


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
    parser.add_argument("--job-from", help="the long command whose normal row starts the job that fills {job}")
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
    settable = [p for p in facts.contract["sample_placeholders"] if p != "{inputs}"]
    for item in args.set:
        name, _, value = item.partition("=")
        if f"{{{name}}}" not in settable or not value:
            raise SystemExit(f"--set takes one of {settable} as name=value, not {item!r}")
        if name in ("doc", "dir") and path_like(value):
            value = str(Path(value).resolve())  # the tool runs in the project, not where this was started
        values[name] = value
        if name in ("session", "job") or (name == "doc" and not path_like(value)):
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
    inputs = root / "tests" / "inputs"
    values["inputs"] = str(inputs)
    secret = {f["name"] for f in command.get("flags", []) if f.get("secret")}
    needs_job = "job" not in values and any("{job}" in a for r in rows for a in r["arguments"])
    starter = None
    if needs_job:
        starter = _job_starter(root, facts, args.job_from, values, authorized)
    elif args.job_from:
        raise SystemExit("--job-from fills {job}; no row to run uses it, or --set job= already does")
    filled = []
    for row in rows:
        arguments = [_fill(a, values) for a in row["arguments"]]
        _check_row(row["row"], command, arguments, authorized, inputs, needs_job)
        filled.append((row, arguments, mode_of(command, arguments, args.mode)))

    env = {k: v for k, v in os.environ.items() if not k.startswith(facts.prefix + "_FAKE_HOST")}
    tool = [sys.executable, "-m", facts.pkg]
    app_version = args.application_version or _context_version(tool, root, env)
    job_note = None
    if starter is not None:
        values["job"], job_note = _start_job(tool, root, env, starter)
        filled = [(row, [a.replace("{job}", values["job"]) for a in arguments], mode) for row, arguments, mode in filled]
    runs = []
    state_dir = Path(env.get(f"{facts.prefix}_STATE_DIR") or Path.home() / f".{facts.tool}")
    for row, arguments, mode in filled:
        notes = [job_note] if job_note and any(values["job"] in a for a in arguments) else []
        tampered = row["row"] == "read_back_mismatch"
        row_env = env
        watcher = None
        if tampered:
            row_env = {**env, facts.contract["matrix"]["pause_env"].replace("<PREFIX>", facts.prefix):
                       str(min(args.pause, int(facts.contract["matrix"]["max_pause_seconds"])))}
            watcher = _Watcher(state_dir / facts.contract["matrix"]["pause_file"], root, row_env, args, notes)
            watcher.start()
        expected_code = row["expected"].get("code")
        exit_code, stdout = _confirmed(tool + args.command.split(" ") + arguments, root, row_env, expected_code, notes)
        envelope = _envelope(stdout)
        if command.get("long") and envelope.get("ok") is True:
            exit_code, envelope = _job_end(tool, root, env, envelope, facts.contract, notes)
        if tampered and command.get("verify_after_save") and mode == "session" and envelope.get("ok") is True:
            # The change is verified at the save, so the mismatch is caused there (DVER-030).
            exit_code, stdout = _confirmed(tool + ["doc", "save", "--session", values.get("session", ""), "--doc", values.get("doc", "")],
                                           root, row_env, expected_code, notes)
            envelope = _envelope(stdout)
        if watcher is not None:
            watcher.join(timeout=5)
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
                 "matrix_row": row["row"], "mode": mode,
                 "envelope_sha256": hashlib.sha256(stdout.strip()).hexdigest()}
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
    (folder / name).write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    for row, _, _ in filled:
        row["evidence"] = f"live:docs/evidence/{name}#{row['row']}"
    matrix_path.write_text(json.dumps(matrix, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote docs/evidence/{name} and updated {matrix_path.relative_to(root).as_posix()}.")
    return 0 if all(r["result"] == "pass" for r in runs) else 1


def _check_row(name: str, command: dict[str, Any], arguments: list[str], authorized: list[str], inputs: Path,
               job_pending: bool = False) -> None:
    """Every target a row names is authorized (DVER-050); a file it only reads from tests/inputs/ is not a target."""
    missing = sorted({m for a in arguments for m in re.findall(r"\{(session|doc|device|dir|job)\}", a)
                      if not (m == "job" and job_pending)})
    if missing:
        raise SystemExit(f"row {name} needs --set {', '.join(missing)}")
    outputs = {f["name"] for f in command.get("flags", []) if f.get("output")} | {"--output", "--dir"}
    written = outputs | ({"--doc"} if command.get("effects") != ["observe"] else set())
    path_flags = {f["name"] for f in command.get("flags", []) if f.get("type") in ("path", "file")} | outputs | {"--doc"}
    for flag, value in pairs(arguments):
        if flag == "--device" and covered(f"device:{value}", authorized) is None:
            raise SystemExit(f"row {name} uses device {value}, which is not an authorized target")
        if flag not in path_flags or not path_like(value):
            continue
        if flag not in written and _inside(value, inputs):
            continue  # read only, from the project's own sample inputs
        if covered(target_of("doc", value), authorized) is None:
            raise SystemExit(f"row {name} uses {value}, which is not inside an authorized target")


def _inside(value: str, folder: Path) -> bool:
    try:
        Path(value).resolve().relative_to(folder.resolve())
        return True
    except ValueError:
        return False


def _job_starter(root: Path, facts: Any, named: str | None, values: dict[str, str],
                 authorized: list[str]) -> tuple[str, list[str]]:
    """The long command, and its filled normal row, that starts the job filling {job}."""
    long = [c["path"] for c in facts.commands if c.get("long")]
    if named is None:
        if len(long) != 1:
            raise SystemExit("a row uses {job}: pass --set job=<id>, or --job-from with the long command that starts one"
                             + (f" (one of {', '.join(long)})" if long else "; the tool has no long command"))
        named = long[0]
    elif named not in long:
        raise SystemExit(f"--job-from takes a long command; {named!r} is not one" + (f" (long: {', '.join(long)})" if long else ""))
    source = next(c for c in facts.commands if c["path"] == named)
    path = root / "tests" / "matrix" / (named.replace(" ", "-") + ".json")
    rows = [r for r in json.loads(check_project.read(path))["rows"] if r["row"] == "normal" and r["applies"]]
    if not rows:
        raise SystemExit(f"{path.name} has no normal row to start a job with")
    arguments = [_fill(a, values) for a in rows[0]["arguments"]]
    if any("{job}" in a for a in arguments):
        raise SystemExit(f"the normal row of {named} itself uses {{job}}")
    _check_row("normal of " + named, source, arguments, authorized, Path(values["inputs"]))
    return named, arguments


def _start_job(tool: list[str], root: Path, env: dict[str, str], starter: tuple[str, list[str]]) -> tuple[str, str]:
    named, arguments = starter
    notes: list[str] = []
    _, stdout = _confirmed(tool + named.split(" ") + arguments, root, env, None, notes)
    data = _envelope(stdout).get("data") or {}
    job = (data.get("result") or {}).get("job") or data.get("job") or {}
    if not job.get("id"):
        raise SystemExit(f"{named} started no job for {{job}}: {stdout.decode('utf-8', 'replace').strip()[-300:]}")
    print(f"{{job}} is {job['id']}, started by {named}.")
    return str(job["id"]), f"{{job}} is {job['id']}, started by `{named}`"


def _run(argv: list[str], root: Path, env: dict[str, str], notes: list[str], timeout: float = TIMEOUT_S) -> tuple[int, bytes]:
    """Run one call; when it does not answer in time, end it with every process it started, so
    a child that still holds the output cannot keep the runner waiting."""
    options: dict[str, Any] = {"cwd": root, "env": env, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
    if os.name == "nt":
        options["creationflags"] = NO_WINDOW
    else:
        options["start_new_session"] = True  # its own process group, so killpg ends them all
    proc = subprocess.Popen(argv, **options)
    try:
        stdout, _ = proc.communicate(timeout=timeout)
        return proc.returncode, stdout
    except subprocess.TimeoutExpired:
        notes.append(f"no answer within {int(timeout)} s")
        kill_tree(proc)
        try:
            stdout, _ = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            stdout = b""
            for stream in (proc.stdout, proc.stderr):
                try:
                    stream.close()
                except OSError:
                    pass
        return -1, stdout or b""


def kill_tree(proc: subprocess.Popen) -> None:
    """End a process and every process it started."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, creationflags=NO_WINDOW, check=False)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
    try:
        proc.kill()
    except OSError:
        pass


class _Watcher(threading.Thread):
    """The read_back_mismatch row: once the tool pauses before its read-back, the result is
    changed from outside, by --tamper or by the person (DVER-030)."""

    def __init__(self, pause: Path, root: Path, env: dict[str, str], args: Any, notes: list[str]) -> None:
        super().__init__(daemon=True)
        self.pause, self.root, self.env, self.args, self.notes = pause, root, env, args, notes
        self.stopped = threading.Event()

    def run(self) -> None:
        end = time.monotonic() + TIMEOUT_S + JOB_WAIT_S
        while not self.pause.exists():
            if time.monotonic() > end or self.stopped.is_set():
                self.notes.append("the tool never paused before its read-back")
                return
            time.sleep(0.2)
        try:
            info = json.loads(self.pause.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            info = {}
        if self.args.tamper:
            done = subprocess.run(self.args.tamper, shell=True, cwd=self.root,
                                  env={**self.env, "TOOL_DRIVER_PAUSE_FILE": str(self.pause)}, creationflags=NO_WINDOW)
            self.notes.append(f"--tamper exited {done.returncode}")
        else:
            print(f"Now change {', '.join(info.get('fields') or ['the result'])} of {', '.join(info.get('targets', []))} "
                  f"in the application, or delete the file it made; the tool waits up to {info.get('seconds')} s.",
                  file=sys.stderr, flush=True)

    def join(self, timeout: float | None = None) -> None:
        self.stopped.set()
        super().join(timeout)


def _confirmed(argv: list[str], root: Path, env: dict[str, str], expected_code: str | None,
               notes: list[str]) -> tuple[int, bytes]:
    """Run a row; a two-step or dangerous write is confirmed with its token, unless the row
    expects the confirmation itself (DCLI-053)."""
    exit_code, stdout = _run(argv, root, env, notes)
    out = _envelope(stdout)
    details = (out.get("error") or {}).get("details") or {}
    if (out.get("error") or {}).get("code") == "E_CONFIRMATION_REQUIRED" and expected_code != "E_CONFIRMATION_REQUIRED" \
            and details.get("confirm_token"):
        extra = ["--confirm", details["confirm_token"]]
        if (details.get("preview") or {}).get("tier") == "dangerous":
            extra.append("--dangerous")
        exit_code, stdout = _run(argv + extra, root, env, notes)
    return exit_code, stdout


def _job_end(tool: list[str], root: Path, env: dict[str, str], envelope: dict[str, Any], contract: dict[str, Any],
             notes: list[str]) -> tuple[int, dict[str, Any]]:
    """A long command's row is decided by how its job ends (DCLI-065)."""
    data = envelope.get("data") or {}
    job = (data.get("result") or {}).get("job") or data.get("job") or {}
    if not job.get("id"):
        notes.append("the long command returned no job")
        return 1, envelope
    end = time.monotonic() + JOB_WAIT_S
    view: dict[str, Any] = {}
    while time.monotonic() < end:
        out = _envelope(_run(tool + ["job", "get", "--job", job["id"], "--wait", "600s"], root, env, notes)[1])
        view = out.get("data") or {}
        if view.get("state") in ("completed", "failed", "partial", "unknown", "cancelled"):
            break
    else:
        notes.append(f"job {job['id']} did not end within {JOB_WAIT_S} s")
        return 1, {"ok": False, "error": {"code": "E_TIMEOUT"}}
    notes.append(f"job {job['id']} ended {view.get('state')}")
    if view.get("ok"):
        return 0, {"ok": True, "data": view}
    exits = {e["code"]: e["exit"] for e in contract["error_codes"]}
    code = view.get("code") or "E_UNKNOWN"
    return exits.get(code, 1), {"ok": False, "error": {"code": code}, "data": view}


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
    _, stdout = _run(tool + ["context"], root, env, [], 120)
    try:
        version = json.loads(stdout.decode("utf-8"))["data"]["application"]["version"]
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
