# -*- coding: utf-8 -*-
"""Saber que hizo el asistente sin escribir un script cada vez.

El 26 de agosto de 2026, para averiguar por que dijo "a las 10:30 ya tengo una
cita" -mentira: estaba libre para las cinco profesionales- hubo que escribir tres
scripts desechables. Ese dia se escribieron doce.

Con la traza, la misma pregunta se contesta mirando una fila: en ese turno no se
llamo a `consultar_disponibilidad`.

Aqui se comprueban las dos cosas que la harian inutil o peligrosa:

* que no sirva -que no apunte las herramientas, los frenos o el coste-, y
* que ESTORBE: una traza jamas puede tumbar una conversacion. Es un cuaderno.
"""
from __future__ import annotations

from test_booking_exhaustive import api_module, client  # noqa: F401


def _limpiar(session_id: str) -> None:
    from backend import db

    with db._get_db_connection() as conexion:
        conexion.execute("DELETE FROM agent_turns WHERE session_id = ?", (session_id,))
        conexion.commit()


def test_apunta_las_herramientas_y_los_frenos(api_module, client):  # noqa: F811
    """Es lo que explica una respuesta rara sin tener que reproducirla."""
    from backend import trazas

    _limpiar("s_traza")
    try:
        traza = trazas.Traza("demo", "s_traza", canal="whatsapp")
        traza.tool("buscar_servicio", {"descripcion": "mechas"}, ok=True, ms=40)
        traza.tool("consultar_disponibilidad", {"fecha": "2026-09-01"}, ok=True, ms=120)
        traza.freno("se_repetia")
        traza.vuelta()
        traza.modelo("gpt-4o-mini", prompt=1200, salida=180)
        traza.guardar(mensaje="quiero mechas", respuesta="¿que dia te viene bien?")

        turnos = trazas.del_turno("demo", "s_traza")
        assert len(turnos) == 1
        turno = turnos[0]
        assert [h["nombre"] for h in turno["herramientas"]] == [
            "buscar_servicio", "consultar_disponibilidad"]
        assert turno["frenos"] == ["se_repetia"]
        assert turno["tokens"] == {"entrada": 1200, "salida": 180}
        assert turno["coste_euros"] > 0
        assert turno["canal"] == "whatsapp"
    finally:
        _limpiar("s_traza")


def test_sabe_si_se_consulto_la_agenda(api_module, client):  # noqa: F811
    """Es lo que convierte "parece que no miro" en un hecho."""
    from backend import trazas

    traza = trazas.Traza("demo", "s_uso")
    traza.tool("buscar_servicio", {}, ok=True)
    assert traza.uso("buscar_servicio") is True
    assert traza.uso("consultar_disponibilidad") is False


def test_el_coste_sale_en_euros_y_distingue_modelos(api_module):  # noqa: F811
    """Nos enteramos de que se acababa el saldo porque se cayo produccion."""
    from backend import trazas

    barato = trazas.coste_euros("gpt-4o-mini", 1000, 500)
    caro = trazas.coste_euros("gpt-4o", 1000, 500)
    assert 0 < barato < caro, "el modelo caro tiene que salir mas caro"
    # Un modelo que no conocemos no inventa un precio.
    assert trazas.coste_euros("modelo-raro", 1000, 500) == 0.0


def test_una_traza_rota_no_tumba_la_conversacion(api_module, client, monkeypatch):  # noqa: F811
    """REGLA DE ORO: es un cuaderno de bitacora, no la conversacion.

    Un cliente no se puede quedar sin respuesta porque no se pudo apuntar una
    metrica.
    """
    from backend import db, trazas

    def _revienta(*_args, **_kwargs):
        raise RuntimeError("la base de datos se ha caido")

    monkeypatch.setattr(db, "_get_db_connection", _revienta)
    traza = trazas.Traza("demo", "s_rota")
    traza.tool("crear_cita", {}, ok=True)
    traza.guardar(mensaje="hola", respuesta="buenas")   # no debe levantar


def test_el_resumen_cuenta_conversaciones_coste_y_frenos(api_module, client):  # noqa: F811
    from backend import trazas

    _limpiar("s_res1")
    _limpiar("s_res2")
    try:
        for session_id, freno in (("s_res1", "se_repetia"), ("s_res2", "precio_que_no_se_da")):
            traza = trazas.Traza("demo", session_id)
            traza.freno(freno)
            traza.modelo("gpt-4o-mini", prompt=1000, salida=100)
            traza.guardar(mensaje="hola", respuesta="hola")

        resumen = trazas.resumen_del_dia("demo")
        assert resumen["conversaciones"] >= 2
        assert resumen["coste_euros"] > 0
        assert resumen["coste_por_conversacion"] > 0
        nombres = [nombre for nombre, _veces in resumen["frenos"]]
        assert "se_repetia" in nombres and "precio_que_no_se_da" in nombres
    finally:
        _limpiar("s_res1")
        _limpiar("s_res2")


def test_las_trazas_viejas_se_borran_solas(api_module, client):  # noqa: F811
    """Son para depurar y medir, no un archivo historico de conversaciones."""
    from backend import db, timeutils, trazas

    with db._get_db_connection() as conexion:
        conexion.execute(
            "INSERT INTO agent_turns (cliente_id, session_id, created_at)"
            " VALUES ('demo', 's_vieja', ?)",
            ((timeutils._utc_now().replace(year=timeutils._utc_now().year - 1)).isoformat(),),
        )
        conexion.commit()
    borradas = trazas.limpiar_viejas(dias=30)
    assert borradas >= 1
    assert trazas.del_turno("demo", "s_vieja") == []


def test_el_agente_deja_traza_de_lo_que_hace(api_module):  # noqa: F811
    """Si nadie la rellena, la tabla esta vacia y esto no sirve de nada."""
    import inspect

    from backend import agent

    fuente = inspect.getsource(agent.responder)
    assert "traza.tool(" in fuente, "no apunta las herramientas"
    assert "traza.freno(" in fuente, "no apunta que freno ha saltado"
    assert "traza.modelo(" in fuente, "no apunta el coste"
    # Y se guarda en TODOS los finales, incluido el que revienta: es cuando mas
    # falta hace saber que paso.
    assert fuente.count("traza.guardar(") >= 3, (
        "hay caminos de salida que no dejan traza"
    )
