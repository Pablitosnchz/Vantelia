"""El caso de una reserva completa no puede aprobar una agenda duplicada.

Se ejecuta el veredicto real con el caso real del banco y resultados de agenda
sintéticos; la frontera de lectura usa SQLite temporal. No mide la conversación
ni importa el backend real, modelo o canales.
"""
import sqlite3
import sys
from contextlib import closing
from types import ModuleType, SimpleNamespace

import pytest

from scripts import evaluar_asistente as banco


def _cita(identificador, estado, codigo="EVAL-123"):
    return {"id": identificador, "booking_code": codigo, "status": estado,
            "booking_date": "2030-01-02", "booking_time": "10:00"}


def _veredicto_con_citas(monkeypatch, antes, despues):
    caso = next(c for c in banco._cargar_casos() if c["id"] == "reserva-completa-de-verdad")

    async def conversar(**kwargs):
        pass

    backend_sintetico = ModuleType("backend")
    backend_sintetico.whatsapp = SimpleNamespace(
        _wa_clear_flow=lambda *args: None, _handle_whatsapp_message=conversar)
    monkeypatch.setitem(sys.modules, "backend", backend_sintetico)
    lecturas = iter([antes, despues])
    monkeypatch.setattr(banco, "_citas_del_telefono", lambda *args: next(lecturas))
    return banco._ejecutar_caso("tenant_sintetico", caso, [], 0)


@pytest.mark.parametrize("estados, esperado", [
    pytest.param([], False, id="cero-citas"),
    pytest.param(["confirmed"], True, id="una-confirmada"),
    pytest.param(["pending_review"], True, id="una-pendiente"),
    pytest.param(["pending_payment"], True, id="una-pendiente-de-pago"),
    pytest.param(["confirmed", "confirmed"], False, id="dos-vivas"),
    pytest.param(["confirmed", "pending_payment"], False, id="confirmada-y-pago-pendiente"),
    pytest.param(["cancelled"], False, id="ninguna-viva"),
    pytest.param(["confirmed", "cancelled"], True, id="una-viva-con-historial"),
])
def test_reserva_completa_exige_una_cita_viva(monkeypatch, estados, esperado):
    filas = [_cita("bk_eval_%d" % i, estado) for i, estado in enumerate(estados)]
    ok, _respuestas, motivo = _veredicto_con_citas(monkeypatch, [], filas)
    assert ok is esperado, "Veredicto incorrecto para %s: %s" % (estados, motivo)


@pytest.mark.parametrize("antes, despues, esperado", [
    pytest.param(
        [_cita("bk_antigua", "confirmed")],
        [_cita("bk_antigua", "confirmed"), _cita("bk_nueva", "cancelled")],
        False, id="antigua-viva-y-nueva-cancelada"),
    pytest.param(
        [_cita("bk_antigua", "confirmed")],
        [_cita("bk_antigua", "cancelled"), _cita("bk_nueva", "confirmed")],
        True, id="antigua-cancelada-y-nueva-viva"),
    pytest.param(
        [_cita("bk_antigua", "cancelled", "")],
        [_cita("bk_antigua", "cancelled", ""), _cita("bk_nueva", "pending_payment", "")],
        True, id="codigos-vacios-identidad-distinta"),
    pytest.param(
        [_cita("bk_antigua", "cancelled")],
        [_cita("bk_nueva", "confirmed")],
        True, id="nueva-viva-sin-crecer-el-total"),
])
def test_la_unica_cita_viva_debe_ser_nueva(monkeypatch, antes, despues, esperado):
    ok, _respuestas, motivo = _veredicto_con_citas(monkeypatch, antes, despues)
    assert ok is esperado, "Veredicto incorrecto para %s -> %s: %s" % (antes, despues, motivo)


def test_lectura_de_agenda_conserva_identidad_con_codigos_vacios(monkeypatch, tmp_path):
    with closing(sqlite3.connect(str(tmp_path / "agenda.sqlite3"))) as conexion:
        conexion.row_factory = sqlite3.Row
        conexion.execute(
            "CREATE TABLE bookings (id TEXT PRIMARY KEY, booking_code TEXT, status TEXT, "
            "booking_date TEXT, booking_time TEXT, cliente_id TEXT, telefono TEXT, created_at TEXT)")
        conexion.executemany(
            "INSERT INTO bookings VALUES (?, '', ?, '2030-01-02', '10:00', "
            "'tenant_sintetico', '+34 600123456', ?)",
            [("bk_antigua", "cancelled", "2030-01-01T09:00:00"),
             ("bk_nueva", "pending_payment", "2030-01-01T09:01:00")])
        backend_sintetico = ModuleType("backend")
        backend_sintetico.db = SimpleNamespace(_get_db_connection=lambda: conexion)
        monkeypatch.setitem(sys.modules, "backend", backend_sintetico)

        citas = banco._citas_del_telefono("tenant_sintetico", "34600123456")

        assert {c["id"] for c in citas} == {"bk_antigua", "bk_nueva"}
        assert [c["booking_code"] for c in citas] == ["", ""]
