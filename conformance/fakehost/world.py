"""The fake application: instances, documents, devices and long jobs, the generic answer to
domain commands (DVER-020), and the faults a test injects.

Every adapter capability of DCLI-260 is a method of ``World`` with the payloads of
``contract/schemas/adapter.schema.json``. ``World.handle`` runs one call and applies the
faults; it raises ``HostError`` for a host error (DCLI-279), ``Hang`` when the call must get
no reply, and ``Close`` when the connection must close without a reply.
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

PROTOCOL_VERSION = "1.0.0"
CONTRACT = Path(__file__).resolve().parents[2] / "contract" / "driver-contract.json"

CLI_SIDE = ["probe", "sessions", "open_session", "devices", "plugin_status", "plugin_install"]
INSTANCE_SIDE = [
    "close_session", "documents", "create_doc", "open_doc", "save_doc", "save_doc_as", "close_doc",
    "undo", "read", "preview", "apply", "read_back", "job_status", "cancel",
]
WRITE_METHODS = {
    "open_session", "close_session", "create_doc", "open_doc", "save_doc", "save_doc_as", "close_doc",
    "undo", "apply", "cancel", "plugin_install",
}
SELECT = ("id", "ids", "items")
FAULT_ACTIONS = {"error", "hang", "close", "result", "store", "unreadable", "job"}

DEFAULT_CONFIG: dict[str, Any] = {
    "application": {"name": "FakeApp", "version": "1.0.0"},
    "protocol_version": PROTOCOL_VERSION,
    "plugin": {"name": "fakehost-plugin", "version": "1.0.0", "version_on_disk": "1.0.0"},
    "host_component": False,
    "instances": [{"id": "fake-1", "documents": [{"id": "doc-1", "name": "doc-1.fake"}]}],
    "files": [{"id": "file-1", "name": "file-1.fake"}],
    "devices": [{"id": "dev-1", "model": "FakeDevice", "firmware": "1.0.0", "state": "ready", "simulated": True}],
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
    tool_changes: list[dict[str, Any]] = field(default_factory=list)
    external_changes: list[dict[str, Any]] = field(default_factory=list)
    history: list[tuple[str, dict[str, dict[str, Any]]]] = field(default_factory=list)

    def key(self, obj: str | None = None) -> str:
        if self.path is None:
            return f"untitled:{self.session}/{self.untitled}"
        return file_key(self.path) + (f"#/{obj}" if obj else "")

    def view(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id, "path": self.path, "session": self.session,
            "revision": f"r{self.revision}", "dirty": self.dirty, "readonly": self.readonly,
        }
        if self.path is not None:
            out["disk"] = self.disk
        return out

    def write_file(self) -> None:
        if self.path is not None:
            Path(self.path).write_text(json.dumps({"objects": self.objects}, sort_keys=True), encoding="utf-8")


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
        data = json.loads(Path(contract or CONTRACT).read_text(encoding="utf-8"))
        self.suffixes = {u["quantity"]: u["suffix"] for u in data["units"]}
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
            self.instances: dict[str, Instance] = {}
            self.documents: dict[str, Document] = {}
            self.devices = {d["id"]: dict(d) for d in cfg["devices"]}
            self.jobs: dict[str, Job] = {}
            self.faults: list[dict[str, Any]] = []
            self.calls: list[dict[str, Any]] = []
            self.applied: list[dict[str, Any]] = []
            self.violations: list[str] = []
            self.counter = 0
            self._pending_jobs: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
            for spec in cfg["instances"]:
                inst = self._add_instance(spec.get("id"), owned=False)
                for doc in spec.get("documents", []):
                    self._add_document(doc, inst.id)
            for doc in cfg["files"]:
                self._add_document(doc, None)

    def _next(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}-{self.counter}"

    def _add_instance(self, instance_id: str | None, owned: bool) -> Instance:
        inst = Instance(id=instance_id or self._next("fake"), pid=os.getpid(), owned=owned)
        if self.host_component:
            inst.plugin_loaded = self.plugin["version"]
        self.instances[inst.id] = inst
        return inst

    def _add_document(self, spec: dict[str, Any], session: str | None) -> Document:
        doc_id = spec.get("id") or self._next("doc")
        name = spec.get("name", f"{doc_id}.fake")
        path = None if spec.get("untitled") else str(self.workdir / name)
        doc = Document(id=doc_id, path=path, session=session, objects=copy.deepcopy(spec.get("objects", {})))
        if path is None:
            inst = self.instances[session]
            inst.untitled += 1
            doc.untitled = inst.untitled
        else:
            doc.write_file()
        self.documents[doc.id] = doc
        return doc

    def state(self) -> dict[str, Any]:
        """Everything a test may check, as plain data."""
        with self.lock:
            return copy.deepcopy({
                "instances": [self._session_view(i) for i in self.instances.values()],
                "documents": [
                    {**d.view(), "objects": d.objects, "external_changes": d.external_changes}
                    for d in self.documents.values()
                ],
                "devices": list(self.devices.values()),
                "jobs": [vars(j) for j in self.jobs.values()],
                "plugin": self.plugin,
                "calls": self.calls,
                "applied": self.applied,
                "violations": self.violations,
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
        if inst.since_at and inst.state in ("busy", "unresponsive", "blocked"):
            out["since_at"] = inst.since_at
        if inst.state == "unresponsive" and "since_at" not in out:
            out["since_at"] = utc_now()
        return out

    # ------------------------------------------------------------------ dispatch

    def handle(self, method: str, params: dict[str, Any], endpoint: str | None = None) -> Any:
        """Run one call, with the faults that match it. ``endpoint`` is the instance a host
        component connection belongs to, or ``None`` for the fake host's main address."""
        with self.lock:
            entry = {"seq": len(self.calls) + 1, "endpoint": endpoint or "main", "method": method, "params": params}
            self.calls.append(entry)
            self._check_request(method, params)
            if endpoint is not None and method in INSTANCE_SIDE:
                if params.get("session", endpoint) != endpoint:
                    self.violations.append(f"{method}: session {params['session']} sent to the host of {endpoint}")
                params = {**params, "session": endpoint}
            if method == "hello":
                handler = lambda p: self._hello(p, endpoint)  # noqa: E731
            else:
                handler = getattr(self, f"cap_{method}", None)
            if handler is None or (endpoint is not None and method not in INSTANCE_SIDE + ["hello"]):
                entry["outcome"] = "error"
                raise HostError("E_UNSUPPORTED", f"{method} is not a method of this host")
            rule = self._take_fault(method, params)
            try:
                result = self._run(handler, method, params, rule)
            except HostError as exc:
                entry["outcome"] = "error"
                entry["error"] = exc.data["code"]
                raise
            except Hang:
                entry["outcome"] = "hang"
                raise
            except Close:
                entry["outcome"] = "close"
                raise
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                self.violations.append(f"{method}: malformed request ({type(exc).__name__}: {exc})")
                entry["outcome"] = "error"
                entry["error"] = "E_VALIDATION"
                raise HostError("E_VALIDATION", f"malformed {method} request: {exc}") from exc
            entry["outcome"] = "result"
            return result

    def _run(self, handler: Any, method: str, params: dict[str, Any], rule: dict[str, Any] | None) -> Any:
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
        if action in ("store", "unreadable", "job"):
            return handler(params, rule)
        result = handler(params)
        if action == "result":
            _merge(result, rule.get("result", {}))
        return result

    def _check_request(self, method: str, params: Any) -> None:
        if not isinstance(params, dict):
            self.violations.append(f"{method}: params is not an object")
            return
        deadline = params.get("deadline_ms")
        if not isinstance(deadline, int) or isinstance(deadline, bool) or deadline < 1:
            self.violations.append(f"{method}: deadline_ms missing or not a positive integer")
        if method in WRITE_METHODS and not params.get("operation_id"):
            self.violations.append(f"{method}: a write without operation_id")
        if method == "hello" and not (params.get("protocol_version") and params.get("cli_version")):
            self.violations.append("hello: protocol_version and cli_version are required")

    def _hello(self, params: dict[str, Any], endpoint: str | None) -> dict[str, Any]:
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
            "methods": ["hello", *INSTANCE_SIDE],
        }

    # ------------------------------------------------------------------ faults

    def add_fault(self, rule: dict[str, Any]) -> None:
        if rule.get("action") not in FAULT_ACTIONS:
            raise ValueError(f"unknown fault action {rule.get('action')!r}")
        if "method" not in rule:
            raise ValueError("a fault needs a method")
        only = {"store": "apply", "job": "apply", "unreadable": "read_back"}.get(rule["action"])
        if only and rule["method"] != only:
            raise ValueError(f"the {rule['action']} fault works only on {only}")
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

    def _gate(self, params: dict[str, Any], halt: bool = False) -> None:
        """Refuse a call the way a real instance or device would in its current state."""
        session = params.get("session")
        if session:
            inst = self._instance(session)
            if inst.state == "unresponsive":
                raise Hang()
            if inst.state == "lost":
                raise Close()
            if inst.state == "closed":
                raise HostError("E_NOT_FOUND", f"instance {session} is closed")
            if not halt and inst.state in ("busy", "starting"):
                raise HostError("E_BUSY", "the main thread is busy", retry_after_ms=500)
            if not halt and inst.state == "blocked":
                blocker = inst.blocker or {"action": "dismiss_dialog"}
                raise HostError("E_HUMAN_REQUIRED", "a dialog blocks the application", action=blocker["action"])
        device = params.get("device")
        if device:
            dev = self.devices.get(device)
            if dev is None:
                raise HostError("E_NOT_FOUND", f"no device {device!r}")
            if dev["state"] == "offline":
                raise Close()
            if not halt and dev["state"] == "busy":
                raise HostError("E_BUSY", "the device is busy", retry_after_ms=500)

    def _document(self, params: dict[str, Any], required: bool = True) -> Document | None:
        ref = params.get("document")
        if ref is None:
            if required:
                raise HostError("E_NOT_FOUND", "the call names no document")
            return None
        for doc in self.documents.values():
            if ref in (doc.id, doc.path) or (doc.path and ref == file_key(doc.path)):
                if params.get("session") and doc.session not in (None, params["session"]):
                    break
                return doc
        raise HostError("E_NOT_FOUND", f"no document {ref!r}")

    # ------------------------------------------------------------------ generic domain answer

    def _registered(self, command: str) -> dict[str, dict[str, Any]] | None:
        """Input key -> flag, for a registered command; ``None`` when the command is unknown."""
        reg = self.commands.get(command)
        if reg is None:
            return None
        keys = {}
        for flag in reg.get("flags", []):
            key = flag["name"][2:].replace("-", "_")
            if flag.get("quantity"):
                key += self.suffixes[flag["quantity"]]
            keys[key] = flag
        return keys

    def _plan(self, params: dict[str, Any]) -> dict[str, Any]:
        """The targets, the changed fields and the output files of a domain command call."""
        command = params["command"]
        reg = self.commands.get(command, {})
        flags = self._registered(command)
        inputs = params.get("inputs") or {}

        def is_field(key: str) -> bool:
            if key in SELECT:
                return False
            if flags is None:
                return True
            return key in flags and not flags[key].get("output")

        common = {k: v for k, v in inputs.items() if is_field(k)}
        outputs = [str(v) for k, v in inputs.items() if flags and k in flags and flags[k].get("output")]
        selected: list[tuple[str, dict[str, Any]]] = []
        if isinstance(inputs.get("items"), list):
            for item in inputs["items"]:
                own = {k: v for k, v in item.items() if is_field(k)}
                selected.append((str(item["id"]), {**common, **own}))
        else:
            for obj in _selected(inputs):
                selected.append((obj, dict(common)))

        doc = self._document(params, required=False)
        device = params.get("device")
        if doc is None and device is None and params.get("session"):
            docs = [d for d in self.documents.values() if d.session == params["session"]]
            doc = docs[0] if docs else None
        targets = []
        for obj, fields in selected:
            if doc is not None:
                if obj in doc.missing:
                    raise HostError("E_NOT_FOUND", f"no object {obj!r} in {doc.id}")
                targets.append({"key": doc.key(obj), "object": obj, "fields": fields})
            elif device is not None:
                targets.append({"key": f"device:{device}/{obj}", "object": obj, "fields": fields})
            else:
                raise HostError("E_NOT_FOUND", "the call names no document or device")
        if not selected and not outputs:
            if doc is not None:
                targets.append({"key": doc.key(), "object": None, "fields": common})
            elif device is not None:
                targets.append({"key": f"device:{device}", "object": None, "fields": common})
            else:
                raise HostError("E_NOT_FOUND", "the call names no document or device")
        return {
            "command": command, "reg": reg, "doc": doc, "device": device, "targets": targets,
            "outputs": outputs, "artifact": "artifact" in reg.get("effects", []),
            "halt": bool(reg.get("halt")),
        }

    def _values(self, plan: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
        doc, obj = plan["doc"], target["object"]
        if doc is not None:
            if obj is None:
                return doc.objects.setdefault("", {})
            return doc.objects.setdefault(obj, {})
        dev = self.devices[plan["device"]]
        return dev.setdefault("values", {}).setdefault(obj or "", {})

    def _changes(self, plan: dict[str, Any]) -> list[dict[str, Any]]:
        changes = []
        for target in plan["targets"]:
            values = self._values(plan, target)
            fields = target["fields"] or {"last_command": plan["command"]}
            for name, after in fields.items():
                changes.append({"target": target["key"], "field": name, "before": values.get(name), "after": after})
        for path in plan["outputs"]:
            changes.append({"target": file_key(path), "field": "exists", "before": os.path.exists(path), "after": True})
        return changes

    def cap_read(self, params: dict[str, Any]) -> dict[str, Any]:
        self._gate(params)
        plan = self._plan(params)
        objects = []
        for target in plan["targets"]:
            values = self._values(plan, target)
            objects.append({"key": target["key"], "id": target["object"], **values})
        return {"result": {"items": objects}}

    def cap_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        self._gate(params)
        if params["command"] == "doc save":
            doc = self._document(params)
            assert doc is not None
            return {
                "action": "save",
                "targets": [{"key": doc.key(), "kind": "document"}],
                "changes": [{**c, "origin": "tool"} for c in doc.tool_changes],
                "external_changes": copy.deepcopy(doc.external_changes),
                "can_apply": True,
            }
        plan = self._plan(params)
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
            self._pending_jobs[job.id] = (params, plan)
            return {
                "dispatch_state": "dispatched", "change": "not_applied", "delivery": "not_applicable",
                "persistence": "unchanged", "job": {"id": job.id, "state": "running"},
            }
        stored = rule.get("values", {}) if rule is not None and rule["action"] == "store" else {}
        return self._do_apply(params, plan, stored)

    def _do_apply(self, params: dict[str, Any], plan: dict[str, Any], stored: dict[str, Any]) -> dict[str, Any]:
        doc = plan["doc"]
        changes = self._changes(plan)
        if doc is not None:
            doc.history.append((params["operation_id"], copy.deepcopy(doc.objects)))
        for target in plan["targets"]:
            values = self._values(plan, target)
            fields = target["fields"] or {"last_command": plan["command"]}
            for name, value in fields.items():
                values[name] = stored.get(name, value)
        files = []
        for path in plan["outputs"]:
            data = json.dumps({"command": plan["command"], "inputs": params.get("inputs")}, sort_keys=True).encode()
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(data)
            files.append({"path": path, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        self.applied.append({
            "operation_id": params["operation_id"], "command": plan["command"],
            "targets": [t["key"] for t in plan["targets"]] + [file_key(p) for p in plan["outputs"]],
        })
        if plan["artifact"]:
            return {
                "dispatch_state": "dispatched", "change": "not_applicable", "delivery": "not_applicable",
                "persistence": "saved", "files": files,
            }
        if doc is not None:
            doc.revision += 1
            doc.tool_changes.extend(c for c in changes if c["field"] != "exists")
            if doc.session is None:
                doc.write_file()
                return {"dispatch_state": "dispatched", "change": "applied", "delivery": "not_applicable", "persistence": "saved"}
            doc.dirty = True
            return {"dispatch_state": "dispatched", "change": "applied", "delivery": "not_applicable", "persistence": "unchanged"}
        return {"dispatch_state": "dispatched", "change": "applied", "delivery": "delivered", "persistence": "not_applicable"}

    def cap_read_back(self, params: dict[str, Any], rule: dict[str, Any] | None = None) -> dict[str, Any]:
        self._gate(params)
        plan = self._plan(params)
        wanted_targets = set(params.get("targets") or [t["key"] for t in plan["targets"]] + [file_key(p) for p in plan["outputs"]])
        wanted_fields = params.get("fields")
        unreadable = set(rule.get("fields", [])) if rule is not None and rule["action"] == "unreadable" else set()
        observed: dict[str, dict[str, Any]] = {}
        for target in plan["targets"]:
            if target["key"] not in wanted_targets:
                continue
            values = self._values(plan, target)
            names = wanted_fields or list(target["fields"]) or ["last_command"]
            observed[target["key"]] = {n: values.get(n) for n in names if n not in unreadable}
        for path in plan["outputs"]:
            if file_key(path) in wanted_targets:
                observed[file_key(path)] = {"exists": os.path.exists(path)}
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
        inst = self._add_instance(None, owned=True)
        if params.get("path"):
            self._add_document({"id": self._next("doc"), "name": Path(params["path"]).name}, inst.id)
        return {"dispatch_state": "dispatched", "change": "applied", "delivery": "not_applicable",
                "persistence": "not_applicable", "session": self._session_view(inst)}

    def cap_devices(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"items": [{k: v for k, v in d.items() if k != "values"} for d in self.devices.values()]}

    def cap_plugin_status(self, params: dict[str, Any]) -> dict[str, Any]:
        loaded = [{"session": i.id, "version": i.plugin_loaded} for i in self.instances.values() if i.plugin_loaded]
        installed = self.plugin_state_dir is not None or self.host_component
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
        return {"dispatch_state": "dispatched", "change": "applied", "delivery": "not_applicable",
                "persistence": "saved", "install_path": str(self.workdir / "plugin"), "version": version}

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
        elif params.get("path"):
            docs = [d for d in self.documents.values() if d.session is None and d.path and d.path.startswith(params["path"])]
        else:
            docs = [d for d in self.documents.values() if d.session is None]
        return {"items": [d.view() for d in docs]}

    def cap_create_doc(self, params: dict[str, Any]) -> dict[str, Any]:
        self._gate(params)
        doc = self._add_document({"id": self._next("doc"), "untitled": True}, params["session"])
        return {"dispatch_state": "dispatched", "change": "applied", "delivery": "not_applicable",
                "persistence": "unchanged", "document": doc.view()}

    def cap_open_doc(self, params: dict[str, Any]) -> dict[str, Any]:
        self._gate(params)
        path = Path(params["path"])
        if not path.is_file():
            raise HostError("E_NOT_FOUND", f"no file {params['path']}")
        doc = Document(id=self._next("doc"), path=str(path), session=params["session"])
        try:
            doc.objects = json.loads(path.read_text(encoding="utf-8")).get("objects", {})
        except (ValueError, OSError) as exc:
            raise HostError("E_VALIDATION", f"cannot read {path}", native_message=str(exc)) from exc
        self.documents[doc.id] = doc
        return {"dispatch_state": "dispatched", "change": "applied", "delivery": "not_applicable",
                "persistence": "unchanged", "document": doc.view()}

    def cap_save_doc(self, params: dict[str, Any]) -> dict[str, Any]:
        self._gate(params)
        doc = self._document(params)
        assert doc is not None
        if doc.path is None:
            raise HostError("E_VALIDATION", "an untitled document needs save-as")
        doc.write_file()
        doc.dirty, doc.disk = False, "in_sync"
        doc.revision += 1
        doc.tool_changes.clear()
        doc.external_changes.clear()
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
        doc.path, doc.untitled = str(path), 0
        doc.write_file()
        data = path.read_bytes()
        doc.dirty, doc.disk = False, "in_sync"
        doc.revision += 1
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
        self._gate(params)
        doc = self._document(params)
        assert doc is not None
        if not doc.history:
            raise HostError("E_NATIVE_FAILURE", "nothing to undo")
        _, doc.objects = doc.history.pop()
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
            else:
                job.done += 1
                if job.done >= job.total:
                    params_plan = self._pending_jobs.pop(job.id)
                    facts = self._do_apply(*params_plan, {})
                    job.state = "completed"
                    return {"state": "completed", "progress": {"done": job.total, "total": job.total, "unit": "steps"},
                            **{k: facts[k] for k in ("change", "delivery", "persistence")}}
        out: dict[str, Any] = {"state": job.state, "progress": {"done": job.done, "total": job.total, "unit": "steps"}}
        if job.state == "blocked":
            out["action"] = job.action or "dismiss_dialog"
        if job.state == "cancelled":
            out.update({"change": "not_applied", "delivery": "not_applicable", "persistence": "unchanged"})
        return out

    def cap_cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        job = self.jobs.get(params["job"])
        if job is None:
            raise HostError("E_NOT_FOUND", f"no job {params['job']!r}")
        job.cancel_requested = True
        return {"dispatch_state": "dispatched"}

    # ------------------------------------------------------------------ control (tests only)

    def set_session(self, session: str, state: str, title: str | None = None, action: str = "dismiss_dialog") -> None:
        with self.lock:
            inst = self._instance(session)
            inst.state = state
            inst.since_at = utc_now()
            inst.blocker = {"action": action, "title": title or "Fake dialog"} if state == "blocked" else None

    def restart_session(self, session: str) -> None:
        with self.lock:
            inst = self._instance(session)
            inst.generation += 1
            inst.state = "ready"

    def add_session(self, session: str | None = None) -> str:
        with self.lock:
            inst = self._add_instance(session, owned=False)
            self._add_document({"id": self._next("doc")}, inst.id)
            return inst.id

    def set_device(self, device: str, state: str) -> None:
        with self.lock:
            self.devices[device]["state"] = state

    def edit(self, document: str, obj: str, name: str, value: Any) -> None:
        """A person changes a document in the application (DCLI-277)."""
        with self.lock:
            doc = self._document({"document": document})
            assert doc is not None
            values = doc.objects.setdefault(obj, {})
            before = values.get(name)
            values[name] = value
            doc.dirty = True
            doc.revision += 1
            doc.external_changes.append({"target": doc.key(obj), "field": name, "before": before, "after": value, "origin": "external"})

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
