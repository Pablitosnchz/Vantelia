from test_booking_exhaustive import api_module, client  # noqa: F401
from test_crm_light import portal_cookies  # noqa: F401


def test_qa_configura_apellidos_solo_para_su_negocio(client, portal_cookies, monkeypatch):
    from backend import clients, appstate
    import copy
    vecino_cfg = copy.deepcopy(appstate.CONFIG_CLIENTES["demo"])
    vecino_cfg["booking"]["exigir_dos_apellidos"] = False
    monkeypatch.setitem(appstate.CONFIG_CLIENTES, "otro_negocio", vecino_cfg)
    monkeypatch.setattr(clients, "_persist_configs_to_disk", lambda configs: None)
    antes = client.get("/auth/app/business-rules", cookies=portal_cookies).json()
    vecino = clients.exige_dos_apellidos("otro_negocio")
    contactos = []
    try:
        for valor in (True, False):
            respuesta = client.put("/auth/app/business-rules/config", cookies=portal_cookies,
                                  json={"exigir_dos_apellidos": valor})
            assert respuesta.status_code == 200, respuesta.text
            assert respuesta.json()["exigir_dos_apellidos"] is valor
            assert respuesta.json()["enabled"] == antes["enabled"]
            assert clients.exige_dos_apellidos("demo") is valor
            assert clients.exige_dos_apellidos("otro_negocio") is vecino
            contacto = client.post("/auth/app/contacts", cookies=portal_cookies,
                                   json={"name": "Ana Ruiz", "phone": "600991122"})
            assert contacto.status_code == (400 if valor else 200), contacto.text
            if contacto.status_code == 200:
                contactos.append(contacto.json()["id"])
    finally:
        from backend import db
        with db._get_db_connection() as cx:
            for ident in contactos:
                cx.execute("DELETE FROM crm_contacts WHERE id=? AND cliente_id=?", (ident, "demo"))
            cx.commit()
        client.put("/auth/app/business-rules/config", cookies=portal_cookies,
                   json={"exigir_dos_apellidos": antes.get("exigir_dos_apellidos", False)})
