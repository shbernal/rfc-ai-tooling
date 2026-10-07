"""The section index: FTS5 BM25 over every section, as `rfc search --fulltext`
ranks when the index is present.

The query goes to the core exactly as a user's would. A hit's text is what
`rfc get --section` returns for it, read from the mirror.

Reads the index at `RFC_SECTION_INDEX` if set, else the mirror's own. For
tuning on the dev split, `RFC_BM25_HEADING_WEIGHT` and `RFC_BM25_OBSOLETE_WEIGHT`
override the core's defaults; a reported number uses the defaults.
"""

from __future__ import annotations

import os
from pathlib import Path

from systems import Corpus, Hit, rfc

_corpus: Corpus | None = None
_conn = None


def retrieve(query: str, k: int) -> list[Hit]:
    global _corpus, _conn
    if _corpus is None:
        _corpus = Corpus()
        override = os.environ.get("RFC_SECTION_INDEX")
        path = Path(override) if override else rfc.section_index_path(_corpus.mirror)
        _conn = rfc.open_section_index(path)
        if _conn is None:
            raise SystemExit(f"no section index at {path}; run `rfc index build`")
    results, _ = rfc.search_sections(
        _conn,
        query,
        k,
        heading_weight=float(os.environ.get("RFC_BM25_HEADING_WEIGHT", rfc.HEADING_WEIGHT)),
        obsolete_weight=float(os.environ.get("RFC_BM25_OBSOLETE_WEIGHT", rfc.OBSOLETE_WEIGHT)),
    )
    return [
        Hit(r["number"], r["section"], _corpus.section_text(r["number"], r["section"]))
        for r in results
    ]
