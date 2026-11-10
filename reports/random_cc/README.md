# 200 random real-world PDF pages — no benchmark, 2026-11-07

**Set.** SafeDocs CC-MAIN-2021-31-PDF-UNTRUNCATED (digitalcorpora.org): ~8M PDFs crawled at random by Common Crawl.
`bench/random_cc.py` (seed 7) picked 5 random zip files, 40 random PDFs from each, and one random page from each PDF.
Nothing was chosen by us. What came out: forms, invoices, brochures, Japanese ads and manga, product sheets, slides,
architectural drawings, sheet music, a 1944 Soviet newspaper scan, county minutes, legal decisions, price lists,
in ~20 languages (`manifest.jsonl` lists the sources).

**Run.** c3b (default, margins dropped) on Modal: stages 1–2 on an L40S (757 s wall, 391 s of it loading models),
stage 3 on an H200 (483 s, 211 s loading). About **$1.0** for 200 pages; most of that is model start-up.

## Automatic check against the PDF's own text layer (165 born-digital pages)

`bench/random_eval.py`: word-level, order-free comparison with the text the PDF itself embeds.

| | precision (our words really on the page) | recall (page words we kept) |
|---|---|---|
| **c3b final** | **96.3** | **92.5** |
| stage 1 alone (LightOnOCR-3-0.8B) | 90.5 | 94.7 |

No empty outputs on pages with content, and no repetition loops. The two empty outputs are pages that really are
blank when rendered. Stage 1 alone has lower precision because it writes descriptions of images. The final output
has lower recall because it drops running headers, footers and text inside pictures, by design.

The 25 worst-scoring pages were checked by eye. Most of the low scores are the metric's fault, not ours:
- a worksheet whose text layer is font-encoding gibberish (our reading is perfect);
- maps, floor plans and charts whose labels are in the text layer but sit inside images we skip;
- dropped letterheads;
- CJK text, which this word-level metric splits badly.

## Manual grading (8 scanned or image-only pages, 25 worst digital pages)

| page | verdict |
|---|---|
| sheet music lyrics | correct |
| INPI journal cover (pt) | correct |
| Italian two-column parish letter | correct, full text in order |
| Slovak administrative decision (scan) | correct; one Czech-ism ("správě" for "správe") |
| 1944 Soviet newspaper, poor scan, 4 columns | very good: headings, articles and treaty clauses in order; small misreads ("Громико" for Громыко) |
| Texas county minutes with signatures | correct, including signer names and the amount |
| architectural elevation drawing | **lost the drawing title** "South Elevation – Proposed Garage Studio": stage 2 labelled it `footer`, so it was dropped |
| blank page | empty, correct |

**Real problems found on random documents** (all general, none benchmark-specific):
1. **PDFs whose fonts don't render.** A Hebrew page renders as boxes (missing embedded font), so every reader sees
   tofu and we output junk like `$\text{,}$`. Its text layer is perfect. Same root cause for a stray `□` in a
   Hungarian page. → **Biggest win available: use the PDF's text layer when it is present and sane** (hybrid
   extraction). It also fixes exact characters in CJK (we wrote simplified `压力` for Japanese `圧力`, swapped a
   name `美和子` → `和美子`).
2. **Captions and titles dropped as "footer".** The margin filter trusts the reader's `footer` label even for a
   figure title in the middle-bottom of a drawing. Same family as the dropped 1862 dateline in the olmOCR-Bench
   review (`reports/failure_review/`). → Only drop a footer/header block if it lies in the outer band of the
   page and looks like a running element; or run with `--keep-margins`.
3. Text inside figures (floor-plan room names, map labels, chart axes) is skipped by design. Fine for most uses,
   but should be an option.

## Bottom line

On truly random web PDFs the system is robust: no crashes, no empty or looping outputs, and ~96% word precision /
~93% recall against the documents' own text, with headers and footers removed on purpose. Hand-checked pages read
correctly, including hard scans. The weaknesses are known and general: unrenderable fonts, over-eager header/footer
dropping, and text inside figures.
