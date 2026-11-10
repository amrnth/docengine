# docengine

PDF / page image → Markdown, built from open, commercially licensed models (all Apache-2.0), aiming for the
cost–accuracy frontier of [olmOCR-Bench](https://github.com/allenai/olmocr), with
[OmniDocBench](https://github.com/opendatalab/OmniDocBench) as the check that we are not overfitting.

Rules we kept: no routing or post-processing by benchmark category, no tuned thresholds (fractions are round numbers,
and confidence calibration uses the *other* benchmark), every number from our own runs.

Rule we did not keep, disclosed:
- There is no held-out split. The final system (c3b) was chosen among 34 variants scored on olmOCR-Bench, so its score
  is somewhat optimistic.
- `--drop-margins` is an olmOCR-Bench-specific setting: 87.2 with it, 77.2 without.
- ParseBench rose from 58.5 (as run) to 72.8 after fixes informed by ParseBench itself.

## Results (2026-11-06)

| System | olmOCR-Bench | OmniDocBench* | $ / 1k pages | GPU |
|---|---|---|---|---|
| v1: PP-DocLayoutV3 masks margins, OvisOCR2 reads the page | 82.3 | 92.0 | 0.19 | 4090 |
| **v2**: v1 + LightOnOCR-3-4B re-reads OvisOCR2's least-confident 10% | 84.6 | **92.3** | 0.26–0.31 | 4090 |
| casc20: LightOnOCR-3-0.8B, 4B re-reads its least-confident 20% | 86.0 | 87.3 | ~0.3 est. | 4090 |
| **c3b**: casc20 + Infinity-Parser2-Pro re-reads the least-confident 10% (end to end on Modal) | **87.2** | 87.9 | 0.90–1.41 (Modal); ~0.45–0.69 at RunPod prices | L40S + H200 |
| *Reference, same harness, no benchmark-specific post-processing:* | | | | |
| LightOnOCR-3-4B | 85.9 | 87.2 | 0.40 | 4090 |
| Infinity-Parser2-Pro (reports 87.6 *with* per-category post-processing) | 85.2 | — | 1.71 | 96 GB |
| Infinity-Parser2-Flash (reports 86.0) | 84.3 | 88.6 | 0.50 | 4090 |
| olmOCR-2 (7B, FP8; reports 82.4) | 82.1 | — | 0.38 | 4090 |

\* Overall = mean of (1 − text edit)·100, table TEDS, (1 − formula edit)·100, without CDM: comparable between our runs
only, not with published OmniDocBench numbers. $ = RunPod GPU price × measured inference time (est. = combined
offline from separate runs, not timed end to end).

### Other benchmarks (2026-11-07, not used for tuning before this; details in PLAN.md)

| System | ParseBench overall (official scorer) | DP-Bench NID / TEDS | CC-OCR tables TEDS / TEDS-S |
|---|---|---|---|
| c3b as run | 58.5 (charts 1.1: chart blocks were dropped) | 0.920 / 0.955 | 58.4 / 89.4 |
| c3b, current default (chart tables kept, title headings) | 72.8 | 0.920 / 0.955 | — |
| c3b, current default + `--keep-margins` | 74.1 | 0.956 / 0.955 | — |
| v2 as run | 40.8 (no chart data, no boxes) | 0.937 / 0.948 (table F1 0.973, best) | 58.9 / 89.6 |
| References | LightOnOCR-3-4B 75.6, Datalab Accurate 72.9, Infinity-Parser2-Pro 71.2, Reducto Agentic 70.9, LlamaParse Agentic Plus 86.7 | Upstage 0.966 / 0.956, AWS 0.960 / 0.955 | — |

The default change (keep chart/image blocks holding an HTML table; '#' for title blocks) left olmOCR-Bench at 87.2 and
moved OmniDocBench 87.94 -> 88.08. Reading: c3b's olmOCR-Bench lead does not carry over to ParseBench, mostly because
of olmOCR-shaped conventions (dropping page headers/footers costs ~4 points of ParseBench content faithfulness and
DP-Bench NID).

**Failure review** (`reports/failure_review/`): of c3b's 916 failed olmOCR-Bench tests, roughly 25–30% are real
reading errors, ~55% are notation/convention differences where our output is a correct reading, and ~15% are wrong
tests (the expected string is a typo or not on the page — checked against the PDF's own text layer).

**Random real-world PDFs** (`reports/random_cc/`): 200 random pages from the Common Crawl PDF corpus. No crashes,
empty or looping outputs; 96.3% word precision / 92.5% recall against the PDFs' own text layers (165 born-digital
pages); hand-checked scans read correctly. Found weaknesses: unrenderable fonts (fix: use the text layer when sane),
captions/datelines dropped as header/footer, text inside figures skipped.

**c3b2** (2026-11-08, `reports/stress/c3b2.md`): visibly failed pages are always re-read, dense pages are read in
tiles at 400 dpi, and born-digital pages are spell-checked against their own text layer. Dense 3–4 pt pages now read
at 98–99% (English) and 90–98% (random words), up from 0–68%. olmOCR-Bench 86.9 ± 0.9: the changes themselves net +2
tests, and the rest is run-to-run sampling.

**Commercial APIs** (2026-11-09, `reports/external/`), on our own test sets only:
- **Dense 3–10 pt pages, word recall:** ours 98.8, Reducto r-1 94–95, Datalab accurate 83–85. On rare words at
  3–4 pt: ours 98, Reducto 49–88, Datalab 29–60.
  - **Caveat: this lead is partly circular.** These pages are born-digital. Our text-layer step corrects words with
    the PDF's stored text, and the ground truth is that same text. Without the step, ours was 74–91 on rare words at
    3–4 pt.
  - An image-only re-run, which removes the stored text for every system, has not been done.
- **200 random web pages, precision / recall against the PDFs' text:** ours 96.8 / 92.8, Reducto 89 / 97.5, Datalab
  88.5 / 94.8.
  - About half of our recall gap is header/footer text we read and drop by design. Most of the rest is stored-text
    artefacts the others copy, plus text inside charts and maps.
  - With headers/footers kept, now the default outside olmOCR-Bench: 96.3 / 96.1 (offline rebuild).
  - Their precision gap is mostly image descriptions they add.

The comparison found two tiling and parsing bugs, now fixed.

**Benchmark audit** (2026-11-10, `reports/audit/`): why no system gets clearly above 88 on olmOCR-Bench.
- **38 tests cannot be passed by a correct reader** (0.61 points). 32 expect a string the page does not show
  ("sternum" for "scrotum", "line 2" for "line 37a"); 6 header/footer tests forbid a string that is also body text.
  Evidence: the PDF's stored text, at least 3 of 4 model families, and a page crop for each.
- This is a lower bound: the method can check only 1,100 of the 8,413 tests (no scans, math or tables).
- 561 tests (8.6 points) are failed by all 14 saved runs from four model families. Best run per test: 91.4.
- Without the 38 tests every run gains 0.5–0.6 and the order does not change.
- Paired with single models on the same tests, c3b is +1.24 over LightOnOCR-3-4B (95% +0.45 to +2.18) and +1.95 over
  Infinity-Parser2-Pro. c3b was the best of 34 variants, so read this as about +1.

Published olmOCR-Bench leaders: Infinity-Parser2-Pro 87.6 (uses benchmark-folder-specific post-processing in its
eval script), OXR-1.0 87.84 (unverified snapshot; excluded: its licence restricts companies over $2M revenue/funding and bans competing hosted APIs), LightOnOCR-3-4B 86.3, Chandra 2
85.8.

## Layout

| Path | What |
|---|---|
| `docengine/pipeline.py` | Stage 1 driver: render, PP-DocLayoutV3 layout, OCR via a vLLM server; readers `ovis`, `lighton`, `infinity`, `olmocr2`; writes per-page confidence |
| `docengine/reread.py` | Stage 2: re-read the least-confident pages with a second reader |
| `docengine/layout.py` | PP-DocLayoutV3 wrapper (margin labels: header, footer, number, aside_text) |
| `runpod/launch.py`, `runpod/job.sh` | Rent a RunPod GPU, run a benchmark job by key, pull outputs, terminate |
| `azure/score.sh`, `bench/omni/` | OmniDocBench scoring on an Azure CPU VM |
| `bench/scoreboard.py`, `bench/failures.py`, `bench/oracle.py` | olmOCR-Bench scoring, per-test failures, best-of-N ceiling |
| `bench/cascade.py`, `selector.py`, `consensus.py`, `union_drop.py`, `route_sim.py` | Offline combination experiments |
| `bench/export_failures.py` → `failures/` | Every failed case per system, for error analysis |
| `bench/test_matrix.py`, `audit_tests.py`, `audit_confirm.py`, `audit_crops.py`, `audit_report.py` → `reports/audit/` | Benchmark audit: per-test results, tests checked against the PDF's stored text, page crops |
| `PLAN.md` | Full lab notebook: every experiment, number, cost and decision, in order |
| `DEPLOY.md` | How to run v2 and c3b, pinned model revisions, gotchas |
| `deploy/modal_app.py` | c3b / v2 end to end on Modal (L40S + H200), one command |

Not in this repository (see `.gitignore`): `.env` (API keys), `data/` (benchmarks, re-downloadable), `vendor/`
(cloned olmocr / OmniDocBench / chandra repos), `results/` (raw run outputs, ~650 MB), virtualenvs. Our page-level
outputs on the benchmarks are not included either; `reports/audit/pass/` has every run's per-test pass/fail, and
`bench/export_failures.py` writes the failed pages' outputs to `failures/` from a local `results/`.
`reports/external/data/` is included: the stress-test PDFs and every system's output on both of our own test sets.

`PLAN.md` is the full lab notebook.

## License

MIT, see `LICENSE`. The models the pipeline calls have their own licences (all Apache-2.0); the benchmarks have
theirs.

## Setup

```bash
uv venv .venv && uv pip install -r requirements.txt
# olmOCR-Bench scorer + data
git clone https://github.com/allenai/olmocr vendor/olmocr && uv pip install -e vendor/olmocr
huggingface-cli download allenai/olmOCR-bench --repo-type dataset --local-dir data/olmOCR-bench
# OmniDocBench scorer (scored on Azure; see azure/score.sh)
git clone https://github.com/opendatalab/OmniDocBench vendor/OmniDocBench
```

RunPod needs `RUNPOD_API_KEY` in `.env` and an SSH key (`RUNPOD_SSH_KEY`, default `~/.ssh/runpod_cheap_inference`,
created on first use); Azure scoring needs a logged-in `az`.

### Reproducing the olmOCR-Bench audit

Needs the olmOCR-Bench data (above) and saved runs in `results/<run>/`. Model families used for confirmation:
`lt4_u`, `lt08_u` (LightOnOCR-3), `inf_pro`, `inf_flash` (Infinity-Parser2), `olm2_plain` (olmOCR-2), `ovisocr2`.

```bash
.venv/bin/python bench/test_matrix.py modal_c3b_olmocr lt4_u lt08_u inf_pro inf_flash olm2_plain ovisocr2  # per-test pass/fail
.venv/bin/python bench/audit_tests.py     # every text test against the PDF's stored text
.venv/bin/python bench/audit_confirm.py   # keep tests where >= 3 of 4 model families agree with the stored text
.venv/bin/python bench/audit_crops.py     # page crops for checking by eye (verdicts in reports/audit/review.json)
.venv/bin/python bench/audit_report.py    # numbers, paired tests, reports/audit/wrong_tests.md
.venv/bin/python bench/audit_issue.py     # the report filed as allenai/olmocr#485
```

## Known gaps / next steps

- Single page only; no API service; no multi-page reassembly.
- Generalisation so far: ParseBench, DP-Bench, CC-OCR tables (above). Still open: READoc (multi-page), OCRBench v2,
  UniMERNet, official OmniDocBench with CDM. Headers/footers are kept by default
  since 2026-11-09 and dropped only for olmOCR-Bench (`--drop-margins`): olmOCR-Bench 87.2 dropped vs 77.2 kept,
  ParseBench 72.8 -> 74.1 kept.
- An ideal per-page choice between our readers would score 90.0 on olmOCR-Bench; capturing that without labels is
  open (confidence and text-consensus selection reach only 85.6–85.9).
