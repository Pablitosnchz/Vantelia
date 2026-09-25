# -*- coding: utf-8 -*-
"""Lo que cazo Astra al revisar el lanzador de Sara y la rotacion de cuentas (24-sep-2026).

POR QUE EXISTE
--------------
Astra reviso 1c4e6a7 (lanzador + Lista Robinson) y d57a362..e535899 (rotacion de
cuentas de ElevenLabs) y reprodujo ocho fallos con los modulos reales y sin red. Tres
eran criticos: con una respuesta incompleta de la Lista Robinson se llamaba igual; una
rotacion con la sincronizacion rota daba la cuenta nueva por buena y se marcaba con los
agentes de la vieja; y con dos claves de la misma cuenta se borraba el agente de
telefono que seguia en uso. Cada test de aqui es uno de sus casos (actas en
docs/REVISION_LANZADOR_24SEP.md y docs/REVISION_CUENTAS_ELEVENLABS_24SEP.md, rama de
Astra) y falla sin el arreglo.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401
from test_cuenta_elevenlabs import _Reserva, _Respuesta, _suscripcion, cuenta, reserva  # noqa: F401
from test_lanzador_llamadas import MARTES_10_30, _llamada_previa, _Marcador, _prospecto, lanzador  # noqa: F401


# --- Lista Robinson -------------------------------------------------------------

class _Http(_Respuesta):
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP %s" % self.status_code)


class _RobinsonQueContesta:
    def __init__(self, elemento):
        self.elemento = elemento

    def post(self, url, content=b"", **k):
        return _Respuesta(200, {h: self.elemento for h in content.decode().split(",")})


@pytest.mark.parametrize("elemento", [{}, None, {"found": None}, {"found": "false"}, {"found": 0}])
def test_una_respuesta_incompleta_de_robinson_no_es_que_no_este(lanzador, elemento):  # noqa: F811
    from backend import lista_robinson

    with pytest.raises(RuntimeError):
        lista_robinson.consultar(["+34911111111"], cliente=_RobinsonQueContesta(elemento))


def test_con_robinson_incompleto_no_se_llama_ni_se_apunta(lanzador):  # noqa: F811
    from backend import lista_robinson

    lanzador.guardar_config(activo=True)
    _prospecto(lanzador, "a@pelu.es", "911111111")
    marcador = _Marcador(lanzador, MARTES_10_30)
    lanzador.ronda(ahora=MARTES_10_30, llamar=marcador, consultar=lambda numeros: lista_robinson.consultar(
        numeros, cliente=_RobinsonQueContesta({"found": None})))
    with lanzador._db() as conn:
        apuntados = conn.execute("SELECT COUNT(*) FROM robinson_consultas").fetchone()[0]
    assert marcador.llamados == [] and apuntados == 0


# --- Lo que cambia mientras contesta Robinson -------------------------------------

def test_apagado_mientras_contesta_robinson_no_marca(lanzador):  # noqa: F811
    lanzador.guardar_config(activo=True)
    _prospecto(lanzador, "a@pelu.es", "911111111")

    def robinson(numeros):
        lanzador.guardar_config(activo=False)
        return {n: False for n in numeros}

    marcador = _Marcador(lanzador, MARTES_10_30)
    lanzador.ronda(ahora=MARTES_10_30, llamar=marcador, consultar=robinson)
    assert marcador.llamados == []


def test_si_la_franja_se_acaba_mientras_contesta_robinson_no_marca(lanzador):  # noqa: F811
    lanzador.guardar_config(activo=True)
    _prospecto(lanzador, "a@pelu.es", "911111111")
    hora = [datetime(2026, 9, 29, 10, 29, 50, tzinfo=timezone.utc)]  # 12:29:50 en Madrid

    def robinson(numeros):
        hora[0] += timedelta(seconds=20)  # contesta a las 12:30:10, ya fuera de la franja
        return {n: False for n in numeros}

    marcador = _Marcador(lanzador, hora[0])
    lanzador.ronda(reloj=lambda: hora[0], llamar=marcador, consultar=robinson)
    assert marcador.llamados == []


def test_si_bajan_el_cupo_mientras_contesta_robinson_no_se_pasa(lanzador):  # noqa: F811
    lanzador.guardar_config(activo=True)
    _prospecto(lanzador, "a@pelu.es", "911111111")
    _llamada_previa(lanzador, "+34912222222", MARTES_10_30 - timedelta(hours=1), resultado="interesado")

    def robinson(numeros):
        lanzador.guardar_config(cupo_diario=1)
        return {n: False for n in numeros}

    marcador = _Marcador(lanzador, MARTES_10_30)
    lanzador.ronda(ahora=MARTES_10_30, llamar=marcador, consultar=robinson)
    assert marcador.llamados == []


# --- Reintentos --------------------------------------------------------------------

def test_una_conversacion_sin_herramienta_no_se_reintenta(lanzador):  # noqa: F811
    """Hablo con Sara y colgo sin que apuntara nada: resultado vacio, pero hubo conversacion."""
    from backend import captacion_voz

    lanzador.guardar_config(activo=True)
    _prospecto(lanzador, "a@pelu.es", "911111111")
    _llamada_previa(lanzador, "+34911111111", MARTES_10_30 - timedelta(days=3), estado="en_curso")
    with lanzador._db() as conn:
        conn.execute("UPDATE llamadas_voz SET conversation_id='conv_real'")
        conn.commit()
    llamada = lanzador._db().execute("SELECT id FROM llamadas_voz").fetchone()[0]
    captacion_voz.estado_final(llamada, "completed")
    assert lanzador.candidatos(MARTES_10_30) == []


# --- Publicar un agente --------------------------------------------------------------

def test_si_el_agente_no_aparece_tras_guardarlo_no_se_borran_sus_tools(api_module):  # noqa: F811
    from backend import voz_elevenlabs

    class _Api:
        def __init__(self):
            self.lecturas, self.borradas = 0, []

        def get(self, url, **k):
            self.lecturas += 1
            if self.lecturas == 1:
                return _Http(200, {"conversation_config": {"agent": {"prompt": {"tool_ids": ["tool_1"]}}}})
            return _Http(404, {"detail": "not_found"})

        def patch(self, url, **k):
            return _Http(200, {"agent_id": "agent_1"})

        def delete(self, url, **k):
            self.borradas.append(url)
            return _Respuesta(204)

    api = _Api()
    with pytest.raises(RuntimeError):
        voz_elevenlabs.publicar_agente(api, {}, "agent_1")
    assert api.borradas == []


# --- Rotacion de cuentas ---------------------------------------------------------------

def test_si_no_se_crean_los_agentes_la_cuenta_no_cambia(cuenta, reserva, monkeypatch, tmp_path):  # noqa: F811
    from backend import appstate, clients, settings

    monkeypatch.setattr(clients, "_persist_configs_to_disk", lambda configs: None)

    def sincronizar_a_medias():
        appstate.CONFIG_CLIENTES["negocio_voz"]["voice"]["elevenlabs_agent_id"] = "agent_a_medias"
        reserva.agentes["agent_a_medias"] = ["tool_a_medias"]
        raise RuntimeError("Fallo creando el agente de telefono")

    monkeypatch.setattr(cuenta, "sincronizar_agentes", sincronizar_a_medias)
    salida = cuenta.rotar("prueba", cliente=reserva)
    assert salida["rotada"] is False
    assert settings.ELEVENLABS_API_KEY == "k_agotada", "se sigue con la cuenta de antes"
    assert appstate.CONFIG_CLIENTES["negocio_voz"]["voice"]["elevenlabs_agent_id"] == "agent_viejo"
    assert not (tmp_path / "elevenlabs_cuenta_activa.json").exists(), "no se guarda una cuenta sin agentes"
    assert ("k_buena", "agent_a_medias") in reserva.borrados, "lo creado a medias se quita de la cuenta nueva"
    assert ("k_agotada", "agent_viejo") not in reserva.borrados
    assert len(cuenta.correos) == 1 and "no se pudo" in cuenta.correos[0][0].lower()
    # Y no se reintenta con esa cuenta en cada ronda.
    assert cuenta.rotar("otra vez", cliente=reserva)["a"] != cuenta.huella("k_buena")


def test_la_principal_fuera_de_la_reserva_se_recupera(cuenta, reserva, monkeypatch):  # noqa: F811
    from backend import settings

    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "k_principal")
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEYS", ["k_buena", "k_otra"])
    reserva.cuentas["k_principal"] = _suscripcion(usados=300000)
    assert cuenta.rotar("sin creditos", cliente=reserva)["rotada"] is True
    reserva.cuentas["k_principal"] = _suscripcion()  # se renuevan sus creditos
    assert cuenta.vigilar_una_vez(cliente=reserva) == "rotada"
    assert settings.ELEVENLABS_API_KEY == "k_principal"


def test_dos_claves_de_la_misma_cuenta_no_borran_el_agente_de_telefono(cuenta, reserva, monkeypatch):  # noqa: F811
    from backend import appstate, settings

    monkeypatch.setitem(appstate.CONFIG_CLIENTES, "negocio_voz", {"voice": {
        "elevenlabs_agent_id": "web_compartido", "elevenlabs_agent_id_telefono": "tel_compartido"}})
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "k_buena")
    reserva.agentes.update({"web_compartido": [], "tel_compartido": []})
    # La sincronizacion de verdad devuelve el id web y deja los dos donde estaban.
    monkeypatch.setattr(cuenta, "sincronizar_agentes", lambda: {"negocio_voz": "web_compartido"})
    assert cuenta.rotar("prueba", cliente=reserva, destino="k_otra")["rotada"] is True
    assert reserva.borrados == []


def test_las_claves_no_salen_en_log_correo_ni_respuesta(cuenta, reserva, monkeypatch, caplog):  # noqa: F811
    def falla():
        raise RuntimeError("Denied api key k_buena (y otra suelta sk_abcdefghijklmnopqrstu)")

    monkeypatch.setattr(cuenta, "sincronizar_agentes", falla)
    with caplog.at_level(logging.DEBUG):
        salida = cuenta.rotar("prueba", cliente=reserva)
    superficies = {"log": caplog.text, "correo": repr(cuenta.correos), "respuesta": json.dumps(salida)}
    for nombre, texto in superficies.items():
        assert "k_buena" not in texto and "sk_abcdefghijklmnopqrstu" not in texto, nombre
    assert cuenta.huella("k_buena") in salida["error"]


def test_el_error_de_voz_se_guarda_sin_claves(al_descolgar_con_clave):
    lanzador, captacion_voz = al_descolgar_con_clave
    lanzador.fallo_de_voz("ll_x", "ElevenLabs rejected key k_buena")
    assert "k_buena" not in captacion_voz._fila("ll_x")["notas"]


@pytest.fixture()
def al_descolgar_con_clave(cuenta, reserva, monkeypatch, tmp_path):  # noqa: F811
    from backend import captacion_voz, lanzador_llamadas

    monkeypatch.setenv("OUTREACH_DB_PATH", str(tmp_path / "outreach.db"))
    monkeypatch.setattr(cuenta, "estado", lambda **k: {"ok": True, "tipo": "", "problema": ""})
    with captacion_voz._db() as conn:
        conn.execute("INSERT INTO llamadas_voz (id, telefono, estado, origen, creada, actualizada) "
                     "VALUES ('ll_x', '+34911111111', 'en_curso', 'auto', 'x', 'x')")
        conn.commit()
    return lanzador_llamadas, captacion_voz
