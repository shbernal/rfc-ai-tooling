---
name: rfc-lookup
description: >
  Look up IETF RFCs and read what a specification actually says. Use whenever an RFC
  number comes up ("RFC 9110", "RFC 2616", "rfc7231"), when checking what a protocol
  spec requires, when quoting normative MUST/SHOULD/MAY language, when asked "what does
  the spec say about X", or when verifying whether an RFC is still current or has been
  obsoleted. Covers HTTP, TCP/IP, DNS, TLS, QUIC, SMTP, OAuth, JSON/JOSE and every other
  IETF standard. Finds the right RFC, reads one section instead of the whole document,
  and flags superseded specifications before they get cited.
---

# RFC lookup

`scripts/rfc.py` reads the IETF RFC corpus. It needs nothing but a Python
interpreter — no install step, no packages.

```bash
python3 scripts/rfc.py <command> [options]
```

It works immediately, fetching documents over HTTPS as needed. If a local mirror
has been synced it reads from disk instead and can search the full text of every
RFC. Same commands either way.

## Check obsolescence before citing anything

This is the rule, not a suggestion. RFCs are superseded constantly and the
best-known number is very often the dead one — RFC 2616 has been obsolete since
2014, and it is still what most people reach for on HTTP.

Every command prints a banner, and a superseded document says so:

```
RFC 2616 — Hypertext Transfer Protocol -- HTTP/1.1  [DRAFT STANDARD]
!! OBSOLETED BY: RFC 7230, 7231, 7232, 7233, 7234, 7235
```

When you see `!! OBSOLETED BY`, go read the replacement and cite that instead.
Mention the supersession to the user rather than quietly substituting. `meta`
shows this without fetching the document:

```bash
python3 scripts/rfc.py meta 2616
```

## Find the right RFC

```bash
python3 scripts/rfc.py search "http semantics"        # all terms must appear in the title
python3 scripts/rfc.py search 'HTTP/\d\.\d' --regex
```

Title search is available always. Searching document bodies requires a synced
mirror:

```bash
python3 scripts/rfc.py search "must-revalidate" --fulltext
```

If there is no mirror, `--fulltext` fails with a message rather than falling back
to titles — a title search silently standing in for a full-text search answers a
different question than the one asked.

Both scopes return at most `--limit` results (default 20). When more matched, the
output ends with `(showing 20 of 795 — raise --limit for more)`, and `--json`
carries `total` and `truncated`. **Report the total, never the number of rows you
were handed** — a truncated page counted as the answer is off by whatever was cut.

`status` says which mode you are in:

```bash
python3 scripts/rfc.py status
```

## Read one section, not the whole document

Fetching an entire RFC is usually the wrong move. The average is 53 KB but the
tail runs past 1.6 MB, and a whole specification in context buys nothing over the
two or three paragraphs that answer the question.

List the headings first, then read the one you need:

```bash
python3 scripts/rfc.py sections 9110
python3 scripts/rfc.py get 9110 --section 9.3.1
python3 scripts/rfc.py get 9110 --section "Idempotent Methods"
```

A section includes its subsections and stops at the next heading of the same
depth. Page headers, footers and form feeds are stripped; pass `--raw` to keep
them.

Some older RFCs — RFC 1060 among them — have no numbered headings at all.
`sections` will say so, and a line range is the fallback:

```bash
python3 scripts/rfc.py get 1060 --lines 200:320
```

Line numbers are the file's real line numbers, so they agree with `sections`,
with `--fulltext` results, and with `rg` or `sed` over the same file.

## Escape hatch

With a synced mirror, the documents are plain text files in `$RFC_MIRROR` (or
`~/.local/share/rfc-ai-tooling`). For anything the CLI does not cover, use
ripgrep directly:

```bash
rg -l 'Retry-After' "$RFC_MIRROR"
```

Add `--json` to any read command when you want to parse the output rather than
read it.

## Full-text mode is opt-in — never sync unprompted

`rfc.py sync` downloads 512 MB from the RFC Editor's volunteer-run rsync mirror
and takes a few minutes.

**Only run it when the user explicitly asks for it.** Do not run it because
`--fulltext` failed, do not run it to "set things up", and do not run it as a
first step. Suggest it, explain the cost, and let the user decide:

```bash
python3 scripts/rfc.py sync            # prompts for confirmation
```

Everything else works without it.
