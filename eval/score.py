#!/usr/bin/env python3
"""Score a retrieval system against the eval items.

Standard library only. Runs every item through `systems.<name>.retrieve`,
writes `results/<name>.json` with every metric for both splits and each item's
ranks, and prints one split's table as markdown. Same mirror, same numbers.

    python3 eval/score.py --system rg [--split test|dev] [--mirror PATH]
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from check_gold import ITEMS, STRATA, load_items  # noqa: E402
from systems import Corpus, Hit, rfc  # noqa: E402

RESULTS = HERE / "results"
# How many hits to ask a system for. Recall stops at 10; the rest is there for
# the budgets, which small sections can fill past rank 10.
DEPTH = 20
KS = (1, 5, 10)
MRR_K = 10
# Tokens, counted as bytes / 4 as the README's charts count them.
BUDGETS = (2000, 8000)
AVOID_K = 5


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------


def dedupe(hits: Sequence[Hit]) -> list[Hit]:
    """First occurrence of each (rfc, section). A system that returns the same
    passage twice would otherwise fill its own top 5 with one answer."""
    seen: set[tuple[int, str | None]] = set()
    out = []
    for hit in hits:
        key = (hit.rfc, hit.section)
        if key not in seen:
            seen.add(key)
            out.append(hit)
    return out


def section_match(hit: Hit, gold: Sequence[dict]) -> bool:
    """Exact section number, as gold is written. A gold section of None is the
    whole document, so any hit on it counts; a hit of None only meets that."""
    return any(
        hit.rfc == g["rfc"] and (g["section"] is None or hit.section == g["section"]) for g in gold
    )


def document_match(hit: Hit, gold: Sequence[dict]) -> bool:
    return any(hit.rfc == g["rfc"] for g in gold)


def first_rank(hits: Sequence[Hit], matches: Callable[[Hit], bool]) -> int | None:
    """1-based rank of the first matching hit, or None."""
    for rank, hit in enumerate(hits, 1):
        if matches(hit):
            return rank
    return None


def within_budget(hits: Sequence[Hit], matches: Callable[[Hit], bool], tokens: int) -> bool:
    """Whether a matching hit fits whole inside the first `tokens` of the hits
    read in rank order. The read stops at the budget: a hit that overflows it
    is cut, and so is everything after it, however small."""
    spent = 0
    for hit in hits:
        spent += len(hit.text.encode("utf-8"))
        if spent > tokens * 4:
            return False
        if matches(hit):
            return True
    return False


# --------------------------------------------------------------------------
# Per item and aggregate
# --------------------------------------------------------------------------


@dataclass
class ItemResult:
    id: str
    stratum: str
    split: str
    section_rank: int | None
    document_rank: int | None
    section_budget: dict[int, bool]
    document_budget: dict[int, bool]
    avoid_rank: int | None
    top: list[str]

    @property
    def current_first(self) -> bool:
        """A gold document ranks in the top 10 and no avoided RFC above it."""
        if self.document_rank is None or self.document_rank > MRR_K:
            return False
        return self.avoid_rank is None or self.avoid_rank > self.document_rank

    def as_json(self) -> dict:
        return {
            "id": self.id,
            "stratum": self.stratum,
            "split": self.split,
            "section_rank": self.section_rank,
            "document_rank": self.document_rank,
            "section_budget": {str(b): v for b, v in self.section_budget.items()},
            "document_budget": {str(b): v for b, v in self.document_budget.items()},
            "avoid_rank": self.avoid_rank,
            "top": self.top,
        }


def label(hit: Hit) -> str:
    return f"{hit.rfc}" if hit.section is None else f"{hit.rfc}#{hit.section}"


def score_item(item: dict, hits: Sequence[Hit]) -> ItemResult:
    hits = dedupe(hits)
    gold = item["gold"]
    avoid = set(item["avoid"])

    def by_section(h: Hit) -> bool:
        return section_match(h, gold)

    def by_document(h: Hit) -> bool:
        return document_match(h, gold)

    return ItemResult(
        id=item["id"],
        stratum=item["stratum"],
        split=item["split"],
        section_rank=first_rank(hits, by_section),
        document_rank=first_rank(hits, by_document),
        section_budget={b: within_budget(hits, by_section, b) for b in BUDGETS},
        document_budget={b: within_budget(hits, by_document, b) for b in BUDGETS},
        avoid_rank=first_rank(hits, lambda h: h.rfc in avoid),
        top=[label(h) for h in hits[:MRR_K]],
    )


def _share(flags: Sequence[bool]) -> float:
    return round(sum(flags) / len(flags), 4) if flags else 0.0


def _hit_at(rank: int | None, k: int) -> bool:
    return rank is not None and rank <= k


def aggregate(results: Sequence[ItemResult]) -> dict:
    """Shares of items, so every figure reads as "this fraction of questions"."""
    out: dict = {"items": len(results)}
    for level in ("section", "document"):
        ranks = [getattr(r, f"{level}_rank") for r in results]
        for k in KS:
            out[f"{level}_recall@{k}"] = _share([_hit_at(rank, k) for rank in ranks])
        for b in BUDGETS:
            out[f"{level}_budget@{b}"] = _share([getattr(r, f"{level}_budget")[b] for r in results])
    reciprocal = [1 / r.section_rank for r in results if _hit_at(r.section_rank, MRR_K)]
    out[f"section_mrr@{MRR_K}"] = round(sum(reciprocal) / len(results), 4) if results else 0.0
    return out


def obsolescence(results: Sequence[ItemResult]) -> dict:
    members = [r for r in results if r.stratum == "obsolescence"]
    return {
        "items": len(members),
        "current_first": _share([r.current_first for r in members]),
        f"avoid@{AVOID_K}": _share([_hit_at(r.avoid_rank, AVOID_K) for r in members]),
    }


def resolution(returned: Sequence[Hit], corpus: Corpus) -> dict:
    """Share of returned (rfc, section) pairs that name a real heading. A
    system that invents section numbers has a bug, not a low score."""
    pairs = {(h.rfc, h.section) for h in returned if h.section is not None}
    unresolved = sorted(
        f"{n}#{s}" for n, s in pairs if not any(x["section"] == s for x in corpus.sections(n))
    )
    return {
        "pairs": len(pairs),
        "resolved": round(1 - len(unresolved) / len(pairs), 4) if pairs else 1.0,
        "unresolved": unresolved,
    }


def report(results: Sequence[ItemResult]) -> dict:
    by_split: dict = {}
    for split in ("dev", "test"):
        members = [r for r in results if r.split == split]
        by_split[split] = {
            "overall": aggregate(members),
            **{s: aggregate([r for r in members if r.stratum == s]) for s in sorted(STRATA)},
            # Not under "obsolescence", which is that stratum's recall row.
            "currency": obsolescence(members),
        }
    return by_split


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

COLUMNS = (
    ("n", "items"),
    ("sec@1", "section_recall@1"),
    ("sec@5", "section_recall@5"),
    ("sec@10", "section_recall@10"),
    ("MRR@10", f"section_mrr@{MRR_K}"),
    ("doc@1", "document_recall@1"),
    ("doc@10", "document_recall@10"),
    *((f"sec {b // 1000}k", f"section_budget@{b}") for b in BUDGETS),
    *((f"doc {b // 1000}k", f"document_budget@{b}") for b in BUDGETS),
)


def table(split_report: dict) -> str:
    rows = ["| | " + " | ".join(c for c, _ in COLUMNS) + " |"]
    rows.append("|---" * (len(COLUMNS) + 1) + "|")
    for name in ("overall", *sorted(STRATA)):
        metrics = split_report[name]
        cells = [str(metrics[k]) if k == "items" else f"{metrics[k]:.2f}" for _, k in COLUMNS]
        rows.append(f"| {name} | " + " | ".join(cells) + " |")
    obs = split_report["currency"]
    rows.append("")
    rows.append(
        f"Obsolescence ({obs['items']} items): current-first {obs['current_first']:.2f}, "
        f"avoid@{AVOID_K} {obs[f'avoid@{AVOID_K}']:.2f}"
    )
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--system", required=True, help="module name under eval/systems/")
    parser.add_argument("--split", choices=("test", "dev"), default="test", help="table to print")
    parser.add_argument("--mirror", help="mirror directory (default: as the core resolves it)")
    parser.add_argument("--items", default=str(ITEMS), help="items file")
    args = parser.parse_args(argv)

    if args.mirror:
        # Systems resolve the mirror themselves, the way the core does.
        os.environ["RFC_MIRROR"] = args.mirror
    corpus = Corpus(rfc.resolve_mirror(args.mirror))
    system = importlib.import_module(f"systems.{args.system}")
    items = load_items(Path(args.items))

    results = []
    returned: list[Hit] = []
    for n, item in enumerate(items, 1):
        hits = system.retrieve(item["query"], DEPTH)
        returned += hits
        results.append(score_item(item, hits))
        print(f"\r{n}/{len(items)}", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)

    validated = sum(item["validated_on"] is not None for item in items)
    payload = {
        "system": args.system,
        "depth": DEPTH,
        "items": len(items),
        "validated": validated,
        "splits": report(results),
        "resolution": resolution(returned, corpus),
        "per_item": [r.as_json() for r in results],
    }
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{args.system}.json"
    out.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")

    print(f"## {args.system}, {args.split} split\n")
    if validated < len(items):
        print(f"{validated} of {len(items)} items validated; the rest are drafts.\n")
    print(table(payload["splits"][args.split]))
    res = payload["resolution"]
    print(f"\nResolution: {res['resolved']:.2%} of {res['pairs']} returned sections resolve.")
    print(f"\nwrote {out.relative_to(Path.cwd()) if out.is_relative_to(Path.cwd()) else out}")
    return 1 if res["unresolved"] else 0


if __name__ == "__main__":
    sys.exit(main())
