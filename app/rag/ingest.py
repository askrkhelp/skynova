"""Load data/kb + data/policies, split into chunks, attach metadata.

Chunking strategy: split each markdown file on its H1/H2 headers (the corpus
is short, hand-written docs — headers are the natural retrieval unit), then
run each section through a char-based splitter as a safety net for any
section that grows past ~500 tokens. Every chunk gets a stable source_id of
`{source_file}#{header-slug}` used for citations and Chroma document ids.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
KB_DIR = DATA_DIR / "kb"
POLICIES_DIR = DATA_DIR / "policies"

# doc_type/fare_class are derived from filename, not file content, so every
# chunk gets non-null metadata regardless of what the doc text says.
FARE_CLASS_BY_STEM = {
    "fare_rules_saver": "Saver",
    "fare_rules_flex": "Flex",
    "fare_rules_business": "Business",
}

# chunk_size/overlap are in characters; ~4 chars/token, so 2000/200 ~= the
# spec's "500 tokens, 50 overlap". Corpus docs are short enough that this
# splitter rarely fires — it exists as a safety net for future growth.
_CHAR_SPLITTER = RecursiveCharacterTextSplitter(chunk_size=2000, chunk_overlap=200)


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return slug or "section"


def _doc_type_for(path: Path) -> str:
    if path.parent.name == "kb":
        return "kb"
    if path.stem.startswith("fare_rules_"):
        return "fare_rule"
    return "policy"


def _fare_class_for(path: Path) -> str:
    return FARE_CLASS_BY_STEM.get(path.stem, "")


def _header_splitter() -> MarkdownHeaderTextSplitter:
    return MarkdownHeaderTextSplitter(headers_to_split_on=[("#", "h1"), ("##", "h2")], strip_headers=False)


def _chunks_for_file(path: Path) -> list[Document]:
    text = path.read_text(encoding="utf-8")
    sections = _header_splitter().split_text(text)

    doc_type = _doc_type_for(path)
    fare_class = _fare_class_for(path)
    source_file = f"{path.parent.name}/{path.name}"

    chunks: list[Document] = []
    for section in sections:
        topic = section.metadata.get("h2") or section.metadata.get("h1") or path.stem
        content = section.page_content.strip()
        if not content:
            continue

        sub_texts = _CHAR_SPLITTER.split_text(content)
        slug = _slugify(topic)
        for i, sub_text in enumerate(sub_texts):
            source_id = f"{source_file}#{slug}" if len(sub_texts) == 1 else f"{source_file}#{slug}-{i + 1}"
            chunks.append(
                Document(
                    page_content=sub_text,
                    metadata={
                        "source_id": source_id,
                        "source_file": source_file,
                        "doc_type": doc_type,
                        "fare_class": fare_class,
                        "topic": topic,
                    },
                )
            )
    return chunks


def load_and_chunk() -> list[Document]:
    """Load and chunk the full corpus (data/kb + data/policies)."""
    files = sorted(KB_DIR.glob("*.md")) + sorted(POLICIES_DIR.glob("*.md"))
    if not files:
        raise FileNotFoundError(f"No corpus files found under {KB_DIR} or {POLICIES_DIR}")

    chunks: list[Document] = []
    for path in files:
        chunks.extend(_chunks_for_file(path))
    return chunks


def corpus_fingerprint(chunks: list[Document]) -> str:
    """Hash chunk content + metadata so app.rag.index can tell whether the
    on-disk Chroma collection still matches data/kb + data/policies, and
    auto-rebuild instead of silently serving stale retrieval results when a
    doc is added/edited/removed after the index was last built."""
    hasher = hashlib.sha256()
    for chunk in sorted(chunks, key=lambda c: c.metadata["source_id"]):
        fields = (
            chunk.metadata["source_id"],
            chunk.metadata["source_file"],
            chunk.metadata["doc_type"],
            chunk.metadata["fare_class"],
            chunk.metadata["topic"],
            chunk.page_content,
        )
        hasher.update("\0".join(fields).encode("utf-8"))
        hasher.update(b"\x1e")
    return hasher.hexdigest()
