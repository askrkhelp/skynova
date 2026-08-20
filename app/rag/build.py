"""CLI: build the Chroma index from data/kb + data/policies.

Usage: python -m app.rag.build
"""

from __future__ import annotations

import time

from app.rag.index import DEFAULT_PERSIST_DIR, build_index
from app.rag.ingest import load_and_chunk

# fare_class may legitimately be "" (fare-agnostic chunk) — that's a valid
# non-null string, not a missing value, so the check below is for presence
# (not None), not for truthiness.
REQUIRED_METADATA_FIELDS = ("source_id", "source_file", "doc_type", "fare_class", "topic")


def main() -> int:
    chunks = load_and_chunk()

    missing = [c.metadata.get("source_id", "<no id>") for c in chunks if any(c.metadata.get(f) is None for f in REQUIRED_METADATA_FIELDS)]
    if missing:
        print(f"ERROR: {len(missing)} chunk(s) missing required metadata: {missing}")
        return 1

    print(f"Loaded {len(chunks)} chunks from data/kb + data/policies (100% non-null metadata: {REQUIRED_METADATA_FIELDS}).")

    start = time.perf_counter()
    build_index(DEFAULT_PERSIST_DIR, chunks=chunks)
    elapsed = time.perf_counter() - start

    print(f"Indexed {len(chunks)} chunks into '{DEFAULT_PERSIST_DIR}' in {elapsed:.2f}s.")
    if elapsed >= 30:
        print("WARNING: index build exceeded the 30s acceptance target.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
