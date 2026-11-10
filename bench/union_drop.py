"""Offline: rebuild a LightOnOCR grounding run, also dropping blocks that PP-DocLayoutV3 calls margin content.

  .venv/bin/python bench/union_drop.py lt4 pipe_mask lt4_u      # olmOCR-Bench names
  .venv/bin/python bench/union_drop.py omni_lt4 omni_mask omni_lt4_u --plain-names

A grounding block is dropped if its own label is a margin label (as in the pipeline), or if >= 60% of its area lies
inside a header/footer/number/aside_text region from the layout run. Pure geometry; no benchmark information.
"""
import json, os, sys, glob
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image
import pypdfium2 as pdfium
from docengine.pipeline import GROUNDING_DROP, grounding_blocks, RENDER_LONGEST, IMAGE_EXTS
from docengine.lighton_dollars import fix_escaped_dollars
from docengine.layout import DROP_LABELS
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH = os.path.join(ROOT, "data", "olmOCR-bench", "bench_data", "pdfs")
OMNI = os.path.join(ROOT, "data", "omnidocbench", "images")


_OMNI_SIZES = None


def page_size(rel):
    global _OMNI_SIZES
    if _OMNI_SIZES is None:  # OmniDocBench images are not stored locally: sizes from the ground-truth page_info
        _OMNI_SIZES = {pg["page_info"]["image_path"]: (pg["page_info"]["width"], pg["page_info"]["height"])
                       for pg in json.load(open(os.path.join(ROOT, "data", "omnidocbench", "OmniDocBench.json")))}
    if rel in _OMNI_SIZES:
        w, h = _OMNI_SIZES[rel]
        s = min(1.0, RENDER_LONGEST / max(w, h))
        return w * s, h * s
    for base in (BENCH, OMNI):
        p = os.path.join(base, rel)
        if os.path.exists(p):
            if p.lower().endswith(IMAGE_EXTS):
                w, h = Image.open(p).size
            else:
                pdf = pdfium.PdfDocument(p); w, h = pdf[0].get_size(); pdf.close()
            s = min(1.0, RENDER_LONGEST / max(w, h)) if p.lower().endswith(IMAGE_EXTS) else RENDER_LONGEST / max(w, h)
            return w * s, h * s
    return None


def overlap_frac(b, r):
    x0, y0, x1, y1 = max(b[0], r[0]), max(b[1], r[1]), min(b[2], r[2]), min(b[3], r[3])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    area = max(1e-6, (b[2] - b[0]) * (b[3] - b[1]))
    return inter / area


def main(src, layout_run, dst, plain):
    lay = {}
    for l in open(os.path.join(ROOT, "results", layout_run, "_layout.jsonl")):
        d = json.loads(l); lay[d["pdf"]] = [r for r in d["regions"] if r[1] in DROP_LABELS]
    n_pages = n_drop = 0
    for l in open(os.path.join(ROOT, "results", src, "_pages.jsonl")):
        d = json.loads(l); rel = d["page"]
        regs = lay.get(rel, [])
        size = page_size(rel) if regs else None
        keep = []
        for lab, box, t in grounding_blocks(d["raw"]):
            if not t or lab in GROUNDING_DROP:
                continue
            if size:
                W, H = size
                bb = [box[0] * W / 1000, box[1] * H / 1000, box[2] * W / 1000, box[3] * H / 1000]
                if any(overlap_frac(bb, r[3]) >= 0.6 for r in regs):
                    n_drop += 1; continue
            keep.append(fix_escaped_dollars(t))
        md = "\n\n".join(keep) if grounding_blocks(d["raw"]) else open(os.path.join(ROOT, "results", src, os.path.splitext(rel)[0] + ("" if plain else "_pg1_repeat1") + ".md")).read()
        out = os.path.join(ROOT, "results", dst, os.path.splitext(rel)[0] + ("" if plain else "_pg1_repeat1") + ".md")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        open(out, "w").write(md); n_pages += 1
    print(f"{dst}: {n_pages} pages, {n_drop} extra blocks dropped")


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    main(*a, plain="--plain-names" in sys.argv)
