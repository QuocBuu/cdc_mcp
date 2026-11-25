"""Documentation submodule: index of the SDK's Markdown documents (README, guide/, example
READMEs) split into heading sections, plus the list/read tools."""

from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from ...adapters.neon_mdf import NeonMdfSdk
from ...core.tools import READ_ONLY, ToolRegistry
from ...system.errors import InvalidArgumentError, NotFoundError

if TYPE_CHECKING:
    from ...core.app import NeonApp

DocCategory = Literal["overview", "guide", "examples", "example", "sdk"]

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_TOKEN = re.compile(r"[a-z0-9_]+")


@dataclass
class Section:
    doc: str          # path relative to the SDK root, e.g. guide/Setup.md
    heading: str
    level: int
    start_line: int   # 1-based, line of the heading (or 1 for the preamble)
    end_line: int
    text: str


@dataclass
class Document:
    path: str
    title: str
    category: str
    lines: int
    sections: list[Section]


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if len(t) > 1]


def _split(rel: str, text: str) -> tuple[str, list[Section]]:
    lines = text.splitlines()
    sections: list[Section] = []
    title = Path(rel).stem
    current_heading, current_level, start = "(introduction)", 0, 1
    buffer: list[str] = []
    in_fence = False

    def flush(end: int) -> None:
        body = "\n".join(buffer).strip()
        if body or current_level:
            sections.append(Section(rel, current_heading, current_level, start, end, body))

    for number, line in enumerate(lines, start=1):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
        match = None if in_fence else _HEADING.match(line)
        if match:
            flush(number - 1)
            current_heading, current_level, start = match.group(2).strip(), len(match.group(1)), number
            if current_level == 1 and title == Path(rel).stem:
                title = current_heading
            buffer = []
        else:
            buffer.append(line)
    flush(len(lines))
    return title, sections


class DocumentIndex:
    def __init__(self, sdk: NeonMdfSdk) -> None:
        self._sdk = sdk
        self._lock = threading.Lock()
        self._stamp: tuple | None = None
        self._docs: dict[str, Document] = {}
        self._idf: dict[str, float] = {}
        self._tokens: list[tuple[Section, dict[str, int], set[str]]] = []

    def _paths_stamp(self) -> tuple[list[tuple[Path, str]], tuple]:
        paths = self._sdk.documents()
        return paths, tuple((str(p), p.stat().st_mtime_ns) for p, _ in paths)

    def seed(self, documents: list[Document]) -> None:
        """Use pre-split documents (from a verified knowledge pack) for the files as they are now.
        Any later change is detected by modification time and indexed live again."""
        with self._lock:
            self._load({d.path: d for d in documents}, self._paths_stamp()[1])

    def _refresh(self) -> None:
        paths, stamp = self._paths_stamp()
        if stamp == self._stamp:
            return
        docs: dict[str, Document] = {}
        for path, category in paths:
            rel = self._sdk.relative(path)
            text = path.read_text(encoding="utf-8", errors="replace")
            title, sections = _split(rel, text)
            docs[rel] = Document(rel, title, category, text.count("\n") + 1, sections)
        self._load(docs, stamp)

    def _load(self, docs: dict[str, Document], stamp: tuple) -> None:
        tokens = []
        df: dict[str, int] = {}
        for doc in docs.values():
            title = doc.title
            for section in doc.sections:
                counts: dict[str, int] = {}
                for tok in tokenize(section.text):
                    counts[tok] = counts.get(tok, 0) + 1
                heading_tokens = set(tokenize(section.heading + " " + title))
                for tok in set(counts) | heading_tokens:
                    df[tok] = df.get(tok, 0) + 1
                tokens.append((section, counts, heading_tokens))
        total = max(len(tokens), 1)
        self._idf = {tok: math.log(1 + total / n) for tok, n in df.items()}
        self._docs, self._tokens, self._stamp = docs, tokens, stamp

    def documents(self) -> list[Document]:
        with self._lock:
            self._refresh()
            return list(self._docs.values())

    def document(self, path: str) -> Document:
        key = path.strip().lstrip("./")
        with self._lock:
            self._refresh()
            if key in self._docs:
                return self._docs[key]
            # Accept bare names such as "Setup", "Setup.md" or "SPI_W5500".
            lowered = key.lower().removesuffix(".md")
            for rel, doc in self._docs.items():
                p = Path(rel)
                if lowered in (p.stem.lower(), p.parent.name.lower(), rel.lower().removesuffix(".md")):
                    return doc
        raise NotFoundError(f"No document '{path}'.", "Use knowledge_list_documents to see available documents.")

    def search(self, query: str, limit: int, category: str | None) -> list[dict]:
        terms = tokenize(query)
        if not terms:
            return []
        phrase = query.strip().lower()
        with self._lock:
            self._refresh()
            scored = []
            for section, counts, heading_tokens in self._tokens:
                doc = self._docs[section.doc]
                if category and doc.category != category:
                    continue
                score = 0.0
                matched = 0
                for term in terms:
                    idf = self._idf.get(term, 0.0)
                    tf = counts.get(term, 0)
                    if tf or term in heading_tokens:
                        matched += 1
                    score += idf * (math.log1p(tf) + (2.0 if term in heading_tokens else 0.0))
                if not matched:
                    continue
                score *= matched / len(terms)
                if len(terms) > 1 and phrase in section.text.lower():
                    score *= 1.5
                scored.append((score, section, doc))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            {"document": section.doc, "title": doc.title, "heading": section.heading,
             "lines": f"{section.start_line}-{section.end_line}", "score": round(score, 2),
             "snippet": _snippet(section.text, terms)}
            for score, section, doc in scored[:limit]
        ]


def _snippet(text: str, terms: list[str], width: int = 360) -> str:
    lower = text.lower()
    positions = [lower.find(t) for t in terms if lower.find(t) >= 0]
    start = max(min(positions) - 80, 0) if positions else 0
    snippet = " ".join(text[start:start + width].split())
    return ("…" if start else "") + snippet + ("…" if start + width < len(text) else "")


def get_index(app: NeonApp) -> DocumentIndex:
    return app.service("docs", lambda: DocumentIndex(app.sdk))


def register(registry: ToolRegistry, app: NeonApp) -> None:
    index = get_index(app)

    @registry.tool("knowledge", "documentation", READ_ONLY)
    def knowledge_list_documents(category: DocCategory | None = None) -> dict[str, Any]:
        """List the SDK's documentation files with their titles and section headings."""
        docs = [
            {"path": d.path, "title": d.title, "category": d.category, "lines": d.lines,
             "headings": [s.heading for s in d.sections if 1 <= s.level <= 3]}
            for d in index.documents() if category is None or d.category == category
        ]
        return {"count": len(docs), "documents": docs}

    @registry.tool("knowledge", "documentation", READ_ONLY)
    def knowledge_read_document(document: str, heading: str | None = None,
                                max_chars: int = 20000) -> dict[str, Any]:
        """Read a documentation file, or only one section of it.

        document: path such as "guide/GT32U2086Flashing.md", or a bare name such as
        "Setup", "MenuConfig" or an example name like "SPI_W5500".
        heading: optional section heading (case-insensitive substring); the section and its
        subsections are returned.
        """
        doc = index.document(document)
        sections = doc.sections
        if heading:
            needle = heading.strip().lower()
            start = next((i for i, s in enumerate(sections) if needle in s.heading.lower()), None)
            if start is None:
                raise InvalidArgumentError(
                    f"'{doc.path}' has no heading matching '{heading}'.",
                    "Headings: " + "; ".join(s.heading for s in sections))
            level = sections[start].level
            end = start + 1
            while end < len(sections) and (sections[end].level == 0 or sections[end].level > level):
                end += 1
            sections = sections[start:end]
        parts = []
        for s in sections:
            prefix = f"{'#' * s.level} {s.heading}\n\n" if s.level else ""
            parts.append(prefix + s.text)
        text = "\n\n".join(parts)
        return {
            "document": doc.path, "title": doc.title,
            "lines": f"{sections[0].start_line}-{sections[-1].end_line}" if sections else None,
            "truncated": len(text) > max_chars, "content": text[:max_chars],
        }
