"""The fake application: instances, documents, devices and long jobs, the generic answer to
domain commands (DVER-020), and the faults a test injects.

Every adapter capability of DCLI-260 is a ``cap_<name>`` method of ``World`` with the
payloads of ``contract/schemas/adapter.schema.json``. ``World.handle`` runs one call and
applies the faults; it raises ``HostError`` for a host error (DCLI-279), ``Hang`` when the
call must get no reply, and ``Close`` when the connection must close without a reply.

Reads never change the world. A request that breaks the protocol or the payloads is
refused and recorded in ``violations``; a fault in the fake host itself is recorded in
``internal_errors``. Tests check both lists.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONTRACT = Path(__file__).resolve().parents[2] / "contract" / "driver-contract.json"
_DEFAULT = json.loads(CONTRACT.read_text(encoding="utf-8"))
PROTOCOL_VERSION: str = _DEFAULT["host_protocol"]["version"]

SELECT = ("id", "ids", "items")
FAULT_ACTIONS = {"error", "hang", "close", "result", "store", "unreadable", "job"}
FAULT_METHODS = {"store": "apply", "job": "apply", "unreadable": "read_back"}

DEFAULT_CONFIG: dict[str, Any] = {
    "application": {"name": "FakeApp", "version": "1.0.0"},
    "protocol_version": PROTOCOL_VERSION,
    "plugin": {"name": "fakehost-plugin", "version": "1.0.0", "version_on_disk": "1.0.0"},
    "host_component": False,
    "instances": [{"id": "fake-1", "documents": [{"id": "doc-1", "name": "doc-1.fake"}]}],
    "files": [{"id": "file-1", "name": "file-1.fake"}],
    "devices": [{"id": "dev-1", "model": "FakeDevice", "firmware": "1.0.0", "state": "ready", "simulated": True}],
    "kinds": {},  # file extension -> the kind of a document opened from such a file, such as {".prj": "project"}
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def file_key(path: str) -> str:
    return "file:///" + Path(path).as_posix().lstrip("/")


class HostError(Exception):
    """A host error (DCLI-279): a JSON-RPC error with code -32000 and this ``data``."""

    def __init__(self, code: str, message: str, dispatch_state: str = "not_started", **extra: Any) -> None:
        super().__init__(message)
        self.data = {"code": code, "dispatch_state": dispatch_state, **extra}


class Hang(Exception):
    """The call gets no reply; the connection stays open until the client gives up."""


class Close(Exception):
    """The connection closes before the reply."""


class Refused(Exception):
    """The request breaks the protocol or the payloads; it is answered with E_VALIDATION."""


@dataclass
class Document:
    id: str
    path: str | None
    session: str | None
    untitled: int = 0
    objects: dict[str, dict[str, Any]] = field(default_factory=dict)
    missing: set[str] = field(default_factory=set)
    revision: int = 1
    dirty: bool = False
    readonly: bool = False
    disk: str = "in_sync"
    kind: str = "board"
    tool_changes: list[dict[str, Any]] = field(default_factory=list)
    external_changes: list[dict[str, Any]] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)

    def key(self, obj: str | None = None) -> str:
        base = f"untitled:{self.session}/{self.untitled}" if self.path is None else file_key(self.path)
        return f"{base}#/{obj}" if obj else base

    def view(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id, "path": self.path, "session": self.session, "kind": self.kind,
            "revision": f"r{self.revision}", "dirty": self.dirty, "readonly": self.readonly,
        }
        if self.path is None:
            out["key"] = self.key()  # only the application knows the number of an untitled document
        else:
            out["disk"] = self.disk
        return out

    def content(self) -> bytes:
        return json.dumps({"objects": self.objects}, sort_keys=True).encode("utf-8")

    def saved(self) -> None:
        self.dirty, self.disk = False, "in_sync"
        self.revision += 1
        self.tool_changes.clear()
        self.external_changes.clear()


@dataclass
class Instance:
    id: str
    pid: int
    generation: int = 0
    state: str = "ready"
    owned: bool = False
    blocker: dict[str, str] | None = None
    since_at: str | None = None
    plugin_loaded: str | None = None
    untitled: int = 0
    values: dict[str, Any] = field(default_factory=dict)


@dataclass
class Job:
    id: str
    operation_id: str
    total: int
    done: int = 0
    state: str = "running"
    action: str | None = None
    cancel_requested: bool = False
    polls_after_cancel: int = 0
    facts: dict[str, Any] = field(default_factory=dict)


class World:
    def __init__(
        self,
        config: dict[str, Any] | None = None,
        commands: list[dict[str, Any]] | None = None,
        workdir: str | None = None,
        contract: str | os.PathLike[str] | None = None,
    ) -> None:
        self.lock = threading.RLock()
        self.workdir = Path(workdir or tempfile.mkdtemp(prefix="fakehost-"))
        path = Path(contract or CONTRACT)
        data = json.loads(path.read_text(encoding="utf-8"))
        adapter = json.loads((path.parent / "schemas" / "adapter.schema.json").read_text(encoding="utf-8"))
        self.suffixes = {u["quantity"]: u["suffix"] for u in data["units"]}
        self.cli_side = [c["name"] for c in data["adapter_capabilities"] if c["side"] == "cli"]
        self.instance_side = [c["name"] for c in data["adapter_capabilities"] if c["side"] == "instance"]
        self.write_methods = set(data["host_protocol"]["write_methods"]) | {"open_session", "plugin_install", "plugin_remove"}
        self.host_error_codes = set(data["host_protocol"]["allowed_error_codes"])
        self.required = _required_keys(adapter)
        self.reset(config, commands)

    # ------------------------------------------------------------------ state

    def reset(self, config: dict[str, Any] | None = None, commands: list[dict[str, Any]] | None = None) -> None:
        with self.lock:
            cfg = copy.deepcopy(DEFAULT_CONFIG)
            cfg.update(copy.deepcopy(config or {}))
            self.config = cfg
            self.commands = {c["path"]: c for c in (commands or [])}
            self.protocol_version = cfg["protocol_version"]
            self.plugin = dict(cfg["plugin"])
            self.plugin_state_dir: str | None = None
            self.host_component = bool(cfg["host_component"])
            self.plugin_installed = self.host_component
            self.instances: dict[str, Instance] = {}
            self.documents: dict[str, Document] = {}
            self.devices = {d["id"]: {**d, "values": {}} for d in cfg["devices"]}
            self.jobs: dict[str, Job] = {}
            self.faults: list[dict[str, Any]] = []
            self.calls: list[dict[str, Any]] = []
            self.applied: list[dict[str, Any]] = []
            self.violations: list[str] = []
            self.internal_errors: list[str] = []
            self.pending_jobs: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
            self.counter = 0
            self.kind = "board"
            self.kinds = {suffix.lower(): kind for suffix, kind in cfg["kinds"].items()}
            for spec in cfg["instances"]:
                inst = self._add_instance(spec.get("id"), owned=False)
                for doc in spec.get("documents", []):
                    self._add_document(doc, inst.id)
            for doc in cfg["files"]:
                self._add_document(doc, None)

    def _next(self, prefix: str) -> str:
        taken = set(self.instances) | set(self.documents) | set(self.jobs)
        while True:
            self.counter += 1
            candidate = f"{prefix}-{self.counter}"
            if candidate not in taken:
                return candidate

    def _add_instance(self, instance_id: str | None, owned: bool) -> Instance:
        inst = Instance(id=instance_id or self._next("fake"), pid=os.getpid(), owned=owned)
        if self.host_component:
            inst.plugin_loaded = self.plugin["version"]
        self.instances[inst.id] = inst
        return inst

    def _add_document(self, spec: dict[str, Any], session: str | None, write: bool = True) -> Document:
        doc_id = spec.get("id") or self._next("doc")
        path = None if spec.get("untitled") else spec.get("path") or str(self.workdir / spec.get("name", f"{doc_id}.fake"))
        kind = spec.get("kind") or (self.kinds.get(Path(path).suffix.lower()) if path else None) or self.kind
        doc = Document(id=doc_id, path=path, session=session, objects=copy.deepcopy(spec.get("objects", {})), kind=kind)
        if path is None:
            inst = self.instances[session]
            inst.untitled += 1
            doc.untitled = inst.untitled
        elif write:
            Path(path).write_bytes(doc.content())
        self.documents[doc.id] = doc
        return doc

    def state(self) -> dict[str, Any]:
        """Everything a test may check, as plain data."""
        with self.lock:
            return copy.deepcopy({
                "instances": [{**self._session_view(i), "values": i.values} for i in self.instances.values()],
                "documents": [
                    {**d.view(), "objects": d.objects, "external_changes": d.external_changes}
                    for d in self.documents.values()
                ],
                "devices": list(self.devices.values()),
                "jobs": [vars(j) for j in self.jobs.values()],
                "plugin": self.plugin,
                "protocol_version": self.protocol_version,
                "calls": self.calls,
                "applied": self.applied,
                "violations": self.violations,
                "internal_errors": self.internal_errors,
                "faults": self.faults,
            })

    def _session_view(self, inst: Instance) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": inst.id,
            "application": dict(self.config["application"]),
            "pid": inst.pid,
            "owned": inst.owned,
            "generation": inst.generation,
            "state": inst.state,
            "documents": [
                {"id": d.id, "path": d.path, "dirty": d.dirty} for d in self.documents.values() if d.session == inst.id
            ],
            "plugin_loaded": inst.plugin_loaded,
        }
        if inst.state == "blocked":
            out["blocker"] = inst.blocker or {"action": "dismiss_dialog", "title": "Fake dialog"}
        if inst.state in ("busy", "unresponsive", "blocked"):
            out["since_at"] = inst.since_at or utc_now()
        return out

    # ------------------------------------------------------------------ dispatch

    def record_ignored(self, method: Any, params: Any, endpoint: str | None) -> None:
        """A request sent on a connection that already hangs; it gets no reply."""
        with self.lock:
            self.calls.append({"seq": len(self.calls) + 1, "endpoint": endpoint or "main", "method": method,
                               "params": params, "outcome": "ignored"})

    def handle(self, method: str, params: dict[str, Any], endpoint: str | None = None) -> Any:
        """Run one call, with the faults that match it. ``endpoint`` is the instance a host
        component connection belongs to, or ``None`` for the fake host's main address."""
        with self.lock:
            entry: dict[str, Any] = {"seq": len(self.calls) + 1, "endpoint": endpoint or "main", "method": method, "params": params}
            self.calls.append(entry)
            try:
                handler, params = self._route(method, params, endpoint)
                if method != "hello":
                    self._reachable(params)
                rule = self._take_fault(method, params)
                result = self._run(handler, params, rule)
            except Refused as exc:
                self.violations.append(f"{method}: {exc}")
                entry.update(outcome="error", error="E_VALIDATION")
                raise HostError("E_VALIDATION", str(exc)) from exc
            except HostError as exc:
                entry.update(outcome="error", error=exc.data["code"])
                raise
            except Hang:
                entry["outcome"] = "hang"
                raise
            except Close:
                entry["outcome"] = "close"
                raise
            except OSError as exc:
                entry.update(outcome="error", error="E_NATIVE_FAILURE")
                raise HostError("E_NATIVE_FAILURE", "the application could not write a file", native_message=str(exc)) from exc
            except Exception as exc:  # noqa: BLE001 - a fault of the fake host itself
                self.internal_errors.append(f"{method}: {type(exc).__name__}: {exc}")
                entry.update(outcome="error", error="E_NATIVE_FAILURE")
                raise HostError("E_NATIVE_FAILURE", f"fake host internal error: {exc}") from exc
            entry["outcome"] = "result"
            return result

    def _route(self, method: str, params: Any, endpoint: str | None) -> tuple[Any, dict[str, Any]]:
        """Check the request and pick its handler."""
        if not isinstance(params, dict):
            raise Refused("params is not an object")
        deadline = params.get("deadline_ms")
        if not isinstance(deadline, int) or isinstance(deadline, bool) or deadline < 1:
            raise Refused("deadline_ms is missing or not a positive integer")
        if method == "hello":
            if not (params.get("protocol_version") and params.get("cli_version")):
                raise Refused("hello needs protocol_version and cli_version")
            return (lambda p: self._hello(endpoint)), params
        known = method in self.cli_side or method in self.instance_side
        if not known or (endpoint is not None and method not in self.instance_side):
            raise HostError("E_UNSUPPORTED", f"{method} is not a method of this host")
        if endpoint is not None:
            if params.get("session", endpoint) != endpoint:
                raise Refused(f"session {params['session']} sent to the host of {endpoint}")
            params = {**params, "session": endpoint}
        elif self.host_component and method in self.instance_side and params.get("session"):
            self.violations.append(f"{method}: an instance-side call on the main address; with a host component it goes to the instance (DVER-023)")
        missing = [k for k in self.required.get(method, []) if k not in params]
        if missing:
            raise Refused(f"missing {', '.join(missing)}")
        return getattr(self, f"cap_{method}"), params

    def _run(self, handler: Any, params: dict[str, Any], rule: dict[str, Any] | None) -> Any:
        action = rule["action"] if rule else None
        if action in ("error", "hang", "close"):
            if rule.get("apply_first"):
                handler(params)
            if action == "hang":
                raise Hang()
            if action == "close":
                raise Close()
            error = dict(rule.get("error", {}))
            code = error.pop("code", "E_NATIVE_FAILURE")
            message = error.pop("message", f"injected {code}")
            error.setdefault("dispatch_state", "dispatched" if rule.get("apply_first") else "not_started")
            if code == "E_BUSY":
                error.setdefault("retry_after_ms", 500)
            if code == "E_HUMAN_REQUIRED":
                error.setdefault("action", "dismiss_dialog")
            raise HostError(code, message, **error)
        if action in FAULT_METHODS:
            return handler(params, rule)
        result = handler(params)
        if action == "result":
            _merge(result, rule.get("result", {}))
        return result

    def _hello(self, endpoint: str | None) -> dict[str, Any]:
        if endpoint is None:
            session = {"id": "fakehost", "generation": 0}
        else:
            inst = self._instance(endpoint)
            if inst.state == "unresponsive":
                raise Hang()
            session = {"id": inst.id, "generation": inst.generation}
        return {
            "protocol_version": self.protocol_version,
            "plugin_version": self.plugin["version"],
            "application": dict(self.config["application"]),
            "session": session,
            "methods": ["hello", *self.instance_side],
        }

    # ------------------------------------------------------------------ faults

    def add_fault(self, rule: dict[str, Any]) -> None:
        action, method = rule.get("action"), rule.get("method")
        if action not in FAULT_ACTIONS:
            raise ValueError(f"unknown fault action {action!r}")
        if method not in self.cli_side + self.instance_side + ["hello"]:
            raise ValueError(f"unknown method {method!r}")
        if action in FAULT_METHODS and method != FAULT_METHODS[action]:
            raise ValueError(f"the {action} fault works only on {FAULT_METHODS[action]}")
        code = rule.get("error", {}).get("code", "E_NATIVE_FAILURE")
        if action == "error" and code not in self.host_error_codes:
            raise ValueError(f"a host may not return {code} (DCLI-279)")
        with self.lock:
            self.faults.append({"times": 1, **rule})

    def _take_fault(self, method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        for rule in self.faults:
            if rule["method"] != method:
                continue
            if "command" in rule and params.get("command") != rule["command"]:
                continue
            if "session" in rule and params.get("session") != rule["session"]:
                continue
            if "target" in rule and rule["target"] not in _selected(params.get("inputs") or {}):
                continue
            if rule["times"] == 1:
                self.faults.remove(rule)
            elif rule["times"] > 1:
                rule["times"] -= 1
            return rule
        return None

    # ------------------------------------------------------------------ gates

    def _instance(self, session: str | None) -> Instance:
        inst = self.instances.get(session or "")
        if inst is None:
            raise HostError("E_NOT_FOUND", f"no instance {session!r}")
        return inst

    def _reachable(self, params: dict[str, Any]) -> None:
        """An instance that does not answer, a lost one and an offline device answer nothing,
        whatever the call asks for."""
        inst = self.instances.get(params.get("session") or "")
        if inst is not None and inst.state == "unresponsive":
            raise Hang()
        if inst is not None and inst.state == "lost":
            raise Close()
        dev = self.devices.get(params.get("device") or "")
        if dev is not None and dev["state"] == "offline":
            raise Close()

    def _gate(self, params: dict[str, Any], halt: bool = False) -> None:
        """Refuse a call the way a real instance or device would in its current state.
        A halt command passes a busy or blocked target (DSEC-018)."""
        if params.get("session"):
            inst = self._instance(params["session"])
            if inst.state == "unresponsive":
                raise Hang()
            if inst.state == "lost":
                raise Close()
            if inst.state == "closed":
                raise HostError("E_NOT_FOUND", f"instance {inst.id} is closed")
            if inst.state == "unreachable":
                raise HostError("E_BACKEND_UNAVAILABLE", f"instance {inst.id} runs, but cannot be driven")
            if not halt and inst.state in ("busy", "starting"):
                raise HostError("E_BUSY", "the main thread is busy", retry_after_ms=500)
            if not halt and inst.state == "blocked":
                blocker = inst.blocker or {"action": "dismiss_dialog"}
                raise HostError("E_HUMAN_REQUIRED", "a dialog blocks the application", action=blocker["action"])
        if params.get("device"):
            dev = self.devices.get(params["device"])
            if dev is None:
                raise HostError("E_NOT_FOUND", f"no device {params['device']!r}")
            if dev["state"] == "offline":
                raise Close()
            if not halt and dev["state"] == "busy":
                raise HostError("E_BUSY", "the device is busy", retry_after_ms=500)

    def _document(self, params: dict[str, Any], required: bool = True) -> Document | None:
        ref = params.get("document")
        if ref is None:
            if required:
                raise Refused("the call names no document")
            return None
        for doc in self.documents.values():
            if ref in (doc.id, doc.path) or (doc.path and ref == file_key(doc.path)):
                if params.get("session") and doc.session not in (None, params["session"]):
                    break
                return doc
        raise HostError("E_NOT_FOUND", f"no document {ref!r}")

    # ------------------------------------------------------------------ generic domain answer

    def _plan(self, params: dict[str, Any]) -> dict[str, Any]:
        """The targets, the changed fields and the output files of a domain command call."""
        command = params["command"]
        reg = self.commands.get(command)
        if reg is None and self.commands:
            raise Refused(f"command {command!r} is not registered")
        flags: dict[str, dict[str, Any]] | None = None
        if reg is not None:
            flags = {}
            for flag in reg.get("flags", []):
                key = flag["name"][2:].replace("-", "_")
                flags[key + self.suffixes.get(flag.get("quantity", ""), "")] = flag
        inputs = params.get("inputs") or {}
        items = inputs.get("items") if isinstance(inputs.get("items"), list) else None
        for key in list(inputs) + [k for item in items or [] for k in item]:
            if flags is not None and key not in SELECT and key not in flags:
                raise Refused(f"input {key!r} is not a flag of {command}")
        outputs = [str(v) for k, v in inputs.items() if flags and flags.get(k, {}).get("output")]
        common = {k: v for k, v in inputs.items() if k not in SELECT and not (flags and flags.get(k, {}).get("output"))}
        if items is not None:
            selected = [(str(i["id"]), {**common, **{k: v for k, v in i.items() if k != "id"}}) for i in items]
        else:
            selected = [(obj, dict(common)) for obj in _selected(inputs)]

        doc = self._document(params, required=False)
        device = params.get("device")
        if doc is None and device is None and selected:
            raise Refused("objects are selected but the call names no document or device")
        targets = []
        for obj, fields in selected:
            if doc is not None:
                if obj in doc.missing:
                    raise HostError("E_NOT_FOUND", f"no object {obj!r} in {doc.id}")
                targets.append({"key": doc.key(obj), "object": obj, "fields": fields})
            else:
                targets.append({"key": f"device:{device}/{obj}", "object": obj, "fields": fields})
        if not selected and not outputs:
            if doc is not None:
                targets.append({"key": doc.key(), "object": None, "fields": common})
            elif device is not None:
                targets.append({"key": f"device:{device}", "object": None, "fields": common})
        return {
            "command": command, "reg": reg or {}, "doc": doc, "device": device, "session": params.get("session"),
            "targets": targets, "fields": common, "outputs": outputs,
            "artifact": "artifact" in (reg or {}).get("effects", []), "halt": bool((reg or {}).get("halt")),
        }

    def _store(self, plan: dict[str, Any], target: dict[str, Any], create: bool = False) -> dict[str, Any]:
        """The stored values of a target; reads get a copy and never create anything."""
        doc, obj = plan["doc"], target["object"] or ""
        if doc is not None:
            box = doc.objects
        else:
            box = self.devices[plan["device"]]["values"]
        if create:
            return box.setdefault(obj, {})
        return dict(box.get(obj, {}))

    @staticmethod
    def _fields(plan: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
        return target["fields"] or {"last_command": plan["command"]}

    def _changes(self, plan: dict[str, Any]) -> list[dict[str, Any]]:
        changes = []
        for target in plan["targets"]:
            values = self._store(plan, target)
            for name, after in self._fields(plan, target).items():
                changes.append({"target": target["key"], "field": name, "before": values.get(name), "after": after})
        for path in plan["outputs"]:
            changes.append({"target": file_key(path), "field": "exists", "before": os.path.exists(path), "after": True})
        return changes

    def cap_read(self, params: dict[str, Any]) -> dict[str, Any]:
        plan = self._plan(params)
        self._gate(params, halt=plan["halt"])
        items = [{"key": t["key"], "id": t["object"], **self._store(plan, t)} for t in plan["targets"]]
        return {"result": {"items": items}}

    def cap_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        if params["command"] == "doc save":
            self._gate(params)
            doc = self._document(params)
            assert doc is not None
            return {
                "action": "save",
                "targets": [{"key": doc.key(), "kind": "document"}],
                "changes": [{**{k: v for k, v in c.items() if k != "operation_id"}, "origin": "tool"} for c in doc.tool_changes],
                "external_changes": copy.deepcopy(doc.external_changes),
                "can_apply": True,
            }
        plan = self._plan(params)
        self._gate(params, halt=plan["halt"])
        kind = plan["reg"].get("target_kind", "object")
        targets = [{"key": t["key"], "kind": kind} for t in plan["targets"]]
        targets += [{"key": file_key(p), "kind": "file"} for p in plan["outputs"]]
        return {"action": plan["command"], "targets": targets, "changes": self._changes(plan), "can_apply": True}

    def cap_apply(self, params: dict[str, Any], rule: dict[str, Any] | None = None) -> dict[str, Any]:
        plan = self._plan(params)
        self._gate(params, halt=plan["halt"])
        if rule is not None and rule["action"] == "job":
            job = Job(id=self._next("job"), operation_id=params["operation_id"], total=int(rule.get("steps", 3)))
            self.jobs[job.id] = job
            self.pending_jobs[job.id] = (params, plan)
            return {"dispatch_state": "dispatched", "change": "not_applied", "delivery": "not_applicable",
                    "persistence": "unchanged", "job": {"id": job.id, "state": "running"}}
        stored = rule.get("values", {}) if rule is not None and rule["action"] == "store" else {}
        return self._do_apply(params, plan, stored)

    def _do_apply(self, params: dict[str, Any], plan: dict[str, Any], stored: dict[str, Any]) -> dict[str, Any]:
        doc, op = plan["doc"], params["operation_id"]
        outputs = {}
        made = list(plan["outputs"])
        if plan["artifact"] and not made:
            # The application names the file itself, such as a footprint file in the library the
            # document is: the same call makes the same file.
            seed = json.dumps({"command": plan["command"], "doc": doc.key() if doc is not None else None,
                               "inputs": params.get("inputs")}, sort_keys=True).encode()
            made.append(str(self.workdir / "made" / f"{plan['command'].replace(' ', '-')}-{hashlib.sha256(seed).hexdigest()[:12]}.out"))
        for path in made:
            outputs[path] = json.dumps({"command": plan["command"], "inputs": params.get("inputs")}, sort_keys=True).encode()
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(outputs[path])
        changes = self._changes(plan)
        snapshot = copy.deepcopy(doc.objects) if doc is not None else None
        undo = []
        for target in plan["targets"]:
            values = self._store(plan, target, create=True)
            for name, value in self._fields(plan, target).items():
                undo.append((target["object"] or "", name, values.get(name)))
                values[name] = stored.get(name, value)
        if doc is not None and doc.session is None:
            try:
                Path(doc.path).write_bytes(doc.content())
            except OSError:
                doc.objects = snapshot
                raise
        if not plan["targets"] and not plan["outputs"] and plan["session"]:
            self._instance(plan["session"]).values.update(plan["fields"])
        self.applied.append({
            "operation_id": op, "command": plan["command"],
            "targets": [t["key"] for t in plan["targets"]] + [file_key(p) for p in plan["outputs"]],
        })
        files = [{"path": p, "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()} for p, b in outputs.items()]
        changes_doc = doc is not None and "change" in plan["reg"].get("effects", [])
        if plan["artifact"] and not changes_doc:
            return {"dispatch_state": "dispatched", "change": "not_applicable", "delivery": "not_applicable",
                    "persistence": "saved", "files": files}
        made_files = {"files": files} if files else {}
        if doc is not None:
            doc.history.append({"operation_id": op, "undo": undo})
            doc.revision += 1
            doc.tool_changes.extend({"operation_id": op, **c} for c in changes)
            if doc.session is None:
                doc.tool_changes.clear()
                return {"dispatch_state": "dispatched", "change": "applied", "delivery": "not_applicable", "persistence": "saved",
                        **made_files}
            doc.dirty = True
            return {"dispatch_state": "dispatched", "change": "applied", "delivery": "not_applicable", "persistence": "unchanged",
                    **made_files}
        if plan["device"] is not None:
            return {"dispatch_state": "dispatched", "change": "applied", "delivery": "delivered", "persistence": "not_applicable"}
        return {"dispatch_state": "dispatched", "change": "applied", "delivery": "not_applicable", "persistence": "unchanged"}

    def cap_read_back(self, params: dict[str, Any], rule: dict[str, Any] | None = None) -> dict[str, Any]:
        if params["command"] == "doc save":
            return self._read_saved(params, rule)
        plan = self._plan(params)
        self._gate(params, halt=plan["halt"])
        keys = [t["key"] for t in plan["targets"]] + [file_key(p) for p in plan["outputs"]]
        wanted = set(params.get("targets") or keys)
        unreadable = set(rule.get("fields", [])) if rule is not None else set()
        observed: dict[str, dict[str, Any]] = {}
        for target in plan["targets"]:
            if target["key"] in wanted:
                values = self._store(plan, target)
                names = params.get("fields") or list(self._fields(plan, target))
                observed[target["key"]] = {n: values.get(n) for n in names if n not in unreadable}
        for path in plan["outputs"]:
            if file_key(path) in wanted:
                observed[file_key(path)] = {"exists": os.path.exists(path)}
        result: dict[str, Any] = {"observed": observed}
        if unreadable:
            result["unreadable"] = sorted(unreadable)
        return result

    def _read_saved(self, params: dict[str, Any], rule: dict[str, Any] | None) -> dict[str, Any]:
        """Read the changed fields from the file a save wrote."""
        self._gate(params)
        doc = self._document(params)
        assert doc is not None
        if doc.path is None:
            raise HostError("E_VALIDATION", "an untitled document has no file to read")
        try:
            objects = json.loads(Path(doc.path).read_text(encoding="utf-8")).get("objects", {})
        except (OSError, ValueError) as exc:
            raise HostError("E_NATIVE_FAILURE", "the saved file cannot be read", native_message=str(exc)) from exc
        unreadable = set(rule.get("fields", [])) if rule is not None else set()
        prefix = doc.key() + "#/"
        observed: dict[str, dict[str, Any]] = {}
        for key in params.get("targets") or []:
            obj = key[len(prefix):] if key.startswith(prefix) else "" if key == doc.key() else None
            values = objects.get(obj, {}) if obj is not None else {}
            names = params.get("fields") or list(values)
            observed[key] = {n: values[n] for n in names if n in values and n not in unreadable}
            if key == doc.key() and "saved" in names and "saved" not in unreadable:
                observed[key]["saved"] = True  # read from the saved file itself
        result: dict[str, Any] = {"observed": observed}
        if unreadable:
            result["unreadable"] = sorted(unreadable)
        return result

    # ------------------------------------------------------------------ CLI-side capabilities

    def cap_probe(self, params: dict[str, Any]) -> dict[str, Any]:
        app = self.config["application"]
        return {"found": True, "path": str(self.workdir / app["name"]), "version": app["version"], "license": "not_required"}

    def cap_sessions(self, params: dict[str, Any]) -> dict[str, Any]:
        items = [self._session_view(i) for i in self.instances.values() if i.state != "closed"]
        return {"items": items, "complete": True}

    def cap_open_session(self, params: dict[str, Any]) -> dict[str, Any]:
        objects = self._load(params["path"]) if params.get("path") else None
        inst = self._add_instance(None, owned=True)
        if params.get("path"):
            # The kind of document the instance is for is the kind of the document it opens (DCLI-206).
            self._add_document({"path": params["path"], "objects": objects, "kind": params.get("kind")}, inst.id, write=False)
        return {"dispatch_state": "dispatched", "change": "applied", "delivery": "not_applicable",
                "persistence": "not_applicable", "session": self._session_view(inst)}

    def cap_devices(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"items": [{k: v for k, v in d.items() if k != "values"} for d in self.devices.values()]}

    def cap_plugin_status(self, params: dict[str, Any]) -> dict[str, Any]:
        loaded = [{"session": i.id, "version": i.plugin_loaded} for i in self.instances.values() if i.plugin_loaded]
        installed = self.plugin_installed
        return {
            "name": self.plugin["name"],
            "version_on_disk": self.plugin["version_on_disk"] if installed else None,
            "protocol_version": self.protocol_version,
            "install_path": str(self.workdir / "plugin") if installed else None,
            "loaded": loaded,
        }

    def cap_plugin_install(self, params: dict[str, Any]) -> dict[str, Any]:
        self.plugin_state_dir = params["state_dir"]
        version = params.get("version", self.plugin["version_on_disk"])
        self.plugin["version_on_disk"] = version
        self.plugin_installed = True
        return {"dispatch_state": "dispatched", "change": "applied", "delivery": "not_applicable",
                "persistence": "saved", "install_path": str(self.workdir / "plugin"), "version": version}

    def cap_plugin_remove(self, params: dict[str, Any]) -> dict[str, Any]:
        self.plugin_installed = False
        self.plugin_state_dir = None
        return {"dispatch_state": "dispatched", "change": "applied", "delivery": "not_applicable", "persistence": "saved"}

    # ------------------------------------------------------------------ instance-side capabilities

    def cap_close_session(self, params: dict[str, Any]) -> dict[str, Any]:
        self._gate(params)
        inst = self._instance(params["session"])
        if not params.get("discard") and any(d.dirty for d in self.documents.values() if d.session == inst.id):
            raise HostError("E_NATIVE_FAILURE", "the instance has unsaved changes")
        inst.state = "closed"
        for doc_id in [d.id for d in self.documents.values() if d.session == inst.id]:
            del self.documents[doc_id]
        return {"dispatch_state": "dispatched", "change": "applied", "delivery": "not_applicable", "persistence": "not_applicable"}

    def cap_documents(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("session"):
            self._gate(params)
            docs = [d for d in self.documents.values() if d.session == params["session"]]
        else:
            prefix = params.get("path", "")
            docs = [d for d in self.documents.values() if d.session is None and (d.path or "").startswith(prefix)]
        return {"items": [d.view() for d in docs]}

    def cap_create_doc(self, params: dict[str, Any]) -> dict[str, Any]:
        """Untitled in an instance; or at a path, written at once, in an instance or, without a
        session, in file mode (DCLI-212)."""
        session = params.get("session")
        if session is not None:
            self._gate(params)
        path = params.get("path")
        if path is None and session is None:
            raise HostError("E_VALIDATION", "a document made without an instance needs a path")
        if path is not None and Path(path).exists() and not params.get("overwrite"):
            raise HostError("E_VALIDATION", f"{path} exists")
        objects = self._load(params["template"]) if params.get("template") else {}
        spec = {"untitled": True} if path is None else {"path": path, "objects": objects}
        doc = self._add_document(spec, session, write=path is not None)
        if params.get("kind"):
            doc.kind = params["kind"]
        out = {"dispatch_state": "dispatched", "change": "applied", "delivery": "not_applicable",
               "persistence": "saved" if path is not None else "unchanged", "document": doc.view()}
        if path is not None:
            out["files"] = [{"path": path}]
        return out

    def cap_open_doc(self, params: dict[str, Any]) -> dict[str, Any]:
        self._gate(params)
        objects = self._load(params["path"])
        doc = self._add_document({"path": params["path"], "objects": objects}, params["session"], write=False)
        return {"dispatch_state": "dispatched", "change": "applied", "delivery": "not_applicable",
                "persistence": "unchanged", "document": doc.view()}

    @staticmethod
    def _load(path: str) -> dict[str, Any]:
        if not Path(path).is_file():
            raise HostError("E_NOT_FOUND", f"no file {path}")
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except ValueError:
            return {}  # a file of the real application, such as an evaluation's part: an empty document
        objects = data.get("objects", {}) if isinstance(data, dict) else {}
        return objects if isinstance(objects, dict) else {}

    def cap_save_doc(self, params: dict[str, Any]) -> dict[str, Any]:
        self._gate(params)
        doc = self._document(params)
        assert doc is not None
        if doc.path is None:
            raise HostError("E_VALIDATION", "an untitled document needs save-as")
        Path(doc.path).write_bytes(doc.content())
        doc.saved()
        self.applied.append({"operation_id": params["operation_id"], "command": "doc save", "targets": [doc.key()]})
        return {"dispatch_state": "dispatched", "change": "not_applicable", "delivery": "not_applicable",
                "persistence": "saved", "document": doc.view()}

    def cap_save_doc_as(self, params: dict[str, Any]) -> dict[str, Any]:
        self._gate(params)
        doc = self._document(params)
        assert doc is not None
        path = Path(params["path"])
        if path.exists() and not params.get("overwrite"):
            raise HostError("E_VALIDATION", f"{path} exists")
        data = doc.content()
        path.write_bytes(data)
        doc.path, doc.untitled = str(path), 0
        doc.saved()
        self.applied.append({"operation_id": params["operation_id"], "command": "doc save-as", "targets": [doc.key()]})
        return {"dispatch_state": "dispatched", "change": "not_applicable", "delivery": "not_applicable",
                "persistence": "saved", "document": doc.view(),
                "files": [{"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}]}

    def cap_close_doc(self, params: dict[str, Any]) -> dict[str, Any]:
        self._gate(params)
        doc = self._document(params)
        assert doc is not None
        if doc.dirty and not params.get("discard"):
            raise HostError("E_NATIVE_FAILURE", "the document has unsaved changes")
        del self.documents[doc.id]
        return {"dispatch_state": "dispatched", "change": "applied", "delivery": "not_applicable", "persistence": "not_applicable"}

    def cap_undo(self, params: dict[str, Any]) -> dict[str, Any]:
        """Undo the tool's most recent change: only its fields go back; a person's edits stay."""
        self._gate(params)
        doc = self._document(params)
        assert doc is not None
        if not doc.history:
            raise HostError("E_NATIVE_FAILURE", "nothing to undo")
        last = doc.history.pop()
        unsaved = any(c["operation_id"] == last["operation_id"] for c in doc.tool_changes)
        reverse = []
        for obj, name, before in reversed(last["undo"]):
            values = doc.objects.setdefault(obj, {})
            reverse.append({"operation_id": params["operation_id"], "target": doc.key(obj or None),
                            "field": name, "before": values.get(name), "after": before})
            if before is None:
                values.pop(name, None)
            else:
                values[name] = before
        if unsaved:
            # The undone change was never saved: it simply disappears from the save preview.
            doc.tool_changes = [c for c in doc.tool_changes if c["operation_id"] != last["operation_id"]]
        else:
            # It was saved: taking it back is itself a change the next save writes.
            doc.tool_changes.extend(reverse)
        doc.revision += 1
        doc.dirty = True
        return {"dispatch_state": "dispatched", "change": "applied", "delivery": "not_applicable",
                "persistence": "unchanged", "document": doc.view()}

    def cap_job_status(self, params: dict[str, Any]) -> dict[str, Any]:
        job = self.jobs.get(params["job"])
        if job is None:
            raise HostError("E_NOT_FOUND", f"no job {params['job']!r}")
        if job.state == "running":
            if job.cancel_requested:
                job.polls_after_cancel += 1
                if job.polls_after_cancel >= 2:
                    job.state = "cancelled"
                    job.facts = {"change": "not_applied", "delivery": "not_applicable", "persistence": "unchanged"}
            else:
                job.done += 1
                if job.done >= job.total:
                    facts = self._do_apply(*self.pending_jobs.pop(job.id), {})
                    job.state = "completed"
                    job.facts = {k: v for k, v in facts.items() if k in ("change", "delivery", "persistence", "files")}
        out: dict[str, Any] = {"state": job.state, "progress": {"done": job.done, "total": job.total, "unit": "steps"}}
        if job.state == "blocked":
            out["action"] = job.action or "dismiss_dialog"
        out.update(job.facts)
        return out

    def cap_cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        job = self.jobs.get(params["job"])
        if job is None:
            raise HostError("E_NOT_FOUND", f"no job {params['job']!r}")
        job.cancel_requested = True
        return {"dispatch_state": "dispatched"}

    # ------------------------------------------------------------------ control (tests only)

    def set_session(self, session: str, state: str, title: str | None = None, action: str = "dismiss_dialog",
                    knowledge: list[str] | None = None) -> None:
        with self.lock:
            inst = self._instance(session)
            inst.state = state
            inst.since_at = utc_now()
            inst.blocker = {"action": action, "title": title or "Fake dialog"} if state == "blocked" else None
            if inst.blocker is not None and knowledge:
                inst.blocker["knowledge"] = list(knowledge)  # the entries that tell how to handle it (DSKL-124)

    def restart_session(self, session: str) -> None:
        with self.lock:
            inst = self._instance(session)
            inst.generation += 1
            inst.state = "ready"

    def add_session(self, session: str | None = None) -> str:
        with self.lock:
            if session in self.instances:
                raise ValueError(f"instance {session} exists")
            inst = self._add_instance(session, owned=False)
            self._add_document({}, inst.id)
            return inst.id

    def set_device(self, device: str, state: str) -> None:
        with self.lock:
            self.devices[device]["state"] = state

    def edit(self, document: str, obj: str | None, name: str, value: Any) -> None:
        """A person changes a document in the application (DCLI-277). Without an object, the
        change is to a field of the document itself, which a read of the whole document returns."""
        with self.lock:
            doc = self._document({"document": document})
            assert doc is not None
            if name.endswith("[*]"):
                name, value = name[:-3], [value]  # a field that holds a list of texts
            values = doc.objects.setdefault(obj or "", {})
            before = values.get(name)
            values[name] = value
            doc.dirty = True
            doc.revision += 1
            doc.external_changes.append({"target": doc.key(obj), "field": name, "before": before, "after": value, "origin": "external"})

    def set_kind(self, kind: str) -> None:
        """Every open document, and every later one without a kind of its own, is of this kind:
        a test of a command registered with doc_kinds sets one of them (DCLI-210)."""
        with self.lock:
            self.kind = kind
            for doc in self.documents.values():
                doc.kind = kind

    def set_disk(self, document: str, disk: str) -> None:
        with self.lock:
            doc = self._document({"document": document})
            assert doc is not None
            doc.disk = disk

    def set_missing(self, document: str, objects: list[str]) -> None:
        with self.lock:
            doc = self._document({"document": document})
            assert doc is not None
            doc.missing = set(objects)

    def set_job(self, job: str, state: str, action: str | None = None) -> None:
        with self.lock:
            self.jobs[job].state = state
            self.jobs[job].action = action

    def configure(self, protocol_version: str | None = None, plugin: dict[str, Any] | None = None) -> None:
        with self.lock:
            if protocol_version:
                self.protocol_version = protocol_version
            if plugin:
                self.plugin.update(plugin)


def _required_keys(adapter: dict[str, Any]) -> dict[str, list[str]]:
    """The keys each adapter request requires, from adapter.schema.json."""
    defs = adapter["$defs"]
    out = {}
    for name, sub in defs["requests"]["properties"].items():
        keys = set(sub.get("required", []))
        ref = sub.get("$ref", "")
        if ref.startswith("#/$defs/"):
            keys |= set(defs[ref.rsplit("/", 1)[-1]].get("required", []))
        out[name] = sorted(keys)
    return out


def _selected(inputs: dict[str, Any]) -> list[str]:
    if isinstance(inputs.get("items"), list):
        return [str(item.get("id")) for item in inputs["items"]]
    ids = inputs.get("ids")
    if isinstance(ids, str):
        return [i for i in ids.split(",") if i]
    if isinstance(ids, list):
        return [str(i) for i in ids]
    if inputs.get("id") is not None:
        return [str(inputs["id"])]
    return []


def _merge(base: dict[str, Any], extra: dict[str, Any]) -> None:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
