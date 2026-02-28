from __future__ import annotations

from backend.searcher import _min_max, combine_weighted_score


def test_min_max_handles_equal_values():
    assert _min_max({"a": 3.0, "b": 3.0}) == {"a": 1.0, "b": 1.0}


def test_pagerank_can_change_ranking_order(isolated_environment):
    stronger_pagerank = combine_weighted_score(0.81, 0.80, 1.0)
    weaker_pagerank = combine_weighted_score(0.85, 0.80, 0.0)
    assert stronger_pagerank > weaker_pagerank
