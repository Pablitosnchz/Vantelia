import datetime as dt

from test_estirar_la_cita import _proximo_dia_con_hueco


def test_la_rejilla_abierta_no_basta_si_hay_ocupacion(monkeypatch):
    from backend import agenda, timeutils
    monkeypatch.setattr(timeutils, "_utc_now", lambda: dt.datetime(2026, 9, 12, tzinfo=dt.timezone.utc))
    monkeypatch.setattr(agenda, "_build_slots_for_day", lambda *a, **k: ["10:00", "11:00", "12:00"])
    async def disponible(cid, fecha, hora, **kwargs):
        return fecha != "2026-09-13"
    monkeypatch.setattr(agenda, "_booking_slot_available", disponible)
    assert _proximo_dia_con_hueco("negocio") == "2026-09-14"
