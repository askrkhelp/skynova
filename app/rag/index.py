"""Build and open the Chroma index for the KB/policy corpus.

Single collection, metadata-filtered (doc_type, fare_class) rather than one
collection per doc_type — see 01_Architecture_and_Design.md SS3.5.
"""

from __future__ import annotations

from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from app.rag.ingest import corpus_fingerprint, load_and_chunk

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PERSIST_DIR = REPO_ROOT / "chroma_db"
COLLECTION_NAME = "resolveai_policy"
EMBEDDING_MODEL = "gemini-embedding-001"

# Sidecar file (next to the sqlite store) recording the corpus_fingerprint()
# of the corpus as of the last build, so get_index() can detect a doc
# added/edited/removed under data/kb or data/policies since then.
FINGERPRINT_FILENAME = "corpus_fingerprint.txt"

# Cosine space gives relevance scores in a well-behaved 0..1 range, which the
# grounding contract needs for a "nothing relevant found" threshold check.
_COLLECTION_CONFIG = {"hnsw": {"space": "cosine"}}


def get_embeddings() -> GoogleGenerativeAIEmbeddings:
    return GoogleGenerativeAIEmbeddings(model=EMBEDDING_MODEL)


def _open_store(persist_directory: str | Path) -> Chroma:
    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=get_embeddings(),
        persist_directory=str(persist_directory),
        collection_configuration=_COLLECTION_CONFIG,
    )


def _fingerprint_path(persist_directory: str | Path) -> Path:
    return Path(persist_directory) / FINGERPRINT_FILENAME


def _read_fingerprint(persist_directory: str | Path) -> str | None:
    path = _fingerprint_path(persist_directory)
    return path.read_text(encoding="utf-8").strip() if path.exists() else None


def _write_fingerprint(persist_directory: str | Path, fingerprint: str) -> None:
    path = _fingerprint_path(persist_directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(fingerprint, encoding="utf-8")


def build_index(persist_directory: str | Path = DEFAULT_PERSIST_DIR, chunks: list[Document] | None = None) -> Chroma:
    """(Re)build the index from data/kb + data/policies and persist it.

    Always rebuilds from scratch so the index never drifts from the corpus
    on disk (the corpus is small enough that cold rebuilds are sub-second to
    a few seconds, per the architecture doc's stated cold-start assumption).
    """
    if chunks is None:
        chunks = load_and_chunk()
    store = _open_store(persist_directory)
    store.reset_collection()

    ids = [chunk.metadata["source_id"] for chunk in chunks]
    store.add_documents(documents=chunks, ids=ids)
    _write_fingerprint(persist_directory, corpus_fingerprint(chunks))
    return store


def get_index(persist_directory: str | Path = DEFAULT_PERSIST_DIR) -> Chroma:
    """Open the persisted index, rebuilding it if empty/missing or if
    data/kb or data/policies changed since the last build (corpus_fingerprint
    mismatch) — so an added/edited/removed doc never silently serves stale
    retrieval results until someone remembers to rerun `python -m app.rag.build`.
    """
    store = _open_store(persist_directory)
    chunks = load_and_chunk()
    is_empty = not store.get(limit=1)["ids"]
    is_stale = _read_fingerprint(persist_directory) != corpus_fingerprint(chunks)
    if is_empty or is_stale:
        store = build_index(persist_directory, chunks=chunks)
    return store
