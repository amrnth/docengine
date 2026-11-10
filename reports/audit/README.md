# olmOCR-Bench audit (2026-11-10)

Question: why does no system get clearly above 88? We examined the tests, not the models.

## Results

| | |
|---|---|
| Tests in the benchmark (with the automatic baseline tests) | 8,413 |
| Text tests on pages with stored text (the only ones this method can check) | 1,100 |
| Expected string not in the stored text, under any normalisation | 120 |
| …and the stored text holds another string that >= 3 of 4 model families output | 37 |
| …and confirmed on the page crop | **32** (5 rejected) |
| Header/footer tests whose forbidden string is also body text | **6** |
| **Tests a correct reader cannot pass** | **38** = 0.61 points of the score |
| Tests failed by all 14 saved runs | 561 = 8.6 points |
| Score of "best run for each test" | 91.4 |

Without the 38 tests, each run gains 0.5–0.6 points and the order does not change (`summary.json`).

Paired comparison of c3b with single models (bootstrap over pages, 5,000 samples): LightOnOCR-3-4B +1.24
(95% +0.45 to +2.18), Infinity-Parser2-Pro +1.95 (+0.86 to +3.22), LightOnOCR-3-0.8B +2.35 (+1.26 to +3.78).

## Rule

1. `bench/audit_tests.py`: apply each `present` / `order` test's own rule (same normalisation, same `max_diffs`) to the
   PDF's stored text. A string counts as on the page if it matches any of: line-break hyphens joined or kept, ligatures
   expanded, accents removed, case folded, all spaces removed. Pages with less than 200 stored characters or a
   full-page image are skipped.
2. `bench/audit_confirm.py`: keep a test only if the nearest stored string is close (edit distance <= 35% of the
   length) and at least 3 of 4 model families output that string, within the test's `max_diffs`, and do not output the
   test's string. Families: LightOnOCR-3 (4B, 0.8B), Infinity-Parser2 (Pro, Flash), olmOCR-2, OvisOCR2.
3. `bench/audit_crops.py` + `review.json`: look at each page crop. 31 of the 32 kept tests were seen on the crop; one
   rests on the stored text and 4 of 4 families.
4. Header/footer (`absent`) tests: listed where the forbidden string is at two or more places in the stored text, or
   where 5 or 6 of the 6 single models fail; then judged by eye, with `first_n` / `last_n` taken into account.

Why the second step is needed: the stored text is wrong on some pages (OCR layers of scans, lost ligatures, line
numbers). In 46 of the 120 tests all four model families output the test's string, so the stored text is the bad one.

## Limits

- Only 13% of the tests can be checked this way. Scans, math and tables cannot. 38 is a lower bound.
- The 561 "failed by all" tests are not all wrong tests: many are hard pages (handwriting).
- The paired test uses one run of each system. c3b was chosen among 34 variants on this benchmark.

## Files

| File | What |
|---|---|
| `wrong_tests.md` | The 38 tests, what each expects, what the page shows, and the 5 rejected candidates |
| `upstream_issue.md` | The report sent to the maintainers (`bench/audit_issue.py`): [allenai/olmocr#485](https://github.com/allenai/olmocr/issues/485), filed 2026-11-10 against dataset revision `54a96a6` |
| `review.json` | By-eye verdicts |
| `crops/sheet_1..8.png` | Page crops of the 40 candidate strings, in the order of `wrong_tests.jsonl` |
| `crops/headers_footers.png` | Every place of the forbidden string for the header/footer tests |
| `wrong_tests.jsonl` | All 120 stage-1 candidates with the evidence per string |
| `text_audit.jsonl` | Stage 1 for every text test |
| `tests.json`, `pass/<run>.json` | Per-test pass (1) / fail (0) of 14 runs, same order as `tests.json` |
| `summary.json` | All numbers above |

Runs: `modal_c3b_olmocr` (c3b), `modal_c3b2_olmocr`, `casc20`, `l08pro2`, `ltpro1`, `v2`, `pipe_mask` (v1); single
models `lt4_u` and `lt4` (LightOnOCR-3-4B), `lt08_u` (0.8B), `inf_pro`, `inf_flash`, `olm2_plain`, `ovisocr2`.
