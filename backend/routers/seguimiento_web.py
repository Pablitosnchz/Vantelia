"""Endpoints del seguimiento tras la demo (backend/seguimiento_demo.py).

- `/interes/{token}`: la pagina "¿Te ha gustado la demo?" de los correos y SMS de Pablo.
- `/interes/demo/{cliente_id}`: el boton "Me interesa" de cada demo.
- `/admin/captacion/seguimiento*`: el panel (leads cualificados, embudo, interruptor).

Abrir una pagina no escribe ni cuenta nada (los antivirus de correo abren los enlaces): solo
enviar el formulario (POST). Decoran directamente la app de backend.main, como el resto de
routers; este se importa el ultimo.
"""
from __future__ import annotations

import threading
from html import escape
from typing import Any, Dict
from urllib.parse import parse_qs

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from backend import security, seguimiento_demo, settings, textnorm, timeutils
from backend.main import app

_ESTILO = """
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:#0B132B;color:#fff;
font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;padding:20px 16px;display:flex;justify-content:center}
main{width:100%;max-width:520px}
.logo{font-weight:800;font-size:20px;letter-spacing:.5px;background:linear-gradient(135deg,#00D1FF,#00F5D4);
-webkit-background-clip:text;background-clip:text;color:transparent;margin:6px 0 22px}
h1{font-size:23px;line-height:1.3;margin:0 0 10px}p{color:rgba(255,255,255,.75);line-height:1.6;margin:0 0 14px}
.botones{display:flex;flex-direction:column;gap:10px;margin:22px 0}
.boton{display:block;text-align:center;padding:14px 18px;border-radius:12px;font-weight:700;text-decoration:none;
font-size:16px;font-family:inherit;border:0;cursor:pointer;width:100%}
.si{background:linear-gradient(135deg,#00D1FF,#00F5D4);color:#04101C}
.no{background:transparent;color:rgba(255,255,255,.8);border:1px solid rgba(255,255,255,.25)}
.enlace{color:#00D1FF}
form{display:flex;flex-direction:column;gap:14px;margin-top:8px}
label,legend{font-size:14px;color:rgba(255,255,255,.85);display:flex;flex-direction:column;gap:6px}
fieldset{border:0;padding:0;margin:0;display:flex;flex-direction:column;gap:8px}
input,select,textarea{font:inherit;font-size:16px;padding:11px 12px;border-radius:10px;
border:1px solid rgba(255,255,255,.2);background:rgba(255,255,255,.06);color:#fff;width:100%}
select option{color:#000}
.opcion{flex-direction:row;align-items:center;gap:10px;padding:10px 12px;border:1px solid rgba(255,255,255,.15);
border-radius:10px}.opcion input{width:auto}
.trampa{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden}
.error{background:rgba(255,90,90,.15);border:1px solid rgba(255,90,90,.4);padding:10px 12px;border-radius:10px;color:#fff}
.pie{font-size:12px;color:rgba(255,255,255,.4);margin-top:26px}
"""
_CONSULTAS = "https://www.vantelia.es/consultas/"


def _pagina(titulo: str, cuerpo: str, estado: int = 200) -> HTMLResponse:
    html = ("<!doctype html><html lang='es'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<meta name='robots' content='noindex, nofollow'>"
            "<title>%s | Vantelia</title><style>%s</style></head><body><main>"
            "<div class='logo'>VANTELIA</div>%s"
            "<p class='pie'>Vantelia · recepcionistas con IA para negocios con citas · "
            "<a class='enlace' href='mailto:info@vantelia.es'>info@vantelia.es</a></p>"
            "</main></body></html>" % (escape(titulo), _ESTILO, cuerpo))
    return HTMLResponse(content=html, status_code=estado, headers={"Cache-Control": "no-store"})


def _no_vale() -> HTMLResponse:
    return _pagina("Enlace no válido", "<h1>Este enlace no es válido</h1><p>Escríbenos a "
                   "<a class='enlace' href='mailto:info@vantelia.es'>info@vantelia.es</a> y te ayudamos.</p>", 404)


def _trampa() -> str:
    return ("<div class='trampa' aria-hidden='true'><label>Web<input name='web' tabindex='-1' "
            "autocomplete='off'></label></div>")


def _formulario_si(accion: str, datos: Dict[str, Any], error: str = "") -> str:
    opciones = "".join("<option value='%s'>%s</option>" % (escape(o, quote=True), escape(o[:1].upper() + o[1:]))
                       for o in seguimiento_demo.huecos_para_elegir())
    return (
        "<h1>Genial. ¿Cómo te lo enseñamos?</h1>"
        "<p>Son 15 minutos: Pablo, el fundador, te enseña la recepcionista de %s montada con vuestra agenda.</p>"
        "%s<form method='post' action='%s'><input type='hidden' name='r' value='si'>%s"
        "<label>Tu nombre<input name='nombre' maxlength='80' autocomplete='name' value='%s'></label>"
        "<fieldset><legend>¿Cómo prefieres?</legend>"
        "<label class='opcion'><input type='radio' name='como' value='telefono' checked> Por teléfono</label>"
        "<label class='opcion'><input type='radio' name='como' value='video'> Por videollamada</label>"
        "<label class='opcion'><input type='radio' name='como' value='email'> Mejor por correo</label></fieldset>"
        "<label>¿Cuándo te viene bien?<select name='cuando'>%s</select></label>"
        "<label>Teléfono<input name='telefono' type='tel' maxlength='20' autocomplete='tel' value='%s'></label>"
        "<label>Email<input name='email' type='email' maxlength='200' autocomplete='email' value='%s'></label>"
        "<label>¿Algo que quieras preguntar? (opcional)<textarea name='pregunta' rows='3' maxlength='600'></textarea></label>"
        "<button class='boton si' type='submit'>Quiero saber más</button></form>"
        % (escape(datos["negocio"]), ("<p class='error'>%s</p>" % escape(error)) if error else "",
           escape(accion, quote=True), _trampa(), escape(datos.get("nombre") or "", quote=True), opciones,
           escape(datos.get("telefono") or "", quote=True), escape(datos.get("email") or "", quote=True)))


def _formulario_no(accion: str) -> str:
    motivos = "".join("<label class='opcion'><input type='radio' name='motivo' value='%s'> %s</label>"
                      % (escape(clave), escape(texto)) for clave, texto in seguimiento_demo.OPCIONES_NO.items())
    return (
        "<h1>Sin problema</h1><p>¿Nos dices por qué? Nos ayuda a mejorar (es opcional).</p>"
        "<form method='post' action='%s'><input type='hidden' name='r' value='no'>%s"
        "<fieldset>%s</fieldset>"
        "<label>¿Algo más? (opcional)<textarea name='detalle' rows='2' maxlength='300'></textarea></label>"
        "<button class='boton no' type='submit'>Enviar</button></form>"
        "<p class='pie'>No os volveremos a escribir.</p>" % (escape(accion, quote=True), _trampa(), motivos))


def _eleccion(token: str, datos: Dict[str, Any]) -> str:
    demo = ("<p>¿Aún no la has probado? <a class='enlace' href='%s'>Abre la demo de %s</a> y pídele una cita "
            "como lo haría un cliente.</p>" % (escape(datos["enlace_demo"], quote=True), escape(datos["negocio"]))
            if datos.get("enlace_demo") else "")
    return ("<h1>¿Qué te ha parecido la demo de %s?</h1>%s<div class='botones'>"
            "<a class='boton si' href='/interes/%s?r=si'>Me gusta, quiero saber más</a>"
            "<a class='boton no' href='/interes/%s?r=no'>Ahora no me interesa</a></div>"
            % (escape(datos["negocio"]), demo, escape(token), escape(token)))


def _ya_apuntado(datos: Dict[str, Any]) -> HTMLResponse:
    return _pagina("Hecho", "<h1>Ya lo tenemos apuntado</h1><p>Pablo te contacta muy pronto. ¡Gracias!</p>"
                   + _seguir_probando(datos))


def _seguir_probando(datos: Dict[str, Any]) -> str:
    if not datos.get("enlace_demo"):
        return ""
    return ("<p>Mientras, puedes seguir probándola: <a class='enlace' href='%s'>abrir la demo de %s</a>.</p>"
            % (escape(datos["enlace_demo"], quote=True), escape(datos["negocio"])))


async def _leer_formulario(request: Request) -> Dict[str, str]:
    """El formulario (application/x-www-form-urlencoded) sin python-multipart."""
    client_ip = request.client.host if request.client else "unknown"
    security._check_rate_limit("interes:%s" % client_ip, 10)
    crudo = (await request.body())[:8000].decode("utf-8", errors="replace")
    return {clave: valores[0] for clave, valores in parse_qs(crudo, keep_blank_values=True).items() if valores}


def _falta_contacto(datos: Dict[str, str]) -> bool:
    telefono = textnorm._sanitize_text(datos.get("telefono") or "")
    email = textnorm._sanitize_text(datos.get("email") or "").lower()
    return not (seguimiento_demo.captacion_voz.telefono_e164(telefono) or seguimiento_demo._EMAIL.match(email))


def _gracias(resultado: str, datos: Dict[str, str], datos_pagina: Dict[str, Any]) -> HTMLResponse:
    if resultado == "descartado" or datos.get("r") == "no":
        return _pagina("Gracias", "<h1>Gracias por decírnoslo</h1><p>No os volveremos a escribir. Si algún día "
                       "cambias de idea, escríbenos a <a class='enlace' href='mailto:info@vantelia.es'>"
                       "info@vantelia.es</a>.</p>")
    if resultado == "ya":
        return _ya_apuntado(datos_pagina)
    cuando = textnorm._sanitize_text(datos.get("cuando") or "")
    return _pagina("Hecho", "<h1>¡Hecho!</h1><p>Pablo te contacta %s.</p>%s"
                   % (escape(cuando) if cuando and not cuando.startswith("cuando sea") else "muy pronto",
                      _seguir_probando(datos_pagina)))


# --- Desde los correos y SMS de Pablo ------------------------------------------------------------

@app.get("/interes/demo/{cliente_id}", include_in_schema=False)
async def interes_desde_la_demo(cliente_id: str) -> HTMLResponse:
    """El boton "Me interesa" de una demo: el formulario. No apunta nada hasta enviarlo."""
    if not settings.CLIENT_ID_PATTERN.match(cliente_id or "") or not cliente_id.startswith("demo_auto_"):
        return RedirectResponse(url=_CONSULTAS, status_code=303)
    datos = await timeutils._to_thread(seguimiento_demo.datos_de_la_demo, cliente_id)
    if not datos:
        return RedirectResponse(url=_CONSULTAS, status_code=303)
    if datos["estado"] == "cualificado":
        return _ya_apuntado(datos)
    return _pagina("Me interesa", _formulario_si("/interes/demo/%s" % cliente_id, datos))


@app.post("/interes/demo/{cliente_id}", include_in_schema=False)
async def interes_desde_la_demo_respuesta(cliente_id: str, request: Request) -> HTMLResponse:
    if not settings.CLIENT_ID_PATTERN.match(cliente_id or "") or not cliente_id.startswith("demo_auto_"):
        return _no_vale()
    datos = await _leer_formulario(request)
    datos_pagina = await timeutils._to_thread(seguimiento_demo.datos_de_la_demo, cliente_id)
    if not datos_pagina:
        return _no_vale()
    if datos.get("web"):
        # El campo trampa solo lo rellena un bot: se le dan las gracias y no se apunta nada.
        return _pagina("Gracias", "<h1>¡Gracias!</h1><p>Lo tenemos.</p>")
    datos["r"] = "si"
    if _falta_contacto(datos):
        return _pagina("Me interesa", _formulario_si("/interes/demo/%s" % cliente_id, dict(
            datos_pagina, nombre=datos.get("nombre") or ""), "Déjanos un teléfono o un email para poder contactarte."),
            400)
    seg_id = await timeutils._to_thread(seguimiento_demo.seguimiento_para_demo, cliente_id)
    if not seg_id:
        return _no_vale()
    resultado = await timeutils._to_thread(seguimiento_demo.respuesta_del_formulario, seg_id, datos)
    return _gracias(resultado, datos, datos_pagina)


@app.get("/interes/{token}", include_in_schema=False)
async def interes_pagina(token: str, r: str = "") -> HTMLResponse:
    seg_id = seguimiento_demo.id_del_token(token)
    datos = await timeutils._to_thread(seguimiento_demo.para_la_pagina, seg_id) if seg_id else {}
    if not datos:
        return _no_vale()
    if datos["estado"] == "cualificado":
        return _ya_apuntado(datos)
    if r == "no":
        return _pagina("Ahora no", _formulario_no("/interes/%s" % token))
    if r == "si":
        return _pagina("Me interesa", _formulario_si("/interes/%s" % token, datos))
    if datos["estado"] == "descartado":
        return _pagina("Hecho", "<h1>No os volveremos a escribir</h1><p>¿Has cambiado de idea? "
                       "<a class='enlace' href='/interes/%s?r=si'>Cuéntanos cuándo te viene bien</a>.</p>"
                       % escape(token))
    return _pagina("¿Te ha gustado?", _eleccion(token, datos))


@app.post("/interes/{token}", include_in_schema=False)
async def interes_respuesta(token: str, request: Request) -> HTMLResponse:
    datos = await _leer_formulario(request)
    seg_id = seguimiento_demo.id_del_token(token)
    datos_pagina = await timeutils._to_thread(seguimiento_demo.para_la_pagina, seg_id) if seg_id else {}
    if not datos_pagina:
        return _no_vale()
    if datos.get("web"):
        return _pagina("Gracias", "<h1>¡Gracias!</h1><p>Lo tenemos.</p>")
    if datos.get("r") != "no":
        datos["r"] = "si"
        if _falta_contacto(datos):
            return _pagina("Me interesa", _formulario_si("/interes/%s" % token, dict(
                datos_pagina, nombre=datos.get("nombre") or datos_pagina.get("nombre")),
                "Déjanos un teléfono o un email para poder contactarte."), 400)
    resultado = await timeutils._to_thread(seguimiento_demo.respuesta_del_formulario, seg_id, datos)
    return _gracias(resultado, datos, datos_pagina)


# --- Panel ---------------------------------------------------------------------------------------

@app.get("/admin/captacion/seguimiento", dependencies=[Depends(security._require_admin_token)])
async def admin_seguimiento() -> Dict[str, Any]:
    """Leads cualificados, embudo de los ultimos 30 dias, quien esta en seguimiento y el interruptor."""
    return await timeutils._to_thread(seguimiento_demo.resumen)


@app.put("/admin/captacion/seguimiento/config", dependencies=[Depends(security._require_admin_token)])
async def admin_seguimiento_config(request: Request) -> Dict[str, Any]:
    try:
        datos = await request.json()
    except Exception:  # noqa: BLE001
        datos = {}
    if not isinstance(datos, dict) or "encendido" not in datos:
        raise HTTPException(status_code=400, detail="Indica 'encendido' (true o false).")
    return await timeutils._to_thread(seguimiento_demo.guardar_config, encendido=bool(datos["encendido"]))


@app.post("/admin/captacion/seguimiento/ronda", dependencies=[Depends(security._require_admin_token)])
async def admin_seguimiento_ronda() -> Dict[str, Any]:
    """Una vuelta ahora. Senales, inscripciones y recordatorios en el momento; los toques salen
    en segundo plano (con el espaciado de siempre entre correos, pueden tardar minutos)."""
    senales = await timeutils._to_thread(seguimiento_demo.procesar_senales)
    inscritos = await timeutils._to_thread(seguimiento_demo.inscribir_a_quien_la_usa)
    recordatorios = await timeutils._to_thread(seguimiento_demo.recordar)
    threading.Thread(target=seguimiento_demo.ronda, name="vantelia-seguimiento-manual", daemon=True).start()
    return {"senales": senales, "inscritos": inscritos, "recordatorios": recordatorios,
            "ronda": {"motivo": "en_marcha"}}


@app.get("/admin/captacion/seguimiento/vista-previa", dependencies=[Depends(security._require_admin_token)])
async def admin_seguimiento_vista_previa() -> Dict[str, Any]:
    """Los correos y SMS tal cual salen, con un negocio de ejemplo."""
    return {"toques": await timeutils._to_thread(seguimiento_demo.vista_previa)}


@app.get("/admin/captacion/seguimiento/{seg_id}/ficha", dependencies=[Depends(security._require_admin_token)])
async def admin_seguimiento_ficha(seg_id: str) -> Dict[str, Any]:
    datos = await timeutils._to_thread(seguimiento_demo.ficha, seg_id)
    if not datos:
        raise HTTPException(status_code=404, detail="No existe ese seguimiento.")
    asunto, _texto, html = seguimiento_demo.aviso(datos)
    return dict(datos, asunto=asunto, html=html)


@app.post("/admin/captacion/seguimiento/{seg_id}/accion", dependencies=[Depends(security._require_admin_token)])
async def admin_seguimiento_accion(seg_id: str, request: Request) -> Dict[str, Any]:
    """parar (deja de escribirle), cualificar (lo pasas tu a lead: sin correo, con oportunidad) o
    descartar (no le interesa: baja de correo y de llamadas)."""
    try:
        datos = await request.json()
    except Exception:  # noqa: BLE001
        datos = {}
    accion = str((datos or {}).get("accion") or "")
    if await timeutils._to_thread(seguimiento_demo._fila, seg_id) is None:
        raise HTTPException(status_code=404, detail="No existe ese seguimiento.")
    if accion == "parar":
        hecho = await timeutils._to_thread(seguimiento_demo.parar_a_mano, seg_id)
    elif accion == "cualificar":
        hecho = await timeutils._to_thread(
            lambda: seguimiento_demo.cualificar(seg_id, por="pablo", detalle="Cualificado a mano", avisar=False))
    elif accion == "descartar":
        hecho = await timeutils._to_thread(
            lambda: seguimiento_demo.descartar(seg_id, motivo="otro", detalle="Descartado a mano desde el panel"))
    else:
        raise HTTPException(status_code=400, detail="Accion no valida: parar, cualificar o descartar.")
    return {"ok": True, "hecho": bool(hecho)}
