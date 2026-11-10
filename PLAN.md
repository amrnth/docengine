# docengine — plan

## Goal
Build a PDF → Markdown parser that sits on the **cost–accuracy frontier** of olmOCR-Bench:
either beat the top score, or match it closely at a clearly lower cost per 1,000 pages.
Built for fun, and as the document layer for our AI services company (so licences must allow commercial use).

## Decisions
| Topic | Decision |
|---|---|
| Primary benchmark | **olmOCR-Bench** (1,403 PDFs, ~7,010 pass/fail tests) |
| Headline metric | Score vs **$ per 1,000 pages** (Pareto chart against published systems) |
| Speed | No limit; cost is what we optimise |
| Output | Markdown, in the format olmOCR-Bench expects |
| Models | Open models first; API models (Gemini etc.) allowed as a separately scored mode |
| Compute | Rented GPUs: RunPod first ($10 credit), then AWS/GCP credits. Mac (M4 Pro, 24 GB) for dev + scoring |
| Generalisation | Check the pipeline on other benchmarks (OmniDocBench v1.6 etc.) so we don't overfit olmOCR-Bench |
| Reading order | Handled by a model pass |

## olmOCR-Bench: what it rewards
- Test categories: arXiv math (2,927), tables (1,020), multi-column (884), headers/footers (753),
  old scans (526), old scans math (458), long/tiny text (442).
- Test types: text present, text **absent** (headers, footers, page numbers must be removed),
  reading order, table cell relationships, math rendering.
- Scoring code: `olmocr/bench/benchmark.py` in github.com/allenai/olmocr; data: `allenai/olmOCR-bench` on Hugging Face.

## How cost is measured
`$ per 1k pages = (GPU $/hour × wall-clock hours for the run + any API spend) / pages × 1000`,
on a named GPU type, with models served by vLLM. Model download and setup time is excluded but reported.

## Phases
| Phase | Work | Done when | Budget |
|---|---|---|---|
| 0 | Local scoring setup + 100-page dev subset | One published score reproduced from its released outputs | $0 |
| 1 | Baselines: 3 open models on RunPod, plus cost per page | Our own scoreboard, by category | ~$2–3 |
| 2 | Pipeline v1: layout → per-region readers → reading-order pass → Markdown | Beats best single baseline, or matches it cheaper | ~$5–6 |
| 3 | Improvements: PDF text layer, header/footer removal, multi-model voting on hard regions, checks/retries | Each change shows a gain | (within above) |
| 4 | Optional: fine-tune the weakest step | Closes remaining gap | separate credit |

## Licences (commercial use matters)
- **Chandra 2 (Datalab):** weights under modified OpenRAIL-M — free under $2M revenue/funding, not allowed in
  competition with Datalab's API. Fine for benchmarking; risky as a component in a product. Verify the model card.
- **PaddleOCR-VL, OvisOCR2, olmOCR 2, dots.ocr:** check each model card before relying on it.

## RunPod budget rules
1. Develop and debug on the Mac against the dev subset.
2. GPU only for full benchmark runs: start pod → run → save outputs → stop pod.
3. Keep model weights on a network volume.
4. Serve models with vLLM.
5. Score on the Mac (CPU only).

## Results log
### 2026-11-05 — Phase 1/2 (olmOCR-Bench, full 1,403 pages)
| System | Overall | H&F | Old scans | Tables | arXiv | $/1k pages |
|---|---|---|---|---|---|---|
| OvisOCR2 alone | 72.1 | 17.9 | 33.1 | 85.5 | 89.1 | 0.13 (4090) |
| **pipeline v1 mask** (PP-DocLayoutV3 masks header/footer/page no./margin → OvisOCR2 page pass) | **82.2** | 93.6 | 37.6 | 86.1 | 88.8 | 0.47 (H100) |
| pipeline v1 regions (per-region crops) | 80.3 | 95.4 | 36.9 | 83.4 | 88.2 | 0.81 (H100) |
Published: olmOCR 2 82.4, Chandra 2 85.8. Decision: keep **mask** mode. Remaining gap: old scans (handwriting
recognition errors, not formatting), tables, old-scans math. Next idea: route hard pages to a stronger model.
H100 was only ~1.5x faster than a 4090 for this 0.8B model at 4.5x the price.

### 2026-11-05 — Overfitting check on OmniDocBench v1.6 (1,651 pages, RTX 4090)
| System | Text edit ↓ | Formula edit ↓ | Table TEDS ↑ | Order edit ↓ | Overall* ↑ | $/1k pages |
|---|---|---|---|---|---|---|
| OvisOCR2 alone | 0.034 | 0.089 | 89.2 | 0.120 | 92.3 | 0.14 |
| pipeline v1 mask | 0.035 | 0.090 | 88.9 | 0.122 | 92.1 | 0.20 |
Overall* = ((1-text)+TEDS+(1-formula edit))/3; CDM omitted, so not comparable to the leaderboard, only between our runs.
Verdict: mask mode neither helps nor really hurts here (-0.2). OmniDocBench ignores headers, footers and page numbers
when matching, so removing them can't score; the small loss is layout boxes that wrongly blanked real content.
So the +10 on olmOCR-Bench is a real feature (clutter removal, which the user wants for downstream use) rather than a
general reading-accuracy gain. Next accuracy gains must come from reading quality (hard pages, tables), checked on both.
Scoring now runs on Azure (azure/score.sh, F64as_v7, ~6 min/run vs ~2.5 h on the Mac) using a patched OmniDocBench
page matcher that uses processes instead of GIL-bound threads (OMNI_PAGE_PROCS=1; verified to reproduce Mac numbers
within 0.0002).

### 2026-11-05 — Error analysis of pipeline v1 mask on olmOCR-Bench (bench/failures.py → results/pipe_mask/_failures.jsonl)
1,135 failed tests of 7,019. Where they come from:
| Category (score) | Fails | Main causes |
|---|---|---|
| Old scans (37.6) | 322 | Real reading errors on handwriting / degraded print: ~150 badly misread or missing, ~145 small misreads |
| arXiv math (88.8) | 327 | Mix of real formula errors and notation the scorer treats as different (\leqslant vs \leq, \cdots vs \dots, author macros in ground truth) |
| Multi-column (81.3) | 165 | Mostly not order: ~100 small misreads (inline LaTeX for symbols, e.g. μ → $\mu$; dropped diacritics), 18 missing, 10 blanked by the mask |
| Tables (86.1) | 142 | 62 wrong structure, 58 missing/misread cells, 22 table not output as a table |
| Old scans math (80.1) | 91 | Formula reading errors |
Mask false positives: 34 tests fail only because the mask blanked real content (affiliations, copyright lines, sidebars) ≈ −0.5 overall.

### 2026-11-06 — Strong-reader ceiling test: olmOCR-2 (7B FP8, Apache-2.0) through our pipeline, RTX 4090
olmOCR-Bench (full, plain mode; olmOCR-2 drops headers/footers itself). bench/oracle.py = best of the two per page,
picked with the answer key, so an upper bound for any page-level router:
| Run | Overall | arXiv | H&F | Long tiny | Multi-col | Old scans | Old-scan math | Tables | Baseline | $/1k (4090) |
|---|---|---|---|---|---|---|---|---|---|---|
| pipeline v1 mask | 82.2 | 88.8 | 93.6 | 92.5 | 81.3 | 37.6 | 80.1 | 86.1 | 97.4 | ~0.20 |
| olmOCR-2 | 82.1 | 83.6 | 96.2 | 83.9 | 83.4 | 46.6 | 79.5 | 83.9 | 99.9 | 0.38 |
| oracle (best per page) | 87.1 | 91.6 | 97.6 | 93.0 | 86.2 | 49.6 | 87.1 | 91.5 | 99.9 | — |
(olmOCR-2 via our harness 82.1 vs published 82.4, so the harness is faithful.)

OmniDocBench, same 876 pages for all three (run stopped early: olmOCR-2 loops on Chinese notes/reports, ~5 h ETA):
| Run | Text edit ↓ | Formula edit ↓ | Table TEDS ↑ | Order edit ↓ | Overall* ↑ |
|---|---|---|---|---|---|
| OvisOCR2 alone | 0.025 | 0.058 | 89.3 | 0.091 | 93.7 |
| pipeline v1 mask | 0.028 | 0.062 | 89.2 | 0.095 | 93.4 |
| olmOCR-2 | 0.081 | 0.135 | 69.7 | 0.175 | 82.7 |
olmOCR-2 is worse on every OmniDocBench source, English included (text 0.044 vs 0.018; newspapers 0.41 vs 0.08).

Conclusion: a second reader can lift olmOCR-Bench a lot (ceiling 87.1 > Chandra 2's 85.8), but olmOCR-2 is the
wrong second reader: it was trained toward olmOCR-Bench-style data and does not generalise (OmniDocBench −11).
Its olmOCR-Bench advantage (old scans, headers) is partly home-field. Next: pick the second reader on general data
(OmniDocBench first, then olmOCR-Bench), e.g. a larger general VLM, and only then build confidence routing.
Spend: RunPod $1.33 (balance $2.49); Azure scoring on credits. No pods or VMs left running.

### 2026-11-06 — Second-reader shortlist (research only, nothing run)
Scores are self-reported on the model cards (HF, checked 2026-11-06) unless marked; "—" = not reported.

| Model | Params | Licence | olmOCR-Bench | OmniDoc v1.6 | Verdict |
|---|---|---|---|---|---|
| **LightOnOCR-3-0.8B / 4B** (Oct 2026, Qwen3.5) | 0.85 / 4.5B | Apache-2.0 | 85.5 / 86.3 | — | **Test first.** Best olmOCR-Bench under a clean licence; 0.8B alone beats our 82.2. Unknown on OmniDoc (earlier LightOn models skipped it: weak Chinese) → measure before trusting. Native header/footer/page_number labels in `grounding` mode = "label instead of erase" for free. |
| **Infinity-Parser2-Flash** (May 2026) | 2.2B | Apache-2.0 | 86.0 | 91.98 | **Test.** Only model reporting both, and good on both. |
| **Xiaomi-OCR-0** (Sep 2026, Qwen3.5) | 0.87B | Apache-2.0 | — | 96.83 | Test as a *primary* swap for OvisOCR2 (96.58), not as second reader. |
| **TeleOCR** (Aug 2026, Qwen2.5-VL) | 1.4B | Apache-2.0 | — | 96.87 | Same role as Xiaomi-OCR-0; pick one of the two. |
| dots.mocr | 3.0B | MIT | 83.9 (old scans 48.2, old-scan math 85.5) | — (dots.ocr 90.5) | Backup: strong exactly where we fail (old scans). |
| PaddleOCR-VL-1.6 | 0.96B | Apache-2.0 | 78.5 (v1.5) | 96.33 | Skip: same profile as OvisOCR2, adds little. |
| Infinity-Parser2-Pro | 35B MoE | Apache-2.0 | 87.6 | 93.95 | Skip for now: needs 2 GPUs, breaks the 4090 cost story. |
| OXR-1.0 | 1.3B | Custom: >$2M revenue/funding needs licence, **no competing hosted API** | claims #1 | claims #1 | Excluded (licence). |
| Chandra OCR 2 | — | OpenRAIL-M modified | 85.8 | — | Excluded (licence). |
| olmOCR-2 | 7B | Apache-2.0 | 82.4 | 82.7* (our 876-page subset) | Rejected (tested 2026-11-06). |

Pattern: models strong on olmOCR-Bench don't report OmniDocBench and vice versa — the same home-field split we hit
with olmOCR-2. So the screen must score every candidate on *both* before any routing work.

Proposed screen (needs approval + RunPod top-up; balance $2.49): for each of LightOnOCR-3-0.8B, LightOnOCR-3-4B,
Infinity-Parser2-Flash, Xiaomi-OCR-0 — full olmOCR-Bench + the 876-page OmniDoc subset on one 4090, then
bench/oracle.py vs pipe_mask. Keep a candidate only if OmniDoc overall* ≥ ~92 (within ~1.5 of OvisOCR2).
Rough cost: ~$0.5–1.5 per model incl. idle → ~$4–6 total, plus Azure scoring.

### 2026-11-06 — LightOnOCR-3 screen (RTX 4090, vLLM 0.30.0, model-card settings: `grounding` prompt, 2048 px, T=0.1)
No LightOn olmOCR-specific post-processing (their `pp3`) and not their olmOCR-tuned 400 DPI/5 Mpx render.
Margin blocks dropped by the model's own labels (header/footer/page_number/aside_text; image/chart text dropped like
OvisOCR2's `<img>`), so no layout model is needed. `_u` = also drop blocks >=60% inside a PP-DocLayoutV3
header/footer/number/aside region (bench/union_drop.py; geometry only). Cascade = bench/route_sim.py: 0.8B reads
every page, its least-confident X% (own mean token logprob) re-read by the 4B.

| System | olmOCR-Bench | OmniDoc overall* | $/1k pages (4090) |
|---|---|---|---|
| pipe_mask (OvisOCR2 + mask) | 82.2 | 92.1 | ~0.20 |
| LightOnOCR-3-0.8B | 83.9 | 86.5 | 0.14 |
| LightOnOCR-3-0.8B _u | 84.8 | 86.5 | ~0.20 |
| LightOnOCR-3-4B | 85.3 (LightOn reports 85.4 for this setup) | 87.2 | 0.40 |
| LightOnOCR-3-4B _u | 85.9 | 87.2 | ~0.46 |
| cascade 0.8B_u → 4B_u, 20% re-read | 86.0 (10–50% all 85.8–86.1) | not yet scored | ~0.28 |
| oracle pipe_mask / lt08 / lt4 | 88.4 | | |

OmniDoc gap of LightOn vs OvisOCR2: 81% of the text gap comes from 50 pages scored ~1.0. 46% of the text gap is 41
pages where LightOn transcribes vocabulary lists / contents / exercise grids as HTML tables while OmniDoc's GT has
text (a convention, not a misread). Rest: real losses (contents page labelled `image`, one loop) and genuinely weaker
reading on Chinese, handwritten notes and newspapers (English text edit 0.038 vs 0.025 even so).
=> Each benchmark rewards a different reader. Next: run both readers, pick per page by label-free confidence
(bench/selector.py: mean-logprob percentiles, calibrated on the *other* benchmark).

### 2026-11-06 — Combining OvisOCR2 and LightOnOCR-3 with label-free confidence (final table of the day)
OvisOCR2 mask re-run with token logprobs (pipe_mask_lp 82.3 / omni_mask_lp 92.0: reproduces pipe_mask).
All routing uses only a reader's own mean token logprob; fractions are fixed round numbers, not tuned.
- `ovcasc10` (bench/cascade.py): OvisOCR2+mask everywhere, LightOnOCR-3-4B_u re-reads OvisOCR2's least-confident 10%.
- `casc20`: LightOnOCR-3-0.8B_u everywhere, 4B_u re-reads its least-confident 20%.
- `sel_m0.0` (bench/selector.py): both readers on every page, pick the one with the higher confidence percentile,
  percentiles calibrated on the *other* benchmark.

| System | olmOCR-Bench | OmniDoc overall* | $/1k pages (4090) |
|---|---|---|---|
| pipe_mask (v1) | 82.3 | 92.0 | 0.19 |
| **ovcasc10** | **84.6** | **92.2** | **~0.24** |
| ovcasc20 | 84.8 | 91.9 | ~0.28 |
| sel_m0.0 | 84.5 | 90.8 | ~0.65 |
| LightOnOCR-3-4B_u | 85.9 | 87.2 | ~0.46 |
| **casc20** | **86.0** | 87.3 | **~0.28** |
| published: Chandra 2 / LightOn-4B+pp3 / Infinity-Parser2-Pro (35B, 2 GPUs) | 85.8 / 86.1 / 86.9 | | |

Verdict: two honest operating points.
- **ovcasc10 = new default (pipeline v2):** beats v1 on both benchmarks (+2.3 olmOCR, +0.2 OmniDoc) for +$0.05/1k.
- **casc20:** near-SOTA on olmOCR-Bench (86.0, above Chandra 2) at ~$0.28/1k, but −4.7 on OmniDoc, mostly because
  LightOn writes lists/contents as tables where OmniDoc's GT expects text, plus weaker Chinese/handwriting.
Confidence selection between readers (sel_*) trades along the same line but never beats the cascades.
Not yet built as one deployable pipeline: ovcasc10 needs both models on one GPU (0.85B + 4B fit a 4090).
Next ideas: Infinity-Parser2-Flash (reports 86.0 / 91.98) as the re-reader; implement v2 end-to-end and time it.

### 2026-11-06 — Pipeline v2 built end to end (docengine/reread.py, job.sh keys v2 / omni_v2)
One 4090, vLLM 0.30.0 image (OvisOCR2 runs fine on it). Stage 1 = `docengine.pipeline --mode mask` (layout +
OvisOCR2, token logprobs). The vLLM model is then swapped, and stage 2 = `docengine.reread --frac 0.1`: LightOnOCR-3-4B grounding
on OvisOCR2's least-confident 10% of the job, dropping margin blocks by LightOn's label or the stage-1 layout regions
(`grounding_to_md(..., margins=, size=)`). If LightOn returns nothing, the page keeps the stage-1 text.
Offline check: on saved outputs, reread's logic reproduces ovcasc10 page for page (140/140 identical).

| run | score | v2 offline | v1 | stage1 s | stage2 s (re-read pages) | model loads s | $/1k (inference) | $/1k (incl. loads) |
|---|---|---|---|---|---|---|---|---|
| v2 (olmOCR-Bench, 1403 p) | **84.6** | 84.6 | 82.3 | 925 | 553 (140) | 347 | 0.26 | 0.32 |
| omni_v2 (OmniDoc overall*, 1651 p) | **92.29** | 92.17 | 92.01 | 1239 | 858 (165) | 152 | 0.31 | 0.34 |

- Scores match the offline estimate; the small OmniDoc difference comes from sampling variation in re-reads that
  needed a retry, plus the empty-output fallback.
- Stage 2 is the bottleneck: the hardest 10% of pages take about 35-40% of the time (long outputs and loops; omni had
  52 retries in 165 pages), and 140-165 requests don't saturate the GPU. The real cost is $0.26-0.31/1k, not the ~$0.24 estimate.
- Fraction versus fixed threshold: OvisOCR2's p10 confidence cut-off is -0.056 on olmOCR-Bench but -0.088 on OmniDoc;
  the olmOCR-Bench cut-off would re-read 15% of OmniDoc. We keep the per-job fraction as the default (`--below T` exists for streaming).
- Cheaper stage 2 ideas: lower max_tokens / earlier loop cut-off for re-reads; co-serve both models so stage 2
  overlaps stage 1 (needs KV-cache room); a smaller re-reader (Infinity-Parser2-Flash).

### 2026-11-06 — Infinity-Parser2 Flash/Pro, measured cleanly; Pro as last-stage re-reader
Goal update: outright SOTA on olmOCR-Bench (public 87.6 = Infinity-Parser2-Pro; one unverified leaderboard snapshot
shows OXR-1.0 87.84, which we excluded for its licence), then check every other public benchmark for overfitting.

Their harness (INF-MLLM/Infinity-Parser2/evaluation/olmocr-bench/infer.py): doc2json prompt, 300 DPI, greedy, drop
header/footer/page_footnote blocks, **plus post-processing chosen by benchmark folder** (synonym map + LaTeX-to-Unicode
only for `tables`/`multi_column`, LaTeX normalisation only for the math folders). That is category routing, so we
reproduce everything except it (`--reader infinity`). Running their post-processing to measure its effect was
blocked here, because it would run code downloaded from their repository; not measured.

| System (no benchmark-specific post-processing) | olmOCR-Bench | OmniDoc overall* | $/1k | GPU |
|---|---|---|---|---|
| Infinity-Parser2-Flash (2B) | 84.3 (they report 86.0) | 88.57 | 0.50 | 4090 |
| Infinity-Parser2-Pro (35B-A3B, bf16) | 85.2 (they report 87.6) | — | 1.71 | RTX PRO 6000 96 GB |
| LightOnOCR-3-4B_u | 85.9 | 87.19 | 0.40 | 4090 |
| ltpro1: LightOn-4B_u, Pro re-reads its least-confident 10% | 86.7 | 88.23 | ~0.75 est. | |
| **c3b: 0.8B_u → 4B_u re-reads 20% → Pro re-reads 10% (by 4B confidence)** | **86.8** | 88.26 | ~0.6 est. | |
| v2 (OvisOCR2 mask → LightOn-4B 10%) | 84.6 | **92.29** | 0.26 | 4090 |

- Pro's clean category scores vs its card: old_scans 57.6 (58.2), headers 95.9 (95.8), tables 89.2 (91.2), arxiv 87.4
  (88.1), old_scans_math 83.8 (91.3), long_tiny 86.7 (92.5). Our run truncated 1 page (16k max tokens vs their 32k,
  13 failed tests on that page), and long_tiny failures cluster on 2 pages. The big gaps are in the categories their
  folder-specific post-processing targets (math, tables).
- Oracles (best of several readers per page) are high: v2+Pro 88.6, LightOn-4B+Pro+OvisOCR2+Flash 90.0. Text-consensus
  selection (bench/consensus.py, edit-distance agreement) does not capture this: 85.7-85.9, because the LightOn
  models share their errors.
- Pro cascades also gain on OmniDoc (+1.0 over LightOn-4B), so this is not olmOCR-specific, but every LightOn-first
  system stays ~4 points below v2 on OmniDoc (LightOn writes lists/contents as tables).
- Pro on hard pages is slow: 176 hard OmniDoc pages took 1050 s (6 s/page vs 2.5 s average).
- Spend this round: RunPod ~$6.3 (Flash $1.40; Pro: L40S/A100 failures ~$0.6, RTX PRO 6000 $0.41 + $2.77 + $1.17).
  The A100 cannot run this model in FP8 (missing cutlass sm80 kernel), and the L40S has no KV-cache room left with FP8.
- Status: 86.8 is the best clean olmOCR-Bench number we know of, but it does not beat the published 87.6/87.84 as
  printed. Claiming SOTA requires either (a) a level comparison (running their harness with and without their
  post-processing), or (b) more accuracy.

### 2026-11-07 — c3b built and run end to end on Modal (deploy/modal_app.py)
Code: `pipeline.py --layout-drop` (grounding reader + PP-DocLayoutV3 margin-region drop in one pass) and
`reread.py --rank-by/--tag` (chain re-read stages: stage 3 ranks by stage 2's own confidence). Modal app: stages 1-2
on one L40S (0.8B then 4B, model swap in between), stage 3 on an H200 (Pro bf16, as benchmarked); data + model cache
on the `docengine-data` volume. Smoke test (20 pages) first, then both benchmarks in parallel.

| run | olmOCR-Bench | OmniDoc overall* | offline estimate | stage 1 s | stage 2 s (pages) | stage 3 s (pages) | loads s |
|---|---|---|---|---|---|---|---|
| modal_c3b_olmocr (1403 p) | **87.2** (±0.8) | | 86.8 | 869 | 455 (281) | 436 (140) | 206+195+296 |
| modal_c3b_omni (1651 p) | | 87.94 | 88.26 | 1528 | 1464 (330) | 567 (165) | 211+195+216 |

olmOCR-Bench categories (end to end): arxiv_math 89.0, old_scans_math 87.6, tables 88.9, old_scans 58.0,
headers_footers 96.3, multi_column 83.8, long_tiny_text 94.1, baseline 99.6.

Cost per 1k pages (GPU time only; Modal list prices L40S $1.95/h, H200 $4.54/h):
- olmOCR-Bench: inference $0.90 (L40S $0.51 + H200 $0.39); including the three model loads $1.33.
- OmniDoc: inference $1.41; including loads $1.72 (more long Chinese / dense pages: stage 2 is 2x longer).
- At RunPod prices (4090 $0.89/h for stages 1-2, RTX PRO 6000 $2.49/h for Pro, assuming similar speed):
  ~$0.45/1k (olmOCR-Bench) and ~$0.69/1k (OmniDoc). Model loads are fixed per job, so they matter less on big jobs.
- Total Modal spend for this work (smoke + both runs + data prep): ~$6 of the $30 credit. No apps left running
  (a watchdog would have stopped them after 2.5 h).

Reading: the end-to-end run scores 0.4 above the offline combination on olmOCR-Bench (re-reads sample at
temperature 0.1, so ± a few tenths is run-to-run noise; CI is ±0.8) and 0.3 below on OmniDoc. 87.2 is still below the
published 87.6 (Infinity-Parser2-Pro, with benchmark-folder-specific post-processing; 85.2 without, in our harness)
and the unverified 87.84 (OXR-1.0). Within the confidence interval of both, so not a clear SOTA claim.

### 2026-11-07 — generalisation: ParseBench, DP-Bench, CC-OCR tables (none used for tuning before this)
Runs on Modal, `--bench gen` (ParseBench 2,079 docs + DP-Bench 200 PDFs, one job so model loads are paid once) and
`--bench gen2` (CC-OCR table parsing: 4 x 75 images, photo/scan x English/Chinese). Official scorers run in Docker
(`bench/docker/*.Dockerfile`): ParseBench = `parse-bench` (run-llama), DP-Bench = upstage `evaluate.py`; CC-OCR tables
= TEDS from the IBM implementation vendored in OmniDocBench (`bench/gen_ccocr.py`). Converters: `bench/gen_export.py`
(run -> per-page markdown + the final reader's blocks), `bench/gen_parsebench.py`, `bench/gen_dpbench.py`.
Scorer checks: ParseBench counts missing pages as 0; DP-Bench re-scores its published sample results (Upstage etc.)
to their numbers; CC-OCR scorer gives 100 on the ground truth.

**ParseBench** (official leaderboard: data/parsebench_lb/leaderboard.csv; overall = mean of the five dimensions)

| system | Overall | Tables | Charts | Content | Formatting | Visual grounding |
|---|---|---|---|---|---|---|
| c3b as run (held-out number) | 58.5 | 84.8 | 1.1 | 85.3 | 51.1 | 70.3 |
| c3b + chart tables + title headings (new default, see below) | 72.8 | 85.1 | 61.5 | 85.0 | 62.0 | 70.3 |
| v2 as run (no boxes: grounding counts 0) | 40.8 | 77.0 | 1.2 | 85.8 | 40.1 | — |
| LightOnOCR-3-4B (leaderboard) | 75.6 | 83.6 | 66.3 | 90.1 | 68.1 | 69.8 |
| Datalab Accurate / Infinity-Parser2-Pro / Reducto Agentic | 72.9 / 71.2 / 70.9 | | | | | |
| LlamaParse Agentic Plus (leader) | 86.7 | 93.3 | 92.2 | 89.7 | 82.8 | 75.4 |

Why c3b scored low as run, all from choices made on olmOCR-Bench:
1. Charts (1.1): the system dropped every image/chart block; LightOnOCR-3 writes a chart's data into that block as an
   HTML table. Keeping visual blocks whose text is an HTML table: olmOCR-Bench identical failing tests (87.2),
   OmniDoc 87.94 -> 88.08, ParseBench charts 61.5. Keeping all visual blocks (descriptions too): OmniDoc 88.02.
2. Formatting (51.1): Infinity-Pro pages (86 of 476 text pages) scored 2.2 — its doc2json text has no markdown, the
   category carries it. Rendering title blocks as '#' headings: formatting 62.0, olmOCR-Bench 87.2, OmniDoc 88.08 (no
   change). Also wrapping formula blocks in $$: same ParseBench gain but olmOCR-Bench 86.9 (old_scans_math -1.6) and
   OmniDoc 87.73, so titles only.
3. Content faithfulness (85.3 vs LightOn's 90.1): ParseBench counts page headers/footers as content; olmOCR-Bench
   penalises them. Keeping margin blocks: content 89.2 (overall ~73.6). A real convention conflict, left as is
   (product option, not a default flip per benchmark).
Adopted 1 + 2 as the default in `grounding_to_md` (`legacy=True` reproduces the old output; the new default reproduces
the offline variant on all 1,403 olmOCR pages). The ParseBench held-out number is 58.5; 72.8 is after a fix
informed by ParseBench, verified not to cost anything on the other two benchmarks.
Remaining gap to LightOnOCR-3-4B alone (75.6): headers (above), charts (65 vs 61) and formatting (68 vs 62; their
adapter also converts markdown tables to HTML, fences code, etc.). The c3b cascade's olmOCR-Bench lead does not
carry over to ParseBench.

**DP-Bench** (200 pages; NID = reading-order text similarity incl. headers/footers; tables TEDS)

| system | NID | TEDS | TEDS-S | Table F1 |
|---|---|---|---|---|
| c3b | 0.920 | 0.955 | 0.971 | 0.946 |
| v2 | 0.937 | 0.948 | 0.962 | **0.973** |
| Upstage (enhanced / standard) | 0.966 / 0.963 | 0.956 / 0.961 | 0.976 / 0.973 | 0.898 / 0.906 |
| AWS | 0.960 | 0.955 | 0.970 | 0.690 |
| Unstructured / Microsoft / Google / LlamaParse | 0.918 / 0.870 / 0.822 / 0.905 | 0.803 / 0.779 / 0.783 / 0.907 | | |
(published sample results, re-scored with the same scorer.) Tables are at the level of the best commercial APIs;
NID is lower mainly because both systems drop headers/footers, which DP-Bench's ground truth includes.

**CC-OCR table parsing** (300 images; TEDS / TEDS-S, all subsets)

| system | all | photo zh | photo en | scan zh | scan en |
|---|---|---|---|---|---|
| c3b | 58.4 / 89.4 | 53.7 / 92.0 | 58.9 / 86.7 | 57.8 / 87.2 | 63.1 / 91.6 |
| v2 | 58.9 / 89.6 | 54.6 / 90.5 | 58.0 / 85.9 | 58.8 / 88.9 | 64.2 / 93.0 |
Structure is good (TEDS-S ~89); content TEDS is pulled down by notation (we write LaTeX `$\sigma_{acc}$`, the
ground truth uses Unicode + `<sub>`) and empty vs merged header cells. No other system scored in this harness, so this
only compares our two systems (equal).

Modal spend for this round (GPU list price): gen c3b $3.28 (L40S 61 min + H200 17 min), gen v2 $1.77, gen2 c3b $1.30,
gen2 v2 $0.56 = ~$6.9 (+ CPU/memory, ~$7.5). Cumulative ~$13.5 of the $30 credit. Azure: 5 OmniDoc scorings (VM
deallocated after each).

### 2026-11-07 — page headers/footers: now an option (`--keep-margins`), default unchanged
`pipeline.py` / `reread.py --keep-margins` (Modal: `--keep-margins`, run name gets `_km`): keeps page-margin text
blocks (header, footer, page number, side note, page footnote) and skips the PP-DocLayoutV3 margin-region drop / mask.
Default stays drop. Measured offline from the same raw outputs (c3b, current default rules otherwise):

| | olmOCR-Bench | ParseBench overall (content) | DP-Bench NID / TEDS |
|---|---|---|---|
| drop margins (default) | **87.2** (headers_footers 96.3) | 72.8 (85.0) | 0.920 / 0.955 |
| `--keep-margins` | 77.2 (headers_footers 20.9) | **74.1** (90.2) | **0.956** / 0.955 |

So: drop for olmOCR-style "body text only" output (RAG over document content), keep for faithful full-page
transcription. With margins kept c3b is 74.1 on ParseBench (LightOnOCR-3-4B alone 75.6: remaining gap is charts and
formatting) and 0.956 NID on DP-Bench (Upstage 0.966, AWS 0.960).
