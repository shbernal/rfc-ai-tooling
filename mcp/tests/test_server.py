"""Tests for the MCP adapter itself.

core/test_rfc.py covers the implementation; this covers the boundary the model
actually calls. The distinction matters because the two have different failure
modes: the core is a library called once per process by the CLI, while the
server is long-lived and calls it repeatedly, so anything the adapter holds
between calls is state the core's tests cannot see.

No network. The tools are plain functions — the @server.tool decorator returns
them unchanged — so they are called directly.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest
from mcp_server_rfc import rfc, server

FIXTURES = Path(__file__).parents[2] / "core" / "fixtures"
INDEX_EXCERPT = (FIXTURES / "rfc-index-excerpt.txt").read_text(encoding="utf-8")


def test_the_packaged_version_is_the_one_the_server_reports():
    """Two files declare a version and nothing else makes them agree.

    The publish workflow checks the tag against mcp/pyproject.toml, so that
    half cannot drift silently. Nothing checks it against core/rfc.py, which is
    what serverInfo reports and what `--version` prints — so a bump that missed
    one would upload a wheel whose server announces the previous release.
    """
    manifest = (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    packaged = next(
        line.split('"')[1] for line in manifest.splitlines() if line.startswith("version = ")
    )
    assert rfc.__version__ == packaged


@pytest.fixture(autouse=True)
def isolated_mirror(tmp_path, monkeypatch):
    """Point every tool at an empty mirror and drop the core's parse cache.

    The cache is keyed on (path, mtime, size), so distinct tmp_paths cannot
    collide — but a test that rewrites its own index depends on the key
    changing, and clearing here keeps that independent of clock resolution.
    """
    monkeypatch.setenv("RFC_MIRROR", str(tmp_path))
    monkeypatch.setattr(rfc, "_index_cache", None)
    return tmp_path


def offline(*args, **kwargs):
    raise rfc.RFCError("network error fetching ...: [Errno -3] no name resolution")


def stale(path):
    """Age a file past the index TTL so the next load attempts a refresh."""
    when = rfc.time.time() - rfc.INDEX_TTL_SECONDS - 1
    os.utime(path, (when, when))


# --------------------------------------------------------------------------
# The index is not loaded until a tool asks for it
# --------------------------------------------------------------------------


def test_importing_the_server_touches_no_mirror(tmp_path, monkeypatch):
    """A client that connects and asks nothing must not download or parse 2 MB.

    smoke.py asserts this over the wire against the published wheel; asserting
    it here is what makes a regression fail before the release rather than
    after it.
    """
    monkeypatch.setattr(rfc, "_fetch", offline)
    fresh = tmp_path / "untouched"
    monkeypatch.setenv("RFC_MIRROR", str(fresh))
    importlib.reload(server)
    assert not fresh.exists()


# --------------------------------------------------------------------------
# Offline fallback, and the cache that used to defeat it
# --------------------------------------------------------------------------


def test_an_unreachable_refresh_still_answers_from_disk(isolated_mirror, monkeypatch):
    index = isolated_mirror / "rfc-index.txt"
    index.write_text(INDEX_EXCERPT, encoding="utf-8")
    stale(index)
    monkeypatch.setattr(rfc, "_fetch", offline)

    result = server.search_rfcs("hypertext transfer", scope="title")
    assert "error" not in result
    assert any(r["number"] == 2616 for r in result["results"])


def test_a_refresh_that_failed_once_is_retried_on_the_next_call(isolated_mirror, monkeypatch):
    """The regression this release exists for.

    The server used to hold the parsed index in a module global for the life of
    the process. A first call made during an outage fell back to the copy on
    disk — correctly — and then served that copy forever, because nothing ever
    looked again. ensure_index leaves the mtime alone on failure precisely so
    the next call retries; a process-lifetime cache is what made "next call"
    mean never.
    """
    index = isolated_mirror / "rfc-index.txt"
    index.write_text(INDEX_EXCERPT, encoding="utf-8")
    stale(index)

    monkeypatch.setattr(rfc, "_fetch", offline)
    first = server.search_rfcs("stateless application", scope="title")
    assert first["total"] == 0  # the outage copy does not have it

    # Network comes back and the index now carries an RFC the old one lacked.
    published = INDEX_EXCERPT + (
        "\n9999 A Stateless Application Protocol. S. Bernal. August 2026. "
        "(Status: PROPOSED STANDARD) (DOI: 10.17487/RFC9999)\n"
    )
    monkeypatch.setattr(rfc, "_fetch", lambda url, **kw: (published.encode("utf-8"), 'W/"new"'))

    second = server.search_rfcs("stateless application", scope="title")
    assert second["total"] == 1
    assert second["results"][0]["number"] == 9999


def test_an_unchanged_index_is_parsed_once(isolated_mirror, monkeypatch):
    """The cache still has to earn its keep: repeated calls must not re-parse."""
    index = isolated_mirror / "rfc-index.txt"
    index.write_text(INDEX_EXCERPT, encoding="utf-8")
    monkeypatch.setattr(rfc, "_fetch", offline)  # fresh index: never consulted

    parses = []
    real_parse = rfc.parse_index
    monkeypatch.setattr(rfc, "parse_index", lambda text: (parses.append(1), real_parse(text))[1])

    for _ in range(3):
        server.search_rfcs("hypertext", scope="title")
    assert len(parses) == 1


# --------------------------------------------------------------------------
# A missing index must not block reading a document
# --------------------------------------------------------------------------


def test_a_document_is_readable_with_no_index_at_all(isolated_mirror, monkeypatch):
    """Retrieval does not depend on the index, and neither does the tool.

    An index that cannot be fetched costs the obsolescence banner. It must not
    cost the document, which fetches perfectly well on its own.
    """
    (isolated_mirror / "rfc4242.txt").write_text("Body line one\nBody line two\n", encoding="utf-8")
    monkeypatch.setattr(rfc, "_fetch", offline)

    result = server.get_rfc(4242, max_lines=2)
    assert "error" not in result
    assert result["header"] == "RFC 4242"
    assert "Body line one" in result["content"]

    listed = server.list_sections(4242)
    assert "error" not in listed
    assert listed["header"] == "RFC 4242"


# --------------------------------------------------------------------------
# The refusals, at the boundary rather than in the core
# --------------------------------------------------------------------------


def test_fulltext_without_a_mirror_names_what_to_run(isolated_mirror):
    result = server.search_rfcs("congestion", scope="fulltext")
    assert "sync" in result["error"]
    assert "scope='title'" in result["error"]


def test_an_unknown_scope_is_refused(isolated_mirror):
    assert "error" in server.search_rfcs("anything", scope="everything")


def test_a_long_rfc_with_no_section_is_refused(isolated_mirror, monkeypatch):
    """The 0.2.1 regression, asserted where the model actually hits it."""
    body = "\n".join(f"line {n}" for n in range(rfc.WHOLE_DOCUMENT_LINE_LIMIT + 100))
    (isolated_mirror / "rfc9110.txt").write_text(body, encoding="utf-8")
    monkeypatch.setattr(rfc, "_fetch", offline)

    refused = server.get_rfc(9110)
    assert "error" in refused
    assert "list_sections(9110)" in refused["error"]

    # ...and the documented ways through it work.
    assert "error" not in server.get_rfc(9110, full=True)
    assert "error" not in server.get_rfc(9110, max_lines=10)


def test_section_and_start_line_together_are_refused(isolated_mirror, monkeypatch):
    (isolated_mirror / "rfc4242.txt").write_text("1. Intro\nbody\n", encoding="utf-8")
    monkeypatch.setattr(rfc, "_fetch", offline)
    result = server.get_rfc(4242, section="1", start_line=2)
    assert "error" in result
