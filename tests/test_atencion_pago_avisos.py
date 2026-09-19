"""El corte del aviso conserva el pago ya creado, sin llamarlo entrega."""
from contextlib import closing
from datetime import timedelta

import pytest

from test_atencion_persistida import autoridad_atencion  # noqa: F401
from test_atencion_operaciones import operaciones_atencion, _crear_ticket_prueba  # noqa: F401
from test_atencion_pago import pago_atencion, _enviar_pago, _pagos_guardados, _pausar_pago  # noqa: F401
from test_atencion_salidas import transporte_atencion, _cliente_http_simulado_salida  # noqa: F401


@pytest.fixture
def frontera_pago_avisos(operaciones_atencion, request, monkeypatch):
    from backend import emailing, messaging

    # PAGO conserva núcleo/SQLite/Checkout simulado. Restaurar sus fachadas de
    # avisos para atravesar también la admisión real de transporte de fase 2c.
    email_real, sms_real = emailing._send_client_email, messaging._send_client_sms
    a = request.getfixturevalue("pago_atencion")
    request.getfixturevalue("transporte_atencion")
    monkeypatch.setattr(emailing, "_send_client_email", email_real)
    monkeypatch.setattr(messaging, "_send_client_sms", sms_real)
    _cliente_http_simulado_salida(monkeypatch, lambda *args: pytest.fail("Un aviso pausado no inicia POST"))
    return a


@pytest.mark.parametrize("canal,source,canal_diario", [
    ("email", "vantelia_widget", "smtp_cliente"), ("sms", "voice", "twilio_sms")])
def test_pago_persistido_conserva_referencia_al_suprimir_aviso_y_no_recrea_checkout(
        frontera_pago_avisos, canal, source, canal_diario):
    a = frontera_pago_avisos
    with closing(a.db._get_db_connection()) as conn, conn:
        conn.execute("UPDATE bookings SET source=? WHERE id=?", (source, a.booking["id"]))
    a.booking = a.nucleo._get_booking_row_by_id(a.booking["id"])
    a.hooks["checkout"] = lambda: _pausar_pago(a)
    with a.turno(), pytest.raises(a.contexto.AtencionDetenida) as corte:
        _enviar_pago(a)

    pagos = _pagos_guardados(a)
    assert len(pagos) == 1 and pagos[0]["id"].startswith("pay_")
    assert a.efectos == ["connect", "crm", "checkout"]
    assert a.llamadas == [] and a.entregas == [] and a.fallback == []
    operacion = a.op.consultar_operaciones_atencion("demo", tipo="pago")[0]
    assert (operacion["estado"], operacion["result_ref"]) == ("aceptado", pagos[0]["id"])
    assert [(r["canal"], r["estado"]) for r in a.op.consultar_envios_atencion("demo")] == [
        (canal_diario, "suprimido")]
    with closing(a.db._get_db_connection()) as conn:
        assert conn.execute("SELECT count(*) FROM booking_audit WHERE event_type='ai_payment_link_sent'").fetchone()[0] == 0

    # Otro ticket tras reactivar, misma identidad del intento: consulta el pay_
    # conocido antes de vigencia/rate-limit y no repite Checkout ni el aviso.
    a.autoridad.cambiar_atencion("demo", "activa", version_esperada=1, motivo="temporada", actor="sistema")
    a.reloj["ahora"] += timedelta(microseconds=1)
    nuevo = _crear_ticket_prueba(a, evento="pago_otra_captura", tenant="demo")
    with a.contexto.turno_atencion("demo", nuevo["ticket_id"], "intento_salida"), pytest.raises(a.contexto.AtencionDetenida) as repetida:
        _enviar_pago(a)
    assert (repetida.value.estado, repetida.value.result_ref) == ("aceptado", pagos[0]["id"])
    assert a.efectos.count("checkout") == 1 and len(_pagos_guardados(a)) == 1
    assert a.llamadas == [] and a.entregas == [] and a.fallback == []

    # El primer corte identifica el envío suprimido, con el pago como dato aparte.
    assert (corte.value.estado, corte.value.motivo, corte.value.result_ref) == ("suprimido", "pausada", "")
    assert getattr(corte.value, "operacion_conocida", None) == {
        "tipo": "pago", "estado": "aceptado", "result_ref": pagos[0]["id"]}
