#!/usr/bin/env python3
"""Run evaluation questions with an Agent: the evaluation runner (DSKL-040 to DSKL-044).

    python scripts/run_eval.py <project> --workspace-root <folder> [--questions tests/eval]
        [--only <id>,<id> | --stale] [--model <model>] [--report <file>] [--keep]
    python scripts/run_eval.py <project> --fake-host [...]
    python scripts/run_eval.py <project> --check (--fake-host | --workspace-root <folder>) [...]

Each question is one Python file (DSKL-044). For each question the runner makes a fresh
workspace with the tool's Skills and the scope file, keeps the question's documents in a
folder beside it, puts the tool on PATH behind a shim that records every run, and hands the
user's turns to the Agent one by one. The question's grader then decides from the real result:
the application, the files and the recorded runs, never from what the Agent says it did.

The Agent is Claude Code in print mode, resumed for each further turn. It may run only the tool
and `sleep` in its shell, and read and edit files only inside the workspace.

--check      the question's scripted agents instead of a real Agent: `right` must pass and every
             `wrong...` must fail, which shows that the grader tells them apart
--fake-host  the fake host stands in for the application; the report then says simulated, and a
             simulated report never supports a maturity level (DVER-021)

On the real application the workspace root and every scope target must be listed under
Authorized Targets in docs/E2E.md, or lie inside a listed folder (DVER-050), and the tool keeps the person's environment, so
it finds the running application. Before the Agent runs, the scripted `right` agent of each
question that has one runs once on the fake host, or on the real application for a question with
FAKE_HOST None; a question whose right answer fails stops the run, so no model credits go to it. A run on the real
application writes its report to docs/evidence/eval-<date>.json unless --report names another file.

Each result counts on its own while its question file, the commands it lists and the tool's
handwritten Skills and knowledge are unchanged (DSKL-043). --stale runs only the questions whose
newest such result is missing or failed.
"""
from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import check_project  # noqa: E402

NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
CALL_TIMEOUT_S = 100  # below the 120 s an Agent's shell waits for one command
TURN_TIMEOUT_S = 900
PLATFORMS = {"win32": "windows", "darwin": "macos"}
# The version line of a Skill's front matter, read the way the tool's doctor reads it.
SKILL_VERSION = re.compile(r"^\s+version:\s*['\"]?([^'\"\s]+)", re.MULTILINE)
HOME_VARIABLES = ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
                  "XDG_CACHE_HOME")
SHELLS = ("Bash", "PowerShell")
# File tools reach only the workspace, and never the installed Skills or the Agent's settings;
# the Skill tool loads only the tool's own Skills (claude_skills).
CLAUDE_TOOLS = ["Read(./**)", "Edit(./**)", "Write(./**)"]
CLAUDE_DENIED = [f"{tool}(./{folder}/**)" for tool in ("Edit", "Write") for folder in (".claude", ".agents")]
# A Claude Code session started from another one would otherwise join it.
CLAUDE_SESSION_VARIABLES = {"CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_ENTRYPOINT",
                            "CLAUDE_CODE_SESSION_ATTENDED", "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN",
                            "CLAUDE_CODE_EXECPATH", "CLAUDE_PID", "CLAUDE_EFFORT", "AI_AGENT"}
# What the Agent must know about the evaluation's limits; nothing about the task itself.
CLAUDE_RULES = ("In this session the shell runs only the `{tool}` command, and `sleep` to wait: one command per shell "
                "call, without pipes, redirections, `;`, `&&` or any other program. Files can be read and written only "
                "inside the working directory.")


class EvalError(Exception):
    """The run cannot go on; nothing about the Agent is decided."""


class AgentTimeout(Exception):
    """The Agent did not finish a turn in time; the question fails."""


# ------------------------------------------------------------------ questions


class Question:
    """One evaluation question, loaded from its Python file."""

    def __init__(self, path: Path, contract: dict[str, Any]) -> None:
        values, functions, problems = check_project.question_facts(path, contract)
        if problems:
            raise EvalError(f"{path.name}: " + "; ".join(problems))
        self.path = path
        self.id = path.stem
        self.sha256 = check_project.digest(path)
        self.scenario: str = values["SCENARIO"]
        self.commands: list[str] = values["COMMANDS"]
        self.turns: list[str] = values["TURNS"]
        self.scope: dict[str, Any] | None = values.get("SCOPE", {})
        self.files = path.parent / values["FILES"] if "FILES" in values else None
        # None: the question runs only on the real application, such as one that reads real files.
        self.fake_host: dict[str, Any] | None = values.get("FAKE_HOST", {})
        spec = importlib.util.spec_from_file_location(f"eval_question_{self.id}", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.title = (module.__doc__ or self.id).strip().splitlines()[0]
        self.grade: Callable[..., Any] = module.grade
        self.before: Callable[..., Any] | None = getattr(module, "before", None)
        self.after: Callable[..., Any] | None = getattr(module, "after", None)
        self.right: Callable[..., Any] | None = getattr(module, "right", None)
        self.wrong = [(name, getattr(module, name)) for name in sorted(functions)
                      if name == "wrong" or name.startswith("wrong_")]


def on_fake_host(questions: list[Question]) -> list[Question]:
    """The questions that run on the fake host; the others are named as skipped."""
    for question in questions:
        if question.fake_host is None:
            print(f"SKIP {question.id}: FAKE_HOST is None, so it runs only on the real application; "
                  "check it with --workspace-root in place of --fake-host", flush=True)
    return [q for q in questions if q.fake_host is not None]


def load_questions(folder: Path, contract: dict[str, Any], only: list[str] | None) -> list[Question]:
    paths = sorted(p for p in folder.glob("*.py") if not p.name.startswith("_"))
    if only:
        missing = sorted(set(only) - {p.stem for p in paths})
        if missing:
            raise EvalError(f"no question {', '.join(missing)} in {folder}")
        paths = [p for p in paths if p.stem in only]
    if not paths:
        raise EvalError(f"no question in {folder}")
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))  # questions may share helpers in files named _*.py
    return [Question(p, contract) for p in paths]


# ------------------------------------------------------------------ what the tool ran


class Call:
    """One run of the tool, as the recording shim saw it; ``exit`` is None while it runs."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.tool: str = data["tool"]
        self.turn: int = data["turn"]
        self.args: list[str] = data["args"]
        self.exit: int | None = data["exit"]
        self.stdout: str = data["stdout"]
        self.stderr: str = data["stderr"]
        self.started: int = data["started"]
        try:
            self.envelope: dict[str, Any] | None = json.loads(self.stdout)
        except ValueError:
            self.envelope = None

    @property
    def command(self) -> str:
        """The command path: the words before the first flag."""
        words = []
        for arg in self.args:
            if arg.startswith("-"):
                break
            words.append(arg)
        return " ".join(words)

    @property
    def ok(self) -> bool:
        return bool(self.envelope and self.envelope.get("ok"))

    @property
    def code(self) -> str | None:
        return ((self.envelope or {}).get("error") or {}).get("code")

    @property
    def details(self) -> dict[str, Any]:
        return ((self.envelope or {}).get("error") or {}).get("details") or {}

    @property
    def data(self) -> Any:
        return (self.envelope or {}).get("data")

    def has(self, *flags: str) -> bool:
        return all(flag in self.args for flag in flags)

    def value(self, flag: str) -> str | None:
        """The value given to a flag, as ``--flag value`` or ``--flag=value``."""
        for index, arg in enumerate(self.args):
            if arg == flag and index + 1 < len(self.args):
                return self.args[index + 1]
            if arg.startswith(flag + "="):
                return arg[len(flag) + 1:]
        return None

    def matches(self, line: str) -> bool:
        """Whether this call ran a command line the tool gave, such as a ``resume``, exactly."""
        try:
            return shlex.split(line, posix=True) == [self.tool, *self.args]
        except ValueError:
            return False

    def __repr__(self) -> str:
        return f"<turn {self.turn}: {shlex.join(self.args)} -> exit {self.exit}>"


def write_json(path: Path, data: Any) -> None:
    """Write a file whole, so a reader never sees half of it."""
    part = path.with_name(path.name + ".part")
    part.write_text(json.dumps(data), encoding="utf-8")
    os.replace(part, path)


def shim(config_path: str, args: list[str]) -> int:
    """The tool on the Agent's PATH: run the real tool and record the call."""
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    env = {k: v for k, v in os.environ.items() if k not in config["unset"]}
    env.update(config["set"])
    started = time.time_ns()
    folder = Path(config["calls"])
    folder.mkdir(parents=True, exist_ok=True)
    record = {"tool": config["tool"], "turn": config["turn"], "args": args, "exit": None, "started": started,
              "stdout": "", "stderr": ""}
    path = folder / f"{started}-{os.getpid()}.json"
    write_json(path, record)  # a run cut short still shows that it began
    try:
        proc = subprocess.run(config["argv"] + args, env=env, capture_output=True, timeout=CALL_TIMEOUT_S,
                              stdin=sys.stdin if sys.stdin and not sys.stdin.closed else subprocess.DEVNULL,
                              creationflags=NO_WINDOW)
        stdout, stderr, code = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired:
        stdout, stderr, code = b"", f"the tool did not finish within {CALL_TIMEOUT_S} s\n".encode(), 124
    record.update(exit=code, stdout=stdout.decode("utf-8", "replace"), stderr=stderr.decode("utf-8", "replace")[-4000:])
    write_json(path, record)
    sys.stdout.buffer.write(stdout)
    sys.stdout.flush()
    sys.stderr.buffer.write(stderr)
    sys.stderr.flush()
    return code


# ------------------------------------------------------------------ one question in its workspace


def file_key(path: Path) -> str:
    """A path as a target key, the way the runtime and docs/E2E.md write it (DCLI-040)."""
    return "file:///" + str(path).replace("\\", "/").lstrip("/")


def dangerous(command: dict[str, Any]) -> bool:
    tiers = command.get("tier")
    tiers = list(tiers.values()) if isinstance(tiers, dict) else [tiers]
    tiers += [w.get("tier") for w in command.get("tier_when", []) or []]
    return "dangerous" in tiers


class Session:
    """A question's workspace, documents, scope file and recording shim, and the fake host when asked."""

    def __init__(self, project: Path, facts: check_project.Facts, question: Question, fake_host: bool,
                 root: Path | None, keep: bool) -> None:
        self.project, self.facts, self.question, self.keep = project, facts, question, keep
        self.fake = fake_host
        self.tmp = Path(tempfile.mkdtemp(prefix=f"eval-{question.id}-", dir=root)).resolve()
        self.workspace = self.tmp / "work"
        self.workspace.mkdir()
        # The documents sit beside the workspace: the Agent reaches them through the tool,
        # never with its own file tools.
        self.documents = self.tmp / "documents"
        if question.files:
            shutil.copytree(question.files, self.documents)
        self.documents.mkdir(exist_ok=True)
        self.scope_file = self.workspace / "scope.json"
        self.calls_dir = self.tmp / "calls"
        self.config = self.tmp / "shim.json"
        self.bin = self.tmp / "bin"
        self.turn = 0
        self.messages: list[str] = []
        self.denied: list[str] = []
        self.ran: list[str] = []
        for folder in (self.workspace / ".claude" / "skills", self.workspace / ".agents" / "skills"):
            shutil.copytree(project / "skills", folder)
        self.host = self.client = None
        prefix = facts.prefix
        self.set = {f"{prefix}_SCOPE_FILE": str(self.scope_file), "npm_config_registry": "http://127.0.0.1:9/",
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONPATH": os.pathsep.join([str(project), os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep)}
        self.unset = [f"{prefix}_FAKE_HOST"]
        if fake_host:
            # On the fake host the tool gets a home and a state directory of its own; the
            # Skills sit where its doctor looks for installed copies (DSKL-031).
            home = self.tmp / "home"
            shutil.copytree(project / "skills", home / ".agents" / "skills")
            self.set.update({name: str(home) for name in HOME_VARIABLES})
            self.set[f"{prefix}_STATE_DIR"] = str(self.tmp / "state")
            sys.path.insert(0, str(HERE.parent / "conformance"))
            from fakehost import Client, FakeHost

            config = dict(question.fake_host or {})
            config.setdefault("host_component", facts.host_component)
            commands = (facts.registration or {}).get("commands", [])
            self.host = FakeHost(state_dir=str(self.tmp / "state"), config=config, commands=commands,
                                 workdir=str(self.documents)).start()
            self.client = Client(self.host.address)
            self.client.connect()
            self.set[f"{prefix}_FAKE_HOST"] = self.host.address
            self.unset = []
        self.scope_text = self._write_scope()
        self.harness_scope = self._write_harness_scope()
        self._write_shim()

    def default_scope(self) -> dict[str, Any]:
        """The documents folder, the effects of the question's commands, and dangerous only when one needs it."""
        commands = {c["path"]: c for c in self.facts.commands}
        chosen = [commands[p] for p in self.question.commands if p in commands]
        order = [e["effect"] for e in self.facts.contract["effects"]]
        effects = [e for e in order if e != "observe" and any(e in c.get("effects", []) for c in chosen)]
        return {"scope_id": "evaluation", "effects": effects, "dangerous": any(dangerous(c) for c in chosen),
                "targets": ["{documents}"] + (["untitled:", "device:"] if self.fake else []),
                "expires_at": "2099-01-01T00:00:00Z"}

    def _write_scope(self) -> str | None:
        if self.question.scope is None:
            return None
        scope = {**self.default_scope(), **self.question.scope}
        if not scope["effects"]:
            return None  # a question that only reads runs without a scope file
        documents = file_key(self.documents) + "/"
        scope["targets"] = [t.replace("{documents}", documents) for t in scope.get("targets", [])]
        text = json.dumps(scope, indent=2) + "\n"
        self.scope_file.write_text(text, encoding="utf-8")
        return text

    def _write_harness_scope(self) -> Path:
        """The scope of the grader's and hooks' own runs: every effect on the question's targets,
        never limited by the scope the Agent is evaluated under."""
        effects = [e["effect"] for e in self.facts.contract["effects"] if e["effect"] != "observe"]
        documents = file_key(self.documents) + "/"
        extra = [t for t in (self.question.scope or {}).get("targets", []) if not t.startswith("{documents}")]
        targets = [documents] + extra + (["untitled:", "device:"] if self.fake else [])
        path = self.tmp / "harness-scope.json"
        path.write_text(json.dumps({"scope_id": "evaluation-harness", "effects": effects, "dangerous": True,
                                    "targets": list(dict.fromkeys(targets)), "expires_at": "2099-01-01T00:00:00Z"}),
                        encoding="utf-8")
        return path

    def targets(self) -> list[str]:
        """The scope targets, with the documents folder written as {documents}."""
        if self.scope_text is None:
            return []
        documents = file_key(self.documents) + "/"
        return [t.replace(documents, "{documents}") for t in json.loads(self.scope_text)["targets"]]

    def _write_shim(self) -> None:
        self.bin.mkdir()
        python, script = Path(sys.executable).as_posix(), Path(__file__).resolve().as_posix()
        name = self.facts.tool
        sh = self.bin / name
        sh.write_text(f'#!/bin/sh\nexec "{python}" "{script}" --shim "{self.config.as_posix()}" "$@"\n', encoding="utf-8",
                      newline="\n")
        sh.chmod(0o755)
        if os.name == "nt":
            (self.bin / f"{name}.cmd").write_text(f'@"{sys.executable}" "{Path(__file__).resolve()}" --shim "{self.config}" %*\r\n',
                                                 encoding="utf-8", newline="")
        self.write_config()

    def write_config(self) -> None:
        argv = [sys.executable, "-m", self.facts.pkg]
        write_json(self.config, {"tool": self.facts.tool, "argv": argv, "set": self.set, "unset": self.unset,
                                 "calls": str(self.calls_dir), "turn": self.turn})

    def tool_env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k not in self.unset}
        env.update(self.set)
        return env

    def agent_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["PATH"] = str(self.bin) + os.pathsep + env.get("PATH", "")
        return env

    def calls(self) -> list[Call]:
        found = sorted(self.calls_dir.glob("*.json")) if self.calls_dir.is_dir() else []
        return sorted((Call(json.loads(p.read_text(encoding="utf-8"))) for p in found), key=lambda c: c.started)

    def close(self) -> None:
        if self.client is not None:
            self.client.close()
        if self.host is not None:
            self.host.stop()
        if self.keep:
            (self.tmp / "messages.json").write_text(json.dumps(self.messages, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"   kept {self.tmp}")
        else:
            shutil.rmtree(self.tmp, ignore_errors=True)


class Run:
    """What a grader and the ``before`` and ``after`` hooks see."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self.workspace = session.workspace
        self.documents = session.documents
        self.scope_file = session.scope_file
        self.simulated = session.host is not None
        self.problems: list[str] = []
        self.notes: dict[str, Any] = {}  # what a hook keeps for the grader
        self._writes = {c["path"] for c in session.facts.commands if c.get("effects") not in (None, [], ["observe"])}

    @property
    def calls(self) -> list[Call]:
        """Every run of the tool by the Agent, in order."""
        return self._session.calls()

    @property
    def messages(self) -> list[str]:
        """The Agent's last message of each turn."""
        return list(self._session.messages)

    def ran(self, command: str, turn: int | None = None) -> list[Call]:
        """The Agent's runs of one command path, in order."""
        return [c for c in self.calls if c.command == command and (turn is None or c.turn == turn)]

    def write_calls(self, turn: int | None = None) -> list[Call]:
        """The Agent's runs of write commands, without the dry runs."""
        return [c for c in self.calls if c.command in self._writes and "--dry-run" not in c.args
                and (turn is None or c.turn == turn)]

    def said(self, *needles: str, turn: int = -1) -> bool:
        """Whether the Agent's last message of a turn contains every text, ignoring case."""
        messages = self._session.messages
        text = messages[turn].lower() if messages else ""
        return all(n.lower() in text for n in needles)

    def check(self, condition: Any, problem: str) -> None:
        """Record a problem when the condition does not hold; a question without problems passed."""
        if not condition:
            self.problems.append(problem)

    def read(self, name: str) -> str:
        """The text of a file in the question's documents folder."""
        return (self.documents / name).read_text(encoding="utf-8")

    def tool(self, *args: str) -> dict[str, Any]:
        """Run the tool as the grader or a hook, under a scope of its own that grants every effect
        on the question's targets; the run is not one of the Agent's calls."""
        env = {**self._session.tool_env(), f"{self._session.facts.prefix}_SCOPE_FILE": str(self._session.harness_scope)}
        proc = subprocess.run([sys.executable, "-m", self._session.facts.pkg, *args], cwd=self.workspace,
                              env=env, capture_output=True, timeout=CALL_TIMEOUT_S,
                              stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
        try:
            return json.loads(proc.stdout.decode("utf-8"))
        except ValueError:
            raise RuntimeError(f"the tool gave no envelope for {shlex.join(args)}: "
                               f"{proc.stderr.decode('utf-8', 'replace')[-400:]}") from None

    def scope_changed(self) -> bool:
        text = self._session.scope_text
        if text is None:
            return self.scope_file.exists()
        return not self.scope_file.is_file() or self.scope_file.read_text(encoding="utf-8") != text

    # The fake host only ---------------------------------------------------------------

    def host(self, name: str, **params: Any) -> Any:
        """Call a fake host control, such as ``set_session``."""
        if self._session.client is None:
            raise RuntimeError("this question uses the fake host; it runs only with --fake-host")
        return self._session.client.control(name, **params)

    def state(self) -> dict[str, Any]:
        return self.host("state")

    def applied(self, command: str | None = None) -> list[dict[str, Any]]:
        """The changes that reached the fake host, one entry per dispatch."""
        return [a for a in self.state()["applied"] if command is None or a["command"] == command]

    def document(self, doc_id: str) -> dict[str, Any]:
        for doc in self.state()["documents"]:
            if doc["id"] == doc_id:
                return doc
        raise LookupError(f"the fake host has no document {doc_id}")


# ------------------------------------------------------------------ agents


class ScriptedAgent:
    """A question's scripted agent: it runs the tool through the same recording shim."""

    def __init__(self, script: Callable[..., Any]) -> None:
        self.script = script

    def turn(self, session: Session, message: str) -> str:
        actor = Actor(session)
        self.script(actor, session.turn)
        return actor.message


class Actor:
    """What a scripted agent uses: ``run``, ``line``, ``say`` and the calls so far."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self.turn = session.turn
        self.workspace = session.workspace
        self.documents = session.documents
        self.message = ""

    @property
    def calls(self) -> list[Call]:
        """Every run of the tool so far, in order, from earlier turns too."""
        return self._session.calls()

    def run(self, *args: str) -> Call:
        before = {c.started for c in self._session.calls()}
        subprocess.run([sys.executable, str(Path(__file__).resolve()), "--shim", str(self._session.config), *args],
                       cwd=self.workspace, env=self._session.agent_env(), capture_output=True, stdin=subprocess.DEVNULL,
                       timeout=CALL_TIMEOUT_S + 30, creationflags=NO_WINDOW)
        new = [c for c in self._session.calls() if c.started not in before]
        if not new:
            raise EvalError(f"the shim recorded no call for {shlex.join(args)}")
        return new[-1]

    def line(self, text: str) -> Call:
        """Run a command line the tool gave, such as a ``poll`` or ``lookup``, exactly as given."""
        words = shlex.split(text, posix=True)
        if not words or words[0] != self._session.facts.tool:
            raise RuntimeError(f"{text!r} is not a command of {self._session.facts.tool}")
        return self.run(*words[1:])

    def say(self, text: str) -> None:
        self.message = text


def git_bash() -> Path | None:
    """The bash.exe of Git for Windows, found from git.exe, which sits in its cmd or mingw64/bin folder."""
    git = shutil.which("git")
    for root in Path(git).resolve().parents if git else []:
        for path in (root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe"):
            if path.is_file():
                return path
    return None


def skill_names(project: Path) -> list[str]:
    folder = project / "skills"
    return sorted(d.name for d in folder.iterdir() if (d / "SKILL.md").is_file()) if folder.is_dir() else []


def claude_skills(project: Path) -> list[str]:
    """The permission rules that let the Agent load the tool's own Skills and no other."""
    return [rule for name in skill_names(project) for rule in (f"Skill({name})", f"Skill({name} *)")]


def shadowing_skills(project: Path, facts: check_project.Facts, real: bool) -> list[tuple[Path, str]]:
    """Copies of the tool's Skills outside the project that would change the evaluation, each with
    the reason: a personal Skill of Claude Code whose files differ, because Claude Code loads it in
    place of the project's Skill of that name; and on the real application, where the tool keeps the
    person's home, a copy at another version in an Agent's Skill folder, because the tool's doctor
    reports it and tells the Agent to run update (DSKL-031)."""
    names = skill_names(project)
    personal = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "skills"

    def files(folder: Path) -> dict[str, str]:
        return {f.relative_to(folder).as_posix(): check_project.digest(f) for f in folder.rglob("*")
                if f.is_file() and f.name not in check_project.JUNK and "__pycache__" not in f.parts}

    found = [(personal / name, "Claude Code loads it in place of the tool's Skill of that name")
             for name in names if (personal / name).is_dir() and files(personal / name) != files(project / "skills" / name)]
    if not real:
        return found
    home = Path(os.environ.get("USERPROFILE" if os.name == "nt" else "HOME") or os.environ.get("HOME") or Path.home())
    for entry in facts.contract["update"]["skill_dirs"]:
        folder = home / entry[2:] if entry.startswith("~/") else Path(entry)
        for name in names:
            skill = folder / name / "SKILL.md"
            if not skill.is_file() or any(path == skill.parent for path, _ in found):
                continue
            match = SKILL_VERSION.search(skill.read_text(encoding="utf-8", errors="replace"))
            version = match.group(1) if match else None
            if version != facts.version:
                found.append((skill.parent, f"it is at version {version}, not {facts.version}, so the tool's doctor "
                                            "reports it and tells the Agent to run update"))
    return found


class ClaudeAgent:
    """Claude Code in print mode; each further turn resumes the same conversation."""

    def __init__(self, model: str | None) -> None:
        self.executable = shutil.which("claude")
        if not self.executable:
            raise EvalError("Claude Code (`claude`) is not on PATH")
        version = subprocess.run([self.executable, "--version"], capture_output=True, text=True, timeout=60,
                                 creationflags=NO_WINDOW).stdout.strip()
        self.name = f"Claude Code {version.split()[0] if version else ''}".strip()
        self.requested = model
        self.models: list[str] = []
        self.conversation: str | None = None

    def fresh(self) -> ClaudeAgent:
        self.conversation = None
        return self

    def turn(self, session: Session, message: str) -> str:
        tool = session.facts.tool
        shells = [f"{shell}({name}{rest})" for shell in SHELLS for name in (tool, "sleep") for rest in ("", " *")]
        cmd = [self.executable, "-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "dontAsk",
               "--setting-sources", "project", "--strict-mcp-config", "--append-system-prompt",
               CLAUDE_RULES.format(tool=tool), "--allowedTools", *shells, *CLAUDE_TOOLS, *claude_skills(session.project),
               "--disallowedTools", *CLAUDE_DENIED]
        if self.requested:
            cmd += ["--model", self.requested]
        if self.conversation:
            cmd += ["--resume", self.conversation]
        env = {k: v for k, v in session.agent_env().items() if k not in CLAUDE_SESSION_VARIABLES}
        if os.name == "nt":
            # Claude Code checks the permission rules of its Bash tool reliably; its PowerShell
            # tool may fail to parse a command and refuse it.
            env["CLAUDE_CODE_USE_POWERSHELL_TOOL"] = "0"
            bash = git_bash()
            if bash and "CLAUDE_CODE_GIT_BASH_PATH" not in env:
                env["CLAUDE_CODE_GIT_BASH_PATH"] = str(bash)
        try:
            proc = subprocess.run(cmd, cwd=session.workspace, env=env, input=message.encode("utf-8"), capture_output=True,
                                  timeout=TURN_TIMEOUT_S, creationflags=NO_WINDOW)
        except subprocess.TimeoutExpired:
            raise AgentTimeout(f"the Agent did not finish turn {session.turn + 1} within {TURN_TIMEOUT_S} s") from None
        events = []
        for line in proc.stdout.decode("utf-8", "replace").splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
        result = next((e for e in reversed(events) if e.get("type") == "result"), None)
        if result is None or result.get("is_error") or proc.returncode != 0:
            detail = (result or {}).get("result") or proc.stderr.decode("utf-8", "replace")[-600:]
            raise EvalError(f"Claude Code failed: {detail}")
        self.conversation = result.get("session_id") or self.conversation
        self.models += [m for m in result.get("modelUsage") or {} if m not in self.models]
        denied = {d.get("tool_use_id") for d in result.get("permission_denials") or []}
        session.denied += [json.dumps(d.get("tool_input"))[:200] for d in result.get("permission_denials") or []]
        ran = 0
        for event in events:
            for item in ((event.get("message") or {}).get("content") or []) if event.get("type") == "assistant" else []:
                if item.get("type") == "tool_use" and item.get("name") in SHELLS and item.get("id") not in denied:
                    words = str((item.get("input") or {}).get("command", "")).split()
                    ran += bool(words) and Path(words[0]).stem == tool
        recorded = sum(1 for c in session.calls() if c.turn == session.turn)
        if ran > recorded:
            raise EvalError(f"Claude Code ran {tool} {ran} times in turn {session.turn + 1}, but the shim recorded "
                            f"{recorded}: another {tool} comes first on the PATH of its shell")
        return str(result.get("result") or "")


# ------------------------------------------------------------------ running


def attempt(project: Path, facts: check_project.Facts, question: Question, agent: Any, fake_host: bool,
            root: Path | None, keep: bool) -> tuple[list[str], str | None, Session]:
    """Run one question with one agent: the grader's problems (none: passed), what broke in the
    question, a hook or a scripted agent, and the closed session."""
    session = Session(project, facts, question, fake_host, root, keep)
    run = Run(session)
    error = None
    try:
        for index, message in enumerate(question.turns):
            session.turn = index
            session.write_config()
            if question.before:
                question.before(run, index)
            session.messages.append(agent.turn(session, message.replace("{documents}", str(session.documents))))
        question.grade(run)
    except EvalError:
        raise
    except AgentTimeout as exc:
        run.problems.append(str(exc))
    except Exception as exc:  # noqa: BLE001 - a broken question fails, with the reason
        error = f"{type(exc).__name__}: {exc}"
    finally:
        if question.after:
            try:
                question.after(run)
            except Exception as exc:  # noqa: BLE001
                error = error or f"after: {type(exc).__name__}: {exc}"
        session.ran = sorted({c.command for c in session.calls() if c.command})
        session.close()
    return run.problems, error, session


def check_graders(project: Path, facts: check_project.Facts, questions: list[Question], fake_host: bool,
                  root: Path | None, keep: bool) -> int:
    failed = 0
    for question in questions:
        if question.right is None or not question.wrong:
            print(f"FAIL {question.id}: --check needs a `right` and at least one `wrong` scripted agent")
            failed += 1
            continue
        problems, error, _ = attempt(project, facts, question, ScriptedAgent(question.right), fake_host, root, keep)
        bad = bool(problems or error)
        lines = [f"right {'BROKE: ' + error if error else 'FAILED: ' + '; '.join(problems) if problems else 'passed'}"]
        for name, script in question.wrong:
            problems, error, _ = attempt(project, facts, question, ScriptedAgent(script), fake_host, root, keep)
            bad |= bool(error) or not problems
            lines.append(f"{name} " + ("BROKE: " + error if error else "failed: " + "; ".join(problems) if problems
                                       else "PASSED, the grader cannot tell it from right"))
        failed += bad
        print(f"{'FAIL' if bad else 'ok  '} {question.id} ({question.scenario}): " + " | ".join(lines), flush=True)
    print(f"{len(questions) - failed} of {len(questions)} graders tell the right run from the wrong ones")
    return 1 if failed else 0


def broken_questions(project: Path, facts: check_project.Facts, questions: list[Question], fake_host: bool,
                     root: Path | None) -> list[str]:
    """The scripted ``right`` agent of each question that has one, run before the Agent spends
    model credits: a question whose own right answer fails would grade the Agent against a broken
    question. It runs on the fake host; a question with ``FAKE_HOST = None`` cannot, so in a run on
    the real application its right answer runs there."""
    broken = []
    for question in questions:
        if question.right is None or (question.fake_host is None and fake_host):
            continue
        on_fake = question.fake_host is not None
        try:
            problems, error, _ = attempt(project, facts, question, ScriptedAgent(question.right), on_fake,
                                         None if on_fake else root, False)
        except EvalError as exc:
            problems, error = [], str(exc)
        if problems or error:
            broken.append(f"{question.id} ({error or '; '.join(problems)})")
    return broken


def evaluate(project: Path, facts: check_project.Facts, questions: list[Question], agent: Any, fake_host: bool,
             root: Path | None, keep: bool, report: Path | None) -> int:
    results: list[dict[str, Any]] = []
    targets: list[str] = []
    data = {"tool": facts.tool, "tool_version": facts.version, "date": datetime.date.today().isoformat(),
            "agent": agent.name, "model": "", "simulated": fake_host, "platform": PLATFORMS.get(sys.platform, "linux"),
            "targets": targets, "questions": results}
    base = file_key(root or Path(tempfile.gettempdir()).resolve()) + "/"
    # What each result depends on, taken before the Agent runs (DSKL-043).
    fingerprints = {q.id: check_project.question_fingerprint(facts, q.sha256, q.commands) for q in questions}
    for question in questions:
        problems, error, session = attempt(project, facts, question, agent.fresh(), fake_host, root, keep)
        failures = problems + ([error] if error else [])
        if failures and session.denied:
            failures.append("refused: " + ", ".join(session.denied))
        results.append({"scenario": question.scenario, "id": question.id, "passed": not failures,
                        "notes": "; ".join(failures)[:2000] if failures else question.title,
                        "sha256": question.sha256, "commands": question.commands, "ran": session.ran,
                        "fingerprint": fingerprints[question.id]})
        for target in [base] + [t for t in session.targets() if t != "{documents}"]:
            if target not in targets:
                targets.append(target)
        data["model"] = ", ".join(agent.models) or agent.requested or "default"
        print(f"{'pass' if not failures else 'FAIL'} {question.id} ({question.scenario})"
              + (f": {'; '.join(failures)}" if failures else ""), flush=True)
        if report is not None:
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    if report is not None:
        print(f"report: {report}")
    passed = sum(r["passed"] for r in results)
    print(f"{passed} of {len(results)} questions passed")
    return 0 if passed == len(results) else 1


def default_report(project: Path) -> Path:
    folder = project / "docs" / "evidence"
    base = f"eval-{datetime.date.today().isoformat()}"
    path, number = folder / f"{base}.json", 2
    while path.exists():
        path, number = folder / f"{base}-{number}.json", number + 1
    return path


def authorize(project: Path, questions: list[Question], root: Path | None) -> None:
    """On the real application, the workspaces and every scope target must be authorized (DVER-050)."""
    authorized = check_project.authorized_targets(project)
    if not authorized:
        raise EvalError("docs/E2E.md lists no Authorized Targets; nothing runs on the real application")
    if root is None:
        raise EvalError("name a workspace root with --workspace-root: a folder listed under Authorized Targets, or one inside it")
    key = file_key(root.resolve()) + "/"
    if not any(check_project.target_covered(key, a) for a in authorized):
        raise EvalError(f"the workspace root {key} is not listed under Authorized Targets in docs/E2E.md, nor inside a listed folder")
    for question in questions:
        for target in (question.scope or {}).get("targets", []):
            if target.startswith("{documents}"):
                continue
            if not any(check_project.target_covered(target, a) for a in authorized):
                raise EvalError(f"{question.id}: the scope target {target} is not listed under Authorized Targets in docs/E2E.md, nor inside a listed folder")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--shim"]:
        return shim(argv[1], argv[2:])
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")  # the console code page may lack a character of the output
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project")
    parser.add_argument("--questions", default="tests/eval", help="the folder of question files, relative to the project")
    parser.add_argument("--only", help="question IDs, separated by commas")
    parser.add_argument("--stale", action="store_true",
                        help="only the questions without a current passed result from the real application")
    parser.add_argument("--model", help="the model the Agent uses")
    parser.add_argument("--check", action="store_true", help="run the scripted agents and check the graders")
    parser.add_argument("--fake-host", action="store_true", help="run on the fake host instead of the real application")
    parser.add_argument("--workspace-root", help="where the workspaces are made; on the real application, a folder listed under Authorized Targets or inside one")
    parser.add_argument("--report", help="where to write the evaluation report")
    parser.add_argument("--keep", action="store_true", help="keep each workspace")
    args = parser.parse_args(argv)
    project = Path(args.project).resolve()
    root = Path(args.workspace_root).resolve() if args.workspace_root else None
    try:
        facts = check_project.gather(project)
        if facts.reference is None:
            raise EvalError(f"cannot start the tool: {facts.tool_error or 'package.json names no command'}")
        folder = Path(args.questions)
        folder = folder if folder.is_absolute() else project / folder
        questions = load_questions(folder, facts.contract, args.only.split(",") if args.only else None)
        paths = {c["path"] for c in facts.commands}
        for question in questions:
            unknown = [c for c in question.commands if c not in paths]
            if unknown:
                raise EvalError(f"{question.id}: COMMANDS names commands the tool does not have: {', '.join(unknown)}")
        if args.stale:
            if args.only or args.fake_host or args.check:
                raise EvalError("--stale picks the questions to run on the real application; leave out --only, --fake-host and --check")
            results = check_project.Checker(facts).results()
            questions = [q for q in questions if q.id not in results or not results[q.id][1]["passed"]]
            if not questions:
                print("every question has a current passed result; nothing to run")
                return 0
            print("running " + ", ".join(q.id for q in questions))
        if args.fake_host:
            questions = on_fake_host(questions)
            if not questions:
                print("no question runs on the fake host")
                return 0
        else:
            authorize(project, questions, root)
        if root is not None:
            root.mkdir(parents=True, exist_ok=True)
        if args.check:
            return check_graders(project, facts, questions, args.fake_host, root, args.keep)
        report = Path(args.report).resolve() if args.report else None
        if report is None and not args.fake_host:
            report = default_report(project)
        stale = shadowing_skills(project, facts, not args.fake_host)
        if stale:
            raise EvalError("these copies of the tool's Skills would change the evaluation: "
                            + "; ".join(f"{path} ({why})" for path, why in stale)
                            + ". Move them out of those folders for the evaluation, then run again")
        broken = broken_questions(project, facts, questions, args.fake_host, root)
        if broken:
            raise EvalError("the scripted right answer fails these questions, so nothing was asked of the Agent: "
                            + "; ".join(broken) + ". Fix the questions; --check shows each grader")
        return evaluate(project, facts, questions, ClaudeAgent(args.model), args.fake_host, root, args.keep, report)
    except EvalError as exc:
        print(f"run_eval: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
