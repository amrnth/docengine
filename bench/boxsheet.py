"""Contact sheet: page thumbnails with one red box each + index label. boxsheet.py rows.jsonl out.png [start] [count]"""
import json, os, sys
import pypdfium2 as pdfium
from PIL import Image, ImageDraw
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDFS = os.path.join(ROOT, "data", "olmOCR-bench", "bench_data", "pdfs")
rows = [json.loads(l) for l in open(sys.argv[1])]
start = int(sys.argv[3]) if len(sys.argv) > 3 else 0
rows = rows[start:start + (int(sys.argv[4]) if len(sys.argv) > 4 else 12)]
W = 560; tiles = []
for r in rows:
    pdf = pdfium.PdfDocument(os.path.join(PDFS, r["pdf"]))
    im = pdf[0].render(scale=W / pdf[0].get_size()[0]).to_pil().convert("RGB"); pdf.close()
    d = ImageDraw.Draw(im); b = r["box"]; w, h = im.size
    d.rectangle([b[0]*w/1000-4, b[1]*h/1000-4, b[2]*w/1000+4, b[3]*h/1000+4], outline=(255, 0, 0), width=4)
    d.rectangle([0, 0, 70, 34], fill=(255, 255, 0)); d.text((6, 4), str(r.get("n", "")), fill=(0, 0, 0), font_size=26)
    tiles.append(im)
H = max(t.height for t in tiles); cols = 4
c = Image.new("RGB", (W * cols, H * (-(-len(tiles) // cols))), "white")
for k, t in enumerate(tiles):
    c.paste(t, ((k % cols) * W, (k // cols) * H))
c.save(sys.argv[2])
