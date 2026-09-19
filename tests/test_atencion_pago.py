"""El ganador de un enlace conserva su pago; un turno detenido no inicia efectos."""
import asyncio
import concurrent.futures
from contextlib import closing
from datetime import timedelta
import threading
from types import SimpleNamespace

import pytest

from test_ai_payment_link import _seed_booking, _seed_full_policy
from test_atencion_operaciones import operaciones_atencion, _crear_ticket_prueba  # noqa: F401
from test_atencion_persistida import autoridad_atencion  # noqa: F401
from atencion_proceso_aislado import comprobar_intento_en_interprete_nuevo


@pytest.fixture
def pago_atencion(operaciones_atencion, monkeypatch):
    from backend import atencion_contexto, booking, db, emailing, messaging, stripe_gateway, timeutils

    a = operaciones_atencion
    # Los helpers históricos solo necesitan estas tres funciones. El api_module
    # de sesión puede pertenecer a un runtime anterior al backend de esta DB.
    datos_actuales = SimpleNamespace(_utc_now_iso=timeutils._utc_now_iso,
        _store_booking=booking._store_booking, _get_db_connection=db._get_db_connection)
    booking_id = _seed_booking(datos_actuales, "atencion", source="vantelia_widget",
                               email="pago@example.test", telefono="+34600123456")
    _seed_full_policy(datos_actuales)
    a.booking = booking._get_booking_row_by_id(booking_id)
    a.efectos, a.entregas, a.hooks = [], [], {}
    a.contexto, a.nucleo = atencion_contexto, booking

    def cuenta(cliente_id, refresh=False):
        a.efectos.append("connect")
        if a.hooks.get("connect"):
            a.hooks["connect"]()
        return SimpleNamespace(connected=True, charges_enabled=True, stripe_account_id="acct_sintetica")

    contacto_real = booking._payment_contact_for_booking

    def contacto(fila):
        a.efectos.append("crm")
        return contacto_real(fila)

    def checkout(**kwargs):
        a.efectos.append("checkout")
        if a.hooks.get("checkout"):
            a.hooks["checkout"]()
        return SimpleNamespace(id="cs_" + kwargs["metadata"]["payment_id"], url="https://checkout.test/pago")

    def email(*args, **kwargs):
        if a.hooks.get("aviso"):
            a.hooks["aviso"]()
        a.entregas.append("email")

    async def sms(*args, **kwargs):
        if a.hooks.get("aviso"):
            a.hooks["aviso"]()
        a.entregas.append("sms")
        return True

    monkeypatch.setattr(booking, "_connect_account_status", cuenta)
    monkeypatch.setattr(booking, "_payment_contact_for_booking", contacto)
    monkeypatch.setattr(booking, "_ai_payment_delivery_available", lambda *args: True)
    monkeypatch.setattr(stripe_gateway, "_stripe_init", lambda: None)
    monkeypatch.setattr(stripe_gateway.stripe.checkout.Session, "create", checkout)
    monkeypatch.setattr(emailing, "_send_client_email", email)
    monkeypatch.setattr(messaging, "_send_client_sms", sms)
    return a


def _pausar_pago(a, tenant="demo"):
    return a.autoridad.cambiar_atencion(tenant, "pausada", version_esperada=0,
                                      motivo="temporada", actor="sistema")


def _crear_pago(a, fila=None, tenant="demo"):
    return a.nucleo._create_customer_payment_link(
        tenant, a.booking if fila is None else fila, base_url="https://widget.test")


def _enviar_pago(a):
    return asyncio.run(a.nucleo._ai_send_payment_link("demo", a.booking, base_url="https://widget.test"))


def _pagos_guardados(a):
    with closing(a.db._get_db_connection()) as connection:
        return [dict(f) for f in connection.execute("SELECT * FROM customer_payments ORDER BY id")]


def test_fixture_pago_siembra_solo_en_la_db_actual_tras_otro_runtime(
        api_module, vantelia_env_factory, request):
    # El hub histórico abre otro runtime y el shim renueva backend.*. La fixture
    # de sesión sigue siendo la primera API: sembrar por ella toca otra DB.
    with closing(api_module._get_db_connection()) as connection:
        anteriores = connection.execute("SELECT count(*) FROM bookings").fetchone()[0]
    vantelia_env_factory()
    a = request.getfixturevalue("pago_atencion")
    with closing(a.db._get_db_connection()) as connection:
        cita = connection.execute("SELECT id FROM bookings WHERE id='bk_aipay_atencion'").fetchone()
        politica = connection.execute(
            "SELECT mode FROM service_payment_policies WHERE cliente_id='demo' AND service_id='consulta'").fetchone()
    assert cita is not None and a.booking is not None
    assert cita["id"] == a.booking["id"] and politica["mode"] == "full"
    with closing(api_module._get_db_connection()) as connection:
        assert connection.execute("SELECT count(*) FROM bookings").fetchone()[0] == anteriores


@pytest.mark.parametrize("entrada", ["core", "ai"])
def test_pausa_antes_del_primer_efecto_no_toca_connect_crm_checkout_ni_avisos(pago_atencion, entrada):
    a = pago_atencion
    ticket = _crear_ticket_prueba(a, tenant="demo")
    _pausar_pago(a)
    with a.contexto.turno_atencion("demo", ticket["ticket_id"], "pago_1"):
        with pytest.raises(a.contexto.AtencionDetenida):
            _crear_pago(a) if entrada == "core" else _enviar_pago(a)
    assert a.efectos == [] and a.entregas == [] and _pagos_guardados(a) == []


def test_pausa_despues_de_checkout_conserva_pago_conocido_antes_del_aviso(pago_atencion):
    a = pago_atencion
    ticket = _crear_ticket_prueba(a, tenant="demo")
    a.hooks["checkout"] = lambda: _pausar_pago(a)

    def aviso_suprimido():
        operacion = a.op.consultar_operaciones_atencion("demo", tipo="pago")[0]
        assert operacion["estado"] == "aceptado"
        assert operacion["result_ref"] == _pagos_guardados(a)[0]["id"]
        raise a.contexto.AtencionDetenida("pausada")

    a.hooks["aviso"] = aviso_suprimido
    with a.contexto.turno_atencion("demo", ticket["ticket_id"], "pago_1"):
        with pytest.raises(a.contexto.AtencionDetenida):
            _enviar_pago(a)
    assert a.efectos.count("checkout") == 1 and a.entregas == []
    assert len(_pagos_guardados(a)) == 1


def test_dos_ejecutores_mismo_intento_solo_crean_un_checkout(pago_atencion):
    a = pago_atencion
    tickets = [_crear_ticket_prueba(a, evento="evento_%s" % i, tenant="demo") for i in range(2)]
    barrera = threading.Barrier(2)

    def ejecutar(ticket):
        with a.contexto.turno_atencion("demo", ticket["ticket_id"], "pago_1"):
            barrera.wait(timeout=10)
            try:
                return _crear_pago(a)["id"]
            except a.contexto.AtencionDetenida as error:
                return error

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as workers:
        resultados = list(workers.map(ejecutar, tickets))
    assert sum(isinstance(r, str) and r.startswith("pay_") for r in resultados) == 1
    assert sum(isinstance(r, a.contexto.AtencionDetenida) for r in resultados) == 1
    assert a.efectos.count("checkout") == 1 and len(_pagos_guardados(a)) == 1


def test_reinicio_consulta_pago_conocido_antes_de_vigencia_y_rate_limit(pago_atencion, monkeypatch):
    a = pago_atencion
    original = _crear_ticket_prueba(a, tenant="demo")
    with a.contexto.turno_atencion("demo", original["ticket_id"], "pago_1"):
        pago = _crear_pago(a)
    a.reloj["ahora"] += timedelta(minutes=11)
    _pausar_pago(a)
    otro = _crear_ticket_prueba(a, evento="otro_evento", tenant="demo")
    recuperada = comprobar_intento_en_interprete_nuevo(a.settings.DB_PATH, otro["ticket_id"],
        tipo="pago", accion="crear_enlace", clave="pago_1",
        solicitud={"booking_id": a.booking["id"], "base_url": "https://widget.test", "override_cents": None})
    assert recuperada == {"estado": "aceptado", "result_ref": pago["id"]}

    def no_avanzar(*args):
        raise AssertionError("Un intento conocido no llega a preparar canal ni rate limit")

    monkeypatch.setattr(a.nucleo, "_ai_payment_delivery_available", no_avanzar)
    with a.contexto.turno_atencion("demo", otro["ticket_id"], "pago_1"):
        with pytest.raises(a.contexto.AtencionDetenida) as exc:
            _enviar_pago(a)
    assert exc.value.estado == "aceptado" and exc.value.result_ref == pago["id"]
    assert a.efectos.count("checkout") == 1


def test_respuesta_checkout_perdida_no_autoriza_otro_checkout(pago_atencion):
    a = pago_atencion
    original = _crear_ticket_prueba(a, tenant="demo")

    def respuesta_perdida():
        raise TimeoutError("Stripe aceptó; la respuesta se perdió")

    a.hooks["checkout"] = respuesta_perdida
    with a.contexto.turno_atencion("demo", original["ticket_id"], "pago_1"):
        assert _enviar_pago(a)["ok"] is False
    otro = _crear_ticket_prueba(a, evento="otro_evento", tenant="demo")
    with a.contexto.turno_atencion("demo", otro["ticket_id"], "pago_1"):
        with pytest.raises(a.contexto.AtencionDetenida) as exc:
            _enviar_pago(a)
    assert exc.value.estado == "desconocido" and exc.value.result_ref == ""
    assert a.efectos.count("checkout") == 1 and _pagos_guardados(a) == [] and a.entregas == []


def test_ticket_de_otro_tenant_no_inicia_un_pago(pago_atencion):
    a = pago_atencion
    ticket = _crear_ticket_prueba(a, tenant="negocio_en")
    with a.contexto.turno_atencion("negocio_en", ticket["ticket_id"], "pago_1"):
        with pytest.raises(a.contexto.AtencionDetenida):
            _crear_pago(a)
    assert a.efectos == [] and _pagos_guardados(a) == []


def test_manual_sin_contexto_sigue_creando_pago_aunque_este_pausada(pago_atencion):
    a = pago_atencion
    _pausar_pago(a)
    pago = _crear_pago(a)
    assert pago["id"].startswith("pay_") and len(_pagos_guardados(a)) == 1
    assert a.op.consultar_operaciones_atencion("demo") == []


def test_error_del_diario_no_rompe_el_ganador_ni_autoriza_repetir(pago_atencion):
    a = pago_atencion
    ticket = _crear_ticket_prueba(a, tenant="demo")
    with closing(a.db._get_db_connection()) as conn, conn:
        conn.execute("CREATE TRIGGER romper_resultado_pago BEFORE UPDATE ON client_attention_operations "
                     "BEGIN SELECT RAISE(ABORT, 'fallo de diario'); END")
    with a.contexto.turno_atencion("demo", ticket["ticket_id"], "pago_1"):
        assert _enviar_pago(a)["ok"] is True
    assert len(_pagos_guardados(a)) == 1 and a.entregas == ["email"]
    assert a.op.consultar_operaciones_atencion("demo", tipo="pago")[0]["estado"] == "en_transito"
    with a.contexto.turno_atencion("demo", ticket["ticket_id"], "pago_1"):
        with pytest.raises(a.contexto.AtencionDetenida):
            _enviar_pago(a)
    assert a.efectos.count("checkout") == 1


def test_pago_valida_accion_datos_y_referencia_sin_confundir_tenants(operaciones_atencion):
    a = operaciones_atencion
    tickets = {tenant: _crear_ticket_prueba(a, tenant=tenant) for tenant in ("demo", "negocio_en")}
    identidad = dict(tipo="pago", canal="crear_enlace", clave_intento="pago_1")
    ganadoras = {}
    for tenant, ticket in tickets.items():
        ganadoras[tenant] = a.op.admitir_operacion_atencion(tenant, ticket["ticket_id"], **identidad, payload=b"importe:100")
        assert ganadoras[tenant]["ejecutar_operacion"]
        for referencia in ("", "bk_ajena", None):
            with pytest.raises(ValueError):
                a.op.registrar_resultado_operacion_atencion(tenant, ticket["ticket_id"], **identidad,
                    owner_token=ganadoras[tenant]["owner_token"], resultado="aceptado", result_ref=referencia)
        aceptada = a.op.registrar_resultado_operacion_atencion(tenant, ticket["ticket_id"], **identidad,
            owner_token=ganadoras[tenant]["owner_token"], resultado="aceptado", result_ref="pay_" + tenant)
        assert aceptada["result_ref"] == "pay_" + tenant
    with pytest.raises(a.op.AtencionOperacionNoEncontrada):
        a.op.consultar_operaciones_atencion("demo", ticket_id=tickets["negocio_en"]["ticket_id"])
    with pytest.raises(a.op.AtencionIdentidadEnConflicto):
        a.op.admitir_operacion_atencion("demo", tickets["demo"]["ticket_id"], **identidad, payload=b"importe:200")
    with pytest.raises(ValueError):
        a.op.admitir_operacion_atencion("demo", tickets["demo"]["ticket_id"],
            tipo="pago", canal="crear", clave_intento="otra", payload=b"{}")


def test_migracion_del_diario_conserva_envios_reservas_y_admite_pago(operaciones_atencion):
    a = operaciones_atencion
    ticket = _crear_ticket_prueba(a)
    envio = a.op.admitir_envio_atencion("negocio_es", ticket["ticket_id"], "email", 0, payload=b"aviso")
    a.op.registrar_resultado_atencion("negocio_es", ticket["ticket_id"], "email", 0,
                                    owner_token=envio["owner_token"], resultado="aceptado")
    reserva = a.op.admitir_operacion_atencion("negocio_es", ticket["ticket_id"],
        tipo="reserva", canal="crear", clave_intento="reserva_1", payload=b"cita")
    a.op.registrar_resultado_operacion_atencion("negocio_es", ticket["ticket_id"],
        tipo="reserva", canal="crear", clave_intento="reserva_1", owner_token=reserva["owner_token"],
        resultado="aceptado", result_ref="bk_original")
    with closing(a.db._get_db_connection()) as conn, conn:
        originales = [tuple(row) for row in conn.execute("SELECT * FROM client_attention_operations ORDER BY tipo")]
        conn.execute("DROP TABLE client_attention_operations")
        # Versión anterior del diario: solo dos tipos, los mismos campos duraderos.
        conn.execute("""CREATE TABLE client_attention_operations (
            cliente_id TEXT NOT NULL, ticket_id TEXT NOT NULL,
            tipo TEXT NOT NULL CHECK (tipo IN ('envio', 'reserva')), canal TEXT NOT NULL,
            fragmento INTEGER NOT NULL, clave_intento TEXT NOT NULL DEFAULT '',
            payload_hash TEXT NOT NULL, request_hash TEXT NOT NULL, estado TEXT NOT NULL,
            owner_token TEXT NOT NULL DEFAULT '', motivo TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, resultado_at TEXT NOT NULL DEFAULT '', result_ref TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (cliente_id,ticket_id,tipo,canal,fragmento,clave_intento),
            FOREIGN KEY (cliente_id,ticket_id) REFERENCES client_attention_tickets(cliente_id,ticket_id))""")
        conn.executemany("INSERT INTO client_attention_operations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", originales)
    a.db._init_database()
    a.db._init_database()  # Reabrir no rejuvenece los propietarios ni duplica registros.
    with closing(a.db._get_db_connection()) as conn:
        assert [tuple(row) for row in conn.execute("SELECT * FROM client_attention_operations ORDER BY tipo")] == originales
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='client_attention_operations_sin_pago'").fetchone()
    pago = a.op.admitir_operacion_atencion("negocio_es", ticket["ticket_id"],
        tipo="pago", canal="crear_enlace", clave_intento="pago_1", payload=b"importe:100")
    assert pago["ejecutar_operacion"]
    repetido = a.op.admitir_operacion_atencion("negocio_es", ticket["ticket_id"],
        tipo="pago", canal="crear_enlace", clave_intento="pago_1", payload=b"importe:100")
    assert not repetido["ejecutar_operacion"]


def test_mismo_intento_no_admite_cambiar_la_solicitud_de_pago(pago_atencion):
    a = pago_atencion
    ticket = _crear_ticket_prueba(a, tenant="demo")
    with a.contexto.turno_atencion("demo", ticket["ticket_id"], "pago_1"):
        _crear_pago(a)
        with pytest.raises(a.contexto.AtencionDetenida) as exc:
            a.nucleo._create_customer_payment_link("demo", a.booking, base_url="https://widget.test", override_cents=200)
    assert exc.value.motivo == "identidad_en_conflicto" and a.efectos.count("checkout") == 1


@pytest.mark.parametrize("connected, charges_enabled", [(False, True), (True, False)])
def test_connect_no_operativo_es_rechazo_conocido_sin_checkout(pago_atencion, monkeypatch, connected, charges_enabled):
    a = pago_atencion
    ticket = _crear_ticket_prueba(a, tenant="demo")

    def connect_no_operativo(*args, **kwargs):
        a.efectos.append("connect")
        return SimpleNamespace(connected=connected, charges_enabled=charges_enabled)

    monkeypatch.setattr(a.nucleo, "_connect_account_status", connect_no_operativo)
    with a.contexto.turno_atencion("demo", ticket["ticket_id"], "pago_1"):
        respuesta = _enviar_pago(a)
    assert not respuesta["ok"] and respuesta["reason"] == "stripe_unavailable"
    operacion = a.op.consultar_operaciones_atencion("demo", tipo="pago")[0]
    assert operacion["estado"] == "rechazado" and operacion["result_ref"] == ""
    otro = _crear_ticket_prueba(a, evento="otro_evento", tenant="demo")
    recuperada = comprobar_intento_en_interprete_nuevo(a.settings.DB_PATH, otro["ticket_id"],
        tipo="pago", accion="crear_enlace", clave="pago_1",
        solicitud={"booking_id": a.booking["id"], "base_url": "https://widget.test", "override_cents": None})
    assert recuperada == {"estado": "rechazado", "result_ref": ""}
    with a.contexto.turno_atencion("demo", otro["ticket_id"], "pago_1"):
        with pytest.raises(a.contexto.AtencionDetenida) as exc:
            _enviar_pago(a)
    assert exc.value.estado == "rechazado"
    assert a.efectos == ["connect"] and _pagos_guardados(a) == [] and a.entregas == []
