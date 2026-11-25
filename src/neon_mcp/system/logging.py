"""Logging to stderr (stdout carries the MCP stream on stdio) and an audit trail of
permission decisions for write and hardware operations."""

from __future__ import annotations

import logging
import sys

AUDIT = logging.getLogger("neon_mcp.audit")


def setup(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger("neon_mcp")
    root.handlers[:] = [handler]
    root.setLevel(level)
    root.propagate = False


def audit(event: str, **fields: object) -> None:
    details = " ".join(f"{k}={v!r}" for k, v in fields.items())
    AUDIT.info("%s %s", event, details)
