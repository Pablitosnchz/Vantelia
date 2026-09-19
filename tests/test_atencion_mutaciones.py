"""Una pausa detiene el turno por código y no permite repetir una mutación."""
import asyncio
import concurrent.futures
from contextlib import closing, contextmanager
from dataclasses import FrozenInstanceError
from datetime import timedelta
import json
import sqlite3
import sys
import threading
import types

import pytest

from test_atencion_operaciones import operaciones_atencion, _crear_ticket_prueba  # noqa: F401
from test_atencion_persistida import autoridad_atencion  # noqa: F401
from atencion_proceso_aislado import comprobar_intento_en_interprete_nuevo


@pytest.fixture
def nucleo_atencion(operaciones_atencion):
    from api_models import BookingUpdatePayload, PortalEmployeePayload
    from backend import agenda, booking

    a = operaciones_atencion
    persona = agenda._create_portal_employee("demo", PortalEmployeePayload(
        name="Profesional de prueba", day_start="09:00", day_end="10:00",
        slot_minutes=30, closed_weekdays=[], service_ids=[]), full_access=True)
    empleado = agenda._get_employee_row(persona.employee_id, cliente_id="demo")
    dia = (a.reloj["ahora"].date() + timedelta(days=7)).isoformat()
    a.datos = dict(employee_row=empleado, nombre="Ana Prueba", telefono="600111222",
        email="", servicio="", booking_date=dia, booking_time="09:00",
        source="test", send_confirmation=False)

    async def crear(**cambios):
        return await booking._create_booking_core("demo", **dict(a.datos, **cambios))

    async def mover(fila, **cambios):
        datos = dict(nombre=fila["nombre"], telefono=fila["telefono"], email=fila["email"],
            servicio=fila["servicio"], employee_id=fila["employee_id"], fecha=dia, hora="09:30")
        return await booking._update_booking_details(fila, BookingUpdatePayload(**dict(datos, **cambios)),
                                                    None, source="test")

    a.crear, a.mover = crear, mover
    return a


def _pausa_nucleo_prueba(a, estado="pausada", version=0):
    return a.autoridad.cambiar_atencion("demo", estado, version_esperada=version,
        motivo="temporada", actor="sistema")


def test_sin_contexto_recuperacion_pendiente_precede_disponibilidad(nucleo_atencion):
    from backend import booking_operations
    from fastapi import HTTPException

    a = nucleo_atencion
    asyncio.run(a.crear())  # El hueco se ocupa después de quedar pendiente la otra operación.
    huella = booking_operations.booking_creation_fingerprint(**dict(
        (k, v) for k, v in a.datos.items() if k != "send_confirmation"), notas="")
    booking_operations.claim_creation_operation("demo", "pendiente", huella, "bk_pendiente")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(a.crear(operation_key="pendiente"))
    assert isinstance(exc.value.detail, dict) and exc.value.detail["code"] == "OPERATION_PENDING"


@pytest.mark.parametrize("accion", ["crear", "cancelar"])
def test_fallo_del_diario_tras_persistir_no_interrumpe_pago_ni_politica(nucleo_atencion, monkeypatch, accion):
    from backend import atencion_contexto, booking

    a = nucleo_atencion
    fila = asyncio.run(a.crear()) if accion == "cancelar" else None
    ticket = _crear_ticket_prueba(a, tenant="demo")
    continuaciones = []
    if accion == "crear":
        monkeypatch.setattr(booking, "_booking_payment_after_store", lambda *args, **kw: continuaciones.append("pago"))
    else:
        monkeypatch.setattr(booking, "apply_cancellation_policy", lambda *args, **kw: continuaciones.append("politica"))
    # Falla solo la escritura del diario: la reserva y sus pasos siguen disponibles.
    with closing(a.db._get_db_connection()) as conn, conn:
        conn.execute("CREATE TRIGGER romper_resultado BEFORE UPDATE ON client_attention_operations "
                     "BEGIN SELECT RAISE(ABORT, 'fallo de diario'); END")
    with atencion_contexto.turno_atencion("demo", ticket["ticket_id"], "intento_1"):
        if accion == "crear":
            resultado = asyncio.run(a.crear())
        else:
            resultado = asyncio.run(booking._cancel_booking_core(fila, source="test"))
    assert continuaciones == (["pago"] if accion == "crear" else ["politica"])
    assert resultado["status"] == ("confirmed" if accion == "crear" else "cancelled")
    assert a.op.consultar_operaciones_atencion("demo")[0]["estado"] == "en_transito"


def test_comprobacion_vencida_no_reabre_ticket_si_retrocede_el_reloj(operaciones_atencion):
    from backend import atencion_contexto

    a = operaciones_atencion
    inicio = a.reloj["ahora"]
    ticket = _crear_ticket_prueba(a, vence=inicio + timedelta(seconds=1))
    a.reloj["ahora"] += timedelta(seconds=1)
    with atencion_contexto.turno_atencion("negocio_es", ticket["ticket_id"], "crear_1"):
        with pytest.raises(atencion_contexto.AtencionDetenida):
            atencion_contexto.verificar_turno_atencion("negocio_es")
    a.reloj["ahora"] = inicio
    envio = a.op.admitir_envio_atencion("negocio_es", ticket["ticket_id"], "whatsapp", 0, payload=b"x")
    assert not envio["ejecutar_red"] and envio["motivo"] == "vencido"


def test_reserva_aceptada_exige_referencia_de_resultado(operaciones_atencion):
    a = operaciones_atencion
    ticket = _crear_ticket_prueba(a)
    op = a.op.admitir_operacion_atencion("negocio_es", ticket["ticket_id"],
        tipo="reserva", canal="crear", clave_intento="intento_1", payload=b"{}")
    with pytest.raises(ValueError):
        a.op.registrar_resultado_operacion_atencion("negocio_es", ticket["ticket_id"],
            tipo="reserva", canal="crear", clave_intento="intento_1",
            owner_token=op["owner_token"], resultado="aceptado")
    assert a.op.consultar_operaciones_atencion("negocio_es")[0]["estado"] == "en_transito"


def test_envio_no_admite_referencia_de_reserva_y_desconocido_no_borra_la_conocida(operaciones_atencion):
    a = operaciones_atencion
    ticket = _crear_ticket_prueba(a)
    envio = a.op.admitir_envio_atencion("negocio_es", ticket["ticket_id"], "whatsapp", 0, payload=b"x")
    with pytest.raises(ValueError):
        a.op.registrar_resultado_operacion_atencion("negocio_es", ticket["ticket_id"],
            tipo="envio", canal="whatsapp", owner_token=envio["owner_token"],
            resultado="aceptado", result_ref="bk_resultado")
    op = a.op.admitir_operacion_atencion("negocio_es", ticket["ticket_id"],
        tipo="reserva", canal="crear", clave_intento="intento_1", payload=b"{}")
    args = dict(tipo="reserva", canal="crear", clave_intento="intento_1", owner_token=op["owner_token"])
    aceptada = a.op.registrar_resultado_operacion_atencion("negocio_es", ticket["ticket_id"],
        **args, resultado="aceptado", result_ref="bk_resultado")
    assert a.op.registrar_resultado_operacion_atencion("negocio_es", ticket["ticket_id"],
        **args, resultado="desconocido") == aceptada
    assert a.op.consultar_envios_atencion("negocio_es")[0]["estado"] == "en_transito"


@pytest.mark.parametrize("referencia", [0, False, None])
@pytest.mark.parametrize("tipo,canal,clave", [("envio", "whatsapp", ""), ("reserva", "crear", "intento_1")])
def test_referencia_falsa_no_es_vacio_valido(operaciones_atencion, referencia, tipo, canal, clave):
    a = operaciones_atencion
    ticket = _crear_ticket_prueba(a)
    identidad = dict(tipo=tipo, canal=canal, clave_intento=clave)
    op = a.op.admitir_operacion_atencion("negocio_es", ticket["ticket_id"], **identidad, payload=b"{}")
    with pytest.raises(ValueError):
        a.op.registrar_resultado_operacion_atencion("negocio_es", ticket["ticket_id"],
            **identidad, owner_token=op["owner_token"], resultado="aceptado", result_ref=referencia)
    assert a.op.consultar_operaciones_atencion("negocio_es")[0]["estado"] == "en_transito"


@pytest.mark.parametrize("bloqueo", ["pausa", "vencimiento"])
def test_reintento_conocido_conserva_evidencia_aunque_el_ticket_ya_no_prepare(operaciones_atencion, bloqueo):
    from backend import atencion_contexto

    a = operaciones_atencion
    ticket = _crear_ticket_prueba(a)
    solicitud = {"booking_id": "bk_a"}
    with atencion_contexto.turno_atencion("negocio_es", ticket["ticket_id"], "intento_1"):
        with atencion_contexto.admitir_mutacion_atencion("negocio_es", "cancelar", solicitud):
            atencion_contexto.registrar_mutacion_conocida("negocio_es", "bk_a")
        if bloqueo == "pausa":
            a.autoridad.cambiar_atencion("negocio_es", "pausada", version_esperada=0,
                motivo="temporada", actor="sistema")
        else:
            a.reloj["ahora"] += timedelta(hours=1)
        with pytest.raises(atencion_contexto.AtencionDetenida) as detenido:
            atencion_contexto.comprobar_intento_mutacion_atencion("negocio_es", "cancelar", solicitud)
        assert (detenido.value.estado, detenido.value.result_ref) == ("aceptado", "bk_a")
        with pytest.raises(atencion_contexto.AtencionDetenida) as conflicto:
            atencion_contexto.comprobar_intento_mutacion_atencion("negocio_es", "cancelar", {"booking_id": "bk_b"})
        assert conflicto.value.motivo == "identidad_en_conflicto"


@pytest.mark.parametrize("concurrente", [False, True])
def test_identidad_reserva_es_unica_tambien_entre_tickets(operaciones_atencion, concurrente):
    a = operaciones_atencion
    tickets = [_crear_ticket_prueba(a, evento="evento_%s" % i) for i in range(2)]
    barrera = threading.Barrier(2)

    def admitir(ticket):
        if concurrente:
            barrera.wait(timeout=5)
        return a.op.admitir_operacion_atencion("negocio_es", ticket["ticket_id"],
            tipo="reserva", canal="crear", clave_intento="intento_1", payload=b"{}")

    if concurrente:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            resultados = list(pool.map(admitir, tickets))
    else:
        resultados = [admitir(ticket) for ticket in tickets]
    assert sum(r["ejecutar_operacion"] for r in resultados) == 1
    assert len(a.op.consultar_operaciones_atencion("negocio_es", tipo="reserva")) == 1
    with pytest.raises(a.op.AtencionIdentidadEnConflicto):
        a.op.admitir_operacion_atencion("negocio_es", tickets[1]["ticket_id"],
            tipo="reserva", canal="crear", clave_intento="intento_1", payload=b"otro")


def _invocacion_nucleo_prueba(a, accion):
    from backend import booking

    if accion == "crear":
        return a.crear, None, "_create_provider_booking"
    fila = asyncio.run(a.crear())
    if accion == "cancelar":
        async def cancelar():
            return await booking._cancel_booking_core(fila, source="test")
        return cancelar, fila, "_cancel_provider_booking"
    async def mover():
        return await a.mover(fila)
    return mover, fila, "_reschedule_provider_booking"


@pytest.mark.parametrize("accion", ["crear", "cancelar", "mover"])
@pytest.mark.parametrize("momento", ["antes", "preparando"])
def test_pausa_impide_primer_efecto_de_cada_nucleo(nucleo_atencion, monkeypatch, accion, momento):
    from backend import atencion_contexto, booking

    a = nucleo_atencion
    ejecutar, fila, proveedor = _invocacion_nucleo_prueba(a, accion)
    ticket = _crear_ticket_prueba(a, tenant="demo")
    with closing(a.db._get_db_connection()) as conn:
        antes = [tuple(r) for r in conn.execute("SELECT * FROM bookings")]
    efectos = []
    async def prohibido(*args, **kwargs):
        efectos.append("proveedor")
        raise AssertionError("La pausa debe preceder al proveedor")
    monkeypatch.setattr(booking, proveedor, prohibido)
    if momento == "antes":
        _pausa_nucleo_prueba(a)
    elif accion in ("crear", "mover"):
        from backend import agenda
        modulo = booking if accion == "crear" else agenda
        nombre = "_prepare_booking_creation" if accion == "crear" else "_booking_slot_available_for_reschedule"
        preparar = getattr(modulo, nombre)
        async def pausar_en_preparacion(*args, **kwargs):
            preparado = await preparar(*args, **kwargs)
            await asyncio.sleep(0)
            _pausa_nucleo_prueba(a)
            return preparado
        monkeypatch.setattr(modulo, nombre, pausar_en_preparacion)
    else:
        original = atencion_contexto.admitir_mutacion_atencion
        @contextmanager
        def pausar_tras_preparar(*args, **kwargs):
            _pausa_nucleo_prueba(a)
            with original(*args, **kwargs) as permiso:
                yield permiso
        monkeypatch.setattr(atencion_contexto, "admitir_mutacion_atencion", pausar_tras_preparar)
    with atencion_contexto.turno_atencion("demo", ticket["ticket_id"], "intento_1"):
        with pytest.raises(atencion_contexto.AtencionDetenida):
            asyncio.run(ejecutar())
    assert efectos == []
    with closing(a.db._get_db_connection()) as conn:
        assert [tuple(r) for r in conn.execute("SELECT * FROM bookings")] == antes
        assert conn.execute("SELECT COUNT(*) FROM booking_operations").fetchone()[0] == 0


@pytest.mark.parametrize("accion", ["crear", "cancelar", "mover"])
@pytest.mark.parametrize("fallo_auxiliar", [False, True])
def test_ganadora_termina_y_conserva_evidencia_tras_pausa_o_fallo_auxiliar(
        nucleo_atencion, monkeypatch, accion, fallo_auxiliar):
    from backend import atencion_contexto, booking

    a = nucleo_atencion
    ejecutar, fila, proveedor = _invocacion_nucleo_prueba(a, accion)
    ticket = _crear_ticket_prueba(a, tenant="demo")
    efectos = []
    original = getattr(booking, proveedor)
    async def efecto_admitido(*args, **kwargs):
        efectos.append("proveedor")
        assert a.op.consultar_operaciones_atencion("demo")[0]["estado"] == "en_transito"
        _pausa_nucleo_prueba(a)
        return await original(*args, **kwargs)
    monkeypatch.setattr(booking, proveedor, efecto_admitido)
    if fallo_auxiliar:
        def caer(*args, **kwargs):
            raise RuntimeError("fallo auxiliar tras persistir")
        monkeypatch.setattr(booking, "_record_booking_audit", caer)
    with atencion_contexto.turno_atencion("demo", ticket["ticket_id"], "intento_1"):
        if fallo_auxiliar:
            with pytest.raises(RuntimeError, match="fallo auxiliar"):
                asyncio.run(ejecutar())
        elif accion in ("cancelar", "mover"):
            # Fase 2c: el ganador termina, pero su aviso requiere un permiso
            # independiente. El control terminal de ese aviso llega al adaptador.
            with pytest.raises(atencion_contexto.AtencionDetenida) as aviso:
                asyncio.run(ejecutar())
            assert aviso.value.estado == "suprimido"
            assert aviso.value.operacion_conocida == {
                "tipo": "reserva", "estado": "aceptado", "result_ref": fila["id"]}
        else:
            asyncio.run(ejecutar())
        diario = a.op.consultar_operaciones_atencion("demo")[0]
        assert diario["estado"] == "aceptado" and diario["result_ref"].startswith("bk_")
        # La consulta previa atraviesa el núcleo real, con el ticket ahora pausado.
        with pytest.raises(atencion_contexto.AtencionDetenida) as repetida:
            asyncio.run(ejecutar())
        assert (repetida.value.estado, repetida.value.result_ref) == ("aceptado", diario["result_ref"])
    assert efectos == ["proveedor"]
    assert a.op.consultar_envios_atencion("demo") == []


def test_crear_con_otro_ticket_no_repite_y_duracion_manual_distinta_es_conflicto(nucleo_atencion):
    from backend import atencion_contexto

    a = nucleo_atencion
    primero = _crear_ticket_prueba(a, tenant="demo")
    with atencion_contexto.turno_atencion("demo", primero["ticket_id"], "intento_1"):
        fila = asyncio.run(a.crear())
    segundo = _crear_ticket_prueba(a, tenant="demo", evento="otro")
    with atencion_contexto.turno_atencion("demo", segundo["ticket_id"], "intento_1"):
        with pytest.raises(atencion_contexto.AtencionDetenida) as repetida:
            asyncio.run(a.crear())
        assert repetida.value.result_ref == fila["id"] and repetida.value.estado == "aceptado"
        with pytest.raises(atencion_contexto.AtencionDetenida) as conflicto:
            asyncio.run(a.crear(duracion_manual=15))
        assert conflicto.value.motivo == "identidad_en_conflicto"


def test_resultado_incierto_y_recarga_no_permiten_repetir(nucleo_atencion, monkeypatch):
    from backend import atencion_contexto, booking
    from fastapi import HTTPException

    a = nucleo_atencion
    ticket = _crear_ticket_prueba(a, tenant="demo")
    solicitudes = []
    comprobar_original = atencion_contexto.comprobar_intento_mutacion_atencion
    def capturar_solicitud(*args, **kwargs):
        solicitudes.append(args[2])
        return comprobar_original(*args, **kwargs)
    monkeypatch.setattr(atencion_contexto, "comprobar_intento_mutacion_atencion", capturar_solicitud)
    llamadas = []
    async def incierto(*args, **kwargs):
        llamadas.append(1)
        raise RuntimeError("proceso sin resultado")
    monkeypatch.setattr(booking, "_create_provider_booking", incierto)
    with atencion_contexto.turno_atencion("demo", ticket["ticket_id"], "intento_1"):
        with pytest.raises(HTTPException) as incierta:
            asyncio.run(a.crear())
        assert incierta.value.status_code == 503
    nuevo = _crear_ticket_prueba(a, tenant="demo", evento="nuevo")
    recuperada = comprobar_intento_en_interprete_nuevo(a.settings.DB_PATH, nuevo["ticket_id"],
        tipo="reserva", accion="crear", clave="intento_1", solicitud=solicitudes[0])
    assert recuperada == {"estado": "desconocido", "result_ref": ""}
    with atencion_contexto.turno_atencion("demo", nuevo["ticket_id"], "intento_1"):
        with pytest.raises(atencion_contexto.AtencionDetenida) as repetida:
            asyncio.run(a.crear())
    assert repetida.value.estado == "desconocido" and llamadas == [1]


def test_portal_sin_contexto_conserva_recorrido_y_source_no_otorga_excepcion(nucleo_atencion):
    from backend import atencion_contexto

    a = nucleo_atencion
    ticket = _crear_ticket_prueba(a, tenant="demo")
    _pausa_nucleo_prueba(a)
    with atencion_contexto.turno_atencion("demo", ticket["ticket_id"], "intento_1"):
        with pytest.raises(atencion_contexto.AtencionDetenida):
            asyncio.run(a.crear(source="portal"))
    fila = asyncio.run(a.crear(source="portal"))
    assert fila["status"] == "confirmed" and a.op.consultar_operaciones_atencion("demo") == []


def test_tenant_ajeno_no_prepara_ni_reclama(nucleo_atencion, monkeypatch):
    from backend import atencion_contexto, booking

    a = nucleo_atencion
    ticket = _crear_ticket_prueba(a, tenant="negocio_es")
    async def prohibido(*args, **kwargs):
        pytest.fail("El tenant ajeno no puede preparar")
    monkeypatch.setattr(booking, "_prepare_booking_creation", prohibido)
    with atencion_contexto.turno_atencion("negocio_es", ticket["ticket_id"], "intento_1"):
        with pytest.raises(atencion_contexto.AtencionDetenida) as detenido:
            asyncio.run(a.crear())
    assert detenido.value.motivo == "tenant_incorrecto"
    assert a.op.consultar_operaciones_atencion("demo") == []


@pytest.mark.parametrize("pausada", [True, False])
def test_claim_caducado_no_se_libera_sin_admision(nucleo_atencion, pausada):
    from backend import atencion_contexto, booking_operations, timeutils

    a = nucleo_atencion
    ticket = _crear_ticket_prueba(a, tenant="demo")
    booking_operations.claim_creation_operation("demo", "pendiente", "huella", "bk_pendiente")
    with closing(a.db._get_db_connection()) as conn, conn:
        conn.execute("UPDATE booking_operations SET created_at=?",
                     (timeutils._to_utc_iso(a.reloj["ahora"] - timedelta(hours=1)),))
    if pausada:
        _pausa_nucleo_prueba(a)
    with atencion_contexto.turno_atencion("demo", ticket["ticket_id"], "intento_1"):
        with pytest.raises(atencion_contexto.AtencionDetenida):
            booking_operations.recover_creation_operation("demo", "pendiente", "huella")
    with closing(a.db._get_db_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM booking_operations").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM booking_operation_audit").fetchone()[0] == 0


def test_migracion_conserva_envios_owners_y_tickets_sin_segundo_diario(operaciones_atencion):
    a = operaciones_atencion
    ticket = _crear_ticket_prueba(a)
    enviada = a.op.admitir_envio_atencion("negocio_es", ticket["ticket_id"], "whatsapp", 0, payload=b"x")
    with closing(a.db._get_db_connection()) as conn, conn:
        conn.execute("CREATE TABLE client_attention_sends AS SELECT cliente_id,ticket_id,canal,fragmento,"
            "payload_hash,estado,owner_token,motivo,created_at,resultado_at FROM client_attention_operations")
        conn.execute("DROP TABLE client_attention_operations")
    a.db._init_database()
    a.db._init_database()
    anterior = a.op.consultar_envios_atencion("negocio_es")[0]
    assert anterior["payload_hash"] == enviada["payload_hash"] and anterior["estado"] == "en_transito"
    assert anterior["ticket_id"] == ticket["ticket_id"] and not anterior["ejecutar_red"]
    assert "owner_token" not in anterior
    resultado = a.op.registrar_resultado_atencion("negocio_es", ticket["ticket_id"], "whatsapp", 0,
        owner_token=enviada["owner_token"], resultado="aceptado")
    assert resultado["estado"] == "aceptado"
    with closing(a.db._get_db_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='client_attention_sends'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM client_attention_tickets").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM client_attention_operations").fetchone()[0] == 1


def test_tipo_reserva_separa_identidad_y_error_de_escritura_es_atomico(operaciones_atencion):
    a = operaciones_atencion
    ticket = _crear_ticket_prueba(a)
    envio = a.op.admitir_envio_atencion("negocio_es", ticket["ticket_id"], "crear", 0, payload=b"x")
    assert envio["ejecutar_red"]
    with closing(a.db._get_db_connection()) as conn, conn:
        conn.execute("CREATE TRIGGER romper_reserva BEFORE INSERT ON client_attention_operations "
            "WHEN NEW.tipo='reserva' BEGIN SELECT RAISE(ABORT, 'fallo'); END")
    a.autoridad.cambiar_atencion("negocio_es", "pausada", version_esperada=0, motivo="temporada", actor="sistema")
    with pytest.raises(a.autoridad.AtencionNoDisponible):
        a.op.admitir_operacion_atencion("negocio_es", ticket["ticket_id"],
            tipo="reserva", canal="crear", clave_intento="intento_1", payload=b"{}")
    with closing(a.db._get_db_connection()) as conn:
        assert conn.execute("SELECT estado FROM client_attention_tickets").fetchone()[0] == "vigente"
    assert a.op.consultar_operaciones_atencion("negocio_es", tipo="reserva") == []
    assert a.op.consultar_envios_atencion("negocio_es")[0]["estado"] == "en_transito"


def test_pausa_reactiva_no_renueva_mutacion_y_evento_nuevo_no_cambia_version_vieja(nucleo_atencion):
    from backend import atencion_contexto

    a = nucleo_atencion
    ticket = _crear_ticket_prueba(a, tenant="demo")
    _pausa_nucleo_prueba(a)
    _pausa_nucleo_prueba(a, "activa", 1)
    with atencion_contexto.turno_atencion("demo", ticket["ticket_id"], "intento_1"):
        with pytest.raises(atencion_contexto.AtencionDetenida) as viejo:
            asyncio.run(a.crear())
    assert viejo.value.motivo == "version_obsoleta"
    fresco = _crear_ticket_prueba(a, tenant="demo", evento="nuevo")
    assert not fresco["puede_preparar"]  # Evento en el mismo instante de la pausa.
    with closing(a.db._get_db_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 0


def test_contexto_inmutable_aislado_y_restaurado_en_tareas_e_hilos(operaciones_atencion):
    from backend import atencion_contexto, timeutils

    a = operaciones_atencion
    tickets = [_crear_ticket_prueba(a, evento="evento_%s" % i) for i in range(2)]
    assert atencion_contexto.contexto_atencion_actual() is None
    async def tarea(i):
        with atencion_contexto.turno_atencion("negocio_es", tickets[i]["ticket_id"], "intento_%s" % i) as turno:
            with pytest.raises(FrozenInstanceError):
                turno.clave_intento = "otro"
            await asyncio.sleep(0)
            assert await timeutils._to_thread(atencion_contexto.contexto_atencion_actual) == turno
            with pytest.raises(RuntimeError):
                with atencion_contexto.turno_atencion("negocio_es", tickets[1-i]["ticket_id"], "anidado"):
                    raise RuntimeError("restaurar")
            assert atencion_contexto.contexto_atencion_actual() == turno
        return atencion_contexto.contexto_atencion_actual()
    async def juntas():
        return await asyncio.gather(tarea(0), tarea(1))
    assert asyncio.run(juntas()) == [None, None]
    assert atencion_contexto.contexto_atencion_actual() is None


@pytest.mark.parametrize("frontera", ["codigo_cancelar", "codigo_mover", "voz_cancelar", "voz_mover"])
def test_control_terminal_atraviesa_wrappers_y_dispatch_sin_respuesta(nucleo_atencion, frontera):
    from backend import atencion_contexto, booking, voice

    a = nucleo_atencion
    fila = asyncio.run(a.crear())
    ticket = _crear_ticket_prueba(a, tenant="demo")
    _pausa_nucleo_prueba(a)
    async def llamar():
        if frontera == "codigo_cancelar":
            return await booking._cancel_booking_by_code("demo", fila["booking_code"],
                trusted_phone="600111222", source="test")
        if frontera == "codigo_mover":
            return await booking._reschedule_booking_by_code("demo", fila["booking_code"],
                fila["booking_date"], "09:30", trusted_phone="600111222", source="test")
        return await voice._voice_dispatch_tool("demo",
            "cancelar_cita" if frontera == "voz_cancelar" else "reprogramar_cita",
            json.dumps({"codigo_reserva": fila["booking_code"], "fecha": fila["booking_date"], "hora": "09:30"}),
            from_number="600111222")
    with atencion_contexto.turno_atencion("demo", ticket["ticket_id"], "intento_1"):
        with pytest.raises(atencion_contexto.AtencionDetenida):
            asyncio.run(llamar())
    assert booking._load_booking_or_404(fila["id"])["status"] == "confirmed"


def test_agente_propaga_control_sin_segunda_llamada_ni_fallback(operaciones_atencion, monkeypatch):
    from backend import agent, atencion_contexto, reserva, settings

    estado = reserva.Estado()
    monkeypatch.setattr(reserva, "cargar", lambda *a: estado)
    monkeypatch.setattr(reserva, "guardar", lambda *a, **k: None)
    monkeypatch.setattr(agent, "_historial", lambda *a: [])
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "clave-falsa-sin-red")
    llamadas = []
    def modelo(**kwargs):
        llamadas.append(1)
        llamada = types.SimpleNamespace(id="unica", function=types.SimpleNamespace(
            name="consultar_disponibilidad", arguments="{}"))
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(
            content="", tool_calls=[llamada]))])
    modulo = types.ModuleType("openai")
    modulo.OpenAI = lambda **k: types.SimpleNamespace(chat=types.SimpleNamespace(
        completions=types.SimpleNamespace(create=modelo)))
    monkeypatch.setitem(sys.modules, "openai", modulo)
    detenido = atencion_contexto.AtencionDetenida("pausada")
    async def detener(*args, **kwargs):
        raise detenido
    monkeypatch.setattr(agent, "_ejecutar", detener)
    with pytest.raises(atencion_contexto.AtencionDetenida) as exc:
        asyncio.run(agent.responder("demo", "hola", session_id="control-terminal", telefono=""))
    assert exc.value is detenido and llamadas == [1]


@pytest.mark.parametrize("falla_diario", [False, True])
def test_claim_legacy_liberado_es_rechazo_conocido_sin_repetir(nucleo_atencion, monkeypatch, falla_diario):
    from backend import atencion_contexto, booking, booking_operations, timeutils
    from fastapi import HTTPException

    a = nucleo_atencion
    huella = booking_operations.booking_creation_fingerprint(**dict(
        (k, v) for k, v in a.datos.items() if k != "send_confirmation"), notas="")
    booking_operations.claim_creation_operation("demo", "legacy", huella, "bk_legacy")
    with closing(a.db._get_db_connection()) as conn, conn:
        conn.execute("UPDATE booking_operations SET created_at=?",
                     (timeutils._to_utc_iso(a.reloj["ahora"] - timedelta(hours=1)),))
    ticket = _crear_ticket_prueba(a, tenant="demo")
    if falla_diario:
        with closing(a.db._get_db_connection()) as conn, conn:
            conn.execute("CREATE TRIGGER romper_rechazo BEFORE UPDATE ON client_attention_operations "
                "BEGIN SELECT RAISE(ABORT, 'fallo diario'); END")
    async def prohibido(*args, **kwargs):
        pytest.fail("La liberación conocida no crea una reserva")
    monkeypatch.setattr(booking, "_create_provider_booking", prohibido)
    with atencion_contexto.turno_atencion("demo", ticket["ticket_id"], "intento_1"):
        with pytest.raises(HTTPException) as liberada:
            asyncio.run(a.crear(operation_key="legacy"))
        assert liberada.value.detail["code"] == "OPERATION_RELEASED"
        esperado = "en_transito" if falla_diario else "rechazado"
        assert a.op.consultar_operaciones_atencion("demo")[0]["estado"] == esperado
        with pytest.raises(atencion_contexto.AtencionDetenida) as repetida:
            asyncio.run(a.crear(operation_key="legacy"))
        assert repetida.value.estado == esperado
    with closing(a.db._get_db_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM booking_operations").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM booking_operation_audit").fetchone()[0] == 1


def test_dos_nucleos_preparados_con_tickets_distintos_solo_un_proveedor(nucleo_atencion, monkeypatch):
    from backend import atencion_contexto, booking

    a = nucleo_atencion
    tickets = [_crear_ticket_prueba(a, tenant="demo", evento="evento_%s" % i) for i in range(2)]
    preparar = booking._prepare_booking_creation
    proveedor = booking._create_provider_booking
    preparados, efectos = [], []
    async def carrera():
        ambos = asyncio.Event()
        async def preparar_ambos(*args, **kwargs):
            resultado = await preparar(*args, **kwargs)
            preparados.append(1)
            if len(preparados) == 2:
                ambos.set()
            await asyncio.wait_for(ambos.wait(), timeout=5)
            return resultado
        async def efecto_unico(*args, **kwargs):
            efectos.append(1)
            await asyncio.sleep(0)
            return await proveedor(*args, **kwargs)
        monkeypatch.setattr(booking, "_prepare_booking_creation", preparar_ambos)
        monkeypatch.setattr(booking, "_create_provider_booking", efecto_unico)
        async def intento(ticket):
            with atencion_contexto.turno_atencion("demo", ticket["ticket_id"], "intento_1"):
                return await a.crear()
        return await asyncio.gather(*(intento(t) for t in tickets), return_exceptions=True)
    resultados = asyncio.run(carrera())
    assert len(preparados) == 2 and efectos == [1]
    assert sum(isinstance(r, atencion_contexto.AtencionDetenida) for r in resultados) == 1
    assert len(a.op.consultar_operaciones_atencion("demo")) == 1
    assert a.op.consultar_operaciones_atencion("demo")[0]["estado"] == "aceptado"
    with closing(a.db._get_db_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 1


def test_error_db_al_comprobar_nunca_prepara(nucleo_atencion, monkeypatch):
    from backend import atencion_contexto, booking

    a = nucleo_atencion
    ticket = _crear_ticket_prueba(a, tenant="demo")
    async def prohibido(*args, **kwargs):
        pytest.fail("DB no verificable no permite preparar")
    def fallar():
        raise sqlite3.OperationalError("fallo de prueba")
    monkeypatch.setattr(booking, "_prepare_booking_creation", prohibido)
    monkeypatch.setattr(a.db, "_get_db_connection", fallar)
    with atencion_contexto.turno_atencion("demo", ticket["ticket_id"], "intento_1"):
        with pytest.raises(atencion_contexto.AtencionDetenida) as exc:
            asyncio.run(a.crear())
    assert exc.value.motivo == "atencion_no_verificable"


def test_resultado_aceptado_corrupto_no_se_oculta_en_repeticion(nucleo_atencion):
    from backend import atencion_contexto

    a = nucleo_atencion
    ticket = _crear_ticket_prueba(a, tenant="demo")
    with atencion_contexto.turno_atencion("demo", ticket["ticket_id"], "intento_1"):
        asyncio.run(a.crear())
        with closing(a.db._get_db_connection()) as conn, conn:
            conn.execute("UPDATE client_attention_operations SET result_ref=''")
        with pytest.raises(atencion_contexto.AtencionDetenida) as exc:
            asyncio.run(a.crear())
        assert exc.value.motivo == "atencion_no_verificable"


def test_cancelacion_de_tarea_restaura_contexto_y_no_libera_admision(nucleo_atencion, monkeypatch):
    from backend import atencion_contexto, booking

    a = nucleo_atencion
    ticket = _crear_ticket_prueba(a, tenant="demo")
    async def carrera():
        dentro = asyncio.Event()
        async def esperar(*args, **kwargs):
            dentro.set()
            await asyncio.Event().wait()
        monkeypatch.setattr(booking, "_create_provider_booking", esperar)
        async def ejecutar():
            with atencion_contexto.turno_atencion("demo", ticket["ticket_id"], "intento_1"):
                try:
                    await a.crear()
                finally:
                    assert atencion_contexto._MUTACION_ATENCION.get() is None
        tarea = asyncio.create_task(ejecutar())
        await asyncio.wait_for(dentro.wait(), timeout=5)
        tarea.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarea
    asyncio.run(carrera())
    assert atencion_contexto.contexto_atencion_actual() is None
    assert a.op.consultar_operaciones_atencion("demo")[0]["estado"] == "desconocido"
    with atencion_contexto.turno_atencion("demo", ticket["ticket_id"], "intento_1"):
        with pytest.raises(atencion_contexto.AtencionDetenida):
            asyncio.run(a.crear())
