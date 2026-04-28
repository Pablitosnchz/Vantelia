"""Convierte PNG/JPG a WebP optimizado y crea variantes de tamaño donde aplique.
Uso: python scripts/convert-webp.py
"""
from pathlib import Path
from PIL import Image
import sys

ROOT = Path(__file__).resolve().parents[1]
IMG_DIR = ROOT / "hostinger_site" / "assets" / "img"

# Calidad WebP por imagen (logos = lossless, fotos = 82)
QUALITY_MAP = {
    "logo-letra": {"lossless": True, "quality": 100, "method": 6},
    "logo-vantelia": {"lossless": True, "quality": 100, "method": 6},
    "favicon": {"lossless": True, "quality": 100, "method": 6},
    "default": {"lossless": False, "quality": 82, "method": 6},
}


def opts_for(stem: str):
    for key, val in QUALITY_MAP.items():
        if key == stem:
            return val
    return QUALITY_MAP["default"]


def convert(src: Path):
    img = Image.open(src)
    if img.mode in ("P", "RGBA") and src.suffix.lower() == ".png":
        # Mantener transparencia
        img = img.convert("RGBA")
    elif img.mode != "RGB":
        img = img.convert("RGB")

    out = src.with_suffix(".webp")
    opts = opts_for(src.stem)
    img.save(out, "WEBP", **opts)
    src_size = src.stat().st_size
    out_size = out.stat().st_size
    pct = (1 - out_size / src_size) * 100
    print(f"  {src.name:30s} {src_size/1024:8.1f} KB -> {out_size/1024:8.1f} KB  (-{pct:.1f}%)")


def main():
    if not IMG_DIR.exists():
        print(f"ERROR: {IMG_DIR} no existe", file=sys.stderr)
        sys.exit(1)

    print(f"Convirtiendo PNG/JPG a WebP en {IMG_DIR}\n")
    files = sorted(
        list(IMG_DIR.glob("*.png")) + list(IMG_DIR.glob("*.jpg")) + list(IMG_DIR.glob("*.jpeg"))
    )
    if not files:
        print("Sin imágenes que convertir.")
        return
    for f in files:
        convert(f)
    print(f"\n{len(files)} imagen(es) convertida(s).")


if __name__ == "__main__":
    main()
