"""Structured JSON logging with simple secret redaction.

The project logs machine-readable JSON lines so a run can be audited later.
Secrets are never logged; the redaction filter is a second line of defence for
accidental ``Authorization`` headers or token-shaped values.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any, TextIO

_SECRET_PATTERNS = [
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;\"']+"),
    re.compile(r"(?i)((?:api[_-]?key|token|secret)\s*[:=]\s*)[^\s,;\"']+"),
]


class JsonFormatter(logging.Formatter):
    """Render one log record as a single JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": self._redact(record.getMessage()),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key in ("run_id", "agent", "phase", "event_type"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        extra = getattr(record, "extra_payload", None)
        if extra:
            payload["payload"] = extra
        return json.dumps(payload, sort_keys=True, default=str)

    @staticmethod
    def _redact(text: str) -> str:
        for pattern in _SECRET_PATTERNS:
            text = pattern.sub(r"\1***", text)
        return text


def configure_logging(level: str = "INFO", stream: TextIO | None = None) -> None:
    """Configure the root logger exactly once.

    Args:
        level: Standard logging level name (``INFO``, ``DEBUG``, ...).
        stream: Optional output stream for tests; defaults to ``stderr``.
    """

    root = logging.getLogger()
    root.setLevel(level.upper())
    # Remove only handlers installed by this module, preserving pytest's.
    for handler in list(root.handlers):
        if getattr(handler, "_cfb_json", False):
            root.removeHandler(handler)
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter())
    handler._cfb_json = True  # type: ignore[attr-defined]
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger."""

    return logging.getLogger(name)
