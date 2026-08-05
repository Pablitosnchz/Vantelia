"""Endpoints: seccion tracking (refactor F3).

Decoran directamente la app de backend.main para preservar el orden de
registro de rutas identico al monolito original.
"""
from __future__ import annotations

import hmac
import os
from urllib.parse import urlparse

from fastapi import (
    HTTPException,
    Request,
    Response,
)
from fastapi.responses import RedirectResponse


from api_models import *  # noqa: F401,F403
from backend import (
    outreach,
    settings,
)
from backend.outreach import outreach_verify_token  # noqa: F401
from backend.main import app

@app.get("/track/open/{token}.gif", include_in_schema=False)
def outreach_track_open(token: str, request: Request):
    if not outreach.OUTREACH_AVAILABLE or not outreach.OUTREACH_TRACKING_SECRET:
        return Response(content=outreach.OUTREACH_PIXEL_GIF, media_type="image/gif")
    parsed = outreach_verify_token(token, outreach.OUTREACH_TRACKING_SECRET)
    if parsed:
        email, stage = parsed
        try:
            with outreach._outreach_db() as conn:
                conn.execute(
                    "INSERT INTO events (email, type, stage, ts, ua, ip) VALUES (?,?,?,?,?,?)",
                    (email, "open", stage, outreach._outreach_now(),
                     request.headers.get("user-agent", "")[:300],
                     (request.client.host if request.client else "")[:64]),
                )
                conn.commit()
        except Exception:
            settings.logger.exception("Outreach open track error")
        # Pre-generar la demo personalizada en segundo plano: al hacer clic ya
        # estara lista (carga instantanea, aspecto legitimo).
        try:
            outreach._outreach_maybe_pregenerate_demo(email)
        except Exception:
            settings.logger.debug("pregen demo on open fallo", exc_info=True)
    return Response(
        content=outreach.OUTREACH_PIXEL_GIF,
        media_type="image/gif",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/track/click/{token}", include_in_schema=False)
def outreach_track_click(token: str, request: Request, u: str = ""):
    if not outreach.OUTREACH_AVAILABLE or not outreach.OUTREACH_TRACKING_SECRET:
        if u:
            return RedirectResponse(url=u, status_code=302)
        raise HTTPException(status_code=404, detail="not found")
    parsed = outreach_verify_token(token, outreach.OUTREACH_TRACKING_SECRET)
    if not parsed or not u:
        raise HTTPException(status_code=404, detail="not found")
    target = u
    try:
        host = urlparse(target).hostname or ""
    except Exception:
        host = ""
    if host and host.lower() not in outreach.OUTREACH_TRACKING_ALLOWED_HOSTS:
        # Permitir solo dominios propios para evitar open redirect.
        target = "https://www.vantelia.es"
    email, stage = parsed
    try:
        with outreach._outreach_db() as conn:
            conn.execute(
                "INSERT INTO events (email, type, stage, url, ts, ua, ip) VALUES (?,?,?,?,?,?,?)",
                (email, "click", stage, target[:500], outreach._outreach_now(),
                 request.headers.get("user-agent", "")[:300],
                 (request.client.host if request.client else "")[:64]),
            )
            conn.commit()
    except Exception:
        settings.logger.exception("Outreach click track error")
    return RedirectResponse(url=target, status_code=302)


def _demo_waiting_page(business: str, refresh_seconds: int = 4) -> str:
    """Pagina de espera con marca Vantelia mientras la demo se genera. Auto-refresca
    y redirige sola cuando esta lista. Aspecto profesional (no un loader tecnico)."""
    from html import escape as _esc

    name = _esc(business) if business else "tu negocio"
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{refresh_seconds}">
<title>Preparando tu asistente | Vantelia</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;
background:#0B132B;color:#fff;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;padding:24px}}
.card{{max-width:460px;text-align:center}}
.logo{{font-weight:800;font-size:22px;letter-spacing:.5px;background:linear-gradient(135deg,#00D1FF,#00F5D4);
-webkit-background-clip:text;background-clip:text;color:transparent;margin-bottom:28px}}
.ring{{width:64px;height:64px;margin:0 auto 26px;border:4px solid rgba(255,255,255,.12);
border-top-color:#00D1FF;border-radius:50%;animation:spin 1s linear infinite}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
h1{{font-size:22px;margin:0 0 12px}}p{{color:rgba(255,255,255,.66);line-height:1.6;margin:0 0 8px}}
.small{{font-size:13px;color:rgba(255,255,255,.4);margin-top:22px}}
</style></head><body><main class="card">
<div class="logo">VANTELIA</div>
<div class="ring"></div>
<h1>Estamos preparando el asistente de {name}</h1>
<p>Nuestra IA esta analizando la informacion para personalizar tu demo. Tarda unos segundos.</p>
<p>Esta pagina se actualizara sola en cuanto este lista.</p>
<div class="small">Si tarda demasiado, escribenos a info@vantelia.es</div>
</main></body></html>"""


@app.get("/demo/go/{token}", include_in_schema=False)
def outreach_demo_go(token: str, request: Request):
    """Destino del CTA del email. Si la demo del prospecto ya esta lista (pre-generada
    al abrir), redirige al instante a su asistente vivo. Si aun se genera, muestra una
    pagina de espera con marca que redirige sola. Sin web, cae al formulario clasico."""
    from fastapi.responses import HTMLResponse

    if not outreach.OUTREACH_AVAILABLE or not outreach.OUTREACH_TRACKING_SECRET:
        return RedirectResponse(url="https://www.vantelia.es/demo/", status_code=302)
    parsed = outreach_verify_token(token, outreach.OUTREACH_TRACKING_SECRET)
    if not parsed:
        return RedirectResponse(url="https://www.vantelia.es/demo/", status_code=302)
    email, stage = parsed
    # Registrar el clic (misma semantica que /track/click).
    try:
        with outreach._outreach_db() as conn:
            conn.execute(
                "INSERT INTO events (email, type, stage, url, ts, ua, ip) VALUES (?,?,?,'demo_go',?,?,?)",
                (email, "click", stage, outreach._outreach_now(),
                 request.headers.get("user-agent", "")[:300],
                 (request.client.host if request.client else "")[:64]),
            )
            conn.commit()
    except Exception:
        settings.logger.debug("demo_go click log fallo", exc_info=True)

    target = outreach._outreach_demo_target_for_email(email)
    if target["status"] == "ready":
        return RedirectResponse(url=target["demo_url"], status_code=302)
    if target["status"] == "form":
        return RedirectResponse(url=target.get("form_url") or "https://www.vantelia.es/demo/", status_code=302)
    # generating -> pagina de espera branded que se auto-refresca
    return HTMLResponse(content=_demo_waiting_page(target.get("business", "")),
                        headers={"Cache-Control": "no-store"})


@app.post("/webhooks/brevo", include_in_schema=False)
async def outreach_brevo_webhook(request: Request, key: str = ""):
    """Recibe eventos de rebote/queja de Brevo (canal de cold dedicado).

    Con SMTP dedicado los NDR NO llegan al buzon IMAP, asi que este webhook es
    el que alimenta el freno de rebotes. Seguridad: secreto en ?key= (Brevo no
    firma por defecto). Sin secreto configurado, el webhook queda deshabilitado.
    """
    secret = os.getenv("OUTREACH_BREVO_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="webhook no configurado")
    if not hmac.compare_digest(key or "", secret):
        raise HTTPException(status_code=403, detail="clave invalida")
    if not outreach.OUTREACH_AVAILABLE:
        return {"ok": True, "handled": False}
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="payload invalido")
    events = payload if isinstance(payload, list) else [payload]
    results = []
    for ev in events:
        if isinstance(ev, dict):
            try:
                results.append(outreach._outreach_process_brevo_event(ev))
            except Exception:
                settings.logger.exception("Error procesando evento Brevo")
    return {"ok": True, "processed": len(results), "results": results}


@app.get("/track/reply/{token}", include_in_schema=False)
def outreach_track_reply_intent(token: str, request: Request, u: str = ""):
    if not u.lower().startswith("mailto:"):
        raise HTTPException(status_code=404, detail="not found")
    if not outreach.OUTREACH_AVAILABLE or not outreach.OUTREACH_TRACKING_SECRET:
        return RedirectResponse(url=u, status_code=302)
    parsed = outreach_verify_token(token, outreach.OUTREACH_TRACKING_SECRET)
    if not parsed:
        raise HTTPException(status_code=404, detail="not found")
    email, stage = parsed
    try:
        with outreach._outreach_db() as conn:
            conn.execute(
                "INSERT INTO events (email, type, stage, url, ts, ua, ip) VALUES (?,?,?,?,?,?,?)",
                (email, "reply_intent", stage, u[:500], outreach._outreach_now(),
                 request.headers.get("user-agent", "")[:300],
                 (request.client.host if request.client else "")[:64]),
            )
            conn.execute(
                """UPDATE prospects SET status='engaged', updated_at=?
                   WHERE email=? AND status IN ('new','contacted')""",
                (outreach._outreach_now(), email),
            )
            conn.commit()
    except Exception:
        settings.logger.exception("Outreach reply intent track error")
    return RedirectResponse(url=u, status_code=302)




