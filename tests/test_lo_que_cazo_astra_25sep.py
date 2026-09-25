# -*- coding: utf-8 -*-
"""Lo que cazo Astra al revisar los arreglos, el plan del responsable y las transcripciones.

POR QUE EXISTE
--------------
Segunda revision de Astra (25-sep-2026, acta docs/REVISION_SARA_25SEP.md en su rama):
nueve hallazgos sobre 3a33f02, 5e2c841 y 246bdce, reproducidos con los modulos reales y
sin red. Los tres criticos: la vuelta atras de una rotacion dejaba apuntando a un agente
de telefono recien borrado; un rechazo que llegaba mientras contestaba la Lista Robinson
no frenaba la llamada; y una conversacion "processing" guardada como definitiva ya no se
volvia a recoger. Cada test es uno de sus casos y falla sin el arreglo.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401
from test_captacion_voz import _Falso, _Respuesta, captacion  # noqa: F401
from test_cuenta_elevenlabs import cuenta, reserva  # noqa: F401
from test_hablar_con_el_responsable import MARTES_16_30, _hablo_con_un_empleado, _Marcador  # noqa: F401
from test_lanzador_llamadas import lanzador  # noqa: F401
from test_transcripciones_llamadas import _conversacion, llamada  # noqa: F401


# --- Rotacion (sobre 3a33f02) -----------------------------------------------------

def test_la_vuelta_atras_quita_tambien_el_telefono_que_se_creo(cuenta, reserva, monkeypatch):  # noqa: F811
    from backend import appstate, clients

    monkeypatch.setattr(clients, "_persist_configs_to_disk", lambda configs: None)
    antes = json.loads(json.dumps(appstate.CONFIG_CLIENTES["negocio_voz"]))  # solo agente web

    def crea_telefono_y_falla():
        from backend import voz_elevenlabs

        voz_elevenlabs.guardar_en_voz("negocio_voz", "elevenlabs_agent_id_telefono", "tel_nuevo")
        reserva.agentes["tel_nuevo"] = []
        raise RuntimeError("Falla el segundo negocio")

    monkeypatch.setattr(cuenta, "sincronizar_agentes", crea_telefono_y_falla)
    assert cuenta.rotar("prueba", cliente=reserva)["rotada"] is False
    assert appstate.CONFIG_CLIENTES["negocio_voz"] == antes, "sin agente de telefono, como estaba"
    assert ("k_buena", "tel_nuevo") in reserva.borrados


def test_la_principal_fuera_de_la_reserva_sobrevive_a_un_reinicio(cuenta, reserva, monkeypatch):  # noqa: F811
    from backend import settings
    from test_cuenta_elevenlabs import _suscripcion

    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "k_principal")
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEYS", ["k_buena", "k_otra"])
    reserva.cuentas["k_principal"] = _suscripcion(usados=300000)
    assert cuenta.rotar("sin creditos", cliente=reserva)["rotada"] is True
    # Reinicio: vuelven los valores del .env y se aplica la activa guardada.
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "k_principal")
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEYS", ["k_buena", "k_otra"])
    assert cuenta.aplicar_activa_guardada() == cuenta.huella("k_buena")
    reserva.cuentas["k_principal"] = _suscripcion()
    assert cuenta.vigilar_una_vez(cliente=reserva) == "rotada"
    assert settings.ELEVENLABS_API_KEY == "k_principal"


# --- Rellamada dirigida (sobre 5e2c841) ---------------------------------------------

def test_un_rechazo_que_llega_mientras_contesta_robinson_frena(lanzador):  # noqa: F811
    lanzador.guardar_config(activo=True)
    _hablo_con_un_empleado(lanzador)

    def robinson(numeros):
        with lanzador._db() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS llamadas_transcripcion (llamada_id TEXT PRIMARY KEY, "
                         "analisis_json TEXT)")
            conn.execute("INSERT INTO llamadas_transcripcion VALUES ('ll_original', ?)",
                         (json.dumps({"data_collection_results": {"desenlace": {"value": "rechazo"}}}),))
            conn.commit()
        return {n: False for n in numeros}

    marcador = _Marcador(lanzador, MARTES_16_30)
    lanzador.ronda(ahora=MARTES_16_30, llamar=marcador, consultar=robinson)
    assert marcador.llamadas == []


def test_no_se_llama_antes_de_la_hora_que_dijeron(lanzador):  # noqa: F811
    _hablo_con_un_empleado(lanzador, cuando="el martes a partir de las cinco", hace_horas=30)
    assert lanzador.rellamadas_dirigidas(MARTES_16_30) == [], "son las 16:30 y pidieron desde las 17:00"
    assert len(lanzador.rellamadas_dirigidas(MARTES_16_30 + timedelta(minutes=35))) == 1


@pytest.mark.parametrize("cuando", ["", "no se", "el 3 de octubre"])
def test_sin_saber_cuando_esta_no_hay_rellamada(lanzador, cuando):  # noqa: F811
    _hablo_con_un_empleado(lanzador, cuando=cuando)
    assert lanzador.rellamadas_dirigidas(MARTES_16_30) == []


# --- Transcripciones (sobre 246bdce) ----------------------------------------------------

class _Api:
    def __init__(self, conversacion):
        self.conversacion, self.pedidas = conversacion, []

    def get(self, url, headers=None, **k):
        self.pedidas.append(url.rsplit("/", 1)[1])
        return _Respuesta(200, self.conversacion)

    def close(self):
        pass


def test_una_conversacion_a_medias_no_se_guarda_como_definitiva(llamada, captacion, monkeypatch):  # noqa: F811
    from backend import lanzador_llamadas, settings

    llamada_id, t = llamada
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEYS", ["k_vieja"])
    captacion._actualizar(llamada_id, interlocutor="empleado", responsable_nombre="Ana",
                          responsable_cuando="por las tardes")
    with captacion._db() as conn:
        conn.execute("UPDATE llamadas_voz SET origen='auto', creada='2026-09-28T08:00:00+00:00', "
                     "actualizada='2026-09-20T08:00:00+00:00'")
        conn.commit()
    a_medias = dict(_conversacion(), status="processing", analysis={})
    assert t.leer(llamada_id, cliente=_Api(a_medias))["estado"] == "processing"
    assert t.de_la_llamada(llamada_id) is None, "no se guarda lo que aun no ha terminado"
    final = _conversacion(data_collection_results={"desenlace": {"value": "rechazo"}})
    assert t.recoger_pendientes(cliente=_Api(final)) == 1
    martes_tarde = datetime(2026, 9, 29, 14, 30, tzinfo=timezone.utc)
    assert lanzador_llamadas.rellamadas_dirigidas(martes_tarde) == []


def test_la_clasificacion_no_pisa_lo_que_escribe_la_herramienta_a_la_vez(llamada, captacion, monkeypatch):  # noqa: F811
    llamada_id, t = llamada
    turnos = t._turnos

    def entremedias(transcript):
        captacion.herramienta("anotar_responsable", {captacion.CAMPO_LLAMADA: llamada_id,
                                                     "interlocutor": "duena_o_encargada", "nombre": "Ana"})
        return turnos(transcript)

    monkeypatch.setattr(t, "_turnos", entremedias)
    t.guardar(_conversacion(), "aviso")  # clasifica empleado / Marta
    fila = captacion._fila(llamada_id)
    assert (fila["interlocutor"], fila["responsable_nombre"]) == ("duena_o_encargada", "Ana")


def test_las_conversaciones_perdidas_no_atascan_la_cola(llamada, captacion, monkeypatch):  # noqa: F811
    from backend import settings

    llamada_id, t = llamada
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEYS", ["k_vieja"])
    antiguas = []
    for i in range(20):
        hecho = captacion.llamar("91%07d" % (i + 10), "Antiguo %d" % i, cliente=_Falso())
        captacion._actualizar(hecho["llamada"], estado="terminada", conversation_id="conv_perdida_%d" % i)
        antiguas.append(hecho["llamada"])
    with captacion._db() as conn:
        conn.execute("UPDATE llamadas_voz SET actualizada='2026-09-01T00:00:00+00:00' WHERE id<>?", (llamada_id,))
        conn.execute("UPDATE llamadas_voz SET actualizada='2026-09-02T00:00:00+00:00' WHERE id=?", (llamada_id,))
        conn.commit()

    class _SoloLaNueva(_Api):
        def get(self, url, headers=None, **k):
            self.pedidas.append(url.rsplit("/", 1)[1])
            return _Respuesta(200, _conversacion()) if url.endswith("/conv_1") else _Respuesta(404, {})

    api = _SoloLaNueva(None)
    t.recoger_pendientes(cliente=api)
    t.recoger_pendientes(cliente=api)
    assert t.de_la_llamada(llamada_id) is not None, "la nueva se recoge aunque haya 20 perdidas delante"


def test_si_una_cuenta_no_responde_se_prueba_la_siguiente(llamada, monkeypatch):  # noqa: F811
    from backend import settings

    _, t = llamada
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "k_caida")
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEYS", ["k_caida", "k_vieja"])

    class _Timeout:
        def __init__(self):
            self.claves = []

        def get(self, url, headers=None, **k):
            self.claves.append(headers["xi-api-key"])
            if headers["xi-api-key"] == "k_caida":
                raise httpx.ReadTimeout("sin respuesta")
            return _Respuesta(200, _conversacion())

    api = _Timeout()
    assert t._pedir("conv_1", api) is not None and api.claves[-2:] == ["k_caida", "k_vieja"]


# --- Tercera vuelta: lo que quedaba en 08df105 ------------------------------------------

JUEVES = datetime(2026, 10, 1, tzinfo=timezone.utc)  # 1-oct-2026, jueves; Madrid = UTC+2


@pytest.mark.parametrize("cuando,hora_utc,llama", [
    ("el jueves de cinco a seis", (8, 30), False),   # 10:30: solo se entendia el dia
    ("el jueves de cinco a seis", (15, 30), True),   # 17:30
    ("el jueves hasta las cinco", (14, 30), True),   # 16:30: todavia esta
    ("el jueves hasta las cinco", (15, 30), False),  # 17:30: ya se ha ido
    ("entre las cinco y las seis", (15, 15), True),
    ("de las cinco a las seis", (15, 30), True),     # el tramo manda, no "a las seis" suelto
    ("a las cinco", (15, 30), True),
    ("a las cinco", (8, 30), False),
    ("el jueves a una hora rara", (8, 30), False),   # hora que no se sabe leer: no se llama
    # Cuarta vuelta (c40a60c): "no esta hasta las cinco" es "desde las cinco".
    ("el jueves no esta hasta las cinco", (14, 30), False),
    ("el jueves no esta hasta las cinco", (15, 30), True),
    ("no llega antes de las cinco", (15, 30), True),
    ("por la tarde no, mejor otro dia", (15, 30), False),  # otra negacion: no se adivina
])
def test_se_respeta_la_hora_entera_que_dijeron(lanzador, cuando, hora_utc, llama):  # noqa: F811
    ahora = JUEVES.replace(hour=hora_utc[0], minute=hora_utc[1])
    creada = ahora - timedelta(hours=30)  # la llamada fue el miercoles
    _hablo_con_un_empleado(lanzador, cuando=cuando, hace_horas=(MARTES_16_30 - creada).total_seconds() / 3600)
    assert bool(lanzador.rellamadas_dirigidas(ahora)) is llama


def test_descargar_el_jsonl_no_gasta_los_reintentos(llamada, captacion, monkeypatch):  # noqa: F811
    from backend import settings

    llamada_id, t = llamada
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEYS", ["k_vieja"])
    reloj = [captacion.timeutils._utc_now()]
    monkeypatch.setattr(t.timeutils, "_utc_now", lambda: reloj[0])

    class _Caida(_Api):
        codigo = 503

        def get(self, url, headers=None, **k):
            self.pedidas.append(url)
            return _Respuesta(self.codigo, _conversacion() if self.codigo == 200 else {})

    api = _Caida(None)
    for _ in range(t.MAX_INTENTOS):  # a la misma hora, como al descargar varias veces
        t.recoger_pendientes(cliente=api)
    reloj[0] += timedelta(hours=2)
    api.codigo = 200
    assert t.recoger_pendientes(cliente=api) == 1
    assert t.de_la_llamada(llamada_id) is not None


def test_recogidas_a_la_vez_gastan_un_solo_intento(llamada, captacion, monkeypatch):  # noqa: F811
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from backend import settings

    llamada_id, t = llamada
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEYS", ["k_vieja"])
    reloj = [captacion.timeutils._utc_now()]
    monkeypatch.setattr(t.timeutils, "_utc_now", lambda: reloj[0])
    todos_eligen, hilo = threading.Barrier(8), threading.local()
    claves = t.cuenta_elevenlabs.claves

    def espera_a_los_demas():  # las ocho han leido la cola antes de que nadie apunte nada
        if not getattr(hilo, "visto", False):
            hilo.visto = True
            todos_eligen.wait(timeout=10)
        return claves()

    monkeypatch.setattr(t.cuenta_elevenlabs, "claves", espera_a_los_demas)

    class _Caida(_Api):
        def get(self, url, headers=None, **k):
            return _Respuesta(503, {})

    with ThreadPoolExecutor(max_workers=8) as hilos:
        list(hilos.map(lambda _: t.recoger_pendientes(cliente=_Caida(None)), range(8)))
    with t._db() as conn:
        intentos = conn.execute("SELECT intentos FROM llamadas_transcripcion_intentos WHERE llamada_id=?",
                                (llamada_id,)).fetchone()[0]
    assert intentos == 1
