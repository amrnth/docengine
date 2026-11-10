"""Export a run on the generalisation set (ParseBench docs + DP-Bench PDFs, `--bench gen` on Modal) to one JSONL
record per page, for the official scorers that run in Docker (bench/gen_parsebench.py, bench/gen_dpbench.py).

Per page: the system's markdown exactly as written (the .md file), the reader whose output it is (the last stage that
re-read the page and produced text), that reader's blocks (label, 0-1000 box, text, kept-by-the-system flag) and the
page size in PDF points. Variants (`--variant`) rebuild the markdown from the same blocks for diagnosis only:
  system   the .md file as written (what we report)
  margins  + header/footer/page-number blocks the system drops
  vtable   + image/chart blocks whose text is an HTML table (bench/visual_variant.py policy)
  charts   + image/chart blocks the system drops (LightOn often transcribes chart data into them)
  all      both

  python bench/gen_export.py results/modal_c3b_gen [--variant system]  -> results/modal_c3b_gen/_export_<variant>.jsonl
"""
import argparse
import json
import os
import sys

import pypdfium2 as pdfium
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from docengine.layout import DROP_LABELS  # noqa: E402
from docengine.pipeline import (GROUNDING_DROP, IMAGE_EXTS, INFINITY_DROP, _inside, blocks_of,  # noqa: E402
                                fix_escaped_dollars, grounding_to_md, render_block)

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "gen")
MARGIN = {"header", "footer", "page_number", "page_header", "page_footer", "header_image", "footer_image",
          "aside_text", "page_footnote"}
VISUAL = {"image", "chart", "figure"}


def page_size(rel):
    path = os.path.join(SRC, rel)
    if path.lower().endswith(IMAGE_EXTS):
        return Image.open(path).size
    pdf = pdfium.PdfDocument(path)
    w, h = pdf[0].get_size()
    pdf.close()
    return w, h


def load(path):
    return {d["page"]: d for d in map(json.loads, open(path))} if os.path.exists(path) else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--stage1-reader", default=None, help="lighton (c3b) or ovis (v2); default from run name")
    ap.add_argument("--rebuild", choices=["default", "keep_margins"], default=None,
                    help="rebuild the markdown with the current grounding_to_md (default rules, or --keep-margins)")
    ap.add_argument("--fmt", action="store_true", help="render_block markup from block labels")
    ap.add_argument("--fmt-kinds", default="title,formula,code")
    ap.add_argument("--variant", default="system", choices=["system", "vtable", "vtable_margins", "margins", "charts", "all"])
    a = ap.parse_args()
    r1 = a.stage1_reader or ("ovis" if "v2" in os.path.basename(a.run_dir.rstrip("/")) else "lighton")
    stages = [(r1, load(os.path.join(a.run_dir, "_pages.jsonl")))]
    for tag, reader in [("", "lighton"), ("_lt4", "lighton"), ("_pro", "infinity")]:
        d = load(os.path.join(a.run_dir, f"_reread{tag}.jsonl"))
        if d:
            stages.append((reader, d))
    margins = {}
    lay = os.path.join(a.run_dir, "_layout.jsonl")
    if os.path.exists(lay):
        for line in open(lay):
            d = json.loads(line)
            margins[d["pdf"]] = [r[3] for r in d["regions"] if r[1] in DROP_LABELS]
    out = open(os.path.join(a.run_dir, f"_export_{a.variant}{('_fmt' if a.fmt_kinds.count(',') else '_tfmt') if a.fmt else ''}{'_' + a.rebuild if a.rebuild else ''}.jsonl"), "w", encoding="utf-8")
    n = 0
    for rel in stages[0][1]:
        reader, raw = r1, stages[0][1][rel].get("raw", "")
        for rd, d in stages[1:]:
            if rel in d and blocks_of(rd, d[rel].get("raw", "")):
                reader, raw = rd, d[rel]["raw"]
        W, H = page_size(rel)
        # layout margin boxes are in pixels of the default 2048-longest render (images never upscaled)
        s = 2048 / max(W, H)
        if rel.lower().endswith(IMAGE_EXTS):
            s = min(1.0, s)
        drop = INFINITY_DROP if reader == "infinity" else GROUNDING_DROP
        blocks = []
        for lab, box, t in (blocks_of(reader, raw) if reader != "ovis" else []):
            kept = bool(t) and lab not in drop
            if kept and margins.get(rel):
                bb = [box[0] * W * s / 1000, box[1] * H * s / 1000, box[2] * W * s / 1000, box[3] * H * s / 1000]
                kept = not any(_inside(bb, r) >= 0.6 for r in margins[rel])
            blocks.append({"label": lab, "box": box, "text": t, "kept": kept})
        stem = os.path.splitext(rel)[0]
        md = open(os.path.join(a.run_dir, stem + ".md"), encoding="utf-8").read() \
            if os.path.exists(os.path.join(a.run_dir, stem + ".md")) else ""
        if a.variant != "system" and blocks:
            add = (MARGIN if a.variant in ("margins", "all", "vtable_margins") else set()) | (
                VISUAL if a.variant in ("charts", "all") else set())
            parts = [b["text"] if reader == "infinity" else fix_escaped_dollars(b["text"]) for b in blocks
                     if b["text"] and (b["kept"] or b["label"] in add
                                       or (a.variant.startswith("vtable") and b["label"] in VISUAL and "<table" in b["text"]))]
            md = "\n\n".join(parts)
        if a.rebuild and reader != "ovis":
            md = grounding_to_md(raw, margins=margins.get(rel, ()), size=(W * s, H * s), reader=reader,
                                 keep_margins=a.rebuild == "keep_margins")
        if a.fmt and blocks:
            md = "\n\n".join(render_block(b["label"], b["text"] if reader == "infinity" else fix_escaped_dollars(b["text"]),
                                            tuple(a.fmt_kinds.split(",")))
                               for b in blocks if b["text"] and (b["kept"] or (a.variant.startswith("vtable") and
                               b["label"] in VISUAL and "<table" in b["text"]) or (b["label"] in MARGIN and
                               a.variant in ("margins", "all", "vtable_margins")) or (b["label"] in VISUAL and
                               a.variant in ("charts", "all"))))
        out.write(json.dumps({"rel": rel, "reader": reader, "w": W, "h": H, "md": md, "blocks": blocks},
                             ensure_ascii=False) + "\n")
        n += 1
    print(n, "pages ->", out.name)


if __name__ == "__main__":
    main()
