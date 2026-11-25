"""Error types reported back to the AI agent.

Every error deliberately raised by NEON MCP derives from `NeonError`, which is an
MCP `ToolError`: its message reaches the model as an `isError` tool result. Any
other exception is treated by the MCP SDK as a crash and its text is hidden.
"""

from __future__ import annotations

from mcp.server.mcpserver.exceptions import ToolError


class NeonError(ToolError):
    """Base class for anticipated failures. Include an actionable hint."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        self.hint = hint
        super().__init__(f"{message} Hint: {hint}" if hint else message)


class SdkNotFoundError(NeonError):
    """The NEON-MDF SDK could not be located."""


class NotFoundError(NeonError):
    """A requested document, symbol, peripheral, register, example or file does not exist."""


class InvalidArgumentError(NeonError):
    """An argument is malformed or out of range."""


class PermissionDeniedError(NeonError):
    """The security policy does not allow the requested operation."""


class CapabilityError(NeonError):
    """The selected target does not support the requested operation."""


class CommandError(NeonError):
    """An external command failed to start."""
