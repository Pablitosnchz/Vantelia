# -*- coding: utf-8 -*-
"""Un unico correo a quien no dijo que no en la llamada de Sara.

POR QUE EXISTE
--------------
Plan de Pablo del 25-sep-2026 (docs/PLAN_SEGUNDA_OPORTUNIDAD_LLAMADAS.md): recuperar
las llamadas que se perdieron por el momento, no por el producto. Lo que NO puede pasar:
escribir a quien dijo que no, escribir dos veces al mismo negocio, escribir en fin de
semana o encima de otro correo nuestro, o que "no me llameis" deje abierta la puerta del
email. Cada fila de la tabla del plan es un caso (backend/segunda_oportunidad.py).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401
from test_captacion_voz import _Falso, captacion, envios  # noqa: F401

# 29-sep-2026 es martes; Madrid = UTC+2.
MARTES_0930 = datetime(2026, 9, 29, 7, 30, tzinfo=timezone.utc)
MARTES_1630 = datetime(2026, 9, 29, 14, 30, tzinfo=timezone.utc)
MARTES_1700 = datetime(2026, 9, 29, 15, 0, tzinfo=timezone.utc)
MIERCOLES_1030 = datetime(2026, 9, 30, 8, 30, tzinfo=timezone.utc)
VIERNES_1700 = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)
SABADO_1100 = datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc)
LUNES_1030 = datetime(2026, 10, 5, 8, 30, tzinfo=timezone.utc)


@pytest.fixture()
def so(captacion):  # noqa: F811
    from backend import segunda_oportunidad

    segunda_oportunidad.lanzador_llamadas.guardar_config(segunda_oportunidad=True)
    return segunda_oportunidad


def _negocio(email="hola@pelu.es", nombre="Pelu Marta", sector="peluqueria", estado="contacted"):
    from backend import outreach

    with outreach._outreach_db() as conn:
        conn.execute("INSERT OR REPLACE INTO prospects (email, business_name, niche, phone, status, created_at, "
                     "updated_at) VALUES (?,?,?,?,?,?,?)", (email, nombre, sector, "911111111", estado, "x", "x"))
        conn.commit()


def _llamada(captacion, *, desenlace="ocupado_sin_rechazo", creada=MARTES_0930, email="hola@pelu.es",  # noqa: F811
             resultado="", telefono="911111111", **campos):
    """Una llamada terminada con lo que ElevenLabs saco de ella."""
    hecho = captacion.llamar(telefono, "Pelu Marta", "peluqueria", email, origen="auto", cliente=_Falso())
    llamada_id = hecho["llamada"]
    captacion._actualizar(llamada_id, estado="terminada", resultado=resultado,
                          conversation_id="conv_" + llamada_id[-6:], **campos)
    from backend import transcripciones_llamadas

    with transcripciones_llamadas._db() as conn:
        conn.execute("UPDATE llamadas_voz SET creada=?, actualizada=? WHERE id=?",
                     (creada.isoformat(timespec="seconds"), creada.isoformat(timespec="seconds"), llamada_id))
        if desenlace:
            conn.execute("INSERT INTO llamadas_transcripcion (llamada_id, conversation_id, analisis_json, recibida) "
                         "VALUES (?,?,?,?)", (llamada_id, "conv_" + llamada_id[-6:], json.dumps(
                             {"data_collection_results": {"desenlace": {"value": desenlace}}}), "x"))
        conn.commit()
    return llamada_id


def _enviados(so):
    registro = []
    return registro, (lambda candidato, ahora: registro.append(candidato["prospecto"]) or "<id@vantelia>")


def _ronda(so, ahora):
    registro, mandar = _enviados(so)
    salida = so.ronda(ahora=ahora, mandar=mandar, esperar_turno=lambda: None)
    return registro, salida


# --- La tabla del plan ---------------------------------------------------------------

@pytest.mark.parametrize("desenlace,resultado,correo", [
    ("colgo_al_principio", "", True),
    ("ocupado_sin_rechazo", "", True),
    ("interesado", "", False),            # ya recibio la informacion
    ("volver_a_llamar", "", False),       # lo gestiona Pablo
    ("rechazo", "", False),               # "no me interesa": nunca
    ("buzon", "", False),                 # no oyo nada: lo reintenta el lanzador
    ("persona_equivocada", "", False),
    ("", "", False),                      # sin clasificar: no se adivina
    ("ocupado_sin_rechazo", "no_llamar", False),   # lo que apunto Sara manda
    ("colgo_al_principio", "interesado", False),
])
def test_quien_recibe_el_correo(so, captacion, desenlace, resultado, correo):  # noqa: F811
    _negocio()
    _llamada(captacion, desenlace=desenlace, resultado=resultado)
    assert bool(so.elegibles(MARTES_1630)) is correo


def test_si_alguna_vez_dijo_que_no_no_se_le_escribe(so, captacion):  # noqa: F811
    _negocio()
    _llamada(captacion, desenlace="rechazo", creada=MARTES_0930 - timedelta(days=1))
    _llamada(captacion, desenlace="ocupado_sin_rechazo")
    assert so.elegibles(MARTES_1630) == []


def test_no_me_llameis_es_baja_tambien_del_email(so, captacion):  # noqa: F811
    from backend import outreach

    _negocio()
    llamada_id = _llamada(captacion, desenlace="ocupado_sin_rechazo")
    captacion.herramienta("no_volver_a_llamar", {captacion.CAMPO_LLAMADA: llamada_id, "motivo": "que no llamemos"})
    with outreach._outreach_db() as conn:
        assert conn.execute("SELECT 1 FROM suppressions WHERE email='hola@pelu.es'").fetchone()
        assert conn.execute("SELECT status FROM prospects WHERE email='hola@pelu.es'").fetchone()[0] == "baja"
        # Y la secuencia de correos de captacion tampoco le escribe.
        assert outreach._outreach_send_eligibility(conn, "hola@pelu.es", "fu1", 0)["reason"] == "suppressed"
    assert so.elegibles(MARTES_1630) == []


@pytest.mark.parametrize("estado", ["replied", "client", "lost", "bounced", "baja"])
def test_nunca_a_quien_respondio_es_cliente_o_esta_fuera(so, captacion, estado):  # noqa: F811
    _negocio(estado=estado)
    _llamada(captacion)
    assert so.elegibles(MARTES_1630) == []


def test_nunca_con_un_correo_nuestro_reciente(so, captacion):  # noqa: F811
    from backend import outreach

    _negocio()
    _llamada(captacion)
    with outreach._outreach_db() as conn:
        conn.execute("INSERT INTO sends (email, stage, subject, sent_at, mode) VALUES (?,?,?,?,?)",
                     ("hola@pelu.es", "fu1", "x", (MARTES_1630 - timedelta(days=2)).isoformat(timespec="seconds"),
                      "send"))
        conn.commit()
    assert so.elegibles(MARTES_1630) == []
    assert len(so.elegibles(MARTES_1630 + timedelta(days=1, hours=1))) == 1


def test_sin_email_no_hay_correo(so, captacion):  # noqa: F811
    _llamada(captacion, email="")
    assert so.elegibles(MARTES_1630) == []


def test_encenderlo_no_escribe_a_todo_el_historico(so, captacion):  # noqa: F811
    _negocio()
    _llamada(captacion, creada=MARTES_0930 - timedelta(days=5))
    assert so.elegibles(MARTES_1630) == []


def test_espera_a_la_rellamada_a_quien_decide(so, captacion):  # noqa: F811
    _negocio()
    _llamada(captacion, interlocutor="empleado", responsable_nombre="Marta", responsable_cuando="por las tardes")
    assert so.elegibles(MARTES_1630) == [], "primero se llama a Marta"


def test_sin_saber_cuando_esta_quien_decide_no_hay_rellamada_y_si_correo(so, captacion):  # noqa: F811
    _negocio()
    _llamada(captacion, interlocutor="empleado", responsable_nombre="Marta", responsable_cuando="no se")
    elegidos = so.elegibles(MARTES_1630)
    assert len(elegidos) == 1 and elegidos[0]["responsable"] == "Marta"


# --- Cuando ----------------------------------------------------------------------------

def test_llamada_de_manana_correo_por_la_tarde(so, captacion):  # noqa: F811
    _negocio()
    _llamada(captacion, creada=MARTES_0930)
    assert so.elegibles(MARTES_1630 - timedelta(minutes=10)) == []
    assert len(so.elegibles(MARTES_1630)) == 1


def test_llamada_de_tarde_correo_al_dia_siguiente(so, captacion):  # noqa: F811
    _negocio()
    _llamada(captacion, creada=MARTES_1700)
    assert so.elegibles(MARTES_1700 + timedelta(hours=1)) == []
    assert len(so.elegibles(MIERCOLES_1030)) == 1


def test_viernes_por_la_tarde_se_escribe_el_lunes(so, captacion):  # noqa: F811
    assert so.cuando_toca(VIERNES_1700) == LUNES_1030


def test_nunca_en_fin_de_semana(so, captacion):  # noqa: F811
    _negocio()
    _llamada(captacion, creada=VIERNES_1700 - timedelta(hours=8))
    registro, salida = _ronda(so, SABADO_1100)
    assert registro == [] and salida["motivo"] == "fuera_de_horario"


def test_apagada_no_manda_nada(so, captacion):  # noqa: F811
    so.lanzador_llamadas.guardar_config(segunda_oportunidad=False)
    _negocio()
    _llamada(captacion)
    registro, salida = _ronda(so, MARTES_1630)
    assert registro == [] and salida["motivo"] == "apagada"


# --- Una vez, para siempre ----------------------------------------------------------------

def test_una_segunda_oportunidad_por_negocio_para_siempre(so, captacion):  # noqa: F811
    _negocio()
    _llamada(captacion)
    assert _ronda(so, MARTES_1630)[0] == ["hola@pelu.es"]
    assert _ronda(so, MARTES_1630 + timedelta(minutes=30))[0] == []
    # Otra llamada semanas despues que vuelve a acabar ocupada: tampoco.
    _llamada(captacion, creada=MARTES_0930 + timedelta(days=21))
    assert _ronda(so, MARTES_1630 + timedelta(days=21))[0] == []


def test_dos_rondas_a_la_vez_mandan_uno(so, captacion):  # noqa: F811
    _negocio()
    _llamada(captacion)
    candidato = so.elegibles(MARTES_1630)[0]
    assert so._reservar(candidato, MARTES_1630) is True
    assert so._reservar(candidato, MARTES_1630) is False


def test_si_falla_el_envio_se_reintenta(so, captacion):  # noqa: F811
    _negocio()
    _llamada(captacion)

    def falla(candidato, ahora):
        raise RuntimeError("SMTP caido")

    salida = so.ronda(ahora=MARTES_1630, mandar=falla, esperar_turno=lambda: None)
    assert salida["fallidas"] == 1
    assert _ronda(so, MARTES_1630 + timedelta(minutes=30))[0] == ["hola@pelu.es"]


# --- Revision de Astra (27-sep): coordinacion con la secuencia y con la espera -----------

def test_tras_la_segunda_oportunidad_no_sale_ningun_correo_mas(so, captacion):  # noqa: F811
    """Promete "no te volvemos a escribir": la secuencia de captacion (fu1, fu2...) tambien
    se cierra, por el panel y por la linea de comandos."""
    import outreach_campaign  # type: ignore
    from backend import outreach

    _negocio()
    _llamada(captacion)
    with outreach._outreach_db() as conn:
        conn.execute("INSERT INTO sends (email, stage, subject, sent_at, mode) VALUES (?,?,?,?,?)",
                     ("hola@pelu.es", "cold", "x", "2026-09-20T08:00:00+00:00", "send"))
        conn.commit()
    registro, mandar = _enviados(so)

    def mandar_y_apuntar(candidato, ahora):  # como el envio real: queda en `sends` con su etapa
        with outreach._outreach_db() as conn:
            conn.execute("INSERT INTO sends (email, stage, subject, sent_at, mode) VALUES (?,?,?,?,?)",
                         (candidato["prospecto"], so.ETAPA, "x", ahora.isoformat(), "send"))
            conn.commit()
        return mandar(candidato, ahora)

    so.ronda(ahora=MARTES_1630, mandar=mandar_y_apuntar, esperar_turno=lambda: None)
    assert registro == ["hola@pelu.es"]
    with outreach._outreach_db() as conn:
        conn.row_factory = __import__("sqlite3").Row
        assert outreach._outreach_send_eligibility(conn, "hola@pelu.es", "fu1", 0)["reason"] == "cerrada_tras_la_llamada"
        assert outreach_campaign.revalidate_send_candidate(conn, "hola@pelu.es", "fu1", 0)[1] == "cerrada_tras_la_llamada"
        assert outreach_campaign.fetch_candidates(conn, "fu1", 0, 50) == []


def test_un_correo_que_sale_mientras_se_reserva_la_frena(so, captacion, monkeypatch):  # noqa: F811
    """La reserva propia no puede tapar el "correo reciente" de otra campana."""
    from backend import outreach

    _negocio()
    _llamada(captacion)
    reservar = so._reservar

    def reservar_y_cruzarse(candidato, ahora):
        hecho = reservar(candidato, ahora)
        with outreach._outreach_db() as conn:  # la campana de email manda un fu1 justo ahora
            conn.execute("INSERT INTO sends (email, stage, subject, sent_at, mode) VALUES (?,?,?,?,?)",
                         (candidato["prospecto"], "fu1", "x", ahora.isoformat(timespec="seconds"), "send"))
            conn.commit()
        return hecho

    monkeypatch.setattr(so, "_reservar", reservar_y_cruzarse)
    assert _ronda(so, MARTES_1630)[0] == []
    with so._db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM segunda_oportunidad").fetchone()[0] == 0, "se suelta la reserva"


@pytest.mark.parametrize("mientras_espera", ["baja", "respuesta", "apagada", "se_pasa_la_hora"])
def test_lo_que_pasa_mientras_espera_el_turno_frena_el_envio(so, captacion, mientras_espera):  # noqa: F811
    from backend import outreach

    _negocio()
    _llamada(captacion)
    hora = [MARTES_1630.replace(hour=16, minute=55)]  # 18:55 en Madrid

    def esperar():
        with outreach._outreach_db() as conn:
            if mientras_espera == "baja":
                conn.execute("INSERT INTO suppressions (email, reason, added_at) VALUES (?,?,?)",
                             ("hola@pelu.es", "BAJA", "x"))
            elif mientras_espera == "respuesta":
                conn.execute("INSERT INTO events (email, type, ts) VALUES (?,?,?)", ("hola@pelu.es", "reply", "x"))
            conn.commit()
        if mientras_espera == "apagada":
            so.lanzador_llamadas.guardar_config(segunda_oportunidad=False)
        if mientras_espera == "se_pasa_la_hora":
            hora[0] = hora[0] + timedelta(minutes=10)  # 19:05: fuera de horario

    registro, mandar = _enviados(so)
    extra = {"reloj": lambda: hora[0]} if mientras_espera == "se_pasa_la_hora" else {}
    so.ronda(ahora=hora[0], mandar=mandar, esperar_turno=esperar, **extra)
    assert registro == []


# --- El correo ---------------------------------------------------------------------------

def test_el_correo_que_sale(so, captacion, envios):  # noqa: F811
    from backend import outreach

    _negocio()
    _llamada(captacion, creada=MARTES_1700)
    salida = so.ronda(ahora=MIERCOLES_1030, esperar_turno=lambda: None)
    assert salida["enviadas"] == 1
    mensaje = envios["email"][0]
    texto = mensaje.get_body(preferencelist=("plain",)).get_content()
    assert mensaje["To"] == "hola@pelu.es"
    assert mensaje["Subject"] == "Lo de la llamada de ayer"
    assert "Ayer os llamó Sara" in texto and "Pelu Marta" in texto and "las peluquerías" in texto
    assert "no te volvemos a escribir" in texto
    assert mensaje["List-Unsubscribe"] is None, "Pablo, 26-sep: sin List-Unsubscribe, como el resto"
    assert envios["demos"] == ["hola@pelu.es"], "su demo empieza a generarse al mandarlo"
    with outreach._outreach_db() as conn:
        envio = conn.execute("SELECT stage, mode FROM sends WHERE email='hola@pelu.es'").fetchone()
        assert tuple(envio) == ("llamada", "send"), "la secuencia de correos lo ve"


@pytest.mark.parametrize("creada,ahora,frase", [
    (MARTES_0930, MARTES_1630, "esta mañana"),
    (MARTES_1700, MIERCOLES_1030, "ayer"),
    (VIERNES_1700, LUNES_1030, "el viernes"),
])
def test_el_correo_dice_bien_cuando_fue(so, creada, ahora, frase):
    assert so._cuando_fue(creada, ahora) == frase


def test_el_asunto_cuadra_con_el_dia(so):
    asunto = lambda cuando: so.correo("Pelu", "peluqueria", "https://x", cuando)["asunto"]  # noqa: E731
    assert (asunto("ayer"), asunto("el viernes"), asunto("esta mañana")) == (
        "Lo de la llamada de ayer", "Lo de la llamada del viernes", "Lo de la llamada de esta mañana")


@pytest.mark.parametrize("sector,audio", [
    ("peluqueria", "peluqueria"), ("Barbería - peluquería de caballero", "barberia"),
    ("clinica dental", "clinica_dental"), ("Clínica de fisioterapia", "fisioterapia"),
    ("centro de estetica", "estetica"), ("clinica estetica", "estetica"), ("masajes", "estetica"),
    ("clinica veterinaria", None), ("gimnasio", None), ("", None),
])
def test_el_correo_lleva_la_llamada_de_ejemplo_de_su_sector(so, sector, audio):
    """Audios de la web aprobados por Pablo (26-sep). Uno que no es de su sector confunde
    mas que ayuda: sin audio que encaje, el correo va sin el."""
    elegido = so.audio_de_su_sector(sector)
    assert (elegido["url"].rsplit("/", 1)[1] if elegido else None) == (audio + ".mp3" if audio else None)
    texto = so.correo("Pelu", sector, "https://demo", "ayer")["texto"]
    assert ("vantelia.es/assets/audio/" in texto) is bool(audio)
    assert texto.count("https://demo") == 1


# --- El panel ----------------------------------------------------------------------------

def test_el_panel_ensena_como_acabo_y_el_interruptor(so, captacion, client, monkeypatch):  # noqa: F811
    from backend import settings

    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "")  # sin el tenant de Sara en los tests
    _negocio()
    llamada_id = _llamada(captacion)
    cabeceras = {"Authorization": "Bearer test-admin-token"}
    r = client.put("/admin/captacion/llamadas/config", json={"segunda_oportunidad": False}, headers=cabeceras)
    assert r.status_code == 200 and r.json()["segunda_oportunidad"] == 0
    datos = client.get("/admin/captacion/llamadas", headers=cabeceras).json()
    fila = next(ll for ll in datos["llamadas"] if ll["id"] == llamada_id)
    assert fila["desenlace"] == "ocupado_sin_rechazo" and fila["segunda_oportunidad"] == ""
    assert "segunda_oportunidad_en_cola" in datos
