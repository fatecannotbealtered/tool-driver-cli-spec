"""Operation records (DCLI-059), confirm tokens (DCLI-055, DSEC-033) and target locks (DCLI-060).

Records live in ``operations/<operation_id>.json``. Keys that start with ``_`` are the
runtime's own bookkeeping, such as the token and what it binds; ``operation get`` never
shows them. Locks live in ``locks/<operation_id>.json`` and are shared by every process of
the user. One mutex file serializes taking locks and spending tokens across processes.
"""
from __future__ import annotations

import os
import secrets
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .errors import DriverError
from .state import StateDir, read_json, write_json
from .targets import conflict

WINDOWS = sys.platform == "win32"
_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(text: str) -> datetime:
    return datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def public(record: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if not k.startswith("_")}


class Records:
    def __init__(self, state: StateDir, retention_days: int, id_prefix: str) -> None:
        self.state = state
        self.retention = timedelta(days=retention_days)
        self.prefix = id_prefix

    def _dir(self) -> Path:
        path = self.state.sub("operations")
        if not path.is_dir():
            raise DriverError("E_IO", f"The operation records cannot be written: {path} is not a directory. Nothing was sent.")
        return path

    def check_writable(self) -> None:
        """Every write is refused with E_IO when records cannot be written (DCLI-059)."""
        path = self._dir()
        probe = path / f".probe-{os.getpid()}-{secrets.token_hex(4)}"
        try:
            probe.write_bytes(b"")
            probe.unlink()
        except OSError as exc:
            raise DriverError("E_IO", f"The operation records cannot be written ({exc.strerror}); nothing was sent.") from None

    def new_id(self) -> str:
        return self.prefix + "".join(secrets.choice(_ALPHABET) for _ in range(16))

    def save(self, record: dict[str, Any]) -> None:
        write_json(self._dir() / f"{record['operation_id']}.json", record)

    def load(self, operation_id: str) -> dict[str, Any] | None:
        if not operation_id.startswith(self.prefix) or not operation_id[len(self.prefix):].isalnum():
            return None
        try:
            return read_json(self.state.path / "operations" / f"{operation_id}.json")
        except (OSError, ValueError):
            return None

    def all(self) -> list[dict[str, Any]]:
        """Every readable record, newest first."""
        folder = self.state.path / "operations"
        out = []
        if folder.is_dir():
            for path in folder.glob(f"{self.prefix}*.json"):
                try:
                    record = read_json(path)
                except (OSError, ValueError):
                    continue
                if isinstance(record, dict) and "operation_id" in record:
                    out.append(record)
        out.sort(key=lambda r: (r.get("_seq", 0), r.get("planned_at", "")), reverse=True)
        return out

    def purge(self) -> None:
        """Drop settled records older than the retention period (DCLI-059)."""
        cutoff = datetime.now(timezone.utc) - self.retention
        for record in self.all():
            if record.get("state") in ("dispatched", "unknown"):
                continue
            stamp = record.get("finished_at") or record.get("planned_at")
            if stamp and parse_utc(stamp) < cutoff:
                try:
                    (self.state.path / "operations" / f"{record['operation_id']}.json").unlink()
                except OSError:
                    pass

    def by_token(self, token: str) -> dict[str, Any] | None:
        for record in self.all():
            stored = record.get("_token", {}).get("value")
            if stored and secrets.compare_digest(stored, token):
                return record
        return None


class Mutex:
    """An exclusive lock on ``locks/.mutex`` shared by every process of the user."""

    def __init__(self, state: StateDir) -> None:
        self.state = state

    @contextmanager
    def hold(self, timeout: float = 10.0) -> Iterator[None]:
        path = self.state.sub("locks") / ".mutex"
        try:
            fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        except OSError as exc:
            raise DriverError("E_IO", f"Cannot open the lock file {path}: {exc.strerror}.") from None
        try:
            _lock(fd, timeout)
            try:
                yield
            finally:
                _unlock(fd)
        finally:
            os.close(fd)


def _lock(fd: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            if WINDOWS:
                import msvcrt

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise DriverError("E_BUSY", "Another call of this tool holds the state lock; nothing was sent.",
                                  retry_after_ms=1000) from None
            time.sleep(0.02)


def _unlock(fd: int) -> None:
    if WINDOWS:
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


def process_start(pid: int) -> int:
    from .adapter import start_time

    return start_time(pid)


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if WINDOWS:
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5  # access denied: it exists
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Locks:
    """Target locks (DCLI-060). An entry is held by a process, by a long job, or by a write
    whose outcome is unknown; only the last two outlive the process that took them."""

    def __init__(self, state: StateDir, records: Records, mutex: Mutex, tool: str) -> None:
        self.state = state
        self.records = records
        self.mutex = mutex
        self.tool = tool

    def _dir(self) -> Path:
        return self.state.sub("locks")

    def entries(self) -> list[dict[str, Any]]:
        """Every lock entry. A lock file that cannot be read counts as held: locks fail closed."""
        out = []
        folder = self.state.path / "locks"
        if folder.is_dir():
            for path in folder.glob("op_*.json"):
                try:
                    entry = read_json(path)
                except (OSError, ValueError):
                    entry = None
                if isinstance(entry, dict) and isinstance(entry.get("keys"), list):
                    out.append(entry)
                elif path.exists():
                    out.append({"operation_id": path.stem, "keys": [], "holder": "unreadable"})
        return out

    def _stale(self, entry: dict[str, Any]) -> bool:
        """A lock held by a process that is gone (its PID ended or now names a later process)."""
        if entry.get("holder") != "process":
            return False
        pid = int(entry.get("pid", 0))
        return not pid_alive(pid) or (entry.get("started") is not None and process_start(pid) != entry["started"])

    def _settle(self, entry: dict[str, Any]) -> bool:
        """Under the mutex: drop the lock of a process that died before dispatch. A death
        after dispatch leaves the write outcome unknown and the lock in place (DCLI-063)."""
        record = self.records.load(entry["operation_id"])
        if record is not None and record.get("state") == "dispatched":
            record["state"] = "unknown"
            self.records.save(record)
            write_json(self._dir() / f"{entry['operation_id']}.json", {**entry, "holder": "unknown", "pid": 0})
            return False
        self._remove(entry["operation_id"])
        return True

    def holders(self, keys: list[str], exclude: str | None = None, settle: bool = False) -> list[dict[str, Any]]:
        """The lock entries that conflict with any of ``keys``. Only a caller that holds the
        mutex may ``settle`` stale entries; others just skip a stale lock taken before dispatch."""
        found = []
        for entry in self.entries():
            if entry["operation_id"] == exclude:
                continue
            if entry["holder"] == "unreadable":
                found.append(entry)
                continue
            if self._stale(entry):
                if settle:
                    if self._settle(entry):
                        continue
                else:
                    record = self.records.load(entry["operation_id"])
                    if record is None or record.get("state") == "planned":
                        continue
            if any(conflict(a, b) for a in keys for b in entry.get("keys", [])):
                found.append(entry)
        return found

    def acquire_held(self, operation_id: str, keys: list[str]) -> None:
        """With the mutex held: lock ``keys`` for one operation, or fail with ``target_locked``."""
        busy = self.holders(keys, exclude=operation_id, settle=True)
        if busy:
            raise conflict_locked(busy[0], self.tool)
        entry = {"operation_id": operation_id, "keys": sorted(keys), "holder": "process", "pid": os.getpid(),
                 "started": process_start(os.getpid()), "locked_at": utc_now()}
        write_json(self._dir() / f"{operation_id}.json", entry)

    def acquire(self, operation_id: str, keys: list[str]) -> None:
        with self.mutex.hold():
            self.acquire_held(operation_id, keys)

    def hold_as(self, operation_id: str, holder: str, keys: list[str]) -> None:
        """Keep a lock after the process ends: for a long job, or an outcome-unknown write."""
        with self.mutex.hold():
            write_json(self._dir() / f"{operation_id}.json",
                       {"operation_id": operation_id, "keys": sorted(keys), "holder": holder, "pid": 0, "locked_at": utc_now()})

    def replace(self, operation_id: str, held: list[tuple[str, list[str]]]) -> None:
        """Release one lock and keep others in its place, with no gap between (DCLI-064)."""
        with self.mutex.hold():
            for child, keys in held:
                write_json(self._dir() / f"{child}.json",
                           {"operation_id": child, "keys": sorted(keys), "holder": "unknown", "pid": 0, "locked_at": utc_now()})
            self._remove(operation_id)

    def release(self, operation_id: str) -> None:
        with self.mutex.hold():
            self._remove(operation_id)

    def _remove(self, operation_id: str) -> None:
        path = self.state.path / "locks" / f"{operation_id}.json"
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise DriverError("E_IO", f"Cannot release the lock of {operation_id}: {exc.strerror}.") from None


def conflict_locked(entry: dict[str, Any], tool: str) -> DriverError:
    holder = entry.get("holder")
    op = entry["operation_id"]
    if holder == "unreadable":
        return DriverError("E_BUSY", f"The lock file of {op} cannot be read; nothing was sent.", retry_after_ms=1000)
    if holder == "unknown":
        action = f"Settle it first with `{tool} operation resolve --id {op}`."
    elif holder == "job":
        action = "Wait for the long job to end, then run the command again."
    else:
        action = "Wait for the other write to finish, then run the command again."
    return DriverError("E_CONFLICT", f"The target is locked by operation {op}; nothing was sent.",
                       conflict="target_locked", next_action=action)


def expiry(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def expired(stamp: str) -> bool:
    return parse_utc(stamp) <= datetime.now(timezone.utc)
