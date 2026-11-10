"""docengine pipeline v1: layout (PP-DocLayoutV3) -> recognition (OvisOCR2 via vLLM) -> Markdown.

Modes
  mask     Blank out header/footer/page-number/margin regions, then one OvisOCR2 pass over the page.
  regions  Crop every kept region (in the layout model's reading order), recognise each crop, join.

Usage (on a GPU box with a vLLM server for OvisOCR2 on :8000):
  python -m docengine.pipeline --mode mask --pdf-dir .../pdfs --out-dir out/ [--limit N]

Writes <out>/<category>/<name>_pg1_repeat1.md for every PDF (empty on failure), <out>/_layout.jsonl and
<out>/_run_stats.json (layout seconds, OCR seconds, requests, tokens).
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
from PIL import Image, ImageDraw

from docengine.layout import DROP_LABELS, LayoutModel
from docengine.lighton_dollars import fix_escaped_dollars

RENDER_LONGEST = 2048
OVIS_PROMPT = (
    "\nExtract all readable content from the image in natural human reading order and output the result as a "
    "single Markdown document. For charts or images, represent them using an HTML image tag: "
    '<img src="images/bbox_{left}_{top}_{right}_{bottom}.jpg" />, where left, top, right, bottom are bounding box '
    "coordinates scaled to [0, 1000). Format formulas as LaTeX. Format tables as HTML: <table>...</table>. "
    "Transcribe all other text as standard Markdown. Preserve the original text without translation or paraphrasing."
)
# olmOCR-2's own prompt (olmocr.prompts.build_no_anchoring_v4_yaml_prompt); it answers with YAML front matter + text.
OLMOCR_PROMPT = (
    "Attached is one page of a document that you must process. "
    "Just return the plain text representation of this document as if you were reading it naturally. Convert equations to LateX and tables to HTML.\n"
    "If there are any figures or charts, label them with the following markdown syntax ![Alt text describing the contents of the figure](page_startx_starty_width_height.png)\n"
    "Return your output as markdown, with a front matter section on top specifying values for the primary_language, is_rotation_valid, rotation_correction, is_table, and is_diagram parameters."
)
# Infinity-Parser2's layout-JSON prompt (infinity_parser2/prompts.py PROMPT_DOC2JSON, used by their olmOCR-Bench run).
INFINITY_PROMPT = """
- Extract layout information from the provided PDF image.
- For each layout element, output its bbox, category, and the text content within the bbox.
- Bbox format: [x1, y1, x2, y2].
- Allowed layout categories: ['header', 'title', 'text', 'figure', 'table', 'formula', 'figure_caption', 'table_caption', 'formula_caption', 'figure_footnote', 'table_footnote', 'page_footnote', 'footer'].
- Text extraction and formatting:
  1) For 'figure', the text field must be an empty string.
  2) For 'formula', format text as LaTeX.
  3) For 'table', format text as HTML.
  4) For all other categories (e.g., text, title), format text as Markdown.
- The output text must be exactly the original text from the image, with no translation or rewriting.
- Sort all layout elements in human reading order.
- Final output must be a single JSON object.
"""
# Per-reader settings, each taken from the model's own reference harness.
READERS = {
    "ovis": dict(prompt=OVIS_PROMPT, image_first=True, longest=None, temps=[0.0, 0.2, 0.4], max_tokens=16384),
    "olmocr2": dict(prompt=OLMOCR_PROMPT, image_first=False, longest=1288, temps=[0.1, 0.1, 0.2, 0.3, 0.5],
                    max_tokens=8000),
    # LightOnOCR-3 (model card + repo README): "grounding" prompt, 2048 px longest edge, temperature 0.1.
    # Every block comes back labelled; margin blocks are dropped by label instead of masked by a layout model.
    "lighton": dict(prompt="grounding", image_first=True, longest=2048, temps=[0.1, 0.2, 0.4], max_tokens=12288),
    # Infinity-Parser2 (their vllm_server backend + evaluation/olmocr-bench/infer.py): doc2json prompt, PDFs rendered at
    # 300 DPI, images sent at native size (<= 4096x4096 px), greedy decoding. Their category-specific olmOCR
    # post-processing (synonym maps / LaTeX rewriting chosen by benchmark folder) is deliberately NOT used.
    "infinity": dict(prompt=INFINITY_PROMPT, image_first=True, longest=None, dpi=300, max_pixels=4096 * 4096,
                     temps=[0.0, 0.2, 0.4], max_tokens=16384),
}
# ![label](x0,y0,x1,y1) block markers of LightOnOCR-3's grounding mode (coordinates normalised to 0-1000).
BLOCK_MARKER = re.compile(r"!\[([a-zA-Z_+]+)\]\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)[ \t]*")
# Same margin set as LightOn's own omit_margins; image/chart content is dropped like OvisOCR2's <img> tags.
GROUNDING_DROP = {"header", "footer", "page_number", "page_header", "page_footer", "header_image", "footer_image",
                  "aside_text", "image", "chart"}


def grounding_blocks(raw: str):
    ms = list(BLOCK_MARKER.finditer(raw))
    ends = [m.start() for m in ms[1:]] + [len(raw)]
    return [(m.group(1).rstrip("+"), [int(m.group(i)) for i in range(2, 6)], raw[m.end():e].strip())
            for m, e in zip(ms, ends)]


# Same set their convert_json_to_markdown drops by default, plus figures (empty text by prompt anyway).
INFINITY_DROP = {"header", "footer", "page_footnote", "figure"}
# Page-margin text (running headers/footers, page numbers, side notes, page footnotes). Kept by default since 2026-11-09
# (it is real content: dates, prices, addresses); dropped with keep_margins=False / --drop-margins, the olmOCR-Bench
# convention. Header/footer *images* stay dropped like other pictures.
MARGIN_LABELS = {"header", "footer", "page_number", "page_header", "page_footer", "aside_text", "page_footnote"}


def infinity_blocks(raw: str):
    """Infinity-Parser2 doc2json output -> [(category, [x0,y0,x1,y1] in 0-1000, text)]. A truncated array keeps every
    complete element (as their truncate_last_incomplete_element does)."""
    m = re.search(r"```json\n(.*?)(?:\n```|$)", raw, re.S)
    text = (m.group(1) if m else raw).strip()
    i = text.find("[")
    if i < 0:
        return []
    dec, pos, out = json.JSONDecoder(), i + 1, []
    while True:
        while pos < len(text) and text[pos] in " \t\r\n,":
            pos += 1
        if pos >= len(text) or text[pos] != "{":
            break
        try:
            el, pos = dec.raw_decode(text, pos)
        except json.JSONDecodeError:
            # One malformed element (e.g. a missing quote: "text": word ...) must not lose the rest of the page:
            # salvage it field by field up to the next element, then carry on.
            el, pos = _salvage(text, pos)
            if el is None:
                break
        if isinstance(el, dict):
            box = el.get("bbox")
            box = box if isinstance(box, list) and len(box) == 4 else [0, 0, 0, 0]
            out.append((str(el.get("category", "text")), box, str(el.get("text") or "").strip()))
    return out


_NEXT_EL = re.compile(r'\}\s*,\s*(?=\{\s*"(?:bbox|category|text)")')
_BBOX = re.compile(r'"bbox"\s*:\s*\[\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\]')
_CAT = re.compile(r'"category"\s*:\s*"([^"]*)"')
_TEXT = re.compile(r'"text"\s*:\s*"?(.*)', re.S)


def _salvage(text: str, pos: int):
    """Best-effort parse of a malformed element starting at text[pos] == '{'. Returns (dict, end) or (None, pos)."""
    m = _NEXT_EL.search(text, pos)
    if m:
        chunk, end = text[pos:m.start()], m.end()
    else:  # last element: only if the array is closed (a truncated last element stays dropped, as before)
        tail = text[pos:].rstrip()
        if not tail.endswith("]"):
            return None, pos
        tail = tail[:-1].rstrip()
        chunk, end = (tail[:-1] if tail.endswith("}") else tail), len(text)
    t = _TEXT.search(chunk)
    if not t:
        return None, pos
    body = t.group(1).rstrip()
    body = body[:-1] if body.endswith('"') else body
    try:
        body = json.loads('"' + body.replace('"', '\\"').replace('\\\\"', '\\"') + '"')
    except json.JSONDecodeError:
        body = body.replace("\\n", "\n").replace('\\"', '"')
    b, c = _BBOX.search(chunk), _CAT.search(chunk)
    return {"bbox": [float(v) for v in b.groups()] if b else None, "category": c.group(1) if c else "text",
            "text": body}, end


def blocks_of(reader: str, raw: str):
    return infinity_blocks(raw) if reader == "infinity" else grounding_blocks(raw)


def _inside(b, r) -> float:
    """Fraction of box b's area that lies inside box r."""
    x0, y0, x1, y1 = max(b[0], r[0]), max(b[1], r[1]), min(b[2], r[2]), min(b[3], r[3])
    return max(0, x1 - x0) * max(0, y1 - y0) / max(1e-6, (b[2] - b[0]) * (b[3] - b[1]))


_HEADING = re.compile(r"^[ \t]*#{1,6}[ \t]+")


def render_block(label: str, text: str, kinds=("title", "formula", "code")) -> str:
    """Markdown for one labelled block: add the markup its label implies when the reader left it out (title -> '#'
    heading, formula -> $$ display math, code -> fenced block), as LightOnOCR's and Infinity-Parser2's own markdown
    converters do. The system renders titles only (TITLES_ONLY): formula wrapping cost 1.6 on olmOCR-Bench old_scans_math
    and 0.35 OmniDoc overall (PLAN.md 2026-11-07, generalisation)."""
    t = text.strip()
    if "title" in kinds and label in ("title", "doc_title", "paragraph_title", "section_header") and not _HEADING.match(t):
        return "# " + t
    if "formula" in kinds and label == "formula" and not t.startswith(("$", "\\[", "\\(", "\\begin")):
        return f"$$\n{t}\n$$"
    if "code" in kinds and label == "code" and not t.startswith("```"):
        return f"```\n{t}\n```"
    return text


TITLES_ONLY = ("title",)
VISUAL_LABELS = {"image", "chart", "figure"}


def grounding_to_md(raw: str, drop=None, margins=(), size=None, reader: str = "lighton", legacy: bool = False,
                    keep_margins: bool = True) -> str:
    """Join a block-emitting reader's blocks (LightOnOCR grounding, Infinity-Parser2 JSON), dropping margin blocks by
    the model's own label and, if layout margin boxes (pixels of an image of `size`) are given, any block lying
    >= 60% inside one of them.

    Since 2026-11-07 (not legacy): an image/chart/figure block is kept when its text is an HTML table (data read off a
    chart), and title blocks get a '#' heading when the reader wrote none. Both checked on olmOCR-Bench (unchanged,
    87.2), OmniDoc (87.94 -> 88.08) and ParseBench (see PLAN.md). legacy=True reproduces the earlier behaviour.
    keep_margins=True keeps page-margin text blocks (MARGIN_LABELS) and ignores the layout margin regions."""
    blocks = blocks_of(reader, raw)
    if drop is None:
        drop = INFINITY_DROP if reader == "infinity" else GROUNDING_DROP
    if keep_margins:
        drop, margins = set(drop) - MARGIN_LABELS, ()
    if not blocks:
        if reader == "infinity":
            return "" if raw.lstrip().startswith(("[", "```json")) else raw.strip()
        return fix_escaped_dollars(raw.strip())
    keep = []
    for lab, box, t in blocks:
        if not t:
            continue
        if lab in drop and (legacy or lab not in VISUAL_LABELS or "<table" not in t):
            continue
        if margins and size:
            W, H = size
            bb = [box[0] * W / 1000, box[1] * H / 1000, box[2] * W / 1000, box[3] * H / 1000]
            if any(_inside(bb, r) >= 0.6 for r in margins):
                continue
        t = t if reader == "infinity" else fix_escaped_dollars(t)
        keep.append(t if legacy else render_block(lab, t, TITLES_ONLY))
    return "\n\n".join(keep)
FRONT_MATTER = re.compile(r"^\s*---\n(.*?)\n---\n?", re.S)
SKIP_IN_REGIONS = {"image", "chart", "seal", "formula_number"}  # no transcribable body text
IMG_TAG = re.compile(r'<img src="images/bbox_[^"]*"\s*/>')

_PDFIUM_LOCK = threading.Lock()  # pdfium is not thread-safe


IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp")


def render(pdf_path: str, dpi: int | None = None, max_pixels: int | None = None) -> Image.Image:
    """Page 1 as RGB. Default: longest edge RENDER_LONGEST. With dpi: PDFs at that DPI, images at native size;
    either way capped at max_pixels."""
    if pdf_path.lower().endswith(IMAGE_EXTS):
        img = Image.open(pdf_path).convert("RGB")
        if dpi is None and max(img.size) > RENDER_LONGEST:
            img.thumbnail((RENDER_LONGEST, RENDER_LONGEST))
        elif max_pixels and img.width * img.height > max_pixels:
            s = (max_pixels / (img.width * img.height)) ** 0.5
            img = img.resize((int(img.width * s), int(img.height * s)), Image.LANCZOS)
        return img
    with _PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(pdf_path)
        page = pdf[0]
        w, h = page.get_size()
        scale = dpi / 72 if dpi else RENDER_LONGEST / max(w, h)
        if max_pixels and w * h * scale * scale > max_pixels:
            scale = (max_pixels / (w * h)) ** 0.5
        img = page.render(scale=scale).to_pil().convert("RGB")
        pdf.close()
    return img


def layout_size(path: str, img: Image.Image, cfg: dict) -> tuple[float, float]:
    """Size of the default render (the one the layout model saw) for a page whose reader image is `img`. Block
    boxes are normalised 0-1000, so only this size matters when comparing them with layout regions."""
    if not cfg.get("dpi"):
        return float(img.width), float(img.height)
    s = RENDER_LONGEST / max(img.size) if path.lower().endswith(".pdf") else min(1.0, RENDER_LONGEST / max(img.size))
    return img.width * s, img.height * s


def b64png(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def looks_repetitive(text: str) -> bool:
    return bool(re.search(r"(.{8,80}?)\1{10,}", text[-2000:], re.S))


def clean(text: str) -> str:
    return IMG_TAG.sub("", text).strip()


class Recognizer:
    def __init__(self, endpoint: str, model: str, stats: dict, reader: str = "ovis", keep_margins: bool = True):
        self.endpoint, self.model, self.stats = endpoint.rstrip("/"), model, stats
        self.keep_margins = keep_margins
        self.reader, self.cfg = reader, READERS[reader]

    def fit(self, img: Image.Image) -> Image.Image:
        L = self.cfg["longest"]  # None: keep the page render as is (RENDER_LONGEST)
        if L and max(img.size) != L:
            s = L / max(img.size)
            img = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.LANCZOS)
        return img

    async def __call__(self, client: httpx.AsyncClient, img: Image.Image, max_tokens: int | None = None,
                       info: dict | None = None) -> str:
        """info, if given, receives the raw output and confidence stats of the final attempt (for routing)."""
        img = self.fit(img)
        text, rotated = "", False
        for attempt, temp in enumerate(self.cfg["temps"]):
            image_b64 = b64png(img)
            parts = [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}}]
            if self.cfg["prompt"]:
                parts.append({"type": "text", "text": self.cfg["prompt"]})
            req = {
                "model": self.model,
                "messages": [{"role": "user", "content": parts if self.cfg["image_first"] else parts[::-1]}],
                "max_tokens": max_tokens or self.cfg["max_tokens"],
                "temperature": temp,
            }
            if info is not None:
                req["logprobs"] = True
            try:
                r = await client.post(f"{self.endpoint}/chat/completions", json=req)
                r.raise_for_status()
                data = r.json()
            except Exception as e:  # noqa: BLE001
                self.stats["errors"] += 1
                print(f"recognise error attempt {attempt}: {e}", flush=True)
                continue
            usage = data.get("usage") or {}
            self.stats["requests"] += 1
            self.stats["prompt_tokens"] += usage.get("prompt_tokens", 0)
            self.stats["completion_tokens"] += usage.get("completion_tokens", 0)
            choice = data["choices"][0]
            raw = choice["message"]["content"] or ""
            text, meta = split_front_matter(raw)
            if info is not None:
                lps = [t["logprob"] for t in ((choice.get("logprobs") or {}).get("content") or [])]
                info.update(raw=raw, finish=choice.get("finish_reason"), attempt=attempt, n_tok=len(lps),
                            mean_lp=sum(lps) / len(lps) if lps else None, min_lp=min(lps) if lps else None,
                            n_low=sum(lp < -2.3 for lp in lps))  # tokens with p < 0.1
            if self.reader == "olmocr2" and not rotated and meta.get("is_rotation_valid") == "false":
                deg = int(meta.get("rotation_correction", "0") or 0)
                if deg in (90, 180, 270):  # same transpose as olmocr.pipeline.build_page_query
                    img = img.transpose({90: Image.Transpose.ROTATE_90, 180: Image.Transpose.ROTATE_180,
                                         270: Image.Transpose.ROTATE_270}[deg])
                    rotated = True
                    self.stats["rotations"] = self.stats.get("rotations", 0) + 1
                    continue
            if choice.get("finish_reason") == "stop" and not looks_repetitive(text):
                break
            self.stats["retries"] += 1
        if self.reader in ("lighton", "infinity"):
            return grounding_to_md(text, reader=self.reader, keep_margins=self.keep_margins)
        return clean(text)


def split_front_matter(raw: str):
    m = FRONT_MATTER.match(raw)
    if not m:
        return raw, {}
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().lower()
    return raw[m.end():], meta


def mask_page(img: Image.Image, regions, keep_margins: bool = True) -> Image.Image:
    if keep_margins:
        return img
    out = img.copy()
    d = ImageDraw.Draw(out)
    for r in regions:
        if r.label in DROP_LABELS:
            x0, y0, x1, y1 = r.box
            d.rectangle([x0 - 2, y0 - 2, x1 + 2, y1 + 2], fill="white")
    return out


def crop(img: Image.Image, box, pad: int = 8) -> Image.Image:
    x0, y0, x1, y1 = box
    return img.crop((max(0, x0 - pad), max(0, y0 - pad), min(img.width, x1 + pad), min(img.height, y1 + pad)))


def as_formula(text: str) -> str:
    t = text.strip()
    if t.startswith("$") or t.startswith("\\[") or t.startswith("\\("):
        return t
    return f"$$\n{t}\n$$"


async def page_regions_md(rec, client, img, regions, sem, keep_margins: bool = True) -> str:
    kept = [r for r in regions if (keep_margins or r.label not in DROP_LABELS) and r.label not in SKIP_IN_REGIONS]

    async def one(r):
        async with sem:
            txt = await rec(client, crop(img, r.box), max_tokens=8192)
        if r.label == "formula":
            return as_formula(txt)
        if r.label == "doc_title" and txt and not txt.startswith("#"):
            return "# " + txt
        if r.label == "paragraph_title" and txt and not txt.startswith("#"):
            return "## " + txt
        return txt

    parts = await asyncio.gather(*(one(r) for r in kept))
    return "\n\n".join(p for p in parts if p)


def run_layout(pdfs, args, stats, t0):
    lm = LayoutModel()
    t_load = time.time()
    layouts = {}
    for i in range(0, len(pdfs), args.layout_batch):
        batch = pdfs[i : i + args.layout_batch]
        imgs = [render(p) for p in batch]
        for p, regs in zip(batch, lm(imgs)):
            layouts[p] = regs
    stats["layout_model_load_seconds"] = round(t_load - t0, 1)
    stats["layout_seconds"] = round(time.time() - t_load, 1)
    with open(os.path.join(args.out_dir, "_layout.jsonl"), "w") as f:
        for p, regs in layouts.items():
            f.write(json.dumps({"pdf": os.path.relpath(p, args.pdf_dir),
                                "regions": [[r.order, r.label, r.score, r.box] for r in regs]}) + "\n")
    del lm

    return layouts


async def run(args):
    pdfs = sorted(f for f in glob.glob(os.path.join(args.pdf_dir, "**", "*"), recursive=True)
                  if f.lower().endswith((".pdf",) + IMAGE_EXTS))
    if args.only:  # restrict to a list of paths relative to --pdf-dir (e.g. the pages a cascade re-reads)
        keep = {l.strip() for l in open(args.only) if l.strip()}
        pdfs = [p for p in pdfs if os.path.relpath(p, args.pdf_dir) in keep]
    if args.limit:
        step = max(1, len(pdfs) // args.limit)  # spread the sample across categories
        pdfs = pdfs[::step][: args.limit]
    stats = {"pages": len(pdfs), "mode": args.mode, "reader": args.reader, "requests": 0, "retries": 0, "errors": 0,
             "prompt_tokens": 0, "completion_tokens": 0}
    os.makedirs(args.out_dir, exist_ok=True)

    # Stage 1: layout for every page (batched on the GPU). Skipped in plain mode (raw model baseline).
    t0 = time.time()
    if args.mode == "plain" and not args.layout_drop:
        layouts = {p: [] for p in pdfs}
        stats["layout_model_load_seconds"] = stats["layout_seconds"] = 0.0
    else:
        layouts = run_layout(pdfs, args, stats, t0)

    # Stage 2: recognition.
    rec = Recognizer(args.endpoint, args.model, stats, args.reader, keep_margins=args.keep_margins)
    sem = asyncio.Semaphore(args.concurrency)
    done = 0
    t1 = time.time()
    async with httpx.AsyncClient(timeout=900) as client:

        async def do_page(pdf):
            nonlocal done
            cfg = READERS[args.reader]
            if args.mode == "plain" and cfg.get("dpi"):
                img = await asyncio.to_thread(render, pdf, cfg["dpi"], cfg.get("max_pixels"))
            else:
                img = await asyncio.to_thread(render, pdf)
            regs = layouts[pdf]
            info = {}
            if args.mode == "plain":
                async with sem:
                    md = await rec(client, img, info=info)
                if args.layout_drop and not args.keep_margins and args.reader in ("lighton", "infinity"):
                    # Also drop blocks lying inside the layout model's margin regions (header/footer/number/aside).
                    margins = [r.box for r in regs if r.label in DROP_LABELS]
                    md = grounding_to_md(info.get("raw", ""), margins=margins, size=layout_size(pdf, img, cfg),
                                         reader=args.reader)
            elif args.mode == "mask":
                async with sem:
                    md = await rec(client, mask_page(img, regs, args.keep_margins), info=info)
            else:
                md = await page_regions_md(rec, client, img, regs, sem, args.keep_margins)
            rel = os.path.relpath(pdf, args.pdf_dir)
            suffix = "" if args.plain_names else "_pg1_repeat1"
            out = os.path.join(args.out_dir, os.path.splitext(rel)[0] + suffix + ".md")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                f.write(md)
            if info:
                info["page"] = rel
                with open(os.path.join(args.out_dir, "_pages.jsonl"), "a", encoding="utf-8") as f:
                    f.write(json.dumps(info, ensure_ascii=False) + "\n")
            done += 1
            if done % 100 == 0:
                print(f"{done}/{len(pdfs)} pages, {time.time() - t1:.0f}s", flush=True)

        await asyncio.gather(*(do_page(p) for p in pdfs))
    stats["ocr_seconds"] = round(time.time() - t1, 1)
    stats["inference_seconds"] = round(stats["layout_seconds"] + stats["ocr_seconds"], 1)
    with open(os.path.join(args.out_dir, "_run_stats.json"), "w") as f:
        json.dump(stats, f, indent=2)
    print(json.dumps(stats, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["plain", "mask", "regions"], required=True)
    ap.add_argument("--plain-names", action="store_true", help="write <name>.md (OmniDocBench) instead of olmOCR-Bench names")
    ap.add_argument("--pdf-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--endpoint", default="http://localhost:8000/v1")
    ap.add_argument("--model", default="ovis", help="served model name")
    ap.add_argument("--reader", choices=sorted(READERS), default="ovis", help="prompt/render/retry settings")
    ap.add_argument("--concurrency", type=int, default=128)
    ap.add_argument("--layout-batch", type=int, default=16)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--layout-drop", action="store_true",
                    help="plain mode with a block-emitting reader: also run layout and drop blocks in margin regions")
    ap.add_argument("--drop-margins", dest="keep_margins", action="store_false",
                    help="drop page headers/footers/page numbers/side notes (the olmOCR-Bench convention; "
                         "default since 2026-11-09: keep them)")
    ap.add_argument("--keep-margins", dest="keep_margins", action="store_true", help=argparse.SUPPRESS)  # old flag
    ap.set_defaults(keep_margins=True)
    ap.add_argument("--only", default=None, help="file listing page paths (relative to --pdf-dir) to process")
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
