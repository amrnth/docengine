"""Audit olmOCR-Bench text tests against the PDF's own stored text. Uses no OCR system at all.

  .venv/bin/python bench/audit_tests.py

For every `present` / `order` test on a born-digital page: is the test's expected string on the page, by the test's
own matching rule (same normalisation, same max_diffs), when the "candidate" is the text stored in the PDF?

To be safe against text-layer artefacts, a string counts as ON the page if it matches ANY variant of the stored text:
line-break hyphens joined / kept, ligatures expanded (NFKC), accents stripped, case folded, all spaces removed.
Only a string that matches none of them is reported as `not_on_page`.

For `absent` tests (headers_footers): count how many separate places hold the forbidden string. Two or more means
it may also be body text (to be checked by eye).

Writes reports/audit/text_audit.jsonl.
"""
import json
import os
import re
import sys
import unicodedata

import numpy as np
import pypdfium2 as pdfium
import pypdfium2.raw as raw
from fuzzysearch import find_near_matches
from rapidfuzz import fuzz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from failures import BENCH, ROOT, all_tests  # noqa: E402

from olmocr.bench.tests import normalize_text  # noqa: E402

PDFS = os.path.join(BENCH, "pdfs")
OUT = os.path.join(ROOT, "reports", "audit")
ACCENTS = "´`¨ˆ˜¸˚ˇ˘˙"


def page_info(rel, page, cache={}):
    """(raw stored text, scan_like) of one page. scan_like = one image covers >= 60% of the page."""
    key = (rel, page)
    if key not in cache:
        pdf = pdfium.PdfDocument(os.path.join(PDFS, rel))
        pg = pdf[page - 1]
        w, h = pg.get_size()
        txt = pg.get_textpage().get_text_range()
        big = 0.0
        for o in pg.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE], max_depth=4):
            try:
                l, b, r, t = o.get_pos()
            except Exception:  # noqa: BLE001
                continue
            l, r, b, t = max(0, l), min(w, r), max(0, b), min(h, t)
            if r > l and t > b:
                big = max(big, (r - l) * (t - b) / (w * h))
        pdf.close()
        cache[key] = (txt, big >= 0.6)
    return cache[key]


def strip_accents(s):
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c) and c not in ACCENTS)


def layer_variants(txt):
    """Stored text under every reading of line-break hyphens, normalised like the scorer normalises a candidate."""
    out = []
    for soft in ("", "-"):
        t = txt.replace("￾", soft).replace("\x02", soft)
        for hy in (None, "", "-"):
            u = t if hy is None else re.sub(r"-[ \t]*\r?\n[ \t]*", hy, t)
            u = normalize_text(unicodedata.normalize("NFKC", u))
            if u not in out:
                out.append(u)
    return out


def forms(s):
    """(name, transform) pairs, weakest normalisation first."""
    def nosp(x):
        return re.sub(r"\s+", "", x)
    return [("exact", lambda x: x), ("case", str.casefold), ("accent", lambda x: strip_accents(x).casefold()),
            ("space", lambda x: nosp(strip_accents(x).casefold()))]


def found(s, variants, max_diffs, kind):
    """Name of the first form under which the test's own rule finds s in the stored text, else None."""
    for name, f in forms(s):
        q = f(s)
        if not q:
            return name
        for v in variants:
            hay = f(v)
            if kind == "order":
                if find_near_matches(q, hay, max_l_dist=max_diffs):
                    return name
            else:
                thr = 1.0 - (max_diffs / len(q))
                if fuzz.partial_ratio(q, hay) / 100.0 >= thr:
                    return name
    return None


def nearest(s, variants):
    """Closest stretch of the stored text and its edit distance from s (after accent strip and case fold)."""
    q = strip_accents(s).casefold()
    best = None
    for v in variants:
        hay = strip_accents(v).casefold()
        if not q or not hay:
            continue
        d, end = _infix(q, hay)
        d2, rstart = _infix(q[::-1], hay[:end][::-1])  # same alignment, read backwards, gives the start
        cand = (d, hay[end - rstart:end])
        if best is None or cand[0] < best[0]:
            best = cand
    return best or (len(q), "")


def _infix(q, hay):
    """Smallest edit distance between q and any substring of hay, and where that substring ends (Sellers)."""
    h = np.frombuffer(hay.encode("utf-32-le"), dtype=np.uint32)
    ar = np.arange(len(h) + 1)
    prev = np.zeros(len(h) + 1, dtype=np.int64)
    for i, ch in enumerate(q, 1):
        cur = np.empty_like(prev)
        cur[0] = i
        cur[1:] = np.minimum(prev[1:] + 1, prev[:-1] + (h != ord(ch)))
        prev = np.minimum.accumulate(cur - ar) + ar  # insertions along the row
    end = int(np.argmin(prev))
    return int(prev[end]), end


def occurrences(s, variants, max_diffs):
    hay = variants[0]
    ms = sorted(find_near_matches(s, hay, max_l_dist=max_diffs), key=lambda m: m.start)
    spots, last_end = [], -1
    for m in ms:
        if m.start >= last_end:
            spots.append(hay[max(0, m.start - 70):m.end + 70])
            last_end = m.end
    return spots


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = []
    for cat, tests in all_tests():
        for t in tests:
            if t.type not in ("present", "order", "absent"):
                continue
            txt, scan = page_info(t.pdf, t.page)
            variants = layer_variants(txt)
            row = {"id": t.id, "category": cat, "type": t.type, "pdf": t.pdf, "max_diffs": t.max_diffs,
                   "layer_chars": len(variants[0]), "scan_like": scan}
            if len(variants[0]) < 200 or scan:
                row["verdict"] = "no_layer"
            elif t.type == "absent":
                spots = occurrences(t.text, variants, t.max_diffs)
                row.update(text=t.text, n_places=len(spots), places=spots[:4],
                           verdict="absent_multi" if len(spots) >= 2 else "absent_single" if spots else "absent_none")
            else:
                parts = []
                for k in (["text"] if t.type == "present" else ["before", "after"]):
                    s = getattr(t, k)
                    if t.type == "present" and not t.case_sensitive:
                        s = s.lower()
                    f = found(s, variants, t.max_diffs, t.type)
                    p = {"key": k, "want": s, "found": f}
                    if f is None:
                        d, near = nearest(s, variants)
                        p.update(dist=d, nearest=near)
                    parts.append(p)
                row["parts"] = parts
                row["verdict"] = "not_on_page" if any(p["found"] is None for p in parts) else "on_page"
            rows.append(row)
    with open(os.path.join(OUT, "text_audit.jsonl"), "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    import collections
    c = collections.Counter((r["category"], r["type"], r["verdict"]) for r in rows)
    for k in sorted(c):
        print(k, c[k])


if __name__ == "__main__":
    main()
