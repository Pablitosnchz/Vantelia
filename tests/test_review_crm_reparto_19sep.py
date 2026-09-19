import asyncio
import pytest
from fastapi import HTTPException
from test_reparto_por_niveles import equipo, _dia_habil  # noqa: F401
from test_nota_del_mostrador_no_es_clienta import _apuntar
from test_api_smoke import _portal_admin_cookies


def test_solicitar_ultima_gana_a_nivel(api_module, equipo):
    requested = equipo['Alicia Prueba']
    chosen = asyncio.run(api_module._resolve_public_booking_employee(
        'demo', _dia_habil(), '11:00', employee_id=requested))
    assert chosen['id'] == requested


def test_empleado_ajeno_no_se_selecciona(api_module, equipo):
    with pytest.raises(HTTPException) as caught:
        asyncio.run(api_module._resolve_public_booking_employee(
            'otro_cliente', _dia_habil(), '11:00', employee_id=equipo['Alicia Prueba']))
    assert caught.value.status_code == 404


def test_guardar_otro_campo_conserva_segunda(client, api_module, equipo):
    cookies = _portal_admin_cookies(api_module)
    emp = equipo['Lucia Prueba']
    r = client.post('/auth/employees/%s' % emp, params={'cliente_id': 'demo'},
                    cookies=cookies, json={'name': 'Lucia Prueba', 'role_label': 'Color'})
    assert r.status_code == 200, r.text
    assert r.json()['reparto'] == 2


def test_staff_no_puede_cambiar_nivel(client, api_module, equipo):
    staff = api_module._create_user(email='review-staff@example.invalid', password='review-password-123',
        role='client', display_name='Staff', cliente_id='demo', portal_role='staff')
    cookies = {'vantelia_portal_session': api_module._create_auth_session(staff['id'])}
    r = client.post('/auth/employees/%s' % equipo['Lucia Prueba'], cookies=cookies,
                    json={'name': 'Lucia Prueba', 'reparto': 1})
    assert r.status_code == 403, r.text
    assert api_module.nivel_de_reparto(api_module._get_employee_row(equipo['Lucia Prueba'], cliente_id='demo')) == 2


def test_crm_guardia_aislado_y_solo_notas(client, api_module):
    cookies = _portal_admin_cookies(api_module)
    bid, _ = _apuntar(client, cookies, 'Nota Revisada Aislada', hora='09:00')
    assert api_module._es_nota_del_mostrador('demo', bid)
    assert not api_module._es_nota_del_mostrador('otro_cliente', bid)
    assert not api_module._crm_upsert_contact('demo', name='Nota Revisada Aislada',
        entity_type='booking', entity_id=bid)
    assert api_module._crm_upsert_contact('demo', name='Contacto Manual Revisado',
        source='portal_manual', entity_type='lead', entity_id='review-lead')
    contacto = api_module._crm_upsert_contact('demo', name='Nota Revisada Aislada',
        email='review-email@example.invalid', entity_type='booking', entity_id=bid)
    assert contacto
    with api_module._get_db_connection() as conn:
        row = conn.execute('SELECT cliente_id, email FROM crm_contacts WHERE id=?', (contacto,)).fetchone()
    assert row['cliente_id'] == 'demo'
    assert row['email'] == 'review-email@example.invalid'
    with api_module._get_db_connection() as conn:
        conn.execute('DELETE FROM bookings WHERE id=?', (bid,))
        conn.execute('DELETE FROM booking_audit WHERE booking_id=?', (bid,))
        conn.execute('DELETE FROM crm_contact_links WHERE entity_id IN (?, ?)', (bid, 'review-lead'))
        conn.execute('DELETE FROM crm_contacts WHERE id=? OR name=?', (contacto, 'Contacto Manual Revisado'))
        conn.commit()

