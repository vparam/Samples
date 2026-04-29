"""Mini golden-set evaluator. Runs the queries from the brief plus
adversarial / out-of-corpus queries and prints a pass/fail summary.

Architecture section 6 layer 3: 'CI fails if any of these returns content.'
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from prototype.backend import db, ingestion  # noqa: E402
from prototype.backend.search import get_index  # noqa: E402


# (query, expected_kind) where expected_kind is:
#   "hit"   - we expect at least one indexed result
#   "none"  - we expect the no-results state (adversarial / out-of-corpus)
GOLDEN = [
    # From the brief
    ("Why should a customer work with us?",                 "hit"),
    ("What case studies do we have around food-grade packaging?", "hit"),
    ("Do we have any content about sustainable materials?", "hit"),
    ("What have we published recently about supply chain?", "hit"),
    ("I want content around why a customer should work with us", "hit"),
    # Entity-anchored
    ("pharma-grade glass case studies",                     "hit"),
    ("airless pump cosmetics",                              "hit"),
    ("borosilicate vials USP 660",                          "hit"),
    # Adversarial / out-of-corpus
    ("What is the population of Tokyo?",                    "none"),
    ("Who is the current US president?",                    "none"),
    ("Tell me about the Eiffel Tower",                      "none"),
    ("How do I bake sourdough bread?",                      "none"),
]


def main() -> int:
    db.init_db()
    with db.connect() as cx:
        n = cx.execute(
            "SELECT COUNT(*) AS n FROM documents WHERE deleted_at IS NULL"
        ).fetchone()["n"]
    if n == 0:
        ingestion.ingest_seed()
    idx = get_index()
    idx.load()

    failures = 0
    print(f"{'EXPECTED':<7} {'ACTUAL':<7} {'TOP':<10} QUERY")
    print("-" * 80)
    for q, expected in GOLDEN:
        out = idx.search(q, k=5)
        actual = "none" if out["no_results"] else "hit"
        top = "—"
        if out["results"]:
            top = f"{out['results'][0]['score']:.3f}"
        ok = (actual == expected)
        marker = "PASS" if ok else "FAIL"
        if not ok:
            failures += 1
        print(f"{expected:<7} {actual:<7} {top:<10} {q}   [{marker}]")
        if expected == "hit" and actual == "hit":
            print(f"   -> {out['results'][0]['title']}")

    print("-" * 80)
    print(f"failures: {failures} / {len(GOLDEN)}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
