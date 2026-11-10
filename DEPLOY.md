# Running docengine

Two systems are worth deploying:

| System | olmOCR-Bench | OmniDocBench* | GPU | $ / 1k pages (GPU only) | Status |
|---|---|---|---|---|---|
| **v2**: layout + OvisOCR2 on every page, LightOnOCR-3-4B re-reads the least-confident 10% | 84.6 | **92.3** | 1 × RTX 4090 | 0.26–0.31 measured (0.32–0.34 incl. model loads) | Runnable end to end |
| **c3b** (best olmOCR-Bench): LightOnOCR-3-0.8B on every page, 4B re-reads the least-confident 20%, Infinity-Parser2-Pro re-reads the least-confident 10% | **87.2** | 87.9 | L40S + H200 (Modal) | 0.90–1.41 measured on Modal (1.33–1.72 incl. loads); ~0.45–0.69 at RunPod prices | Runnable end to end on Modal |

\* Our OmniDocBench "overall" excludes the CDM formula metric; only comparable between our own runs.

Limits today: page 1 of each PDF only (both benchmarks are single-page); batch over a folder, no HTTP API; no
multi-page reassembly. Every model is Apache-2.0 (PP-DocLayoutV3, OvisOCR2, LightOnOCR-3, Infinity-Parser2).

## Pinned versions

| Component | Hugging Face id | Revision we benchmarked |
|---|---|---|
| Layout | PaddlePaddle/PP-DocLayoutV3_safetensors | e4f489dc536556fc1be02b973ba06756e0d4a2ac |
| Reader (v2 stage 1) | ATH-MaaS/OvisOCR2 | cbdede82e048659b83310476ff807da825f8fe78 |
| Re-reader (v2 stage 2) / c3b stage 2 | lightonai/LightOnOCR-3-4B | b71010f095dc3735de7ee6b9969bff8f8f50b39a |
| c3b stage 1 | lightonai/LightOnOCR-3-0.8B | 36d8636925327c671bd8e479c517a004f7566bd9 |
| c3b stage 3 | infly/Infinity-Parser2-Pro | b27d470100514329fc6439aada8f16ccea5f9e2a |
| Serving | vllm/vllm-openai:v0.30.0 (Docker) | LightOnOCR-3 and Infinity-Parser2 need vLLM >= 0.30 |

Add `--revision <sha>` to each `vllm serve` below to pin the weights. The client deps are in `requirements.txt`.

## v2 on one RTX 4090 (24 GB)

Inside `vllm/vllm-openai:v0.30.0` (or any box with vLLM 0.30 and `pip install -r requirements.txt`), with this repo
at `$CODE` and the PDFs (or page images) under `$IN`:

```bash
# Stage 1: layout + OvisOCR2 on every page. vLLM gets 65% of the GPU; the layout model uses the rest.
vllm serve ATH-MaaS/OvisOCR2 --served-model-name ovis --max-model-len 20000 \
  --gpu-memory-utilization 0.65 --limit-mm-per-prompt '{"image":1}' \
  --mm-processor-kwargs '{"min_pixels":200704,"max_pixels":8294400}' --port 8000 &
# wait until curl -sf localhost:8000/v1/models answers, then:
cd $CODE && python3 -m docengine.pipeline --mode mask --pdf-dir $IN --out-dir $OUT --concurrency 128 --layout-batch 4
# add --plain-names for image folders: writes <name>.md instead of <name>_pg1_repeat1.md

# Swap models.
pkill -f "vllm serve"

# Stage 2: LightOnOCR-3-4B re-reads the 10% of pages OvisOCR2 was least confident about (overwrites their .md).
vllm serve lightonai/LightOnOCR-3-4B --served-model-name lighton --trust-remote-code \
  --gpu-memory-utilization 0.9 --limit-mm-per-prompt '{"image":1}' --max-model-len 24576 \
  --default-chat-template-kwargs '{"enable_thinking": false}' --port 8000 &
cd $CODE && python3 -m docengine.reread --run-dir $OUT --pdf-dir $IN --frac 0.1
```

Output: one `.md` per page in `$OUT` (mirroring the input folder tree), plus
`_pages.jsonl` (stage-1 confidence per page), `_layout.jsonl` (layout regions), `_reread.jsonl` (which pages stage 2
replaced), `_run_stats.json` and `_reread_stats.json` (time and tokens).

Knobs
- `--frac 0.1` is a per-job budget (the 10% least confident pages of *this* job). For streaming use, `--below T`
  re-reads every page with mean token logprob < T instead. The 10% cut-off was -0.056 on olmOCR-Bench but -0.088
  on OmniDocBench, so a fixed threshold re-reads a different share per document mix.
- Reference timing on a 4090 for 1,403 pages: model load 3 min each, stage 1 925 s, stage 2 553 s.
- `runpod/job.sh v2` is the exact script we ran (key `v2` / `omni_v2`), and `runpod/launch.py v2 --image
  vllm/vllm-openai:v0.30.0` rents a RunPod 4090, runs it and pulls the outputs back.

## c3b on Modal (one command)

`deploy/modal_app.py` runs the whole cascade: stages 1-2 on an L40S, stage 3 on an H200, data and model cache on
the `docengine-data` volume. Needs `modal setup` once (token in `~/.modal.toml`).

```bash
.venv/bin/modal run deploy/modal_app.py::prep                                  # once: benchmark inputs -> volume
.venv/bin/modal run deploy/modal_app.py --bench olmocr --system c3b --limit 20  # smoke test (~$1.5 incl. loads)
.venv/bin/modal run deploy/modal_app.py --bench olmocr --system c3b            # full run (--bench omni for OmniDocBench)
.venv/bin/modal volume get docengine-data out/modal_c3b_olmocr results/        # pull outputs back
```

`--system v2` runs v2 on one L40S the same way.

**Page headers, footers, page numbers and side notes are kept by default** (since 2026-11-09). They are real content:
dates, prices, addresses. The exception is olmOCR-Bench, whose tests penalise them (87.2 with them dropped, 77.2
kept).
- The Modal entrypoint drops them for `--bench olmocr` and keeps them for every other set. `--keep-margins` /
  `--drop-margins` override either way.
- `pipeline.py`, `reread.py` and `restage1.py` keep them unless given `--drop-margins`. `runpod/job.sh` passes it for
  olmOCR-Bench keys.
- Effect elsewhere:
  - ParseBench 72.8 -> 74.1, DP-Bench NID 0.920 -> 0.956.
  - 200 random web pages: recall 92.7 -> 96.1, precision 96.7 -> 96.3 (`reports/external/`). For your own documents, copy them onto the volume
(`modal volume put docengine-data <dir> <path>`) and point `src_of()` at that path.

The stages, all label-free:

1. LightOnOCR-3-0.8B on every page: `pipeline --mode plain --reader lighton --layout-drop` (grounding blocks with
   margin labels dropped, plus blocks >= 60% inside a PP-DocLayoutV3 header/footer/number/aside region).
2. The 20% of pages with the lowest 0.8B mean token logprob are re-read by LightOnOCR-3-4B:
   `reread --reader lighton --frac 0.2 --tag lt4`.
3. Of those, the 10% (of all pages) with the lowest 4B logprob are re-read by Infinity-Parser2-Pro (their doc2json
   prompt, 300 DPI, greedy; header/footer/page_footnote dropped):
   `reread --reader infinity --model infinity --frac 0.1 --rank-by _reread_lt4.jsonl --tag pro`.
   Pro needs a GPU with >= 96 GB in bf16:

```bash
vllm serve infly/Infinity-Parser2-Pro --served-model-name infinity --trust-remote-code \
  --default-chat-template-kwargs '{"enable_thinking": false}' --chat-template-content-format openai \
  --gpu-memory-utilization 0.92 --max-model-len 32768 --max-num-batched-tokens 16384 --max-num-seqs 128 \
  --limit-mm-per-prompt '{"image":1}' --enable-prefix-caching --port 8000
```

Since 2026-11-08 (c3b2), three additions, all general (see `reports/stress/`):

- **Visibly failed pages are always re-read**, outside the 20% / 10% budgets. A page qualifies when the ranking
  stage's reading hit the output-token cap, is mostly repetition, or (born-digital PDFs) less than 60% of its
  words are in the page's own text layer (`reread.must_reread`). Use `--no-must` on `reread` for the old behaviour.
- **Dense pages are read in tiles** (`docengine/tiles.py`). When a page's previous reading, or its whole-page
  re-read, was truncated or repetitive, it is cut into ≤ 4–6 crops along the layout model's regions (same column,
  ≤ 1/4 page each) and rendered at 400 dpi. Each crop is read separately and the results are joined in reading
  order. Use `--tile never` for the old behaviour.
- **Text-layer correction** (`docengine/textlayer.py`) runs last, on the CPU. For born-digital PDFs with a visible,
  sane text layer, a word our reader got almost right takes the layer's exact spelling. The word must be aligned
  1:1 and anchored by matching neighbours. Structure, maths, table numbers and reading order are never touched. Use
  `--no-text-layer` on the Modal entrypoint to skip it.

`--from-run R` reuses run R's stage 1 (`docengine/restage1.py` rebuilds its markdown from the saved raw outputs),
which saves the stage-1 GPU time when only later stages changed.

Measured on Modal for 1,403 olmOCR-Bench pages: stage 1 869 s, stage 2 455 s (281 pages), stage 3 436 s
(140 pages); model loads 3-5 min each from the volume cache (first ever Pro load ~9 min: 70 GB download).

Things that do not work for Pro: FP8 on an A100 (missing sm80 cutlass kernel); FP8 on a 48 GB L40S (no KV-cache room
left); vLLM's default `--max-num-seqs 1024` (exceeds the Mamba-state blocks: cap at 128).

## Reproducing the benchmark numbers

- olmOCR-Bench outputs: `runpod/launch.py <key>` (keys in `runpod/job.sh`), scored locally with
  `bench/scoreboard.py <key>` (official scorer from `vendor/olmocr`, data in `data/olmOCR-bench`).
- OmniDocBench: `omni_<key>` runs, scored on an Azure CPU VM with `azure/score.sh omni_<key>` (official end-to-end
  eval minus CDM; `bench/omni/score.py`).
- Offline combinations: `bench/cascade.py`, `bench/selector.py`, `bench/consensus.py`, `bench/union_drop.py`.
- Everything we tried, with numbers and costs: `PLAN.md`. Failed cases: `failures/`.
