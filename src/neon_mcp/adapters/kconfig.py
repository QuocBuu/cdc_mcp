"""Non-interactive menuconfig built on kconfiglib, the same library the SDK build uses.

Mirrors `cmake/kconfig.cmake`: the SDK root Kconfig is parsed with
NEON_MDF_APP_KCONFIG=<app>/Kconfig, and settings live in <app>/sdkconfig.
"""

from __future__ import annotations

import contextlib
import os
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import kconfiglib

from ..system.errors import InvalidArgumentError, NotFoundError

_ENV_LOCK = threading.Lock()
_TYPE_NAMES = {kconfiglib.BOOL: "bool", kconfiglib.TRISTATE: "tristate", kconfiglib.STRING: "string",
               kconfiglib.INT: "int", kconfiglib.HEX: "hex"}


@contextlib.contextmanager
def _kconfig_env(app_dir: Path | None) -> Iterator[None]:
    """kconfiglib expands $(NEON_MDF_APP_KCONFIG) from os.environ at parse time."""
    with _ENV_LOCK:
        old = os.environ.get("NEON_MDF_APP_KCONFIG")
        app_kconfig = (app_dir / "Kconfig") if app_dir else Path(os.devnull + ".neon-mcp-no-app-kconfig")
        os.environ["NEON_MDF_APP_KCONFIG"] = str(app_kconfig)
        try:
            yield
        finally:
            if old is None:
                os.environ.pop("NEON_MDF_APP_KCONFIG", None)
            else:
                os.environ["NEON_MDF_APP_KCONFIG"] = old


def _menu_path(node: kconfiglib.MenuNode) -> str:
    parts = []
    parent = node.parent
    while parent is not None and parent.parent is not None:
        if parent.prompt:
            parts.append(parent.prompt[0])
        parent = parent.parent
    return " / ".join(reversed(parts))


def _symbol_info(sym: kconfiglib.Symbol, sdk_dir: Path) -> dict[str, Any]:
    node = sym.nodes[0] if sym.nodes else None
    help_text = next((n.help for n in sym.nodes if n.help), None)
    default = None
    for value, cond in sym.defaults:
        if kconfiglib.expr_value(cond):
            default = kconfiglib.expr_str(value)
            break
    info: dict[str, Any] = {
        "name": f"CONFIG_{sym.name}",
        "type": _TYPE_NAMES.get(sym.type, "unknown"),
        "value": sym.str_value,
        "default": default,
        "prompt": node.prompt[0] if node is not None and node.prompt else None,
        "menu": _menu_path(node) if node is not None else "",
        "visible": sym.visibility > 0,
        "help": " ".join(help_text.split()) if help_text else None,
    }
    if sym.ranges:
        low, high, _cond = sym.ranges[0]
        info["range"] = [low.str_value, high.str_value]
    if node is not None and node.filename:
        filename = Path(node.filename)
        if not filename.is_absolute():
            filename = sdk_dir / filename
        info["defined_in"] = f"{filename}:{node.linenr}"
    return info


class KconfigProject:
    """The merged SDK + application Kconfig tree with an application's sdkconfig loaded."""

    def __init__(self, sdk_dir: Path, app_dir: Path | None) -> None:
        self.sdk_dir = sdk_dir
        self.app_dir = app_dir
        self.sdkconfig = (app_dir / "sdkconfig") if app_dir else None
        root = (sdk_dir / "Kconfig").resolve()
        # An absolute root path lets kconfiglib resolve `rsource` relative to the including
        # file without changing the process-wide working directory (tools run in threads).
        with _kconfig_env(app_dir):
            self.kconf = kconfiglib.Kconfig(str(root), warn_to_stderr=False)
            if self.sdkconfig is not None and self.sdkconfig.exists():
                self.kconf.load_config(str(self.sdkconfig), replace=True)
        self.warnings = list(self.kconf.warnings)

    def symbols(self) -> list[kconfiglib.Symbol]:
        return [s for s in self.kconf.unique_defined_syms if s.type in _TYPE_NAMES]

    def symbol(self, name: str) -> kconfiglib.Symbol:
        key = name.strip()
        key = key.removeprefix("CONFIG_")
        sym = self.kconf.syms.get(key)
        if sym is None or not sym.nodes:
            raise NotFoundError(f"Unknown Kconfig option '{name}'.",
                                "Use dev_get_config with a filter to list valid option names.")
        return sym

    def describe(self, name_filter: str | None = None) -> list[dict[str, Any]]:
        needle = (name_filter or "").strip().lower()
        result = []
        for sym in self.symbols():
            info = _symbol_info(sym, self.sdk_dir)
            haystack = " ".join(str(info.get(k) or "") for k in ("name", "prompt", "menu", "help")).lower()
            if needle and needle not in haystack:
                continue
            result.append(info)
        return result

    def set_values(self, values: dict[str, Any]) -> list[dict[str, Any]]:
        """Assign values like menuconfig would. Raises without writing if any value is rejected."""
        if self.sdkconfig is None:
            raise InvalidArgumentError("An application directory is required to change sdkconfig.")
        changes = []
        for name, requested in values.items():
            sym = self.symbol(name)
            text = _to_kconfig_value(sym, requested)
            old = sym.str_value
            if sym.visibility == 0:
                raise InvalidArgumentError(
                    f"CONFIG_{sym.name} cannot be set: it has no prompt or its dependencies are not met.")
            if not sym.set_value(text) or sym.str_value != text:
                detail = f" (allowed range {sym.ranges[0][0].str_value}..{sym.ranges[0][1].str_value})" if sym.ranges else ""
                raise InvalidArgumentError(f"Value {requested!r} is not valid for CONFIG_{sym.name}{detail}.")
            changes.append({"name": f"CONFIG_{sym.name}", "old": old, "new": sym.str_value})
        # kconfiglib returns its status message instead of printing (stdout is the MCP stream).
        self.kconf.write_config(str(self.sdkconfig))
        return changes


def _to_kconfig_value(sym: kconfiglib.Symbol, value: Any) -> str:
    if sym.type in (kconfiglib.BOOL, kconfiglib.TRISTATE):
        if isinstance(value, bool):
            return "y" if value else "n"
        text = str(value).strip().lower()
        mapping = {"y": "y", "yes": "y", "true": "y", "1": "y", "on": "y",
                   "n": "n", "no": "n", "false": "n", "0": "n", "off": "n"}
        if text not in mapping:
            raise InvalidArgumentError(f"CONFIG_{sym.name} is a bool; use true/false or y/n.")
        return mapping[text]
    if sym.type == kconfiglib.INT:
        try:
            return str(int(str(value).strip(), 0))
        except ValueError as exc:
            raise InvalidArgumentError(f"CONFIG_{sym.name} is an int; got {value!r}.") from exc
    if sym.type == kconfiglib.HEX:
        try:
            return hex(int(str(value).strip(), 16 if not str(value).strip().lower().startswith("0x") else 0))
        except ValueError as exc:
            raise InvalidArgumentError(f"CONFIG_{sym.name} is a hex value; got {value!r}.") from exc
    text = str(value)
    if "\n" in text:
        raise InvalidArgumentError(f"CONFIG_{sym.name} string values cannot contain newlines.")
    return text
