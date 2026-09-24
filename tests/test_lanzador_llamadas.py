# -*- coding: utf-8 -*-
"""El lanzador de llamadas de Sara: a quien NO se llama, y que sin Robinson no hay llamada.

POR QUE EXISTE
--------------
`backend/lanzador_llamadas.py` marca solo, sin nadie mirando. Una llamada de mas no se
deshace: al que esta en la Lista Robinson, al que pidio que no, al movil de un
autonomo, a las nueve de la noche o tres veces el mismo dia. Estos tests fijan esas
reglas y que, si la Lista Robinson no contesta, no suena ningun telefono.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401

MARTES_10_30 = datetime(2026, 9, 29, 8, 30, tzinfo=timezone.utc)  # 10:30 en Madrid
CABECERAS = {"Authorization": "Bearer test-admin-token"}


@pytest.fixture()
def lanzador(api_module, monkeypatch, tmp_path):  # noqa: F811
    """Todo listo para llamar, con la base de captacion SIEMPRE temporal."""
    from backend import captacion_voz, clients, settings

    monkeypatch.setenv("OUTREACH_DB_PATH", str(tmp_path / "outreach.db"))
    for nombre, valor in {
        "ELEVENLABS_API_KEY": "clave-de-prueba", "ELEVENLABS_TOOL_SECRET": "secreto",
        "TWILIO_ACCOUNT_SID": "ACtest", "TWILIO_AUTH_TOKEN": "token-test",
        "CAPTACION_TWILIO_NUMBER": "+34910000000", "ROBINSON_API_KEY": "CLAVE",
        "ROBINSON_API_SECRET": "secreto", "CAPTACION_LLAMADAS_ENABLED": True,
    }.items():
        monkeypatch.setattr(settings, nombre, valor)
    original = clients._get_client_config
    monkeypatch.setattr(clients, "_get_client_config", lambda cid: (
        {"voice": {captacion_voz.CLAVE_AGENTE: "agent_sara"}} if cid == captacion_voz.TENANT else original(cid)))
    from backend import cuenta_elevenlabs, lanzador_llamadas

    # Cuenta de ElevenLabs sana (la caida se prueba en test_cuenta_elevenlabs.py).
    monkeypatch.setattr(cuenta_elevenlabs, "estado", lambda **k: {"ok": True, "tipo": "", "problema": "", "aviso": ""})

    return lanzador_llamadas


def _prospecto(lanzador, email, telefono, estado="new", negocio="", creado="2026-09-01T00:00:00+00:00"):
    with lanzador._db() as conn:
        conn.execute("INSERT INTO prospects (email, business_name, niche, phone, status, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?,?)",
                     (email, negocio or email.split("@")[0], "peluqueria", telefono, estado, creado, creado))
        conn.commit()


def _llamada_previa(lanzador, telefono, creada, resultado="", origen="auto", estado="terminada"):
    with lanzador._db() as conn:
        conn.execute("INSERT INTO llamadas_voz (id, telefono, estado, resultado, origen, creada, actualizada) "
                     "VALUES (?,?,?,?,?,?,?)",
                     ("ll_%s_%s" % (telefono, creada), telefono, estado, resultado, origen,
                      lanzador._iso(creada), lanzador._iso(creada)))
        conn.commit()


class _Marcador:
    """Hace de captacion_voz.llamar: apunta a quien se llamo, sin Twilio."""

    def __init__(self, lanzador, ahora):
        self.lanzador, self.ahora, self.llamados = lanzador, ahora, []

    def __call__(self, telefono, negocio, sector, prospecto, origen="manual"):
        self.llamados.append(telefono)
        _llamada_previa(self.lanzador, telefono, self.ahora, origen=origen, estado="marcando")
        return {"ok": True, "llamada": "ll_%d" % len(self.llamados)}


class _Robinson:
    def __init__(self, en_lista=()):
        self.en_lista, self.preguntados = set(en_lista), []

    def __call__(self, telefonos):
        self.preguntados.append(list(telefonos))
        return {t: t in self.en_lista for t in telefonos}


def _ronda(lanzador, ahora=MARTES_10_30, robinson=None, marcador=None):
    marcador = marcador or _Marcador(lanzador, ahora)
    salida = lanzador.ronda(ahora=ahora, llamar=marcador, consultar=robinson or _Robinson())
    return salida, marcador


# --- Lista Robinson ----------------------------------------------------------

def test_huella_y_firma_iguales_que_el_cliente_oficial():
    """Vectores sacados del Signing.js de adigital-org/slr-client con node (24-sep-2026)."""
    from backend import lista_robinson

    assert lista_robinson.normalizar("+34 911 23 45 67") == "0034911234567"
    assert lista_robinson.normalizar("911234567") == lista_robinson.normalizar("0034911234567")
    a, b = lista_robinson.huella("345678890"), lista_robinson.huella("+34 911 23 45 67")
    assert a == "9a0d14c71b6bb4b50fd4a9efc0536de8c7198f4bebdadcc4e7ee32731fb75c15"
    assert b == "6ef685af3e70b2876070a828f58453accf63fa9200c6ff41dc5340618f7e9b75"
    firma = lista_robinson.firma_query(lista_robinson.URL, a + "," + b, "CLAVEDEPRUEBA123",
                                       "secreto/De+Prueba", datetime(2026, 9, 24, 10, 15, 30, tzinfo=timezone.utc))
    assert firma == ("?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=CLAVEDEPRUEBA123%2F20260924%2F"
                     "eu-west-1%2Fexecute-api%2Faws4_request&X-Amz-Date=20260924T101530Z&X-Amz-SignedHeaders=host"
                     "&X-Amz-Signature=b0e3159c9863c4027dd79d28986c21cb435e1c278c8d95b5199a2cc10e025974")


class _Respuesta:
    def __init__(self, status_code, datos):
        self.status_code, self._datos, self.text = status_code, datos, str(datos)

    def json(self):
        return self._datos


class _ApiRobinson:
    def __init__(self, contestar_todo=True):
        self.cuerpos, self.contestar_todo = [], contestar_todo

    def post(self, url, content=b"", **k):
        huellas = content.decode().split(",")
        self.cuerpos.append(huellas)
        if not self.contestar_todo:
            huellas = huellas[:-1]
        return _Respuesta(200, {h: {"found": False} for h in huellas})


def test_la_consulta_no_manda_telefonos_y_va_en_lotes_de_60(lanzador):
    from backend import lista_robinson

    telefonos = ["+3491%07d" % i for i in range(61)]
    api = _ApiRobinson()
    resultado = lista_robinson.consultar(telefonos, cliente=api)
    assert set(resultado) == set(telefonos) and not any(resultado.values())
    assert [len(c) for c in api.cuerpos] == [60, 1]
    assert not any("91" in h[:2] for c in api.cuerpos for h in c)  # solo huellas hex
    with pytest.raises(RuntimeError):
        lista_robinson.consultar(telefonos[:3], cliente=_ApiRobinson(contestar_todo=False))


def test_sin_credenciales_la_consulta_falla_en_vez_de_decir_que_no_esta(lanzador, monkeypatch):
    from backend import lista_robinson, settings

    monkeypatch.setattr(settings, "ROBINSON_API_SECRET", "")
    with pytest.raises(RuntimeError):
        lista_robinson.consultar(["+34911234567"], cliente=_ApiRobinson())


# --- El lanzador -------------------------------------------------------------

def test_apagado_de_serie(lanzador):
    assert lanzador.config()["activo"] == 0
    _prospecto(lanzador, "a@pelu.es", "911111111")
    salida, marcador = _ronda(lanzador)
    assert marcador.llamados == [] and "apagado" in salida["motivo"].lower()


@pytest.mark.parametrize("ajuste,valor,trozo", [
    ("ROBINSON_API_KEY", "", "robinson"),
    ("CAPTACION_TWILIO_NUMBER", "", "numero espanol"),
    ("CAPTACION_LLAMADAS_ENABLED", False, "captacion_llamadas_enabled"),
])
def test_cada_llave_que_falta_bloquea(lanzador, monkeypatch, ajuste, valor, trozo):
    from backend import settings

    lanzador.guardar_config(activo=True)
    _prospecto(lanzador, "a@pelu.es", "911111111")
    monkeypatch.setattr(settings, ajuste, valor)
    salida, marcador = _ronda(lanzador)
    assert marcador.llamados == [] and trozo in salida["motivo"].lower()


def test_si_robinson_no_contesta_no_suena_nadie(lanzador):
    lanzador.guardar_config(activo=True)
    _prospecto(lanzador, "a@pelu.es", "911111111")

    def caida(telefonos):
        raise RuntimeError("timeout")

    salida, marcador = _ronda(lanzador, robinson=caida)
    assert marcador.llamados == [] and "robinson" in salida["motivo"].lower()


def test_quien_esta_en_robinson_no_recibe_la_llamada(lanzador):
    lanzador.guardar_config(activo=True)
    _prospecto(lanzador, "a@pelu.es", "911111111", creado="2026-09-01T00:00:00+00:00")
    _prospecto(lanzador, "b@pelu.es", "912222222", creado="2026-09-02T00:00:00+00:00")
    salida, marcador = _ronda(lanzador, robinson=_Robinson(en_lista={"+34911111111"}))
    assert marcador.llamados == ["+34912222222"], salida


def test_robinson_se_recuerda_30_dias(lanzador):
    lanzador.guardar_config(activo=True, minutos_entre=5)
    _prospecto(lanzador, "a@pelu.es", "911111111")
    robinson = _Robinson(en_lista={"+34911111111"})
    _ronda(lanzador, robinson=robinson)
    _ronda(lanzador, ahora=MARTES_10_30 + timedelta(minutes=20), robinson=robinson)
    assert robinson.preguntados == [["+34911111111"]], "dentro de los 30 dias no se vuelve a preguntar"
    # Martes 3-nov, 10:30 en Madrid ya en horario de invierno (UTC+1).
    _ronda(lanzador, ahora=datetime(2026, 11, 3, 9, 30, tzinfo=timezone.utc), robinson=robinson)
    assert len(robinson.preguntados) == 2, "pasados 30 dias la respuesta caduca"


def test_primero_quien_se_intereso_por_el_correo(lanzador):
    """Pablo (24-sep-2026): llamar antes a quien abrio o pincho nuestros correos."""
    _prospecto(lanzador, "frio@pelu.es", "911111111", creado="2026-09-01T00:00:00+00:00")
    _prospecto(lanzador, "abrio@pelu.es", "912222222", creado="2026-09-02T00:00:00+00:00")
    _prospecto(lanzador, "pincho@pelu.es", "913333333", creado="2026-09-03T00:00:00+00:00")
    _prospecto(lanzador, "ya_llamado@pelu.es", "914444444", creado="2026-08-01T00:00:00+00:00")
    _llamada_previa(lanzador, "+34914444444", MARTES_10_30 - timedelta(days=5), resultado="no_contesta")
    with lanzador._db() as conn:
        for email, tipo in (("abrio@pelu.es", "open"), ("pincho@pelu.es", "open"), ("pincho@pelu.es", "click"),
                            ("ya_llamado@pelu.es", "click")):
            conn.execute("INSERT INTO events (email, type, ts) VALUES (?,?,?)", (email, tipo, "2026-09-10T10:00:00+00:00"))
        conn.commit()
    orden = [c["prospecto"] for c in lanzador.candidatos(MARTES_10_30)]
    assert orden == ["pincho@pelu.es", "abrio@pelu.es", "frio@pelu.es", "ya_llamado@pelu.es"], (
        "los que nunca sonaron van antes; entre ellos, primero quien pincho y luego quien abrio")


def test_solo_fijos_y_nunca_a_quien_no_toca(lanzador):
    lanzador.guardar_config(activo=True)
    _prospecto(lanzador, "movil@pelu.es", "675111111")          # movil: autonomo, a mano
    _prospecto(lanzador, "baja@pelu.es", "913333333", estado="baja")
    _prospecto(lanzador, "cliente@pelu.es", "914444444", estado="client")
    _prospecto(lanzador, "suprimido@pelu.es", "915555555")
    _prospecto(lanzador, "vetado@pelu.es", "916666666")
    _prospecto(lanzador, "correo@pelu.es", "917777777")
    _prospecto(lanzador, "bueno@pelu.es", "918888888")
    with lanzador._db() as conn:
        conn.execute("INSERT INTO suppressions (email, reason, added_at) VALUES ('suprimido@pelu.es','BAJA','x')")
        conn.execute("INSERT INTO no_llamar (telefono, motivo, creado) VALUES ('+34916666666','no','x')")
        conn.execute("INSERT INTO sends (email, stage, subject, sent_at, mode) VALUES (?,?,?,?,?)",
                     ("correo@pelu.es", "cold", "hola", lanzador._iso(MARTES_10_30 - timedelta(days=1)), "send"))
        conn.commit()
    telefonos = [c["telefono"] for c in lanzador.candidatos(MARTES_10_30)]
    assert telefonos == ["+34918888888"]


@pytest.mark.parametrize("ahora,llama", [
    (datetime(2026, 9, 28, 8, 30, tzinfo=timezone.utc), False),   # lunes 10:30
    (datetime(2026, 9, 29, 11, 0, tzinfo=timezone.utc), False),   # martes 13:00
    (datetime(2026, 9, 29, 14, 30, tzinfo=timezone.utc), True),   # martes 16:30
    (datetime(2026, 9, 29, 16, 0, tzinfo=timezone.utc), False),   # martes 18:00
    (datetime(2026, 10, 3, 8, 30, tzinfo=timezone.utc), False),   # sabado 10:30
    (datetime(2026, 10, 2, 7, 59, tzinfo=timezone.utc), False),   # viernes 9:59
])
def test_solo_en_horario_de_madrid(lanzador, ahora, llama):
    lanzador.guardar_config(activo=True)
    _prospecto(lanzador, "a@pelu.es", "911111111")
    salida, marcador = _ronda(lanzador, ahora=ahora)
    assert bool(marcador.llamados) is llama, salida


@pytest.mark.parametrize("previas,llama", [
    ([(3, "no_contesta")], True),
    ([(3, "contestador")], True),
    ([(1, "no_contesta")], False),                     # menos de 2 dias
    ([(3, "interesado")], False),                      # ya hablo con Sara
    ([(3, "volver_a_llamar")], False),                 # lo gestiona una persona
    ([(9, "no_contesta"), (5, "ocupado")], False),     # dos intentos: basta
])
def test_reintentos(lanzador, previas, llama):
    lanzador.guardar_config(activo=True)
    _prospecto(lanzador, "a@pelu.es", "911111111")
    for dias, resultado in previas:
        _llamada_previa(lanzador, "+34911111111", MARTES_10_30 - timedelta(days=dias), resultado=resultado)
    _, marcador = _ronda(lanzador)
    assert bool(marcador.llamados) is llama


def test_una_cada_vez_con_hueco_y_cupo_diario(lanzador):
    lanzador.guardar_config(activo=True, cupo_diario=2, minutos_entre=10)
    for i in range(5):
        _prospecto(lanzador, "p%d@pelu.es" % i, "91%07d" % i, creado="2026-09-0%dT00:00:00+00:00" % (i + 1))
    marcador = _Marcador(lanzador, MARTES_10_30)
    _ronda(lanzador, marcador=marcador)
    salida, _ = _ronda(lanzador, ahora=MARTES_10_30 + timedelta(minutes=5), marcador=marcador)
    assert len(marcador.llamados) == 1 and "en curso" in salida["motivo"], "una llamada cada vez"
    with lanzador._db() as conn:
        conn.execute("UPDATE llamadas_voz SET estado='terminada'")
        conn.commit()
    salida, _ = _ronda(lanzador, ahora=MARTES_10_30 + timedelta(minutes=6), marcador=marcador)
    assert len(marcador.llamados) == 1 and "hueco" in salida["motivo"]
    marcador.ahora = MARTES_10_30 + timedelta(minutes=11)
    _ronda(lanzador, ahora=marcador.ahora, marcador=marcador)
    with lanzador._db() as conn:
        conn.execute("UPDATE llamadas_voz SET estado='terminada'")
        conn.commit()
    salida, _ = _ronda(lanzador, ahora=MARTES_10_30 + timedelta(minutes=40), marcador=marcador)
    assert len(marcador.llamados) == 2 and "cupo" in salida["motivo"].lower()
    assert len(set(marcador.llamados)) == 2, "nunca dos veces el mismo el mismo dia"


def test_la_llamada_real_queda_marcada_como_automatica_con_su_conversacion(lanzador):
    """Del lanzador a Twilio y de ahi a ElevenLabs: origen 'auto' y el id de la
    conversacion guardado, para leer la transcripcion desde el panel."""
    from backend import captacion_voz

    class _Http:
        def post(self, url, **k):
            if "register-call" in url:
                respuesta = _Respuesta(200, {})
                respuesta.text = ('<Response><Connect><Stream url="wss://x"><Parameter name="conversation_id" '
                                  'value="conv_abc123" /></Stream></Connect></Response>')
                return respuesta
            return _Respuesta(201, {"sid": "CA1"})

    hecho = captacion_voz.llamar("911111111", "Pelu", origen="auto", cliente=_Http())
    captacion_voz.twiml_al_descolgar(hecho["llamada"], "human", "+34910000000", "+34911111111", cliente=_Http())
    fila = captacion_voz._fila(hecho["llamada"])
    assert fila["origen"] == "auto" and fila["conversation_id"] == "conv_abc123"


# --- Panel -------------------------------------------------------------------

def test_el_panel_exige_admin_y_ensena_lo_que_falta(client, lanzador, monkeypatch):  # noqa: F811
    from backend import settings

    assert client.get("/admin/captacion/llamadas").status_code in (401, 403)
    monkeypatch.setattr(settings, "ROBINSON_API_KEY", "")
    datos = client.get("/admin/captacion/llamadas", headers=CABECERAS).json()
    assert datos["config"]["activo"] == 0
    assert any("Robinson" in b for b in datos["bloqueos"])
    r = client.put("/admin/captacion/llamadas/config", headers=CABECERAS,
                   json={"activo": True, "cupo_diario": 500, "minutos_entre": 1})
    assert r.status_code == 200 and r.json()["activo"] == 1
    assert r.json()["cupo_diario"] == 40 and r.json()["minutos_entre"] == 5, "limites que no se saltan"


def test_la_transcripcion_sale_de_elevenlabs(client, lanzador, monkeypatch):  # noqa: F811
    from backend import voz_elevenlabs

    _llamada_previa(lanzador, "+34911111111", MARTES_10_30, resultado="no_contesta")
    llamada = "ll_+34911111111_%s" % MARTES_10_30
    assert client.get("/admin/captacion/llamadas/%s/transcripcion" % llamada,
                      headers=CABECERAS).status_code == 404, "sin conversacion no hay nada que leer"
    with lanzador._db() as conn:
        conn.execute("UPDATE llamadas_voz SET conversation_id='conv_abc123'")
        conn.commit()
    monkeypatch.setattr(voz_elevenlabs, "transcripcion", lambda cid: {"turnos": [{"quien": "agente", "texto": cid}]})
    r = client.get("/admin/captacion/llamadas/%s/transcripcion" % llamada, headers=CABECERAS)
    assert r.status_code == 200 and r.json()["turnos"][0]["texto"] == "conv_abc123"
