"""PROTOTYPE: outline in orange where frame b (texture highlighted) differs from frame a; crop the HUD line."""
import sys
import numpy as np
from PIL import Image, ImageFilter
a, b = Image.open(sys.argv[1]).convert("RGB"), Image.open(sys.argv[2]).convert("RGB")
A, B = np.asarray(a, np.int16), np.asarray(b, np.int16)
mask = Image.fromarray(((np.abs(B - A).sum(2) > 60) * 255).astype(np.uint8))
mask = mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
fill = np.asarray(mask, bool)
edge = np.asarray(mask.filter(ImageFilter.MaxFilter(5)), bool) & ~np.asarray(mask.filter(ImageFilter.MinFilter(3)), bool)
out = A.copy()
out[fill] = out[fill] * 0.7 + np.array((255, 140, 30)) * 0.3
out[edge] = (255, 140, 30)
img = Image.fromarray(out.astype(np.uint8))
h = img.height
img = img.crop((0, int(h * 0.07), img.width, h))
img.thumbnail((720, 720))
img.save(sys.argv[3], quality=85)
