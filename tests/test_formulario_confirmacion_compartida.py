"""Formulario real: recoger datos no acepta ni ejecuta una cita."""
import asyncio
import json
import uuid

import httpx
import pytest

from test_huecos_para_mover_la_cita import api_module, agenda_de_dos  # noqa: F401


@pytest.fixture
def formulario(agenda_de_dos, monkeypatch):
    from backend import booking, db, inbox, messaging, reserva, wa_flows, whatsapp
    _, dia, empleados, _ = agenda_de_dos
    numero = "34" + str(uuid.uuid4().int)[-9:]
    botones, textos, historial, payloads, proveedores = [], [], [], [], []
    async def si(**kw): return True
    async def no(**kw): return False
    async def boton(**kw):
        botones.append(kw)
        return True
    async def texto(**kw):
        textos.append(kw["text"])
        return True
    async def payload(**kw):
        payloads.append(kw["payload"])
        return True
    original = booking._create_provider_booking
    async def proveedor(*a, **kw):
        proveedores.append(1)
        return await original(*a, **kw)
    monkeypatch.setattr(booking, "_create_provider_booking", proveedor)
    monkeypatch.setattr(wa_flows, "enabled", lambda: True)
    monkeypatch.setattr(wa_flows, "_token_secret", lambda: b"solo-prueba-formulario")
    monkeypatch.setattr(whatsapp, "_wa_freno_del_precio", no)
    monkeypatch.setattr(whatsapp, "_wa_explicar_el_recargo", si)
    monkeypatch.setattr(whatsapp, "_wa_registrar", lambda **kw: historial.append(kw))
    monkeypatch.setattr(inbox, "bot_is_muted", lambda *a: False)
    monkeypatch.setattr(messaging, "_send_whatsapp_payload", payload)
    monkeypatch.setattr(messaging, "_send_whatsapp_buttons", boton)
    monkeypatch.setattr(messaging, "_send_whatsapp_text", texto)
    monkeypatch.setattr(messaging, "_send_whatsapp_cta_url", si)
    def abrir():
        asyncio.run(whatsapp._wa_send_booking_form(
            cliente_id="demo", phone_number_id="PN", to_number=numero))
        return payloads[-1]["interactive"]["action"]["parameters"]["flow_token"]
    def recibir(token=None, **cambios):
        datos = dict(flow_token=token or actual, servicio="", employee_id=empleados[0]["id"],
                     hueco=dia + "T10:00", nombre="Ana Formulario", email="", notas="")
        datos.update(cambios)
        return asyncio.run(whatsapp._wa_handle_flow_reply(
            cliente_id="demo", phone_number_id="PN", from_number=numero,
            response_json=json.dumps(datos), request=None))
    def confirmar(iid=None):
        asyncio.run(whatsapp._handle_whatsapp_message(
            cliente_id="demo", phone_number_id="PN", from_number=numero,
            incoming_text="Confirmar", interactive_id=iid or botones[-1]["buttons"][0][0], request=None))
    def citas():
        with db._get_db_connection() as conn:
            return conn.execute("SELECT * FROM bookings WHERE telefono=?", (numero,)).fetchall()
    reserva.guardar("demo", numero, reserva.cargar("demo", numero))
    actual = abrir()
    yield dict(numero=numero, dia=dia, empleado=empleados[0]["id"], abrir=abrir, recibir=recibir, confirmar=confirmar, citas=citas,
               botones=botones, textos=textos, historial=historial, token=actual, proveedores=proveedores)
    propuesta = reserva.leer_confirmacion_reserva(reserva.cargar("demo", numero), incluir_hecha=True)
    clave = (propuesta or {}).get("operacion", {}).get("clave", "")
    reserva.olvidar("demo", numero)
    whatsapp._wa_clear_flow("demo", numero)
    with db._get_db_connection() as conn:
        conn.execute("DELETE FROM booking_operations WHERE operation_key=?", (clave,))
        conn.execute("DELETE FROM booking_operations WHERE booking_id IN (SELECT id FROM bookings WHERE telefono=?)", (numero,))
        conn.execute("DELETE FROM bookings WHERE telefono=?", (numero,))
        conn.commit()


def test_formulario_ofrece_y_solo_el_boton_vigente_crea_una_fila(formulario, monkeypatch):
    from backend import appstate, reserva
    f = formulario
    assert f["recibir"]()
    assert not f["citas"]() and not f["proveedores"]
    p = reserva.leer_confirmacion_reserva(reserva.cargar("demo", f["numero"]))
    assert p["estado"] == "ofrecida"
    iid = f["botones"][-1]["buttons"][0][0]
    f["confirmar"]("confirm_yes:antiguo")
    assert not f["citas"]()
    monkeypatch.setattr(appstate, "whatsapp_flows", {})
    assert f["recibir"]()
    assert f["botones"][-1]["buttons"][0][0] == iid
    f["confirmar"](iid)
    f["confirmar"](iid)
    f["recibir"]()
    assert len(f["citas"]()) == len(f["proveedores"]) == 1


@pytest.mark.parametrize("tenant,phone", [("otro", None), ("demo", "34600123456"), ("demo", "99600123456")])
def test_token_ajeno_no_muta_estado_ni_agenda(formulario, tenant, phone):
    from backend import reserva, wa_flows
    f = formulario
    previo = reserva.cargar("demo", f["numero"])
    token = wa_flows.make_flow_token(tenant, phone or f["numero"])
    assert f["recibir"](token) is False
    assert reserva.cargar("demo", f["numero"]) == previo
    assert not f["citas"]() and not f["proveedores"]


@pytest.mark.parametrize("accion", ["crear", "cancelar"])
def test_formulario_no_sustituye_aceptacion_pendiente(formulario, accion):
    from backend import reserva
    f = formulario
    estado = reserva.cargar("demo", f["numero"])
    datos = {"accion": "cancelar", "booking_code": "EXISTENTE"} if accion == "cancelar" else {"nombre": "Anterior"}
    iid = reserva.preparar_confirmacion_reserva(estado, datos)
    reserva.avanzar_confirmacion_reserva(estado, iid, "ofrecida")
    reserva.avanzar_confirmacion_reserva(estado, iid, "aceptada")
    reserva.guardar("demo", f["numero"], estado)
    previo = estado.confirmacion_reserva_json
    f["recibir"]()
    assert reserva.cargar("demo", f["numero"]).confirmacion_reserva_json == previo
    assert not f["citas"]() and not f["proveedores"]


def test_token_anterior_y_respuesta_alterada_no_reemplazan_propuesta(formulario):
    from backend import reserva
    f = formulario
    f["recibir"]()
    viejo = f["botones"][-1]["buttons"][0][0]
    nuevo_token = f["abrir"]()
    f["recibir"](nuevo_token, notas="Nueva propuesta")
    nueva = reserva.cargar("demo", f["numero"]).confirmacion_reserva_json
    assert f["recibir"]() is False
    assert f["recibir"](nuevo_token, notas="Respuesta alterada") is False
    assert reserva.cargar("demo", f["numero"]).confirmacion_reserva_json == nueva
    f["confirmar"](viejo)
    assert not f["citas"]()


def test_otra_gestion_sustituye_resumen_sin_resucitar_formulario_consumido(formulario):
    from backend import reserva
    f = formulario
    f["recibir"]()
    estado = reserva.cargar("demo", f["numero"])
    datos = reserva.leer_confirmacion_reserva(estado)["datos"]
    datos["hora"] = "11:00"
    nuevo = reserva.preparar_confirmacion_reserva(estado, datos)
    reserva.avanzar_confirmacion_reserva(estado, nuevo, "ofrecida")
    reserva.guardar("demo", f["numero"], estado)
    assert f["recibir"]() is False
    assert reserva.cargar("demo", f["numero"]).confirmacion_reserva_json == estado.confirmacion_reserva_json


def test_formulario_nuevo_tras_hecha_libera_flujo_y_el_viejo_no_lo_muta(formulario):
    from backend import reserva
    f = formulario
    f["recibir"]()
    f["confirmar"]()
    assert reserva.cargar("demo", f["numero"]).hecho
    nuevo_token = f["abrir"]()
    f["recibir"](nuevo_token, notas="Otra solicitud", hueco=f["dia"] + "T11:00")
    actual = reserva.cargar("demo", f["numero"])
    assert not actual.hecho
    assert reserva.leer_confirmacion_reserva(actual)["estado"] == "ofrecida"
    assert f["recibir"]() is False
    assert reserva.cargar("demo", f["numero"]).confirmacion_reserva_json == actual.confirmacion_reserva_json
    assert len(f["citas"]()) == len(f["proveedores"]) == 1


def test_aceptacion_concurrente_antes_de_publicar_resumen_no_se_sustituye(formulario, monkeypatch):
    from backend import reserva, whatsapp
    f = formulario
    aceptadas = []
    async def aceptar(**kw):
        estado = reserva.cargar("demo", f["numero"])
        iid = reserva.preparar_confirmacion_reserva(estado, {"accion": "cancelar", "booking_code": "ANTERIOR"})
        reserva.avanzar_confirmacion_reserva(estado, iid, "ofrecida")
        reserva.avanzar_confirmacion_reserva(estado, iid, "aceptada")
        reserva.guardar("demo", f["numero"], estado)
        aceptadas.append(estado.confirmacion_reserva_json)
    monkeypatch.setattr(whatsapp, "_wa_explicar_el_recargo", aceptar)
    assert f["recibir"]() is False
    assert reserva.cargar("demo", f["numero"]).confirmacion_reserva_json == aceptadas[-1]
    assert not f["botones"] and not f["citas"]()


def test_dos_formularios_en_el_mismo_segundo_tienen_identidades_distintas(formulario, monkeypatch):
    from backend import timeutils, wa_flows
    monkeypatch.setattr(timeutils, "_utc_now_iso", lambda: "2026-09-13T00:00:00Z")
    assert wa_flows.make_flow_token("demo", formulario["numero"]) != wa_flows.make_flow_token("demo", formulario["numero"])


@pytest.mark.parametrize("cambio", ["ocupado", "retirado", "vacaciones", "horario"])
def test_no_ofrece_datos_que_el_nucleo_ya_rechaza(formulario, cambio):
    from backend import db, reserva, timeutils
    f = formulario
    cambios = {}
    slug = "form_" + uuid.uuid4().hex
    with db._get_db_connection() as conn:
        if cambio == "ocupado":
            cambios["hueco"] = f["dia"] + "T12:00"  # La fixture ya tiene una cita de otra persona.
        elif cambio == "retirado":
            conn.execute("INSERT INTO services(cliente_id,slug,name,is_active,created_at) VALUES('demo',?,?,0,?)",
                         (slug, slug, timeutils._utc_now_iso()))
            cambios["servicio"] = slug
        elif cambio == "vacaciones":
            conn.execute("INSERT INTO agenda_blocks(id,cliente_id,employee_id,block_date,start_time,end_time,reason,created_at) VALUES(?,'demo',?,?,'00:00','23:59','Vacaciones',?)",
                         (slug, f["empleado"], f["dia"], timeutils._utc_now_iso()))
        else:
            conn.execute("UPDATE employees SET day_end='09:30' WHERE id=?", (f["empleado"],))
        conn.commit()
    try:
        assert f["recibir"](**cambios) is False
        assert not f["botones"] and not f["citas"]() and not f["proveedores"]
        assert not any(h.get("intent") == "resumen_para_confirmar" for h in f["historial"])
        assert reserva.leer_confirmacion_reserva(reserva.cargar("demo", f["numero"])) is None
    finally:
        with db._get_db_connection() as conn:
            conn.execute("DELETE FROM services WHERE slug=?", (slug,))
            conn.execute("DELETE FROM agenda_blocks WHERE id=?", (slug,))
            conn.commit()


def test_sin_preferencia_conserva_profesional_y_recargo_y_no_reasigna(formulario):
    from backend import agenda, booking, db, reserva
    f = formulario
    competidora = None
    with db._get_db_connection() as conn:
        anteriores = conn.execute("SELECT id,is_active FROM employees WHERE cliente_id='demo'").fetchall()
        conn.execute("UPDATE employees SET is_active=0 WHERE cliente_id='demo' AND id<>?", (f["empleado"],))
        conn.execute("UPDATE employees SET price_surcharge_pct=25 WHERE id=?", (f["empleado"],))
        conn.commit()
    try:
        assert f["recibir"](employee_id="")
        p = reserva.leer_confirmacion_reserva(reserva.cargar("demo", f["numero"]))
        assert p["datos"]["employee_id"] == f["empleado"]
        fila = agenda._get_employee_row(f["empleado"], cliente_id="demo")
        assert p["datos"]["employee_name"] == fila["name"]
        assert p["datos"]["location_id"] == str(fila["location_id"] or "")
        assert "25%" in f["botones"][-1]["body"]
        competidora = asyncio.run(booking._create_booking_core(
            "demo", employee_row=fila, nombre="Otra persona", email="", telefono="competidora_" + f["numero"],
            servicio="", booking_date=f["dia"], booking_time="10:00", source="test", send_confirmation=False))
        with db._get_db_connection() as conn:
            for anterior in anteriores:
                conn.execute("UPDATE employees SET is_active=? WHERE id=?", (anterior["is_active"], anterior["id"]))
            conn.commit()
        f["proveedores"].clear()
        f["confirmar"]()
        assert not f["citas"]() and not f["proveedores"], "No cambiar a otra profesional sin otra propuesta"
    finally:
        with db._get_db_connection() as conn:
            for anterior in anteriores:
                conn.execute("UPDATE employees SET is_active=? WHERE id=?", (anterior["is_active"], anterior["id"]))
            if competidora:
                conn.execute("DELETE FROM bookings WHERE id=?", (competidora["id"],))
            conn.commit()


@pytest.mark.parametrize("incierto", [False, True])
def test_resumen_no_aceptado_no_oferta_historial_ni_perdida_de_identidad(formulario, monkeypatch, incierto):
    from backend import messaging, reserva
    f = formulario
    async def fallo(**kw):
        f["botones"].append(kw)
        if incierto:
            raise messaging.WhatsAppDeliveryUnknown(messaging.WhatsAppSendResult("desconocido"))
        return False
    monkeypatch.setattr(messaging, "_send_whatsapp_buttons", fallo)
    f["recibir"]()
    p = reserva.leer_confirmacion_reserva(reserva.cargar("demo", f["numero"]))
    assert p and p["estado"] == "preparada"
    assert not f["historial"] and not f["citas"]()
    f["recibir"]()
    assert reserva.leer_confirmacion_reserva(reserva.cargar("demo", f["numero"]))["id"] == p["id"]
    f["confirmar"]("confirm_yes:" + p["id"])
    assert not f["citas"]()


@pytest.mark.parametrize("tras_commit", [False, True])
def test_replay_tras_resultado_perdido_recupera_sin_segundo_proveedor(formulario, monkeypatch, tras_commit):
    from backend import appstate, booking, reserva
    f = formulario
    f["recibir"]()
    if tras_commit:
        def caer(*a, **kw): raise RuntimeError("caida tras guardar")
        monkeypatch.setattr(booking, "_record_booking_audit", caer)
    else:
        async def timeout(*a, **kw):
            f["proveedores"].append(1)
            raise httpx.ReadTimeout("resultado perdido")
        monkeypatch.setattr(booking, "_create_provider_booking", timeout)
    f["confirmar"]()
    p = reserva.leer_confirmacion_reserva(reserva.cargar("demo", f["numero"]))
    assert p and p.get("operacion")
    monkeypatch.setattr(appstate, "whatsapp_flows", {})
    f["recibir"]()
    assert len(f["proveedores"]) == 1
    assert len(f["citas"]()) == int(tras_commit)
    actual = reserva.leer_confirmacion_reserva(reserva.cargar("demo", f["numero"]), incluir_hecha=True)
    assert actual["id"] == p["id"]


def test_formulario_tras_un_rechazo_del_asistente_ensena_el_resumen(formulario):
    """Revisión de Codex a 167fc8d: con un rechazo del asistente guardado, el formulario nativo de
    WhatsApp traía servicio, profesional, día y hora validados y la clienta no recibía nada: el
    resumen seguía bloqueado. Rellenar el formulario es la aclaración."""
    from backend import reserva
    f = formulario
    estado = reserva.cargar("demo", f["numero"])
    reserva.anotar_resultado(estado, "crear_cita", {}, {"ok": False, "error": "Falta aclarar el servicio"})
    reserva.guardar("demo", f["numero"], estado)
    assert f["recibir"](), "el formulario no ha seguido: %s" % f["textos"][-2:]
    assert f["botones"], "rellenó el formulario y no le llegó el resumen"
