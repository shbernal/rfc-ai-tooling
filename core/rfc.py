#!/usr/bin/env python3
"""Look up IETF RFCs from the command line.

Standard library only, deliberately: this file is vendored verbatim into a
ClawHub skill and into a PyPI package, and both need to run wherever there is a
Python interpreter and nothing else.

Two runtime modes, decided by one predicate — whether a local mirror is
populated. Online mode fetches documents on demand over HTTPS; offline mode
reads them from disk and can search their full text. There is no build-time
flavour and no separate "offline edition"; `rfc sync` moves you from one mode to
the other and everything else behaves the same.

The index-parsing approach here — match entries by a leading RFC number, treat
"Not Issued" as a placeholder — follows mcp-server-ietf (MIT, Copyright (c) 2025
Jeff Chiang), https://github.com/tizee/mcp-server-ietf. See NOTICE. The parser
itself is a rewrite; the original's regexes are documented as counter-examples
in parse_index() below.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from email.utils import formatdate
from pathlib import Path

__version__ = "0.2.3"

INDEX_URL = "https://www.rfc-editor.org/rfc-index.txt"
RFC_URL = "https://www.rfc-editor.org/rfc/rfc{number}.txt"
RSYNC_MODULE = "rsync.rfc-editor.org::rfcs-text-only/"

# 512 MB of RFC text is data the user asked for, not a cache a cleaner should be
# free to reclaim, so this lives under ~/.local/share rather than ~/.cache.
DEFAULT_MIRROR = Path.home() / ".local" / "share" / "rfc-ai-tooling"

INDEX_TTL_SECONDS = 7 * 24 * 60 * 60
# Where "just read the whole thing" stops being reasonable. Short RFCs are
# cheap and refusing them would be pedantry; past roughly 20k tokens an
# unscoped read stops being a document and becomes a context window. Both
# surfaces advise reading one section, and advice is the weaker half of a
# guardrail — this is the half that holds when the advice is skipped.
WHOLE_DOCUMENT_LINE_LIMIT = 1500
# Enough documents that full-text search is worth offering. A handful of
# on-demand fetches accumulating in the mirror should not look like a sync.
POPULATED_THRESHOLD = 1000
SYNC_STAMP = ".rfc-sync"

USER_AGENT = f"rfc-ai-tooling/{__version__} (+https://github.com/shbernal/rfc-ai-tooling)"


class RFCError(Exception):
    """Anything the user should see as a clean error rather than a traceback."""


# A host that ships its own entry point for this CLI sets this to the command
# that reaches it. Nothing observable from inside the process distinguishes an
# ephemeral environment from an installed one — `uvx` leaves the package
# importable and its bin directory on PATH — so the spelling has to come from
# the surface that knows how it is distributed, not from a guess made here.
CLI_NAME: str | None = None


def invocation() -> str:
    """How to re-run this program, spelled the way the caller actually reached it.

    Error messages here tell the reader to run another command, and the two
    surfaces disagree about what that command is. The PyPI package installs no
    `rfc` console script and the skill ships this file with nothing on PATH, so
    a hardcoded "run `rfc sync`" is advice that fails as typed in the place it
    fires most often — the --fulltext refusal, which is the first wall an agent
    hits on an unsynced machine.

    A host that set CLI_NAME has already answered the question and is believed.
    Otherwise: vendored into a package, this file is reachable as a module
    whether it was run with -m or imported by the MCP server, and the module
    path is right in both cases. Standalone, argv[0] is trusted only when it
    points at this very file; anything else is some other program's entry point.
    """
    if CLI_NAME:
        return CLI_NAME
    if __package__:
        return f"python3 -m {__package__}.{Path(__file__).stem}"
    argv0 = sys.argv[0] if sys.argv else ""
    if not argv0:
        return "rfc"
    if Path(argv0).name in {"rfc", "rfc.exe"}:
        return "rfc"
    try:
        if Path(argv0).resolve() == Path(__file__).resolve():
            return f"python3 {argv0}"
    except OSError:
        pass
    return "rfc"


# --------------------------------------------------------------------------
# Index records
# --------------------------------------------------------------------------


@dataclass
class Record:
    number: int
    title: str = ""
    authors: str = ""
    date: str = ""
    status: str = ""
    doi: str = ""
    obsoletes: list[int] = field(default_factory=list)
    obsoleted_by: list[int] = field(default_factory=list)
    updates: list[int] = field(default_factory=list)
    updated_by: list[int] = field(default_factory=list)
    also: list[str] = field(default_factory=list)
    not_issued: bool = False

    def to_dict(self) -> dict:
        return {
            "number": self.number,
            "title": self.title,
            "authors": self.authors,
            "date": self.date,
            "status": self.status,
            "doi": self.doi,
            "obsoletes": self.obsoletes,
            "obsoleted_by": self.obsoleted_by,
            "updates": self.updates,
            "updated_by": self.updated_by,
            "also": self.also,
            "not_issued": self.not_issued,
            "obsolete": bool(self.obsoleted_by),
            "header": self.header(),
        }

    def header(self) -> str:
        """The banner shown above every result.

        Obsolescence is the highest-value field in the index and the easiest for
        a model to skip, so it goes on its own line with a marker, never folded
        into a list of attributes.
        """
        if self.not_issued:
            return f"RFC {self.number} — Not Issued"
        status = f"  [{self.status}]" if self.status else ""
        lines = [f"RFC {self.number} — {self.title}{status}"]
        if self.obsoleted_by:
            refs = ", ".join(str(n) for n in self.obsoleted_by)
            lines.append(f"!! OBSOLETED BY: RFC {refs}")
        if self.updated_by:
            refs = ", ".join(str(n) for n in self.updated_by)
            lines.append(f"!! UPDATED BY: RFC {refs}")
        return "\n".join(lines)


# The metadata block that closes every entry. Format/Status/DOI must be followed
# by a colon: RFC 4304's *title* contains a bare "(DOI)" and matching that as
# metadata truncates the title and loses the date.
_META_START = re.compile(
    r"\s*\((?:Format:|Status:|DOI:|Obsoletes\s|Obsoleted by\s|Updates\s|Updated by\s|Also\s)"
)
_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_DATE_TAIL = re.compile(rf"\s*(?:(?:{_MONTHS})\s+)?\d{{4}}\.?\s*$")
# Where the author list starts: one to four initials followed by a surname.
# Initials may be hyphenated ("M-K.", "Y.-K.") and surnames may begin lowercase
# ("N. ten Oever"), both of which occur in the real index.
_AUTHOR_ONSET = re.compile(r"^(?:[A-Z](?:[.\-]{1,2}[A-Z])*\.\s*){1,4}[A-Za-z]")
_SENTENCE_BREAK = re.compile(r"\.\s+")
_REFS = re.compile(r"\((Obsoletes|Obsoleted by|Updates|Updated by)\s+([^)]*)\)")
_ALSO = re.compile(r"\(Also\s+([^)]*)\)")
_STATUS = re.compile(r"\(Status:\s*([^)]*)\)")
_DOI = re.compile(r"\(DOI:\s*([^)]*)\)")
_RFC_REF = re.compile(r"RFC0*(\d+)")


def parse_index(text: str) -> dict[int, Record]:
    """Parse rfc-index.txt into records keyed by RFC number.

    The file's shape, which the three rules below all depend on:

        2616 Hypertext Transfer Protocol -- HTTP/1.1. R. Fielding, J. Gettys, J.
             Mogul, H. Frystyk, L. Masinter, P. Leach, T. Berners-Lee. June 1999.
             (Format: TXT, PS, PDF, HTML) (Obsoletes RFC2068) (Obsoleted by
             RFC7230, RFC7231, RFC7232, RFC7233, RFC7234, RFC7235) (Updated by
             RFC2817, RFC5785, RFC6266, RFC6585) (Status: DRAFT STANDARD) (DOI:
             10.17487/RFC2616)

    Three traps, each of which has bitten a previous implementation:

    1. Entries begin at column 0; continuation lines are indented and entries are
       separated by blank lines. Reading line by line therefore sees only the
       first physical line of an entry and loses most of the metadata. Join the
       record before parsing anything.

    2. RFC numbers are *not* zero-padded. A regex expecting four or five digits
       silently drops all 999 RFCs below 1000 — including 768, 791, 793 and 959.

    3. The title cannot be taken as everything before the first period. That
       yields "Hypertext Transfer Protocol -- HTTP/1" above, and corrupts every
       title containing a version number, an abbreviation or a hostname. The
       title ends where the author list begins; find that boundary explicitly.
    """
    records: dict[int, Record] = {}
    for block in re.split(r"\n\s*\n", text):
        lines = block.split("\n")
        if not lines or not re.match(r"^\d+\s", lines[0]):
            continue
        joined = " ".join(line.strip() for line in lines if line.strip())
        record = _parse_record(joined)
        if record is not None:
            records[record.number] = record
    return records


def _parse_record(joined: str) -> Record | None:
    num_text, _, rest = joined.partition(" ")
    try:
        number = int(num_text)
    except ValueError:
        return None

    meta_match = _META_START.search(rest)
    prose = (rest[: meta_match.start()] if meta_match else rest).strip()
    metadata = rest[meta_match.start() :] if meta_match else ""

    if prose.rstrip(".").strip() == "Not Issued":
        return Record(number=number, title="Not Issued", not_issued=True)

    record = Record(number=number)

    date_match = _DATE_TAIL.search(prose)
    if date_match:
        record.date = prose[date_match.start() :].strip().rstrip(".")
        body = prose[: date_match.start()]
    else:
        body = prose
    body = body.strip()

    split_at = None
    for match in _SENTENCE_BREAK.finditer(body):
        if _AUTHOR_ONSET.match(body[match.end() :]):
            split_at = match
            break
    if split_at is None:
        # Corporate authorship ("Sun Microsystems", "International Organization
        # for Standardization") has no initials to key on; the first sentence
        # break is the best available boundary.
        split_at = _SENTENCE_BREAK.search(body)

    if split_at is None:
        record.title = body.rstrip(".")
    else:
        record.title = body[: split_at.start()].strip()
        # The author list keeps its terminating period, so that a trailing
        # "Ed." stays "Ed." rather than becoming "Ed" — at the cost of a doubled
        # period where the last author is already an abbreviation, which the
        # index itself prints as "J. Reschke, Ed..".
        authors = body[split_at.end() :].strip()
        record.authors = authors[:-1] if authors.endswith("..") else authors

    for match in _REFS.finditer(metadata):
        refs = [int(n) for n in _RFC_REF.findall(match.group(2))]
        key = match.group(1).lower().replace(" ", "_")
        getattr(record, key).extend(refs)
    for match in _ALSO.finditer(metadata):
        record.also.append(match.group(1).strip())
    status_match = _STATUS.search(metadata)
    if status_match:
        record.status = status_match.group(1).strip()
    doi_match = _DOI.search(metadata)
    if doi_match:
        record.doi = doi_match.group(1).strip()
    return record


# --------------------------------------------------------------------------
# Mirror and mode
# --------------------------------------------------------------------------


def resolve_mirror(override: str | None = None) -> Path:
    if override:
        return Path(override).expanduser()
    env = os.environ.get("RFC_MIRROR")
    if env:
        return Path(env).expanduser()
    return DEFAULT_MIRROR


def index_path(mirror: Path) -> Path:
    return mirror / "rfc-index.txt"


def document_path(mirror: Path, number: int) -> Path:
    return mirror / f"rfc{number}.txt"


def count_documents(mirror: Path) -> int:
    if not mirror.is_dir():
        return 0
    return sum(1 for _ in mirror.glob("rfc[0-9]*.txt"))


def is_populated(mirror: Path) -> bool:
    """True when the mirror holds enough of the corpus to search its full text."""
    if not index_path(mirror).exists():
        return False
    if (mirror / SYNC_STAMP).exists():
        return True
    return count_documents(mirror) > POPULATED_THRESHOLD


# --------------------------------------------------------------------------
# Network
# --------------------------------------------------------------------------


def _fetch(
    url: str,
    if_modified_since: float | None = None,
    etag: str | None = None,
    want_etag: bool = False,
) -> bytes | None | tuple[bytes | None, str | None]:
    """GET a URL. Returns None (or (None, etag)) if the server answers 304."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    if if_modified_since is not None:
        request.add_header("If-Modified-Since", formatdate(if_modified_since, usegmt=True))
    if etag:
        request.add_header("If-None-Match", etag)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            if want_etag:
                return body, response.headers.get("ETag")
            return body
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return (None, etag) if want_etag else None
        if exc.code == 404:
            raise RFCError(f"not found: {url}") from exc
        raise RFCError(f"HTTP {exc.code} fetching {url}") from exc
    except urllib.error.URLError as exc:
        raise RFCError(f"network error fetching {url}: {exc.reason}") from exc


def ensure_index(mirror: Path, ttl: int = INDEX_TTL_SECONDS, force: bool = False) -> Path:
    """Return the local index, refreshing it if it is missing or older than the TTL.

    The index must not be a write-once cache. An index fetched in January will
    report an RFC published in March as nonexistent, even though its URL fetches
    perfectly well, and there is no way for the user to tell why.

    Revalidation sends both If-None-Match and If-Modified-Since. As of
    2026-08-01 the RFC Editor's CDN honours neither — it answers 200 with the
    full 2 MB even when handed back its own ETag verbatim — so treat the 304
    path as an optimisation that may start working rather than one that does.
    That is affordable only because the TTL is a week; do not shorten it without
    re-checking whether conditional requests have started working.
    """
    path = index_path(mirror)
    etag_path = mirror / ".rfc-index.etag"
    fresh_enough = False
    if path.exists() and not force:
        age = time.time() - path.stat().st_mtime
        fresh_enough = age < ttl
    if fresh_enough:
        return path

    known_etag = None
    if path.exists() and etag_path.exists():
        known_etag = etag_path.read_text(encoding="utf-8").strip() or None

    result = _fetch(
        INDEX_URL,
        if_modified_since=path.stat().st_mtime if path.exists() else None,
        etag=known_etag,
        want_etag=True,
    )
    data, etag = result  # type: ignore[misc]

    if data is None:
        path.touch()
        return path

    mirror.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if etag:
        # Losing the ETag only costs a revalidation next time.
        with contextlib.suppress(OSError):
            etag_path.write_text(etag, encoding="utf-8")
    return path


def load_index(mirror: Path, offline_only: bool = False) -> dict[int, Record]:
    path = index_path(mirror)
    if not offline_only:
        path = ensure_index(mirror)
    if not path.exists():
        raise RFCError(
            f"no RFC index at {path}. Run `{invocation()} status` while online to "
            f"fetch it, or `{invocation()} sync` for the full corpus."
        )
    return parse_index(path.read_text(encoding="utf-8", errors="replace"))


def read_document(mirror: Path, number: int) -> str:
    """Read an RFC from the mirror, fetching and caching it if absent.

    Note that this does not consult the index first. An RFC published since the
    last index refresh still fetches perfectly well, and gating retrieval on a
    cached index is how a stale index turns into "no such RFC".
    """
    path = document_path(mirror, number)
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    data = _fetch(RFC_URL.format(number=number))
    if data is None:
        raise RFCError(f"RFC {number} could not be retrieved")
    text = data.decode("utf-8", errors="replace")
    try:
        mirror.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError:
        pass  # A read-only mirror is fine; we just do not get to cache.
    return text


# --------------------------------------------------------------------------
# Document structure
# --------------------------------------------------------------------------


def split_lines(text: str) -> list[str]:
    """Split on newlines only.

    Not str.splitlines(): it also breaks on form feeds, which paginated RFCs use
    by the hundred. Line numbers computed that way disagree with the file itself
    and with every other tool the agent might reach for, including the ripgrep
    output from full-text search.
    """
    return text.split("\n")


_HEADING = re.compile(r"^(\d+(?:\.\d+)*)\.?[ \t]+(\S.*)$")
_PAGE_FOOTER = re.compile(r"\[Page \d+\]\s*$")
_RUNNING_HEADER = re.compile(r"^RFC \d+\s+.*\s\d{4}\s*$")


def furniture_mask(lines: list[str]) -> list[bool]:
    """Mark page headers, footers and form feeds.

    Pre-RFC-8650 documents are paginated for print: each page ends with a
    "[Page N]" footer, a form feed, and a running header repeating the RFC
    number and date. None of it is content. Post-8650 documents are generated
    from XML and have none of it, so the mask is simply all False there.

    Returned as a mask rather than a filtered list so that reported line numbers
    always refer to the original file and stay valid across --raw.
    """
    mask = [False] * len(lines)
    for i, line in enumerate(lines):
        if "\f" in line or _PAGE_FOOTER.search(line) or _RUNNING_HEADER.match(line):
            mask[i] = True
    return mask


def find_sections(lines: list[str]) -> list[dict]:
    """Numbered headings with their 1-based line numbers.

    Headings sit at column 0 in every RFC generation; the table of contents is
    indented, which is what keeps it out of the results.
    """
    mask = furniture_mask(lines)
    sections = []
    for i, line in enumerate(lines):
        if mask[i]:
            continue
        match = _HEADING.match(line)
        if not match:
            continue
        number = match.group(1)
        sections.append(
            {
                "section": number,
                "title": match.group(2).strip(),
                "line": i + 1,
                "depth": number.count(".") + 1,
            }
        )
    # How long each section is, so that a caller choosing one can see what it
    # costs before paying for it. Without this the only way to find out a
    # section is 1400 lines is to read 1400 lines.
    for i, section in enumerate(sections):
        section["lines"] = _section_end(sections, i, len(lines)) - section["line"] + 1
    return sections


def _section_end(sections: list[dict], index: int, total_lines: int) -> int:
    """Last line of sections[index]: a section runs until the next heading at
    the same or a shallower depth, so section 6 includes 6.1 but stops at 7."""
    depth = sections[index]["depth"]
    for section in sections[index + 1 :]:
        if section["depth"] <= depth:
            return section["line"] - 1
    return total_lines


def section_range(sections: list[dict], wanted: str, total_lines: int) -> tuple[int, int, dict]:
    """Resolve a section selector to a 1-based inclusive line range.

    A section runs until the next heading at the same or a shallower depth, so
    asking for section 6 includes 6.1 and 6.2 but stops at section 7.
    """
    target = wanted.strip().rstrip(".")
    index = None
    for i, section in enumerate(sections):
        if section["section"] == target:
            index = i
            break
    if index is None:
        lowered = target.lower()
        for i, section in enumerate(sections):
            if lowered in section["title"].lower():
                index = i
                break
    if index is None:
        raise RFCError(f"no section {wanted!r}; run `sections` to list them")

    return sections[index]["line"], _section_end(sections, index, total_lines), sections[index]


def check_whole_document(
    number: int, total_lines: int, *, list_hint: str, override_hint: str
) -> None:
    """Refuse an unscoped read of a long RFC, naming the way to scope it.

    Only for reads with no section and no line range. Anything explicitly
    scoped is the caller saying what they want, and a large section they asked
    for by name is not the failure mode this exists to catch.
    """
    if total_lines <= WHOLE_DOCUMENT_LINE_LIMIT:
        return
    raise RFCError(
        f"RFC {number} is {total_lines} lines — reading it whole would spend the "
        f"context on a specification you have one question about. Run "
        f"`{list_hint}` to find the section that answers it, then read that. "
        f"{override_hint} overrides this if you genuinely need the entire text."
    )


def slice_lines(lines: list[str], start: int, end: int, raw: bool) -> str:
    """Extract 1-based inclusive lines, dropping page furniture unless raw."""
    start = max(1, start)
    end = min(len(lines), end)
    if start > end:
        return ""
    chunk = lines[start - 1 : end]
    if raw:
        return "\n".join(chunk)
    mask = furniture_mask(lines)[start - 1 : end]
    kept = [line for line, is_furniture in zip(chunk, mask, strict=True) if not is_furniture]
    return _collapse_blank_runs(kept)


def _collapse_blank_runs(lines: list[str]) -> str:
    out: list[str] = []
    blanks = 0
    for line in lines:
        if line.strip():
            blanks = 0
            out.append(line)
        else:
            blanks += 1
            if blanks <= 1:
                out.append("")
    return "\n".join(out).strip("\n")


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------


def search_titles(
    records: dict[int, Record], query: str, limit: int, use_regex: bool = False
) -> tuple[list[Record], int]:
    """Return one page of matches and how many matched in total.

    The total is not decoration. A caller that only sees the page reports the
    page size as the answer — "20 RFCs mention stateless" when 795 do — which
    is the same failure as falling back to a title search: a confident answer
    to a question nobody asked.
    """
    if use_regex:
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error as exc:
            raise RFCError(f"bad regular expression: {exc}") from exc

        def matches(title: str) -> bool:
            return pattern.search(title) is not None
    else:
        terms = [t.lower() for t in query.split() if t]

        def matches(title: str) -> bool:
            lowered = title.lower()
            return all(term in lowered for term in terms)

    hits = [r for _, r in sorted(records.items()) if not r.not_issued and matches(r.title)]
    return hits[:limit], len(hits)


def _search_tool() -> tuple[str, bool]:
    """Pick a full-text search backend: ripgrep if present, else grep."""
    if shutil.which("rg"):
        return "rg", True
    if shutil.which("grep"):
        return "grep", False
    raise RFCError("full-text search needs `rg` or `grep` on PATH; neither was found")


def search_fulltext(
    mirror: Path, query: str, limit: int, max_lines_per_doc: int = 3
) -> tuple[list[dict], str, int]:
    """Rank documents by hit count, then pull a few matching lines from each.

    Two passes so that ranking reflects real hit counts: capping matches per
    file in a single pass would flatten every document to the same score.

    Returns the page, the backend that produced it, and the total number of
    matching documents — see search_titles on why the total is not optional.
    """
    tool, is_rg = _search_tool()
    if is_rg:
        count_cmd = [
            "rg",
            "--count-matches",
            "--no-messages",
            "-i",
            "-e",
            query,
            "--glob",
            "rfc*.txt",
            str(mirror),
        ]
    else:
        count_cmd = ["grep", "-rciE", "--include=rfc*.txt", "--", query, str(mirror)]

    counts: list[tuple[int, int]] = []
    for line in _run_search(count_cmd):
        path, _, count = line.rpartition(":")
        number = _number_from_path(path)
        if number is None:
            continue
        try:
            hits = int(count)
        except ValueError:
            continue
        if hits:
            counts.append((hits, number))
    counts.sort(key=lambda pair: (-pair[0], pair[1]))

    results = []
    for hits, number in counts[:limit]:
        path = document_path(mirror, number)
        # --no-filename / -h keep the output shape at "line:text" for both tools.
        if is_rg:
            line_cmd = [
                "rg",
                "--line-number",
                "--no-filename",
                "--no-heading",
                "--no-messages",
                "--color",
                "never",
                "--max-count",
                str(max_lines_per_doc),
                "-i",
                "-e",
                query,
                str(path),
            ]
        else:
            line_cmd = ["grep", "-nhiE", "-m", str(max_lines_per_doc), "--", query, str(path)]
        matches = []
        for line in _run_search(line_cmd):
            lineno, _, body = line.partition(":")
            if not lineno.isdigit():
                continue
            matches.append({"line": int(lineno), "text": body.strip()})
        results.append({"number": number, "hits": hits, "matches": matches})
    return results, tool, len(counts)


def _run_search(cmd: list[str]) -> list[str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise RFCError(f"could not run {cmd[0]}: {exc}") from exc
    # Exit status 1 means "no matches" for both rg and grep; only 2+ is an error.
    if proc.returncode >= 2:
        message = proc.stderr.strip() or f"{cmd[0]} exited {proc.returncode}"
        raise RFCError(f"search failed: {message}")
    return [line for line in proc.stdout.splitlines() if line]


def _number_from_path(path: str) -> int | None:
    match = re.search(r"rfc(\d+)\.txt$", path)
    return int(match.group(1)) if match else None


# --------------------------------------------------------------------------
# Sync
# --------------------------------------------------------------------------


def sync_command(mirror: Path, bwlimit: str, dry_run: bool = False) -> list[str]:
    """Build the rsync invocation. --delete is not optional.

    Without --delete, documents removed upstream linger while the index no
    longer lists them, and the two views of the corpus drift apart.
    """
    cmd = [
        "rsync",
        "-az",
        "--delete",
        f"--bwlimit={bwlimit}",
        "--include=rfc[0-9]*.txt",
        "--include=rfc-index.txt",
        "--exclude=*",
        RSYNC_MODULE,
        f"{mirror}/",
    ]
    if dry_run:
        cmd.insert(1, "--dry-run")
    return cmd


def run_sync(mirror: Path, bwlimit: str, assume_yes: bool, dry_run: bool) -> int:
    if not shutil.which("rsync"):
        raise RFCError("`rsync` is not on PATH; install it and try again")
    cmd = sync_command(mirror, bwlimit, dry_run)
    print(f"About to sync the RFC text corpus into {mirror}")
    print("  roughly 9,800 documents, 512 MB, a few minutes")
    print(f"  source: {RSYNC_MODULE} (volunteer-operated; bandwidth limited to {bwlimit})")
    print(f"  {' '.join(cmd)}")
    if not assume_yes and not dry_run:
        if not sys.stdin.isatty():
            raise RFCError("refusing to sync non-interactively without --yes")
        answer = input("Proceed? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Cancelled.")
            return 1
    mirror.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(cmd, check=False)
    if result.returncode == 0 and not dry_run:
        (mirror / SYNC_STAMP).write_text(f"synced {formatdate(usegmt=True)}\n", encoding="utf-8")
        print(f"\nDone. {count_documents(mirror)} documents in {mirror}")
    return result.returncode


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def parse_number(text: str) -> int:
    match = re.fullmatch(r"(?:rfc\s*)?0*(\d+)", text.strip(), re.IGNORECASE)
    if not match:
        raise RFCError(f"not an RFC number: {text!r}")
    return int(match.group(1))


def _emit(payload: dict, human: str, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(human)


def _describe_age(seconds: float) -> str:
    if seconds < 86400:
        hours = round(seconds / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} old"
    days = round(seconds / 86400)
    return f"{days} day{'s' if days != 1 else ''} old"


def cmd_status(args: argparse.Namespace) -> int:
    mirror = resolve_mirror(args.mirror)
    populated = is_populated(mirror)
    docs = count_documents(mirror)
    path = index_path(mirror)

    index_info: dict = {"present": path.exists(), "path": str(path)}
    lines = [
        f"mode: {'offline' if populated else 'online'}"
        f" ({'full-text search available' if populated else 'title search only'})",
        f"mirror: {mirror} ({docs} document{'s' if docs != 1 else ''})",
    ]
    if path.exists():
        age = time.time() - path.stat().st_mtime
        index_info["age_seconds"] = int(age)
        index_info["stale"] = age > INDEX_TTL_SECONDS
        try:
            entries = len(parse_index(path.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            entries = 0
        index_info["entries"] = entries
        lines.append(f"index: {path} ({entries} entries, {_describe_age(age)})")
    else:
        lines.append(f"index: not present (will be fetched on first use) — {path}")
    if not populated:
        lines.append(
            f"run `{invocation()} sync` for full-text search across the whole corpus (512 MB)"
        )

    payload = {
        "mode": "offline" if populated else "online",
        "fulltext_available": populated,
        "mirror": str(mirror),
        "documents": docs,
        "index": index_info,
    }
    _emit(payload, "\n".join(lines), args.json)
    return 0


def cmd_meta(args: argparse.Namespace) -> int:
    mirror = resolve_mirror(args.mirror)
    number = parse_number(args.number)
    records = load_index(mirror)
    record = records.get(number)
    if record is None:
        raise RFCError(
            f"RFC {number} is not in the index. If it was published very recently, "
            f"`{invocation()} get {number}` may still retrieve it."
        )
    lines = [record.header()]
    if record.authors:
        lines.append(f"Authors: {record.authors}")
    if record.date:
        lines.append(f"Date: {record.date}")
    for label, refs in (
        ("Obsoletes", record.obsoletes),
        ("Updates", record.updates),
    ):
        if refs:
            lines.append(f"{label}: RFC " + ", ".join(str(n) for n in refs))
    if record.also:
        lines.append("Also: " + ", ".join(record.also))
    if record.doi:
        lines.append(f"DOI: {record.doi}")
    _emit(record.to_dict(), "\n".join(lines), args.json)
    return 0


def _truncation_note(shown: int, total: int) -> str:
    """Say so when a page is not the whole answer.

    Silence here reads as completeness: `--limit` defaults to 20, and a reader
    who is not told otherwise will report 20 as the count.
    """
    if total <= shown:
        return ""
    return f"\n\n(showing {shown} of {total} — raise --limit for more)"


def cmd_search(args: argparse.Namespace) -> int:
    mirror = resolve_mirror(args.mirror)
    populated = is_populated(mirror)

    if args.fulltext and not populated:
        raise RFCError(
            "full-text search needs a local mirror, which is not present.\n"
            f"Run `{invocation()} sync` (512 MB, a few minutes) to enable it, or "
            "search titles by dropping --fulltext.\n"
            "Not falling back to title search: it would quietly answer a different "
            "question than the one asked."
        )

    if args.fulltext:
        results, tool, total = search_fulltext(mirror, args.query, args.limit)
        records = load_index(mirror, offline_only=True)
        enriched = []
        human = []
        for result in results:
            record = records.get(result["number"])
            header = record.header() if record else f"RFC {result['number']}"
            enriched.append(
                {**result, "header": header, "record": record.to_dict() if record else None}
            )
            human.append(header)
            for match in result["matches"]:
                human.append(f"   {match['line']}: {match['text']}")
            human.append("")
        payload = {
            "query": args.query,
            "scope": "fulltext",
            "tool": tool,
            "count": len(enriched),
            "total": total,
            "truncated": total > len(enriched),
            "results": enriched,
        }
        text = "\n".join(human).strip() or "no matches"
        text += _truncation_note(len(enriched), total)
        _emit(payload, text, args.json)
        return 0

    records = load_index(mirror)
    hits, total = search_titles(records, args.query, args.limit, args.regex)
    payload = {
        "query": args.query,
        "scope": "title",
        "count": len(hits),
        "total": total,
        "truncated": total > len(hits),
        "results": [r.to_dict() for r in hits],
    }
    if hits:
        human = "\n".join(r.header() for r in hits)
        human += _truncation_note(len(hits), total)
        if not populated:
            human += f"\n\n(titles only — `{invocation()} sync` enables full-text search)"
    else:
        human = "no matches"
    _emit(payload, human, args.json)
    return 0


def cmd_sections(args: argparse.Namespace) -> int:
    mirror = resolve_mirror(args.mirror)
    number = parse_number(args.number)
    lines = split_lines(read_document(mirror, number))
    sections = find_sections(lines)
    header = _header_for(mirror, number)
    human = [header]
    if sections:
        human += [
            f"{'  ' * (s['depth'] - 1)}{s['section']}  {s['title']}  "
            f"(line {s['line']}, {s['lines']} lines)"
            for s in sections
        ]
    else:
        human.append(
            "(no numbered headings found — this RFC is not sectioned in the usual "
            "way; use `get --lines A:B`)"
        )
    payload = {"number": number, "header": header, "total_lines": len(lines), "sections": sections}
    _emit(payload, "\n".join(human), args.json)
    return 0


def _header_for(mirror: Path, number: int) -> str:
    """Best-effort banner.

    Worth fetching the index for if it is missing, because the obsolescence
    warning is the main thing this adds over reading the document directly. But
    a missing index must never block reading: fall back to a bare banner.
    """
    try:
        record = load_index(mirror).get(number)
    except RFCError:
        record = None
    return record.header() if record else f"RFC {number}"


def cmd_get(args: argparse.Namespace) -> int:
    mirror = resolve_mirror(args.mirror)
    number = parse_number(args.number)
    lines = split_lines(read_document(mirror, number))
    header = _header_for(mirror, number)

    section_info = None
    if args.section:
        if args.lines:
            raise RFCError(
                "--section and --lines both choose where to start reading; pass one. "
                "Use --max-lines to cap how much of a section comes back."
            )
        sections = find_sections(lines)
        start, end, section_info = section_range(sections, args.section, len(lines))
    elif args.lines:
        match = re.fullmatch(r"(\d+):(\d+)?", args.lines.strip())
        if not match:
            raise RFCError(f"--lines wants START:END, got {args.lines!r}")
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else len(lines)
    else:
        if not (args.full or args.max_lines):
            check_whole_document(
                number,
                len(lines),
                list_hint=f"{invocation()} sections {number}",
                override_hint="--full",
            )
        start, end = 1, len(lines)

    if args.max_lines:
        end = min(end, start + args.max_lines - 1)

    body = slice_lines(lines, start, end, args.raw)
    payload = {
        "number": number,
        "header": header,
        "section": section_info,
        "start_line": start,
        "end_line": min(end, len(lines)),
        "total_lines": len(lines),
        "content": body,
    }
    _emit(payload, f"{header}\n\n{body}", args.json)
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    mirror = resolve_mirror(args.mirror)
    return run_sync(mirror, args.bwlimit, args.yes, args.dry_run)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=invocation(),
        description=(
            f"Look up IETF RFCs. Works with no setup; `{invocation()} sync` adds full-text search."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--mirror", help=f"corpus directory (default: $RFC_MIRROR or {DEFAULT_MIRROR})"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_read_flags(p: argparse.ArgumentParser) -> None:
        p.add_argument("--json", action="store_true", help="machine-readable output")

    p_status = sub.add_parser("status", help="show mode, mirror and index age")
    add_read_flags(p_status)
    p_status.set_defaults(func=cmd_status)

    p_search = sub.add_parser("search", help="search RFC titles, or full text with --fulltext")
    p_search.add_argument("query")
    p_search.add_argument(
        "--fulltext", action="store_true", help="search document bodies (needs a synced mirror)"
    )
    p_search.add_argument("--regex", action="store_true", help="treat the query as a regex")
    p_search.add_argument("--limit", type=int, default=20)
    add_read_flags(p_search)
    p_search.set_defaults(func=cmd_search)

    p_meta = sub.add_parser("meta", help="title, status, and what obsoletes what")
    p_meta.add_argument("number")
    add_read_flags(p_meta)
    p_meta.set_defaults(func=cmd_meta)

    p_sections = sub.add_parser("sections", help="list headings with line numbers")
    p_sections.add_argument("number")
    add_read_flags(p_sections)
    p_sections.set_defaults(func=cmd_sections)

    p_get = sub.add_parser("get", help="read an RFC, ideally one section at a time")
    p_get.add_argument("number")
    p_get.add_argument("--section", help="section number (e.g. 6.1) or heading text")
    p_get.add_argument("--lines", help="line range START:END, for RFCs without headings")
    p_get.add_argument(
        "--max-lines", type=int, help="cap how many lines come back, from wherever the read starts"
    )
    p_get.add_argument(
        "--full",
        action="store_true",
        help=f"read the whole document even past {WHOLE_DOCUMENT_LINE_LIMIT} lines",
    )
    p_get.add_argument("--raw", action="store_true", help="keep page headers and footers")
    add_read_flags(p_get)
    p_get.set_defaults(func=cmd_get)

    p_sync = sub.add_parser("sync", help="download the corpus for full-text search (512 MB)")
    p_sync.add_argument("--bwlimit", default="2M", help="rsync bandwidth limit (default: 2M)")
    p_sync.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    p_sync.add_argument("--dry-run", action="store_true")
    p_sync.set_defaults(func=cmd_sync)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except RFCError as exc:
        print(f"rfc: {exc}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
