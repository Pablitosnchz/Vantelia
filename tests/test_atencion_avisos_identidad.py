"""Un aviso persistido puede tener varios intentos; dos avisos no son el mismo."""
import asyncio
import concurrent.futures
from contextlib import closing
from dataclasses import FrozenInstanceError
from email import message_from_bytes
from email.message import EmailMessage
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading

import pytest

from test_atencion_operaciones import operaciones_atencion, _crear_ticket_prueba  # noqa: F401
from test_atencion_persistida import autoridad_atencion  # noqa: F401
from test_atencion_mutaciones import nucleo_atencion  # noqa: F401
from test_atencion_salidas import transporte_atencion  # noqa: F401
from test_ai_payment_link import _seed_booking, _seed_full_policy


@pytest.fixture
def avisos_identidad(transporte_atencion, monkeypatch):
    from types import SimpleNamespace
    from backend import agenda, booking, db, timeutils

    a = transporte_atencion
    runtime = SimpleNamespace(_utc_now_iso=timeutils._utc_now_iso,
        _store_booking=booking._store_booking, _get_db_connection=db._get_db_connection)
    a.filas = [booking._get_booking_row_by_id(_seed_booking(runtime, "aviso_%s" % i,
        source="test", email="destino@example.invalid", telefono="600111222")) for i in range(2)]
    monkeypatch.setattr(agenda, "_effective_followup_channels", lambda *args: {
        kind: {"email": True, "sms": False, "whatsapp": False}
        for kind in ("confirmed", "cancelled", "rescheduled", "reminder_24h")})
    monkeypatch.setattr(agenda, "_reminder_channel_availability", lambda *args: {
        "email": {"available": True}, "sms": {"available": False}})
    return a


def _datos_enviados_aviso(a):
    return [datos for tipo, datos in a.llamadas if tipo == "send"]


def _diario_avisos(a):
    return a.op.consultar_operaciones_atencion("demo", tipo="envio")


async def _avisar_fila(fila, kind="confirmed", *, entrada="reminder"):
    from backend import booking
    if entrada == "email":
        return await booking._send_booking_email_by_kind(fila, kind, respect_enabled=False)
    return await booking._send_booking_reminder_by_kind(fila, kind,
        channel_override={"email": True}, respect_enabled=False)


def test_cancelar_y_crear_en_un_turno_emite_ambos_avisos_y_task_hereda_ticket(
        avisos_identidad, nucleo_atencion):
    from backend import booking

    a = avisos_identidad
    anterior = asyncio.run(nucleo_atencion.crear(email="destino@example.invalid"))

    async def cancelar_y_crear():
        cancelada = await booking._cancel_booking_core(anterior, source="test")
        nueva = await nucleo_atencion.crear(email="destino@example.invalid")
        # La confirmación diferida de voz nace dentro del turno del tool.
        await asyncio.create_task(_avisar_fila(nueva))
        return cancelada, nueva

    with a.turno():
        cancelada, nueva = asyncio.run(cancelar_y_crear())
    assert cancelada["status"] == "cancelled" and nueva["status"] == "confirmed"
    assert cancelada["id"] != nueva["id"]
    assert len(_datos_enviados_aviso(a)) == 2
    diario = _diario_avisos(a)
    assert len(diario) == 2 and {r["estado"] for r in diario} == {"aceptado"}
    assert len({r["clave_intento"] for r in diario}) == 2
    assert {r["ticket_id"] for r in diario} == {a.ticket["ticket_id"]}


@pytest.mark.parametrize("entrada", ["reminder", "email"])
def test_mismo_aviso_en_otro_ticket_no_emite_y_mime_no_cambia(avisos_identidad, entrada):
    from backend import atencion_contexto

    a = avisos_identidad
    with a.turno():
        asyncio.run(_avisar_fila(a.filas[0], entrada=entrada))
    otro = _crear_ticket_prueba(a, evento="reentrega", tenant="demo")
    with atencion_contexto.turno_atencion("demo", otro["ticket_id"], "otro_intento"):
        with pytest.raises(atencion_contexto.AtencionDetenida) as exc:
            asyncio.run(_avisar_fila(a.filas[0], entrada=entrada))
    assert exc.value.estado == "aceptado" and exc.value.motivo != "identidad_en_conflicto"
    assert len(_datos_enviados_aviso(a)) == 1 and len(_diario_avisos(a)) == 1
    boundary = message_from_bytes(_datos_enviados_aviso(a)[0]).get_boundary()
    assert boundary and len(boundary) <= 70


def test_cambio_real_de_generacion_y_kind_son_avisos_distintos(avisos_identidad):
    from backend import booking

    a = avisos_identidad
    with a.turno():
        asyncio.run(_avisar_fila(a.filas[0]))
        with closing(a.db._get_db_connection()) as connection, connection:
            # La cita sigue confirmada y cambia de hora; este caso verifica la
            # identidad de los avisos, no ejecuta el núcleo de reprogramación.
            connection.execute("UPDATE bookings SET booking_time='10:30', "
                "start_at='2099-06-15T08:30:00+00:00', end_at='2099-06-15T09:00:00+00:00' WHERE id=?",
                (a.filas[0]["id"],))
        nueva = booking._get_booking_row_by_id(a.filas[0]["id"])
        assert nueva["reminder_generation"] > a.filas[0]["reminder_generation"]
        asyncio.run(_avisar_fila(nueva, "rescheduled"))
        asyncio.run(_avisar_fila(nueva, "confirmed"))
    assert len(_datos_enviados_aviso(a)) == 3
    assert len({r["clave_intento"] for r in _diario_avisos(a)}) == 3


@pytest.mark.parametrize("cambio", ["borrada", "obsoleta", "tenant"])
def test_fila_no_comprobable_no_recibe_generacion_inventada(avisos_identidad, cambio):
    from backend import atencion_contexto

    a = avisos_identidad
    with closing(a.db._get_db_connection()) as connection, connection:
        if cambio == "borrada":
            connection.execute("DELETE FROM bookings WHERE id=?", (a.filas[0]["id"],))
        elif cambio == "obsoleta":
            connection.execute("UPDATE bookings SET nombre='Cambio' WHERE id=?", (a.filas[0]["id"],))
        else:
            connection.execute("UPDATE bookings SET cliente_id='negocio_en' WHERE id=?", (a.filas[0]["id"],))
    with a.turno(), pytest.raises(atencion_contexto.AtencionDetenida):
        asyncio.run(_avisar_fila(a.filas[0]))
    assert a.llamadas == [] and _diario_avisos(a) == []


def test_fila_sin_campo_generacion_usa_la_persistida(avisos_identidad):
    a = avisos_identidad
    parcial = dict(a.filas[0])
    del parcial["reminder_generation"]
    with a.turno():
        asyncio.run(_avisar_fila(parcial, "cancelled"))
    assert len(_datos_enviados_aviso(a)) == 1 and len(_diario_avisos(a)[0]["clave_intento"]) == 64


def test_contextos_de_dos_tasks_y_hilos_no_mezclan_avisos(avisos_identidad):
    from backend import atencion_salidas, timeutils

    a = avisos_identidad
    barrera = threading.Barrier(2)
    def enviar(texto):
        barrera.wait(timeout=10)
        return a.enviar_email(texto)

    async def tarea(fila, texto):
        with atencion_salidas.aviso_reserva_atencion(fila, "confirmed"):
            return await timeutils._to_thread(enviar, texto)

    async def paralelo():
        return await asyncio.gather(*(asyncio.create_task(tarea(fila, str(i))) for i, fila in enumerate(a.filas)))

    with a.turno():
        assert asyncio.run(paralelo()) == ["client_smtp", "client_smtp"]
        # El llamador no hereda el aviso de ningún trabajador.
        a.enviar_email("salida general")
    assert len(_datos_enviados_aviso(a)) == 3
    assert len({r["clave_intento"] for r in _diario_avisos(a) if r["clave_intento"]}) == 2
    assert sum(r["clave_intento"] == "" for r in _diario_avisos(a)) == 1


def test_dos_workers_mismo_aviso_entre_tickets_solo_un_smtp(avisos_identidad):
    from backend import atencion_contexto, atencion_salidas

    a = avisos_identidad
    tickets = [a.ticket, _crear_ticket_prueba(a, evento="worker_2", tenant="demo")]
    barrera = threading.Barrier(2)
    def ejecutar(ticket):
        with atencion_contexto.turno_atencion("demo", ticket["ticket_id"], "worker"):
            with atencion_salidas.aviso_reserva_atencion(a.filas[0], "confirmed"):
                barrera.wait(timeout=10)
                try:
                    return a.enviar_email()
                except atencion_contexto.AtencionDetenida:
                    return "duplicado"
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(ejecutar, tickets)) == ["client_smtp", "duplicado"]
    assert len(_datos_enviados_aviso(a)) == 1 and len(_diario_avisos(a)) == 1


def test_excepcion_restaura_ambito_inmutable_y_no_transfiere_aviso_a_otro_turno(avisos_identidad):
    from backend import atencion_contexto, atencion_salidas

    a = avisos_identidad
    otro = _crear_ticket_prueba(a, evento="otro", tenant="demo")
    with a.turno():
        with pytest.raises(RuntimeError, match="preparacion"):
            with atencion_salidas.aviso_reserva_atencion(a.filas[0], "confirmed") as aviso:
                with pytest.raises(FrozenInstanceError):
                    aviso.clave_intento = "otra"
                with atencion_contexto.turno_atencion("demo", otro["ticket_id"], "otro"):
                    with pytest.raises(atencion_contexto.AtencionDetenida):
                        a.enviar_email()
                raise RuntimeError("preparacion")
        a.enviar_email()
    assert len(_diario_avisos(a)) == 1 and _diario_avisos(a)[0]["clave_intento"] == ""


def test_misma_identidad_con_otros_bytes_es_conflicto(avisos_identidad):
    from backend import atencion_contexto, atencion_salidas

    a = avisos_identidad
    with a.turno(), atencion_salidas.aviso_reserva_atencion(a.filas[0], "confirmed"):
        a.enviar_email("primero")
        with pytest.raises(atencion_contexto.AtencionDetenida) as exc:
            a.enviar_email("cambio de plantilla o pago")
    assert exc.value.motivo == "identidad_en_conflicto" and len(_datos_enviados_aviso(a)) == 1


def test_respuesta_perdida_no_repite_en_otro_ticket_y_siguiente_aviso_no_hereda_contexto(avisos_identidad):
    from backend import atencion_contexto

    a = avisos_identidad
    a.enviar_error = TimeoutError("respuesta perdida")
    with a.turno(), pytest.raises(atencion_contexto.AtencionDetenida) as primera:
        asyncio.run(_avisar_fila(a.filas[0]))
    assert primera.value.estado == "desconocido"
    otro = _crear_ticket_prueba(a, evento="reintento", tenant="demo")
    a.enviar_error = None
    with atencion_contexto.turno_atencion("demo", otro["ticket_id"], "reintento"):
        with pytest.raises(atencion_contexto.AtencionDetenida) as segunda:
            asyncio.run(_avisar_fila(a.filas[0]))
        assert segunda.value.estado == "desconocido" and segunda.value.motivo != "identidad_en_conflicto"
        asyncio.run(_avisar_fila(a.filas[1]))
    assert len(_datos_enviados_aviso(a)) == 2
    assert sorted(r["estado"] for r in _diario_avisos(a)) == ["aceptado", "desconocido"]


def test_pausa_no_hereda_permiso_de_mutacion_y_cada_fragmento_revalida(avisos_identidad):
    from backend import atencion_contexto, atencion_salidas

    a = avisos_identidad
    efectos = []
    with a.turno(), atencion_contexto.admitir_mutacion_atencion("demo", "crear", {"dato": 1}):
        with atencion_salidas.aviso_reserva_atencion(a.filas[0], "confirmed"):
            with atencion_salidas.salida_red_atencion("demo", "smtp_cliente", 0, b"primero") as permiso:
                efectos.append(0)
                atencion_salidas.registrar_salida_atencion(permiso, "aceptado")
            a.autoridad.cambiar_atencion("demo", "pausada", version_esperada=0,
                motivo="temporada", actor="sistema")
            with pytest.raises(atencion_contexto.AtencionDetenida):
                with atencion_salidas.salida_red_atencion("demo", "smtp_cliente", 1, b"segundo"):
                    efectos.append(1)
        with pytest.raises(atencion_contexto.AtencionDetenida):
            asyncio.run(_avisar_fila(a.filas[1]))
    assert efectos == [0]
    assert [(r["fragmento"], r["estado"]) for r in _diario_avisos(a)] == [(0, "aceptado"), (1, "suprimido")]


def test_tenant_ajeno_no_pasa_y_manual_repite_sin_diario(avisos_identidad):
    from backend import atencion_contexto, atencion_salidas

    a = avisos_identidad
    otra = dict(a.filas[0], cliente_id="negocio_en")
    with a.turno(), pytest.raises(atencion_contexto.AtencionDetenida):
        with atencion_salidas.aviso_reserva_atencion(otra, "confirmed"):
            a.enviar_email()
    a.autoridad.cambiar_atencion("demo", "pausada", version_esperada=0,
        motivo="temporada", actor="sistema")
    for _ in range(2):
        asyncio.run(_avisar_fila(a.filas[0]))
    assert len(_datos_enviados_aviso(a)) == 2 and _diario_avisos(a) == []


@pytest.mark.parametrize("canal", ["email", "sms"])
def test_pago_persistido_y_aviso_reserva_tienen_identidades_distintas(avisos_identidad, monkeypatch, canal):
    from types import SimpleNamespace
    import httpx
    from backend import booking, db, stripe_gateway, timeutils
    from test_atencion_salidas import _cliente_http_simulado_salida

    a = avisos_identidad
    _seed_full_policy(SimpleNamespace(_utc_now_iso=timeutils._utc_now_iso,
        _get_db_connection=db._get_db_connection))
    if canal == "sms":
        with closing(a.db._get_db_connection()) as connection, connection:
            connection.execute("UPDATE bookings SET source='voice' WHERE id=?", (a.filas[0]["id"],))
    fila = booking._get_booking_row_by_id(a.filas[0]["id"])
    monkeypatch.setattr(booking, "_connect_account_status", lambda *args, **kwargs:
        SimpleNamespace(connected=True, charges_enabled=True, stripe_account_id="acct_sintetica"))
    monkeypatch.setattr(booking, "_ai_payment_delivery_available", lambda *args: True)
    monkeypatch.setattr(stripe_gateway, "_stripe_init", lambda: None)
    checkouts, sms = [], []
    def checkout(**kwargs):
        checkouts.append(kwargs)
        return SimpleNamespace(id="cs_sintetico", url="https://checkout.invalid/pago")
    monkeypatch.setattr(stripe_gateway.stripe.checkout.Session, "create", checkout)
    def entregar(url, kwargs):
        sms.append(kwargs["content"])
        return httpx.Response(201, json={"sid": "sms_sintetico"}, request=httpx.Request("POST", url))
    _cliente_http_simulado_salida(monkeypatch, entregar)
    with a.turno():
        asyncio.run(_avisar_fila(a.filas[1]))
        resultado = asyncio.run(booking._ai_send_payment_link("demo", fila, base_url="https://widget.invalid"))
    assert resultado["ok"] and resultado["sent"] and resultado["method"] == canal
    assert len(checkouts) == 1
    assert len(_datos_enviados_aviso(a)) == (2 if canal == "email" else 1)
    assert len(sms) == (1 if canal == "sms" else 0)
    with closing(a.db._get_db_connection()) as connection:
        pagos = connection.execute("SELECT id FROM customer_payments WHERE cliente_id='demo'").fetchall()
    assert len(pagos) == 1 and pagos[0]["id"].startswith("pay_")
    diario = _diario_avisos(a)
    assert len(diario) == 2 and {r["estado"] for r in diario} == {"aceptado"}
    assert len({r["clave_intento"] for r in diario if r["clave_intento"]}) == 2
    assert a.op.consultar_operaciones_atencion("demo", tipo="pago")[0]["result_ref"] == pagos[0]["id"]


def test_indice_migrado_conserva_legacy_y_prohibe_mismo_aviso_en_otro_ticket(avisos_identidad):
    a = avisos_identidad
    otro = _crear_ticket_prueba(a, evento="legacy_2", tenant="demo")
    with closing(a.db._get_db_connection()) as connection, connection:
        connection.execute("DROP INDEX idx_attention_notice_attempt")
    # Ambos envíos sin ámbito de aviso conservan identidad por ticket.
    for ticket in (a.ticket, otro):
        admision = a.op.admitir_envio_atencion("demo", ticket["ticket_id"], "smtp_cliente", 0, payload=b"legacy")
        a.op.registrar_resultado_atencion("demo", ticket["ticket_id"], "smtp_cliente", 0,
            owner_token=admision["owner_token"], resultado="aceptado")
    antes = _diario_avisos(a)
    a.db._init_database()
    a.db._init_database()
    assert _diario_avisos(a) == antes
    clave = "a" * 64
    a.op.admitir_envio_atencion("demo", a.ticket["ticket_id"], "smtp_cliente", 0,
        payload=b"aviso", clave_intento=clave)
    with closing(a.db._get_db_connection()) as connection, connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO client_attention_operations "
                "SELECT cliente_id,?,tipo,canal,fragmento,clave_intento,payload_hash,request_hash,estado,"
                "owner_token,motivo,created_at,resultado_at,result_ref FROM client_attention_operations "
                "WHERE clave_intento=?", (otro["ticket_id"], clave))


def _mime_reinicio_aviso():
    mensaje = EmailMessage()
    mensaje["From"], mensaje["To"] = "origen@example.invalid", "destino@example.invalid"
    mensaje["Subject"] = "Aviso"
    mensaje.set_content("Aviso")
    mensaje.add_alternative("<p>Aviso</p>", subtype="html")
    return mensaje


def test_interprete_nuevo_no_repite_aviso_aceptado_con_otro_ticket(avisos_identidad):
    from backend import atencion_salidas

    a = avisos_identidad
    with a.turno(), atencion_salidas.aviso_reserva_atencion(a.filas[0], "confirmed"):
        payload = atencion_salidas.preparar_mime_atencion(_mime_reinicio_aviso(), "smtp_cliente")
        with atencion_salidas.salida_red_atencion("demo", "smtp_cliente", 0, payload) as permiso:
            atencion_salidas.registrar_salida_atencion(permiso, "aceptado")
    otro = _crear_ticket_prueba(a, evento="reinicio", tenant="demo")
    raiz = Path(__file__).resolve().parents[1]
    temporal = Path(a.settings.DB_PATH).resolve().parent
    entorno = {k: v for k, v in os.environ.items() if k.upper() in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP")}
    entorno.update(PYTHONPATH=str(raiz), PYTHONIOENCODING="utf-8", VANTELIA_DATA_DIR=str(temporal),
        VANTELIA_STORAGE_DIR=str(temporal), VANTELIA_CONFIG_PATH=str(temporal / "config_no_cargada.json"))
    codigo = """
import json, os, sys
from pathlib import Path
from email.message import EmailMessage
import dotenv
dotenv.load_dotenv = lambda *args, **kwargs: False
from backend import atencion_contexto, atencion_salidas, db, settings
settings.DB_PATH = Path(sys.argv[1])
with db._get_db_connection() as connection:
    fila = connection.execute('SELECT * FROM bookings WHERE id=?', (sys.argv[3],)).fetchone()
mensaje = EmailMessage()
mensaje['From'], mensaje['To'] = 'origen@example.invalid', 'destino@example.invalid'
mensaje['Subject'] = 'Aviso'
mensaje.set_content('Aviso')
mensaje.add_alternative('<p>Aviso</p>', subtype='html')
with atencion_contexto.turno_atencion('demo', sys.argv[2], 'reinicio'):
    with atencion_salidas.aviso_reserva_atencion(fila, 'confirmed'):
        payload = atencion_salidas.preparar_mime_atencion(mensaje, 'smtp_cliente')
        try:
            with atencion_salidas.salida_red_atencion('demo', 'smtp_cliente', 0, payload):
                raise AssertionError('Un replay no admite efecto')
        except atencion_contexto.AtencionDetenida as corte:
            assert corte.estado == 'aceptado' and corte.motivo != 'identidad_en_conflicto'
            estado = corte.estado
assert 'api' not in sys.modules and 'backend.main' not in sys.modules
print(json.dumps({'pid': os.getpid(), 'estado': estado}))
"""
    resultado = subprocess.run([sys.executable, "-c", codigo, str(a.settings.DB_PATH),
        otro["ticket_id"], a.filas[0]["id"]], cwd=str(temporal), env=entorno,
        capture_output=True, text=True, timeout=30, check=True)
    respuesta = json.loads(resultado.stdout)
    assert respuesta["pid"] != os.getpid() and respuesta["estado"] == "aceptado"
    assert len(_diario_avisos(a)) == 1
