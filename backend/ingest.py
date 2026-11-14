"""Ingestion: parse the 22 NovaCart policy files into cited chunks and build a
FAISS index.

Chunking unit = one numbered item (e.g. **2.2**), because the README says an
item is the unit the bot should cite. Tables / bullet lists that follow an item
belong to that item. Front-matter (version, effective_date, scope, ...) is kept
as metadata on every chunk so the rules engine can filter by date and scope.

Run from the project root:
    python backend/ingest.py
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from langchain_core.documents import Document

import config

# --- Regexes ---------------------------------------------------------------
FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
HEADING_RE = re.compile(r"^##\s+(\d+)\.\s+(.*)$")          # "## 2. How fees apply"
ITEM_RE = re.compile(r"^\*\*(\d+\.\d+)\*\*\s*(.*)$")        # "**2.2** The free..."


@dataclass
class Chunk:
    file: str
    doc_id: str
    title: str
    version: str
    effective_date: str
    last_updated: str
    scope: str
    section: str                       # "2.2" for an item, "2" for heading-level text
    heading: str                       # the "## N." heading this lives under
    lines: list[str] = field(default_factory=list)

    def text(self) -> str:
        return "\n".join(self.lines).strip()

    def to_document(self) -> Document:
        header = f"[{self.file} | Section {self.section}] {self.heading}".strip()
        return Document(
            page_content=f"{header}\n{self.text()}",
            metadata={
                "file": self.file,
                "doc_id": self.doc_id,
                "title": self.title,
                "version": self.version,
                "effective_date": self.effective_date,
                "last_updated": self.last_updated,
                "scope": self.scope,
                "section": self.section,
                "heading": self.heading,
                "citation": f"{self.file}, Section {self.section}",
            },
        )


def parse_front_matter(text: str) -> tuple[dict, str]:
    """Return (front_matter_dict, body_without_front_matter)."""
    m = FRONT_MATTER_RE.match(text)
    if not m:
        return {}, text
    fm = yaml.safe_load(m.group(1)) or {}
    body = text[m.end():]
    return fm, body


def parse_file(path: Path) -> list[Chunk]:
    raw = path.read_text(encoding="utf-8")
    fm, body = parse_front_matter(raw)

    base = dict(
        file=path.name,
        doc_id=str(fm.get("doc_id", "")),
        title=str(fm.get("title", "")),
        version=str(fm.get("version", "")),
        effective_date=str(fm.get("effective_date", "")),
        last_updated=str(fm.get("last_updated", "")),
        scope=str(fm.get("scope", "")),
    )

    chunks: list[Chunk] = []
    current: Chunk | None = None
    heading = ""          # current "## N." heading text
    heading_num = ""      # current section number, e.g. "2"

    def flush() -> None:
        nonlocal current
        if current is not None and current.text():
            chunks.append(current)
        current = None

    for line in body.splitlines():
        h = HEADING_RE.match(line)
        if h:
            flush()
            heading_num, heading_title = h.group(1), h.group(2).strip()
            heading = f"{heading_num}. {heading_title}"
            # Start a heading-level chunk to catch any intro text before item N.1.
            current = Chunk(**base, section=heading_num, heading=heading)
            continue

        it = ITEM_RE.match(line)
        if it:
            flush()
            item_num, first_text = it.group(1), it.group(2)
            current = Chunk(**base, section=item_num, heading=heading)
            current.lines.append(f"**{item_num}** {first_text}".rstrip())
            continue

        # Ordinary line (prose, table row, bullet) -> belongs to current chunk.
        if current is None:
            # Text before the first heading (e.g. the H1 or file intro); skip the
            # bare H1 but keep any real intro prose as a section "0" chunk.
            if line.startswith("# ") or not line.strip():
                continue
            current = Chunk(**base, section="0", heading="")
        current.lines.append(line)

    flush()
    return chunks


def load_all_chunks() -> list[Chunk]:
    files = sorted(config.POLICIES_DIR.glob("*.md"))
    if not files:
        raise RuntimeError(f"No policy files found in {config.POLICIES_DIR}")
    all_chunks: list[Chunk] = []
    for path in files:
        file_chunks = parse_file(path)
        all_chunks.extend(file_chunks)
        print(f"  {path.name}: {len(file_chunks)} chunks")
    return all_chunks


def build_index() -> None:
    # Imported here so that `parse_file` can be unit-tested without the heavy
    # embedding / FAISS dependencies installed.
    from langchain_community.vectorstores import FAISS
    from langchain_huggingface import HuggingFaceEmbeddings

    print(f"Parsing policies in {config.POLICIES_DIR} ...")
    chunks = load_all_chunks()
    documents = [c.to_document() for c in chunks]
    print(f"Total: {len(documents)} chunks from {len(list(config.POLICIES_DIR.glob('*.md')))} files")

    print(f"Loading embedding model: {config.EMBEDDING_MODEL} (first run downloads it) ...")
    embeddings = HuggingFaceEmbeddings(model_name=config.EMBEDDING_MODEL)

    print("Building FAISS index ...")
    store = FAISS.from_documents(documents, embeddings)

    config.FAISS_INDEX_DIR.mkdir(parents=True, exist_ok=True)
    store.save_local(str(config.FAISS_INDEX_DIR))
    print(f"Saved FAISS index to {config.FAISS_INDEX_DIR}")


if __name__ == "__main__":
    build_index()
