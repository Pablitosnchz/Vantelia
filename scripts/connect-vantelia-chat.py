"""Instala el asistente comercial de Vantelia en todas las paginas publicas."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SITE_ROOTS = (
    ROOT / "hostinger_site",
    ROOT / "site_exports" / "vantelia_static_clean",
)
WIDGET_VERSION = "20260605-sitewide"
WIDGET = f"""  <script
    src="https://app.vantelia.es/widget/widget.min.js?v={WIDGET_VERSION}"
    data-api="https://app.vantelia.es"
    data-client="Vantelia"
    data-position="right"></script>
"""

WIDGET_SCRIPT = re.compile(
    r"""[ \t]*<script
        (?=[^>]*\bsrc=["']https://app\.vantelia\.es/widget/widget\.min\.js(?:\?[^"']*)?["'])
        [^>]*>\s*</script>\s*
    """,
    re.IGNORECASE | re.VERBOSE,
)


def connect_chat(path: Path) -> bool:
    html = path.read_text(encoding="utf-8")
    updated = WIDGET_SCRIPT.sub("", html)
    body_closings = list(re.finditer(r"(?i)</body>", updated))
    if not body_closings:
        raise ValueError(f"No se encontro </body> en {path}")

    closing = body_closings[-1]
    updated = updated[: closing.start()] + WIDGET + updated[closing.start() :]
    if updated == html:
        return False

    path.write_text(updated, encoding="utf-8", newline="")
    return True


def main() -> None:
    changed = []
    for site_root in SITE_ROOTS:
        for path in sorted(site_root.rglob("*.html")):
            if connect_chat(path):
                changed.append(path.relative_to(ROOT))

    print(f"Chat Vantelia conectado en {len(changed)} paginas.")
    for path in changed:
        print(path)


if __name__ == "__main__":
    main()
