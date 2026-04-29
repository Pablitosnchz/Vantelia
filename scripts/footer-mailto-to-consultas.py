"""Reemplaza enlaces mailto del FOOTER (no del cuerpo) por /consultas/.
Targetea solo los 2 patrones del footer: icono social y col Empresa.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    ROOT / "hostinger_site" / "index.html",
    *(ROOT / "hostinger_site").glob("*/index.html"),
    *(ROOT / "hostinger_site" / "legal").glob("*/index.html"),
    ROOT / "scripts" / "build-pages.py",
    ROOT / "scripts" / "build-legal.py",
]

PATTERNS = [
    # Icon mailto in footer-social
    (
        '<a href="mailto:info@vantelia.es" class="social-a" aria-label="Email">✉</a>',
        '<a href="/consultas/" class="social-a" aria-label="Solicitar consulta">✉</a>',
    ),
    # Col Empresa mailto label
    (
        '<a href="mailto:info@vantelia.es">info@vantelia.es</a>',
        '<a href="/consultas/">Solicitar consulta</a>',
    ),
    # Padded version
    (
        '<a href="mailto:info@vantelia.es"               class="social-a" aria-label="Email">✉</a>',
        '<a href="/consultas/"                            class="social-a" aria-label="Solicitar consulta">✉</a>',
    ),
    # Remove logo image in footer (keep brand-name span only)
    (
        '<img src="/assets/img/logo-letra.png" alt="Vantelia · IA y Marketing Digital" width="125" height="30" loading="lazy" decoding="async">\n          <span class="brand-name">Vantelia</span>',
        '<span class="brand-name">Vantelia</span>',
    ),
]

for path in TARGETS:
    if not path.exists():
        continue
    text = path.read_text(encoding="utf-8")
    new = text
    for old, repl in PATTERNS:
        new = new.replace(old, repl)
    if new != text:
        path.write_text(new, encoding="utf-8")
        print(f"  edited: {path.relative_to(ROOT)}")
print("done")
