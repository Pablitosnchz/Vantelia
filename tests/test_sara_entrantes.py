# -*- coding: utf-8 -*-
"""Sara atiende las llamadas que entran al 91 (casi siempre, devolver una llamada suya).

POR QUE EXISTE
--------------
Pablo, 30-sep-2026: "si llaman de vuelta, que llamen al asistente y que atienda Sara", y
nunca desviarlo a su movil. El puente pasa la entrante a ElevenLabs con el numero de quien
llama (X-Caller-ID -> system__caller_id). Revision de Astra: una entrante no trae el id de la
llamada, asi que sin ficha propia las herramientas respondian "No encuentro esta llamada".
Plan y tabla de fallos: docs/PLAN_SARA_ENTRANTES.md.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_booking_exhaustive import api_module  # noqa: F401
from test_captacion_voz import _Falso, captacion, envios  # noqa: F401
from test_lanzador_llamadas import MARTES_10_30, _llamada_previa, lanzador  # noqa: F401
from test_sara_por_sip import sip  # noqa: F401
from test_segunda_oportunidad import MARTES_1630, _llamada, _negocio, _ronda, so  # noqa: F401


def _entrante(**cuerpo):
    return dict({"_llamada": "", "_quien": "+34675802001", "_conversacion": "conv_in_1"}, **cuerpo)


def test_las_herramientas_llevan_quien_llama_y_la_entrante_tiene_su_saludo(captacion):  # noqa: F811
    agente = captacion.agente_de_captacion("https://app.test")["conversation_config"]["agent"]
    enviar = [t for t in agente["prompt"]["tools"] if t["name"] == "enviar_informacion"][0]
    campos = enviar["api_schema"]["request_body_schema"]["properties"]
    assert campos["_quien"]["dynamic_variable"] == "system__caller_id"
    assert campos["_conversacion"]["dynamic_variable"] == "system__conversation_id"
    # Si nadie manda variables (solo pasa en una entrante), saluda como quien coge el telefono.
    por_defecto = agente["dynamic_variables"]["dynamic_variable_placeholders"]
    assert (por_defecto["saludo"], por_defecto["sentido"]) == (captacion.SALUDO_ENTRANTE, "entrante")
    assert "una IA" in captacion.SALUDO_ENTRANTE.split(".")[0], "tambien al coger: que es una IA, en la primera frase"
    assert "SI TE LLAMAN ELLOS" in agente["prompt"]["prompt"] and "{{sentido}}" in agente["prompt"]["prompt"]
    # Las salientes mandan siempre lo suyo.
    hecho = captacion.llamar("911111111", "Pelu Marta", "peluqueria", "", origen="auto", cliente=_Falso())
    variables = captacion._variables(captacion._fila(hecho["llamada"]))
    assert (variables["sentido"], variables["saludo"]) == ("saliente", captacion.APERTURA)


def test_la_sara_que_coge_el_91_no_necesita_ninguna_variable(captacion):  # noqa: F811
    """Primera prueba de verdad (30-sep, 22:54): ElevenLabs colgo la entrante al segundo con
    "Missing required dynamic variables in first message: {'saludo'}". Los valores por defecto
    del agente NO valen en una llamada SIP que entra: la Sara del 91 no puede usar ninguna
    variable nuestra, ni en el saludo, ni en el guion, ni en las herramientas."""
    import re

    agente = captacion.agente_de_captacion("https://app.test", entrada=True)
    assert agente["name"] == captacion.NOMBRE_DEL_AGENTE_ENTRADA != captacion.NOMBRE_DEL_AGENTE
    config = agente["conversation_config"]["agent"]
    assert config["first_message"] == captacion.SALUDO_ENTRANTE
    assert "{{" not in config["first_message"] + config["prompt"]["prompt"]
    assert "Esta llamada es entrante" in config["prompt"]["prompt"]
    assert "dynamic_variables" not in config
    usadas = {campo["dynamic_variable"] for t in config["prompt"]["tools"] if t.get("type") == "webhook"
              for campo in t["api_schema"]["request_body_schema"]["properties"].values() if "dynamic_variable" in campo}
    assert usadas == {"system__caller_id", "system__conversation_id"}, "solo las que pone ElevenLabs"
    # El resto de la Sara de siempre, igual: mismo guion y mismas herramientas.
    normal = captacion.agente_de_captacion("https://app.test")["conversation_config"]["agent"]
    assert [t["name"] for t in config["prompt"]["tools"]] == [t["name"] for t in normal["prompt"]["tools"]]
    assert config["prompt"]["prompt"] == captacion.guion_de_entrada()
    assert re.sub(r"\{\{\w+\}\}", "", normal["prompt"]["prompt"]).count("\n") == config["prompt"]["prompt"].count("\n")
    assert "LA DEMO GRATUITA" in config["prompt"]["prompt"]


def test_la_sara_que_llama_recibe_todas_las_variables_que_usa(captacion):  # noqa: F811
    """La misma trampa en las salientes: una {{variable}} del guion o del primer mensaje que el
    servidor no mande colgaria TODAS las llamadas al segundo."""
    import re

    agente = captacion.agente_de_captacion("https://app.test")["conversation_config"]["agent"]
    usadas = set(re.findall(r"\{\{(\w+)\}\}", agente["first_message"] + agente["prompt"]["prompt"]))
    for rellamada in (False, True):
        hecho = captacion.llamar("911111111" if not rellamada else "911111112", "Pelu Marta", "peluqueria", "",
                                 origen="auto", cliente=_Falso())
        if rellamada:
            captacion._actualizar(hecho["llamada"], responsable_nombre="Marta")
            with captacion._db() as conn:
                conn.execute("UPDATE llamadas_voz SET rellamada_de='ll_x' WHERE id=?", (hecho["llamada"],))
                conn.commit()
        mandadas = captacion._variables(captacion._fila(hecho["llamada"]))
        assert usadas <= set(mandadas), usadas - set(mandadas)
        assert all(str(mandadas[v]) for v in usadas if v != "email_negocio"), "ninguna vacia que se note"


def test_el_puente_pasa_de_verdad_quien_llama():
    """En la subrutina de cabeceras CALLERID(num) es el del canal hacia ElevenLabs ("s"): la
    primera entrante llego con X-Caller-ID: s y sin forma de encontrar su ficha."""
    from pathlib import Path

    conf = (Path(__file__).resolve().parents[1] / "deploy" / "sara-puente" / "extensions.conf").read_text(
        encoding="utf-8")
    entrante = conf.split("[entrante]", 1)[1].split("\n[", 1)[0]
    cabeceras = conf.split("[cabeceras]", 1)[1].split("\n[", 1)[0]
    assert entrante.index("Set(__QUIEN=${CALLERID(num)})") < entrante.index("Dial(")
    assert "X-Caller-ID)=${QUIEN}" in cabeceras and "CALLERID" not in cabeceras


def test_la_recogida_reconoce_tambien_a_la_sara_del_91(sip):  # noqa: F811
    from backend import transcripciones_llamadas
    from test_captacion_voz import _Respuesta

    conversaciones = [
        {"conversation_id": "conv_llamar", "agent_id": "agent_sara"},
        {"conversation_id": "conv_91", "agent_id": "agent_entrada"},
        {"conversation_id": "conv_91_vieja", "agent_id": "agent_x", "agent_name": sip.NOMBRE_DEL_AGENTE_ENTRADA},
        {"conversation_id": "conv_ajena", "agent_id": "agent_negocio", "agent_name": "Asistente de un negocio"},
    ]

    class _Api:
        def get(self, url, headers=None, params=None, **k):
            return _Respuesta(200, {"conversations": conversaciones, "has_more": False})

    ids = transcripciones_llamadas._conversaciones_de_sara(_Api(), "k", {"agent_sara", "agent_entrada"}, 0)
    assert ids == ["conv_llamar", "conv_91", "conv_91_vieja"]


def test_quien_devuelve_la_llamada_recibe_la_informacion(captacion, envios):  # noqa: F811
    """Le llamamos, no lo cogio, devuelve la llamada y pide la informacion: le llega el SMS y
    la ficha es la del negocio al que llamamos."""
    captacion.llamar("675802001", "Pelu Movil", "peluqueria", "pelu@movil.es", origen="auto", cliente=_Falso())
    r = captacion.herramienta("enviar_informacion", _entrante())
    assert r["ok"] is True and "SMS" in r["mensaje"]
    assert envios["sms"] and envios["sms"][0][0] == "+34675802001"
    with captacion._db() as conn:
        filas = conn.execute("SELECT origen, negocio, prospecto, conversation_id, resultado FROM llamadas_voz "
                             "WHERE origen='entrante'").fetchall()
    assert [tuple(f) for f in filas] == [("entrante", "Pelu Movil", "pelu@movil.es", "conv_in_1", "interesado")]


def test_una_entrante_es_una_sola_ficha(captacion, envios):  # noqa: F811
    captacion.herramienta("anotar_responsable", _entrante(interlocutor="empleado", nombre="Marta"))
    captacion.herramienta("pasar_a_pablo", _entrante(cuando="por la tarde"))
    captacion.herramienta("volver_a_llamar", _entrante(_conversacion="", cuando="mañana"))  # sin conversacion: por numero
    with captacion._db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM llamadas_voz WHERE origen='entrante'").fetchone()[0] == 1


def test_dos_llamadas_del_mismo_numero_son_dos_fichas(captacion, envios):  # noqa: F811
    """Astra, 30-sep: llamaba dos veces en media hora y la segunda reutilizaba la primera ficha
    (pisaba su transcripcion y su sello de envio: no le llegaba lo que pidio)."""
    captacion.herramienta("enviar_informacion", _entrante(_conversacion="conv_primera"))
    r = captacion.herramienta("enviar_informacion", _entrante(_conversacion="conv_segunda"))
    assert r["ok"] is True and "Ya se le ha mandado" not in r["mensaje"]
    with captacion._db() as conn:
        conversaciones = sorted(f[0] for f in conn.execute(
            "SELECT conversation_id FROM llamadas_voz WHERE origen='entrante'"))
    assert conversaciones == ["conv_primera", "conv_segunda"]


def test_dos_herramientas_a_la_vez_una_sola_ficha(captacion, monkeypatch):  # noqa: F811
    """Astra, 30-sep: dos primeras peticiones a la vez de la misma entrante pasaban las dos la
    busqueda e insertaban dos fichas (dos sellos de envio: dos SMS)."""
    import threading

    original = captacion.secrets.token_urlsafe
    llegadas, las_dos = [], threading.Event()

    def id_lento(n):
        llegadas.append(1)
        if len(llegadas) >= 2:
            las_dos.set()
        las_dos.wait(1.5)  # sin cerrojo, las dos llegan aqui a la vez y cada una crea la suya
        return original(n)

    monkeypatch.setattr(captacion.secrets, "token_urlsafe", id_lento)
    ids = []
    hilos = [threading.Thread(target=lambda: ids.append(captacion._fila_entrante("+34675802001", "conv_x")["id"]))
             for _ in range(2)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(15)
    assert len(ids) == 2 and len(set(ids)) == 1
    with captacion._db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM llamadas_voz WHERE origen='entrante'").fetchone()[0] == 1


def test_si_nos_devolvio_la_llamada_no_se_le_rellama(captacion, lanzador):  # noqa: F811
    """Astra, 30-sep: el empleado dejo el nombre y la hora de la duena, ella nos llamo y pidio
    hablar con Pablo... y la rellamada de Sara seguia pendiente."""
    hecho = captacion.llamar("911111111", "Pelu Marta", "peluqueria", "hola@pelu.es", origen="auto", cliente=_Falso())
    captacion._actualizar(hecho["llamada"], estado="terminada", interlocutor="empleado", responsable_nombre="Marta",
                          responsable_cuando="por las tardes", conversation_id="conv_1")
    with captacion._db() as conn:
        conn.execute("UPDATE llamadas_voz SET creada=? WHERE id=?",
                     (lanzador._iso(MARTES_10_30 - timedelta(days=1)), hecho["llamada"]))
        conn.commit()
    tarde = MARTES_10_30 + timedelta(days=1, hours=6)
    assert len(lanzador.rellamadas_dirigidas(tarde)) == 1, "control: sin la devolucion, se rellamaria"
    captacion.herramienta("pasar_a_pablo", _entrante(_quien="+34911111111", _conversacion="conv_devuelta"))
    assert lanzador.rellamadas_dirigidas(tarde) == []


def test_sin_numero_ni_conversacion_no_se_inventa_nada(captacion):  # noqa: F811
    r = captacion.herramienta("pasar_a_pablo", _entrante(_quien="", _conversacion=""))
    assert r["ok"] is False and "No encuentro esta llamada" in r["error"]


def test_una_saliente_con_id_equivocado_no_se_cuela_como_entrante(captacion):  # noqa: F811
    r = captacion.herramienta("pasar_a_pablo", _entrante(_llamada="ll_que_no_existe"))
    assert r["ok"] is False
    with captacion._db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM llamadas_voz WHERE origen='entrante'").fetchone()[0] == 0


def _conversacion_entrante(agente="agent_sara", direccion="inbound", conversation_id="conv_in_9", numero=""):
    return {"conversation_id": conversation_id, "status": "done", "agent_id": agente,
            "transcript": [{"role": "agent", "message": "Hola, soy Sara.", "time_in_call_secs": 0},
                           {"role": "user", "message": "Me habeis llamado antes", "time_in_call_secs": 3}],
            "metadata": {"call_duration_secs": 20, "termination_reason": "end_call tool",
                         "phone_call": {"direction": direccion, "external_number": "+34911234567",
                                        "agent_number": numero}},
            "analysis": {"data_collection_results": {"interlocutor": {"value": "empleado"}}}}


def test_la_entrante_sin_herramientas_llega_igual_al_panel(sip):  # noqa: F811
    from backend import transcripciones_llamadas

    llamada_id = transcripciones_llamadas.guardar(_conversacion_entrante(), "aviso")
    assert llamada_id
    fila = sip._fila(llamada_id)
    assert (fila["origen"], fila["telefono"], fila["conversation_id"]) == ("entrante", "+34911234567", "conv_in_9")
    with transcripciones_llamadas._db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM llamadas_transcripcion WHERE llamada_id=?",
                            (llamada_id,)).fetchone()[0] == 1


def test_la_entrante_cuyo_aviso_no_llego_se_recoge(sip, monkeypatch):  # noqa: F811
    """Astra, 30-sep: sin herramientas y sin aviso de fin, la entrante no tenia ficha y la
    recogida de respaldo (que solo mira fichas) nunca la veia."""
    from backend import settings, transcripciones_llamadas
    from test_captacion_voz import _Respuesta

    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "k_activa")
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEYS", ["k_activa", "k_vieja"])
    sip._fila_entrante("+34912222222", "conv_conocida")  # esta ya tiene ficha
    pedidas = []
    # Astra (d7146ce): la perdida puede estar en la SEGUNDA pagina y en la cuenta VIEJA (tras
    # rotar), con otro id de agente pero el mismo nombre. La de otro agente no se toca.
    paginas = {
        ("k_activa", ""): {"conversations": [{"conversation_id": "conv_conocida", "agent_id": "agent_sara"}],
                           "has_more": False},
        ("k_vieja", ""): {"conversations": [{"conversation_id": "conv_de_un_negocio", "agent_id": "agent_negocio",
                                             "agent_name": "Asistente de un negocio"}],
                          "has_more": True, "next_cursor": "pag2"},
        ("k_vieja", "pag2"): {"conversations": [{"conversation_id": "conv_perdida", "agent_id": "agent_viejo",
                                                 "agent_name": sip.NOMBRE_DEL_AGENTE}], "has_more": False},
    }

    class _Api:
        def get(self, url, headers=None, params=None, **k):
            if url.endswith("/v1/convai/conversations"):
                return _Respuesta(200, paginas[(headers["xi-api-key"], (params or {}).get("cursor", ""))])
            pedidas.append(url.rsplit("/", 1)[-1])
            return _Respuesta(200, _conversacion_entrante(conversation_id="conv_perdida", agente="agent_viejo",
                                                          numero="+34910000001"))

        def close(self):
            pass

    assert transcripciones_llamadas.recoger_entrantes(cliente=_Api()) == 1
    assert pedidas == ["conv_perdida"], "solo se pide la que falta, y nunca la de otro agente"
    with sip._db() as conn:
        assert conn.execute("SELECT origen FROM llamadas_voz WHERE conversation_id='conv_perdida'").fetchone()[0] == "entrante"
    assert transcripciones_llamadas.recoger_entrantes(cliente=_Api()) == 0, "la segunda vez ya la tiene"


def test_una_entrante_recogida_tarde_conserva_su_hora(sip, lanzador):  # noqa: F811
    """Astra, 30-sep: entrante a las 10, saliente a las 11 en la que un empleado deja a quien
    decide, y la entrante se recoge a las 12. Con la hora de la recogida parecia posterior a la
    saliente y cancelaba su rellamada."""
    from backend import transcripciones_llamadas

    saliente = MARTES_10_30 - timedelta(days=1)
    _llamada_previa(lanzador, "+34911234567", saliente, estado="terminada")
    with sip._db() as conn:
        conn.execute("UPDATE llamadas_voz SET interlocutor='empleado', responsable_nombre='Marta', "
                     "responsable_cuando='por las tardes', sector='peluqueria', conversation_id='conv_saliente' "
                     "WHERE telefono='+34911234567'")
        conn.commit()
    tarde = MARTES_10_30 + timedelta(days=1, hours=6)
    assert len(lanzador.rellamadas_dirigidas(tarde)) == 1
    conversacion = _conversacion_entrante()  # la entrante fue una hora ANTES de la saliente
    conversacion["metadata"]["start_time_unix_secs"] = int((saliente - timedelta(hours=1)).timestamp())
    assert transcripciones_llamadas.guardar(conversacion, "recogida")
    assert len(lanzador.rellamadas_dirigidas(tarde)) == 1, "la rellamada sigue pendiente"


def test_la_entrante_cuenta_aunque_se_haya_cambiado_de_cuenta(sip):  # noqa: F811
    """Astra, 30-sep: el aviso llega con el agente de la cuenta vieja; el 91 es el mismo."""
    from backend import transcripciones_llamadas

    conversacion = _conversacion_entrante(agente="agent_de_la_cuenta_vieja", numero="+34910000001")
    assert transcripciones_llamadas.guardar(conversacion, "aviso")


@pytest.mark.parametrize("cambio", [{"agente": "agent_de_otro"}, {"direccion": "outbound"},
                                    {"agente": "agent_de_otro", "numero": "+34911119999"}])
def test_una_conversacion_ajena_se_sigue_ignorando(sip, cambio):  # noqa: F811
    from backend import transcripciones_llamadas

    assert transcripciones_llamadas.guardar(_conversacion_entrante(**cambio), "aviso") is None


def test_a_quien_nos_devolvio_la_llamada_no_le_llega_la_segunda_oportunidad(so, captacion):  # noqa: F811
    _negocio()
    _llamada(captacion, desenlace="colgo_al_principio")
    assert [e["prospecto"] for e in so.elegibles(MARTES_1630)] == ["hola@pelu.es"], "control: sin la entrante, si"
    captacion._fila_entrante("+34911111111", "conv_devuelta")
    registro, _ = _ronda(so, MARTES_1630)
    assert registro == []
