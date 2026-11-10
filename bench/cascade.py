"""Build a cascade run offline: A everywhere, B on A's least-confident fraction of pages (A's own mean logprob).

  .venv/bin/python bench/cascade.py casc_lt omni_lt08_u omni_lt4_u 0.2 [--plain-names]

The fraction is taken within the run being processed (unsupervised: no labels). Writes results/<out>/.
"""
import json, os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from selector import conf, load, md_path  # noqa: E402  (bench/selector.py)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
a = [x for x in sys.argv[1:] if not x.startswith("--")]
out, A, B, frac = a[0], a[1], a[2], float(a[3])
plain = "--plain-names" in sys.argv
pa = load(A)
order = sorted(pa, key=lambda p: conf(pa[p]))
reread = set(order[: int(round(frac * len(order)))])
for p in pa:
    src = B if p in reread else A
    dst = md_path(out, p, plain)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy(md_path(src, p, plain), dst)
print(f"{out}: {len(pa)} pages, {len(reread)} from {B}")
