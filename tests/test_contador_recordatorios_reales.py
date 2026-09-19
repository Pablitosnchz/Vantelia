"""El contador mide envíos, no avisos examinados o cerrados sin canal."""
import asyncio
from datetime import timedelta

import pytest

from test_recordatorio_omitido_y_fallido import entorno  # noqa: F401


@pytest.mark.parametrize("tipo,horas", [("24h", 24), ("2h", 2)])
@pytest.mark.parametrize("enviar", [False, True])
def test_contador_solo_suma_si_sale_por_un_canal(entorno, monkeypatch, tipo, horas, enviar):
    from backend import agenda, timeutils

    b, bid = entorno.booking, entorno.booking_id
    inicio = timeutils._utc_now() + timedelta(hours=horas, minutes=20)
    b._update_booking_record(bid, start_at=inicio.isoformat(),
                             end_at=(inicio + timedelta(minutes=30)).isoformat(),
                             reminder_24h_sent_at="previo" if tipo == "2h" else "")
    monkeypatch.setattr(agenda, "_effective_followup_channels", lambda *a: {
        "reminder_" + tipo: {"email": False, "whatsapp": enviar, "sms": False}})
    salidas = []
    async def whatsapp(*a, **k):
        salidas.append(1)
        return True
    monkeypatch.setattr(b, "_send_booking_whatsapp_reminder", whatsapp)
    resultado = asyncio.run(b._run_booking_reminders())
    assert resultado.failed == 0
    assert getattr(resultado, "sent_" + tipo) == int(enviar)
    assert len(salidas) == int(enviar)
    fila = b._get_booking_row_by_id(bid)
    assert fila["reminder_" + tipo + "_sent_at"], "se cierra incluso omitido, sin bucle"
    otra = asyncio.run(b._run_booking_reminders())
    assert getattr(otra, "sent_" + tipo) == 0
    assert len(salidas) == int(enviar)
