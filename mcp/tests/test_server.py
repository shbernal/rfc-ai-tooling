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
import importlib.util
import json
import logging
import os
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError
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


def _must_not_fetch(*args, **kwargs):
    raise AssertionError("this should have been refused before any network call")


def refusal(tool, *args, **kwargs) -> str:
    """The message a tool refused with. A refusal is raised as ToolError, which
    the SDK sends as is_error=True with the message for the model to read."""
    with pytest.raises(ToolError) as raised:
        tool(*args, **kwargs)
    return str(raised.value)


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
    assert result["header"] == "RFC 4242"
    assert "Body line one" in result["content"]

    listed = server.list_sections(4242)
    assert listed["header"] == "RFC 4242"


# --------------------------------------------------------------------------
# The refusals, at the boundary rather than in the core
# --------------------------------------------------------------------------


def test_fulltext_without_a_mirror_names_what_to_run(isolated_mirror):
    refused = refusal(server.search_rfcs, "congestion", scope="fulltext")
    assert "sync" in refused
    assert "scope='title'" in refused


def test_an_unknown_scope_is_refused(isolated_mirror):
    assert "scope" in refusal(server.search_rfcs, "anything", scope="everything")


def test_a_long_rfc_with_no_section_is_refused(isolated_mirror, monkeypatch):
    """The 0.2.1 regression, asserted where the model actually hits it."""
    body = "\n".join(f"line {n}" for n in range(rfc.WHOLE_DOCUMENT_LINE_LIMIT + 100))
    (isolated_mirror / "rfc9110.txt").write_text(body, encoding="utf-8")
    monkeypatch.setattr(rfc, "_fetch", offline)

    refused = refusal(server.get_rfc, 9110)
    # Named the way this surface is called, not the way the CLI is typed.
    assert "list_sections(9110)" in refused
    assert "full=true" in refused
    assert "--full" not in refused

    # ...and the documented ways through it work.
    server.get_rfc(9110, full=True)
    server.get_rfc(9110, max_lines=10)


def test_scoping_the_whole_long_rfc_is_refused_too(isolated_mirror, monkeypatch):
    """The guard's two leaks, closed where the model would use them."""
    body = "\n".join(f"line {n}" for n in range(rfc.WHOLE_DOCUMENT_LINE_LIMIT + 100))
    (isolated_mirror / "rfc9110.txt").write_text(body, encoding="utf-8")
    monkeypatch.setattr(rfc, "_fetch", offline)
    assert "full=true" in refusal(server.get_rfc, 9110, start_line=1)
    assert "full=true" in refusal(server.get_rfc, 9110, max_lines=10**9)


@pytest.mark.parametrize(
    ("kwargs", "named"),
    [
        ({"max_lines": -5}, "max_lines"),
        ({"start_line": -50}, "start_line"),
        ({"start_line": 10**9}, "past the end"),
    ],
)
def test_a_line_number_out_of_range_is_an_error_not_an_empty_read(
    isolated_mirror, monkeypatch, kwargs, named
):
    (isolated_mirror / "rfc4242.txt").write_text("1. Intro\nbody\n", encoding="utf-8")
    monkeypatch.setattr(rfc, "_fetch", offline)
    refused = refusal(server.get_rfc, 4242, **kwargs)
    assert named in refused
    assert "--" not in refused


def test_section_and_start_line_together_are_refused(isolated_mirror, monkeypatch):
    (isolated_mirror / "rfc4242.txt").write_text("1. Intro\nbody\n", encoding="utf-8")
    monkeypatch.setattr(rfc, "_fetch", offline)
    refused = refusal(server.get_rfc, 4242, section="1", start_line=2)
    assert "start_line" in refused
    assert "max_lines" in refused
    assert "--" not in refused, "the model has no command line to type flags on"


def test_a_mirror_that_cannot_be_read_is_named_rather_than_crashing(isolated_mirror, monkeypatch):
    """Anything but an anticipated failure reaches the model as a bare "Error
    executing tool", and a full or unreadable disk is anticipated."""

    def unreadable(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(rfc, "read_document", unreadable)
    refused = refusal(server.get_rfc, 4242, section="1")
    assert str(isolated_mirror) in refused
    assert "Permission denied" in refused


# --------------------------------------------------------------------------
# Parity with the CLI
# --------------------------------------------------------------------------
#
# The two surfaces used to assemble their payloads separately and had drifted
# — one carried the search backend's name, the other a bare title where the
# first carried a whole record. `make check-vendor` cannot see that: it holds
# rfc.py identical across its copies, and the adapters are outside it. These
# are that check, at the layer that actually drifted.


def _cli(capsys, argv: list[str]) -> dict:
    assert rfc.main([*argv, "--json"]) == 0
    return json.loads(capsys.readouterr().out)


@pytest.fixture
def sectioned(isolated_mirror, monkeypatch) -> Path:
    (isolated_mirror / "rfc4242.txt").write_text(
        "1. Introduction\nintro prose\n\n2. Body\nbody prose\n", encoding="utf-8"
    )
    (isolated_mirror / "rfc-index.txt").write_text(INDEX_EXCERPT, encoding="utf-8")
    monkeypatch.setattr(rfc, "_fetch", offline)
    return isolated_mirror


def test_get_answers_identically_on_both_surfaces(sectioned, capsys):
    assert server.get_rfc(4242, section="1") == _cli(capsys, ["get", "4242", "--section", "1"])


def test_a_line_range_answers_identically_on_both_surfaces(sectioned, capsys):
    assert server.get_rfc(4242, start_line=2, max_lines=2) == _cli(
        capsys, ["get", "4242", "--lines", "2:", "--max-lines", "2"]
    )


def test_list_sections_answers_identically_on_both_surfaces(sectioned, capsys):
    assert server.list_sections(4242) == _cli(capsys, ["sections", "4242"])


def test_a_title_search_answers_identically_on_both_surfaces(sectioned, capsys):
    query = "hypertext transfer"
    assert server.search_rfcs(query) == _cli(capsys, ["search", query])


# --------------------------------------------------------------------------
# Numbers the model supplies
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [0, -5, "draft-ietf-quic"])
def test_a_number_that_is_not_an_rfc_number_never_reaches_the_network(bad, monkeypatch):
    """These used to become rfc0.txt and rfc-5.txt and come back as a 404 that
    reads like the RFC simply does not exist."""
    monkeypatch.setattr(rfc, "_fetch", _must_not_fetch)
    assert "not an RFC number" in refusal(server.get_rfc, bad)
    assert "not an RFC number" in refusal(server.list_sections, bad)


def test_the_model_may_spell_the_number_the_way_it_has_it(sectioned):
    """It is holding "RFC 4242", and the CLI has always taken that."""
    assert server.list_sections("RFC 4242") == server.list_sections(4242)
    assert server.get_rfc("rfc4242", section="1") == server.get_rfc(4242, section="1")


def test_a_limit_below_one_is_refused(sectioned):
    """The model picks this number, so -1 and 0 arrive from outside."""
    assert "at least 1" in refusal(server.search_rfcs, "hypertext", limit=0)
    assert "at least 1" in refusal(server.search_rfcs, "hypertext", limit=-1)


def test_a_limit_past_the_ceiling_is_refused(sectioned):
    """The same number, from the same place, in the other direction."""
    ceiling = rfc.MAX_SEARCH_LIMIT
    server.search_rfcs("hypertext", limit=ceiling)
    assert f"at most {ceiling}" in refusal(server.search_rfcs, "hypertext", limit=ceiling + 1)


def test_an_empty_query_is_refused(sectioned):
    assert "query is empty" in refusal(server.search_rfcs, "")


def test_regex_reaches_the_model_too(sectioned):
    """The switch is one argument on one payload builder, so it has to be
    offered on both surfaces or it is offered on neither."""
    assert server.search_rfcs(r"HTTP/\d\.\d", regex=True)["total"] == 1
    assert server.search_rfcs(r"HTTP/\d\.\d")["total"] == 0


# --------------------------------------------------------------------------
# smoke.py's copy of the mirror rule
# --------------------------------------------------------------------------


def _load_smoke():
    """smoke.py is not importable as a package: it is a single stdlib-only file
    so that it can be piped into a container that has never held this repo."""
    path = Path(__file__).parents[1] / "smoke.py"
    spec = importlib.util.spec_from_file_location("smoke", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"XDG_DATA_HOME": "/data"},
        {"XDG_DATA_HOME": "relative/path"},
        {"RFC_MIRROR": "/somewhere/else"},
    ],
    ids=["unset", "xdg", "relative-xdg", "explicit"],
)
def test_smoke_resolves_the_mirror_the_way_the_server_does(environment, monkeypatch):
    """smoke.py restates the rule because it cannot import rfc.py, and it went
    a release without being updated. What that costs is not cosmetic: its
    "connecting created no mirror" check compares this path before and after
    the handshake, so a stale rule watches a directory the server never writes
    to and passes without testing anything.
    """
    for name in ("RFC_MIRROR", "XDG_DATA_HOME", "LOCALAPPDATA"):
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    assert _load_smoke().mirror_path() == rfc.resolve_mirror()


# --------------------------------------------------------------------------
# Configuration from the environment
# --------------------------------------------------------------------------
#
# argparse validates what is typed, not a default, and the environment arrives
# as defaults — so none of these were checked before.


@pytest.mark.parametrize("value", ["sse", "STDIO", "stdio ", "htpp"])
def test_an_unknown_transport_is_refused_rather_than_served_over_http(value, monkeypatch, capsys):
    """Anything that was not exactly `stdio` used to start a listener, and the
    image sets HOST=0.0.0.0, so a typo bound an unauthenticated server to every
    interface."""
    monkeypatch.setenv("RFC_TRANSPORT", value)
    monkeypatch.setattr(server.server, "run", _must_not_fetch)
    monkeypatch.setattr(server.sys, "argv", ["mcp-server-rfc"])
    with pytest.raises(SystemExit) as raised:
        server.main()
    assert raised.value.code == 2
    assert "RFC_TRANSPORT" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["stdio", "http"])
def test_a_valid_transport_from_the_environment_is_used(value, monkeypatch):
    monkeypatch.setenv("RFC_TRANSPORT", value)
    assert server.build_parser().parse_args([]).transport == value


def test_a_port_that_is_not_a_number_names_the_variable(monkeypatch, capsys):
    monkeypatch.setenv("PORT", "http")
    with pytest.raises(SystemExit) as raised:
        server.build_parser()
    assert raised.value.code == 2
    assert "PORT='http'" in capsys.readouterr().err


def test_a_port_from_the_environment_is_an_int(monkeypatch):
    monkeypatch.setenv("PORT", "8080")
    assert server.build_parser().parse_args([]).port == 8080


def test_an_unknown_log_level_is_ignored_with_a_warning(monkeypatch, caplog):
    """This runs at import, before the process can answer anything, so raising
    here is a server that spawns and dies with only a traceback to show for it."""
    monkeypatch.setenv("RFC_LOG_LEVEL", "verbose")
    with caplog.at_level(logging.WARNING, logger="mcp-server-rfc"):
        importlib.reload(server)
    assert "RFC_LOG_LEVEL='verbose'" in caplog.text


# --------------------------------------------------------------------------
# The entry point
# --------------------------------------------------------------------------


@pytest.fixture
def launched(monkeypatch):
    """Run main() with a recorder where the transport would start."""
    for name in ("RFC_TRANSPORT", "HOST", "PORT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(server, "_over_http", False)
    calls = []
    monkeypatch.setattr(server.server, "run", lambda *a, **kw: calls.append((a, kw)))

    def launch(*argv):
        monkeypatch.setattr(server.sys, "argv", ["mcp-server-rfc", *argv])
        server.main()
        return calls

    return launch


def test_stdio_is_the_default(launched):
    assert launched() == [(("stdio",), {})]
    assert server._over_http is False


def test_http_serves_statelessly_where_it_was_told(launched):
    calls = launched("--transport", "http", "--host", "0.0.0.0", "--port", "9000")
    assert calls == [
        (("streamable-http",), {"host": "0.0.0.0", "port": 9000, "stateless_http": True})
    ]
    assert server._over_http is True, "the no-mirror refusal has to know it is remote"


def test_http_is_configured_from_the_environment(launched, monkeypatch):
    """The platforms this mode is for set configuration that way."""
    monkeypatch.setenv("RFC_TRANSPORT", "http")
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "8080")
    ((_, kwargs),) = launched()
    assert (kwargs["host"], kwargs["port"]) == ("0.0.0.0", 8080)


def test_a_flag_overrides_the_environment(launched, monkeypatch):
    monkeypatch.setenv("RFC_TRANSPORT", "http")
    assert launched("--transport", "stdio") == [(("stdio",), {})]


def test_a_subcommand_runs_the_cli_instead_of_the_server(launched, monkeypatch):
    """Every refusal the server hands the model names `uvx mcp-server-rfc sync`,
    so that has to sync rather than start a server that ignores the word."""
    ran = []
    monkeypatch.setattr(rfc, "main", lambda argv: ran.append(argv) or 0)
    with pytest.raises(SystemExit) as raised:
        launched("sync", "--dry-run")
    assert raised.value.code == 0
    assert ran == [["sync", "--dry-run"]]
