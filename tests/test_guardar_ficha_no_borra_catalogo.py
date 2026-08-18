"""Guardar la ficha del cliente no puede vaciarle el catalogo de servicios.

Incidente real (18-ago-2026): al cambiar UN campo del formulario admin de un
salon --el mensaje de confirmacion-- se resembraron los servicios desde su
info.txt y se DESACTIVARON los 183 que no aparecian ahi. Su catalogo entero, que
venia de su Excel, desaparecio de la web y de WhatsApp sin decir nada: el
endpoint publico paso a devolver 8 servicios.

Un negocio serio tiene mas servicios de los que caben en su descripcion.
"""
from __future__ import annotations

import uuid

from test_booking_exhaustive import api_module, client  # noqa: F401

CABECERAS = {"Authorization": "Bearer test-admin-token"}

# La descripcion del negocio menciona SUS servicios, que nunca son todos: es
# justo la situacion del incidente (183 en el catalogo, 8 en el texto).
INFO_TXT = chr(10).join([
    'Somos una peluqueria en Elche.',
    '',
    'SERVICIOS Y PRECIOS',
    '',
    '- Servicio: Corte de pelo',
    '- Precio: 20 EUR',
    '- Duracion: 30 min',
    '- Descripcion: corte y peinado',
    '',
    '- Servicio: Coloracion',
    '- Precio: 45 EUR',
    '- Duracion: 60 min',
    '- Descripcion: color por todo el cabello',
    '',
])


def _servicio_suelto(api_module, cliente_id="demo"):
    """Servicio que existe en el catalogo pero NO se menciona en info.txt."""
    from backend import db, timeutils

    ahora = timeutils._utc_now_iso()
    slug = "svc_excel_" + uuid.uuid4().hex[:8]
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO services (cliente_id, slug, name, duration_minutes, price_cents,
                description, is_active, sort_order, created_at, updated_at)
            VALUES (?, ?, ?, 45, 7000, '', 1, 0, ?, ?)
            """,
            (cliente_id, slug, "Mechas balayage " + slug[-4:], ahora, ahora),
        )
        connection.commit()
    return slug


def _sigue_activo(api_module, slug, cliente_id="demo"):
    from backend import db

    with db._get_db_connection() as connection:
        fila = connection.execute(
            "SELECT is_active FROM services WHERE cliente_id=? AND slug=?", (cliente_id, slug)
        ).fetchone()
    return bool(fila and fila["is_active"])


def test_guardar_la_ficha_respeta_los_servicios_que_no_estan_en_el_texto(api_module, client):
    """El caso que costo el catalogo de un cliente real."""
    slug = _servicio_suelto(api_module)
    ficha = client.get("/admin/clientes/demo", headers=CABECERAS)
    assert ficha.status_code == 200, ficha.text
    payload = ficha.json()["config"]
    payload["reindex_after_save"] = False
    payload["info_txt"] = INFO_TXT
    payload["booking_success_message"] = "Te esperamos en el salon."

    guardado = client.put("/admin/clientes/demo", headers=CABECERAS, json=payload)
    assert guardado.status_code == 200, guardado.text
    # Lo que menciona el texto se da de alta...
    assert _sigue_activo(api_module, "corte_de_pelo")
    # ...y lo que NO menciona sigue vivo. Esto es lo que se perdio en produccion.
    assert _sigue_activo(api_module, slug), "guardar la ficha ha desactivado un servicio del catalogo"


def test_el_guardado_no_pide_desactivar_lo_que_falte(api_module):
    """Fijado en el codigo: el flag es la diferencia entre sincronizar y vaciar."""
    import inspect

    from backend import portal

    fuente = inspect.getsource(portal._save_admin_client_payload)
    assert "deactivate_missing=False" in fuente
    assert "deactivate_missing=True" not in fuente


def test_el_sincronizado_sigue_creando_lo_que_menciona_el_texto(api_module):
    """No se rompe lo util: los servicios del texto se siguen dando de alta."""
    import inspect

    from backend import agenda

    fuente = inspect.getsource(agenda._sync_services_from_info)
    assert "deactivate_missing" in fuente
