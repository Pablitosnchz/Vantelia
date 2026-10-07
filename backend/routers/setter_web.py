"""La pagina de reserva de la setter (backend/setter.py): `/reunion/{token}`.

Los botones de hora de los correos de Marta llevan aqui con la hora marcada. Abrir la pagina
NO reserva nada (los antivirus de correo abren los enlaces): se reserva al pulsar "Sí,
llámame" (POST). Decora directamente la app de backend.main; se importa tras seguimiento_web.
"""
from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Dict, List, Optional

from fastapi import Request
from fastapi.responses import HTMLResponse, Response

from backend import captacion_voz, setter, textnorm, timeutils
from backend.main import app
from backend.routers import seguimiento_web

_ESTILO_HORAS = """
<style>
.dia{margin:14px 0 6px;font-size:14px;color:rgba(255,255,255,.85);font-weight:700;text-transform:capitalize}
.horas{display:flex;flex-wrap:wrap;gap:8px}
.hora{position:relative}
.hora input{position:absolute;opacity:0;width:1px;height:1px}
.hora span{display:inline-block;padding:9px 13px;border-radius:999px;border:1px solid rgba(255,255,255,.25);
font-variant-numeric:tabular-nums;cursor:pointer}
.hora input:checked + span{background:linear-gradient(135deg,#00D1FF,#00F5D4);color:#04101C;border-color:transparent;
font-weight:700}
.hora input:focus-visible + span{outline:2px solid #00D1FF;outline-offset:2px}
.elegida{font-size:18px;color:#fff;margin:0 0 6px}
</style>
"""


def _lead_del_token(token: str):
    lead_id = setter.id_del_token(token)
    return setter._lead(lead_id) if lead_id else None


def _horas_por_dia(libres: List[datetime]) -> Dict[str, List[datetime]]:
    """Solo las en punto y las y media: con las de cada cuarto la lista abruma."""
    grupos: Dict[str, List[datetime]] = {}
    for momento in setter._redondas(libres):
        local = setter._local(momento)
        etiqueta = "%s %d de %s" % (setter._DIAS[local.weekday()], local.day, setter._MESES[local.month - 1])
        grupos.setdefault(etiqueta, []).append(momento)
    return grupos


def _formulario(lead, libres: List[datetime], elegida: Optional[datetime], error: str = "") -> str:
    accion = "/reunion/%s" % escape(setter.token_de(lead["id"]), quote=True)
    if elegida is not None:
        titulo = "<h1>¿Te llamo el %s?</h1>" % escape(setter.dia_y_hora(elegida))
    else:
        titulo = "<h1>¿Cuándo te llamo?</h1>"
    explicacion = ("<p>Son 15 minutos: Pablo, el fundador de Vantelia, te llama y te enseña cómo quedaría la "
                   "recepcionista de %s con vuestra agenda.</p>" % escape(lead["negocio"] or "vuestro negocio"))
    aviso = "<p class='error'>%s</p>" % escape(error) if error else ""
    if not libres:
        return (titulo + explicacion + aviso + "<p>Ahora mismo no me quedan huecos libres en la agenda. Escríbeme a "
                "<a class='enlace' href='mailto:info@vantelia.es'>info@vantelia.es</a> y lo cuadramos.</p>")
    grupos = []
    for dia, horas in _horas_por_dia(libres).items():
        botones = "".join(
            "<label class='hora'><input type='radio' name='h' value='%s'%s><span>%s</span></label>" % (
                escape(setter.hueco_en_url(h), quote=True), " checked" if elegida is not None and h == elegida else "",
                escape(setter._local(h).strftime("%H:%M"))) for h in horas)
        grupos.append("<div class='dia'>%s</div><div class='horas'>%s</div>" % (escape(dia), botones))
    telefono = escape(lead["telefono"] or "", quote=True)
    return (
        _ESTILO_HORAS + titulo + explicacion + aviso +
        "<form method='post' action='%s'>%s"
        "<fieldset><legend>%s</legend>%s</fieldset>"
        "<label>¿A qué número te llamo?<input name='telefono' type='tel' autocomplete='tel' required value='%s' "
        "placeholder='600 000 000'></label>"
        "<button class='boton si' type='submit'>Sí, llámame entonces</button></form>"
        % (accion, seguimiento_web._trampa(), "Elige otra hora si te viene mejor:" if elegida else "Elige la hora:",
           "".join(grupos), telefono))


def _ya_tiene(lead) -> HTMLResponse:
    from backend import booking

    cita = setter._cita(lead["booking_id"])
    gestion = booking._build_booking_manage_url(cita["manage_token"]) if cita is not None else ""
    inicio = setter._dt(lead["cita_inicio"])
    cuerpo = "<h1>Ya tienes la llamada</h1><p>Te llamo el %s.</p>" % escape(setter.dia_y_hora(inicio) if inicio else "")
    if gestion:
        cuerpo += "<p><a class='enlace' href='%s'>Cambiarla o cancelarla</a></p>" % escape(gestion, quote=True)
    cuerpo += "<p><a class='enlace' href='/reunion/%s/cita.ics'>Añadirla a mi calendario</a></p>" % escape(
        setter.token_de(lead["id"]), quote=True)
    return seguimiento_web._pagina("Tu llamada", cuerpo)


def _cerrado() -> HTMLResponse:
    return seguimiento_web._pagina("Vantelia", "<h1>Cuando quieras, aquí estamos</h1><p>Si te apetece que lo "
                                   "hablemos, escríbenos a <a class='enlace' href='mailto:info@vantelia.es'>"
                                   "info@vantelia.es</a> y te llamamos.</p>")


@app.get("/reunion/{token}", include_in_schema=False)
async def reunion_pagina(token: str, h: str = "") -> HTMLResponse:
    lead = await timeutils._to_thread(_lead_del_token, token)
    if lead is None:
        return seguimiento_web._no_vale()
    if lead["estado"] in ("descartado", "parado"):
        return _cerrado()
    if lead["estado"] == "reservado" and lead["booking_id"]:
        return _ya_tiene(lead)
    libres = await timeutils._to_thread(setter.huecos)
    elegida = setter.hueco_de_url(h)
    if elegida is not None and elegida not in libres:
        return seguimiento_web._pagina("¿Cuándo te llamo?", _formulario(
            lead, libres, None, "Esa hora ya no está libre. Elige otra, por favor."))
    return seguimiento_web._pagina("¿Cuándo te llamo?", _formulario(lead, libres, elegida))


@app.post("/reunion/{token}", include_in_schema=False)
async def reunion_reservar(token: str, request: Request) -> HTMLResponse:
    lead = await timeutils._to_thread(_lead_del_token, token)
    if lead is None:
        return seguimiento_web._no_vale()
    datos = await seguimiento_web._leer_formulario(request)
    if datos.get("web"):
        return seguimiento_web._no_vale()  # la trampa para robots
    if lead["estado"] in ("descartado", "parado"):
        return _cerrado()
    elegida = setter.hueco_de_url(datos.get("h") or "")
    telefono = captacion_voz.telefono_e164(textnorm._sanitize_text(datos.get("telefono") or ""))
    libres = await timeutils._to_thread(setter.huecos)
    if elegida is None:
        return seguimiento_web._pagina("¿Cuándo te llamo?", _formulario(lead, libres, None, "Elige una hora."))
    if not telefono:
        return seguimiento_web._pagina("¿Cuándo te llamo?", _formulario(
            lead, libres, elegida if elegida in libres else None, "Pon un teléfono para que Pablo te llame."))
    # Su calendario (si lo hay) se lee fuera del bucle; `reservar` lo encuentra ya en cache.
    await timeutils._to_thread(setter.ocupado_en_calendario)
    hecho = await setter.reservar(lead["id"], elegida, telefono=telefono, por="web")
    if hecho.get("motivo") == "ya_reservado":
        return _ya_tiene(setter._lead(lead["id"]))
    if not hecho.get("ok"):
        libres = await timeutils._to_thread(setter.huecos)
        return seguimiento_web._pagina("¿Cuándo te llamo?", _formulario(
            lead, libres, None, "Esa hora se acaba de ocupar. Elige otra, por favor."))
    inicio = setter._dt(hecho["inicio"])
    cuerpo = ("<h1>¡Hecho!</h1><p class='elegida'>Te llamo el %s.</p><p>Son 15 minutos. Te llega la confirmación "
              "por correo con la invitación para el calendario.</p>" % escape(setter.dia_y_hora(inicio)))
    if hecho.get("gestion"):
        cuerpo += "<p><a class='enlace' href='%s'>Si te surge algo, cámbiala aquí</a></p>" % escape(
            hecho["gestion"], quote=True)
    cuerpo += "<p><a class='enlace' href='/reunion/%s/cita.ics'>Añadirla a mi calendario</a></p>" % escape(
        setter.token_de(lead["id"]), quote=True)
    return seguimiento_web._pagina("Hecho", cuerpo)


@app.get("/reunion/{token}/cita.ics", include_in_schema=False)
async def reunion_ics(token: str) -> Response:
    lead = await timeutils._to_thread(_lead_del_token, token)
    inicio = setter._dt(lead["cita_inicio"]) if lead is not None else None
    if lead is None or lead["estado"] != "reservado" or inicio is None:
        return seguimiento_web._no_vale()
    ics = setter.invitacion(lead, inicio, para=lead["email"] or "lead@vantelia.es", metodo="PUBLISH",
                            secuencia=lead["secuencia"])
    return Response(content=ics, media_type="text/calendar",
                    headers={"Content-Disposition": "attachment; filename=llamada-vantelia.ics",
                             "Cache-Control": "no-store"})
