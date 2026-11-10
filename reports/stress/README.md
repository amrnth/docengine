# Dense, tiny-text pages: where the system breaks (2026-11-08)

**Test.** 54 synthetic US-letter pages (`bench/stress_gen.py`), each filled edge to edge with text, with the exact
text known from the PDF's own text layer:
- font size 3–10 pt (measured on the page; two 3-column pages came out smaller than asked, 6.8 and 7.5 pt) × 1, 2 or
  3 columns;
- **natural**: real English prose from web documents;
- **random**: rare dictionary words in random order mixed with numbers and codes like `RL-307` or `98.08`. Nothing
  can be guessed from context, so this measures pure visual reading.

Up to 10,600 words on one page. Scored by `bench/stress_eval.py`:
- recall: the share of the page's words we output;
- char similarity: an order-aware check;
- whether the reader hit its output-token cap.

Run on Modal: the c3b system as deployed, then Infinity-Pro (300 dpi) re-reading every page, to separate "the
models can't" from "the cascade didn't ask". Cost ≈ $2.

## Word recall (%), averaged over 1–3 columns

| text | font (pt) | words/page | **system (c3b)** | stage 1 alone (LightOnOCR-3-0.8B, 2048 px) | Infinity-Pro on every page (300 dpi) |
|---|---|---|---|---|---|
| natural | 3 | 8,400–10,600 | 34 | 5 | 88 |
| natural | 3.5 | 6,500–7,800 | 68 | 15 | 98 |
| natural | 4 | 5,300–6,100 | 66 | 31 | 98 |
| natural | 4.5 | 4,200–4,800 | 96 | 80 | 99 |
| natural | 5 | 3,500–4,100 | 97 | 97 | 99 |
| natural | 6–10 | 1,000–2,800 | 99 | 99 | 99 |
| random | 3 | 6,200–7,400 | 0 | 0 | 49 |
| random | 3.5 | 4,500–5,600 | 1 | 0 | 55 |
| random | 4 | 3,500–4,300 | 33 | 3 | 58 |
| random | 4.5 | 3,100–3,400 | 32 | 32 | 95 |
| random | 5 | 2,500–2,800 | 63 | 63 | 97 |
| random | 6 | ~1,900 | 85 | 85 | 98 |
| random | 7 | ~1,400 | 94 | 94 | 99 |
| random | 8 | ~1,100 | 96 | 96 | 99 |
| random | 10 | ~700 | 98 | 98 | 99 |

On the random pages, **numbers survive much better than rare words**. The system keeps ≥ 99% of numbers from 6 pt up
and 95% at 5 pt; the misses are rare words "corrected" to common ones ("glomerulate" → "glomerature",
"catawampus" → "catarawmps").

## The limits, and what causes each

1. **Output length cap, the first wall on dense pages.** Stage 1 stops at 12,288 output tokens, which is about
   5,000 words of prose and about 3,000 words of random text (rare words and numbers cost more tokens). Every page
   above that was truncated. Infinity-Pro allows 16,384 tokens, about 9,000 words: it read an 8,400-word 3 pt page
   at 99% but stopped at ~83% on the 10,000+ word pages.
2. **The cascade's escalation budget.** Only the 20% least confident pages get the 4B re-read and only 10% get
   Infinity-Pro. On this set, ~22 of 54 pages were truncated, so most were never re-read. That is why the system
   scores 34–68% on 3–4 pt prose although Infinity-Pro reads the same pages at 88–98%. **This is the biggest,
   cheapest fix.**
3. **Confident hallucination when overwhelmed.** On the 3 pt two-column page, stage 1 invented a repeating list
   ("1) United States; 2) Europe; 3) Asia; … 25) Pacific Rim") with a very high mean log-probability (−0.005).
   Ranking by confidence alone does not catch this. A repetition check or the token-cap flag does.
4. **Resolution.** Stage 1 renders a letter page at 2,048 px (≈ 186 dpi): a 5 pt x-height is ~6 px. Prose survives,
   because the language model fills gaps, but unpredictable text degrades below ~7 pt and collapses below 4.5 pt.
   Infinity-Pro at 300 dpi holds 95%+ down to 4.5 pt on random text. Below that, even at 300 dpi, multi-column
   random text fails (26–58%, often finishing early as if done), so ~4 pt is the visual floor of today's models at
   300 dpi.
5. **Speed.** Dense pages are slow: stage 1 took 6 min for these 54 pages (vs 4 min for 200 normal pages), because
   output length dominates.

## Practical envelope today

| page | expected |
|---|---|
| normal documents (≥ 6 pt, ≤ ~3,000 words) | ~99% |
| dense prose 4.5–5 pt, ≤ 5,000 words | ~96–97% |
| dense tables of numbers ≥ 6 pt | ~99% of numbers |
| unusual words / codes / names at 5–6 pt | 63–85%: rare words get "corrected" |
| anything < 4.5 pt or > ~5,000 words | unreliable with the current routing |

## General fixes, in order of value

1. **Always escalate pages that hit the token cap or repeat themselves**, outside the 10–20% budget. On this set:
   system → Infinity-Pro numbers (e.g. 3.5–4 pt prose 66–68% → 98%).
2. **Tile very dense pages**: read the page in 2–4 overlapping crops at 300+ dpi and stitch them. This removes the
   output cap and raises the effective resolution. It should lift the 3–4 pt / 10k-word cases that even Infinity-Pro
   truncates.
3. **Use the PDF text layer for born-digital pages** when it is sane: exact at any size, no cap. This also came up
   on the random web PDFs.
4. Route by density up front: a page with many small text lines in the layout pass goes straight to the 300 dpi
   reader.
