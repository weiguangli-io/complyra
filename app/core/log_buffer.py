"""In-memory ring buffer for recent application log entries.

Captures the last N log records for real-time display in the admin
monitoring dashboard without requiring external log infrastructure.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import List, Optional


@dataclass
class LogEntry:
    timestamp: float
    level: str
    logger: str
    message: str
    request_id: str = ""
    extra: dict = field(default_factory=dict)


class LogBuffer:
    """Thread-safe ring buffer that stores recent log entries."""

    def __init__(self, maxlen: int = 2000):
        self._buffer: deque[LogEntry] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def append(self, entry: LogEntry) -> None:
        with self._lock:
            self._buffer.append(entry)

    def get_entries(
        self,
        limit: int = 100,
        level: Optional[str] = None,
        search: Optional[str] = None,
        since: Optional[float] = None,
    ) -> List[dict]:
        with self._lock:
            entries = list(self._buffer)

        # Filter
        if since:
            entries = [e for e in entries if e.timestamp >= since]
        if level:
            entries = [e for e in entries if e.level == level.upper()]
        if search:
            search_lower = search.lower()
            entries = [
                e for e in entries
                if search_lower in e.message.lower()
                or search_lower in e.logger.lower()
            ]

        # Return most recent first
        entries.reverse()
        return [asdict(e) for e in entries[:limit]]

    def count_by_level(self) -> dict:
        with self._lock:
            entries = list(self._buffer)
        counts = {"DEBUG": 0, "INFO": 0, "WARNING": 0, "ERROR": 0, "CRITICAL": 0}
        for e in entries:
            if e.level in counts:
                counts[e.level] += 1
        return counts


# Global singleton
_buffer = LogBuffer(maxlen=2000)


def get_log_buffer() -> LogBuffer:
    return _buffer


class BufferHandler(logging.Handler):
    """Logging handler that writes to the in-memory ring buffer."""

    def emit(self, record: logging.LogRecord) -> None:
        entry = LogEntry(
            timestamp=record.created,
            level=record.levelname,
            logger=record.name,
            message=record.getMessage(),
            request_id=getattr(record, "request_id", ""),
            extra={
                k: str(v)
                for k, v in record.__dict__.items()
                if k in ("method", "path", "status", "duration_ms", "tenant_id", "user", "action")
                and v is not None
            },
        )
        _buffer.append(entry)
