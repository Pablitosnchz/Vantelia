# -*- coding: utf-8 -*-
"""Marta, la setter: del "me interesa" a una llamada en la agenda de Pablo.

POR QUE EXISTE
--------------
Pablo (7-oct-2026): "quiero un setter de ventas". Los leads se cualificaban y ahi se paraba
todo hasta que Pablo escribia. Plan en docs/PLAN_OFICINA_IA.md.

Lo que NO puede pasar y vigilan estos tests:
- ofrecer una hora que la agenda no tiene, o reservar dos veces el mismo hueco;
- que abrir un enlace (un antivirus lo hace) reserve una llamada;
- escribir a quien dijo que no, o mas de tres correos;
- que una pregunta de precio la conteste la maquina sin que Pablo la vea;
- que los leads de antes de encenderla reciban un correo sin el OK de Pablo;
- que la oficina llame al modelo para pintarse, o que el escaparate ensene datos de nadie.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401
from test_captacion_voz import captacion, envios  # noqa: F401

# Octubre de 2026: Madrid = UTC+2. El lunes 12 es fiesta nacional.
MIERCOLES_1000 = datetime(2026, 10, 7, 8, 0, tzinfo=timezone.utc)
EMAIL = "info@sonrisa.es"
PABLO = "pablo@vantelia.test"


def _madrid(dia, hora, minuto=0):
    return datetime(2026, 10, dia, hora - 2, minuto, tzinfo=timezone.utc)


@pytest.fixture()
def st(captacion, envios, monkeypatch):  # noqa: F811
    """Base de captacion temporal, envios capturados, reloj fijo y la agenda de Pablo creada."""
    from backend import appstate, emailing, outreach, settings, setter, timeutils

    monkeypatch.setenv("OUTREACH_TRACKING_SECRET", "secreto-setter")
    monkeypatch.setenv("OUTREACH_TRACKING_BASE_URL", "https://app.test")
    monkeypatch.delenv("SETTER_ICAL_URL", raising=False)
    monkeypatch.setattr(settings, "CONSULTA_NOTIFICATION_EMAIL", PABLO)
    monkeypatch.setattr(outreach, "_outreach_smtp_health", lambda: {"ok": True})
    monkeypatch.setattr(outreach, "_outreach_wait_send_slot", lambda *a, **k: 0.0)
    reloj = {"ahora": MIERCOLES_1000}
    monkeypatch.setattr(timeutils, "_utc_now", lambda: reloj["ahora"])
    envios["pablo"] = []
    monkeypatch.setattr(emailing, "_send_email_object", lambda msg, *a: envios["pablo"].append(msg))
    monkeypatch.setattr(appstate, "SETTER_SINCRONO", True, raising=False)
    with appstate.state_lock:
        appstate.rate_limit_buckets.clear()
    setter._cache_ocupado.update(momento=None, intervalos=[])
    setter.asegurar_agenda()
    _limpiar_agenda()
    setter.guardar_config(encendida=True)
    setter._guardar_ajuste("desde", "2026-10-01T00:00:00+00:00")
    setter.reloj = reloj
    return setter


def _limpiar_agenda():
    from backend import db, setter

    with db._get_db_connection() as conn:
        conn.execute("DELETE FROM bookings WHERE cliente_id=?", (setter.AGENDA_ID,))
        conn.commit()


def _cualificado(email_=EMAIL, negocio="Clínica Sonrisa", cuando="", hilo="<demo@test>", telefono="911234567",
                 cualificado_en="2026-10-07T07:59:00+00:00", origen="llamada"):
    """Un lead que el seguimiento acaba de cualificar."""
    from backend import seguimiento_demo

    seg_id = seguimiento_demo.inscribir(origen=origen, canal="email", destino=email_, prospecto=email_,
                                        negocio=negocio, sector="clinica dental", contacto="Marta Ruiz",
                                        telefono=telefono, hilo=hilo, asunto_hilo="Lo que te conté por teléfono",
                                        aunque_no_se_le_escriba=True)
    with seguimiento_demo._conexion() as conn:
        conn.execute("UPDATE seguimiento_demo SET estado='cualificado', cualificado_en=?, cualificado_por='formulario', "
                     "preferencias=? WHERE id=?",
                     (cualificado_en, json.dumps({"cuando": cuando} if cuando else {}), seg_id))
        conn.commit()
    return seg_id


def _lead(st, email_=EMAIL):
    with st._conexion() as conn:
        return st._por_email(conn, email_)


def _correos_a(envios, destino):  # noqa: F811
    return [m for m in envios["email"] if m["To"] == destino]


def _cuerpo(mensaje) -> str:
    parte = mensaje.get_body(preferencelist=("plain",))
    return parte.get_content() if parte is not None else ""


def _enlaces_de_hora(texto: str):
    import re

    return re.findall(r"https://app\.test/reunion/(st_[^?\s]+)\?h=(\S+)", texto)


def _citas():
    from backend import db, setter

    with db._get_db_connection() as conn:
        return conn.execute("SELECT * FROM bookings WHERE cliente_id=? ORDER BY start_at", (setter.AGENDA_ID,)).fetchall()


# --- La agenda de Pablo -------------------------------------------------------------------------

def test_la_agenda_de_pablo_tiene_su_horario_y_solo_da_horas_con_margen(st):
    """De lunes a viernes, 10:00-13:30 y 16:00-18:00, nada antes de 2 horas, ni el 12 de octubre."""
    huecos = st.huecos(MIERCOLES_1000)
    assert huecos, "la agenda no da huecos"
    locales = [st._local(h) for h in huecos]
    assert min(huecos) >= MIERCOLES_1000 + timedelta(hours=2)
    for local in locales:
        minutos = local.hour * 60 + local.minute
        assert local.weekday() < 5
        assert (600 <= minutos < 810) or (960 <= minutos < 1080), local
        assert (local.month, local.day) != (10, 12)
    assert {(l.day, l.strftime("%H:%M")) for l in locales} >= {(7, "12:00"), (8, "10:00"), (8, "17:45")}
    # Crearla dos veces no duplica nada.
    assert st.asegurar_agenda() is False


def test_elegir_dos_da_otro_dia_y_otra_franja_y_respeta_lo_que_pidio(st):
    huecos = st.huecos(MIERCOLES_1000)
    a, b = st.elegir_dos(huecos, "", MIERCOLES_1000)
    assert st._local(a).strftime("%d %H:%M") == "07 12:00"
    assert st._local(b).date() != st._local(a).date() and st._franja(b) == "tarde"
    tarde = st.elegir_dos(huecos, "el viernes por la tarde", MIERCOLES_1000)
    assert [st._local(h).strftime("%d %H:%M") for h in tarde] == ["09 16:00", "09 17:00"]


# --- El primer contacto ----------------------------------------------------------------------------

def test_un_cualificado_recibe_dos_horas_en_menos_de_5_minutos(st, envios):  # noqa: F811
    _cualificado()
    st.ciclo(MIERCOLES_1000)
    correos = _correos_a(envios, EMAIL)
    assert len(correos) == 1
    mensaje = correos[0]
    assert mensaje["Subject"] == "Re: Lo que te conté por teléfono" and mensaje["In-Reply-To"] == "<demo@test>"
    texto = _cuerpo(mensaje)
    enlaces = _enlaces_de_hora(texto)
    assert len(enlaces) == 2 and "Hola, Marta:" in texto and "15 minutos" in texto
    assert "elige otra hora aquí" in texto
    lead = _lead(st)
    assert lead["estado"] == "ofrecido" and lead["paso"] == 1
    assert st._dt(lead["primer_contacto"]) - st._dt(lead["creado"]) < timedelta(minutes=5)
    # Una segunda vuelta no repite nada.
    st.ciclo(MIERCOLES_1000 + timedelta(minutes=1))
    assert len(_correos_a(envios, EMAIL)) == 1


def test_de_noche_espera_a_las_830_del_siguiente_laborable(st, envios):  # noqa: F811
    noche = datetime(2026, 10, 9, 20, 30, tzinfo=timezone.utc)  # viernes 22:30
    st.reloj["ahora"] = noche
    _cualificado(cualificado_en="2026-10-09T20:29:00+00:00")
    st.ciclo(noche)
    assert not _correos_a(envios, EMAIL)
    assert _lead(st)["proximo"] == "2026-10-13T06:30:00+00:00"  # martes 13 (el lunes 12 es fiesta)


def test_apagada_no_escribe_a_nadie(st, envios):  # noqa: F811
    st.guardar_config(encendida=False)
    _cualificado()
    st.ciclo(MIERCOLES_1000)
    assert not _correos_a(envios, EMAIL) and _lead(st) is None


def test_los_de_antes_de_encenderla_van_a_la_bandeja(st, envios):  # noqa: F811
    from backend import oficina

    _cualificado(cualificado_en="2026-09-30T10:00:00+00:00")
    st.ciclo(MIERCOLES_1000)
    assert _lead(st) is None, "uno de antes de encenderla entro solo"
    ids = st.importar_cualificados()
    assert len(ids) == 1 and _lead(st)["estado"] == "revision"
    st.ciclo(MIERCOLES_1000)
    assert not _correos_a(envios, EMAIL), "salio sin el OK de Pablo"
    pendientes = oficina.bandeja()
    assert len(pendientes) == 1 and pendientes[0]["tipo"] == "primer_correo"
    assert "Para que no se quede en el aire" in pendientes[0]["vista_previa"]["texto"]
    assert oficina.resolver(pendientes[0]["id"], "aprobar")["ok"] is True
    assert len(_correos_a(envios, EMAIL)) == 1 and _lead(st)["estado"] == "ofrecido"


# --- Reservar desde el enlace -------------------------------------------------------------------------

def _primer_enlace(st, envios):  # noqa: F811
    _cualificado()
    st.ciclo(MIERCOLES_1000)
    token, hora = _enlaces_de_hora(_cuerpo(_correos_a(envios, EMAIL)[0]))[0]
    return token, hora


def test_abrir_el_enlace_no_reserva_y_confirmar_si(st, envios, client):  # noqa: F811
    token, hora = _primer_enlace(st, envios)
    pagina = client.get("/reunion/%s?h=%s" % (token, hora))
    assert pagina.status_code == 200 and "¿Te llamo el miércoles 7 de octubre a las 12:00?" in pagina.text
    assert not _citas(), "abrir el enlace ha reservado"
    hecho = client.post("/reunion/%s" % token, data={"h": hora, "telefono": "600 111 222"})
    assert hecho.status_code == 200 and "¡Hecho!" in hecho.text
    citas = _citas()
    assert len(citas) == 1 and citas[0]["source"] == "setter" and citas[0]["telefono"] == "+34600111222"
    lead = _lead(st)
    assert lead["estado"] == "reservado" and lead["booking_id"] == citas[0]["id"]
    # Al lead: la confirmacion en su hilo con la invitacion; a Pablo: la suya.
    confirmacion = _correos_a(envios, EMAIL)[-1]
    assert "te llamo el miércoles 7 de octubre a las 12:00" in _cuerpo(confirmacion)
    assert any(p.get_content_type() == "text/calendar" for p in confirmacion.iter_attachments())
    assert envios["pablo"] and envios["pablo"][0]["To"] == PABLO
    assert any(p.get_content_type() == "text/calendar" for p in envios["pablo"][0].iter_attachments())
    # Volver a abrir el enlace: ya la tiene.
    assert "Ya tienes la llamada" in client.get("/reunion/%s" % token).text


def test_un_hueco_cogido_no_se_vuelve_a_dar(st, envios, client):  # noqa: F811
    token, hora = _primer_enlace(st, envios)
    _cualificado(email_="otra@clinica.es", hilo="<otra@test>", telefono="912222222")
    st.ciclo(MIERCOLES_1000)
    otro_token = _enlaces_de_hora(_cuerpo(_correos_a(envios, "otra@clinica.es")[0]))[0][0]
    assert client.post("/reunion/%s" % token, data={"h": hora, "telefono": "600111222"}).status_code == 200
    respuesta = client.post("/reunion/%s" % otro_token, data={"h": hora, "telefono": "600333444"})
    assert "se acaba de ocupar" in respuesta.text and len(_citas()) == 1
    assert hora not in [st.hueco_en_url(h) for h in st.huecos(MIERCOLES_1000)]


def test_enlace_con_firma_falsa_no_vale(st, client):  # noqa: F811
    assert client.get("/reunion/st_falsofalso.firma").status_code == 404


# --- Lo que contesta con sus palabras -----------------------------------------------------------------

def _respuesta(texto, email_=EMAIL):
    return {"email": email_, "subject": "Re: Lo que te conté por teléfono", "body_excerpt": texto}


def test_contesta_el_jueves_a_las_11_y_queda_reservado(st, envios):  # noqa: F811
    _primer_enlace(st, envios)
    assert st.al_responder(_respuesta("Perfecto, el jueves a las 11 me va bien.\n\nEl mié, Pablo escribió:\n> hola"))
    citas = _citas()
    assert len(citas) == 1 and (citas[0]["booking_date"], citas[0]["booking_time"]) == ("2026-10-08", "11:00")
    assert _lead(st)["estado"] == "reservado"


def test_contesta_el_viernes_por_la_tarde_y_le_propone_dos_horas_de_tarde(st, envios):  # noqa: F811
    _primer_enlace(st, envios)
    assert st.al_responder(_respuesta("Mejor el viernes por la tarde"))
    assert not _citas()
    texto = _cuerpo(_correos_a(envios, EMAIL)[-1])
    horas = [h for _, h in _enlaces_de_hora(texto)]
    assert horas == ["2026-10-09T16:00", "2026-10-09T17:00"]


def test_por_la_manana_no_es_manana(st):
    pide = st.lo_que_pide("por la mañana mejor", MIERCOLES_1000)
    assert pide == {"fecha": "", "franja": "mañana", "texto": "por la mañana mejor"}


def test_si_pregunta_el_precio_lo_ve_pablo_antes(st, envios):  # noqa: F811
    from backend import oficina

    _primer_enlace(st, envios)
    antes = len(_correos_a(envios, EMAIL))
    assert st.al_responder(_respuesta("¿Y cuánto cuesta al mes?"))
    assert len(_correos_a(envios, EMAIL)) == antes, "contesto sola a una pregunta de precio"
    pendientes = oficina.bandeja()
    assert pendientes and pendientes[0]["tipo"] == "respuesta" and pendientes[0]["borrador"]
    assert any("Marta necesita tu OK" in a[0] for a in envios["avisos"])
    assert oficina.resolver(pendientes[0]["id"], "aprobar", texto="Son 129 € al mes, con diez días gratis.")["ok"]
    ultimo = _cuerpo(_correos_a(envios, EMAIL)[-1])
    assert "Son 129 € al mes" in ultimo and len(_enlaces_de_hora(ultimo)) == 2


def test_si_dice_que_no_se_para(st, envios):  # noqa: F811
    _primer_enlace(st, envios)
    assert st.al_responder(_respuesta("No nos interesa, gracias")) is False
    assert _lead(st)["estado"] == "descartado"
    st.ciclo(MIERCOLES_1000 + timedelta(days=5))
    assert len(_correos_a(envios, EMAIL)) == 1


def test_una_respuesta_automatica_no_hace_nada(st, envios):  # noqa: F811
    _primer_enlace(st, envios)
    assert st.al_responder(_respuesta("Estaré fuera de la oficina hasta el lunes"))
    assert _lead(st)["estado"] == "ofrecido" and not _citas()


# --- La cadencia ----------------------------------------------------------------------------------------

def test_como_mucho_tres_correos_y_despues_lo_deja(st, envios):  # noqa: F811
    _primer_enlace(st, envios)
    for dia in (8, 9, 13, 14, 15, 16, 19, 20, 21, 22, 23):
        momento = _madrid(dia, 11)
        st.reloj["ahora"] = momento
        st.ciclo(momento)
    correos = _correos_a(envios, EMAIL)
    assert len(correos) == 3
    assert "otra hora" in _cuerpo(correos[1]) and len(_enlaces_de_hora(_cuerpo(correos[1]))) == 2
    assert "último correo" in _cuerpo(correos[2]) and not _enlaces_de_hora(_cuerpo(correos[2]))
    assert _lead(st)["estado"] == "sin_respuesta"


# --- Mover y resultado ----------------------------------------------------------------------------------

def _reservado(st, envios, client, telefono="600111222"):  # noqa: F811
    token, hora = _primer_enlace(st, envios)
    assert client.post("/reunion/%s" % token, data={"h": hora, "telefono": telefono}).status_code == 200
    return _lead(st)


def test_pablo_mueve_a_otra_hora(st, envios, client):  # noqa: F811
    import asyncio

    lead = _reservado(st, envios, client)
    nueva = _madrid(8, 10, 30)
    assert asyncio.run(st.mover(lead["id"], nueva=nueva))["ok"]
    cita = _citas()[0]
    assert (cita["booking_date"], cita["booking_time"]) == ("2026-10-08", "10:30")
    assert _lead(st)["cita_inicio"] == st._iso(nueva)


def test_pablo_no_puede_y_que_elija_ella(st, envios, client):  # noqa: F811
    import asyncio

    lead = _reservado(st, envios, client)
    assert asyncio.run(st.mover(lead["id"]))["ok"]
    assert _citas()[0]["status"] == "cancelled"
    ultimo = _cuerpo(_correos_a(envios, EMAIL)[-1])
    assert "imprevisto" in ultimo and len(_enlaces_de_hora(ultimo)) == 2
    assert _lead(st)["estado"] == "ofrecido"


def test_no_vino_se_le_ofrece_moverla_una_vez(st, envios, client):  # noqa: F811
    lead = _reservado(st, envios, client)
    st.reloj["ahora"] = _madrid(7, 12, 30)
    assert st.marcar_resultado(lead["id"], "no_vino")["enviado"] is True
    assert _citas()[0]["status"] == "no_show"
    assert "no he podido localizarte" in _cuerpo(_correos_a(envios, EMAIL)[-1])
    assert st.marcar_resultado(lead["id"], "no_vino")["enviado"] is False


def test_ganado_mueve_la_oportunidad(st, envios, client):  # noqa: F811
    from backend import db

    lead = _reservado(st, envios, client)
    st.reloj["ahora"] = _madrid(7, 12, 30)
    assert st.marcar_resultado(lead["id"], "ganado")["ok"]
    lead = _lead(st)
    with db._get_db_connection() as conn:
        oportunidad = conn.execute("SELECT * FROM growth_opportunities WHERE id=?", (lead["oportunidad_id"],)).fetchone()
    assert lead["estado"] == "cerrado" and oportunidad["stage"] == "ganada"


def test_sms_dos_horas_antes_y_ficha_30_minutos_antes(st, envios, client):  # noqa: F811
    _reservado(st, envios, client, telefono="600111222")
    st.reloj["ahora"] = _madrid(7, 10, 30)  # la llamada es a las 12:00
    st.ciclo(st.reloj["ahora"])
    assert len(envios["sms"]) == 1 and "12:00" in envios["sms"][0][1]
    st.reloj["ahora"] = _madrid(7, 11, 35)
    st.ciclo(st.reloj["ahora"])
    assert any("En 25 min" in a[0] for a in envios["avisos"])
    st.ciclo(st.reloj["ahora"] + timedelta(minutes=1))
    assert len(envios["sms"]) == 1 and sum("En " in a[0] for a in envios["avisos"]) == 1


def test_si_cancela_desde_su_enlace_pablo_se_entera(st, envios, client):  # noqa: F811
    from backend import booking

    _reservado(st, envios, client)
    booking._update_booking_record(_citas()[0]["id"], status="cancelled")
    st.ciclo(MIERCOLES_1000 + timedelta(minutes=2))
    assert _lead(st)["estado"] == "cancelada"
    assert any("Ha cancelado" in m["Subject"] for m in envios["pablo"])


# --- Consultas de la web y calendario de Pablo -----------------------------------------------------------

def test_una_consulta_de_la_web_recibe_sus_dos_horas(st, envios, client):  # noqa: F811
    respuesta = client.post("/consulta", json={"nombre": "Lucía Pérez", "email": "lucia@fisio.es",
                                               "telefono": "600999888", "empresa": "Fisio Lucía",
                                               "mensaje": "Quiero saber cómo funciona"})
    assert respuesta.status_code == 200
    st.ciclo(MIERCOLES_1000)
    texto = _cuerpo(_correos_a(envios, "lucia@fisio.es")[-1])
    assert "Gracias por escribirnos desde la web" in texto and len(_enlaces_de_hora(texto)) == 2


def test_lo_ocupado_en_su_calendario_no_se_ofrece(st, monkeypatch):
    ical = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//t//ES\r\nBEGIN:VEVENT\r\nUID:dentista@t\r\n"
            "DTSTART;TZID=Europe/Madrid:20261008T100000\r\nDTEND;TZID=Europe/Madrid:20261008T120000\r\n"
            "RRULE:FREQ=WEEKLY;COUNT=3\r\nSUMMARY:Dentista\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nUID:libre@t\r\n"
            "DTSTART;TZID=Europe/Madrid:20261009T160000\r\nDTEND;TZID=Europe/Madrid:20261009T180000\r\n"
            "TRANSP:TRANSPARENT\r\nSUMMARY:Disponible\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    intervalos = st.intervalos_del_ical(ical, MIERCOLES_1000, MIERCOLES_1000 + timedelta(days=21))
    assert len(intervalos) == 3, "la repeticion semanal no se expandio, o el transparente cuenta"
    monkeypatch.setattr(st, "ocupado_en_calendario", lambda ahora=None: intervalos)
    jueves = [st._local(h).strftime("%H:%M") for h in st.huecos(MIERCOLES_1000) if st._local(h).day == 8]
    assert "10:00" not in jueves and "11:45" not in jueves and "12:00" in jueves


def test_la_invitacion_es_un_ics_valido_con_su_hora(st, envios, client):  # noqa: F811
    import icalendar

    _reservado(st, envios, client)
    adjunto = next(p for p in envios["pablo"][0].iter_attachments() if p.get_content_type() == "text/calendar")
    evento = icalendar.Calendar.from_ical(adjunto.get_payload(decode=True)).walk("VEVENT")[0]
    assert evento.decoded("dtstart") == _madrid(7, 12)
    assert evento.decoded("dtend") - evento.decoded("dtstart") == timedelta(minutes=15)
    assert "Clínica Sonrisa" in str(evento.get("summary"))


def test_si_contesta_mientras_espera_tu_ok_lo_ve_pablo(st, envios):  # noqa: F811
    from backend import oficina

    _cualificado(cualificado_en="2026-09-30T10:00:00+00:00")
    st.importar_cualificados()
    assert st.al_responder(_respuesta("¿Podemos hablar el jueves a las 11?"))
    assert not _citas() and not _correos_a(envios, EMAIL), "contesto sola sin el OK de Pablo"
    assert {p["tipo"] for p in oficina.bandeja()} == {"primer_correo", "respuesta"}


def test_a_un_cliente_que_escribe_por_la_web_no_le_vende(st, envios, client):  # noqa: F811
    from backend import db

    with db._get_db_connection() as conn:
        conn.execute("INSERT OR IGNORE INTO users (id, email, password_hash, role, display_name, cliente_id, is_active, "
                     "created_at) VALUES ('u_cliente_setter', 'cliente@salon.es', 'x', 'client', 'Cliente', 'demo', 1, "
                     "'2026-01-01T00:00:00Z')")
        conn.commit()
    assert client.post("/consulta", json={"nombre": "Clienta", "email": "cliente@salon.es",
                                          "mensaje": "No me llegan los recordatorios"}).status_code == 200
    st.ciclo(MIERCOLES_1000)
    assert _lead(st, "cliente@salon.es") is None and not _correos_a(envios, "cliente@salon.es")


# --- Lo que cazo Astra en 2246e82 ------------------------------------------------------------------

def test_no_puedo_a_esa_hora_no_reserva(st, envios):  # noqa: F811
    """"El jueves a las 11:00 no puedo" nombra una hora y NO la acepta: va a Pablo."""
    from backend import oficina

    _primer_enlace(st, envios)
    assert st.al_responder(_respuesta("El jueves a las 11:00 no puedo, lo siento"))
    assert not _citas()
    assert [p["tipo"] for p in oficina.bandeja()] == ["respuesta"]


def test_su_hora_sin_un_si_se_le_propone_para_que_la_confirme(st, envios):  # noqa: F811
    _primer_enlace(st, envios)
    assert st.al_responder(_respuesta("¿Y el jueves a las 11?"))
    assert not _citas(), "reservo una hora que solo pregunto"
    horas = [h for _, h in _enlaces_de_hora(_cuerpo(_correos_a(envios, EMAIL)[-1]))]
    assert horas[0] == "2026-10-08T11:00" and len(horas) == 2


def test_una_de_las_ofrecidas_si_reserva(st, envios):  # noqa: F811
    _primer_enlace(st, envios)
    assert st.al_responder(_respuesta("La de las 12:00"))
    assert [(c["booking_date"], c["booking_time"]) for c in _citas()] == [("2026-10-07", "12:00")]


def test_apagada_no_contesta_sola(st, envios):  # noqa: F811
    _primer_enlace(st, envios)
    antes = len(_correos_a(envios, EMAIL))
    st.guardar_config(encendida=False)
    assert st.al_responder(_respuesta("Perfecto, el jueves a las 11 me va bien")) is False
    assert not _citas() and len(_correos_a(envios, EMAIL)) == antes
    st.reloj["ahora"] = _madrid(13, 11)
    st.ciclo(st.reloj["ahora"])
    assert len(_correos_a(envios, EMAIL)) == antes, "con Marta apagada salio un recordatorio"


def test_lo_que_pasa_mientras_espera_turno_no_se_pisa(st, envios, monkeypatch):  # noqa: F811
    """Mientras espera el turno global de envio, el lead dice que no: el correo no sale y su
    "descartado" no se convierte otra vez en "ofrecido"."""
    from backend import outreach

    _primer_enlace(st, envios)
    lead_id = _lead(st)["id"]

    def esperar(*a, **k):
        st._actualizar(lead_id, estado="descartado", motivo="dijo que no mientras", proximo="")
        return 0.0

    monkeypatch.setattr(outreach, "_outreach_wait_send_slot", esperar)
    st.reloj["ahora"] = _madrid(12 + 1, 11)
    st.ciclo(st.reloj["ahora"])
    assert len(_correos_a(envios, EMAIL)) == 1
    assert _lead(st)["estado"] == "descartado"


def test_sin_telefono_no_se_confirma_una_llamada(st, envios, client):  # noqa: F811
    assert client.post("/consulta", json={"nombre": "Sin Número", "email": "sintel@fisio.es",
                                          "mensaje": "Info"}).status_code == 200
    st.ciclo(MIERCOLES_1000)
    assert st.al_responder(_respuesta("Perfecto, el jueves a las 11 me va bien", email_="sintel@fisio.es"))
    assert not _citas(), "confirmo una llamada sin numero al que llamar"
    ultimo = _cuerpo(_correos_a(envios, "sintel@fisio.es")[-1])
    token, hora = _enlaces_de_hora(ultimo)[0]
    assert hora == "2026-10-08T11:00"
    assert "¿A qué número te llamo?" in client.get("/reunion/%s?h=%s" % (token, hora)).text
    import asyncio

    assert asyncio.run(st.reservar(token.split(".")[0] if "." in token else token,
                                   st.hueco_de_url(hora)))["motivo"] == "sin_telefono"


def test_un_no_con_marta_apagada_tambien_cuenta(st, envios):  # noqa: F811
    """Revision de Astra a 118f384: apagada no actua sola, pero un "no" se apunta; y quien
    contesta otra cosa no recibe un recordatorio al encenderla."""
    _primer_enlace(st, envios)
    _cualificado(email_="otra@clinica.es", hilo="<otra@test>", telefono="912222222")
    st.ciclo(MIERCOLES_1000)
    st.guardar_config(encendida=False)
    assert st.al_responder(_respuesta("No nos interesa, gracias")) is False
    assert st.al_responder(_respuesta("Os llamo yo la semana que viene", email_="otra@clinica.es")) is False
    assert _lead(st)["estado"] == "descartado"
    st.guardar_config(encendida=True)
    st.reloj["ahora"] = _madrid(13, 11)
    st.ciclo(st.reloj["ahora"])
    assert len(_correos_a(envios, EMAIL)) == 1 and len(_correos_a(envios, "otra@clinica.es")) == 1


def test_nunca_escribe_en_el_hilo_de_la_despedida_del_correo_frio(st, envios):  # noqa: F811
    """7-oct-2026: dos de los cuatro primeros iban a salir como "Re: no te escribo más sobre
    esto". Se sigue el ultimo correo personal; sin ninguno, hilo nuevo."""
    from backend import oficina, outreach

    with outreach._outreach_db() as conn:
        conn.execute("INSERT INTO sends (email, stage, subject, body_text, body_html, sent_at, mode, message_id) "
                     "VALUES (?,?,?,?,?,?,?,?)", (EMAIL, "breakup", "no te escribo más sobre esto", "", "",
                                                  "2026-08-25T11:00:00+00:00", "send", "<adios@test>"))
        conn.commit()
    _cualificado(cualificado_en="2026-09-30T10:00:00+00:00", hilo="<adios@test>", cuando="mañana (6-oct)")
    st.importar_cualificados()
    previa = oficina.bandeja()[0]["vista_previa"]
    assert previa["asunto"] == "Una llamada de 15 minutos sobre Clínica Sonrisa"
    assert "me dijiste" not in previa["texto"]
    with outreach._outreach_db() as conn:
        conn.execute("INSERT INTO sends (email, stage, subject, body_text, body_html, sent_at, mode, message_id) "
                     "VALUES (?,?,?,?,?,?,?,?)", (EMAIL, "pablo_manual", "Tu demo, ya montada", "", "",
                                                  "2026-10-05T18:00:00+00:00", "send", "<pablo@test>"))
        conn.commit()
        assert st._hilo_para(conn, EMAIL, "<adios@test>") == ("<pablo@test>", "Tu demo, ya montada")


def test_solo_se_cita_la_preferencia_si_sigue_valiendo(st):
    assert st.preferencia_vigente("el jueves por la tarde", MIERCOLES_1000)
    assert not st.preferencia_vigente("cuando esten disponibles", MIERCOLES_1000)
    assert not st.preferencia_vigente("mañana (6-oct)", MIERCOLES_1000)
