# Search evaluation

How a change to search is measured, and where search stands today. The
questions and their gold sections are in [`eval/`](../eval/README.md); this file
covers scoring them.

```bash
make eval SYSTEM=rg              # or SYSTEM=title; SPLIT=dev for the dev table
python3 eval/score.py --system rg --split test
```

Scoring needs a synced mirror (`rfc sync`) and no network. It writes
`eval/results/<system>.json`, holding every metric for both splits and each
item's ranks and top ten hits, and prints one split as a markdown table. The
same mirror gives the same file byte for byte.

## Systems

A system is a module in `eval/systems/` with one function:

```python
def retrieve(query: str, k: int) -> list[Hit]   # best first
```

A `Hit` is an RFC number, a section number (`None` if the system only knows the
document) and the text an agent would read for it. The scorer asks for 20 hits.
Duplicate `(rfc, section)` pairs are dropped before scoring, so returning the
same passage twice gains nothing.

## Metrics

Every figure is a share of items, reported per stratum and overall, separately
for `dev` and `test`.

- **Section recall@k** (k = 1, 5, 10): a hit names a gold section exactly,
  `primary` or `acceptable`. A parent or child of the gold section does not
  count unless the item lists it. A gold section of `None` (the whole
  document) is met by any hit on that RFC.
- **Document recall@k**: a hit is on a gold RFC, at any section.
- **MRR@10**, section level: the reciprocal rank of the first gold section,
  zero past rank 10.
- **Budget recall** at 2k and 8k tokens (bytes / 4, as the README's charts
  count): read the hits' text in rank order and stop at the budget. The item
  counts if a gold hit fits whole before the stop. A hit that overflows ends
  the read, as it would for an agent. This is the comparison that keeps
  "system B wins" from meaning "system B returned more text".
- **Current-first** (obsolescence stratum): a gold RFC is in the top 10 and no
  `avoid` RFC ranks above it. **avoid@5**: an `avoid` RFC is in the top 5.
- **Resolution**: the share of returned `(rfc, section)` pairs that name a real
  heading in the core's own parse. Anything under 100% is a bug in the system,
  so `score.py` exits non-zero on it.

## Systems compared

- **`bm25`** is the section index (`rfc search --fulltext` when the index is
  present): SQLite FTS5 over every section's heading and own text, ranked by
  BM25. The question goes in as written; the core drops stopwords and ORs the
  rest. A hit's text is what `rfc get --section` returns for it.
- **`title`** ranks titles by how many query terms they contain, with
  `search_titles`' substring match and tie order (current before obsoleted).
  It works at document level only, and a hit's text is the whole document,
  because an agent holding a number and nothing else has to read that.
- **`rg`** is the mirror fallback: the terms go to `search_fulltext` as a
  word-boundary alternation, documents rank by matching-line count as the CLI
  ranks them, and each of the three lines the CLI quotes per document is mapped
  to the deepest section that contains it.

`title` and `rg` cannot take a question as written either: title search needs
every word in the title, and the mirror search takes one literal string. Their
adapters use the core's own query terms, ORed, so all three systems see the
same words.

Test split, 152 items, model-reviewed gold.

| | system | sec@1 | sec@10 | MRR@10 | doc@1 | doc@10 | sec 8k | doc 8k |
|---|---|---|---|---|---|---|---|---|
| overall | bm25 | 0.27 | 0.55 | 0.35 | 0.36 | 0.64 | 0.50 | 0.61 |
| | title | 0.02 | 0.05 | 0.03 | 0.10 | 0.23 | 0.03 | 0.07 |
| | rg | 0.00 | 0.00 | 0.00 | 0.04 | 0.24 | 0.00 | 0.07 |
| exact-term | bm25 | 0.52 | 0.86 | 0.63 | 0.66 | 0.93 | 0.83 | 0.93 |
| | title | 0.00 | 0.00 | 0.00 | 0.07 | 0.14 | 0.00 | 0.03 |
| | rg | 0.00 | 0.00 | 0.00 | 0.10 | 0.48 | 0.00 | 0.17 |
| paraphrase | bm25 | 0.00 | 0.03 | 0.00 | 0.03 | 0.12 | 0.00 | 0.07 |
| | title | 0.00 | 0.00 | 0.00 | 0.00 | 0.03 | 0.00 | 0.00 |
| | rg | 0.00 | 0.00 | 0.00 | 0.03 | 0.10 | 0.00 | 0.05 |
| obsolescence | bm25 | 0.17 | 0.52 | 0.25 | 0.31 | 0.62 | 0.48 | 0.62 |
| | title | 0.00 | 0.00 | 0.00 | 0.03 | 0.10 | 0.00 | 0.00 |
| | rg | 0.00 | 0.00 | 0.00 | 0.00 | 0.28 | 0.00 | 0.00 |
| multi-doc | bm25 | 0.37 | 0.81 | 0.52 | 0.52 | 0.89 | 0.81 | 0.93 |
| | title | 0.00 | 0.00 | 0.00 | 0.15 | 0.44 | 0.00 | 0.11 |
| | rg | 0.00 | 0.00 | 0.00 | 0.07 | 0.22 | 0.00 | 0.15 |
| old-numbering | bm25 | 0.41 | 0.78 | 0.49 | 0.44 | 0.85 | 0.59 | 0.70 |
| | title | 0.11 | 0.30 | 0.16 | 0.30 | 0.56 | 0.15 | 0.22 |
| | rg | 0.00 | 0.00 | 0.00 | 0.00 | 0.15 | 0.00 | 0.00 |

Obsolescence stratum, current-first: bm25 0.62, rg 0.24, title 0.10. avoid@5
is 0.00 for bm25 and rg, 0.03 for title.

## What the numbers show

- **The index finds sections; nothing before it did.** BM25 puts a gold
  section in the top 10 for 55% of test items, and in the top 1 for 27%. Within
  an 8k-token budget it reaches one for 50%, so most of what it finds is cheap
  enough to read. `rg` finds none at section level: the three lines the CLI
  quotes are the first three matches in a document, which in a long RFC sit in
  the abstract and the table of contents.
- **`rg` ranks long documents, not relevant ones.** Ranking by matching-line
  count rewards size. RFC 8881 (NFSv4.1) ranks first for 76 of the 226
  questions, and RFC 5661, the NFSv4.1 text it replaced, is in the top 5 for
  139. BM25 normalises for section length, which is most of the difference.
- **Paraphrase is unsolved.** All three systems are near zero on questions
  written to avoid the spec's wording, BM25 included (section recall@10 0.03).
  Lexical matching cannot answer them; this is the stratum a dense or hybrid
  retriever has to move.
- **Demoting obsoleted RFCs works, and the dev split overstates it.**
  Current-first is 1.00 on the 14 dev obsolescence items and 0.62 on the 29
  test ones. Without the demotion it was 0.71 to 0.86 on dev, by heading
  weight. The gap is the expected cost of tuning on a small split, which is
  why only test is reported.

## Tuning

On `dev` only (74 items). Columns: section recall@1 and @10, MRR@10, section
recall within 8k tokens, document recall@10, MRR@10 on the paraphrase and
obsolescence strata, current-first, avoid@5.

| heading weight | obsolete weight | sec@1 | sec@10 | MRR | sec 8k | doc@10 | para | obsol | cur-first | avoid@5 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 1.0 | 0.23 | 0.59 | 0.35 | 0.58 | 0.73 | 0.08 | 0.25 | 0.86 | 0.50 |
| 1 | 0.5 | 0.24 | 0.65 | 0.38 | 0.59 | 0.77 | 0.09 | 0.28 | 1.00 | 0.00 |
| 2 | 0.5 | 0.27 | 0.65 | 0.40 | 0.61 | 0.77 | 0.09 | 0.32 | 1.00 | 0.00 |
| 4 | 1.0 | 0.24 | 0.61 | 0.37 | 0.61 | 0.73 | 0.08 | 0.29 | 0.71 | 0.50 |
| 4 | 0.5 | 0.27 | 0.65 | 0.40 | 0.65 | 0.77 | 0.08 | 0.32 | 1.00 | 0.00 |
| **8** | **0.5** | 0.30 | 0.66 | 0.42 | 0.65 | 0.78 | 0.09 | 0.36 | 1.00 | 0.00 |
| 16 | 0.5 | 0.31 | 0.66 | 0.43 | 0.62 | 0.78 | 0.09 | 0.36 | 1.00 | 0.00 |
| 32 | 0.5 | 0.31 | 0.66 | 0.43 | 0.61 | 0.78 | 0.09 | 0.36 | 1.00 | 0.00 |

An obsolete weight of 0.25 scored the same as 0.5 at every heading weight, so
the milder one was kept. Past a heading weight of 8, MRR stops rising and
budget recall starts falling: heading matches win over body matches in
sections too long to read.

- **Tokenizer.** `porter unicode61` (stemmed) against plain `unicode61`, at
  heading weight 8: MRR 0.42 against 0.41, obsolescence 0.36 against 0.41,
  measured before identifiers were split on "_" for the match. Stemming was
  kept for being no worse overall and for matching "cached" to "caching".
- **Storage.** FTS5 storing its own copy of the text made a 793 MB file. The
  index is contentless instead, with the documents zlib-compressed beside it:
  360 MB on disk, about 268 MB gzipped. `detail=column` would cut that to
  252 MB and 180 MB, but on a contentless table FTS5's `bm25()` then scores
  every row 0, so it cannot rank.
- **Build and query cost.** A build over 9,812 documents (260,798 sections)
  takes about 2.5 minutes on a laptop. A query takes 0.4 s at the median and
  under 1 s at the worst over the eval set; reading a document out of the index
  takes about 5 ms.
