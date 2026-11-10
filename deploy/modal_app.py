"""docengine on Modal: the c3b cascade (and v2) end to end, billed per second.

  .venv/bin/modal run deploy/modal_app.py::prep                          # once: benchmark data -> volume
  .venv/bin/modal run deploy/modal_app.py --bench olmocr --system c3b [--limit 20] [--run NAME]
  .venv/bin/modal volume get docengine-data out/<run> results/<run>      # pull outputs back

c3b: LightOnOCR-3-0.8B on every page (blocks in layout margin regions dropped) -> LightOnOCR-3-4B re-reads the 20% of
pages 0.8B is least confident about -> Infinity-Parser2-Pro re-reads the 10% (of all pages) 4B is least confident
about. Stages 1-2 run on one L40S (model swap in between), stage 3 on an H200 (Pro in bf16, as benchmarked).
v2: layout + OvisOCR2 mask -> LightOnOCR-3-4B re-reads OvisOCR2's least-confident 10%, all on one L40S.

Everything lives on the `docengine-data` volume: /data/hf (model cache), /data/bench, /data/omni (inputs),
/data/out/<run> (markdown + _pages/_layout/_reread logs + _timing.json).
"""
import json
import os
import subprocess
import time

import modal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VLLM_IMAGE = "vllm/vllm-openai:v0.30.0"
REV = {  # Hugging Face revisions we benchmarked (DEPLOY.md)
    "lightonai/LightOnOCR-3-0.8B": "36d8636925327c671bd8e479c517a004f7566bd9",
    "lightonai/LightOnOCR-3-4B": "b71010f095dc3735de7ee6b9969bff8f8f50b39a",
    "infly/Infinity-Parser2-Pro": "b27d470100514329fc6439aada8f16ccea5f9e2a",
    "ATH-MaaS/OvisOCR2": "cbdede82e048659b83310476ff807da825f8fe78",
}

image = (
    modal.Image.from_registry(VLLM_IMAGE, setup_dockerfile_commands=[
        "RUN ln -sf $(command -v python3) /usr/local/bin/python"])  # vLLM image ships python3 only
    .entrypoint([])
    .pip_install("pypdfium2", "httpx", "opencv-python-headless", "huggingface_hub", "transformers>=5.2", "rapidfuzz")
    .env({"HF_HOME": "/data/hf", "HF_HUB_ENABLE_HF_TRANSFER": "0", "PYTHONPATH": "/root/code"})
    .add_local_dir(os.path.join(ROOT, "docengine"), "/root/code/docengine", ignore=["__pycache__"])
)
vol = modal.Volume.from_name("docengine-data", create_if_missing=True)
app = modal.App("docengine", image=image)

LIGHTON = ["--served-model-name", "lighton", "--trust-remote-code", "--limit-mm-per-prompt", '{"image":1}',
           "--max-model-len", "24576", "--default-chat-template-kwargs", '{"enable_thinking": false}']
PRO = ["--served-model-name", "infinity", "--trust-remote-code",
       "--default-chat-template-kwargs", '{"enable_thinking": false}', "--chat-template-content-format", "openai",
       "--gpu-memory-utilization", "0.92", "--max-model-len", "32768", "--max-num-batched-tokens", "16384",
       "--max-num-seqs", "128", "--limit-mm-per-prompt", '{"image":1}', "--enable-prefix-caching"]
OVIS = ["--served-model-name", "ovis", "--max-model-len", "20000", "--gpu-memory-utilization", "0.65",
        "--limit-mm-per-prompt", '{"image":1}', "--mm-processor-kwargs", '{"min_pixels":200704,"max_pixels":8294400}']


class Server:
    """vllm serve <model> on :8000 for the duration of a `with` block."""

    def __init__(self, model, args, log):
        self.cmd = ["vllm", "serve", model, "--revision", REV[model], "--port", "8000", *args]
        self.log = log

    def __enter__(self):
        t0 = time.time()
        self.p = subprocess.Popen(self.cmd, stdout=open(self.log, "w"), stderr=subprocess.STDOUT)
        import httpx
        while True:
            if self.p.poll() is not None:
                raise RuntimeError("vLLM died:\n" + open(self.log).read()[-4000:])
            try:
                if httpx.get("http://localhost:8000/v1/models", timeout=2).status_code == 200:
                    break
            except Exception:  # noqa: BLE001
                pass
            if time.time() - t0 > 1800:
                raise RuntimeError("vLLM not ready after 30 min")
            time.sleep(5)
        self.load_seconds = round(time.time() - t0, 1)
        return self

    def __exit__(self, *exc):
        self.p.terminate()
        try:
            self.p.wait(60)
        except subprocess.TimeoutExpired:
            self.p.kill()


def sh(*args):
    print("+", " ".join(args), flush=True)
    subprocess.run(args, check=True, cwd="/root/code")


def src_of(bench):
    # gen: generalisation set (ParseBench docs + DP-Bench PDFs), uploaded with `modal volume put docengine-data data/gen gen`
    return {"olmocr": ("/data/bench/pdfs", []), "omni": ("/data/omni/images", ["--plain-names"]),
            "gen": ("/data/gen", ["--plain-names"]),
            # gen2: CC-OCR table-parsing images (photo/scan, English/Chinese), `modal volume put ... data/gen2 gen2`
            "gen2": ("/data/gen2", ["--plain-names"]),
            # rcc: random Common Crawl PDF pages (bench/random_cc.py), `modal volume put ... data/random_cc/pages rcc`
            "rcc": ("/data/rcc", ["--plain-names"]),
            # stress: synthetic dense tiny-text pages (bench/stress_gen.py), `modal volume put ... data/stress/pages stress`
            "stress": ("/data/stress", ["--plain-names"])}[bench]


def timing(out, key, **kw):
    path = os.path.join(out, "_timing.json")
    t = json.load(open(path)) if os.path.exists(path) else {}
    t.update(kw)
    json.dump(t, open(path, "w"), indent=2)
    print(key, json.dumps(t), flush=True)


@app.function(volumes={"/data": vol}, timeout=3 * 3600, cpu=8)
def prep():
    """Download olmOCR-Bench PDFs and OmniDocBench images onto the volume (once)."""
    import shutil
    from huggingface_hub import snapshot_download
    if not os.path.isdir("/data/bench/pdfs"):
        p = snapshot_download("allenai/olmOCR-bench", repo_type="dataset", allow_patterns=["bench_data/pdfs/**"])
        shutil.copytree(os.path.join(p, "bench_data"), "/data/bench", dirs_exist_ok=True)
    if not os.path.isdir("/data/omni/images"):
        p = snapshot_download("opendatalab/OmniDocBench", repo_type="dataset", allow_patterns=["images/**"])
        shutil.copytree(os.path.join(p, "images"), "/data/omni/images", dirs_exist_ok=True)
    vol.commit()
    print("pdfs", sum(len(f) for _, _, f in os.walk("/data/bench/pdfs")), "omni", len(os.listdir("/data/omni/images")))


@app.function(volumes={"/data": vol}, gpu="L40S", timeout=4 * 3600, cpu=8, memory=32768)
def c3b_stages12(run, bench, limit=0, keep_margins=False, from_run=""):
    """from_run: reuse that run's stage 1 (reader outputs + layout) instead of running it again; the stage-1
    markdown is rebuilt from the saved raw outputs exactly as stage 1 writes it."""
    src, names = src_of(bench)
    names = names + ([] if keep_margins else ["--drop-margins"])
    out = f"/data/out/{run}"
    os.makedirs(out, exist_ok=True)
    lim = ["--limit", str(limit)] if limit else []
    t0 = time.time()
    if from_run:
        vol.reload()
        sh("python3", "-m", "docengine.restage1", "--from-dir", f"/data/out/{from_run}", "--run-dir", out,
           "--pdf-dir", src, *names)
    else:
        # vLLM leaves room for the layout model that runs alongside it in stage 1.
        with Server("lightonai/LightOnOCR-3-0.8B", LIGHTON + ["--gpu-memory-utilization", "0.65"],
                    f"{out}/_vllm_lt08.log") as s:
            t1 = time.time()
            sh("python3", "-m", "docengine.pipeline", "--mode", "plain", "--reader", "lighton", "--model", "lighton",
               "--layout-drop", "--pdf-dir", src, "--out-dir", out, "--concurrency", "128", "--layout-batch", "4",
               *names, *lim)
            t2 = time.time()
        timing(out, run, gpu12="L40S", lt08_load_seconds=s.load_seconds, stage1_seconds=round(t2 - t1, 1))
    vol.commit()
    with Server("lightonai/LightOnOCR-3-4B", LIGHTON + ["--gpu-memory-utilization", "0.9"], f"{out}/_vllm_lt4.log") as s:
        t3 = time.time()
        sh("python3", "-m", "docengine.reread", "--run-dir", out, "--pdf-dir", src, *names, "--reader", "lighton",
           "--model", "lighton", "--frac", "0.2", "--tag", "lt4")
        t4 = time.time()
    timing(out, run, lt4_load_seconds=s.load_seconds, stage2_seconds=round(t4 - t3, 1),
           stages12_wall_seconds=round(time.time() - t0, 1))
    vol.commit()


@app.function(volumes={"/data": vol}, gpu="H200", timeout=3 * 3600, cpu=8, memory=65536)
def c3b_stage3(run, bench, keep_margins=False, frac=0.1, tag="pro", text_layer=True):
    src, names = src_of(bench)
    names = names + ([] if keep_margins else ["--drop-margins"])
    out = f"/data/out/{run}"
    vol.reload()
    t0 = time.time()
    with Server("infly/Infinity-Parser2-Pro", PRO, f"{out}/_vllm_pro.log") as s:
        t1 = time.time()
        sh("python3", "-m", "docengine.reread", "--run-dir", out, "--pdf-dir", src, *names, "--reader", "infinity",
           "--model", "infinity", "--frac", str(frac), "--tag", tag,
           *([] if frac >= 1 else ["--rank-by", "_reread_lt4.jsonl"]))  # frac 1: every page, not only stage-2's
        t2 = time.time()
    timing(out, run, gpu3="H200", pro_load_seconds=s.load_seconds, stage3_seconds=round(t2 - t1, 1),
           stage3_wall_seconds=round(time.time() - t0, 1))
    if text_layer:  # born-digital pages: correct spellings against the PDF's own text layer (CPU, seconds)
        t3 = time.time()
        sh("python3", "-m", "docengine.textlayer", "--run-dir", out, "--pdf-dir", src, "--out-dir", out,
           *[n for n in names if n == "--plain-names"])
        timing(out, run, textlayer_seconds=round(time.time() - t3, 1))
    vol.commit()


@app.function(volumes={"/data": vol}, gpu="L40S", timeout=4 * 3600, cpu=8, memory=32768)
def v2(run, bench, limit=0, keep_margins=False):
    src, names = src_of(bench)
    names = names + ([] if keep_margins else ["--drop-margins"])
    out = f"/data/out/{run}"
    os.makedirs(out, exist_ok=True)
    lim = ["--limit", str(limit)] if limit else []
    with Server("ATH-MaaS/OvisOCR2", OVIS, f"{out}/_vllm_ovis.log") as s:
        t1 = time.time()
        sh("python3", "-m", "docengine.pipeline", "--mode", "mask", "--pdf-dir", src, "--out-dir", out,
           "--concurrency", "128", "--layout-batch", "4", *names, *lim)
        t2 = time.time()
    timing(out, run, gpu="L40S", ovis_load_seconds=s.load_seconds, stage1_seconds=round(t2 - t1, 1))
    with Server("lightonai/LightOnOCR-3-4B", LIGHTON + ["--gpu-memory-utilization", "0.9"], f"{out}/_vllm_lt4.log") as s:
        t3 = time.time()
        sh("python3", "-m", "docengine.reread", "--run-dir", out, "--pdf-dir", src, *names, "--frac", "0.1")
        t4 = time.time()
    timing(out, run, lt4_load_seconds=s.load_seconds, stage2_seconds=round(t4 - t3, 1))
    vol.commit()


@app.local_entrypoint()
def main(bench: str = "olmocr", system: str = "c3b", limit: int = 0, run: str = "", skip12: bool = False,
         keep_margins: bool = False, drop_margins: bool = False, pro_frac: float = 0.1, pro_tag: str = "pro",
         from_run: str = "", no_text_layer: bool = False):
    """--from-run R: reuse run R's stage 1 (saves the stage-1 GPU time when only later stages changed).
    --no-text-layer: skip the final text-layer correction.
    --pro-frac/--pro-tag: share of pages Infinity-Pro re-reads (experiments; default 0.1) and its output tag.
    Page headers/footers/page numbers are kept, except on olmOCR-Bench, whose tests penalise them (its convention);
    --keep-margins / --drop-margins override that either way."""
    keep = keep_margins or (not drop_margins and bench != "olmocr")
    run = run or f"modal_{system}_{bench}" + (f"_n{limit}" if limit else "") + \
        ("_km" if keep and bench == "olmocr" else "_dm" if not keep and bench != "olmocr" else "")
    if system == "v2":
        v2.remote(run, bench, limit, keep)
    else:
        if not skip12:
            c3b_stages12.remote(run, bench, limit, keep, from_run)
        c3b_stage3.remote(run, bench, keep, pro_frac, pro_tag, not no_text_layer)
    print(f"done: modal volume get docengine-data out/{run} results/{run}")
