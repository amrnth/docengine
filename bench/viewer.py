"""Side-by-side viewer: original PDF page | model Markdown (rendered, with KaTeX math) | raw Markdown.

  python bench/viewer.py <model_key> [--per-cat 2] [--seed 0]   -> results/<model_key>/_viewer.html
"""

import argparse
import base64
import glob
import html
import io
import json
import os
import random

import pypdfium2 as pdfium

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDFS = os.path.join(ROOT, "data", "olmOCR-bench", "bench_data", "pdfs")


def page_png(pdf_path, longest=1100):
    pdf = pdfium.PdfDocument(pdf_path)
    page = pdf[0]
    w, h = page.get_size()
    img = page.render(scale=longest / max(w, h)).to_pil()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    pdf.close()
    return base64.b64encode(buf.getvalue()).decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--per-cat", type=int, default=2)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    out_dir = os.path.join(ROOT, "results", a.model)
    rng = random.Random(a.seed)
    items = []
    for cat in sorted(os.listdir(PDFS)):
        pdfs = sorted(glob.glob(os.path.join(PDFS, cat, "*.pdf")))
        for p in rng.sample(pdfs, min(a.per_cat, len(pdfs))):
            md_path = os.path.join(out_dir, cat, os.path.basename(p)[:-4] + "_pg1_repeat1.md")
            md = open(md_path, encoding="utf-8").read() if os.path.exists(md_path) else "(missing)"
            items.append({"cat": cat, "name": os.path.basename(p), "img": page_png(p), "md": md})

    cards = []
    for i, it in enumerate(items):
        cards.append(f"""
<section>
  <h2>{html.escape(it['cat'])} <small>{html.escape(it['name'])}</small></h2>
  <div class="row">
    <div class="col"><h3>Original page</h3><img src="data:image/png;base64,{it['img']}"></div>
    <div class="col"><h3>{html.escape(a.model)} output (rendered)</h3><div class="md" id="md{i}"></div></div>
    <div class="col"><h3>Raw Markdown</h3><pre>{html.escape(it['md'])}</pre></div>
  </div>
</section>""")
    data = json.dumps([it["md"] for it in items])
    page = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{html.escape(a.model)} on olmOCR-Bench</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script src="https://cdn.jsdelivr.net/npm/marked@12/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"></script>
<style>
body{{font-family:-apple-system,system-ui,sans-serif;margin:0;padding:16px 24px;background:#f6f6f4;color:#222}}
h1{{font-size:20px}} h2{{font-size:16px;margin:28px 0 8px}} h2 small{{color:#888;font-weight:400}}
h3{{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:#777;margin:0 0 6px}}
.row{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px}}
.col{{background:#fff;border:1px solid #ddd;border-radius:6px;padding:10px;max-height:900px;overflow:auto}}
img{{width:100%}} pre{{white-space:pre-wrap;font-size:11px;margin:0}}
.md{{font-size:13px;line-height:1.45}} .md table{{border-collapse:collapse}} .md td,.md th{{border:1px solid #ccc;padding:2px 5px}}
</style></head><body>
<h1>{html.escape(a.model)} on olmOCR-Bench: {len(items)} sample pages ({a.per_cat} per category)</h1>
{''.join(cards)}
<script>
const MDS = {data};
MDS.forEach((m, i) => {{
  // protect math from the markdown parser, then let KaTeX render it
  const math = []; const keep = s => {{ math.push(s); return `@@M${{math.length-1}}@@`; }};
  let t = m.replace(/\\$\\$[\\s\\S]+?\\$\\$|\\\\\\[[\\s\\S]+?\\\\\\]|\\\\\\([\\s\\S]+?\\\\\\)|\\$[^$\\n]+?\\$/g, keep);
  let h = marked.parse(t).replace(/@@M(\\d+)@@/g, (_, k) => math[+k].replace(/</g,'&lt;'));
  const el = document.getElementById('md' + i); el.innerHTML = h;
  renderMathInElement(el, {{delimiters:[{{left:'$$',right:'$$',display:true}},{{left:'\\\\[',right:'\\\\]',display:true}},{{left:'\\\\(',right:'\\\\)',display:false}},{{left:'$',right:'$',display:false}}], throwOnError:false}});
}});
</script></body></html>"""
    path = os.path.join(out_dir, "_viewer.html")
    open(path, "w", encoding="utf-8").write(page)
    print(path, len(items), "pages")


if __name__ == "__main__":
    main()
