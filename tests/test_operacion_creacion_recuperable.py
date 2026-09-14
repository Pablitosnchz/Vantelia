"""La reserva persistida sigue siendo el resultado aunque falle la respuesta."""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import HTTPException

from test_huecos_para_mover_la_cita import api_module, agenda_de_dos  # noqa: F401


@pytest.fixture
def solicitud(agenda_de_dos):
    from backend import booking, db
    _, dia, profesionales, _ = agenda_de_dos
    key = uuid.uuid4().hex
    datos = dict(employee_row=profesionales[0], nombre="Prueba operación", telefono=key,
                 email="", servicio="", booking_date=dia, booking_time="10:00",
                 source="test", send_confirmation=False, operation_key=key)
    async def crear(**cambios):
        return await booking._create_booking_core("demo", **dict(datos, **cambios))
    yield crear, key
    with db._get_db_connection() as conn:
        conn.execute("DELETE FROM bookings WHERE cliente_id=? AND telefono=?", ("demo", key))
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='booking_operations'").fetchone():
            conn.execute("DELETE FROM booking_operations WHERE cliente_id=? AND operation_key=?", ("demo", key))
        conn.commit()


def test_caida_despues_de_guardar_recupera_la_misma_cita(solicitud, monkeypatch):
    from backend import booking, db
    crear, key = solicitud
    llamadas = []
    original = booking._create_provider_booking
    async def proveedor(*args, **kw):
        llamadas.append(1)
        return await original(*args, **kw)
    monkeypatch.setattr(booking, "_create_provider_booking", proveedor)
    def caer(*args, **kw):
        raise RuntimeError("caída después del commit")
    monkeypatch.setattr(booking, "_record_booking_audit", caer)
    with pytest.raises(RuntimeError, match="después del commit"):
        asyncio.run(crear())
    with db._get_db_connection() as conn:
        guardadas = conn.execute("SELECT id,booking_code FROM bookings WHERE telefono=?", (key,)).fetchall()
    assert len(guardadas) == 1
    recuperada = asyncio.run(crear())
    assert recuperada["id"] == guardadas[0]["id"]
    assert recuperada["booking_code"] == guardadas[0]["booking_code"]
    assert len(llamadas) == 1


def test_misma_identidad_no_admite_otra_solicitud(solicitud):
    crear, _ = solicitud
    asyncio.run(crear())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(crear(booking_time="10:30"))
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "OPERATION_KEY_REUSED"


def test_proveedor_con_resultado_desconocido_no_se_repite(solicitud, monkeypatch):
    from backend import booking
    crear, _ = solicitud
    llamadas = []
    async def proveedor(*a, **k):
        llamadas.append(1)
        raise httpx.ReadTimeout("sin resultado verificable")
    monkeypatch.setattr(booking, "_create_provider_booking", proveedor)
    with pytest.raises(HTTPException) as primera:
        asyncio.run(crear())
    assert primera.value.status_code == 502
    with pytest.raises(HTTPException) as segunda:
        asyncio.run(crear())
    assert segunda.value.detail["code"] == "OPERATION_PENDING"
    assert len(llamadas) == 1


def test_dos_mensajes_simultaneos_solo_llaman_una_vez(solicitud, monkeypatch):
    from backend import booking
    crear, _ = solicitud
    original = booking._create_provider_booking
    llamadas = []

    async def carrera():
        dentro = asyncio.Event()
        continuar = asyncio.Event()

        async def proveedor(*args, **kwargs):
            llamadas.append(1)
            dentro.set()
            await continuar.wait()
            return await original(*args, **kwargs)

        monkeypatch.setattr(booking, "_create_provider_booking", proveedor)
        primera = asyncio.create_task(crear())
        try:
            await asyncio.wait_for(dentro.wait(), timeout=5)
            with pytest.raises(HTTPException) as repetida:
                await crear()
            assert repetida.value.detail["code"] == "OPERATION_PENDING"
        finally:
            continuar.set()
            resultado = await primera
        assert (await crear())["id"] == resultado["id"]

    asyncio.run(carrera())
    assert len(llamadas) == 1


def test_otro_negocio_no_recupera_la_operacion(solicitud):
    from backend import booking_operations
    crear, key = solicitud
    asyncio.run(crear())
    # La misma clave ajena no revela ni el resultado ni si cambia la petición.
    assert booking_operations.recover_creation_operation("otro", key, "otra-peticion") is None


def test_recuperar_no_resucita_una_cita_cancelada(solicitud):
    from backend import db
    crear, _ = solicitud
    guardada = asyncio.run(crear())
    with db._get_db_connection() as conn:
        conn.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (guardada["id"],))
        conn.commit()
    recuperada = asyncio.run(crear())
    assert recuperada["id"] == guardada["id"]
    assert recuperada["status"] == "cancelled"


def _pendiente_sin_cita(cliente_id, clave, huella, creada):
    from backend import db
    with db._get_db_connection() as conn:
        conn.execute(
            "INSERT INTO booking_operations (cliente_id,operation_key,request_hash,booking_id,created_at) "
            "VALUES (?,?,?,?,?)",
            (cliente_id, clave, huella, "bk_perdida_" + clave, creada),
        )
        conn.commit()


def test_pendiente_antigua_sin_webhook_se_libera_y_audita(agenda_de_dos, monkeypatch):
    from backend import booking_operations, clients, db, timeutils
    ahora = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)
    clave, huella = "perdida_antigua", "h" * 64
    monkeypatch.setattr(timeutils, "_utc_now", lambda: ahora)
    monkeypatch.setattr(clients, "_get_client_config", lambda _: {"booking": {}})
    _pendiente_sin_cita("demo", clave, huella,
                         (ahora - timedelta(minutes=15)).replace(tzinfo=None).isoformat() + "Z")
    try:
        with pytest.raises(HTTPException) as exc:
            booking_operations.recover_creation_operation("demo", clave, huella)
        assert exc.value.detail["code"] == "OPERATION_RELEASED"
        with db._get_db_connection() as conn:
            assert conn.execute("SELECT 1 FROM booking_operations WHERE cliente_id=? AND operation_key=?",
                                ("demo", clave)).fetchone() is None
            audit = conn.execute(
                "SELECT event_type FROM booking_operation_audit WHERE cliente_id=? AND operation_key=?",
                ("demo", clave),
            ).fetchone()
        assert audit["event_type"] == "creation_pending_released"
    finally:
        with db._get_db_connection() as conn:
            conn.execute("DELETE FROM booking_operations WHERE cliente_id=? AND operation_key=?", ("demo", clave))
            conn.execute("DELETE FROM booking_operation_audit WHERE cliente_id=? AND operation_key=?", ("demo", clave))
            conn.commit()


@pytest.mark.parametrize("booking_config", [
    {"webhook_url": "https://ejemplo.test"},
    {"webhook_env": "RECOVERY_TEST_WEBHOOK"},
])
def test_pendiente_antigua_con_webhook_no_se_libera(monkeypatch, booking_config):
    from backend import booking_operations, clients, db, timeutils
    ahora = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)
    clave, huella = "perdida_webhook", "i" * 64
    monkeypatch.setattr(timeutils, "_utc_now", lambda: ahora)
    monkeypatch.setenv("RECOVERY_TEST_WEBHOOK", "https://ejemplo.test")
    monkeypatch.setattr(clients, "_get_client_config", lambda _: {"booking": booking_config})
    _pendiente_sin_cita("demo", clave, huella,
                         (ahora - timedelta(minutes=16)).replace(tzinfo=None).isoformat() + "Z")
    try:
        with pytest.raises(HTTPException) as exc:
            booking_operations.recover_creation_operation("demo", clave, huella)
        assert exc.value.detail["code"] == "OPERATION_PENDING"
        with db._get_db_connection() as conn:
            assert conn.execute("SELECT 1 FROM booking_operations WHERE cliente_id=? AND operation_key=?",
                                ("demo", clave)).fetchone()
    finally:
        with db._get_db_connection() as conn:
            conn.execute("DELETE FROM booking_operations WHERE cliente_id=? AND operation_key=?", ("demo", clave))
            conn.commit()


def test_pendiente_reciente_no_se_libera(monkeypatch):
    from backend import booking_operations, clients, db, timeutils
    ahora = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)
    clave, huella = "perdida_reciente", "j" * 64
    monkeypatch.setattr(timeutils, "_utc_now", lambda: ahora)
    monkeypatch.setattr(clients, "_get_client_config", lambda _: {"booking": {}})
    _pendiente_sin_cita("demo", clave, huella,
                         (ahora - timedelta(minutes=14, seconds=59)).replace(tzinfo=None).isoformat() + "Z")
    try:
        with pytest.raises(HTTPException) as exc:
            booking_operations.recover_creation_operation("demo", clave, huella)
        assert exc.value.detail["code"] == "OPERATION_PENDING"
        with db._get_db_connection() as conn:
            assert conn.execute("SELECT 1 FROM booking_operations WHERE cliente_id=? AND operation_key=?",
                                ("demo", clave)).fetchone()
    finally:
        with db._get_db_connection() as conn:
            conn.execute("DELETE FROM booking_operations WHERE cliente_id=? AND operation_key=?", ("demo", clave))
            conn.commit()


def test_liberar_una_operacion_no_toca_otro_tenant(monkeypatch):
    from backend import booking_operations, clients, db, timeutils
    ahora = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)
    clave, huella = "perdida_aislada", "k" * 64
    monkeypatch.setattr(timeutils, "_utc_now", lambda: ahora)
    monkeypatch.setattr(clients, "_get_client_config", lambda _: {"booking": {}})
    creada = (ahora - timedelta(minutes=16)).replace(tzinfo=None).isoformat() + "Z"
    _pendiente_sin_cita("demo", clave, huella, creada)
    _pendiente_sin_cita("otro", clave, huella, creada)
    try:
        with pytest.raises(HTTPException) as exc:
            booking_operations.recover_creation_operation("demo", clave, huella)
        assert exc.value.detail["code"] == "OPERATION_RELEASED"
        with db._get_db_connection() as conn:
            assert conn.execute("SELECT 1 FROM booking_operations WHERE cliente_id=? AND operation_key=?",
                                ("otro", clave)).fetchone()
    finally:
        with db._get_db_connection() as conn:
            conn.execute("DELETE FROM booking_operations WHERE operation_key=?", (clave,))
            conn.execute("DELETE FROM booking_operation_audit WHERE operation_key=?", (clave,))
            conn.commit()
