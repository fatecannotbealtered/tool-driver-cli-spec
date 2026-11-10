"""Local transport of the host protocol (DCLI-270).

A named pipe on Windows and a Unix socket on macOS and Linux. Listeners accept local
connections only: the pipe rejects remote clients and the socket file is readable and
writable by its owner alone, inside a private directory.
"""
from __future__ import annotations

import os
import socket
import sys
import tempfile
import threading
import time
import uuid

from .framing import Channel

WINDOWS = sys.platform == "win32"

if WINDOWS:
    import _winapi

    _BUFSIZE = 65536
    _PIPE_TYPE_BYTE = 0x00000000
    _PIPE_READMODE_BYTE = 0x00000000
    _PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
    _GONE = {2, 109, 232, 233}  # file not found, broken pipe, no data, pipe not connected


class Listener:
    """Accepts connections on one address. ``accept`` returns ``None`` once closed."""

    address: str

    def accept(self) -> Channel | None:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError


def private_dir() -> str | None:
    """A short private directory for Unix sockets, whose paths are limited to about 100 bytes."""
    if WINDOWS:
        return None
    return tempfile.mkdtemp(prefix="fh-", dir="/tmp" if os.path.isdir("/tmp") else None)


def new_address(name: str, directory: str | None) -> str:
    """A fresh address. ``directory`` is the private directory of ``private_dir`` on Unix."""
    if WINDOWS:
        return rf"\\.\pipe\fakehost-{os.getpid()}-{uuid.uuid4().hex[:12]}-{name}"
    assert directory is not None
    return os.path.join(directory, f"{name}-{uuid.uuid4().hex[:6]}.sock")


def listen(address: str) -> Listener:
    return _PipeListener(address) if WINDOWS else _UnixListener(address)


def connect(address: str, timeout: float = 5.0) -> Channel:
    """Connect to a listener. Raises ``ConnectionError`` when nothing listens there."""
    return _pipe_connect(address, timeout) if WINDOWS else _unix_connect(address, timeout)


# ------------------------------------------------------------------ Unix sockets


def _socket_channel(sock: socket.socket) -> Channel:
    def recv(n: int) -> bytes:
        try:
            return sock.recv(n)
        except (ConnectionResetError, BrokenPipeError):
            return b""

    def close() -> None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        sock.close()

    sock.settimeout(None)
    return Channel(recv, sock.sendall, close, sock.settimeout)


class _UnixListener(Listener):
    def __init__(self, address: str) -> None:
        self.address = address
        self._closed = False
        # The socket lives in a private 0700 directory (private_dir), so only its owner reaches it.
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(address)
        self._sock.listen(16)
        self._sock.settimeout(0.2)

    def accept(self) -> Channel | None:
        while not self._closed:
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return None
            return _socket_channel(conn)
        return None

    def close(self) -> None:
        self._closed = True
        self._sock.close()
        try:
            os.unlink(self.address)
        except FileNotFoundError:
            pass


def _unix_connect(address: str, timeout: float) -> Channel:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(address)
    except OSError as exc:
        sock.close()
        raise ConnectionError(f"cannot connect to {address}: {exc}") from exc
    return _socket_channel(sock)


# ------------------------------------------------------------------ Windows named pipes


def _pipe_channel(handle: int) -> Channel:
    timeout = {"ms": _winapi.INFINITE if WINDOWS else None}

    def wait(ov) -> None:
        if _winapi.WaitForMultipleObjects([ov.event], False, timeout["ms"]) == _winapi.WAIT_TIMEOUT:
            ov.cancel()
            try:
                ov.GetOverlappedResult(True)
            except OSError:
                pass
            raise TimeoutError("nothing arrived before the deadline")

    def recv(n: int) -> bytes:
        try:
            ov, err = _winapi.ReadFile(handle, n, overlapped=True)
            if err == _winapi.ERROR_IO_PENDING:
                wait(ov)
            _, err = ov.GetOverlappedResult(True)
        except OSError as exc:
            if exc.winerror in _GONE:
                return b""
            raise
        if err in _GONE:
            return b""
        return bytes(ov.getbuffer())

    def send(data: bytes) -> None:
        try:
            ov, err = _winapi.WriteFile(handle, data, overlapped=True)
            if err == _winapi.ERROR_IO_PENDING:
                _winapi.WaitForMultipleObjects([ov.event], False, _winapi.INFINITE)
            _, err = ov.GetOverlappedResult(True)
        except OSError as exc:
            if exc.winerror in _GONE:
                raise BrokenPipeError(str(exc)) from exc
            raise
        if err:
            raise BrokenPipeError(f"write failed with error {err}")

    def close() -> None:
        try:
            _winapi.CloseHandle(handle)
        except OSError:
            pass

    def settimeout(seconds: float | None) -> None:
        timeout["ms"] = _winapi.INFINITE if seconds is None else max(1, int(seconds * 1000))

    return Channel(recv, send, close, settimeout)


class _PipeListener(Listener):
    def __init__(self, address: str) -> None:
        self.address = address
        self._closed = False
        self._lock = threading.Lock()
        self._next: int | None = self._create(first=True)

    def _create(self, first: bool = False) -> int:
        mode = _winapi.PIPE_ACCESS_DUPLEX | _winapi.FILE_FLAG_OVERLAPPED
        if first:
            mode |= _winapi.FILE_FLAG_FIRST_PIPE_INSTANCE
        return _winapi.CreateNamedPipe(
            self.address,
            mode,
            _PIPE_TYPE_BYTE | _PIPE_READMODE_BYTE | _winapi.PIPE_WAIT | _PIPE_REJECT_REMOTE_CLIENTS,
            _winapi.PIPE_UNLIMITED_INSTANCES,
            _BUFSIZE,
            _BUFSIZE,
            _winapi.NMPWAIT_WAIT_FOREVER,
            _winapi.NULL,
        )

    def accept(self) -> Channel | None:
        with self._lock:
            if self._closed or self._next is None:
                return None
            handle, self._next = self._next, self._create()
        try:
            ov = _winapi.ConnectNamedPipe(handle, overlapped=True)
        except OSError as exc:
            if exc.winerror not in (_winapi.ERROR_NO_DATA, _winapi.ERROR_PIPE_CONNECTED):
                _winapi.CloseHandle(handle)
                raise
        else:
            _winapi.WaitForMultipleObjects([ov.event], False, _winapi.INFINITE)
            try:
                ov.GetOverlappedResult(True)
            except OSError:
                pass
        if self._closed:
            _winapi.CloseHandle(handle)
            return None
        return _pipe_channel(handle)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._next is not None:
                _winapi.CloseHandle(self._next)
                self._next = None
        # Wake an accept that waits on the remaining pipe instance.
        try:
            _pipe_connect(self.address, 0.2).close()
        except ConnectionError:
            pass


def _pipe_connect(address: str, timeout: float) -> Channel:
    deadline = time.monotonic() + timeout
    while True:
        try:
            _winapi.WaitNamedPipe(address, max(1, int(timeout * 1000)))
            handle = _winapi.CreateFile(
                address,
                _winapi.GENERIC_READ | _winapi.GENERIC_WRITE,
                0,
                _winapi.NULL,
                _winapi.OPEN_EXISTING,
                _winapi.FILE_FLAG_OVERLAPPED,
                _winapi.NULL,
            )
            return _pipe_channel(handle)
        except OSError as exc:
            busy = exc.winerror in (_winapi.ERROR_SEM_TIMEOUT, _winapi.ERROR_PIPE_BUSY)
            if not busy or time.monotonic() >= deadline:
                raise ConnectionError(f"cannot connect to {address}: {exc}") from exc
            time.sleep(0.01)
