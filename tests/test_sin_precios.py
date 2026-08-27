# -*- coding: utf-8 -*-
"""Un negocio puede decidir que por mensaje NO se dan precios. De nada.

Lo pidio la duenya del salon el 25-ago-2026: "es mas facil que no de precio de
nada; quien quiera precio que nos llame, y si es un cambio de imagen, mechas o
extensiones, que coja cita para un diagnostico y le damos presupuesto". Tiene 191
servicios y todavia no ha decidido cuales quiere publicar.

Y lo que se midio en 100 conversaciones: negarse NO era el problema. Las
conversaciones de precio eran las peores -6 de 17 acababan bien- porque el
asistente repetia la negativa con otras palabras hasta que la clienta se cansaba.
Por eso la segunda vez tiene que CERRAR.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


@pytest.fixture
def salon_sin_precios(api_module, client):  # noqa: F811
    from backend import agenda, clients, db, timeutils

    ahora = timeutils._utc_now_iso()
    with db._get_db_connection() as conexion:
        conexion.execute(
            "INSERT OR REPLACE INTO services (cliente_id, slug, name, category,"
            " duration_minutes, price_cents, description, is_active, sort_order,"
            " created_at, updated_at) VALUES ('demo', ?, 'Corte senora', 'Cortes',"
            " 30, 2500, '', 1, 0, ?, ?)",
            (agenda._normalize_service_id("Corte senora"), ahora, ahora))
        conexion.commit()
    config = clients._get_client_config("demo")
    previo = dict(config.get("booking") or {})
    contacto_previo = dict(config.get("contacto") or {})
    config["booking"] = dict(previo, mostrar_precios=False)
    config["contacto"] = dict(contacto_previo, telefono="625 120 100")
    yield
    config["booking"] = previo
    config["contacto"] = contacto_previo
    with db._get_db_connection() as conexion:
        conexion.execute("DELETE FROM services WHERE cliente_id='demo' AND name='Corte senora'")
        conexion.commit()


def test_el_modelo_no_ve_ni_un_precio(salon_sin_precios, api_module):  # noqa: F811
    """Lo que no tiene, no lo puede soltar."""
    from backend import booking

    lineas = " | ".join(booking._service_catalog_lines("demo"))
    assert "Corte senora" in lineas, "el catalogo tiene que seguir estando"
    assert "25" not in lineas and "EUR" not in lineas and "€" not in lineas
    assert "NO se da por mensaje" in lineas


def test_cualquier_cifra_esta_prohibida(salon_sin_precios, api_module):  # noqa: F811
    """No solo la de las familias con regla: NINGUNA."""
    from backend import agent

    assert agent._da_un_precio_prohibido("demo", "El corte son 25 EUR", "cuanto vale un corte")
    assert agent._da_un_precio_prohibido("demo", "esta entre 40 y 60 euros", "y las mechas?")
    assert not agent._da_un_precio_prohibido("demo", "Te espero el jueves a las 10:00", "")


def test_es_opt_in_quien_no_lo_toque_sigue_igual(api_module, client):  # noqa: F811
    from backend import booking, clients

    config = clients._get_client_config("demo")
    assert booking.precios_ocultos("demo") is False
    assert (config.get("booking") or {}).get("mostrar_precios") is None


def test_a_la_segunda_cierra_en_vez_de_repetirse(salon_sin_precios, api_module):  # noqa: F811
    """El fallo dominante medido: repetir la negativa hasta que se cansa."""
    from backend import agent, reserva

    estado = reserva.Estado()
    primera = agent._salida_para_quien_pregunta_el_precio("demo", estado, "cuanto cuesta un corte?")
    assert "valoracion" in primera.lower()
    assert "625 120 100" in primera, "sin telefono no hay salida humana"

    segunda = agent._salida_para_quien_pregunta_el_precio("demo", estado, "ya pero dime un aproximado")
    assert "CIERRA" in segunda and "dos o tres horas" in segunda
    assert segunda != primera, "le vuelve a decir lo mismo: ese es el fallo"


def test_a_quien_no_pregunta_el_precio_no_se_le_dice_nada(salon_sin_precios, api_module):  # noqa: F811
    from backend import agent, reserva

    estado = reserva.Estado()
    assert agent._salida_para_quien_pregunta_el_precio("demo", estado, "quiero cita el jueves") == ""
    assert estado.veces_sin_precio == 0


def test_el_freno_del_precio_tapa_tambien_el_camino_de_las_listas(api_module, client):  # noqa: F811
    """Preguntar el precio y luego elegir de la LISTA se colaba entero.

    El freno colgaba de `_wa_resumen_para_confirmar`, que es UNO de los cuatro
    caminos que llegan al resumen. Quien preguntaba el precio, recibia la respuesta
    del negocio y luego pulsaba el servicio en la lista, entraba por otro camino y
    acababa con el tratamiento de horas en la agenda.

    Aqui se llama al resumen DIRECTO, como hace el flujo de listas, y se exige que
    pare igual.
    """
    import asyncio

    from backend import appstate, db, messaging, rules, timeutils, whatsapp

    ahora = timeutils._utc_now().isoformat()
    telefono = "34600991234"
    with db._get_db_connection() as conexion:
        conexion.execute(
            "INSERT OR REPLACE INTO services (cliente_id, slug, name, category,"
            " duration_minutes, price_cents, description, is_active, sort_order,"
            " created_at, updated_at) VALUES ('demo', 'kera_listas', 'Keratina listas xl',"
            " 'keratina', 240, 0, '', 1, 0, ?, ?)", (ahora, ahora))
        conexion.commit()
    regla = rules.guardar("demo", nombre="Keratina: pedir foto", intenciones=["precio"],
                          familias=["keratina"], accion="pedir_foto",
                          texto="Mandanos una foto y te decimos el precio.")

    enviados = []

    async def _capturar(**kwargs):
        enviados.append(kwargs.get("text") or "")

    original = messaging._send_whatsapp_text
    messaging._send_whatsapp_text = _capturar
    try:
        from backend import reserva

        estado = reserva.cargar("demo", telefono)
        estado.veces_sin_precio = 1        # pregunto el precio antes
        reserva.guardar("demo", telefono, estado)

        flow = appstate.WAFlowState(cliente_id="demo", from_number=telefono)
        flow.flow = "booking_name"          # venia del camino de las listas
        flow.servicio = "Keratina listas xl"
        flow.fecha = "2026-09-10"
        flow.hora = "10:00"
        flow.nombre = "Ana"

        asyncio.run(whatsapp._wa_send_booking_summary(
            cliente_id="demo", phone_number_id="phone_test",
            to_number=telefono, flow=flow))

        junto = " ".join(enviados).lower()
        assert "resumen de tu cita" not in junto, (
            "le ha ensenyado el resumen del tratamiento a quien pregunto el precio"
        )
        assert "foto" in junto, "no le ha dicho lo que el negocio manda decir"
        assert flow.flow != "booking_confirm"
        assert not flow.flow, (
            "se queda dentro del paso de las listas: su 'si' se leera como su nombre"
        )
    finally:
        messaging._send_whatsapp_text = original
        rules.borrar("demo", regla["id"])
        whatsapp._wa_clear_flow("demo", telefono)
        with db._get_db_connection() as conexion:
            conexion.execute("DELETE FROM services WHERE cliente_id='demo' AND slug='kera_listas'")
            conexion.commit()
