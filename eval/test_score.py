"""The scorer's metrics, on hand-made rankings. No mirror, no network."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import score  # noqa: E402
from systems import Hit, terms  # noqa: E402

GOLD = [
    {"rfc": 9111, "section": "4.2", "grade": "primary"},
    {"rfc": 9111, "section": "4", "grade": "acceptable"},
]


def item(gold=GOLD, avoid=(), stratum="paraphrase", split="test"):
    return {
        "id": "x",
        "stratum": stratum,
        "split": split,
        "gold": list(gold),
        "avoid": list(avoid),
    }


def hit(number, section=None, size=0):
    return Hit(number, section, "x" * size)


def test_section_rank_counts_acceptable_gold():
    result = score.score_item(item(), [hit(2616, "13"), hit(9111, "4"), hit(9111, "4.2")])
    assert result.section_rank == 2
    assert result.document_rank == 2


def test_section_match_is_exact_not_by_prefix():
    # 4.2.1 sits inside 4.2, but gold names 4.2; a parent or child only counts
    # when it is listed as acceptable.
    result = score.score_item(item(gold=GOLD[:1]), [hit(9111, "4.2.1"), hit(9111, "4")])
    assert result.section_rank is None
    assert result.document_rank == 1


def test_document_level_hit_never_matches_a_section_gold():
    result = score.score_item(item(), [hit(9111)])
    assert result.section_rank is None
    assert result.document_rank == 1


def test_whole_document_gold_matches_any_hit_on_it():
    gold = [{"rfc": 791, "section": None, "grade": "primary"}]
    assert score.score_item(item(gold=gold), [hit(791)]).section_rank == 1
    assert score.score_item(item(gold=gold), [hit(791, "3.1")]).section_rank == 1


def test_empty_results():
    result = score.score_item(item(), [])
    assert result.section_rank is None
    assert result.document_rank is None
    assert result.section_budget == {b: False for b in score.BUDGETS}
    assert result.top == []


def test_duplicate_hits_do_not_take_ranks():
    hits = [hit(2616, "13"), hit(2616, "13"), hit(2616, "13"), hit(9111, "4.2")]
    assert score.score_item(item(), hits).section_rank == 2


def test_tied_gold_hits_rank_by_first():
    # Two gold sections back to back: the item is scored on the first, and
    # MRR does not reward having both.
    results = [score.score_item(item(), [hit(9111, "4.2"), hit(9111, "4")])]
    assert score.aggregate(results)["section_mrr@10"] == 1.0


def test_budget_requires_the_gold_hit_to_fit_whole():
    tokens = score.BUDGETS[0]
    fits = [hit(1, "1", size=tokens * 4 - 10), hit(9111, "4.2", size=10)]
    overflows = [hit(1, "1", size=tokens * 4 - 10), hit(9111, "4.2", size=11)]
    assert score.within_budget(fits, lambda h: h.rfc == 9111, tokens)
    assert not score.within_budget(overflows, lambda h: h.rfc == 9111, tokens)


def test_budget_stops_at_an_oversized_hit():
    tokens = score.BUDGETS[0]
    hits = [hit(1, "1", size=tokens * 4 + 1), hit(9111, "4.2", size=1)]
    assert not score.within_budget(hits, lambda h: h.rfc == 9111, tokens)


def test_aggregate_recall_and_mrr():
    results = [
        score.score_item(item(), [hit(9111, "4.2")]),
        score.score_item(item(), [hit(1, "1"), hit(2, "1"), hit(9111, "4.2")]),
        score.score_item(item(), [hit(1, "1")] * 1 + [hit(n, "1") for n in range(2, 12)]),
        score.score_item(item(), []),
    ]
    metrics = score.aggregate(results)
    assert metrics["items"] == 4
    assert metrics["section_recall@1"] == 0.25
    assert metrics["section_recall@5"] == 0.5
    assert metrics["section_recall@10"] == 0.5
    assert metrics["section_mrr@10"] == pytest.approx((1 + 1 / 3) / 4, abs=1e-4)


def test_aggregate_of_nothing_is_zero_not_an_error():
    metrics = score.aggregate([])
    assert metrics["items"] == 0
    assert metrics["section_recall@1"] == 0.0
    assert metrics["section_mrr@10"] == 0.0


def test_current_first_and_avoid():
    obsolete = item(stratum="obsolescence", avoid=[2616, 7234])
    clean = score.score_item(obsolete, [hit(9111, "4.2"), hit(2616, "13")])
    buried = score.score_item(obsolete, [hit(2616, "13"), hit(9111, "4.2")])
    missing = score.score_item(obsolete, [hit(1, "1")])
    assert clean.current_first
    assert not buried.current_first
    # No gold at all is not "current first", whatever else came back.
    assert not missing.current_first
    metrics = score.obsolescence([clean, buried, missing])
    assert metrics["current_first"] == pytest.approx(1 / 3, abs=1e-4)
    assert metrics["avoid@5"] == pytest.approx(2 / 3, abs=1e-4)


def test_report_keeps_the_obsolescence_stratum_apart_from_currency():
    results = [score.score_item(item(stratum="obsolescence", avoid=[2616]), [hit(9111, "4.2")])]
    split = score.report(results)["test"]
    assert split["obsolescence"]["section_recall@1"] == 1.0
    assert split["currency"]["current_first"] == 1.0
    assert score.report(results)["dev"]["overall"]["items"] == 0


def test_terms_drops_question_words_and_repeats():
    assert terms("How does a cache cache a stored response?") == ["cache", "stored", "response"]
    assert terms("BGP LOCAL_PREF") == ["bgp", "local", "pref"]
