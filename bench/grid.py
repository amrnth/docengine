"""Contact sheet of rendered failure pages: grid.py out.png W name_prefix..."""
import glob, sys
from PIL import Image
out, W, names = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
P = "failures/review/png/"
ims = []
for n in names:
    f = sorted(glob.glob(P + "*" + n + "*"))[0]
    i = Image.open(f).convert("RGB")
    ims.append(i.resize((W, int(W * i.height / i.width))))
cols = min(4, len(ims)); rows = -(-len(ims) // cols)
H = max(i.height for i in ims)
c = Image.new("RGB", (W * cols, H * rows), "white")
for k, i in enumerate(ims):
    c.paste(i, ((k % cols) * W, (k // cols) * H))
c.save(out)
