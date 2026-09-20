# -*- coding: utf-8 -*-
"""El interruptor de pausa en el panel (fase 4).

POR QUE EXISTE
--------------
Las fases anteriores dejaron la autoridad de atención puesta y consultada por
todos los canales, pero para accionarla había que entrar en la base de datos.
Esto es el interruptor, y llega el último a propósito: encenderlo antes de
tener las fronteras habría prometido un silencio que no se cumplía.

Lo que se comprueba aquí no es que el endpoint devuelva 200, sino que al
pulsarlo el asistente SE CALLA de verdad, que al volver a pulsarlo vuelve
entero, y que por el camino no se ha tocado el plan ni los cobros: pausar dos
semanas por obras no puede parecerse a darse de baja.
"""
from __future__ import annotations

import uuid

import pytest
from starlette.testclient import TestClient

from conftest import DEFAULT_DEMO_CONFIG  # noqa: F401  (documenta el tenant usado)


@pytest.fixture
def api(api_module):
    yield api_module
    _reactivar("demo")


def _reactivar(cliente_id):
    from backend import atencion, db

    try:
        estado = atencion.leer_atencion(cliente_id)
        if estado["estado"] == "pausada":
            atencion.cambiar_atencion(cliente_id, "activa", version_esperada=estado["version"],
                                      motivo="reapertura", actor="sistema")
        return
    except Exception:  # noqa: BLE001
        pass
    with db._get_db_connection() as conexion:
        conexion.execute("DELETE FROM client_attention_state WHERE cliente_id = ?", (cliente_id,))
        conexion.commit()


def _portal(api, *, portal_role="owner", cliente_id="demo"):
    """Sesión de portal real: la cookie es Secure, así que se entra por HTTPS."""
    email = "panel-" + uuid.uuid4().hex[:10] + "@example.com"
    api._create_user(email=email, password="prueba-atencion-123", role="client",
                     display_name="Panel", cliente_id=cliente_id, portal_role=portal_role)
    sesion = TestClient(api.app, base_url="https://testserver")
    login = sesion.post("/auth/login", json={"email": email, "password": "prueba-atencion-123"})
    assert login.status_code == 200, login.text
    return sesion


def _pausar_desde_el_panel(sesion, motivo="cierre_temporada"):
    version = sesion.get("/auth/app/attention").json()["version"]
    return sesion.put("/auth/app/attention", json={
        "estado": "pausada", "version_esperada": version, "motivo": motivo})


def test_el_panel_cuenta_que_se_para_y_que_no(api):
    sesion = _portal(api)
    datos = sesion.get("/auth/app/attention").json()

    assert datos["estado"] == "activa"
    assert datos["puede_cambiarlo"] is True
    assert datos["se_para"] and datos["sigue_igual"], datos
    assert any("WhatsApp" in linea for linea in datos["se_para"])
    assert any("mano" in linea for linea in datos["sigue_igual"])
    assert "plan" in datos["nota_facturacion"]
    claves = [m["clave"] for m in datos["motivos"]]
    assert "cierre_temporada" in claves, claves


def test_al_pulsarlo_el_asistente_se_calla_y_al_volver_contesta(api):
    """La prueba de verdad del interruptor: que el chat deje de contestar."""
    sesion = _portal(api)
    publico = TestClient(api.app)
    # El widget llama desde la web del negocio; sin Origin permitido el chat ni
    # siquiera llega a preguntar por la atencion.
    publico.headers.update({"Origin": "http://testserver"})
    pregunta = {"cliente_id": "demo", "session_id": "ses_" + uuid.uuid4().hex[:12],
                "mensaje": "hola"}

    antes = publico.post("/chat", json=pregunta)
    assert antes.status_code == 200, antes.text

    respuesta = _pausar_desde_el_panel(sesion)
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["estado"] == "pausada"
    assert cuerpo["motivo"] == "cierre_temporada"
    assert cuerpo["desde"], "una pausa sin fecha no se puede explicar despues"

    durante = publico.post("/chat", json=pregunta)
    assert durante.status_code == 409, (
        "el chat sigue contestando despues de pulsar la pausa: %s" % durante.status_code)
    assert durante.json()["detail"]["code"] == "ATTENTION_STOPPED"

    reactivada = sesion.put("/auth/app/attention", json={
        "estado": "activa", "version_esperada": cuerpo["version"], "motivo": "reapertura"})
    assert reactivada.status_code == 200, reactivada.text
    assert reactivada.json()["estado"] == "activa"
    assert publico.post("/chat", json=pregunta).status_code == 200, (
        "tras reactivar, el asistente tiene que volver entero")


def test_pausar_no_toca_el_plan_ni_los_cobros(api):
    """Pausar dos semanas por obras no puede parecerse a darse de baja."""
    from backend import appstate, db

    def _foto_de_facturacion():
        cfg = appstate.CONFIG_CLIENTES.get("demo") or {}
        with db._get_db_connection() as conexion:
            filas = conexion.execute(
                "SELECT COUNT(*) FROM client_channel_audit WHERE cliente_id='demo' "
                "AND channel != 'atencion'").fetchone()[0]
        return (cfg.get("plan"), dict(cfg.get("subscription") or {}), filas)

    sesion = _portal(api)
    antes = _foto_de_facturacion()
    assert _pausar_desde_el_panel(sesion, motivo="obras").status_code == 200
    assert _foto_de_facturacion() == antes, (
        "la pausa ha tocado el plan, la suscripcion o el diario de otro canal")


def test_la_version_vieja_no_pisa_la_decision_de_otro(api):
    """Dos pestañas abiertas: la segunda relee en vez de deshacer la primera."""
    sesion = _portal(api)
    version_vieja = sesion.get("/auth/app/attention").json()["version"]
    assert _pausar_desde_el_panel(sesion).status_code == 200

    tarde = sesion.put("/auth/app/attention", json={
        "estado": "activa", "version_esperada": version_vieja, "motivo": "reapertura"})
    assert tarde.status_code == 409, tarde.text
    assert tarde.json()["detail"]["code"] == "ATTENTION_STALE"
    assert sesion.get("/auth/app/attention").json()["estado"] == "pausada", (
        "una peticion con version vieja ha reactivado el negocio")


def test_quien_no_lleva_los_canales_lo_ve_pero_no_lo_toca(api):
    """Callar el negocio entero no es una accion de mostrador."""
    sesion = _portal(api, portal_role="staff")
    datos = sesion.get("/auth/app/attention").json()
    assert datos["estado"] == "activa"
    assert datos["puede_cambiarlo"] is False, "el panel le ofreceria un boton que no puede usar"

    intento = sesion.put("/auth/app/attention", json={
        "estado": "pausada", "version_esperada": datos["version"], "motivo": "vacaciones"})
    assert intento.status_code == 403, intento.text
    from backend import atencion

    assert atencion.leer_atencion("demo")["estado"] == "activa"


def test_un_motivo_inventado_no_rompe_ni_se_guarda_tal_cual(api):
    """La autoridad rechaza texto libre; el panel lo traduce en vez de reventar."""
    from backend import atencion

    sesion = _portal(api)
    version = sesion.get("/auth/app/attention").json()["version"]
    respuesta = sesion.put("/auth/app/attention", json={
        "estado": "pausada", "version_esperada": version,
        "motivo": "porque lo dice Marta <script>"})
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["motivo"] == "decision_del_negocio"
    assert atencion.leer_atencion("demo")["motivo"] == "decision_del_negocio"


def test_queda_quien_lo_hizo_y_cuando(api):
    """Si un negocio dice «yo no he sido», tiene que poder mirarse."""
    from backend import db

    sesion = _portal(api)
    correo = sesion.get("/auth/me").json()["email"]
    with db._get_db_connection() as conexion:
        mi_id = conexion.execute(
            "SELECT id FROM users WHERE email = ?", (correo,)).fetchone()[0]
    assert _pausar_desde_el_panel(sesion, motivo="vacaciones").status_code == 200
    with db._get_db_connection() as conexion:
        fila = conexion.execute(
            "SELECT detail, created_at FROM client_channel_audit WHERE cliente_id='demo' "
            "AND channel='atencion' ORDER BY id DESC LIMIT 1").fetchone()
    assert fila is not None, "una pausa sin rastro en el diario"
    assert '"estado": "pausada"' in fila["detail"]
    assert '"motivo": "vacaciones"' in fila["detail"]
    assert mi_id and mi_id in fila["detail"], (
        "el diario no dice quien la pulso: %s" % fila["detail"])


# ─── Lo que el panel ensena ────────────────────────────────────────────────

def _app_ui():
    from pathlib import Path

    return Path(__file__).resolve().parents[1].joinpath("app_ui", "index.html").read_text(
        encoding="utf-8")


def test_el_panel_tiene_el_interruptor_y_el_aviso_permanente(api):
    """El aviso va FUERA de la pestana Cuenta: si alguien se deja la pausa
    puesta, tiene que verlo este donde este, no solo si entra a buscarla."""
    html = _app_ui()

    assert 'id="atencionBlock"' in html
    assert 'id="atencionToggleBtn"' in html
    assert 'data-perm="channels.manage"' in html, (
        "el boton no esta gateado por el mismo permiso que exige el backend")
    assert 'id="atencionBanner"' in html
    assert html.index('id="atencionBanner"') < html.index('id="page-cuenta"'), (
        "el aviso esta dentro de la pestana Cuenta: no se veria desde el resto del panel")
    assert "loadAtencion()" in html.split("if (tab === 'cuenta')")[1][:200]
    assert html.count("loadAtencion();") >= 2, "no se carga al arrancar el panel"


# ─── Lectura administrativa ────────────────────────────────────────────────

def test_el_admin_ve_quien_esta_en_pausa_pero_no_lo_cambia(api):
    """Desde aqui no se pausa a nadie: el interruptor es del negocio. Hacerlo
    por ellos sin que lo sepan seria peor que el problema que resuelve."""
    from starlette.testclient import TestClient as _TC

    admin = _TC(api.app)
    cabecera = {"Authorization": "Bearer test-admin-token"}
    antes = admin.get("/admin/attention", headers=cabecera)
    assert antes.status_code == 200, antes.text
    assert [n for n in antes.json()["no_activos"] if n["cliente_id"] == "demo"] == []

    _pausar_desde_el_panel(_portal(api), motivo="obras")
    despues = admin.get("/admin/attention", headers=cabecera).json()
    fila = [n for n in despues["no_activos"] if n["cliente_id"] == "demo"]
    assert fila and fila[0]["estado"] == "pausada" and fila[0]["motivo"] == "obras", despues
    assert despues["total_negocios"] >= 1

    assert admin.get("/admin/attention").status_code in (401, 403), (
        "la lista de negocios pausados no puede leerse sin el token de admin")
    assert admin.put("/admin/attention", headers=cabecera,
                     json={"estado": "activa"}).status_code == 405, (
        "el admin no debe poder cambiar el estado de un negocio desde aqui")
