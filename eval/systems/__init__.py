"""Retrieval systems the scorer can rank.

A system is a module here exposing `retrieve(query, k) -> list[Hit]`, best
first. `score.py --system NAME` imports `systems.NAME`.

Everything a system needs from the corpus goes through `core/rfc.py`, so a
section a system returns is one `rfc get --section` can return too, and its
text is what that read would print.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "core"))

import rfc  # noqa: E402

# The words a query is matched on, the same for every system: a baseline that
# tokenised differently from the system it is compared with would measure the
# tokeniser.
terms = rfc.query_terms


@dataclass(frozen=True)
class Hit:
    """One retrieved passage.

    `section` is the RFC's own section number, or None when the system only
    knows the document. `text` is what an agent would read for this hit, and is
    what the equal-budget metric spends.
    """

    rfc: int
    section: str | None
    text: str


class Corpus:
    """A mirror's documents, split and sectioned once per process.

    Reads straight from the mirror's files, never through the section index or
    the network, so the corpus a system is scored on is the one on disk.
    """

    def __init__(self, mirror: Path | None = None) -> None:
        self.mirror = mirror or rfc.resolve_mirror()
        if not rfc.is_populated(self.mirror):
            raise SystemExit(f"{self.mirror} is not a populated mirror; run `rfc sync` first")
        self._lines: dict[int, list[str]] = {}
        self._sections: dict[int, list[dict]] = {}

    def lines(self, number: int) -> list[str]:
        if number not in self._lines:
            path = rfc.document_path(self.mirror, number)
            text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
            self._lines[number] = rfc.split_lines(text)
        return self._lines[number]

    def sections(self, number: int) -> list[dict]:
        if number not in self._sections:
            self._sections[number] = rfc.find_sections(self.lines(number))
        return self._sections[number]

    def text(self, number: int, start: int, end: int) -> str:
        """Lines start..end, 1-based and inclusive, without page furniture, as
        `rfc get` prints them."""
        return rfc.slice_lines(self.lines(number), start, end, raw=False)

    def document(self, number: int) -> str:
        return self.text(number, 1, len(self.lines(number)))

    def section_text(self, number: int, section: str | None) -> str:
        """What `get --section` returns, or the front matter for None."""
        sections = self.sections(number)
        total = len(self.lines(number))
        if section is None:
            return self.text(number, 1, sections[0]["line"] - 1 if sections else total)
        first, last, _ = rfc.section_range(sections, section, total)
        return self.text(number, first, last)

    def section_at(self, number: int, line: int) -> dict | None:
        return rfc.section_at(self.sections(number), line, len(self.lines(number)))
