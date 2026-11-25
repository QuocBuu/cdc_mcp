"""Path guard: every path an agent passes in must stay inside the allowed roots."""

from __future__ import annotations

from pathlib import Path

from .errors import InvalidArgumentError, NotFoundError, PermissionDeniedError


class Workspace:
    def __init__(self, roots: list[Path]) -> None:
        self._roots: list[Path] = []
        for root in roots:
            self.add_root(root)

    @property
    def roots(self) -> list[Path]:
        return list(self._roots)

    def add_root(self, root: Path) -> None:
        root = root.resolve()
        if root not in self._roots:
            self._roots.append(root)

    def contains(self, path: Path) -> bool:
        return any(path == root or path.is_relative_to(root) for root in self._roots)

    def resolve(self, path: str | Path, *, base: Path | None = None, must_exist: bool = True,
                kind: str = "any") -> Path:
        """Resolve `path` (relative to `base`, else the first root) and enforce the roots.

        kind: "any", "file" or "dir".
        """
        text = str(path).strip()
        if not text:
            raise InvalidArgumentError("Empty path.")
        if "\x00" in text:
            raise InvalidArgumentError("Path contains a NUL byte.")
        candidate = Path(text).expanduser()
        if not candidate.is_absolute():
            candidate = (base or self._roots[0]) / candidate
        resolved = candidate.resolve()
        if not self.contains(resolved):
            raise PermissionDeniedError(
                f"Path '{resolved}' is outside the allowed workspace.",
                "Allowed roots: " + ", ".join(str(r) for r in self._roots)
                + ". Add more with --workspace / NEON_MCP_WORKSPACE.",
            )
        if must_exist and not resolved.exists():
            raise NotFoundError(f"Path '{resolved}' does not exist.")
        if must_exist and kind == "file" and not resolved.is_file():
            raise InvalidArgumentError(f"'{resolved}' is not a file.")
        if must_exist and kind == "dir" and not resolved.is_dir():
            raise InvalidArgumentError(f"'{resolved}' is not a directory.")
        return resolved
