#!/usr/bin/env python3
"""Report how many of each query's terms appear in its primary gold text.

A paraphrase stratum is only worth its name if this number is low for it: a
set whose queries reuse the gold section's own words rewards lexical retrieval
by construction. The figure is generated here rather than stored in the items,
so it always reflects the current text and tokenizer.

    python3 eval/overlap.py [--mirror PATH] [--items PATH]

Prints one tab-separated row per item, then the mean per stratum.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "core"))
sys.path.insert(0, str(HERE))

import rfc  # noqa: E402
from check_gold import ITEMS, load_items  # noqa: E402

WORD = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")
# Function words carry no retrieval signal, and counting them would lift every
# item's overlap toward the same floor.
_STOPWORDS = """a about after all also an and any are as at be been before being between
    both but by can could did do does doing each for from had has have how i if
    in into is it its may me might more most must my no not of on once only or
    other our out over own same should so some such than that the their them
    then there these they this those through to too under until up very was we
    were what when where which while who whom why will with would you your"""
STOPWORDS = frozenset(_STOPWORDS.split())


def terms(text: str) -> set[str]:
    return {w for w in WORD.findall(text.lower()) if w not in STOPWORDS}


def gold_text(mirror: Path, number: int, section: str | None) -> str:
    lines = rfc.split_lines(rfc.read_document(mirror, number))
    if section is None:
        return "\n".join(lines)
    start, end, _ = rfc.section_range(rfc.find_sections(lines), section, len(lines))
    return rfc.slice_lines(lines, start, end, raw=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mirror", help="mirror directory (default: as the core resolves it)")
    parser.add_argument("--items", default=str(ITEMS), help="items file")
    args = parser.parse_args(argv)
    mirror = rfc.resolve_mirror(args.mirror)

    by_stratum: dict[str, list[float]] = defaultdict(list)
    print("id\tstratum\toverlap")
    for item in load_items(Path(args.items)):
        query = terms(item["query"])
        text = "\n".join(
            gold_text(mirror, g["rfc"], g["section"])
            for g in item["gold"]
            if g["grade"] == "primary"
        )
        present = query & terms(text)
        share = len(present) / len(query) if query else 0.0
        by_stratum[item["stratum"]].append(share)
        print(f"{item['id']}\t{item['stratum']}\t{share:.2f}")

    print()
    for stratum, shares in sorted(by_stratum.items()):
        print(f"# {stratum}\tn={len(shares)}\tmean={sum(shares) / len(shares):.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
