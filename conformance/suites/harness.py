"""What every conformance test uses: the tool under test as a black box, the fake host and a
temporary state directory per test (DVER-011, DSEC-034).

The tool is only ever started as a process. The suite reads its ``reference``, its
``contract/commands.json`` and the write samples in ``tests/matrix/``, starts a fresh fake
host for each test and points the tool at it with ``<PREFIX>_FAKE_HOST`` (DVER-023).
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from fakehost import Client, FakeHost  # noqa: E402

FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
TIERS = ["none", "direct", "two_step", "dangerous"]
DEVICE = {"model": "FakeDevice", "firmware": "1.0.0", "state": "ready", "simulated": True}
# A world with a second document and a second device, to confirm a token against another target.
SECOND = {
    "instances": [{"id": "fake-1", "documents": [{"id": "doc-1", "name": "doc-1.fake"}, {"id": "doc-2", "name": "doc-2.fake"}]}],
    "files": [{"id": "file-1", "name": "file-1.fake"}, {"id": "file-2", "name": "file-2.fake"}],
    "devices": [{"id": "dev-1", **DEVICE}, {"id": "dev-2", **DEVICE}],
}


def isolated_env(base: str) -> dict[str, str]:
    """The environment for a call outside any test case: no state directory, scope or fake
    host of the user's, and a home directory of its own (DSEC-034)."""
    env = {k: v for k, v in os.environ.items() if not k.endswith(("_STATE_DIR", "_SCOPE_FILE", "_FAKE_HOST"))}
    for name in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
                 "XDG_CACHE_HOME"):
        env[name] = base
    return env


class Failure(AssertionError):
    """The tool broke the rule the test checks."""


class NotApplicable(Exception):
    """The test does not apply to this tool; the message names the condition."""


def check(condition: Any, message: str) -> None:
    if not condition:
        raise Failure(message)


@dataclass
class Outcome:
    args: list[str]
    exit: int
    stdout: str
    stderr: str
    seconds: float
    envelope: dict[str, Any] | None

    @property
    def ok(self) -> bool:
        return bool(self.envelope and self.envelope.get("ok"))

    @property
    def code(self) -> str | None:
        return (self.envelope or {}).get("error", {}).get("code")

    @property
    def details(self) -> dict[str, Any]:
        return (self.envelope or {}).get("error", {}).get("details", {})

    @property
    def data(self) -> Any:
        return (self.envelope or {}).get("data")

    def describe(self) -> str:
        return f"`{' '.join(self.args)}` gave exit {self.exit}: {self.stdout.strip()[:600]} {self.stderr.strip()[-400:]}"


@dataclass
class Subject:
    """The tool under test: how to start it and what it declares."""

    argv: list[str]
    project: Path
    envelopes: list[tuple[list[str], dict[str, Any], int]] = field(default_factory=list)

    def __post_init__(self) -> None:
        base = tempfile.mkdtemp(prefix="drv-ref-")
        try:
            env = isolated_env(base)
            out = Path(base) / "reference.json"
            index = self._raw(["reference"], env, base)
            self.name = index["data"]["tool"]
            self.prefix = self.name.upper().replace("-", "_")
            env[f"{self.prefix}_STATE_DIR"] = str(Path(base) / "state")
            self._raw(["reference", "--all", "--output", str(out)], env, base)
            self.reference = json.loads(out.read_text(encoding="utf-8"))
        finally:
            shutil.rmtree(base, ignore_errors=True)
        self.commands = {c["path"]: c for c in self.reference["commands"]}
        self.driver = self.reference["driver"]
        self.modes = self.driver["modes"]
        self.host_component = bool(self.driver.get("host_component"))
        path = self.project / "contract" / "commands.json"
        self.registrations = {c["path"]: c for c in json.loads(path.read_text(encoding="utf-8"))["commands"]}
        self.samples: dict[str, list[str]] = {}
        folder = self.project / "tests" / "matrix"
        for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            matrix = json.loads(path.read_text(encoding="utf-8"))
            for row in matrix.get("rows", []):
                if row.get("row") == "normal" and row.get("applies") and isinstance(row.get("arguments"), list):
                    self.samples[matrix["command"]] = list(row["arguments"])

    def _raw(self, args: list[str], env: dict[str, str], cwd: str) -> dict[str, Any]:
        proc = subprocess.run(self.argv + args, cwd=self.project, env=env, capture_output=True, timeout=120,
                              creationflags=FLAGS)
        return json.loads(proc.stdout.decode("utf-8"))

    # What the registration says -------------------------------------------------------

    def writes(self) -> list[str]:
        return [p for p, r in self.registrations.items() if r["effects"] != ["observe"]]

    def tier(self, path: str, mode: str | None = None) -> str:
        """The tier the rules give, from the registration and the contract, never from the
        tool's own claim (DCLI-051, DCLI-052)."""
        from .schemas import contract

        c = contract()
        reg = self.registrations.get(path)
        if reg is None:
            std = next((s for s in c["standard_commands"] if s["path"] == path), None)
            return std["tier"] if std else "none"
        if reg["effects"] == ["observe"]:
            return "none"
        if reg["halt"]:
            return "direct"
        effects = {e["effect"]: e for e in c["effects"]}
        modes = [mode] if mode else reg["modes"]
        found = []
        for m in modes:
            tiers = [effects[e]["tier"][m] if isinstance(effects[e]["tier"], dict) else effects[e]["tier"] for e in reg["effects"]]
            if reg["irreversible"]:
                tiers.append("dangerous")
            found.append(max(tiers, key=TIERS.index))
        return max(found, key=TIERS.index)

    def facts(self) -> dict[str, bool]:
        """The conditions of DVER-010, decided from the registration and reference only."""
        regs = self.registrations.values()
        writes = [r for r in regs if r["effects"] != ["observe"]]
        tiers = [self.tier(r["path"], m) for r in writes for m in r["modes"]]
        direct = [r for r in writes if not r["halt"] and any(self.tier(r["path"], m) == "direct" for m in r["modes"])]
        return {
            "always": True,
            "writes": bool(writes),
            "direct_writes": bool(direct) or "session" in self.modes,
            "documents": any(m in self.modes for m in ("file", "session")),
            "dangerous": "dangerous" in tiers,
            "jobs": any("job_status" in r["adapter_capabilities"] for r in regs),
            "session": "session" in self.modes,
            "device": "device" in self.modes,
            "host_component": self.host_component,
            "physical": any("physical" in r["effects"] for r in regs),
            "halt": any(r["halt"] and any(m in ("session", "device") for m in r["modes"]) for r in regs),
        }


class Case:
    """One test: a fresh fake host, state directory and scope file."""

    def __init__(self, subject: Subject, config: dict[str, Any] | None = None) -> None:
        self.subject = subject
        self.tmp = Path(tempfile.mkdtemp(prefix="drv-case-"))
        self.state_dir = self.tmp / "state"  # the tool creates it, with its protection
        self.work = self.tmp / "work"
        self.work.mkdir()
        self.dir = self.tmp / "out"
        self.dir.mkdir()
        self.scope_file = self.tmp / "scope.json"
        cfg = dict(config or {})
        cfg.setdefault("host_component", subject.host_component)
        self.host = FakeHost(state_dir=str(self.state_dir), config=cfg, commands=list(subject.registrations.values()),
                             workdir=str(self.work)).start()
        self.client = Client(self.host.address)
        self.client.connect()
        own = {f"{subject.prefix}_{name}" for name in ("STATE_DIR", "SCOPE_FILE", "FAKE_HOST")}
        self.env = {k: v for k, v in os.environ.items() if k not in own and k.lower() not in ("http_proxy", "https_proxy", "all_proxy")}
        self.env.update({f"{subject.prefix}_FAKE_HOST": self.host.address, f"{subject.prefix}_STATE_DIR": str(self.state_dir),
                         f"{subject.prefix}_SCOPE_FILE": str(self.scope_file), "npm_config_registry": "http://127.0.0.1:9/"})
        self.grant()

    def close(self) -> None:
        try:
            self.client.close()
        finally:
            self.host.stop()
            shutil.rmtree(self.tmp, ignore_errors=True)

    def __enter__(self) -> Case:
        return self

    def __exit__(self, kind: object, *exc: object) -> None:
        try:
            if kind is None:
                st = self.state()
                bad = st["violations"] + [f"fake host fault: {e}" for e in st["internal_errors"]]
                check(not bad, f"the tool broke the host protocol or the adapter payloads: {bad[:5]}")
        finally:
            self.close()

    # Scope -----------------------------------------------------------------------------

    def grant(self, *, effects: list[str] | None = None, dangerous: bool = True, targets: list[str] | None = None,
              confirm: str | None = None, scope_id: str = "conformance") -> None:
        data: dict[str, Any] = {
            "scope_id": scope_id,
            "effects": effects or ["lifecycle", "change", "artifact", "persist", "configure", "deliver", "physical"],
            "dangerous": dangerous, "targets": targets or ["file:///", "untitled:", "device:"],
            "expires_at": "2099-01-01T00:00:00Z",
        }
        if confirm:
            data["confirm"] = confirm
        self.scope_file.write_text(json.dumps(data), encoding="utf-8")

    def revoke(self) -> None:
        self.scope_file.unlink(missing_ok=True)

    # The fake host ---------------------------------------------------------------------

    def control(self, name: str, **params: Any) -> Any:
        return self.client.control(name, **params)

    def state(self) -> dict[str, Any]:
        return self.control("state")

    def applied(self) -> list[dict[str, Any]]:
        return self.state()["applied"]

    def calls(self, method: str) -> list[dict[str, Any]]:
        return [c for c in self.state()["calls"] if c["method"] == method]

    def doc_path(self, doc_id: str) -> str:
        for doc in self.state()["documents"]:
            if doc["id"] == doc_id:
                return doc["path"]
        raise KeyError(doc_id)

    def fill(self, args: list[str], file_mode: bool = False) -> list[str]:
        """Fill the sample placeholders with the fake host's values (DVER-002)."""
        values = {"{session}": "fake-1", "{doc}": self.doc_path("file-1") if file_mode else "doc-1",
                  "{device}": "dev-1", "{dir}": str(self.dir)}
        out = []
        for arg in args:
            for key, value in values.items():
                arg = arg.replace(key, value)
            out.append(arg)
        return out

    def footprint(self) -> str:
        """Everything a write could change: the fake host's world and the files it holds."""
        st = self.state()
        files = {}
        for folder in (self.work, self.dir):
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    files[str(path)] = path.read_bytes()
        reg = self.state_dir / "knowledge-links.json"
        knowledge = reg.read_bytes() if reg.exists() else b""
        return json.dumps({"applied": st["applied"], "documents": st["documents"], "devices": st["devices"],
                           "jobs": st["jobs"], "plugin": st["plugin"]}, sort_keys=True, default=str) + repr(files) + repr(knowledge)

    # Running the tool ------------------------------------------------------------------

    def run(self, *args: str, env: dict[str, str] | None = None, timeout: float = 90) -> Outcome:
        argv = self.subject.argv + list(args)
        started = time.monotonic()
        proc = subprocess.run(argv, cwd=self.subject.project, env={**self.env, **(env or {})}, capture_output=True,
                              timeout=timeout, creationflags=FLAGS)
        seconds = time.monotonic() - started
        stdout = proc.stdout.decode("utf-8", "replace")
        envelope = None
        try:
            envelope = json.loads(stdout)
        except ValueError:
            pass
        out = Outcome(list(args), proc.returncode, stdout, proc.stderr.decode("utf-8", "replace"), seconds, envelope)
        if envelope is not None and "--format" not in args:
            self.subject.envelopes.append((list(args), envelope, proc.returncode))
        return out


class Recorder:
    """A local proxy that only counts connections, to show that no request goes out."""

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.sock.settimeout(0.2)
        self.count = 0
        self.url = f"http://127.0.0.1:{self.sock.getsockname()[1]}"
        self._stop = False
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                continue
            self.count += 1
            conn.close()

    def env(self) -> dict[str, str]:
        return {"HTTP_PROXY": self.url, "HTTPS_PROXY": self.url, "ALL_PROXY": self.url, "http_proxy": self.url,
                "https_proxy": self.url, "NO_PROXY": "", "no_proxy": "", "npm_config_registry": "https://registry.npmjs.org/"}

    def close(self) -> None:
        self._stop = True
        self._thread.join(1)
        self.sock.close()
