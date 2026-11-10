#!/usr/bin/env bash
# Runs ON the RunPod pod (inside vllm/vllm-openai). Usage: bash job.sh <model_key>
# Serves the model with vLLM, OCRs every olmOCR-Bench PDF with that model's own harness,
# and leaves /workspace/out_<model_key>.tar.gz plus /workspace/DONE_<model_key>.
set -euo pipefail
KEY="$1"
W=/workspace
CODE=$W/code
BENCH=$W/bench_data
OUT=$W/out/$KEY
LOG=$W/job_$KEY.log
exec > >(tee -a "$LOG") 2>&1

echo "== setup $(date -u +%FT%TZ)"
export DEBIAN_FRONTEND=noninteractive HF_HUB_ENABLE_HF_TRANSFER=0
apt-get update -qq && apt-get install -y -qq poppler-utils curl >/dev/null
python3 -m pip install -q huggingface_hub pypdfium2 httpx
if [ ! -d "$BENCH/pdfs" ]; then
  python3 - <<EOF
from huggingface_hub import snapshot_download
import shutil, os
p = snapshot_download("allenai/olmOCR-bench", repo_type="dataset", allow_patterns=["bench_data/pdfs/**"])
shutil.copytree(os.path.join(p, "bench_data"), "$BENCH", dirs_exist_ok=True)
EOF
fi
echo "pdfs: $(find $BENCH/pdfs -name '*.pdf' | wc -l)"
OMNI=$W/omni
if [[ "$KEY" == omni_* ]] && [ ! -d "$OMNI/images" ]; then
  python3 - <<EOF2
from huggingface_hub import snapshot_download
import shutil, os
p = snapshot_download("opendatalab/OmniDocBench", repo_type="dataset", allow_patterns=["images/**"])
shutil.copytree(os.path.join(p, "images"), "$OMNI/images", dirs_exist_ok=True)
EOF2
  echo "omni images: $(ls $OMNI/images | wc -l)"
fi

# v2 end to end on one GPU: stage 1 (layout + OvisOCR2 mask, with confidence), swap the vLLM model,
# stage 2 (LightOnOCR-3-4B re-reads the least-confident V2_FRAC of pages). Needs the vLLM >= 0.30 image.
if [[ "$KEY" == v2 || "$KEY" == omni_v2 ]]; then
  python3 -m pip install -q opencv-python-headless
  python3 -c "from transformers import PPDocLayoutV3ForObjectDetection" 2>/dev/null || python3 -m pip install -q -U "transformers>=5.2"
  # olmOCR-Bench penalises page headers/footers: drop them there (--drop-margins), keep them elsewhere (the default).
  if [ "$KEY" = omni_v2 ]; then SRC=$OMNI/images; NAMES=--plain-names; else SRC=$BENCH/pdfs; NAMES=--drop-margins; fi
  serve() {  # serve <log> <vllm args...>; returns once the server answers
    local log=$1; shift
    pkill -f "vllm serve" 2>/dev/null || true
    for i in $(seq 1 30); do pgrep -f "vllm serve" >/dev/null || break; sleep 2; done
    pkill -9 -f "vllm serve" 2>/dev/null || true
    vllm serve "$@" --port 8000 > $log 2>&1 &
    VLLM_PID=$!
    for i in $(seq 1 180); do
      curl -sf localhost:8000/v1/models >/dev/null && return 0
      kill -0 $VLLM_PID 2>/dev/null || { echo "vLLM died"; tail -50 $log; exit 1; }
      sleep 5
    done
    echo "vLLM not ready"; tail -50 $log; exit 1
  }
  trap 'pkill -f "vllm serve" 2>/dev/null || true' EXIT
  mkdir -p "$OUT"; cd $CODE
  T0=$(date +%s)
  serve $W/vllm_${KEY}_ovis.log ATH-MaaS/OvisOCR2 --served-model-name ovis --max-model-len 20000 \
    --gpu-memory-utilization 0.65 --limit-mm-per-prompt '{"image":1}' \
    --mm-processor-kwargs '{"min_pixels":200704,"max_pixels":8294400}'
  T1=$(date +%s)
  python3 -m docengine.pipeline --mode mask --pdf-dir $SRC --out-dir "$OUT" $NAMES --concurrency 128 \
    --layout-batch 4 ${PIPE_LIMIT:+--limit $PIPE_LIMIT}
  T2=$(date +%s)
  serve $W/vllm_${KEY}_lighton.log lightonai/LightOnOCR-3-4B --served-model-name lighton --trust-remote-code \
    --gpu-memory-utilization 0.9 --limit-mm-per-prompt '{"image":1}' --max-model-len 24576 \
    --default-chat-template-kwargs '{"enable_thinking": false}'
  T3=$(date +%s)
  python3 -m docengine.reread --run-dir "$OUT" --pdf-dir $SRC $NAMES --frac ${V2_FRAC:-0.1}
  T4=$(date +%s)
  NPAGES=$(python3 -c "import json;print(json.load(open('$OUT/_run_stats.json'))['pages'])")
  GPU=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)
  printf '{"model_key": "%s", "gpu": "%s", "pages": %s, "ovis_load_seconds": %s, "stage1_seconds": %s, "lighton_load_seconds": %s, "stage2_seconds": %s, "inference_seconds": %s, "wall_seconds": %s}\n' \
    "$KEY" "$GPU" $NPAGES $((T1 - T0)) $((T2 - T1)) $((T3 - T2)) $((T4 - T3)) $((T2 - T1 + T4 - T3)) $((T4 - T0)) > "$OUT/_timing.json"
  cat "$OUT/_timing.json"
  cp $W/vllm_${KEY}_ovis.log "$OUT/_vllm_ovis.log"; cp $W/vllm_${KEY}_lighton.log "$OUT/_vllm_lighton.log"
  tar -czf $W/out_$KEY.tar.gz -C $W/out "$KEY"
  pkill -f "vllm serve" 2>/dev/null || true
  touch $W/DONE_$KEY
  echo "== done $(date -u +%FT%TZ)"
  exit 0
fi

case "$KEY" in
  olmocr2)
    python3 -m pip install -q -e "$CODE/vendor/olmocr"
    SERVE=() ;;
  chandra2)
    python3 -m pip install -q -e "$CODE/vendor/chandra" unicodeit
    SERVE=(datalab-to/chandra-ocr-2 --served-model-name chandra --dtype bfloat16 --max-model-len 18000
           --gpu-memory-utilization 0.85 --enable-prefix-caching --max-num-seqs ${CHANDRA_SEQS:-96}
           --mm-processor-kwargs '{"min_pixels":3136,"max_pixels":6291456}') ;;
  ovisocr2)
    SERVE=(ATH-MaaS/OvisOCR2 --served-model-name ovis --max-model-len 20000
           --gpu-memory-utilization 0.85 --limit-mm-per-prompt '{"image":1}'
           --mm-processor-kwargs '{"min_pixels":200704,"max_pixels":8294400}') ;;
  pipe_mask|pipe_regions|omni_plain|omni_mask|pipe_mask_lp|omni_plain_lp|omni_mask_lp)
    python3 -m pip install -q opencv-python-headless
    python3 -c "from transformers import PPDocLayoutV3ForObjectDetection" 2>/dev/null || python3 -m pip install -q -U "transformers>=5.2"
    # Leave GPU memory for the layout model running alongside vLLM.
    SERVE=(ATH-MaaS/OvisOCR2 --served-model-name ovis --max-model-len 20000
           --gpu-memory-utilization 0.65 --limit-mm-per-prompt '{"image":1}'
           --mm-processor-kwargs '{"min_pixels":200704,"max_pixels":8294400}') ;;
  olm2_plain|omni_olm2_plain)
    # Strong-reader ceiling test: olmOCR-2 (7B, FP8, Apache-2.0) through our pipeline, same flags as olmocr.pipeline.
    python3 -m pip install -q opencv-python-headless
    python3 -c "from transformers import PPDocLayoutV3ForObjectDetection" 2>/dev/null || python3 -m pip install -q -U "transformers>=5.2"
    SERVE=(allenai/olmOCR-2-7B-1025-FP8 --served-model-name olmocr --max-model-len 16384
           --gpu-memory-utilization 0.9 --limit-mm-per-prompt '{"video":0}') ;;
  lt08|omni_lt08|lt4|omni_lt4)
    # LightOnOCR-3 (Apache-2.0), served as in its repo's benchmarks/ocr_bench/config.py (needs vLLM >= 0.30).
    case "$KEY" in *lt08) LT=lightonai/LightOnOCR-3-0.8B ;; *) LT=lightonai/LightOnOCR-3-4B ;; esac
    SERVE=($LT --served-model-name lighton --trust-remote-code --gpu-memory-utilization 0.9
           --limit-mm-per-prompt '{"image":1}' --max-model-len 24576
           --default-chat-template-kwargs '{"enable_thinking": false}') ;;
  inf_flash|omni_inf_flash|inf_pro|omni_inf_pro|omni_inf_pro_sub)
    # Infinity-Parser2 (Apache-2.0), flags from their README's vllm serve command (TP=1 here). Pro (35B-A3B MoE,
    # 70 GB bf16) runs unquantised on a 96 GB GPU (INF_QUANT=fp8 for smaller Hopper/Ada cards).
    case "$KEY" in
      *flash) INF=infly/Infinity-Parser2-Flash; Q=(--max-num-batched-tokens 32768) ;;
      *) INF=infly/Infinity-Parser2-Pro; Q=(--max-num-batched-tokens 16384 --max-num-seqs 128 ${INF_QUANT:+--quantization $INF_QUANT}) ;;
    esac
    SERVE=($INF --served-model-name infinity --trust-remote-code "${Q[@]}"
           --default-chat-template-kwargs '{"enable_thinking": false}' --chat-template-content-format openai
           --gpu-memory-utilization 0.92 --max-model-len 32768
           --limit-mm-per-prompt '{"image":1}' --enable-prefix-caching) ;;
  *) echo "unknown model $KEY"; exit 1 ;;
esac

if [ ${#SERVE[@]} -gt 0 ]; then
echo "== starting vLLM $(date -u +%FT%TZ)"
# Never talk to a server left over from an earlier (failed) job.
pkill -f "vllm serve" 2>/dev/null || true
for i in $(seq 1 30); do pgrep -f "vllm serve" >/dev/null || break; sleep 2; done
pkill -9 -f "vllm serve" 2>/dev/null || true
vllm serve "${SERVE[@]}" --port 8000 > $W/vllm_$KEY.log 2>&1 &
VLLM_PID=$!
trap 'kill $VLLM_PID 2>/dev/null || true' EXIT
for i in $(seq 1 180); do
  curl -sf localhost:8000/v1/models >/dev/null && break
  kill -0 $VLLM_PID 2>/dev/null || { echo "vLLM died"; tail -50 $W/vllm_$KEY.log; exit 1; }
  sleep 5
done
curl -sf localhost:8000/v1/models >/dev/null || { echo "vLLM not ready"; tail -50 $W/vllm_$KEY.log; exit 1; }
echo "== vLLM ready $(date -u +%FT%TZ)"
fi

mkdir -p "$OUT"
run_inference() {
case "$KEY" in
  olmocr2)
    # Official olmOCR pipeline, hosting its own vLLM (port 30024), then convert to bench layout.
    python3 -m olmocr.pipeline $W/olm_ws --markdown --workers 32 --pdfs $BENCH/pdfs/**/*.pdf
    python3 $CODE/vendor/olmocr/olmocr/bench/scripts/workspace_to_bench.py $W/olm_ws "$OUT" --bench-path $W ;;
  chandra2)
    # Datalab's own reproduction script (renders at 300 DPI, applies their published post-processing).
    mkdir -p $W/chandra_bench && ln -sfn $BENCH/pdfs $W/chandra_bench/pdfs
    python3 -m chandra.scripts.olmocr_bench --bench-dir $W/chandra_bench --candidate chandra \
      --workers ${CHANDRA_SEQS:-96} --skip-scoring --vllm-api-base http://localhost:8000/v1
    cp -r $W/chandra_bench/chandra/. "$OUT"/ ;;
  omni_plain|omni_mask|omni_plain_lp|omni_mask_lp)
    M=${KEY#omni_}; M=${M%_lp}
    cd $CODE && python3 -m docengine.pipeline --mode $M --pdf-dir $OMNI/images --out-dir "$OUT" \
      --plain-names --concurrency 128 --layout-batch 4 ;;
  pipe_mask|pipe_regions|pipe_mask_lp)
    M=${KEY#pipe_}; M=${M%_lp}
    cd $CODE && python3 -m docengine.pipeline --mode $M --pdf-dir $BENCH/pdfs --drop-margins --out-dir "$OUT" \
      --concurrency 128 --layout-batch 4 ${PIPE_LIMIT:+--limit $PIPE_LIMIT} ;;
  olm2_plain)
    cd $CODE && python3 -m docengine.pipeline --mode plain --reader olmocr2 --model olmocr --pdf-dir $BENCH/pdfs --drop-margins \
      --out-dir "$OUT" --concurrency ${OLM_CONC:-64} ${PIPE_LIMIT:+--limit $PIPE_LIMIT} ;;
  omni_olm2_plain)
    cd $CODE && python3 -m docengine.pipeline --mode plain --reader olmocr2 --model olmocr --pdf-dir $OMNI/images \
      --out-dir "$OUT" --plain-names --concurrency ${OLM_CONC:-64} ${PIPE_LIMIT:+--limit $PIPE_LIMIT} ;;
  lt08|lt4)
    cd $CODE && python3 -m docengine.pipeline --mode plain --reader lighton --model lighton --pdf-dir $BENCH/pdfs --drop-margins \
      --out-dir "$OUT" --concurrency ${LT_CONC:-128} ${PIPE_LIMIT:+--limit $PIPE_LIMIT} ;;
  omni_lt08|omni_lt4)
    cd $CODE && python3 -m docengine.pipeline --mode plain --reader lighton --model lighton --pdf-dir $OMNI/images \
      --out-dir "$OUT" --plain-names --concurrency ${LT_CONC:-128} ${PIPE_LIMIT:+--limit $PIPE_LIMIT} ;;
  inf_flash|inf_pro)
    cd $CODE && python3 -m docengine.pipeline --mode plain --reader infinity --model infinity --pdf-dir $BENCH/pdfs --drop-margins \
      --out-dir "$OUT" --concurrency ${INF_CONC:-64} ${PIPE_LIMIT:+--limit $PIPE_LIMIT} ;;
  omni_inf_flash|omni_inf_pro|omni_inf_pro_sub)
    # _sub: only the OmniDocBench pages the Pro cascades re-read (list built from LightOn's own confidence).
    cd $CODE && python3 -m docengine.pipeline --mode plain --reader infinity --model infinity --pdf-dir $OMNI/images \
      --out-dir "$OUT" --plain-names --concurrency ${INF_CONC:-64} ${PIPE_LIMIT:+--limit $PIPE_LIMIT} \
      $([ "$KEY" = omni_inf_pro_sub ] && echo --only $CODE/docengine/lists/omni_pro_sub.txt) ;;
  ovisocr2)
    python3 $CODE/bench/run_vlm.py --preset ovisocr2 --pdf-dir $BENCH/pdfs --out-dir "$OUT" --concurrency 128 ;;
esac
}
T0=$(date +%s)
run_inference &
INF_PID=$!
if [ "$KEY" = olmocr2 ]; then
  # Start the clock when the pipeline's own server answers, so model load time isn't billed as inference.
  for i in $(seq 1 240); do curl -sf localhost:30024/v1/models >/dev/null && break; kill -0 $INF_PID 2>/dev/null || break; sleep 5; done
  T0=$(date +%s); echo "== olmocr server ready $(date -u +%FT%TZ)"
fi
# Watchdog: if our vLLM dies mid-run, stop instead of retrying against a dead server.
while kill -0 $INF_PID 2>/dev/null; do
  if [ -n "${VLLM_PID:-}" ] && ! kill -0 $VLLM_PID 2>/dev/null; then
    echo "vLLM died during inference"; tail -40 $W/vllm_$KEY.log; kill $INF_PID; exit 1
  fi
  sleep 10
done
wait $INF_PID
T1=$(date +%s)

GPU=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)
NPAGES=$(python3 -c "import json;print(json.load(open('$OUT/_run_stats.json'))['pages'])" 2>/dev/null || find $BENCH/pdfs -name '*.pdf' | wc -l)
NOUT=$(find "$OUT" -name '*.md' | wc -l)
cat > "$OUT/_timing.json" <<EOF
{"model_key": "$KEY", "gpu": "$GPU", "pages": $NPAGES, "md_files": $NOUT, "inference_seconds": $((T1 - T0))}
EOF
cat "$OUT/_timing.json"
cp $W/vllm_$KEY.log "$OUT/_vllm.log" 2>/dev/null || true
tar -czf $W/out_$KEY.tar.gz -C $W/out "$KEY"
kill ${VLLM_PID:-} 2>/dev/null || true
touch $W/DONE_$KEY
echo "== done $(date -u +%FT%TZ)"
