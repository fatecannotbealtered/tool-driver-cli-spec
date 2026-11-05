"""The fake host: one main address, one host endpoint per instance, and discovery files.

The main address answers every adapter capability, CLI-side and instance-side, with the
framing and handshake of the host protocol (DVER-023), plus the ``fake.*`` control methods
tests use. When the world has a host component, each instance also gets its own endpoint
and a discovery file under ``hosts/`` in the state directory (DCLI-271), and answers
``hello`` and the instance-side methods there (DCLI-274).
"""
from __future__ import annotations

import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any

from . import transport
from .framing import Channel, FramingError
from .world import Close, Hang, HostError, World, utc_now

_HANG = object()
_CLOSE = object()
_LIVE = ("starting", "ready", "busy", "blocked", "unresponsive", "unreachable")


class FakeHost:
    def __init__(
        self,
        state_dir: str | os.PathLike[str] | None = None,
        config: dict[str, Any] | None = None,
        commands: list[dict[str, Any]] | None = None,
        workdir: str | None = None,
        contract: str | os.PathLike[str] | None = None,
    ) -> None:
        self.world = World(config, commands, workdir, contract)
        self.state_dir = Path(state_dir) if state_dir else None
        self._dir = transport.private_dir()
        self.address = transport.new_address("main", self._dir)
        self._main: transport.Listener | None = None
        # One lock guards the endpoints, the discovery files, the open channels and stopping.
        self._lock = threading.RLock()
        self._endpoints: dict[str, tuple[transport.Listener, int]] = {}
        self._written: dict[str, tuple[str, str, str]] = {}
        self._lost: set[str] = set()
        self._channels: set[Channel] = set()
        self._shutdown = threading.Event()
        self.stopped = threading.Event()

    # ------------------------------------------------------------------ life cycle

    def start(self) -> FakeHost:
        self._main = transport.listen(self.address)
        self._spawn(self._accept_loop, self._main, None)
        self.sync()
        return self

    def stop(self) -> None:
        with self._lock:
            if self.stopped.is_set():
                return
            self.stopped.set()
            listeners = ([self._main] if self._main else []) + [entry[0] for entry in self._endpoints.values()]
            sessions = set(self._endpoints) | self._lost
            self._endpoints.clear()
            self._lost.clear()
            channels = list(self._channels)
        for listener in listeners:
            listener.close()
        for channel in channels:
            channel.close()
        for session in sessions:
            self._remove_discovery(session)
        if self._dir:
            shutil.rmtree(self._dir, ignore_errors=True)

    def __enter__(self) -> FakeHost:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    @staticmethod
    def _spawn(target: Any, *args: Any) -> None:
        threading.Thread(target=target, args=args, daemon=True).start()

    # ------------------------------------------------------------------ host endpoints

    def sync(self) -> None:
        """Give every live instance an endpoint and a discovery file, as a host component would."""
        if not self.world.host_component:
            return
        with self._lock:
            if self.stopped.is_set():
                return
            with self.world.lock:
                instances = {i.id: (i.state, i.generation) for i in self.world.instances.values()}
                versions = (self.world.protocol_version, self.world.plugin["version"], self.world.config["application"]["version"])
            for session, (state, generation) in instances.items():
                current = self._endpoints.get(session)
                if state in _LIVE and (current is None or current[1] != generation):
                    if current is not None:
                        current[0].close()
                    listener = transport.listen(transport.new_address(session, self._dir))
                    self._endpoints[session] = (listener, generation)
                    self._lost.discard(session)
                    self._write_discovery(session, listener.address, versions)
                    self._spawn(self._accept_loop, listener, session)
                elif state in _LIVE and self._written.get(session) != versions:
                    self._write_discovery(session, current[0].address, versions)
                elif state == "lost" and current is not None:
                    current[0].close()
                    self._endpoints.pop(session, None)
                    self._lost.add(session)
            for session in set(self._endpoints) | self._lost:
                if instances.get(session, ("closed", 0))[0] == "closed":
                    endpoint = self._endpoints.pop(session, None)
                    if endpoint is not None:
                        endpoint[0].close()
                    self._lost.discard(session)
                    self._remove_discovery(session)

    def _discovery_path(self, session: str) -> Path | None:
        return self.state_dir / "hosts" / f"{session}.json" if self.state_dir else None

    def _write_discovery(self, session: str, address: str, versions: tuple[str, str, str]) -> None:
        self._written[session] = versions
        path = self._discovery_path(session)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "address": address,
            "pid": os.getpid(),
            "application": dict(self.world.config["application"]),
            "protocol_version": versions[0],
            "plugin_version": versions[1],
            "started_at": utc_now(),
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def _remove_discovery(self, session: str) -> None:
        self._written.pop(session, None)
        path = self._discovery_path(session)
        if path is not None:
            path.unlink(missing_ok=True)

    # ------------------------------------------------------------------ connections

    def _accept_loop(self, listener: transport.Listener, endpoint: str | None) -> None:
        while True:
            try:
                channel = listener.accept()
            except OSError:
                return
            if channel is None:
                return
            with self._lock:
                if self.stopped.is_set():
                    channel.close()
                    return
                self._channels.add(channel)
            self._spawn(self._serve, channel, endpoint)

    def _serve(self, channel: Channel, endpoint: str | None) -> None:
        greeted = False
        try:
            while True:
                try:
                    message = channel.read_message()
                except FramingError as exc:
                    self._violation(f"framing: {exc}")
                    return
                if message is None:
                    return
                method = message.get("method") if isinstance(message, dict) else None
                if isinstance(method, str) and not method.startswith("fake."):
                    if not greeted and method != "hello":
                        self._violation(f"{method}: sent before hello")
                    greeted = True
                reply = self._reply(message, endpoint)
                if reply is _CLOSE:
                    return
                if reply is _HANG:
                    # The call never gets a reply; record anything else sent on this connection.
                    while (late := channel.read_message()) is not None:
                        late = late if isinstance(late, dict) else {}
                        self.world.record_ignored(late.get("method"), late.get("params"), endpoint)
                    return
                channel.write_message(reply)
        except (FramingError, OSError):
            return
        finally:
            channel.close()
            with self._lock:
                self._channels.discard(channel)
            if self._shutdown.is_set():
                self._spawn(self.stop)

    def _violation(self, text: str) -> None:
        with self.world.lock:
            self.world.violations.append(text)

    def _reply(self, message: Any, endpoint: str | None) -> Any:
        if (
            not isinstance(message, dict)
            or message.get("jsonrpc") != "2.0"
            or not isinstance(message.get("method"), str)
            or not isinstance(message.get("id"), (int, str))
            or isinstance(message.get("id"), bool)
            or not isinstance(message.get("params", {}), dict)
        ):
            self._violation(f"not a JSON-RPC 2.0 request: {str(message)[:200]}")
            rpc_id = message.get("id") if isinstance(message, dict) else None
            return _error(rpc_id, HostError("E_VALIDATION", "not a JSON-RPC 2.0 request"))
        rpc_id, method, params = message["id"], message["method"], message.get("params", {})
        if method.startswith("fake."):
            if endpoint is not None:
                return _error(rpc_id, HostError("E_UNSUPPORTED", "control methods are on the main address only"))
            try:
                result = self._control(method[5:], params)
            except (KeyError, ValueError, TypeError, HostError) as exc:
                return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32602, "message": f"{type(exc).__name__}: {exc}"}}
            return {"jsonrpc": "2.0", "id": rpc_id, "result": result}
        try:
            result = self.world.handle(method, params, endpoint)
        except HostError as exc:
            return _error(rpc_id, exc)
        except Hang:
            return _HANG
        except Close:
            return _CLOSE
        finally:
            self._sync_quietly()
        return {"jsonrpc": "2.0", "id": rpc_id, "result": result}

    def _sync_quietly(self) -> None:
        try:
            self.sync()
        except Exception as exc:  # noqa: BLE001 - never drop a reply because of the fake host's own fault
            with self.world.lock:
                self.world.internal_errors.append(f"sync: {type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------ control

    def _control(self, name: str, p: dict[str, Any]) -> Any:
        w = self.world
        if name == "state":
            state = w.state()
            with self._lock:
                state["endpoints"] = {s: entry[0].address for s, entry in self._endpoints.items()}
            return state
        actions = {
            "reset": lambda: w.reset(p.get("config"), p.get("commands")),
            "fault": lambda: w.add_fault(p["rule"]),
            "clear_faults": lambda: w.faults.clear(),
            "set_session": lambda: w.set_session(p["session"], p["state"], p.get("title"), p.get("action", "dismiss_dialog"), p.get("knowledge")),
            "restart_session": lambda: w.restart_session(p["session"]),
            "add_session": lambda: {"session": w.add_session(p.get("session"))},
            "set_device": lambda: w.set_device(p["device"], p["state"]),
            "edit": lambda: w.edit(p["document"], p["object"], p["field"], p["value"]),
            "set_disk": lambda: w.set_disk(p["document"], p["disk"]),
            "set_missing": lambda: w.set_missing(p["document"], p["objects"]),
            "set_job": lambda: w.set_job(p["job"], p["state"], p.get("action")),
            "configure": lambda: w.configure(p.get("protocol_version"), p.get("plugin")),
            "shutdown": self._request_shutdown,
        }
        if name not in actions:
            raise KeyError(f"unknown control method fake.{name}")
        if name == "reset":
            with self._lock:
                old = list(self._endpoints.items())
                sessions = set(self._endpoints) | self._lost
                self._endpoints.clear()
                self._lost.clear()
                for _, (listener, _) in old:
                    listener.close()
                for session in sessions:
                    self._remove_discovery(session)
        result = actions[name]()
        self.sync()
        return result if result is not None else {}

    def _request_shutdown(self) -> None:
        """Stop once the caller has closed its connection, so the reply still reaches it."""
        self._shutdown.set()
        timer = threading.Timer(2.0, self.stop)
        timer.daemon = True
        timer.start()


def _error(rpc_id: Any, exc: HostError) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32000, "message": str(exc), "data": exc.data}}
