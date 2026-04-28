"""Reduce favicon a 256x256 (suficiente para apple-touch retina)."""
from PIL import Image
from pathlib import Path

src = Path(__file__).resolve().parents[1] / "hostinger_site" / "assets" / "img" / "favicon.png"
img = Image.open(src)
img_256 = img.resize((256, 256), Image.LANCZOS)
img_256.save(src, "PNG", optimize=True)
img_256.save(src.with_suffix(".webp"), "WEBP", quality=92, method=6)
print(f"favicon.png: {src.stat().st_size/1024:.1f} KB")
print(f"favicon.webp: {src.with_suffix('.webp').stat().st_size/1024:.1f} KB")
