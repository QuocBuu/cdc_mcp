"""Search submodule: ranked keyword search over the documentation index."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...core.tools import READ_ONLY, ToolRegistry
from ...system.errors import InvalidArgumentError
from .documentation import DocCategory, get_index

if TYPE_CHECKING:
    from ...core.app import NeonApp


def register(registry: ToolRegistry, app: NeonApp) -> None:
    index = get_index(app)

    @registry.tool("knowledge", "search", READ_ONLY)
    def knowledge_search(query: str, limit: int = 8, category: DocCategory | None = None) -> dict[str, Any]:
        """Search the NEON-MDF documentation (README, guide/, example READMEs) by keywords.

        Returns the best-matching sections with document path, heading, line range and a
        snippet. Follow up with knowledge_read_document(document, heading) for full text.
        Use specific terms, e.g. "boot mode 100 RESET", "printf float", "XIP profile".
        """
        if not 1 <= limit <= 50:
            raise InvalidArgumentError("limit must be 1..50.")
        results = index.search(query, limit, category)
        return {"query": query, "results": results,
                "note": None if results else "No matches; try fewer or different keywords."}
