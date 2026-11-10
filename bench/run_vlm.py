"""Run a single-pass vision model over olmOCR-Bench PDFs via an OpenAI-compatible server (vLLM).

Writes <out_dir>/<category>/<name>_pg1_repeat1.md for every PDF (empty file on failure, so the
scorer never zeroes a whole candidate) and <out_dir>/_run_stats.json with timing + token counts.

Presets hold everything model-specific: prompt, render size, sampling and output clean-up.
"""

import argparse
import asyncio
import base64
import glob
import io
import json
import os
import re
import threading
import time

import httpx
import pypdfium2 as pdfium

OVIS_PROMPT = (
    "\nExtract all readable content from the image in natural human reading order and output the result as a "
    "single Markdown document. For charts or images, represent them using an HTML image tag: "
    '<img src="images/bbox_{left}_{top}_{right}_{bottom}.jpg" />, where left, top, right, bottom are bounding box '
    "coordinates scaled to [0, 1000). Format formulas as LaTeX. Format tables as HTML: <table>...</table>. "
    "Transcribe all other text as standard Markdown. Preserve the original text without translation or paraphrasing."
)


def strip_ovis(text: str) -> str:
    # Model card's default: drop image placeholder tags for visual regions.
    return "\n\n".join(b for b in text.split("\n\n") if not b.strip().startswith('<img src="images/bbox_'))


PRESETS = {
    "ovisocr2": {
        "model": "ovis",
        "prompt": OVIS_PROMPT,
        "longest_dim": 2048,
        "max_tokens": 16384,
        "temperature": 0.0,
        "clean": strip_ovis,
    },
}


# pdfium is not thread-safe: concurrent renders crash with 'double free or corruption'.
_PDFIUM_LOCK = threading.Lock()


def render_png_b64(pdf_path: str, longest_dim: int) -> str:
    with _PDFIUM_LOCK:
        return _render_png_b64(pdf_path, longest_dim)


def _render_png_b64(pdf_path: str, longest_dim: int) -> str:
    pdf = pdfium.PdfDocument(pdf_path)
    page = pdf[0]
    w, h = page.get_size()
    scale = longest_dim / max(w, h)
    img = page.render(scale=scale).to_pil()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    pdf.close()
    return base64.b64encode(buf.getvalue()).decode()


def looks_repetitive(text: str) -> bool:
    tail = text[-2000:]
    return bool(re.search(r"(.{8,80}?)\1{10,}", tail, re.S))


async def ocr_one(client, endpoint, preset, pdf_path, stats):
    image_b64 = await asyncio.to_thread(render_png_b64, pdf_path, preset["longest_dim"])
    temps = [preset["temperature"], 0.2, 0.4]
    text = ""
    for attempt, temp in enumerate(temps):
        req = {
            "model": preset["model"],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                        {"type": "text", "text": preset["prompt"]},
                    ],
                }
            ],
            "max_tokens": preset["max_tokens"],
            "temperature": temp,
        }
        try:
            r = await client.post(f"{endpoint}/chat/completions", json=req)
            r.raise_for_status()
            data = r.json()
        except Exception as e:  # noqa: BLE001
            stats["errors"] += 1
            print(f"error {pdf_path} attempt {attempt}: {e}")
            continue
        choice = data["choices"][0]
        usage = data.get("usage") or {}
        stats["prompt_tokens"] += usage.get("prompt_tokens", 0)
        stats["completion_tokens"] += usage.get("completion_tokens", 0)
        stats["requests"] += 1
        text = choice["message"]["content"] or ""
        if choice.get("finish_reason") == "stop" and not looks_repetitive(text):
            break
        stats["retries"] += 1
    return preset["clean"](text)


async def main_async(args):
    preset = PRESETS[args.preset]
    pdfs = sorted(glob.glob(os.path.join(args.pdf_dir, "**", "*.pdf"), recursive=True))
    if args.limit:
        pdfs = pdfs[: args.limit]
    stats = {"pages": len(pdfs), "requests": 0, "retries": 0, "errors": 0, "prompt_tokens": 0, "completion_tokens": 0}
    sem = asyncio.Semaphore(args.concurrency)
    done = 0

    async with httpx.AsyncClient(timeout=900) as client:

        async def worker(pdf):
            nonlocal done
            rel = os.path.relpath(pdf, args.pdf_dir)
            out = os.path.join(args.out_dir, os.path.splitext(rel)[0] + "_pg1_repeat1.md")
            if os.path.exists(out) and not args.force:
                done += 1
                return
            async with sem:
                md = await ocr_one(client, args.endpoint.rstrip("/"), preset, pdf, stats)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                f.write(md)
            done += 1
            if done % 50 == 0:
                print(f"{done}/{len(pdfs)} pages, {time.time() - t0:.0f}s", flush=True)

        t0 = time.time()
        await asyncio.gather(*(worker(p) for p in pdfs))
        stats["inference_seconds"] = round(time.time() - t0, 1)

    stats["pages_per_second"] = round(stats["pages"] / max(stats["inference_seconds"], 1e-9), 3)
    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "_run_stats.json"), "w") as f:
        json.dump(stats, f, indent=2)
    print(json.dumps(stats, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", required=True, choices=sorted(PRESETS))
    ap.add_argument("--pdf-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--endpoint", default="http://localhost:8000/v1")
    ap.add_argument("--concurrency", type=int, default=64)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
