"""Rebuild a run's markdown from its saved raw reader outputs under a different visual-block policy (offline, no GPU).

The system drops image/chart/figure blocks (GROUNDING_DROP / INFINITY_DROP). LightOnOCR-3 often transcribes a chart's
data into such a block as an HTML table. Policies:
  base    the system as run (sanity check: must reproduce the run's .md files)
  vtable  also keep visual blocks whose text is an HTML table (structured data read off the visual)
  vall    also keep every non-empty visual block (tables and free-text descriptions)
  <policy>_tfmt same, titles only
  <policy>_fmt  same, plus render_block markup from block labels (title -> #, formula -> $$, code -> fence)

  python bench/visual_variant.py results/modal_c3b_olmocr vtable   -> results/modal_c3b_olmocr_vtable/
"""
import json
import os
import shutil
import sys

import pypdfium2 as pdfium

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from docengine.layout import DROP_LABELS  # noqa: E402
from docengine.pipeline import GROUNDING_DROP, INFINITY_DROP, _inside, blocks_of, fix_escaped_dollars, render_block  # noqa: E402

VISUAL = {"image", "chart", "figure"}


def load(path):
    return {d["page"]: d for d in map(json.loads, open(path))} if os.path.exists(path) else {}


def sizes_for(run):
    if "omni" in run:
        d = json.load(open(os.path.join(ROOT, "data", "omnidocbench", "OmniDocBench.json")))
        return lambda rel: next((p["page_info"]["width"], p["page_info"]["height"]) for p in d
                                if p["page_info"]["image_path"] == rel), True
    pdfs = os.path.join(ROOT, "data", "olmOCR-bench", "bench_data", "pdfs")

    def f(rel):
        pdf = pdfium.PdfDocument(os.path.join(pdfs, rel))
        w, h = pdf[0].get_size()
        pdf.close()
        return w, h
    return f, False


def keep_visual(policy, text):
    policy = policy.replace("_tfmt", "").replace("_fmt", "")
    return policy == "vall" or (policy == "vtable" and "<table" in text)


def main(run, policy):
    plain = "omni" in run
    size_of, is_img = sizes_for(run)
    if is_img:
        idx = {p["page_info"]["image_path"]: (p["page_info"]["width"], p["page_info"]["height"])
               for p in json.load(open(os.path.join(ROOT, "data", "omnidocbench", "OmniDocBench.json")))}
        size_of = idx.__getitem__
    stages = [("lighton", load(os.path.join(run, "_pages.jsonl")))]
    for tag, reader in [("_lt4", "lighton"), ("_pro", "infinity")]:
        d = load(os.path.join(run, f"_reread{tag}.jsonl"))
        if d:
            stages.append((reader, d))
    margins = {}
    for line in open(os.path.join(run, "_layout.jsonl")):
        d = json.loads(line)
        margins[d["pdf"]] = [r[3] for r in d["regions"] if r[1] in DROP_LABELS]
    out = run.rstrip("/") + f"_{policy}"
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    same = changed = 0
    for rel in stages[0][1]:
        md = None
        for reader, d in stages:
            if rel not in d:
                continue
            raw = d[rel].get("raw", "")
            blocks = blocks_of(reader, raw)
            if not blocks:
                if md is None:  # stage 1 without blocks: the system used the raw text
                    md = fix_escaped_dollars(raw.strip())
                continue
            W, H = size_of(rel)
            s = 2048 / max(W, H)
            if is_img:
                s = min(1.0, s)
            drop = INFINITY_DROP if reader == "infinity" else GROUNDING_DROP
            keep = []
            for lab, box, t in blocks:
                if not t:
                    continue
                if lab in drop and not (lab in VISUAL and keep_visual(policy, t)):
                    continue
                bb = [box[0] * W * s / 1000, box[1] * H * s / 1000, box[2] * W * s / 1000, box[3] * H * s / 1000]
                if any(_inside(bb, r) >= 0.6 for r in margins.get(rel, ())):
                    continue
                t = t if reader == "infinity" else fix_escaped_dollars(t)
                keep.append(render_block(lab, t, ("title", "formula", "code") if policy.endswith("_fmt") else ("title",))
                            if policy.endswith("fmt") else t)
            new = "\n\n".join(keep)
            if new.strip():
                md = new
        md = md or ""
        name = os.path.splitext(rel)[0] + ("" if plain else "_pg1_repeat1") + ".md"
        old_path = os.path.join(run, name)
        old = open(old_path, encoding="utf-8").read() if os.path.exists(old_path) else ""
        same += old == md
        changed += old != md
        os.makedirs(os.path.dirname(os.path.join(out, name)), exist_ok=True)
        with open(os.path.join(out, name), "w", encoding="utf-8") as f:
            f.write(md)
    print(f"{out}: {same} pages identical to the run, {changed} differ")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
