"""Build an unbiased "random real-world PDFs" test set from SafeDocs CC-MAIN-2021-31-PDF-UNTRUNCATED (digitalcorpora.org):
~8M PDFs crawled at random by Common Crawl. Nothing here was chosen by us or by a benchmark.

  .venv/bin/python bench/random_cc.py [n_docs=200] [seed=7]

Reads a few randomly picked zip files over HTTP range requests (no full 1.3 GB download), takes random PDFs from each,
picks one random page per PDF and writes it as a single-page PDF to data/random_cc/pages/<zip>_<file>_p<k>.pdf.
data/random_cc/manifest.jsonl records the source of every page. PDFs are only parsed with pdfium, never opened.
"""
import io
import json
import os
import random
import sys
import urllib.request
import zipfile

import pypdfium2 as pdfium

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://digitalcorpora.s3.amazonaws.com/corpora/files/CC-MAIN-2021-31-PDF-UNTRUNCATED/zipfiles/"
OUT = os.path.join(ROOT, "data", "random_cc", "pages")


class HttpFile(io.RawIOBase):
    """Seekable read-only file over HTTP range requests, with a small read-ahead cache."""

    def __init__(self, url):
        self.url, self.pos = url, 0
        req = urllib.request.Request(url, method="HEAD")
        self.size = int(urllib.request.urlopen(req).headers["Content-Length"])
        self.buf_start, self.buf = 0, b""

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = {0: off, 1: self.pos + off, 2: self.size + off}[whence]
        return self.pos

    def read(self, n=-1):
        if n < 0:
            n = self.size - self.pos
        end = min(self.pos + n, self.size)
        if not (self.buf_start <= self.pos and end <= self.buf_start + len(self.buf)):
            want = max(end - self.pos, 1 << 20)
            stop = min(self.pos + want, self.size) - 1
            req = urllib.request.Request(self.url, headers={"Range": f"bytes={self.pos}-{stop}"})
            self.buf, self.buf_start = urllib.request.urlopen(req).read(), self.pos
        data = self.buf[self.pos - self.buf_start:end - self.buf_start]
        self.pos += len(data)
        return data

    def readinto(self, b):
        d = self.read(len(b))
        b[:len(d)] = d
        return len(d)


def main(n_docs=200, seed=7):
    rng = random.Random(seed)
    os.makedirs(OUT, exist_ok=True)
    zips = rng.sample(range(0, 7933), 5)
    per = -(-n_docs // len(zips))
    manifest = []
    for z in zips:
        name = f"{z // 1000 * 1000:04d}-{z // 1000 * 1000 + 999:04d}/{z:04d}.zip"
        zf = zipfile.ZipFile(HttpFile(BASE + name))
        members = [m for m in zf.infolist() if m.filename.lower().endswith(".pdf") and m.file_size < 30_000_000]
        got = 0
        for m in rng.sample(members, len(members)):
            if got >= per or len(manifest) >= n_docs:
                break
            try:
                data = zf.read(m)
                src = pdfium.PdfDocument(data)
                n = len(src)
                if n == 0:
                    continue
                k = rng.randrange(n)
                dst = pdfium.PdfDocument.new()
                dst.import_pages(src, [k])
                stem = f"{z:04d}_{os.path.splitext(os.path.basename(m.filename))[0]}_p{k + 1}"
                dst.save(os.path.join(OUT, stem + ".pdf"))
                w, h = src[k].get_size()
                manifest.append({"file": stem + ".pdf", "zip": name, "member": m.filename, "page": k + 1,
                                 "n_pages": n, "w": round(w), "h": round(h)})
                got += 1
            except Exception as e:  # broken/encrypted PDFs are part of the real world; skip and record
                print("skip", m.filename, type(e).__name__, e, flush=True)
        print(name, got, "pages", flush=True)
    with open(os.path.join(ROOT, "data", "random_cc", "manifest.jsonl"), "w") as f:
        for r in manifest:
            f.write(json.dumps(r) + "\n")
    print(len(manifest), "pages ->", OUT)


if __name__ == "__main__":
    main(*(int(a) for a in sys.argv[1:]))
