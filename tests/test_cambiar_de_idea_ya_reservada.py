# -*- coding: utf-8 -*-
"""Cambiar de idea con la cita ya cogida no deja mentiras ni citas de sobra.

POR QUE EXISTE
--------------
3-sep-2026, simulador. La clienta reserva unas mechas el domingo a las 12:00 y
luego cambia de idea:

    ELLA  he estado pensando y creo que solo quiero cortarme las puntas
    IA    Entonces haremos un corte de puntas en lugar de las mechas.
    ELLA  el domingo a las 11:30
    IA    Perfecto, te esperamos el domingo a las 11:30 para cortarte las puntas.

En la agenda seguian las MECHAS a las 12:00. Se lo dijo tres veces. En otras
tiradas le cogia una SEGUNDA cita y dejaba la primera puesta: el salon se come un
hueco largo que nadie ocupa.

LA CAUSA no era el modelo: la tool `reprogramar_cita` del agente solo aceptaba
fecha y hora. El motor de debajo (`_voice_reschedule_booking`) SI sabe cambiar el
servicio, pero el agente no tenia como pedirlo, asi que solo le quedaban salidas
malas: dejarlo como estaba, coger otra cita, o decir que lo habia cambiado.

MEDIDO con `--persona cambia-de-idea`, 8 conversaciones, misma semilla:

    linea base                       12,5 %   (3 servicio, 1 duplicada, 1 repite)
    + freno de la hora               25,0 %   (4 servicio)
    + servicio en la tool            50,0 %   (3 servicio, 1 duplicada)
"""
from __future__ import annotations

from test_booking_exhaustive import api_module  # noqa: F401


def _tool(agent, nombre):
    for t in agent._herramientas():
        if (t.get("function") or {}).get("name") == nombre:
            return t["function"]
    raise AssertionError("no existe la tool %s" % nombre)


def test_reprogramar_puede_cambiar_el_servicio(api_module):
    from backend import agent

    f = _tool(agent, "reprogramar_cita")
    props = f["parameters"]["properties"]
    assert "servicio" in props, (
        "sin este parametro el agente no puede cambiar el servicio de una cita, y "
        "acaba cogiendo una segunda o diciendo que lo ha cambiado sin hacerlo"
    )
    assert "servicio" not in f["parameters"].get("required", []), (
        "cambiar solo el dia y la hora tiene que seguir valiendo"
    )
    assert "segunda cita" in f["description"], (
        "la descripcion tiene que decirle que NO coja otra cita"
    )


def test_no_le_confirma_una_hora_que_no_es_la_suya(api_module, monkeypatch):
    from backend import agent, booking

    monkeypatch.setattr(booking, "citas_vivas_del_telefono",
                        lambda c, t: [{"booking_time": "12:00"}])

    assert agent._le_dice_una_hora_que_no_es_la_suya(
        "demo", "34600111222",
        "Perfecto, te esperamos el domingo a las 11:30 para cortarte las puntas.",
        False) == "12:00"

    # La suya SI se le puede confirmar.
    assert not agent._le_dice_una_hora_que_no_es_la_suya(
        "demo", "34600111222", "Te espero el domingo a las 12:00 para tus mechas.",
        False)


def test_ofrecer_huecos_no_es_confirmar(api_module, monkeypatch):
    """Sin esto, el freno se comeria cualquier lista de horas libres."""
    from backend import agent, booking

    monkeypatch.setattr(booking, "citas_vivas_del_telefono",
                        lambda c, t: [{"booking_time": "12:00"}])

    assert not agent._le_dice_una_hora_que_no_es_la_suya(
        "demo", "34600111222",
        "Tengo disponibles las 11:30, las 12:30 y las 13:00. Cual prefieres?", False)


def test_si_acaba_de_moverla_no_frena(api_module, monkeypatch):
    """Cuando SI ha tocado la agenda, la hora nueva es la buena."""
    from backend import agent, booking

    monkeypatch.setattr(booking, "citas_vivas_del_telefono",
                        lambda c, t: [{"booking_time": "12:00"}])

    assert not agent._le_dice_una_hora_que_no_es_la_suya(
        "demo", "34600111222", "Listo, te espero a las 11:30.", True)


def test_con_varias_citas_no_se_adivina(api_module, monkeypatch):
    from backend import agent, booking

    monkeypatch.setattr(booking, "citas_vivas_del_telefono",
                        lambda c, t: [{"booking_time": "12:00"},
                                      {"booking_time": "17:00"}])

    assert not agent._le_dice_una_hora_que_no_es_la_suya(
        "demo", "34600111222", "Te espero a las 11:30.", False)


def test_el_freno_esta_cableado(api_module):
    import inspect

    from backend import agent

    fuente = inspect.getsource(agent.responder)
    assert "_le_dice_una_hora_que_no_es_la_suya(" in fuente
    assert 'traza.freno("hora_que_no_es_la_suya")' in fuente
