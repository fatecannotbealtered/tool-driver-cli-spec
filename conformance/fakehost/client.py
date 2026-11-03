"""A small host protocol client: connect, handshake, call (DCLI-272 to DCLI-278).

Tests use it to drive the fake host. It is also the reference for the CLI side of the
protocol: one connection per call sequence, ``hello`` first, ``deadline_ms`` on every
request, and a reply that never arrives is a timeout, not a failure.
"""
from __future__ import annotations

import itertools
from typing import Any

from . import transport
from .world import PROTOCOL_VERSION


class ConnectionClosed(Exception):
    """The host closed the connection before it replied."""


class ProtocolMismatch(Exception):
    """The host speaks another major version of the protocol (DCLI-273)."""


class HostCallError(Exception):
    """The host replied with an error. ``data`` holds ``code`` and ``dispatch_state``."""

    def __init__(self, error: dict[str, Any]) -> None:
        super().__init__(error.get("message", ""))
        self.rpc_code = error.get("code")
        self.data = error.get("data", {})
        self.code = self.data.get("code")


class Client:
    def __init__(
        self,
        address: str,
        timeout: float = 5.0,
        cli_version: str = "0.0.0",
        protocol_version: str = PROTOCOL_VERSION,
        handshake: bool = True,
    ) -> None:
        self.address = address
        self.timeout = timeout
        self.cli_version = cli_version
        self.protocol_version = protocol_version
        self.handshake = handshake
        self.channel = None
        self.hello: dict[str, Any] | None = None
        self._ids = itertools.count(1)

    def __enter__(self) -> Client:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def connect(self) -> None:
        self.channel = transport.connect(self.address, self.timeout)
        if self.handshake:
            self.hello = self.call("hello", {"protocol_version": self.protocol_version, "cli_version": self.cli_version})
            if self.hello["protocol_version"].split(".")[0] != self.protocol_version.split(".")[0]:
                self.close()
                raise ProtocolMismatch(f"host speaks {self.hello['protocol_version']}, client {self.protocol_version}")

    def call(self, method: str, params: dict[str, Any] | None = None, deadline_ms: int | None = None) -> Any:
        """Send one request and wait up to ``deadline_ms`` for the reply."""
        assert self.channel is not None, "connect first"
        deadline_ms = deadline_ms or int(self.timeout * 1000)
        body = dict(params or {})
        body.setdefault("deadline_ms", deadline_ms)
        rpc_id = next(self._ids)
        self.channel.settimeout(deadline_ms / 1000)
        try:
            self.channel.write_message({"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": body})
            reply = self.channel.read_message()
        except BrokenPipeError as exc:
            raise ConnectionClosed(str(exc)) from exc
        except TimeoutError:
            # A late reply must not be read as the answer to the next call.
            self.close()
            raise
        finally:
            if not self.channel.closed:
                self.channel.settimeout(None)
        if reply is None:
            raise ConnectionClosed(f"the host closed the connection before it replied to {method}")
        if reply.get("id") != rpc_id:
            raise ConnectionClosed(f"reply id {reply.get('id')!r} does not match request {rpc_id}")
        if "error" in reply:
            raise HostCallError(reply["error"])
        return reply["result"]

    def control(self, name: str, **params: Any) -> Any:
        """Call a ``fake.*`` control method of the fake host."""
        return self.call(f"fake.{name}", params)

    def close(self) -> None:
        if self.channel is not None:
            self.channel.close()
