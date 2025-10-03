#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Builds a multi-size Windows .ico at assets/app.ico — no CLI args.
- Looks for the largest PNG in assets/ and converts it.
- Default sizes: 16,24,32,48,64,128,256
- Fit strategy: "contain" (keeps aspect; transparent pad to square)

Usage:
  python tools/build_icon.py

Requires:
  pip install pillow
"""

from pathlib import Path
from typing import List, Tuple
from PIL import Image

# --- Hardcoded paths / settings ---
ASSETS_DIR = Path(__file__).resolve().parents[1] / "../assets"
OUTPUT_ICO = ASSETS_DIR / "app.ico"
DEFAULT_SIZES = [16, 24, 32, 48, 64, 128, 256]
FIT = "contain"  # one of: "contain", "cover", "stretch"

# --- Helpers ---
def _pick_largest_png(folder: Path) -> Path | None:
    best: tuple[int, Path] | None = None
    for p in folder.glob("*.png"):
        try:
            with Image.open(p) as im:
                w, h = im.size
            px = w * h
            if best is None or px > best[0]:
                best = (px, p)
        except Exception:
            continue
    return best[1] if best else None

def _resize_square(img: Image.Image, size: int, fit: str) -> Image.Image:
    assert fit in ("contain", "cover", "stretch")
    w, h = img.size
    if fit == "stretch":
        return img.resize((size, size), Image.LANCZOS)

    aspect = w / h
    if fit == "contain":
        if aspect >= 1:
            new_w, new_h = size, int(round(size / aspect))
        else:
            new_w, new_h = int(round(size * aspect)), size
        scaled = img.resize((new_w, new_h), Image.LANCZOS)
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        canvas.paste(scaled, ((size - new_w) // 2, (size - new_h) // 2), scaled)
        return canvas

    # cover
    if aspect >= 1:
        new_h, new_w = size, int(round(size * aspect))
    else:
        new_w, new_h = size, int(round(size / aspect))
    scaled = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - size) // 2
    top = (new_h - size) // 2
    return scaled.crop((left, top, left + size, top + size))

def _save_ico(src_img: Image.Image, out_path: Path, sizes: List[int], fit: str):
    sizes = sorted({int(s) for s in sizes if 1 <= int(s) <= 256})
    if not sizes:
        raise ValueError("No valid icon sizes (1..256).")
    # Render once per size for best quality (Pillow embeds sizes from base)
    # Choose largest as base image
    rendered: List[Tuple[int, Image.Image]] = [(s, _resize_square(src_img, s, fit)) for s in sizes]
    base_size, base_img = max(rendered, key=lambda t: t[0])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    base_img.save(out_path, format="ICO", sizes=[(s, s) for s in sizes])

# --- Main ---
def main():
    if not ASSETS_DIR.exists():
        raise SystemExit(f"[error] Assets folder not found: {ASSETS_DIR}")

    src_png = _pick_largest_png(ASSETS_DIR)
    if not src_png:
        raise SystemExit(f"[error] No PNGs found in {ASSETS_DIR}. "
                         f"Export one (e.g., app@1024.png) from Penpot into that folder.")

    try:
        img = Image.open(src_png).convert("RGBA")
    except Exception as e:
        raise SystemExit(f"[error] Failed to load PNG '{src_png}': {e}")

    try:
        _save_ico(img, OUTPUT_ICO, DEFAULT_SIZES, FIT)
    except Exception as e:
        raise SystemExit(f"[error] Failed to write ICO '{OUTPUT_ICO}': {e}")

    print(f"[ok] Wrote {OUTPUT_ICO} from {src_png.name} with sizes: {', '.join(map(str, DEFAULT_SIZES))}")

if __name__ == "__main__":
    main()
