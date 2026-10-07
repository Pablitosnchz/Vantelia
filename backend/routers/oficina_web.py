"""La oficina en el panel (backend/oficina.py y backend/setter.py). Solo admin.

- `/oficina`: la sala (admin_ui/oficina.html). La pagina no lleva datos: los pide a
  `/admin/oficina/estado` con la sesion, y pintarla no llama a ningun modelo.
- `/admin/oficina/*`: la bandeja de Pablo, el interruptor de Marta, mover una llamada, el
  resultado tras la llamada, los huecos libres y las recargas que apunta Pablo.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Cookie, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

from backend import oficina, security, settings, setter, timeutils
from backend.main import app

_ADMIN = [Depends(security._require_admin_token)]


async def _json(request: Request) -> Dict[str, Any]:
    try:
        datos = await request.json()
    except Exception:  # noqa: BLE001
        datos = {}
    return datos if isinstance(datos, dict) else {}


@app.get("/oficina", include_in_schema=False)
async def oficina_pagina(
    portal_session: Optional[str] = Cookie(default=None, alias=settings.PORTAL_COOKIE_NAME),
) -> Response:
    user = security._get_authenticated_portal_user_or_none(portal_session)
    if not user:
        return RedirectResponse("/acceso?next=/oficina")
    if user["role"] != "admin":
        return RedirectResponse("/app")
    pagina = settings.ADMIN_UI_DIR / "oficina.html"
    if not pagina.exists():
        raise HTTPException(status_code=404, detail="Pagina no disponible.")
    return FileResponse(pagina, headers={"Cache-Control": "no-store"})


@app.get("/admin/oficina/estado", dependencies=_ADMIN, include_in_schema=False)
async def admin_oficina_estado() -> Dict[str, Any]:
    return await timeutils._to_thread(oficina.estado)


@app.get("/admin/oficina/escaparate", dependencies=_ADMIN, include_in_schema=False)
async def admin_oficina_escaparate() -> Dict[str, Any]:
    """La sala sin un solo dato de clientes ni prospectos, para grabarla."""
    return await timeutils._to_thread(oficina.escaparate)


@app.post("/admin/oficina/bandeja/{propuesta_id}", dependencies=_ADMIN, include_in_schema=False)
async def admin_oficina_bandeja(propuesta_id: str, request: Request) -> Dict[str, Any]:
    datos = await _json(request)
    accion = str(datos.get("accion") or "")
    if accion not in ("aprobar", "rechazar"):
        raise HTTPException(status_code=400, detail="Accion no valida: aprobar o rechazar.")
    return await timeutils._to_thread(oficina.resolver, propuesta_id, accion, str(datos.get("texto") or ""),
                                      str(datos.get("motivo") or ""))


@app.put("/admin/oficina/setter", dependencies=_ADMIN, include_in_schema=False)
async def admin_oficina_setter(request: Request) -> Dict[str, Any]:
    datos = await _json(request)
    if "encendida" not in datos:
        raise HTTPException(status_code=400, detail="Indica 'encendida' (true o false).")
    return await timeutils._to_thread(setter.guardar_config, encendida=bool(datos["encendida"]))


@app.post("/admin/oficina/setter/importar", dependencies=_ADMIN, include_in_schema=False)
async def admin_oficina_setter_importar() -> Dict[str, Any]:
    """Los leads ya cualificados que aun no tiene Marta: su primer correo, a la bandeja."""
    ids = await timeutils._to_thread(setter.importar_cualificados)
    return {"importados": len(ids), "ids": ids}


@app.get("/admin/oficina/huecos", dependencies=_ADMIN, include_in_schema=False)
async def admin_oficina_huecos() -> Dict[str, Any]:
    libres = await timeutils._to_thread(setter.huecos)
    return {"huecos": [{"valor": setter.hueco_en_url(h), "texto": setter.dia_y_hora(h)}
                       for h in setter._redondas(libres)][:60]}


@app.post("/admin/oficina/reuniones/{lead_id}/mover", dependencies=_ADMIN, include_in_schema=False)
async def admin_oficina_mover(lead_id: str, request: Request) -> Dict[str, Any]:
    """Con `hora` ("2026-10-09T10:30"), se mueve ahi; sin ella, Marta le pide que elija otra."""
    datos = await _json(request)
    nueva = setter.hueco_de_url(str(datos.get("hora") or "")) if datos.get("hora") else None
    if datos.get("hora") and nueva is None:
        raise HTTPException(status_code=400, detail="Hora no valida.")
    await timeutils._to_thread(setter.ocupado_en_calendario)
    return await setter.mover(lead_id, nueva=nueva, request=request)


@app.post("/admin/oficina/reuniones/{lead_id}/resultado", dependencies=_ADMIN, include_in_schema=False)
async def admin_oficina_resultado(lead_id: str, request: Request) -> Dict[str, Any]:
    datos = await _json(request)
    resultado = str(datos.get("resultado") or "")
    if resultado not in ("ganado", "seguir", "perdido", "no_vino"):
        raise HTTPException(status_code=400, detail="Resultado no valido: ganado, seguir, perdido o no_vino.")
    return await timeutils._to_thread(setter.marcar_resultado, lead_id, resultado)


@app.post("/admin/oficina/leads/{lead_id}/parar", dependencies=_ADMIN, include_in_schema=False)
async def admin_oficina_parar(lead_id: str) -> Dict[str, Any]:
    return {"ok": await timeutils._to_thread(setter.parar_a_mano, lead_id)}


@app.post("/admin/oficina/saldo", dependencies=_ADMIN, include_in_schema=False)
async def admin_oficina_saldo(request: Request) -> Dict[str, Any]:
    """Pablo apunta lo que recarga en OpenAI (su saldo no se puede leer por API)."""
    datos = await _json(request)
    try:
        euros = float(datos.get("euros"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Indica los euros recargados.")
    hecho = await timeutils._to_thread(oficina.apuntar_recarga, str(datos.get("proveedor") or ""), euros)
    if not hecho.get("ok"):
        raise HTTPException(status_code=400, detail="Solo se apuntan recargas de OpenAI, en euros.")
    return hecho


@app.post("/admin/oficina/saldos/revisar", dependencies=_ADMIN, include_in_schema=False)
async def admin_oficina_revisar_saldos() -> Dict[str, Any]:
    return {"saldos": await timeutils._to_thread(oficina.revisar_saldos)}
