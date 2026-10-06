"""Full-text search over the mirror, the way `rfc search --fulltext` ranks.

`search_fulltext` takes one literal string, and a whole question never appears
verbatim, so the query's content words go in as a word-boundary alternation:
documents rank by how many lines match any of them, as the CLI ranks them.
Each quoted line is then mapped to the deepest section holding it, which is
what lets this system score at section level.

A document contributes its matched sections in the order of the lines quoted,
up to `LINES_PER_DOC` of them, the CLI's default. A match in the front matter
before the first heading yields a document-level hit whose text is that front
matter.
"""

from __future__ import annotations

from systems import Corpus, Hit, rfc, terms

LINES_PER_DOC = 3

_corpus: Corpus | None = None


def retrieve(query: str, k: int) -> list[Hit]:
    global _corpus
    if _corpus is None:
        _corpus = Corpus()
    words = terms(query)
    if not words:
        return []
    pattern = r"\b(?:" + "|".join(words) + r")\b"
    results, _, _ = rfc.search_fulltext(
        _corpus.mirror, pattern, limit=k, max_lines_per_doc=LINES_PER_DOC, use_regex=True
    )
    hits: list[Hit] = []
    seen: set[tuple[int, str | None]] = set()
    for result in results:
        number = result["number"]
        for match in result["matches"]:
            section = _corpus.section_at(number, match["line"])
            key = (number, section["section"] if section else None)
            if key in seen:
                continue
            seen.add(key)
            if section is None:
                first = _corpus.sections(number)
                end = first[0]["line"] - 1 if first else len(_corpus.lines(number))
                hits.append(Hit(number, None, _corpus.text(number, 1, end)))
            else:
                end = section["line"] + section["lines"] - 1
                hits.append(
                    Hit(number, section["section"], _corpus.text(number, section["line"], end))
                )
    return hits[:k]
