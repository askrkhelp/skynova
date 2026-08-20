"""Retrieval smoke tests for app.rag.search_policy.

Metadata coverage runs offline. The retrieval tests call the real Gemini
embedding API (gemini-embedding-001) and are skipped if no API key is set.
"""

from __future__ import annotations

import os

import pytest

from app.rag.ingest import load_and_chunk
from app.rag.search import search_policy

requires_key = pytest.mark.skipif(
    not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")),
    reason="GEMINI_API_KEY not set - retrieval tests need a live embedding call",
)


def test_ingest_metadata_coverage():
    chunks = load_and_chunk()
    assert chunks, "ingestion produced no chunks"

    required_fields = ("source_id", "source_file", "doc_type", "fare_class", "topic")
    for chunk in chunks:
        for field in required_fields:
            assert chunk.metadata.get(field) is not None, f"{chunk.metadata.get('source_id')} missing {field}"

    ids = [c.metadata["source_id"] for c in chunks]
    assert len(ids) == len(set(ids)), "duplicate source_id across chunks"


@requires_key
def test_search_policy_excess_baggage_top2():
    # Literal acceptance-criteria case from 02_Feature_Breakdown_and_Backlog.md
    # ("query 'excess baggage fee' returns policy_baggage.md chunk in top-2").
    results = search_policy("excess baggage fee", k=2)
    top2_sources = {r["source_file"] for r in results[:2]}
    assert "policies/policy_baggage.md" in top2_sources


# 10 known query -> expected-source pairs. Where a fact is covered by more
# than one doc (e.g. a fare-rule sheet and the general policy doc restate
# the same number), any of the listed sources counts as a hit.
SMOKE_CASES = [
    (
        "How much does excess baggage cost per kilogram?",
        {"policies/policy_baggage.md", "kb/excess_baggage_fees.md"},
    ),
    (
        "Is my Saver ticket refundable if I cancel voluntarily?",
        {"policies/fare_rules_saver.md", "policies/policy_refund_cancellation.md"},
    ),
    (
        "What happens if my flight is delayed more than 3 hours?",
        {"policies/policy_delay_compensation.md"},
    ),
    (
        "How many hours before departure does the airport check-in counter close for an international flight?",
        {"policies/policy_check_in_boarding.md"},
    ),
    (
        "What is the liability limit if the airline loses my checked bag?",
        {"policies/policy_baggage.md"},
    ),
    (
        "Can I bring a service animal in the cabin?",
        {"kb/pets.md"},
    ),
    (
        "How do I request wheelchair assistance for my flight?",
        {"policies/policy_special_assistance.md"},
    ),
    (
        "What baggage allowance do I get on a Business class ticket?",
        {"policies/fare_rules_business.md", "kb/baggage_allowance.md"},
    ),
    (
        "Can I fix a spelling mistake in the name on my ticket?",
        {"kb/name_correction.md"},
    ),
    (
        "What happens if I miss the boarding gate before it closes?",
        {"kb/gate_closure.md", "policies/policy_check_in_boarding.md"},
    ),
]


@requires_key
def test_retrieval_smoke_hit_rate():
    hits = 0
    misses = []
    for query, expected_sources in SMOKE_CASES:
        results = search_policy(query, k=2)
        top2_sources = {r["source_file"] for r in results[:2]}
        if top2_sources & expected_sources:
            hits += 1
        else:
            misses.append((query, expected_sources, top2_sources))

    hit_rate = hits / len(SMOKE_CASES)
    assert hit_rate >= 0.9, f"hit rate {hit_rate:.0%} below 90% target; misses: {misses}"
