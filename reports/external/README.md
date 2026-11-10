# Commercial APIs vs ours: Reducto and Datalab (2026-11-09)

The question: on our own test sets, how does our pipeline compare with two commercial document parsers? We used
Reducto (Parse, model `r-1`) and Datalab (Convert, mode `accurate`). Each service was run twice; ours was run once
per set.

**Short answer**
- **Dense tiny-text pages:** ours scores highest, but **this lead is partly circular** (see the caveat below).
  - Ours 98.8% word recall.
  - Reducto 94–95%.
  - Datalab 83–85%.

  The gap grows on rare words at 3–4 pt: ours 98%, Reducto 49–88%, Datalab 29–60%.

  **Caveat.** All stress pages are born-digital, and their ground truth is the PDF's stored text. Our text-layer step
  corrects words with that same stored text, so part of our lead is copying the answer key.
  - Without the step, our first c3b2 run read rare words at 3–4 pt at 74–91%. That is still at or above Reducto,
    but by much less.
  - Reducto probably uses the stored text too: it reproduces the PDFs' line-break splits word for word.
  - The fair test is an image-only re-run of the stress pages for all systems. It is not done yet.
- **Random web pages:**
  - Ours has the highest precision (96.8 vs 88.6–89.1).
  - Ours has the lowest recall (92.8 vs 94.8–97.6).

  About half of our recall gap to Reducto is page headers and footers, which we drop by design (measured in
  section 2b). Most of the rest is stored-text artefacts that Reducto copies, plus text inside charts and maps.
  Most of the other systems' lost
  precision is image descriptions and alt-text that they add.

## Setup

- **Client:** `bench/external.py`. Each page is sent as a single-page PDF with the service's default output.
  - Datalab: `/api/v1/convert`, markdown, image extraction off.
  - Reducto: `/parse`, `r-1`, tables `dynamic`, chunking off.
  - Neither service gets any benchmark-specific setting.
  - Both drop page headers and footers by default, as we do.
- **Scoring:** the existing local scripts, unchanged. Side-by-side tables come from `bench/external_compare.py`,
  which writes `compare.json`.
  - Dense stress pages: `bench/stress_eval.py`, scored against exact ground truth.
  - Random web pages: `bench/random_eval.py`, word precision and recall against each PDF's own text layer. Only
    born-digital pages are scored, and every system is scored on the same 157 pages: those all runs agree are
    born-digital.
- **Page sets:**
  - `stress`: 54 generated pages, 3–10 pt, 1–3 columns, natural English or random words and numbers
    (`reports/stress/`). The inputs and ground truth are saved here.
  - `web`: 200 random pages from the SafeDocs Common Crawl PDF corpus (`reports/random_cc/`).
- **Our system:**
  - Stress set: c3b2 plus the two bug fixes in section 4 (run `modal_c3b2c_stress`).
  - Web set: c3b2 as committed in `0484c7a` (run `modal_c3b2_rcc`). The fixes do not change any web page; this
    was checked offline.
  - c3b2 includes the text-layer correction, which only applies to born-digital PDFs. All stress pages are
    born-digital. For scans, see the tiling-only numbers in `reports/stress/c3b2.md`.

**Protocol slip, disclosed:** olmOCR-Bench pages were also sent to both services by mistake in the first run: all
1,403 to Reducto and 439 to Datalab. The intent was to use only our own test sets. Those outputs were **not scored**
and are not used anywhere. They sit in `results/ext_*_olmocr/` (not in git).

## 1. Dense, tiny-text pages (54 pages, exact ground truth)

| System | Word recall | Word precision | Character similarity |
|---|---|---|---|
| **Ours** | **98.8** | **98.9** | **99.3** |
| Reducto r-1, run 1 / run 2 | 95.1 / 93.9 | 95.0 / 94.1 | 98.7 / 98.1 |
| Datalab accurate, run 1 / run 2 | 85.0 / 82.9 | 88.3 / 88.0 | 87.9 / 87.4 |

Word recall % by text type and true font size (3 pages per row, 9 for 7–10 pt). Reducto and Datalab show run 1 /
run 2:

| Text | Font | Ours | Reducto | Datalab |
|---|---|---|---|---|
| English | 3 pt | **98.4** | 96.6 / 96.7 | 73.4 / 59.0 |
| English | 3.5 pt | 98.4 | 98.7 / 98.7 | 63.3 / 44.4 |
| English | 4 pt | 99.0 | 99.1 / 98.9 | 94.0 / 93.1 |
| English | 4.5 pt | 98.6 | 99.4 / 99.4 | 98.5 / 98.1 |
| English | 5 pt | 98.0 | 99.6 / 99.6 | 98.7 / 99.3 |
| English | 6 pt | 99.3 | 99.6 / 99.6 | 99.3 / 99.2 |
| English | 7–10 pt | 99.3 | 99.7 / 99.7 | 98.5 / 98.4 |
| Random words + numbers | 3 pt | **97.9** | 70.2 / 48.5 | 36.3 / 29.1 |
| Random words + numbers | 3.5 pt | **98.7** | 79.6 / 79.7 | 36.5 / 50.2 |
| Random words + numbers | 4 pt | **98.2** | 88.1 / 88.4 | 60.1 / 59.9 |
| Random words + numbers | 4.5 pt | **99.6** | 92.5 / 92.6 | 80.1 / 73.1 |
| Random words + numbers | 5 pt | **99.6** | 95.3 / 95.5 | 96.4 / 92.7 |
| Random words + numbers | 6 pt | 96.9 | 97.9 / 98.0 | 98.9 / 98.9 |
| Random words + numbers | 7–10 pt | 99.3 | 98.5 / 98.5 | 99.8 / 99.8 |

On natural English at 3.5–7 pt Reducto is 0.1–1.6 points ahead; ours is ahead at 3 pt.

### What the errors look like

Example: random words at 3 pt, two columns (`random_3pt_2col`), the same 15 words in each output:

| Source | Text |
|---|---|
| Ground truth | centrum stemmer ringmaking **naggingness** hypothecator MR-771 **itching unprovably** proctoplasty **sciurine endearingly ceratoid** undermelody interworry adoral |
| Ours | centrum stemmer ringmaking naggingness hypothecator MR-771 itching unprovably proctoplasty sciurine endearingly ceratoid undermelody interworry adoral |
| Reducto | centrum stemmer ringmaking **nagginess** hypothecator MR-771 **theine unprowly** proctoplasty **scuriure enderending cerated** undermelody interworry adoral |

Datalab's output for this page has a different order, garbled words ("fibshack", "myekold") and an `[illegible]`
marker.

Files: `data/outputs/*/stress/random_3pt_2col.md`. Ground truth: `data/stress_inputs/gt/random_3pt_2col.txt`.

- **Reducto misspells.** Its precision about equals its recall, and its character similarity stays at 0.85–0.96.
  On rare words it reads nearly every letter right but "corrects" the word into a nearby common one.
- **Datalab drops and garbles text on 3–3.5 pt pages.** It writes `[illegible]` for parts it can't read.
- **Both services vary between runs on the hardest pages.** Reducto at 3 pt random: 70.2 vs 48.5. Datalab at 3.5 pt
  English: 63.3 vs 44.4.

## 2. Random web pages (157 born-digital pages common to every run)

| System | Precision | Recall | Pages with recall < 80% | Pages with precision < 90% | Empty outputs (of 200) |
|---|---|---|---|---|---|
| **Ours** | **96.8** | 92.8 | 15 | **10** | 2 (both blank pages) |
| Reducto r-1, run 1 / run 2 | 88.9 / 89.1 | **97.5 / 97.6** | **3 / 3** | 48 / 49 | 0 |
| Datalab accurate, run 1 / run 2 | 88.5 / 88.6 | 94.8 / 94.9 | 7 / 7 | 43 / 41 | 2 |

On individual pages, comparing ours with Reducto run 1 on the lower of precision and recall: Reducto is better by
more than 0.1 on 10 pages, and ours is better by more than 0.1 on 37.

### Our 30 worst pages, by cause

Ten were checked by eye against the rendered page and the rest from word differences against Reducto run 1.

1. **Margin text dropped by design: about half.** These are page headers, footers and side notes. We follow the
   olmOCR-Bench convention and drop them; Reducto keeps them. Examples:
   - letterheads with address and phone (`2652_2652096_p1`, `5332_5332947_p2`);
   - a list of board members in a letter footer (`2652_2652096_p1`);
   - legal disclaimers (`1235_1235120_p1`, `2652_2652648_p2`);
   - registration details (`3234_3234030_p3`);
   - running headers and "revised page" notes (`3234_3234147_p3`, `3234_3234669_p6`);
   - a product price and date in a footer, "CHF 169.00 … 17.07.2020" (`3234_3234160_p2`). This one is real
     content lost.
2. **Defects in the PDF's own text, not in our reading: about a quarter.**
   - A junk custom font encoding (`2652_2652126_p1`).
   - Text stored backwards or rotated (`7764_7764402_p7`).
   - Words split at line breaks in Portuguese and Japanese ("con trol", "aver age"; `5332_5332101_p9`,
     `2652_2652047_p2`, `3234_3234511_p3`). Reducto reproduces these splits exactly, so it very likely copies
     the stored text where one exists. That tilts this metric in its favour.
   - A map whose place labels are part of the image (`3234_3234824_p1`). We read the legend; the labels were not
     expected.
3. **Real reading errors by us.**
   - **Hebrew page with broken embedded fonts** (`5332_5332775_p1`). Both systems fail. Ours also invents a list of
     years, 2022 to 2046.
   - **Tiny half-width katakana names in a sports results table** (`1235_1235628_p6`). We misread several, e.g.
     イヤミユ for イセヤミユウ and モリヒック for オリンピック. Reducto gets them right, probably from the stored text.

**Empty outputs.** Both of our empty pages (`1235_1235564_p9`, `3234_3234422_p1`) are blank. Reducto writes
"Blank white page" for them.

**Where Reducto and Datalab lose precision.** Mostly descriptions they write for images and logos, e.g. "logo
van…", "graues nach unten zeigendes Preisrabatt-Badge…", "INSETA logo blue and orange emblem…". This is not page
text, and a text-only consumer would have to strip it.

**Caveat.** This set is scored against the PDFs' own stored text, not hand-made ground truth. The scores therefore
favour any system that copies that text, and they penalise correct readings where the stored text is broken.

## 2b. Where our missed words are (checking the "headers and footers" claim)

`bench/missed_words.py` places every text-layer word we miss on the page and checks whether our reader read it and
our filters then dropped it. Results are in `missed_words.json`.

- **Pages and words:** the 157 common born-digital pages, 54,820 words.
- **Weighting:** a word missed m of n times counts m/n for each place it occurs.
- **Recall here is pooled over all words,** so it differs from the per-page means in the table above.

| System | Missed words | In header/footer/margin regions | In picture regions | In body regions | Outside any region | Recall, all words | Recall, without margin words |
|---|---|---|---|---|---|---|---|
| Ours | 2,938 | 741 (25%) | 276 (9%) | 1,653 (56%) | 268 (9%) | 94.6 | 95.9 |
| Reducto r-1 (run 1) | 883 | 13 (1%) | 206 (23%) | 578 (65%) | 86 (10%) | 98.4 | 98.4 |
| Datalab accurate (run 1) | 2,035 | 604 (30%) | 84 (4%) | 1,186 (58%) | 161 (8%) | 96.3 | 97.3 |

Region labels come from the layout model alone, which undercounts margins: our reader also labels header and footer
blocks itself. So for ours, each missed word was checked against the reader's own output.

| Our 2,938 missed words | Words | Share |
|---|---|---|
| Read correctly, then dropped as header/footer/margin | 1,158 | 39% |
| Read correctly, then dropped as a picture | 94 | 3% |
| Never read, and Reducto misses them too (PDF text defects, Hebrew, junk encodings) | 676 | 23% |
| Never read, only we miss them | 1,010 | 34% |

The 1,010 words only we miss, by page (checked by word difference; the biggest by eye):

- **210 words: one repeated paragraph we skipped.** On a spam page (`2652_2652551_p1`) the same paragraph is printed
  three times. Our stage-1 reader wrote it twice, while Reducto and Datalab wrote it three times. This is a real
  miss, if a benign one.
- **About 170 words: stored-text artefacts Reducto reproduces.** These are words split at line breaks ("parame
  ters", "dif ficult", "in tervalle", Japanese split mid-word) and glued maths indices ("ai1", "xpi1"). Pages:
  `5332_5332101_p9`, `5332_5332453_p1`, `3234_3234511_p3`, `7764_7764115_p2`, `2652_2652447_p33`,
  `1235_1235809_p11`.
- **About 75 words: labels inside a chart and a map** (`2652_2652071_p1`, `3234_3234824_p1`). Reducto transcribes or
  describes them; we read only the text outside the picture.
- **About 125 words: real misreads.** Tiny half-width katakana (`1235_1235628_p6`) and Hebrew (`7764_7764173_p2`).
- **The remaining ~430 words are spread thin, under 25 per page.** The pages checked (`1235_1235924_p1`,
  `2652_2652050_p1`, `5332_5332759_p1`, `2652_2652447_p33`) are again mostly running headers and footers: journal
  header and DOI, "Powered by TCPDF", "page 33", copyright lines, addresses. The check above did not catch these,
  because the dropped block came from a re-read stage, or was never written out. The rest of this tail is more
  line-break splits.

**Verdict.** The original claim, "our lower recall is mostly headers and footers", was too strong.
- Measured: margin text we read and dropped is **39% of our missed words** and **about 55% of our gap to Reducto**
  (1,145 of 2,055 extra missed words). More running headers sit in the unattributed tail.
- Most of the rest is not misreading. It is either stored-text artefacts that only a system copying the text layer
  "gets right", or text inside pictures.
- Real reading misses in our gap are small: the skipped repeated paragraph, tiny katakana and Hebrew. Together they
  are about 335 words, or 0.6% of all words.

## 2c. Keeping headers and footers (now the default outside olmOCR-Bench)

After section 2b, the default was changed: page headers, footers, page numbers and side notes are kept, and dropped
only for olmOCR-Bench (`--drop-margins`).

To measure the effect without new GPU runs, each web page's final markdown was rebuilt offline from the saved raw
reader output, twice: margins dropped and margins kept.
- The text-layer step was not re-applied to either rebuild.
- Tiled pages (2) were copied unchanged.
- The "dropped" rebuild reproduces the real run to within 0.1, so the rebuild is faithful.

Same 157 pages:

| System | Precision | Recall | Pages with recall < 80% | Pages with precision < 90% |
|---|---|---|---|---|
| Ours, margins dropped (rebuild) | 96.7 | 92.7 | 15 | 10 |
| **Ours, margins kept (rebuild)** | **96.3** | 96.1 | 7 | 12 |
| Reducto r-1 (run 1) | 88.9 | **97.5** | 3 | 48 |
| Datalab accurate (run 1) | 88.5 | 94.8 | 7 | 43 |

Precision fell by more than 0.03 on only three pages, all checked.
- On the worst, `1235_1235692_p1` (0.92 -> 0.54), the added text is a footer address and phone number that is
  printed on the page. It is drawn as an image, so the PDF's stored text lacks it: our reading is correct and the
  metric counts it as wrong.
- On the other two pages, recall rose to 1.00.

What is left of the gap to Reducto (about 1.4 recall points) is, per section 2b, mostly:
- stored-text artefacts Reducto copies;
- text inside charts and maps;
- the skipped repeated paragraph;
- tiny katakana and Hebrew.

## 3. Run-to-run stability

- **Web set:** all three systems are stable. Reducto and Datalab move by 0.2 points or less between runs.
- **Stress set:**
  - Reducto moves by 1.2 points overall and up to 22 points on one bucket.
  - Datalab moves by 2.1 points overall and up to 19 points on one bucket.
  - Ours was run once with the fixes. The c3b2 run before the fixes (`modal_c3b2b_stress`) differed from it only on
    the 4 pages the fixes target.

## 4. Bugs in our pipeline found by this comparison (fixed)

1. **Tiles left gaps on very dense pages** (`docengine/tiles.py`). PP-DocLayoutV3 sometimes returns one large
   container (e.g. `reference`) holding only a few small line boxes. `make_tiles` dropped containers that hold two
   or more regions and kept the small boxes, so the text between them was never read.
   - Example: on `random_3pt_1col`, tiles covered y 106–667, 1074–1583 and 1669–1950, and about 1,000 words were
     lost.
   - Fix: drop a container only when its children cover ≥ 70% of its height; otherwise tile the container itself.
2. **One malformed element in Infinity-Parser2's JSON lost the rest of the page** (`pipeline.infinity_blocks`). The
   model wrote `"text": canter …` (missing opening quote), and parsing stopped there.
   - Fix: salvage the malformed element field by field and continue. A truncated last element is still dropped, as
     before.

Effect on the stress set (rest unchanged):

| Page | Before | After |
|---|---|---|
| `random_3pt_1col` | 0.72 | 0.97 |
| `random_4p5pt_2col` | 0.92 | 1.00 |
| `random_3p5pt_1col` | 0.93 | 0.98 |
| `random_3p5pt_3col` | 0.98 | 0.99 |
| **Mean recall** | **98.1** | **98.8** |

On saved runs, the tiling fix changes the tiles of no tiled page on olmOCR-Bench or the web set. The JSON fix
rescues one saved stage-3 output, the stress page above.

## 5. Options this suggests (undecided)

- **Margins.** Dropping all margin text is a benchmark convention that costs real content: prices, dates and
  addresses on letters and product pages. Options:
  - keep margin text that has numbers, dates or contact details;
  - make `--keep-margins` the default outside olmOCR-Bench-style use (ParseBench was already 72.8 → 74.1 with it).
- **Small CJK in tables** (half-width katakana) stays a weakness. There is no easy fix.

## Cost and time

| | Price | Stress (54 pages) | Web (200 pages) |
|---|---|---|---|
| Reducto r-1 | list $10 / 1k pages | 129–256 s | 46 s |
| Datalab accurate | $0.01 / page (billed per response) | 775–2,196 s | 452–598 s |
| Ours (c3b2) | measured $0.90–1.41 / 1k pages on Modal for olmOCR-Bench | see `reports/stress/c3b2.md` | — |

- Reducto ran with 12 requests in parallel.
- Datalab ran with 3–12 requests in parallel and was rate-limited (HTTP 429) at higher parallelism.
- Datalab spend so far:
  - $10.03 for 684 pages in run 1, of which $4.39 was the mistaken olmOCR-Bench pages;
  - $0.09 to finish the web set;
  - about $2.54 for run 2.

  Sarvam AI was considered and skipped: it targets Indian languages, and these sets are not that.

## Data saved here (for quoting with evidence)

`data/` (about 24 MB) holds everything needed to re-score or quote any number above without calling an API again:

- `data/stress_inputs/`: the 54 stress PDFs (`pages/`), exact ground truth (`gt/`) and `meta.jsonl` (font size,
  columns, word counts).
- `data/outputs/<system>/<set>/`: every page's markdown output, plus per-page logs.
  - Systems: `ours_c3b2fix`, `ours_c3b2`, `reducto_r1_run{1,2}`, `datalab_accurate_run{1,2}`.
  - Sets: `stress`, `web`.
  - Logs: `_external.jsonl` (request time, job id, cost and usage as reported by the service), and
    `_stress_eval.json` / `_random_eval.json` (per-page scores).
  - For ours, also the stage logs `_reread_*.jsonl` (raw reader outputs and tile boxes) and `_textlayer.jsonl`.
  - Run 1 of Datalab on the web set also logs the requests that first failed with HTTP 429 and were retried.
- `missed_words.json`: section 2b, per page and per system (from `bench/missed_words.py`).
- `compare.json`: all tables above, plus the list of the 157 common web pages.
- `stress_eval_*.json`, `random_eval_*.json`: per-page scores for the first runs.

The web-set PDFs are third-party documents and are not copied here. `reports/random_cc/manifest.jsonl` lists their
Common Crawl sources, and `bench/random_cc.py` fetches them again.

To reproduce:

```bash
set -a && . ./.env && set +a
.venv/bin/python bench/external.py reducto --set stress --key ext_reducto_r1_stress_r3
.venv/bin/python bench/stress_eval.py results/ext_reducto_r1_stress_r3
.venv/bin/python bench/external_compare.py
```
