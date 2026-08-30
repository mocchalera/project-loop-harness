from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Iterable, Pattern

from .redaction import redact_bytes


_SCAN_OVERLAP_BYTES = 128
_LINE_BUFFER_BYTES = 4_096
_LINE_TAIL_BYTES = 2_048
_LINE_ELLIPSIS = b"...<bounded-line>..."


@dataclass(frozen=True)
class ErrorWindowResult:
    lines: tuple[str, ...]
    truncated: bool
    redacted: bool
    binary_omitted: bool

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


class BoundedErrorWindowCollector:
    """Retain only redacted lines that match a diagnostic pattern.

    The collector scans every byte incrementally while keeping only a bounded
    representation of the current line and a bounded set of matching lines.
    It is diagnostic-only: callers must keep the child result and normal pipe
    drainage authoritative if observation fails.
    """

    def __init__(
        self,
        *,
        stream_name: str,
        error_pattern: Pattern[str],
        redaction_patterns: Iterable[Pattern[str]],
        max_lines: int,
        max_bytes: int,
        max_line_bytes: int,
    ) -> None:
        self.stream_name = stream_name
        self.error_pattern = error_pattern
        self.redaction_patterns = tuple(redaction_patterns)
        self.max_lines = max_lines
        self.max_bytes = max_bytes
        self.max_line_bytes = max_line_bytes
        self._line_buffer = bytearray()
        self._line_tail = bytearray()
        self._line_length = 0
        self._scan_tail = b""
        self._line_matched = False
        self._lines: list[str] = []
        self._byte_count = 0
        self._truncated = False
        self._redacted = False
        self._binary_omitted = False
        self._finished = False

    def consume(self, chunk: bytes) -> None:
        if self._finished:
            return
        offset = 0
        while offset < len(chunk):
            newline = chunk.find(b"\n", offset)
            if newline < 0:
                self._consume_line_part(chunk[offset:])
                return
            self._consume_line_part(chunk[offset:newline])
            self._finish_line()
            offset = newline + 1

    def finish(self) -> ErrorWindowResult:
        if not self._finished:
            if self._line_length or self._line_matched:
                self._finish_line()
            self._finished = True
        return ErrorWindowResult(
            tuple(self._lines),
            self._truncated,
            self._redacted,
            self._binary_omitted,
        )

    def _consume_line_part(self, part: bytes) -> None:
        if not part:
            return
        scan = self._scan_tail + part
        if self.error_pattern.search(scan.decode("latin-1")):
            self._line_matched = True
        self._scan_tail = scan[-_SCAN_OVERLAP_BYTES:]
        self._line_length += len(part)
        remaining = _LINE_BUFFER_BYTES - len(self._line_buffer)
        if remaining > 0:
            self._line_buffer.extend(part[:remaining])
        if len(part) >= _LINE_TAIL_BYTES:
            self._line_tail = bytearray(part[-_LINE_TAIL_BYTES:])
        else:
            self._line_tail.extend(part)
            overflow = len(self._line_tail) - _LINE_TAIL_BYTES
            if overflow > 0:
                del self._line_tail[:overflow]

    def _finish_line(self) -> None:
        if self._line_matched:
            raw = self._bounded_raw_line()
            redacted, changed = redact_bytes(
                raw,
                additional_patterns=self.redaction_patterns,
            )
            self._redacted = self._redacted or changed
            if b"\x00" in redacted:
                self._binary_omitted = True
                self._truncated = True
            else:
                try:
                    text = redacted.decode("utf-8")
                except UnicodeDecodeError:
                    self._binary_omitted = True
                    self._truncated = True
                else:
                    self._append_line(self._format_line(text))
        self._line_buffer.clear()
        self._line_tail.clear()
        self._line_length = 0
        self._scan_tail = b""
        self._line_matched = False

    def _bounded_raw_line(self) -> bytes:
        if self._line_length <= len(self._line_buffer):
            return bytes(self._line_buffer)
        self._truncated = True
        return (
            bytes(self._line_buffer[: _LINE_BUFFER_BYTES // 2])
            + _LINE_ELLIPSIS
            + bytes(self._line_tail)
        )

    def _format_line(self, text: str) -> str:
        encoded = text.encode("utf-8", errors="replace")
        if len(encoded) <= self.max_line_bytes:
            return f"{self.stream_name} | {text}"
        self._truncated = True
        digest = hashlib.sha256(encoded).hexdigest()[:12]
        side = max(1, (self.max_line_bytes - 64) // 2)
        head = encoded[:side].decode("utf-8", errors="ignore")
        tail = encoded[-side:].decode("utf-8", errors="ignore")
        return f"{self.stream_name} | {head}...<sha256:{digest}>...{tail}"

    def _append_line(self, line: str) -> None:
        if len(self._lines) >= self.max_lines:
            self._truncated = True
            return
        encoded = line.encode("utf-8", errors="replace")
        separator = 1 if self._lines else 0
        if self._byte_count + separator + len(encoded) > self.max_bytes:
            self._truncated = True
            return
        self._lines.append(line)
        self._byte_count += separator + len(encoded)


def combine_error_windows(
    results: Iterable[ErrorWindowResult],
    *,
    max_lines: int,
    max_bytes: int,
) -> ErrorWindowResult:
    lines: list[str] = []
    byte_count = 0
    truncated = False
    redacted = False
    binary_omitted = False
    for result in results:
        truncated = truncated or result.truncated
        redacted = redacted or result.redacted
        binary_omitted = binary_omitted or result.binary_omitted
        for line in result.lines:
            if len(lines) >= max_lines:
                truncated = True
                break
            encoded = line.encode("utf-8", errors="replace")
            separator = 1 if lines else 0
            if byte_count + separator + len(encoded) > max_bytes:
                truncated = True
                break
            lines.append(line)
            byte_count += separator + len(encoded)
    return ErrorWindowResult(tuple(lines), truncated, redacted, binary_omitted)
