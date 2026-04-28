"""Reduce logos sobredimensionados a tamaño util retina."""
from PIL import Image
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMG = ROOT / "hostinger_site" / "assets" / "img"

specs = {
    # logo header display 200x48 -> 600x144 retina; original es 1536x1024 (3:2)
    "logo-letra.png": (800, 533),
    # hero mark display 360x314 -> 720x628 retina; original 811x708
    "logo-vantelia.png": (640, 559),
}

for name, (w, h) in specs.items():
    src = IMG / name
    if not src.exists():
        print(f"  SKIP {name}: no existe")
        continue
    img = Image.open(src)
    if img.size[0] <= w:
        print(f"  SKIP {name}: ya es <= {w}px")
        continue
    img_resized = img.resize((w, h), Image.LANCZOS)
    img_resized.save(src, optimize=True)
    img_resized.save(src.with_suffix(".webp"), "WEBP", lossless=True, quality=100, method=6)
    print(f"  {name}: {src.stat().st_size/1024:.1f} KB / webp {src.with_suffix('.webp').stat().st_size/1024:.1f} KB")
