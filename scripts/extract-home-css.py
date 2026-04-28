"""Extrae CSS inline del index.html a /assets/css/home.css.
Sustituye el bloque <style>...</style> del index por <link>.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "hostinger_site" / "index.html"
CSS_OUT = ROOT / "hostinger_site" / "assets" / "css" / "home.css"

html = INDEX.read_text(encoding="utf-8")

m = re.search(r"<style>(.*?)</style>", html, flags=re.DOTALL)
if not m:
    raise SystemExit("No se encontro bloque <style> en index.html")

css = m.group(1).strip()

CSS_OUT.parent.mkdir(parents=True, exist_ok=True)
CSS_OUT.write_text(css, encoding="utf-8")
print(f"CSS extraido: {len(css)} chars -> {CSS_OUT}")

# Reemplaza inline <style> por <link>
new_html = html[: m.start()] + '<link rel="stylesheet" href="/assets/css/home.css">' + html[m.end() :]
INDEX.write_text(new_html, encoding="utf-8")
print(f"index.html actualizado: {INDEX.stat().st_size} bytes")
