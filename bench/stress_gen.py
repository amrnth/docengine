"""Synthetic stress pages: one US-letter page packed with small text, exact ground truth from the PDF's own text layer.

  .venv/bin/python bench/stress_gen.py

Grid: font size (3–10 pt) x columns (1, 2, 3) x text kind:
  natural  real English prose (paragraphs from the random Common Crawl pages' text layers)
  random   dictionary words in random order mixed with numbers and codes, so the reader cannot guess from context
Each HTML document is printed by headless Chrome (Times-like serif, 0.5 in margins), page 1 is kept, and its text
layer becomes the ground truth. Writes data/stress/pages/<kind>_<pt>pt_<cols>col.pdf and data/stress/gt/<same>.txt.
"""
import html
import json
import os
import random
import re
import subprocess

import pypdfium2 as pdfium

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "stress")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SIZES = [3, 3.5, 4, 4.5, 5, 6, 7, 8, 10]
COLS = [1, 2, 3]


def natural_paragraphs():
    """English prose paragraphs from the random Common Crawl pages (text layers, ASCII-heavy pages only)."""
    paras = []
    src = os.path.join(ROOT, "data", "random_cc", "pages")
    for f in sorted(os.listdir(src)):
        pdf = pdfium.PdfDocument(os.path.join(src, f))
        t = pdf[0].get_textpage().get_text_range()
        pdf.close()
        t = t.replace("\r", "")
        for p in re.split(r"\n\s*\n|(?<=[.!?])\n", t):
            p = re.sub(r"\s+", " ", p).strip()
            words = p.split()
            if len(words) >= 25 and sum(c.isascii() for c in p) > 0.97 * len(p) and \
                    sum(w.isalpha() for w in words) > 0.7 * len(words):
                paras.append(p)
    return paras


def random_paragraphs(rng, n=400):
    words = [w.strip() for w in open("/usr/share/dict/words") if 3 <= len(w.strip()) <= 12 and w.strip().islower()]
    out = []
    for _ in range(n):
        toks = []
        for _ in range(rng.randint(40, 90)):
            r = rng.random()
            if r < 0.12:
                toks.append(str(rng.randint(0, 99999)))
            elif r < 0.16:
                toks.append(f"{rng.choice('ABCDEFGHKLMNPRSTXZ')}{rng.choice('ABCDEFGHKLMNPRSTXZ')}-{rng.randint(10, 999)}")
            elif r < 0.20:
                toks.append(f"{rng.uniform(0, 100):.2f}")
            else:
                toks.append(rng.choice(words))
        out.append(" ".join(toks) + ".")
    return out


def page_html(paras, pt, cols):
    body = "\n".join(f"<p>{html.escape(p)}</p>" for p in paras)
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
@page {{ size: letter; margin: 0.5in; }}
body {{ font-family: 'Times New Roman', Times, serif; font-size: {pt}pt; line-height: 1.2; margin: 0;
       column-count: {cols}; column-gap: 0.25in; text-align: justify; }}
p {{ margin: 0 0 0.4em 0; }}
</style></head><body>{body}</body></html>"""


def main():
    rng = random.Random(3)
    nat = natural_paragraphs()
    rng.shuffle(nat)
    rnd = random_paragraphs(rng)
    os.makedirs(os.path.join(OUT, "pages"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "gt"), exist_ok=True)
    tmp = os.path.join(OUT, "tmp")
    os.makedirs(tmp, exist_ok=True)
    meta = []
    for kind, paras in (("natural", nat), ("random", rnd)):
        for pt in SIZES:
            for cols in COLS:
                name = f"{kind}_{str(pt).replace('.', 'p')}pt_{cols}col"
                start = rng.randrange(max(1, len(paras) - 200))
                hp, pp = os.path.join(tmp, name + ".html"), os.path.join(tmp, name + ".pdf")
                open(hp, "w").write(page_html(paras[start:start + 200] * 2, pt, cols))
                subprocess.run([CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                                f"--print-to-pdf={pp}", "file://" + hp], check=True, capture_output=True)
                src = pdfium.PdfDocument(pp)
                dst = pdfium.PdfDocument.new()
                dst.import_pages(src, [0])
                dst.save(os.path.join(OUT, "pages", name + ".pdf"))
                gt = src[0].get_textpage().get_text_range()
                src.close()
                open(os.path.join(OUT, "gt", name + ".txt"), "w").write(gt)
                meta.append({"file": name + ".pdf", "kind": kind, "pt": pt, "cols": cols, "words": len(gt.split())})
                print(meta[-1], flush=True)
    with open(os.path.join(OUT, "meta.jsonl"), "w") as f:
        for m in meta:
            f.write(json.dumps(m) + "\n")


if __name__ == "__main__":
    main()
