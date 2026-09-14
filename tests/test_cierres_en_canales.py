import asyncio
from datetime import date
import pytest
from test_vacaciones_son_dia_cerrado import api_module, bloqueo, _next_weekday


def test_rag_vacaciones_no_son_agenda_completa(api_module, bloqueo):
    from backend import rag
    fecha = _next_weekday(4)
    bloqueo(fecha, '00:00', '23:59')
    resultado = asyncio.run(rag._availability_snapshot_for_day('demo', date.fromisoformat(fecha)))
    assert resultado['status'] == 'closed'


def test_contexto_chat_informa_cierre_y_motivo(api_module, bloqueo):
    from backend import rag
    fecha = _next_weekday(4)
    bloqueo(fecha, '00:00', '23:59')
    contexto = asyncio.run(rag._build_availability_context('demo', date.fromisoformat(fecha)))
    assert 'cerrada' in contexto
    assert 'Vacaciones' in contexto
    assert 'completa' not in contexto


def test_picker_no_ofrece_fecha_cerrada(api_module, monkeypatch):
    from backend import agenda, whatsapp, messaging, clients
    enviados = []
    fechas = []
    def cierre(cid, fecha, config=None):
        fechas.append(fecha)
        return 'Vacaciones' if len(set(fechas)) == 1 else None
    async def huecos(*a, **kw):
        return {'10:00'}, {'10:00'}
    async def enviar(**kw):
        enviados.append(kw)
        return True
    monkeypatch.setattr(agenda, 'motivo_de_cierre_del_dia', cierre)
    monkeypatch.setattr(agenda, '_public_slot_sets_for_day', huecos)
    monkeypatch.setattr(messaging, '_send_whatsapp_list', enviar)
    asyncio.run(whatsapp._wa_send_date_picker(cliente_id='demo', phone_number_id='PN', to_number='test',
        config=clients._get_client_config('demo'), header='Fecha', body='Elige'))
    assert fechas, 'Debe consultar los cierres por fecha, no solo el dia semanal'
    ids = [row['id'] for s in enviados[0]['sections'] for row in s['rows']]
    assert 'date_' + fechas[0] not in ids
