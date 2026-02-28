from __future__ import annotations

from backend.pagerank import normalize_pagerank


def test_normalize_pagerank_bounds():
    assert normalize_pagerank(0.0, 1.0) == 0.0
    assert 0.0 < normalize_pagerank(0.5, 1.0) < 1.0
    assert normalize_pagerank(1.0, 1.0) == 1.0
