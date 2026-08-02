"""MCP server exposing the RFC corpus.

Deliberately thin. Everything of substance lives in rfc.py, which is shared
verbatim with the skill; anything that grows here is logic the two surfaces
would eventually disagree about.
"""

from __future__ import annotations

import logging
import os
import sys

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from . import rfc

# stderr, INFO, and payloads never logged. A stdio server's stdout is the
# protocol channel, and a document fetcher that logs what it returns writes the
# corpus to disk a second time — the implementation this replaces had
# accumulated 3.8 MB of log against 1.1 MB of retrieved RFCs.
logging.basicConfig(
    level=os.environ.get("RFC_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler(os.environ["RFC_LOG_FILE"])]
    if os.environ.get("RFC_LOG_FILE")
    else [logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("mcp-server-rfc")

server = MCPServer(
    "rfc",
    version=rfc.__version__,
    instructions=(
        "Look up IETF RFCs. Call list_sections before get_rfc so you read one "
        "section rather than a whole specification. Every response carries a "
        "banner; when it says OBSOLETED BY, read the replacement and cite that "
        "instead."
    ),
)

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)

_index: dict[int, rfc.Record] | None = None


def _mirror():
    return rfc.resolve_mirror()


def _index_records() -> dict[int, rfc.Record]:
    """Load the index on first use and keep it.

    Not loaded at startup: a client that connects and asks nothing should not
    pay for parsing 2 MB.
    """
    global _index
    if _index is None:
        _index = rfc.load_index(_mirror())
    return _index


def _fail(message: str) -> dict:
    return {"error": message}


@server.tool(
    annotations=READ_ONLY,
    description=(
        "Search RFCs. scope='title' matches all query terms against RFC titles and "
        "always works. scope='fulltext' searches the text of every RFC but needs a "
        "local mirror the user has synced; it returns an error explaining what to run "
        "if there is none. Results carry each RFC's status and obsolescence. "
        "'count' is how many results this page holds and 'total' is how many matched; "
        "when 'truncated' is true, report 'total' and raise 'limit' rather than counting "
        "the results you were given."
    ),
)
def search_rfcs(query: str, scope: str = "title", limit: int = 20) -> dict:
    mirror = _mirror()
    if scope not in {"title", "fulltext"}:
        return _fail("scope must be 'title' or 'fulltext'")

    try:
        if scope == "fulltext":
            if not rfc.is_populated(mirror):
                return _fail(
                    "Full-text search needs a local RFC mirror, which is not present. "
                    "The user can create one by running "
                    f"`{rfc.invocation()} sync` in a shell, in the environment this "
                    "server is installed in (512 MB, a few minutes). Searching "
                    "titles instead would answer a "
                    "different question, so this is an error rather than a fallback. "
                    "Retry with scope='title' if a title search is what you want."
                )
            results, _, total = rfc.search_fulltext(mirror, query, limit)
            records = rfc.load_index(mirror, offline_only=True)
            for result in results:
                record = records.get(result["number"])
                result["header"] = record.header() if record else f"RFC {result['number']}"
                result["title"] = record.title if record else ""
            return {
                "query": query,
                "scope": scope,
                "count": len(results),
                "total": total,
                "truncated": total > len(results),
                "results": results,
            }

        hits, total = rfc.search_titles(_index_records(), query, limit)
        return {
            "query": query,
            "scope": scope,
            "count": len(hits),
            "total": total,
            "truncated": total > len(hits),
            "fulltext_available": rfc.is_populated(mirror),
            "results": [r.to_dict() for r in hits],
        }
    except rfc.RFCError as exc:
        return _fail(str(exc))


@server.tool(
    annotations=READ_ONLY,
    description=(
        "List an RFC's numbered headings with their line numbers. Cheap, and the right "
        "first call when you need part of a specification: use it to pick a section, "
        "then pass that section to get_rfc. Some pre-1990 RFCs have no numbered "
        "headings, in which case this returns an empty list and get_rfc's line range "
        "is the way in."
    ),
)
def list_sections(number: int) -> dict:
    mirror = _mirror()
    try:
        lines = rfc.split_lines(rfc.read_document(mirror, number))
        record = _index_records().get(number)
        return {
            "number": number,
            "header": record.header() if record else f"RFC {number}",
            "total_lines": len(lines),
            "sections": rfc.find_sections(lines),
        }
    except rfc.RFCError as exc:
        return _fail(str(exc))


@server.tool(
    annotations=READ_ONLY,
    description=(
        "Read an RFC. Call list_sections first and pass a section — whole RFCs average "
        "53 KB and run past 1.6 MB, and reading one in full is almost never what the "
        "question needs. section accepts a number ('9.3.1') or heading text "
        "('Idempotent Methods') and includes that section's subsections. Asking for a "
        "long RFC with no section and no line range is an error naming its size, not a "
        "silent context-filling dump; pass full=true only when the entire text is "
        "genuinely what you need. start_line and "
        "max_lines are the fallback for RFCs without numbered headings. Page headers "
        "and footers are stripped. The response carries a banner naming the RFC's "
        "status and, if it has been superseded, what replaced it."
    ),
)
def get_rfc(
    number: int,
    section: str | None = None,
    start_line: int | None = None,
    max_lines: int | None = None,
    full: bool = False,
) -> dict:
    mirror = _mirror()
    try:
        lines = rfc.split_lines(rfc.read_document(mirror, number))
        record = _index_records().get(number)
        header = record.header() if record else f"RFC {number}"

        section_info = None
        if section:
            sections = rfc.find_sections(lines)
            start, end, section_info = rfc.section_range(sections, section, len(lines))
        else:
            if not (full or start_line or max_lines):
                rfc.check_whole_document(
                    number,
                    len(lines),
                    list_hint=f"list_sections({number})",
                    override_hint="full=true",
                )
            start = start_line or 1
            end = start + max_lines - 1 if max_lines else len(lines)

        return {
            "number": number,
            "header": header,
            "section": section_info,
            "start_line": start,
            "end_line": min(end, len(lines)),
            "total_lines": len(lines),
            "content": rfc.slice_lines(lines, start, end, raw=False),
        }
    except rfc.RFCError as exc:
        return _fail(str(exc))


def main() -> None:
    logger.info("mcp-server-rfc %s starting on stdio", rfc.__version__)
    server.run("stdio")


if __name__ == "__main__":
    main()
