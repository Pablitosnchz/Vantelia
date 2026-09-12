import pytest
from test_booking_exhaustive import api_module, client  # noqa: F401
from test_crm_light import portal_cookies  # noqa: F401

@pytest.mark.parametrize("estado", ["APPROVED", "PENDING", "REJECTED", ""])
def test_portal_muestra_plantilla_del_tenant(client, portal_cookies, monkeypatch, estado):
    from backend import wa_plantillas
    consultados = []
    def consultar(cid):
        consultados.append(cid)
        return {"status": estado, "last_error": "dato interno que no debe exponerse"}
    monkeypatch.setattr(wa_plantillas, "estado", consultar)
    respuesta = client.get("/auth/app/whatsapp", cookies=portal_cookies)
    assert respuesta.status_code == 200
    assert respuesta.json()["plantilla_recordatorio_estado"] == (estado or "NOT_CREATED")
    assert consultados == ["demo"]
    assert "dato interno" not in respuesta.text
