"""Tests for the RFC core.

No network in the default run. The two synthetic document fixtures reproduce
the structure of each RFC generation — paginated (pre-8650) and XML-generated
(post-8650) — without carrying RFC prose. A live check against one real
document of each generation is marked `network` and excluded from CI.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import rfc  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
INDEX_EXCERPT = (FIXTURES / "rfc-index-excerpt.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def records() -> dict[int, rfc.Record]:
    return rfc.parse_index(INDEX_EXCERPT)


# --------------------------------------------------------------------------
# Index parsing
# --------------------------------------------------------------------------


def test_title_is_not_truncated_at_the_first_period(records):
    """RFC 2616 is the canonical victim of splitting a title on '.'."""
    assert records[2616].title == "Hypertext Transfer Protocol -- HTTP/1.1"


def test_rfcs_below_one_thousand_are_indexed(records):
    """The index is not zero-padded; assuming four digits loses 999 RFCs."""
    assert 791 in records
    assert records[791].title == "Internet Protocol"


def test_five_digit_numbers_are_indexed(records):
    assert 10026 in records
    assert records[10026].title.startswith("Operational Recommendations for DNSSEC")


def test_not_issued_entries_are_flagged(records):
    assert records[14].not_issued is True
    assert records[14].title == "Not Issued"


def test_multiline_entries_keep_their_metadata(records):
    record = records[2616]
    assert record.obsoletes == [2068]
    assert record.obsoleted_by == [7230, 7231, 7232, 7233, 7234, 7235]
    assert record.updated_by == [2817, 5785, 6266, 6585]
    assert record.status == "DRAFT STANDARD"
    assert record.doi == "10.17487/RFC2616"
    assert record.date == "June 1999"
    assert record.authors.startswith("R. Fielding, J. Gettys")


def test_parenthesised_abbreviation_in_a_title_is_not_read_as_metadata(records):
    """RFC 4304's title contains a bare '(DOI)'."""
    record = records[4304]
    assert record.title.endswith("Key Management Protocol (ISAKMP)")
    assert record.date == "December 2005"
    assert record.authors == "S. Kent."


def test_title_containing_initials_is_not_split_early(records):
    assert records[1108].title == (
        "U.S. Department of Defense Security Options for the Internet Protocol"
    )


def test_lowercase_surname_particle_does_not_confuse_the_author_boundary(records):
    record = records[9307]
    assert record.title.endswith("(AID) 2021")
    assert record.authors.startswith("N. ten Oever")


def test_corporate_authorship_without_initials(records):
    record = records[1014]
    assert record.title == "XDR: External Data Representation standard"
    assert record.authors == "Sun Microsystems."


def test_also_field_is_captured(records):
    assert records[791].also == ["STD5"]


def test_every_parsed_entry_has_a_title(records):
    assert all(r.title for r in records.values())


# --------------------------------------------------------------------------
# The obsolescence banner
# --------------------------------------------------------------------------


def test_header_shouts_about_obsolescence(records):
    header = records[2616].header()
    assert header.startswith("RFC 2616 — Hypertext Transfer Protocol -- HTTP/1.1")
    assert "[DRAFT STANDARD]" in header
    assert "!! OBSOLETED BY: RFC 7230, 7231, 7232, 7233, 7234, 7235" in header


def test_header_omits_the_warning_for_current_documents(records):
    header = records[10026].header()
    assert "OBSOLETED BY" not in header


def test_to_dict_exposes_an_obsolete_flag(records):
    assert records[2616].to_dict()["obsolete"] is True
    assert records[10026].to_dict()["obsolete"] is False


# --------------------------------------------------------------------------
# Document structure
# --------------------------------------------------------------------------


@pytest.fixture(params=["paginated.txt", "modern.txt"])
def document(request) -> list[str]:
    return rfc.split_lines((FIXTURES / request.param).read_text(encoding="utf-8"))


def test_same_heading_rule_handles_both_rfc_generations(document):
    sections = rfc.find_sections(document)
    assert [s["section"] for s in sections] == ["1", "1.1", "2"]
    assert [s["title"] for s in sections] == ["Introduction", "Purpose", "Body"]
    assert [s["depth"] for s in sections] == [1, 2, 1]


def test_reported_line_numbers_index_the_actual_file(document):
    for section in rfc.find_sections(document):
        assert document[section["line"] - 1].startswith(section["section"])


def test_form_feeds_do_not_shift_line_numbers():
    """str.splitlines() breaks on form feeds; paginated RFCs have hundreds."""
    text = (FIXTURES / "paginated.txt").read_text(encoding="utf-8")
    assert "\f" in text
    assert len(rfc.split_lines(text)) < len(text.splitlines())


def test_a_section_ends_at_the_next_heading_of_the_same_depth(document):
    sections = rfc.find_sections(document)
    start, end, info = rfc.section_range(sections, "1", len(document))
    assert info["title"] == "Introduction"
    body = rfc.slice_lines(document, start, end, raw=False)
    assert "Purpose prose" in body, "subsection 1.1 belongs to section 1"
    assert "Body prose" not in body, "section 2 does not"


def test_a_subsection_stops_at_its_own_boundary(document):
    sections = rfc.find_sections(document)
    start, end, _ = rfc.section_range(sections, "1.1", len(document))
    body = rfc.slice_lines(document, start, end, raw=False)
    assert "Purpose prose" in body
    assert "Introductory prose" not in body


def test_sections_can_be_addressed_by_heading_text(document):
    sections = rfc.find_sections(document)
    _, _, info = rfc.section_range(sections, "purpose", len(document))
    assert info["section"] == "1.1"


def test_unknown_section_is_an_error(document):
    sections = rfc.find_sections(document)
    with pytest.raises(rfc.RFCError, match="no section"):
        rfc.section_range(sections, "99.7", len(document))


def test_page_furniture_is_stripped_by_default():
    lines = rfc.split_lines((FIXTURES / "paginated.txt").read_text(encoding="utf-8"))
    body = rfc.slice_lines(lines, 1, len(lines), raw=False)
    assert "[Page 1]" not in body
    assert "\f" not in body
    assert "RFC 9999                A Paginated Example" not in body
    assert "Body prose" in body


def test_raw_keeps_page_furniture():
    lines = rfc.split_lines((FIXTURES / "paginated.txt").read_text(encoding="utf-8"))
    body = rfc.slice_lines(lines, 1, len(lines), raw=True)
    assert "[Page 1]" in body
    assert "\f" in body


def test_modern_documents_have_no_furniture_to_strip():
    lines = rfc.split_lines((FIXTURES / "modern.txt").read_text(encoding="utf-8"))
    assert rfc.furniture_mask(lines) == [False] * len(lines)


def test_documents_without_numbered_headings_yield_no_sections():
    lines = rfc.split_lines("Some prose.\n\n   Indented text that is not a heading.\n")
    assert rfc.find_sections(lines) == []


# --------------------------------------------------------------------------
# Mode detection
# --------------------------------------------------------------------------


def test_empty_mirror_is_online_mode(tmp_path):
    assert rfc.is_populated(tmp_path) is False


def test_index_alone_is_not_a_populated_mirror(tmp_path):
    (tmp_path / "rfc-index.txt").write_text(INDEX_EXCERPT)
    assert rfc.is_populated(tmp_path) is False


def test_a_few_cached_documents_are_not_a_populated_mirror(tmp_path):
    """On-demand fetches accumulate in the mirror; that is not a sync."""
    (tmp_path / "rfc-index.txt").write_text(INDEX_EXCERPT)
    for number in range(1, 20):
        (tmp_path / f"rfc{number}.txt").write_text("x")
    assert rfc.is_populated(tmp_path) is False


def test_sync_stamp_marks_a_populated_mirror(tmp_path):
    (tmp_path / "rfc-index.txt").write_text(INDEX_EXCERPT)
    (tmp_path / rfc.SYNC_STAMP).write_text("synced")
    assert rfc.is_populated(tmp_path) is True


def test_a_full_corpus_is_recognised_without_a_stamp(tmp_path):
    (tmp_path / "rfc-index.txt").write_text(INDEX_EXCERPT)
    for number in range(1, rfc.POPULATED_THRESHOLD + 2):
        (tmp_path / f"rfc{number}.txt").write_text("x")
    assert rfc.is_populated(tmp_path) is True


def test_explicit_mirror_beats_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("RFC_MIRROR", "/from/env")
    assert rfc.resolve_mirror(str(tmp_path)) == tmp_path
    assert rfc.resolve_mirror(None) == Path("/from/env")


def test_default_mirror_is_not_a_cache_directory(monkeypatch):
    """512 MB the user asked for should not sit where cache cleaners roam."""
    monkeypatch.delenv("RFC_MIRROR", raising=False)
    assert ".cache" not in str(rfc.resolve_mirror(None))


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------


def test_title_search_requires_all_terms(records):
    hits, _ = rfc.search_titles(records, "internet protocol", limit=10)
    assert 791 in [r.number for r in hits]
    assert 1014 not in [r.number for r in hits]


def test_title_search_is_case_insensitive(records):
    hits, _ = rfc.search_titles(records, "HYPERTEXT", limit=10)
    assert hits[0].number == 2616


def test_title_search_supports_regex(records):
    hits, _ = rfc.search_titles(records, r"HTTP/\d\.\d", limit=10, use_regex=True)
    assert [r.number for r in hits] == [2616]


def test_bad_regex_is_a_clean_error(records):
    with pytest.raises(rfc.RFCError, match="bad regular expression"):
        rfc.search_titles(records, "(unclosed", limit=10, use_regex=True)


def test_title_search_skips_not_issued_entries(records):
    hits, _ = rfc.search_titles(records, "", limit=100)
    assert all(not r.not_issued for r in hits)


def test_limit_is_honoured(records):
    hits, _ = rfc.search_titles(records, "", limit=2)
    assert len(hits) == 2


def test_a_truncated_page_still_reports_the_real_total(records):
    """The page size is not the answer.

    Reporting len(results) as the count turns "795 RFCs mention stateless"
    into "20 RFCs mention stateless" — a confident answer to a question
    nobody asked, which is the failure the --fulltext refusal exists to avoid.
    """
    everything, total = rfc.search_titles(records, "", limit=1000)
    page, page_total = rfc.search_titles(records, "", limit=2)
    assert total == len(everything)
    assert total > 2, "fixture too small to truncate; the assertion below is vacuous"
    assert len(page) == 2
    assert page_total == total


def test_truncation_is_stated_in_the_human_output(records, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("RFC_MIRROR", str(tmp_path))
    monkeypatch.setattr(rfc, "load_index", lambda *a, **k: records)
    _, total = rfc.search_titles(records, "", limit=1000)

    assert rfc.main(["search", "", "--limit", "2"]) == 0
    assert f"showing 2 of {total}" in capsys.readouterr().out

    assert rfc.main(["search", "", "--limit", "1000"]) == 0
    assert "showing" not in capsys.readouterr().out


def test_fulltext_without_a_mirror_errors_rather_than_degrading(tmp_path, monkeypatch, capsys):
    """Silently answering a different question is worse than refusing."""
    monkeypatch.setenv("RFC_MIRROR", str(tmp_path))
    assert rfc.main(["search", "congestion", "--fulltext"]) == 1
    stderr = capsys.readouterr().err
    assert f"{rfc.invocation()} sync" in stderr
    assert "different question" in stderr


# --------------------------------------------------------------------------
# How to re-run this program
# --------------------------------------------------------------------------


def test_a_host_that_names_its_own_entry_point_is_believed(monkeypatch):
    """`uvx` leaves this importable while its console script is unreachable.

    The module form below is right for a pip install and unrunnable for the
    ephemeral one Claude Desktop spawns, and the two are indistinguishable from
    in here — so a surface that knows how it ships gets to say.
    """
    monkeypatch.setattr(rfc, "__package__", "mcp_server_rfc")
    monkeypatch.setattr(rfc, "CLI_NAME", "uvx mcp-server-rfc")
    assert rfc.invocation() == "uvx mcp-server-rfc"
    assert rfc.build_parser().prog == "uvx mcp-server-rfc"


def test_a_vendored_copy_names_itself_as_a_module(monkeypatch):
    """The MCP package installs no `rfc` script, so `rfc sync` is unrunnable there."""
    monkeypatch.setattr(rfc, "__package__", "mcp_server_rfc")
    assert rfc.invocation() == "python3 -m mcp_server_rfc.rfc"


def test_a_script_run_names_the_path_it_was_run_by(monkeypatch):
    """The skill's copy is reached as `python3 scripts/rfc.py` and nothing else.

    Echoed back as the caller spelled it, relative path included: they ran it
    from somewhere, and that spelling is the one that works if they run it again.
    """
    source = Path(rfc.__file__)
    monkeypatch.setattr(rfc, "__package__", "")
    monkeypatch.chdir(source.parent)
    monkeypatch.setattr(rfc.sys, "argv", [source.name])
    assert rfc.invocation() == f"python3 {source.name}"


def test_the_console_script_keeps_its_bare_name(monkeypatch):
    monkeypatch.setattr(rfc, "__package__", "")
    monkeypatch.setattr(rfc.sys, "argv", ["/usr/local/bin/rfc"])
    assert rfc.invocation() == "rfc"


def test_another_programs_argv_is_not_mistaken_for_this_one(monkeypatch):
    monkeypatch.setattr(rfc, "__package__", "")
    monkeypatch.setattr(rfc.sys, "argv", ["/usr/bin/pytest"])
    assert rfc.invocation() == "rfc"


# --------------------------------------------------------------------------
# The whole-document guard
# --------------------------------------------------------------------------


def test_a_short_rfc_reads_whole_without_complaint():
    rfc.check_whole_document(
        791, rfc.WHOLE_DOCUMENT_LINE_LIMIT, list_hint="ignored", override_hint="ignored"
    )


def test_a_long_rfc_refuses_and_says_how_to_scope_it():
    with pytest.raises(rfc.RFCError) as excinfo:
        rfc.check_whole_document(9110, 6000, list_hint="rfc sections 9110", override_hint="--full")
    message = str(excinfo.value)
    assert "6000 lines" in message
    # A refusal that does not name the way out just moves the problem.
    assert "rfc sections 9110" in message
    assert "--full" in message


def test_a_named_section_is_never_refused_for_its_length(document):
    """Naming a section is the caller scoping their read, however long it turns
    out to be. RFC 2616 section 13 is 1431 lines and is the canonical example of
    reading one section instead of a whole RFC; a guard that refuses it refuses
    the thing the project is for. Length is reported, not enforced."""
    sections = rfc.find_sections(document)
    start, end, _ = rfc.section_range(sections, "1", len(document))
    assert rfc.slice_lines(document, start, end, raw=False)


def test_sections_report_how_long_they_are(document):
    sections = {s["section"]: s for s in rfc.find_sections(document)}
    # Section 1 spans its own heading plus subsection 1.1; 1.1 stops at its own
    # boundary, so the parent is necessarily the longer of the two.
    assert sections["1"]["lines"] > sections["1.1"]["lines"]
    for section in sections.values():
        start, end, _ = rfc.section_range(
            list(sections.values()), section["section"], len(document)
        )
        assert section["lines"] == end - start + 1


@pytest.fixture
def long_document(tmp_path, monkeypatch, records):
    monkeypatch.setenv("RFC_MIRROR", str(tmp_path))
    monkeypatch.setattr(rfc, "load_index", lambda *a, **k: records)
    path = rfc.document_path(tmp_path, 9110)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"line {n}" for n in range(rfc.WHOLE_DOCUMENT_LINE_LIMIT + 500))
    path.write_text(body, encoding="utf-8")
    return path


def test_get_refuses_a_whole_long_document(long_document, capsys):
    assert rfc.main(["get", "9110"]) == 1
    assert "lines" in capsys.readouterr().err


def test_full_overrides_the_guard(long_document, capsys):
    assert rfc.main(["get", "9110", "--full"]) == 0
    assert "line 1900" in capsys.readouterr().out


def test_an_explicitly_scoped_read_is_never_guarded(long_document, capsys):
    """The guard is for unscoped reads; asking for a range is asking for it."""
    assert rfc.main(["get", "9110", "--lines", "10:12"]) == 0
    out = capsys.readouterr().out
    assert "line 10" in out
    assert "line 1900" not in out


# --------------------------------------------------------------------------
# Number parsing
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [("2616", 2616), ("rfc2616", 2616), ("RFC 2616", 2616), ("0791", 791), (" 791 ", 791)],
)
def test_number_forms(text, expected):
    assert rfc.parse_number(text) == expected


@pytest.mark.parametrize("text", ["", "draft-ietf-quic", "26-16", "abc"])
def test_rejects_non_numbers(text):
    with pytest.raises(rfc.RFCError):
        rfc.parse_number(text)


# --------------------------------------------------------------------------
# Sync
# --------------------------------------------------------------------------


def test_sync_always_deletes(tmp_path):
    """Without --delete the index and the documents drift apart."""
    assert "--delete" in rfc.sync_command(tmp_path, "2M")


def test_sync_is_bandwidth_limited_and_text_only(tmp_path):
    cmd = rfc.sync_command(tmp_path, "500K")
    assert "--bwlimit=500K" in cmd
    assert "--include=rfc[0-9]*.txt" in cmd
    assert "--exclude=*" in cmd
    assert cmd[-2] == rfc.RSYNC_MODULE


def test_sync_refuses_to_run_unattended_without_consent(tmp_path, monkeypatch):
    """512 MB from a volunteer mirror is never an implicit action."""
    monkeypatch.setattr(rfc.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(rfc.shutil, "which", lambda name: "/usr/bin/rsync")
    with pytest.raises(rfc.RFCError, match="--yes"):
        rfc.run_sync(tmp_path, "2M", assume_yes=False, dry_run=False)


# --------------------------------------------------------------------------
# Retrieval policy
# --------------------------------------------------------------------------


def test_reading_a_document_does_not_consult_the_index(tmp_path, monkeypatch):
    """A stale index must not make a newly published RFC unreachable."""
    (tmp_path / "rfc-index.txt").write_text(INDEX_EXCERPT)  # 99999 is absent from it

    def fake_fetch(url, **kwargs):
        assert url.endswith("rfc99999.txt")
        return b"Contents of a very new RFC.\n"

    monkeypatch.setattr(rfc, "_fetch", fake_fetch)
    assert "very new RFC" in rfc.read_document(tmp_path, 99999)


def test_a_fetched_document_is_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(rfc, "_fetch", lambda url, **kwargs: b"body\n")
    rfc.read_document(tmp_path, 4242)
    assert (tmp_path / "rfc4242.txt").read_text() == "body\n"


def test_a_cached_document_is_not_refetched(tmp_path, monkeypatch):
    (tmp_path / "rfc4242.txt").write_text("cached\n")

    def explode(*args, **kwargs):
        raise AssertionError("should not hit the network")

    monkeypatch.setattr(rfc, "_fetch", explode)
    assert rfc.read_document(tmp_path, 4242) == "cached\n"


def test_index_is_refetched_once_stale(tmp_path, monkeypatch):
    """A write-once index is how a published RFC becomes 'not found'."""
    path = tmp_path / "rfc-index.txt"
    path.write_text("old")
    import os

    stale = rfc.time.time() - rfc.INDEX_TTL_SECONDS - 1
    os.utime(path, (stale, stale))
    calls = []

    def fake_fetch(url, **kwargs):
        calls.append(url)
        return (b"new", 'W/"abc"')

    monkeypatch.setattr(rfc, "_fetch", fake_fetch)
    rfc.ensure_index(tmp_path)
    assert calls == [rfc.INDEX_URL]
    assert path.read_bytes() == b"new"


def test_fresh_index_is_left_alone(tmp_path, monkeypatch):
    (tmp_path / "rfc-index.txt").write_text("current")

    def explode(*args, **kwargs):
        raise AssertionError("should not hit the network")

    monkeypatch.setattr(rfc, "_fetch", explode)
    rfc.ensure_index(tmp_path)


def test_not_modified_response_just_resets_the_clock(tmp_path, monkeypatch):
    import os

    path = tmp_path / "rfc-index.txt"
    path.write_text("unchanged")
    stale = rfc.time.time() - rfc.INDEX_TTL_SECONDS - 1
    os.utime(path, (stale, stale))
    monkeypatch.setattr(rfc, "_fetch", lambda url, **kwargs: (None, None))
    rfc.ensure_index(tmp_path)
    assert path.read_text() == "unchanged"
    assert rfc.time.time() - path.stat().st_mtime < rfc.INDEX_TTL_SECONDS


def test_an_unreachable_refresh_falls_back_to_the_index_on_disk(tmp_path, monkeypatch):
    """A network blip must not turn a readable index into an error."""
    import os

    path = tmp_path / "rfc-index.txt"
    path.write_text(INDEX_EXCERPT)
    stale = rfc.time.time() - rfc.INDEX_TTL_SECONDS - 1
    os.utime(path, (stale, stale))

    def offline(*args, **kwargs):
        raise rfc.RFCError("network error fetching ...: [Errno -3] no name resolution")

    monkeypatch.setattr(rfc, "_fetch", offline)
    assert rfc.ensure_index(tmp_path) == path
    assert path.read_text() == INDEX_EXCERPT
    # Searching still works, and the obsolescence banner survives.
    assert rfc.load_index(tmp_path)
    assert rfc._header_for(tmp_path, 2616) != "RFC 2616"


def test_a_failed_refresh_does_not_count_as_a_refresh(tmp_path, monkeypatch):
    """Touching on failure would hide the real age and suppress the retry."""
    import os

    path = tmp_path / "rfc-index.txt"
    path.write_text(INDEX_EXCERPT)
    stale = rfc.time.time() - rfc.INDEX_TTL_SECONDS - 1
    os.utime(path, (stale, stale))

    calls = []

    def offline(*args, **kwargs):
        calls.append(1)
        raise rfc.RFCError("network error fetching ...: unreachable")

    monkeypatch.setattr(rfc, "_fetch", offline)
    rfc.ensure_index(tmp_path)
    assert rfc.time.time() - path.stat().st_mtime > rfc.INDEX_TTL_SECONDS
    rfc.ensure_index(tmp_path)
    assert len(calls) == 2


def test_an_unreachable_refresh_with_no_index_still_raises(tmp_path, monkeypatch):
    """With nothing on disk there is no fallback, so the error has to surface."""

    def offline(*args, **kwargs):
        raise rfc.RFCError("network error fetching ...: unreachable")

    monkeypatch.setattr(rfc, "_fetch", offline)
    with pytest.raises(rfc.RFCError):
        rfc.ensure_index(tmp_path)


def test_refresh_cadence_and_the_staleness_warning_are_separate(tmp_path, capsys):
    """Refreshing daily must not make `status` call a two-day-old index stale."""
    import argparse
    import json
    import os

    assert rfc.INDEX_TTL_SECONDS < rfc.INDEX_STALE_SECONDS

    path = tmp_path / "rfc-index.txt"
    path.write_text(INDEX_EXCERPT)
    aged = rfc.time.time() - 2 * rfc.INDEX_TTL_SECONDS
    os.utime(path, (aged, aged))

    rfc.cmd_status(argparse.Namespace(mirror=str(tmp_path), json=True))
    index_info = json.loads(capsys.readouterr().out)["index"]
    assert index_info["age_seconds"] > rfc.INDEX_TTL_SECONDS
    assert index_info["stale"] is False


# --------------------------------------------------------------------------
# Live checks — excluded from CI
# --------------------------------------------------------------------------


@pytest.mark.network
@pytest.mark.parametrize(("number", "first_section"), [(2616, "1"), (9110, "1")])
def test_real_documents_of_both_generations_parse(tmp_path, number, first_section):
    lines = rfc.split_lines(rfc.read_document(tmp_path, number))
    sections = rfc.find_sections(lines)
    assert sections and sections[0]["section"] == first_section
    assert all(lines[s["line"] - 1].startswith(s["section"]) for s in sections)


@pytest.mark.network
def test_the_live_index_still_parses():
    path = rfc.ensure_index(Path.home() / ".cache" / "rfc-ai-tooling-test", force=True)
    parsed = rfc.parse_index(path.read_text(encoding="utf-8", errors="replace"))
    assert len(parsed) > 9000
    assert parsed[2616].title == "Hypertext Transfer Protocol -- HTTP/1.1"
    assert 791 in parsed
