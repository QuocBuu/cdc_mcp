"""API Search submodule: index of the SDK's public C API, parsed from the driver/console headers.

Extracts function prototypes (and static inline helpers), typedef'd enums/structs/aliases
and public macros, each with its Doxygen comment and file:line. The parser is
deliberately simple and tuned to the NEON coding convention V1.3 header layout.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from ...adapters.neon_mdf import NeonMdfSdk
from ...core.tools import READ_ONLY, ToolRegistry
from ...system.errors import InvalidArgumentError

if TYPE_CHECKING:
    from ...core.app import NeonApp

ApiKind = Literal["function", "inline_function", "enum", "struct", "typedef", "macro"]

_TAG = re.compile(r"^[@\\](\w+)(?:\[([^\]]*)\])?\s*(.*)$")
_FUNC = re.compile(r"^(?P<ret>[A-Za-z_][\w\s\*]*?)\s*\b(?P<name>[A-Za-z_]\w*)\s*\((?P<params>.*)\)\s*$", re.DOTALL)
_DEFINE = re.compile(r"^#\s*define\s+(?P<name>[A-Za-z_]\w*)(?P<args>\([^)]*\))?\s*(?P<value>.*)$")
_ENUM_VALUE = re.compile(r"^\s*([A-Z_][A-Z0-9_]*)\s*(?:=\s*([^,/]+?))?\s*,?\s*(?:/\*+<?\s*(.*?)\s*\*/|//\s*(.*))?$")
_TYPE_REF = re.compile(r"\b(neon_\w+_t|[A-Z][A-Za-z0-9]*_TypeDef)\b")


@dataclass
class ApiEntry:
    name: str
    kind: str              # function | inline_function | enum | struct | typedef | macro
    module: str
    file: str              # relative to SDK root
    line: int
    signature: str
    doc: dict = field(default_factory=dict)
    members: list[dict] = field(default_factory=list)

    def brief(self) -> str:
        return self.doc.get("brief", "")

    def compact(self) -> dict:
        return {"name": self.name, "kind": self.kind, "module": self.module,
                "signature": self.signature, "brief": self.brief(), "location": f"{self.file}:{self.line}"}

    def full(self) -> dict:
        data = self.compact()
        data["doc"] = self.doc
        if self.members:
            data["members"] = self.members
        return data


def parse_doxygen(raw: str) -> dict:
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        line = re.sub(r"^/\*\*+<?", "", line)
        line = re.sub(r"\*+/$", "", line)
        line = re.sub(r"^\*+ ?", "", line)
        lines.append(line.rstrip())
    doc: dict = {}
    params: list[dict] = []
    current: dict | None = None
    current_key = "brief"

    def add(key: str, text: str) -> None:
        if not text:
            return
        if key == "param" and current is not None:
            current["description"] = (current["description"] + " " + text).strip()
        else:
            doc[key] = (doc.get(key, "") + " " + text).strip()

    for line in lines:
        match = _TAG.match(line)
        if match:
            tag, direction, rest = match.group(1).lower(), match.group(2), match.group(3)
            if tag == "param":
                name, _, desc = rest.partition(" ")
                current = {"name": name, "direction": direction or "in", "description": desc.strip()}
                params.append(current)
                current_key = "param"
            elif tag in ("return", "returns", "retval"):
                current_key = "returns"
                add(current_key, rest)
            elif tag in ("brief", "details", "note", "warning", "pre", "post", "copydoc", "internal"):
                current_key = tag
                add(current_key, rest)
            else:
                current_key = "details"
                add(current_key, rest)
            continue
        if not line:
            if current_key == "brief" and doc.get("brief"):
                current_key = "details"
            continue
        add(current_key, line)
    if params:
        doc["params"] = params
    return doc


def _strip_comment(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    return re.sub(r"//.*", "", text)


def _normalize(text: str) -> str:
    return " ".join(_strip_comment(text).split())


def parse_header(path: Path, rel: str, module: str) -> list[ApiEntry]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    entries: list[ApiEntry] = []
    pending_doc: str | None = None
    i = 0
    n = len(lines)
    while i < n:
        raw = lines[i]
        line = raw.strip()
        if line.startswith(("/**", "/*!")):
            block = [raw]
            while "*/" not in lines[i] and i + 1 < n:
                i += 1
                block.append(lines[i])
            pending_doc = "\n".join(block)
            i += 1
            continue
        if line.startswith("/*"):
            while "*/" not in lines[i] and i + 1 < n:
                i += 1
            i += 1
            continue
        if not line or line.startswith("//"):
            i += 1
            continue
        start = i
        if line.startswith("#"):
            text = line
            while text.endswith("\\") and i + 1 < n:
                i += 1
                text = text[:-1] + " " + lines[i].strip()
            match = _DEFINE.match(text)
            if match and not match.group("name").startswith("__") and match.group("value").strip():
                value = _normalize(match.group("value"))
                trailing = re.search(r"/\*+<?\s*(.*?)\s*\*/|//\s*(.*)$", text)
                doc = parse_doxygen(pending_doc) if pending_doc else {}
                if not doc and trailing:
                    doc = {"brief": (trailing.group(1) or trailing.group(2) or "").strip()}
                entries.append(ApiEntry(match.group("name"), "macro", module, rel, start + 1,
                                        f"#define {match.group('name')}{match.group('args') or ''} {value}", doc))
            pending_doc = None
            i += 1
            continue
        if line.startswith(("extern \"C\"", "}", "{")) and not line.startswith("} "):
            pending_doc = None
            i += 1
            continue
        # Accumulate one declaration: up to ';' at depth 0, or a balanced { } body.
        statement = [raw]
        depth = raw.count("{") - raw.count("}")
        while i + 1 < n and not (depth <= 0 and _strip_comment("\n".join(statement)).rstrip().endswith((";", "}"))):
            i += 1
            statement.append(lines[i])
            depth += lines[i].count("{") - lines[i].count("}")
        i += 1
        text = "\n".join(statement)
        entry = _classify(text, module, rel, start + 1, pending_doc)
        if entry is not None:
            entries.append(entry)
        pending_doc = None
    return entries


def _classify(text: str, module: str, rel: str, line: int, raw_doc: str | None) -> ApiEntry | None:
    doc = parse_doxygen(raw_doc) if raw_doc else {}
    code = _strip_comment(text).strip()
    if code.startswith("typedef"):
        if "{" in code:
            kind = "enum" if re.match(r"typedef\s+enum", code) else "struct"
            name_match = re.search(r"}\s*([A-Za-z_]\w*)\s*;\s*$", code)
            if not name_match:
                return None
            members = _members(text, kind)
            return ApiEntry(name_match.group(1), kind, module, rel, line,
                            f"typedef {kind} {{...}} {name_match.group(1)}", doc, members)
        alias = re.search(r"\b([A-Za-z_]\w*)\s*;\s*$", code)
        if alias:
            return ApiEntry(alias.group(1), "typedef", module, rel, line, _normalize(code), doc)
        return None
    head = code.split("{", 1)[0].strip() if "{" in code else code.rstrip(";").strip()
    match = _FUNC.match(head)
    if not match or match.group("name") in ("if", "while", "for", "switch", "return"):
        return None
    ret = " ".join(match.group("ret").split())
    if ret.startswith(("typedef", "struct", "enum")):
        return None
    kind = "inline_function" if "{" in code else "function"
    signature = f"{ret} {match.group('name')}({' '.join(match.group('params').split())})"
    return ApiEntry(match.group("name"), kind, module, rel, line, signature, doc)


def _members(text: str, kind: str) -> list[dict]:
    body = text[text.find("{") + 1:text.rfind("}")]
    members = []
    if kind == "enum":
        for line in body.splitlines():
            match = _ENUM_VALUE.match(line)
            if match:
                members.append({"name": match.group(1), "value": (match.group(2) or "").strip() or None,
                                "comment": (match.group(3) or match.group(4) or "").strip() or None})
        return members
    for line in body.splitlines():
        comment = re.search(r"/\*+<?\s*(.*?)\s*\*/|//\s*(.*)$", line)
        code = _strip_comment(line).strip()
        if code.endswith(";") and "(" not in code:
            members.append({"declaration": code.rstrip(";").strip(),
                            "comment": (comment.group(1) or comment.group(2)).strip() if comment else None})
    return members


class ApiIndex:
    def __init__(self, sdk: NeonMdfSdk) -> None:
        self._sdk = sdk
        self._lock = threading.Lock()
        self._stamp: tuple | None = None
        self._entries: list[ApiEntry] = []

    def _headers_stamp(self) -> tuple[list[tuple[Path, str]], tuple]:
        headers = self._sdk.public_headers()
        return headers, tuple((str(p), p.stat().st_mtime_ns) for p, _ in headers)

    def seed(self, entries: list[ApiEntry]) -> None:
        """Use pre-parsed entries (from a verified knowledge pack) for the headers as they are now.
        Any later header change is detected by modification time and parsed live again."""
        with self._lock:
            self._entries, self._stamp = list(entries), self._headers_stamp()[1]

    def entries(self) -> list[ApiEntry]:
        with self._lock:
            headers, stamp = self._headers_stamp()
            if stamp != self._stamp:
                entries = []
                for path, module in headers:
                    entries.extend(parse_header(path, self._sdk.relative(path), module))
                self._entries, self._stamp = entries, stamp
            return list(self._entries)

    def modules(self) -> list[str]:
        return sorted({e.module for e in self.entries()})

    def by_name(self, name: str) -> ApiEntry | None:
        for entry in self.entries():
            if entry.name == name:
                return entry
        lowered = name.lower()
        return next((e for e in self.entries() if e.name.lower() == lowered), None)

    def search(self, query: str, module: str | None, kind: str | None, limit: int) -> list[ApiEntry]:
        q = query.strip().lower()
        terms = [t for t in re.split(r"[\s,]+", q) if t]
        scored = []
        for entry in self.entries():
            if module and entry.module != module.lower():
                continue
            if kind and not (entry.kind == kind or (kind == "function" and entry.kind == "inline_function")):
                continue
            name = entry.name.lower()
            text = (entry.brief() + " " + str(entry.doc.get("details", ""))).lower()
            score = 0.0
            if q == name:
                score += 100
            elif q and q in name:
                score += 30 - min(len(name) - len(q), 20) * 0.5
            for term in terms:
                if term in name:
                    score += 8
                elif term in text:
                    score += 3
                elif term in entry.signature.lower():
                    score += 1
            if terms and not all(t in name or t in text or t in entry.signature.lower() for t in terms):
                score *= 0.3
            if score > 0:
                scored.append((score, entry))
        scored.sort(key=lambda item: (-item[0], item[1].name))
        return [entry for _, entry in scored[:limit]]

    def implementation_of(self, name: str) -> str | None:
        """Locate the definition of a function in the backend sources."""
        pattern = re.compile(rf"^[A-Za-z_][^;()]*\b{re.escape(name)}\s*\(")
        roots = [self._sdk.driver_dir, self._sdk.console_dir]
        for root in roots:
            for path in sorted(root.rglob("*.c")):
                try:
                    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    continue
                for number, line in enumerate(lines, start=1):
                    if pattern.match(line) and not line.rstrip().endswith(";"):
                        return f"{self._sdk.relative(path)}:{number}"
        return None

    def referenced_types(self, entry: ApiEntry) -> list[dict]:
        names = dict.fromkeys(_TYPE_REF.findall(entry.signature))
        result = []
        for name in names:
            ref = self.by_name(name)
            if ref is not None and ref is not entry:
                data = ref.compact()
                if ref.members:
                    data["members"] = ref.members
                result.append(data)
        return result


def get_api(app: NeonApp) -> ApiIndex:
    return app.service("api", lambda: ApiIndex(app.sdk))


def register(registry: ToolRegistry, app: NeonApp) -> None:
    api = get_api(app)

    @registry.tool("sdk", "api", READ_ONLY)
    def sdk_search_api(query: str, module: str | None = None, kind: ApiKind | None = None,
                       limit: int = 20) -> dict[str, Any]:
        """Search the public C API (driver and console headers) by name or description.

        query: a symbol name (exact names such as "neon_uart_transmit" or "neon_spi_config_t"
        return full detail: Doxygen params/returns/notes, implementation location and the types
        used in the signature) or keywords like "read pin", "baud", "dma memcpy".
        module: restrict to one module (uart, gpio, spi, i2c, qspi, dma, crm, console, common, ...).
        """
        if not 1 <= limit <= 100:
            raise InvalidArgumentError("limit must be 1..100.")
        exact = api.by_name(query.strip())
        result: dict[str, Any] = {"query": query}
        if exact is not None and (module is None or exact.module == module.lower()):
            detail = exact.full()
            if exact.kind == "function":
                detail["implementation"] = api.implementation_of(exact.name)
            detail["related_types"] = api.referenced_types(exact)
            result["exact"] = detail
        matches = api.search(query, module, kind, limit)
        result["matches"] = [m.compact() for m in matches if exact is None or m is not exact]
        if exact is None and not matches:
            result["note"] = f"No API matches. Modules: {', '.join(api.modules())}."
        return result
