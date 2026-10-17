"""Crops the two shape panels out of the evt_003 evidence image for the landing-page slider.

Source: ../samples/w900_1260/evt_003.jpg (1280 x 1341, written by the agent's render_evidence,
build step 7). Lower half = two panels drawn by OpenCV from tracked positions, both "attacking
right": left = White 4-4-2, 15:05-15:35; right = White 3-4-3, 16:35-17:05. The panels are
separated by a white column at x = 636-643; panels start at y = 916, captions end at y = 958.
Run: python3 scripts/crop-evidence.py   (needs Pillow; output is committed in public/product/)
"""
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
SRC = HERE.parent.parent / "samples" / "w900_1260" / "evt_003.jpg"
OUT = HERE.parent / "public" / "product"
# 958: below the two-line caption burned into each panel (its facts are in the small print)
TOP, BOTTOM = 958, 1341
PANELS = {"evt003-before.jpg": (0, 636), "evt003-after.jpg": (644, 1280)}

OUT.mkdir(parents=True, exist_ok=True)
img = Image.open(SRC).convert("RGB")
assert img.size == (1280, 1341), f"unexpected evidence image size {img.size}"
for name, (left, right) in PANELS.items():
    img.crop((left, TOP, right, BOTTOM)).save(OUT / name, quality=88, optimize=True)
    print(f"public/product/{name}: {right - left} x {BOTTOM - TOP}")
