"""Content-Length framing of the host protocol (DCLI-272).

A message is the header line ``Content-Length: <bytes>``, an empty line, then the JSON body
in UTF-8. The header line and the empty line each end with CRLF.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

HEADER = re.compile(rb"Content-Length: ([0-9]{1,9})\r\n\r\n")
MAX_HEADER = 32
MAX_BODY = 64 * 1024 * 1024
CHUNK = 65536


class FramingError(Exception):
    """The peer sent bytes that are not a framed JSON message."""


class Channel:
    """Framed messages over one byte stream.

    ``recv(n)`` returns up to ``n`` bytes and ``b""`` at the end of the stream, ``send(data)``
    writes every byte, ``close()`` ends the stream and ``settimeout(seconds)`` bounds each
    ``recv`` (``None`` waits without limit; a timeout raises ``TimeoutError``).
    """

    def __init__(
        self,
        recv: Callable[[int], bytes],
        send: Callable[[bytes], None],
        close: Callable[[], None],
        settimeout: Callable[[float | None], None],
    ) -> None:
        self._recv = recv
        self._send = send
        self._close = close
        self._settimeout = settimeout
        self._buffer = b""
        self.closed = False

    def settimeout(self, seconds: float | None) -> None:
        self._settimeout(seconds)

    def _fill(self) -> bool:
        chunk = self._recv(CHUNK)
        if not chunk:
            return False
        self._buffer += chunk
        return True

    def read_message(self) -> Any:
        """Return the next message, or ``None`` when the peer closed the stream between messages."""
        while True:
            end = self._buffer.find(b"\r\n\r\n")
            if end != -1:
                break
            if len(self._buffer) > MAX_HEADER:
                raise FramingError("the header is too long")
            if not self._fill():
                if self._buffer:
                    raise FramingError("the stream ended inside a header")
                return None
        match = HEADER.fullmatch(self._buffer[: end + 4])
        if not match:
            raise FramingError(f"bad header {self._buffer[:end]!r}")
        size = int(match.group(1))
        if size > MAX_BODY:
            raise FramingError("the body is too large")
        self._buffer = self._buffer[end + 4 :]
        while len(self._buffer) < size:
            if not self._fill():
                raise FramingError("the stream ended inside a body")
        body, self._buffer = self._buffer[:size], self._buffer[size:]
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise FramingError(f"the body is not UTF-8 JSON: {exc}") from exc

    def write_message(self, message: Any) -> None:
        body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._send(b"Content-Length: %d\r\n\r\n" % len(body) + body)

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self._close()
