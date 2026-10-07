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

## Baselines

The two searches the CLI and the MCP server offer today. Neither accepts a
question as written: title search needs every word in the title, and full-text
search takes one literal string. Both adapters therefore drop question words
and stopwords, then match the remaining terms with OR.

- **`title`** ranks titles by how many query terms they contain, with
  `search_titles`' substring match and tie order (current before obsoleted).
  It works at document level only, and a hit's text is the whole document,
  because an agent holding a number and nothing else has to read that.
- **`rg`** passes the terms to `search_fulltext` as a word-boundary
  alternation. Documents rank by matching-line count, as the CLI ranks them.
  Each of the three lines the CLI quotes per document is mapped to the deepest
  section that contains it.

Test split, 152 items, scored against the model-reviewed gold.

| | system | sec@1 | sec@10 | MRR@10 | doc@1 | doc@10 | sec 8k | doc 8k |
|---|---|---|---|---|---|---|---|---|
| overall | title | 0.03 | 0.06 | 0.04 | 0.11 | 0.24 | 0.03 | 0.08 |
| | rg | 0.00 | 0.00 | 0.00 | 0.05 | 0.28 | 0.00 | 0.10 |
| exact-term | title | 0.00 | 0.00 | 0.00 | 0.07 | 0.10 | 0.00 | 0.03 |
| | rg | 0.00 | 0.00 | 0.00 | 0.10 | 0.52 | 0.00 | 0.21 |
| paraphrase | title | 0.00 | 0.00 | 0.00 | 0.00 | 0.05 | 0.00 | 0.00 |
| | rg | 0.00 | 0.00 | 0.00 | 0.03 | 0.15 | 0.00 | 0.05 |
| obsolescence | title | 0.00 | 0.00 | 0.00 | 0.03 | 0.10 | 0.00 | 0.00 |
| | rg | 0.00 | 0.00 | 0.00 | 0.00 | 0.28 | 0.00 | 0.00 |
| multi-doc | title | 0.00 | 0.00 | 0.00 | 0.15 | 0.44 | 0.00 | 0.15 |
| | rg | 0.00 | 0.00 | 0.00 | 0.11 | 0.30 | 0.00 | 0.22 |
| old-numbering | title | 0.15 | 0.33 | 0.20 | 0.33 | 0.59 | 0.19 | 0.26 |
| | rg | 0.00 | 0.00 | 0.00 | 0.00 | 0.19 | 0.00 | 0.04 |

Current-first on the obsolescence stratum: title 0.10, rg 0.21.

## What the baselines show

- **Neither finds sections.** `rg` scores zero at section level in every
  stratum. Its quoted lines are the first three matches in a document, and in
  a long RFC those sit in the abstract and the table of contents, not in the
  section that answers. Title search's section figures come only from
  old-numbering items whose gold is a whole document.
- **`rg` ranks long documents, not relevant ones.** Ranking by matching-line
  count rewards size. RFC 8881 (NFSv4.1) ranks first for 45 of the 226
  questions, and RFC 5661, the NFSv4.1 text it replaced, is in the top 5 for
  95. It finds the right document in its top 10 for half the exact-term items,
  but rarely at rank 1.
- **Paraphrase is the weakest stratum for both**, as expected for lexical
  matching on questions written to avoid the spec's wording.
- **Obsoleted RFCs do not crowd out current ones.** avoid@5 is low for both
  (0.07 and 0.03). That is mostly because the gold is rarely near the top
  either; current-first stays at 0.21 or below.
- **Most of the text read goes to waste.** At 8k tokens, document-level budget
  recall is about a third of document recall@10. When the right RFC comes
  back, it comes back as more text than the budget allows.
