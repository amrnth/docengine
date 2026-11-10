# olmOCR-Bench failure review — c3b (87.2), 2026-11-07

All 916 failed tests (473 pages) of `results/modal_c3b_olmocr`, sorted into "our error" vs "the test is wrong or asks
for a convention we don't follow". Method:

- **Every** failure went through automatic triage (scripts below).
- **Born-digital pages** (multi-column, tiny text) were judged by the PDF's own embedded text layer, not by us. The
  question per string: does the test's expected string or our output match what is actually printed?
- **Scans and maths** were spot-checked by eye: ~25 rendered pages, ~150 failing strings and formulas read side by
  side. The per-bucket judgements below come from those samples, so treat the "real error" shares as estimates
  (± ~10 points), not exact counts.

Tools: `bench/review_failures.py` (test vs nearest stretch of our output, renders pages to `failures/review/png/`),
`bench/text_arbiter.py` (text-layer referee), `bench/math_triage.py` (LaTeX-synonym normalisation + split detection),
`bench/grid.py` (contact sheets). Raw outputs: `failures/review/*.jsonl`.

## Verdict in one table

| category (failed tests) | test wrong / unfair | convention or notation (ours is a fair reading) | real error by us |
|---|---|---|---|
| arxiv_math (323) | a few (formula not on the page) | ~60%: same maths in other LaTeX, split into pieces, eq. number inside `$$` | ~35–40%: wrong symbol (`\mathcal{E}` for Æ, `\hat` for `\mathring`, υ→v), missing term |
| old_scans_math (57) | — | ~40% | ~60%: hard scans, real misreads |
| multi_column order (143) | **41 test string is wrong** (text layer agrees with us) | ~75: curly quotes, `$d$` for "d", spacing, dropped margin watermark | **4** misreads + ~7 true reading-order flips + ~15 scanned pages |
| old_scans present/order (220) | ~25% GT misread (e.g. "lhagres" for Chagres, "dielinser" for Dickinson) | ~35% punctuation/spelling normalisation of 1800s handwriting ("Washingtn"→"Washington", "allmost"→"almost") | ~40% genuine handwriting misreads + a few dropped lines (dateline) |
| table_tests (113) | a few (map labels as "table", truncated number in GT, slide footer bar as table) | ~40%: value + t-stat stacked in one cell, `$n$` in headers, spacing | ~50%: tables inside figures dropped (20 tests: "no table"), wrong spans |
| headers_footers absent (28) | **~10**: forbidden string also appears legitimately in body text (CERAWEEK, FitForFire, a citation of "PLoS ONE") | ~15: footnotes and letterhead titles kept on purpose | ~3 (a "P.T.O." and a form footer kept) |
| long_tiny_text (26) | 3 | ~10 formatting | ~13 (no text layer; tiny print) |
| baseline (5) | 1 (page holds only a running header, so correct output is empty) | 3 emoji for icons (📧📞🍃) | 1 ("Notes" title dropped) |

**Rough total: of 916 failed tests, ~25–30% are real reading errors, ~55% are notation/convention differences where
our output is a correct reading, and ~15% are wrong or unfair tests.** Read the other way: we lose about 3 points to
real mistakes, about 6 to notation and convention choices, and about 1.5 to bad tests.

## By-eye pass on the "real error" candidates (2026-11-08)

Each case below was looked at on the page: a crop of the region next to the test's string and ours. Tools:
`bench/dropped_text.py`, `bench/boxsheet.py`, `bench/math_crops.py`, `bench/text_crops.py`. Sheets are in
`failures/review/` (not in git).

**1. Text read correctly, then thrown away by our header/footer filter: all 24 cases checked.**
`bench/dropped_text.py` finds every failed string that the final reader *did* read, inside a block that our filter
removed (a reader label or a layout-model margin region).

| verdict | n | cases |
|---|---|---|
| **real mistake: letter dateline dropped** | 4 | "May 22nd, 1914." ×2 (layout `header` region), "Dorchester, Mass., May 22nd., 1914.", "St Louis Jan 13th 1862" |
| **real mistake: letterhead / document title dropped** | 6 | "J. DAY BROWNLEE, JR. Attorney at law…", "Willow Brook Running and Driving Park" (the organisation's name in big type), "FRANK J. DION, PRESIDENT…" ×2, "THE SATURDAY EVENING POST…" price box, "TECHNICAL INVESTIGATION" (page title under a logo) |
| correct drop (running header/footer, download notice) | 9 | journal running heads (×3), "Please cite this article in press as…", Elsevier download notice ×2, "Landtechnik Bd. 38" footer, section kicker "Loi NOTRe…" |
| borderline | 2 | institution line under a logo row on a programme page (×2) |
| text inside a diagram (skipped by design) | 1 | |
| false match (a lone page number) | 2 | |

The pattern: on **letters**, the date line and the printed letterhead sit in the top band, and both the layout model
and the readers call them `header`. They are content. The first 3 or 4 lines of a letter are the most important
metadata on the page: who wrote it, from where, and when.

**2. Tables: checked against our HTML row by row; the figure page checked by eye.**
- Real: **cells that span several rows or columns are written as one filled cell plus empty cells**, not as
  `rowspan`/`colspan`. A category label like "Heterocycles" spanning two rows leaves an empty cell on the second
  row, so the cell→heading link is lost. This is the largest real table issue (~26 tests: every "compared to None"
  failure).
- Real: one figure holding three metric tables next to ROC curves was dropped whole (13 tests, 1 page).
- Not ours: "-.006" when the page prints "-.006**"; "1401" when the page prints "1 401"; a truncated "0.83870967"
  in the test; values and t-statistics stacked in one cell as on the page.

**3. Maths: 28 formulas checked as crops** (18 from the "wrong/missing" bucket, 10 from "close").
- "close" bucket (164 tests): **1 of 10** a real misread. The other nine are correct on the page: `\leqslant` is
  what the page shows, `\cdot` vs `.`, `\left\{` vs `\bigl\{`, `ω|_K`.
- "wrong/missing" bucket (132 tests): **7 of 18** real, all rare glyphs. ẋ read as x on a 1900s scan, Æ→𝓔,
  ♯→#, ϖ→ω̄, υ→v, ■→•, and one arrow with its labels above/below swapped. In **5 of 18** our formula is right and
  the test is wrong: the page prints U − B (minus) but the test wants `\setminus`, and ℙ[B] vs a `\Pr{}` macro.
- **Revised estimate: ~65 of 380 failed maths tests (~17%) are real misreads**, down from the 35–40% guessed above.
- Fixable habit: **equation numbers are written inside the formula** (`… \quad (2.1)` inside `$$`). This happens in
  721 display formulas across our outputs. Writing them as `\tag{2.1}` is the correct LaTeX and would also turn 12
  failed tests into passes.

**4. Old scans: 16 failing lines checked as crops.**
- **The test is wrong in 6:** "held held" (doubled), "Dear Sir," where the page shows "Dear Sir.", "civil war" where
  the page has a capital "War", "then will be" where the page says "there will be", "(Your Excellency)" with
  parentheses on the page, "ofc" where the page says "a/c".
- **Real, spelling normalised (4):** the page says "allmost", "Gurrilla", "Washingtn" and "follwd", and we wrote
  the modern spelling. Fine for search, wrong for archival transcription.
- **Real misreads (3):** "Sturgis/Sturges" as "Storges", "teams" as "team", and a dropped leading "I".
- Undecided (3): the crop missed the line.

## What the real errors are (general weaknesses, not benchmark fixes)

1. **Hard handwriting** (old_scans): genuine misreads — "Lord" vs "God", "State" vs "War Department". The
   reader-cascade already tries the strongest reader; this needs a better model, not a rule.
2. **Rare maths symbols**: Æ, `\mathring`, `\upsilon` read as nearby common symbols. Model limitation.
3. **Tables inside figures are dropped.** A results table drawn inside a figure (e.g. ROC panels with metric tables
   next to them) is lost, because figure blocks are dropped unless the reader wrote an HTML table into them. Fixable
   in general: OCR the table-like part of figures.
4. **Datelines and titles dropped as "header".** In a 1862 letter the first line "St Louis Jan 13th 1862" was
   labelled `header` by both layout model and reader and removed; same for a lone "Notes" page title. Fixable in
   general: only drop a top-of-page block as a running header if it is short and repeats header-like patterns, or
   keep it when it is the first line of body content. Users who want everything already have `--keep-margins`.
5. **Autocorrection of the source**: the model silently fixes misspellings in the document ("Corelation" →
   "Correlation", "allmost" → "almost"). For archival transcription that is wrong; for most users it is harmless.

## What is not worth "fixing"

- LaTeX synonyms (`\notin` vs `\not\in`, `\leqslant` vs `\leq`), splitting `a_0=…, a_1=…` into separate inline
  formulas, `$d$` for an italic variable in prose, curly vs straight quotes. These are correct readings; changing
  them would be tuning to the scorer.
- Footnotes kept on the page, letterheads kept as titles: the benchmark wants them removed, ParseBench and DP-Bench
  reward keeping them. Already an option (`--keep-margins`).
- Tests whose expected string is a typo or not on the page.

## Implication for the SOTA question

The ~1.5 points lost to bad tests are lost by every system, so they don't change the ranking. The ~6 points of
convention mismatch are where systems tuned to olmOCR-Bench's conventions (e.g. per-category post-processing) gain.
The honest headroom from real errors that a general change could address (items 3 and 4) is ~0.5–1 point.
