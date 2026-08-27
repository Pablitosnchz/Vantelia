# -*- coding: utf-8 -*-
"""La fianza se dice ANTES de confirmar, aunque no haya pasarela de pago.

Incidente real (26-ago-2026, salon piloto). La clienta reservo un alisado que
lleva 50 EUR de fianza obligatoria, se le confirmo la cita tan tranquilo, y tuvo
que preguntar ella:

    ELLA: Tengo que dar alguna fianza?
      IA: 💫 Para confirmar y asegurar tu cita se abona una fianza de 50 € por
          servicio, que se descuenta del importe total el dia de tu tratamiento...

La respuesta era perfecta -el negocio la tiene escrita- y el dato tambien: 59 de
sus servicios estan marcados con `payment_type='deposit'` y 5.000 centimos. El
fallo era que nadie se lo ensenyaba antes. La duenya: *"por defecto para ciertos
trabajos, alisados, permanentes y tal, tiene que pedir la IA la fianza"*.

POR QUE PASABA: la unica pregunta que se hacia el codigo era "¿podemos COBRARLA?",
y esa necesita Stripe conectado (`_service_payment_policy` -> `available`). El
salon aun no lo tiene, asi que la fianza desaparecia entera: ni se cobraba NI SE
MENCIONABA. Son dos preguntas distintas, y la de "¿la EXIGE el negocio?" es
politica suya y no depende de ninguna pasarela.
"""
from __future__ import annotations

import asyncio

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401

CON_FIANZA = "Alisado con fianza"
SIN_FIANZA = "Corte normal"


@pytest.fixture()
def catalogo(api_module, client):  # noqa: F811
    """Dos servicios con la configuracion REAL del salon: uno con fianza y otro sin."""
    from backend import db, timeutils

    ahora = timeutils._utc_now().isoformat()
    filas = [
        ("fz_con", CON_FIANZA, "Alisados", 180, 26000, "deposit", "payment_required", 5000),
        ("fz_sin", SIN_FIANZA, "Cortes", 20, 2000, "full", "payment_disabled", 0),
    ]
    with db._get_db_connection() as conexion:
        for slug, nombre, cat, mins, precio, tipo, modo, fianza in filas:
            conexion.execute(
                "INSERT OR REPLACE INTO services (cliente_id, slug, name, category,"
                " duration_minutes, price_cents, description, is_active, sort_order,"
                " created_at, updated_at, payment_type, payment_mode,"
                " deposit_amount_cents) VALUES ('demo',?,?,?,?,?,'',1,0,?,?,?,?,?)",
                (slug, nombre, cat, mins, precio, ahora, ahora, tipo, modo, fianza))
        conexion.commit()
    try:
        yield "demo"
    finally:
        with db._get_db_connection() as conexion:
            conexion.execute("DELETE FROM services WHERE cliente_id='demo' AND slug LIKE 'fz_%'")
            conexion.commit()


def test_se_sabe_que_lleva_fianza_sin_stripe_conectado(catalogo):
    """La pregunta correcta es "¿la exige el negocio?", no "¿podemos cobrarla?"."""
    from backend import booking

    fianza = booking.fianza_del_servicio(catalogo, CON_FIANZA)
    assert fianza, "sin Stripe la fianza desaparecia entera"
    assert fianza["importe_cents"] == 5000
    assert fianza["obligatoria"] is True
    assert booking.fianza_del_servicio(catalogo, SIN_FIANZA) == {}


def test_el_aviso_dice_cuanto_y_que_se_descuenta(catalogo):
    from backend import booking

    aviso = booking.aviso_de_fianza(catalogo, CON_FIANZA)
    assert "50" in aviso and "fianza" in aviso.lower()
    assert booking.aviso_de_fianza(catalogo, SIN_FIANZA) == ""


def test_el_negocio_puede_poner_su_propio_texto(catalogo, monkeypatch):
    """Lo que escribe el negocio manda sobre lo nuestro."""
    from backend import booking, clients

    original = clients._get_client_config

    def _con_texto(cid, *a, **k):
        cfg = dict(original(cid, *a, **k))
        cfg["booking"] = dict(cfg.get("booking") or {})
        cfg["booking"]["fianza_aviso"] = "Se abona {importe} de senyal para reservar."
        return cfg

    monkeypatch.setattr(clients, "_get_client_config", _con_texto)
    assert booking.aviso_de_fianza(catalogo, CON_FIANZA) == (
        "Se abona 50 € de senyal para reservar.")


def test_sale_en_el_resumen_encima_del_boton(catalogo, monkeypatch):
    """Es una condicion para reservar, no una curiosidad: va antes de confirmar."""
    from backend import appstate, messaging, whatsapp

    enviados = []

    async def _capturar(**kwargs):
        enviados.append(kwargs.get("body") or kwargs.get("text") or "")

    monkeypatch.setattr(messaging, "_send_whatsapp_buttons", _capturar)
    monkeypatch.setattr(messaging, "_send_whatsapp_text", _capturar)

    flow = appstate.WAFlowState(cliente_id=catalogo, from_number="34600993333")
    flow.servicio = CON_FIANZA
    flow.fecha = "2026-09-10"
    flow.hora = "10:00"
    flow.nombre = "Ana"
    asyncio.run(whatsapp._wa_send_booking_summary(
        cliente_id=catalogo, phone_number_id="phone_test",
        to_number="34600993333", flow=flow))

    junto = " ".join(enviados)
    assert "Resumen de tu cita" in junto
    assert "fianza" in junto.lower() and "50" in junto, (
        "confirma sin saber que debe una senyal: es justo lo que paso"
    )


def test_sin_fianza_el_resumen_no_inventa_ninguna(catalogo, monkeypatch):
    """Meter una fianza donde no la hay espantaria clientas de un corte de 20 €."""
    from backend import appstate, messaging, whatsapp

    enviados = []

    async def _capturar(**kwargs):
        enviados.append(kwargs.get("body") or kwargs.get("text") or "")

    monkeypatch.setattr(messaging, "_send_whatsapp_buttons", _capturar)
    monkeypatch.setattr(messaging, "_send_whatsapp_text", _capturar)

    flow = appstate.WAFlowState(cliente_id=catalogo, from_number="34600993334")
    flow.servicio = SIN_FIANZA
    flow.fecha = "2026-09-10"
    flow.hora = "10:00"
    flow.nombre = "Ana"
    asyncio.run(whatsapp._wa_send_booking_summary(
        cliente_id=catalogo, phone_number_id="phone_test",
        to_number="34600993334", flow=flow))
    assert "fianza" not in " ".join(enviados).lower()


def test_el_asistente_lo_sabe_mientras_habla(catalogo):
    """Si solo lo supiera el resumen, el asistente diria lo contrario antes."""
    from backend import agent

    detalle = agent._detalle_servicio(catalogo, CON_FIANZA)
    assert detalle.get("fianza") == "50 €"
    assert "antes de cerrar la cita" in detalle.get("avisale_de_la_fianza", "").lower()
    assert "fianza" not in agent._detalle_servicio(catalogo, SIN_FIANZA)


def test_la_confirmacion_tambien_la_recuerda(catalogo):
    """Sin Stripe la cita nunca nace 'pendiente de pago': si no se dice aqui, no se dice."""
    import inspect

    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._wa_create_booking)
    assert "aviso_de_fianza" in fuente
    assert "como_se_paga_la_fianza" in fuente


def test_la_fianza_nunca_pasa_del_precio_del_servicio(api_module, client):  # noqa: F811
    """Cobrarle 50 € de senyal por unas mechas de 18 € es devolverle 32.

    No es teorico: la duenya pidio poner su fianza plana de 50 € a los alisados,
    permanentes y mechas, y de esos servicios QUINCE cuestan menos de 50. El
    catalogo es de quien lo configura, pero el codigo no puede anunciar un cobro
    imposible.
    """
    from backend import booking, db, timeutils

    ahora = timeutils._utc_now().isoformat()
    with db._get_db_connection() as conexion:
        conexion.execute(
            "INSERT OR REPLACE INTO services (cliente_id, slug, name, category,"
            " duration_minutes, price_cents, description, is_active, sort_order,"
            " created_at, updated_at, payment_type, payment_mode,"
            " deposit_amount_cents) VALUES ('demo','fz_barato','Mechas gorro corto',"
            " 'Mechas',45,1800,'',1,0,?,?,'deposit','payment_required',5000)",
            (ahora, ahora))
        conexion.commit()
    try:
        fianza = booking.fianza_del_servicio("demo", "Mechas gorro corto")
        assert fianza["importe_cents"] == 1800, (
            "anuncia una fianza mayor que el propio servicio"
        )
    finally:
        with db._get_db_connection() as conexion:
            conexion.execute("DELETE FROM services WHERE cliente_id='demo' AND slug='fz_barato'")
            conexion.commit()


def test_un_servicio_a_consultar_conserva_su_fianza(api_module, client):  # noqa: F811
    """Precio 0 es "a consultar", no "gratis": ahi la fianza es el unico dato firme.

    Ocho de sus servicios con fianza estan asi.
    """
    from backend import booking, db, timeutils

    ahora = timeutils._utc_now().isoformat()
    with db._get_db_connection() as conexion:
        conexion.execute(
            "INSERT OR REPLACE INTO services (cliente_id, slug, name, category,"
            " duration_minutes, price_cents, description, is_active, sort_order,"
            " created_at, updated_at, payment_type, payment_mode,"
            " deposit_amount_cents) VALUES ('demo','fz_consultar','Extensiones a medida',"
            " 'Extensiones',180,0,'',1,0,?,?,'deposit','payment_required',10000)",
            (ahora, ahora))
        conexion.commit()
    try:
        assert booking.fianza_del_servicio("demo", "Extensiones a medida")["importe_cents"] == 10000
    finally:
        with db._get_db_connection() as conexion:
            conexion.execute("DELETE FROM services WHERE cliente_id='demo' AND slug='fz_consultar'")
            conexion.commit()
