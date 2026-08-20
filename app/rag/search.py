"""search_policy — the standalone RAG retrieval tool.

Not yet wired into the Assistant Agent or Orchestrator (Epic 4/5); this
module is importable and callable on its own for now.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.rag.index import DEFAULT_PERSIST_DIR, get_index


def _build_where(fare_class: str | None, doc_type: str | None) -> dict[str, Any] | None:
    conditions: list[dict[str, Any]] = []
    if fare_class:
        # A fare-specific request is still governed by fare-agnostic policies
        # (fare_class == ""), so match either, not fare_class alone.
        conditions.append({"$or": [{"fare_class": fare_class}, {"fare_class": ""}]})
    if doc_type:
        conditions.append({"doc_type": doc_type})

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def search_policy(
    query: str,
    fare_class: str | None = None,
    doc_type: str | None = None,
    k: int = 4,
    persist_directory: str | Path = DEFAULT_PERSIST_DIR,
) -> list[dict[str, Any]]:
    """Retrieve the top-k KB/policy chunks for a query.

    Args:
        query: free-text search query.
        fare_class: optional "Saver" | "Flex" | "Business" filter. Matches
            chunks tagged with that fare plus fare-agnostic chunks.
        doc_type: optional "kb" | "fare_rule" | "policy" filter.
        k: number of chunks to return.
        persist_directory: Chroma persist dir (override for tests).

    Returns:
        Ranked list of dicts: source_id, text, score (0..1, higher = more
        relevant), source_file, doc_type, fare_class, topic.
    """
    store = get_index(persist_directory)
    where = _build_where(fare_class, doc_type)

    results = store.similarity_search_with_relevance_scores(query, k=k, filter=where)

    return [
        {
            "source_id": doc.metadata["source_id"],
            "text": doc.page_content,
            "score": score,
            "source_file": doc.metadata["source_file"],
            "doc_type": doc.metadata["doc_type"],
            "fare_class": doc.metadata["fare_class"],
            "topic": doc.metadata["topic"],
        }
        for doc, score in results
    ]
