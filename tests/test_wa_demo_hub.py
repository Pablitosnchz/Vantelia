"""Numero de WhatsApp compartido para demos comerciales (backend/wa_demo.py).

Un solo numero propio en Cloud API atiende a muchos prospectos: cada uno recibe
un codigo, y su telefono queda atado a SU asistente. Lo que se valida aqui es lo
que puede costar dinero o credibilidad:

- Que sin codigo valido no se cuele nadie en el asistente de un cliente real
  (probar el id del tenant NO debe funcionar).
- Que el codigo caducado o revocado deje de dar acceso, y que revocar corte
  tambien las conversaciones que ya entraron con el.
- Que el enlace `wa.me` que se le manda al prospecto lleve el texto prellenado,
  que es lo que evita tener que pedirle nada raro.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


@pytest.fixture(autouse=True)
def _limpiar_codigos(api_module):
    from backend import db

    yield
    with db._get_db_connection() as connection:
        connection.execute("DELETE FROM wa_demo_routes")
        connection.execute("DELETE FROM wa_demo_codes")
        connection.commit()


# --- Lectura del codigo en el mensaje --------------------------------------


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("DEMO ABC123", "ABC123"),
        ("demo abc123", "ABC123"),
        ("Hola, DEMO-ABC123", "ABC123"),
        ("demo: abc123", "ABC123"),
        ("ABC123", "ABC123"),              # codigo suelto tecleado a mano
        ("quiero informacion del spa", ""),
        ("demo", ""),
        ("", ""),
    ],
)
def test_extract_code(api_module, texto, esperado):
    from backend import wa_demo

    assert wa_demo.extract_code(texto) == esperado


# --- Enrutado ---------------------------------------------------------------


def test_codigo_ata_el_telefono_a_su_tenant(api_module):
    from backend import wa_demo

    code = wa_demo.create_code("demo", label="Hotel de prueba")["code"]
    routing = wa_demo.resolve_incoming("hub-1", "34600111222", f"DEMO {code}")
    assert routing["cliente_id"] == "demo"
    assert routing["just_bound"] is True

    # Los mensajes siguientes ya no llevan codigo y siguen en la misma demo.
    seguimiento = wa_demo.resolve_incoming("hub-1", "34600111222", "¿teneis spa?")
    assert seguimiento["cliente_id"] == "demo"
    assert seguimiento["just_bound"] is False


def test_sin_codigo_no_habla_con_ningun_asistente(api_module):
    from backend import wa_demo

    routing = wa_demo.resolve_incoming("hub-1", "34600999888", "hola, buenas")
    assert routing["cliente_id"] == ""
    assert "DEMO" in routing["help_text"]


def test_el_id_del_tenant_no_sirve_como_codigo(api_module):
    """Sin esto, cualquiera adivinando nombres entraria en el bot de un cliente real."""
    from backend import wa_demo

    for intento in ("demo", "DEMO demo", "caprocat", "DEMO caprocat"):
        routing = wa_demo.resolve_incoming("hub-1", "34600777666", intento)
        assert routing["cliente_id"] == "", intento


def test_codigo_caducado_no_da_acceso(api_module):
    from backend import db, wa_demo

    code = wa_demo.create_code("demo")["code"]
    with db._get_db_connection() as connection:
        connection.execute(
            "UPDATE wa_demo_codes SET expires_at = '2020-01-01T00:00:00Z' WHERE code = ?", (code,)
        )
        connection.commit()
    routing = wa_demo.resolve_incoming("hub-1", "34600555444", f"DEMO {code}")
    assert routing["cliente_id"] == ""
    assert "caducado" in routing["help_text"]


def test_revocar_corta_tambien_las_conversaciones_abiertas(api_module):
    from backend import wa_demo

    code = wa_demo.create_code("demo")["code"]
    assert wa_demo.resolve_incoming("hub-1", "34600333222", f"DEMO {code}")["cliente_id"] == "demo"

    assert wa_demo.revoke_code(code) is True
    assert wa_demo.resolve_incoming("hub-1", "34600333222", "¿teneis spa?")["cliente_id"] == ""


def test_un_movil_puede_ver_varias_demos(api_module):
    """El comercial enseña dos asistentes desde el mismo telefono."""
    from backend import wa_demo

    primero = wa_demo.create_code("demo")["code"]
    wa_demo.resolve_incoming("hub-1", "34600222111", f"DEMO {primero}")
    segundo = wa_demo.create_code("van")["code"]
    routing = wa_demo.resolve_incoming("hub-1", "34600222111", f"DEMO {segundo}")
    assert routing["cliente_id"] == "van"
    assert routing["just_bound"] is True


def test_contador_de_usos(api_module):
    from backend import wa_demo

    code = wa_demo.create_code("demo")["code"]
    wa_demo.resolve_incoming("hub-1", "34600111000", f"DEMO {code}")
    wa_demo.resolve_incoming("hub-1", "34600111001", f"DEMO {code}")
    fila = [c for c in wa_demo.list_codes("demo") if c["code"] == code][0]
    assert fila["uses"] == 2


# --- Enlace para el prospecto ----------------------------------------------


def test_wa_link_lleva_el_texto_prellenado(api_module, monkeypatch):
    from backend import settings, wa_demo

    monkeypatch.setattr(settings, "WHATSAPP_DEMO_PUBLIC_NUMBER", "+34 600 00 00 00", raising=False)
    assert wa_demo.wa_link("ABC123") == "https://wa.me/34600000000?text=DEMO%20ABC123"


def test_sin_numero_configurado_no_hay_enlace_ni_hub(api_module, monkeypatch):
    """La funcion esta apagada mientras no exista el numero: no debe romper nada."""
    from backend import settings, wa_demo

    monkeypatch.setattr(settings, "WHATSAPP_DEMO_PUBLIC_NUMBER", "", raising=False)
    monkeypatch.setattr(settings, "WHATSAPP_DEMO_PHONE_NUMBER_ID", "", raising=False)
    assert wa_demo.wa_link("ABC123") == ""
    assert wa_demo.hub_phone_number_ids() == set()
    assert wa_demo.is_hub("cualquier-cosa") is False


# --- API admin --------------------------------------------------------------


def test_endpoints_admin(api_module, client):
    headers = {"Authorization": "Bearer test-admin-token"}

    creado = client.post(
        "/admin/whatsapp-demo/codes",
        headers=headers,
        json={"cliente_id": "demo", "label": "Cap Rocat", "days": 30},
    )
    assert creado.status_code == 200, creado.text
    code = creado.json()["code"]
    assert len(code) == 6

    listado = client.get("/admin/whatsapp-demo/codes?cliente_id=demo", headers=headers)
    assert listado.status_code == 200
    assert any(item["code"] == code for item in listado.json()["items"])

    assert client.delete(f"/admin/whatsapp-demo/codes/{code}", headers=headers).status_code == 200
    assert client.delete(f"/admin/whatsapp-demo/codes/{code}", headers=headers).status_code == 404

    # Tenant inexistente y sin token.
    assert client.post(
        "/admin/whatsapp-demo/codes", headers=headers,
        json={"cliente_id": "no-existe", "label": "", "days": 30},
    ).status_code == 404
    assert client.get("/admin/whatsapp-demo/codes").status_code in (401, 403)
