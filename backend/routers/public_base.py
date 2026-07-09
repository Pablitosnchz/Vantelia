"""Endpoints: seccion public_base (refactor F3).

Decoran directamente la app de backend.main para preservar el orden de
registro de rutas identico al monolito original.
"""
from __future__ import annotations

from html import escape
from typing import Any, Dict, List

from fastapi import (
    HTTPException,
)
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse


from api_models import *  # noqa: F401,F403
from backend import (
    appstate,
    settings,
)
from backend.main import app

@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    favicon_candidates = [
        settings.BRAND_DIR / "favicon.png",
        settings.BRAND_DIR / "favicon_fondo.png",
    ]
    for candidate in favicon_candidates:
        if candidate.exists():
            return FileResponse(candidate)
    raise HTTPException(status_code=404, detail="Favicon no encontrado.")


LEGAL_DOCUMENTS = {
    "privacidad": "Politica de privacidad",
    "terminos": "Terminos de uso",
    "cookies": "Politica de cookies",
    "ia": "Aviso sobre IA",
}


def _render_legal_markdown(content: str) -> str:
    html_parts: List[str] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("# "):
            html_parts.append(f"<h1>{escape(line[2:].strip())}</h1>")
        elif line.startswith("## "):
            html_parts.append(f"<h2>{escape(line[3:].strip())}</h2>")
        elif line.startswith("- "):
            html_parts.append(f"<p class=\"bullet\">{escape(line[2:].strip())}</p>")
        else:
            html_parts.append(f"<p>{escape(line)}</p>")
    return "\n".join(html_parts)


def _legal_page_html(slug: str, title: str, content: str) -> str:
    nav = " ".join(
        f'<a class="{"active" if key == slug else ""}" href="/legal/{key}">{escape(label)}</a>'
        for key, label in LEGAL_DOCUMENTS.items()
    )
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(title)} - Vantelia</title>
  <style>
    :root {{ color-scheme: light; --ink: #111827; --muted: #667085; --line: #d8dee8; --brand: #00a3c7; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Inter, Arial, sans-serif; color: var(--ink); background: #f7f9fc; line-height: 1.65; }}
    header {{ background: #101828; color: white; padding: 28px clamp(18px, 5vw, 56px); }}
    header strong {{ display: block; font-size: 20px; }}
    nav {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }}
    nav a {{ color: white; border: 1px solid rgba(255,255,255,.22); border-radius: 6px; padding: 8px 10px; text-decoration: none; font-size: 14px; }}
    nav a.active {{ background: var(--brand); border-color: var(--brand); }}
    main {{ max-width: 920px; margin: 0 auto; padding: 34px clamp(18px, 5vw, 56px) 54px; background: white; min-height: calc(100vh - 130px); }}
    h1 {{ margin: 0 0 16px; font-size: clamp(30px, 5vw, 48px); line-height: 1.05; }}
    h2 {{ margin: 30px 0 8px; font-size: 20px; }}
    p {{ margin: 8px 0; }}
    .bullet::before {{ content: "- "; color: var(--brand); font-weight: 700; }}
    .notice {{ border: 1px solid var(--line); border-left: 4px solid var(--brand); border-radius: 6px; padding: 12px 14px; color: var(--muted); background: #fbfdff; }}
  </style>
</head>
<body>
  <header>
    <strong>Vantelia</strong>
    <nav>{nav}</nav>
  </header>
  <main>
    <div class="notice">Plantilla operativa inicial. Revisar con asesoria legal antes de publicarla como version definitiva.</div>
    {_render_legal_markdown(content)}
  </main>
</body>
</html>"""


@app.get("/legal", include_in_schema=False)
async def legal_index() -> RedirectResponse:
    return RedirectResponse("/legal/privacidad", status_code=302)


@app.get("/legal/{documento}", include_in_schema=False)
async def legal_document(documento: str) -> HTMLResponse:
    slug = documento.strip().lower()
    title = LEGAL_DOCUMENTS.get(slug)
    if not title:
        raise HTTPException(status_code=404, detail="Documento legal no encontrado.")
    path = settings.LEGAL_DIR / f"{slug}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Documento legal no configurado.")
    return HTMLResponse(_legal_page_html(slug, title, path.read_text(encoding="utf-8")))

























# ---------------------------------------------------------------------------
# Catalogo de servicios (duracion + precio) por cliente
# ---------------------------------------------------------------------------

























































# --- Vantelia 2.0 self-serve helpers (Sem 2) ---







# --- Google OAuth helpers ---













# --- Onboarding state (transient, lives in user row's metadata or memory) ---
# We store wizard state in the clientes row's config_json as a `_onboarding_state`
# key while the user has not finalized. On finalize we strip it.














































































































































































































































































# Defaults de descripcion/servicios por sector cuando no hay scraping ni datos.
# El scraping de la web sobrescribe esto; el fallback generico cubre sectores no listados.














# Bloque de "llamada simulada" por voz para la pagina de demo. Se inyecta como VALOR
# en el f-string de _build_demo_page (por eso usa llaves simples sin escapar) y trae su
# propio <style>, el overlay tipo pantalla de llamada y el JS WebRTC. Placeholders:
# __VOICE_CFG__ (objeto JS con api/cliente), __NOMBRE__, __INITIAL__, __COLOR__.



































































































































































































# Alfabeto sin caracteres ambiguos (sin 0/O, 1/I/L) para el numero de reserva
# que el cliente dicta por telefono o teclea en chat.


























































































































# ---------------------------------------------------------------------------
# Datos de demostracion para la agenda (solo admin)
# ---------------------------------------------------------------------------


















































































@app.get("/")
async def root() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": app.title,
        "version": app.version,
        "clientes_activos": sorted(appstate.CONFIG_CLIENTES.keys()),
    }


