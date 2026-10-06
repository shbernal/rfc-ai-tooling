"""Retrieval systems the scorer can rank.

A system is a module here exposing `retrieve(query, k) -> list[Hit]`, best
first. `score.py --system NAME` imports `systems.NAME`.

Everything a system needs from the corpus goes through `core/rfc.py`, so a
section a system returns is one `rfc get --section` can return too.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "core"))

import rfc  # noqa: E402


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


# Question words and filler. A natural-language query matched term by term
# would otherwise rank documents by how often they say "what" and "does".
_STOPWORDS = """
    a about above after again against all also am an and any are as at be
    because been before being below between both but by can could did do does
    doing down during each else few for from further get gets got had has have
    having how i if in into is it its itself just let may me might more most
    must my no nor not now of off on once one only or other our out over own
    per same say says should so some such than that the their them then there
    these they this those through to too under until up upon use used using
    very via want was way we were what when where whether which while who whom
    why will with within without would you your
"""
STOPWORDS = frozenset(_STOPWORDS.split())

_WORD = re.compile(r"[a-z0-9]+")


def terms(query: str) -> list[str]:
    """Content words of a query, lowercased, in order, without repeats."""
    seen: dict[str, None] = {}
    for word in _WORD.findall(query.lower()):
        if len(word) > 1 and word not in STOPWORDS:
            seen.setdefault(word)
    return list(seen)


class Corpus:
    """A mirror's documents, split and sectioned once per process."""

    def __init__(self, mirror: Path | None = None) -> None:
        self.mirror = mirror or rfc.resolve_mirror()
        if not rfc.is_populated(self.mirror):
            raise SystemExit(f"{self.mirror} is not a populated mirror; run `rfc sync` first")
        self._lines: dict[int, list[str]] = {}
        self._sections: dict[int, list[dict]] = {}

    def lines(self, number: int) -> list[str]:
        if number not in self._lines:
            path = rfc.document_path(self.mirror, number)
            # The index lists RFCs the mirror may not hold; never fetch here,
            # or a score would depend on the network.
            text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
            self._lines[number] = rfc.split_lines(text)
        return self._lines[number]

    def sections(self, number: int) -> list[dict]:
        if number not in self._sections:
            self._sections[number] = rfc.find_sections(self.lines(number))
        return self._sections[number]

    def text(self, number: int, start: int, end: int) -> str:
        """Lines start..end, 1-based and inclusive."""
        return "\n".join(self.lines(number)[start - 1 : end])

    def document(self, number: int) -> str:
        return "\n".join(self.lines(number))

    def section_at(self, number: int, line: int) -> dict | None:
        """The deepest section whose range holds a 1-based line, or None in the
        front matter before the first heading."""
        sections = self.sections(number)
        total = len(self.lines(number))
        found = None
        for i, section in enumerate(sections):
            if section["line"] > line:
                break
            if line <= rfc._section_end(sections, i, total):
                found = section
        return found
