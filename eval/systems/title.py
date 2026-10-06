"""Title search, the way `rfc search` ranks titles.

`search_titles` requires every query word in the title, which no
natural-language question satisfies, so this ranks by how many of the query's
content words a title holds instead, with the same substring match. Ties keep
`search_titles`' order: current documents before obsoleted ones, then by
number.

Document level only. A title hit's text is the whole document, because that is
what an agent holding nothing but a number has to read.
"""

from __future__ import annotations

from systems import Corpus, Hit, rfc, terms

_corpus: Corpus | None = None


def retrieve(query: str, k: int) -> list[Hit]:
    global _corpus
    if _corpus is None:
        _corpus = Corpus()
    words = terms(query)
    records = rfc.load_index(_corpus.mirror, offline_only=True)
    scored = []
    for number, record in records.items():
        if record.not_issued:
            continue
        title = record.title.lower()
        score = sum(word in title for word in words)
        if score:
            scored.append((-score, bool(record.obsoleted_by), number))
    scored.sort()
    return [Hit(number, None, _corpus.document(number)) for _, _, number in scored[:k]]
