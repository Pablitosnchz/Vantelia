# -*- coding: utf-8 -*-
"""Dejar de pedirle un numero de reserva que no tiene.

Para cancelar o cambiar una cita habia que dar el codigo `R-XXXX`. Una clienta
real no lo tiene a mano: lo recibio por WhatsApp hace dos semanas. El asistente se
lo pedia, ella no lo encontraba, y la conversacion se moria ahi: la cita seguia
VIVA, el hueco ocupado, y ella convencida de haberla anulado. En la medicion de
100 conversaciones, tres de cada diez cancelaciones acababan asi.

Su telefono ya esta verificado por el canal -es su WhatsApp, o su llamada-, asi
que la cita se puede buscar por el. Si tiene varias, se le pregunta CUAL, que es
una pregunta que si sabe contestar ("la del jueves").

Las dos mitades que se fijan aqui:

* sin codigo, con telefono verificado, se encuentra su cita, y
* el telefono que ELLA escribe no sirve para eso. Si sirviera, cualquiera podria
  cancelar la cita de otra persona escribiendo su numero.
"""
from __future__ import annotations

import asyncio

from test_booking_exhaustive import api_module, client  # noqa: F401


def _dejar_cita(cliente_id, telefono, dia_extra=2, codigo="R-9001"):
    """Una cita suya en la agenda. Se inserta directa a proposito: lo que se prueba
    aqui es ENCONTRARLA por el telefono, no el catalogo ni los huecos."""
    import datetime
    import uuid

    from backend import db, timeutils

    dia = (timeutils._utc_now().date() + datetime.timedelta(days=dia_extra)).isoformat()
    ahora = timeutils._utc_now().isoformat()
    with db._get_db_connection() as conexion:
        conexion.execute(
            "INSERT INTO bookings (id, cliente_id, nombre, email, telefono, servicio,"
            " booking_date, booking_time, notas, status, provider_status, booking_code,"
            " created_at, source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, cliente_id, "Ana Ruiz", "", telefono, "Corte senora",
             dia, "10:00", "", "confirmed", "none", codigo, ahora, "test"))
        conexion.commit()
        fila = conexion.execute(
            "SELECT * FROM bookings WHERE cliente_id=? AND booking_code=?",
            (cliente_id, codigo)).fetchone()
    return fila


def _limpiar(cliente_id, telefono):
    from backend import db

    with db._get_db_connection() as conexion:
        conexion.execute("DELETE FROM bookings WHERE cliente_id=? AND telefono=?",
                         (cliente_id, telefono))
        conexion.commit()


def test_sin_codigo_pero_con_su_telefono_se_encuentra_su_cita(api_module, client):  # noqa: F811
    from backend import voice

    telefono = "34600880001"
    _limpiar("demo", telefono)
    try:
        cita = _dejar_cita("demo", telefono)
        assert cita is not None, "no se ha podido montar la cita de prueba"

        fila, error = asyncio.run(voice._voice_lookup_and_verify_booking(
            "demo", "", from_number=telefono))
        assert error is None, error
        assert fila["booking_code"] == cita["booking_code"]
    finally:
        _limpiar("demo", telefono)


def test_con_dos_citas_se_le_pregunta_cual_y_no_el_codigo(api_module, client):  # noqa: F811
    """Preguntar "¿cual de las dos?" lo sabe contestar; el codigo, no."""
    from backend import voice

    telefono = "34600880002"
    _limpiar("demo", telefono)
    try:
        primera = _dejar_cita("demo", telefono, dia_extra=2, codigo="R-9002")
        segunda = _dejar_cita("demo", telefono, dia_extra=9, codigo="R-9003")
        assert primera is not None and segunda is not None
        assert primera["booking_code"] != segunda["booking_code"]

        fila, error = asyncio.run(voice._voice_lookup_and_verify_booking(
            "demo", "", from_number=telefono))
        assert fila is None and error is not None
        assert error.get("varias") is True
        assert len(error.get("citas") or []) >= 2
        assert "numero de reserva" in error["error"].lower(), (
            "tiene que decirle al modelo que NO pida el codigo"
        )
    finally:
        _limpiar("demo", telefono)


def test_el_telefono_que_escribe_el_cliente_no_abre_citas_ajenas(api_module, client):  # noqa: F811
    """Si sirviera, cualquiera cancelaria la cita de otra persona con su numero."""
    from backend import voice

    telefono = "34600880003"
    _limpiar("demo", telefono)
    try:
        assert _dejar_cita("demo", telefono, codigo="R-9004") is not None
        # Sin codigo y sin telefono del CANAL: aunque lo escriba, no vale.
        fila, error = asyncio.run(voice._voice_lookup_and_verify_booking(
            "demo", "", from_number="", telefono=telefono))
        assert fila is None and error is not None
    finally:
        _limpiar("demo", telefono)


def test_sin_cita_ninguna_no_se_da_por_cancelada(api_module, client):  # noqa: F811
    """"No encuentro nada" no puede sonar a "ya esta cancelada"."""
    from backend import voice

    fila, error = asyncio.run(voice._voice_lookup_and_verify_booking(
        "demo", "", from_number="34600889999"))
    assert fila is None
    assert error and "sin darla por cancelada" in error["error"]


def test_las_tools_de_gestion_ya_no_exigen_el_codigo(api_module, client):  # noqa: F811
    """Si el esquema lo exige, el modelo se lo pide a ella igualmente."""
    from backend import voice

    from backend import appstate

    config = appstate.CONFIG_CLIENTES.get("demo") or {}
    tools = {t["name"]: t for t in voice._voice_booking_tools("demo", config)}
    assert tools, "el tenant de prueba no tiene reserva activada"
    for nombre in ("consultar_cita", "cancelar_cita", "reprogramar_cita"):
        requeridos = tools[nombre]["parameters"]["required"]
        assert "codigo_reserva" not in requeridos, nombre
    # Y las de verificacion SI lo siguen exigiendo: ahi el codigo es la prueba.
    assert "codigo_reserva" in tools["enviar_codigo_verificacion"]["parameters"]["required"]


def test_las_tools_del_agente_tampoco_exigen_el_codigo(api_module, client):  # noqa: F811
    """El agente tiene su PROPIO esquema de tools, y ese es el que usa WhatsApp.

    Arreglarlo solo en el de la voz habria dejado el fallo intacto por el canal
    que usa el salon: la misma leccion de siempre, el arreglo en la capa que no
    era.
    """
    from backend import agent

    tools = {t["function"]["name"]: t["function"] for t in agent._herramientas()}
    for nombre in ("cancelar_cita", "reprogramar_cita"):
        requeridos = tools[nombre]["parameters"].get("required") or []
        assert "codigo_reserva" not in requeridos, nombre
    # Y reprogramar sigue exigiendo a donde se mueve: sin eso no se puede mover.
    assert set(tools["reprogramar_cita"]["parameters"]["required"]) == {"fecha", "hora"}
