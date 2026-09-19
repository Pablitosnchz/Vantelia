"""La admisión es un hecho duradero: solo su ganador puede iniciar una red."""
import concurrent.futures
from contextlib import closing
from datetime import datetime, timedelta, timezone
import importlib
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from test_atencion_persistida import autoridad_atencion  # noqa: F401


@pytest.fixture
def operaciones_atencion(autoridad_atencion, monkeypatch):
    from backend import atencion_operaciones, timeutils

    autoridad, db, settings = autoridad_atencion
    reloj = {"ahora": datetime(2026, 9, 19, 12, 0, 0, 100000, tzinfo=timezone.utc)}
    monkeypatch.setattr(timeutils, "_utc_now", lambda: reloj["ahora"])
    return SimpleNamespace(op=atencion_operaciones, autoridad=autoridad, db=db,
                           settings=settings, reloj=reloj)


def _crear_ticket_prueba(a, evento="evento_1", tenant="negocio_es", instante=None, vence=None):
    ahora = a.reloj["ahora"]
    return a.op.crear_ticket_atencion(tenant, evento,
        event_at=(instante or ahora).isoformat(),
        expires_at=(vence or ahora + timedelta(minutes=10)).isoformat())


def _admitir_prueba(a, ticket, *, tenant=None, canal="whatsapp", fragmento=0, payload=b"respuesta"):
    return a.op.admitir_envio_atencion(tenant or ticket["cliente_id"], ticket["ticket_id"],
                                     canal, fragmento, payload=payload)


def _cambiar_prueba(a, estado, version):
    return a.autoridad.cambiar_atencion("negocio_es", estado,
        version_esperada=version, motivo="temporada", actor="sistema")


def _resultado_prueba(a, envio, resultado, **overrides):
    args = {"cliente_id": envio["cliente_id"], "ticket_id": envio["ticket_id"],
            "canal": envio["canal"], "fragmento": envio["fragmento"],
            "owner_token": envio["owner_token"], "resultado": resultado}
    args.update(overrides)
    return a.op.registrar_resultado_atencion(**args)


def test_ticket_captura_estado_sin_renovar_evento_ni_vigencia(operaciones_atencion):
    a = operaciones_atencion
    original = _crear_ticket_prueba(a)
    assert original["version"] == 0 and original["puede_preparar"]
    a.reloj["ahora"] += timedelta(minutes=1)
    repetido = a.op.crear_ticket_atencion("negocio_es", "evento_1",
        event_at=original["event_at"], expires_at=original["expires_at"])
    assert repetido == original
    with pytest.raises(a.op.AtencionIdentidadEnConflicto):
        _crear_ticket_prueba(a)
    assert a.op.consultar_envios_atencion("negocio_es") == []


def test_tenant_ajeno_no_puede_admitir_leer_ni_finalizar_ticket(operaciones_atencion):
    a = operaciones_atencion
    ticket = _crear_ticket_prueba(a)
    otro = _crear_ticket_prueba(a, tenant="negocio_en")
    assert otro["ticket_id"] != ticket["ticket_id"]
    with pytest.raises(a.op.AtencionOperacionNoEncontrada):
        _admitir_prueba(a, ticket, tenant="negocio_en")
    with pytest.raises(a.op.AtencionOperacionNoEncontrada):
        a.op.consultar_envios_atencion("negocio_en", ticket_id=ticket["ticket_id"])
    admitido = _admitir_prueba(a, ticket)
    with pytest.raises(a.op.AtencionOperacionNoEncontrada):
        _resultado_prueba(a, admitido, "aceptado", cliente_id="negocio_en")
    assert a.op.consultar_envios_atencion("negocio_en") == []
    assert _admitir_prueba(a, otro)["ejecutar_red"]


def test_ticket_suprimido_en_pausa_no_revive_despues(operaciones_atencion):
    a = operaciones_atencion
    _cambiar_prueba(a, "pausada", 0)
    a.reloj["ahora"] += timedelta(microseconds=1)
    ticket = _crear_ticket_prueba(a)
    assert not ticket["puede_preparar"] and ticket["motivo"] == "pausada"
    a.reloj["ahora"] += timedelta(seconds=1)
    _cambiar_prueba(a, "activa", 1)
    repetido = a.op.crear_ticket_atencion("negocio_es", "evento_1",
        event_at=ticket["event_at"], expires_at=ticket["expires_at"])
    assert repetido == ticket
    envio = _admitir_prueba(a, ticket)
    assert not envio["ejecutar_red"] and envio["estado"] == "suprimido"
    assert envio["motivo"] == "pausada" and "owner_token" not in envio


def test_pausa_reactivacion_invalida_ticket_preparado_y_evento_con_id_nuevo(operaciones_atencion):
    a = operaciones_atencion
    ticket = _crear_ticket_prueba(a)
    anterior = a.reloj["ahora"]
    _cambiar_prueba(a, "pausada", 0)
    # Dentro del MISMO segundo: truncar la fecha de transición lo rejuvenecería.
    a.reloj["ahora"] += timedelta(microseconds=1)
    _cambiar_prueba(a, "activa", 1)
    envio = _admitir_prueba(a, ticket)
    assert not envio["ejecutar_red"] and envio["motivo"] == "version_obsoleta"
    viejo = _crear_ticket_prueba(a, "evento_con_id_nuevo", instante=anterior)
    assert not viejo["puede_preparar"] and viejo["motivo"] == "evento_anterior"
    a.reloj["ahora"] += timedelta(microseconds=1)
    nuevo = _crear_ticket_prueba(a, "evento_nuevo")
    assert nuevo["puede_preparar"] and nuevo["version"] == 2
    assert _admitir_prueba(a, nuevo)["ejecutar_red"]


def test_vencimiento_exacto_se_suprime_y_no_reabre_por_reloj_o_id_repetido(operaciones_atencion):
    a = operaciones_atencion
    inicio = a.reloj["ahora"]
    ticket = _crear_ticket_prueba(a, vence=inicio + timedelta(microseconds=1))
    a.reloj["ahora"] += timedelta(microseconds=1)
    envio = _admitir_prueba(a, ticket)
    assert envio["motivo"] == "vencido" and not envio["ejecutar_red"]
    a.reloj["ahora"] = inicio
    repetido = a.op.crear_ticket_atencion("negocio_es", "evento_1",
        event_at=ticket["event_at"], expires_at=ticket["expires_at"])
    assert not repetido["puede_preparar"] and repetido["motivo"] == "vencido"
    assert not _admitir_prueba(a, ticket, fragmento=1)["ejecutar_red"]


def test_version_invalida_ticket_aunque_pausa_y_reactivacion_compartan_instante(operaciones_atencion):
    a = operaciones_atencion
    ticket = _crear_ticket_prueba(a)
    _cambiar_prueba(a, "pausada", 0)
    _cambiar_prueba(a, "activa", 1)
    envio = _admitir_prueba(a, ticket)
    assert not envio["ejecutar_red"] and envio["motivo"] == "version_obsoleta"


def test_evento_sin_ticket_en_instante_reactivacion_no_acredita_posterioridad(operaciones_atencion):
    a = operaciones_atencion
    _cambiar_prueba(a, "pausada", 0)
    _cambiar_prueba(a, "activa", 1)
    ambiguo = _crear_ticket_prueba(a, "evento_sin_ticket_previo")
    assert not ambiguo["puede_preparar"] and ambiguo["motivo"] == "evento_anterior"
    a.reloj["ahora"] += timedelta(microseconds=1)
    posterior = _crear_ticket_prueba(a, "evento_posterior")
    assert posterior["puede_preparar"]
    assert _admitir_prueba(a, posterior)["ejecutar_red"]


def test_ticket_ya_vencido_no_admite_preparacion(operaciones_atencion):
    a = operaciones_atencion
    ticket = _crear_ticket_prueba(a, instante=a.reloj["ahora"] - timedelta(minutes=2),
                                vence=a.reloj["ahora"] - timedelta(minutes=1))
    assert ticket["motivo"] == "vencido" and not ticket["puede_preparar"]


def test_fragmentos_son_unicos_y_payload_diferente_es_conflicto(operaciones_atencion):
    a = operaciones_atencion
    ticket = _crear_ticket_prueba(a)
    primero = _admitir_prueba(a, ticket)
    assert primero["ejecutar_red"] and primero["estado"] == "en_transito"
    repetido = _admitir_prueba(a, ticket)
    assert not repetido["ejecutar_red"] and "owner_token" not in repetido
    with pytest.raises(a.op.AtencionIdentidadEnConflicto):
        _admitir_prueba(a, ticket, payload=b"otro contenido")
    segundo = _admitir_prueba(a, ticket, fragmento=1)
    assert segundo["ejecutar_red"] and segundo["owner_token"] != primero["owner_token"]
    _cambiar_prueba(a, "pausada", 0)
    assert not _admitir_prueba(a, ticket, fragmento=2)["ejecutar_red"]
    assert not _admitir_prueba(a, ticket, canal="email")["ejecutar_red"]
    diario = a.op.consultar_envios_atencion("negocio_es", ticket_id=ticket["ticket_id"])
    assert [e["estado"] for e in diario].count("en_transito") == 2
    assert all(not e["ejecutar_red"] and "owner_token" not in e for e in diario)
    assert all("payload" not in e for e in diario)


def test_dos_admisiones_simultaneas_solo_un_ganador(operaciones_atencion):
    a = operaciones_atencion
    ticket = _crear_ticket_prueba(a)
    preparados = threading.Barrier(2)

    def enviar():
        preparados.wait(timeout=10)
        return _admitir_prueba(a, ticket)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as workers:
        resultados = list(workers.map(lambda _: enviar(), range(2)))
    assert sum(e["ejecutar_red"] for e in resultados) == 1
    assert len(a.op.consultar_envios_atencion("negocio_es")) == 1
    # Después de retornar se puede tomar el lock de escritura: no queda una
    # transacción esperando a la red del ganador.
    with closing(a.db._get_db_connection()) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")


@pytest.mark.parametrize("primero", ["pausa", "admision"])
def test_cas_y_admision_comparten_transaccion_y_la_pausa_ve_el_transito(operaciones_atencion, monkeypatch, primero):
    a = operaciones_atencion
    ticket = _crear_ticket_prueba(a)
    dentro, liberar, segundo_iniciado = threading.Event(), threading.Event(), threading.Event()
    lectura_real = a.autoridad._leer_atencion_en_transaccion
    parar = {"pendiente": True}

    def lectura_con_puerta(connection, tenant):
        foto = lectura_real(connection, tenant)
        if parar["pendiente"]:
            parar["pendiente"] = False
            dentro.set()
            assert liberar.wait(timeout=10)
        return foto

    monkeypatch.setattr(a.autoridad, "_leer_atencion_en_transaccion", lectura_con_puerta)
    pausa = lambda: _cambiar_prueba(a, "pausada", 0)
    admision = lambda: _admitir_prueba(a, ticket)
    inicial, siguiente = (pausa, admision) if primero == "pausa" else (admision, pausa)

    def ejecutar_segundo():
        segundo_iniciado.set()
        return siguiente()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as workers:
        uno = workers.submit(inicial)
        assert dentro.wait(timeout=10)
        dos = workers.submit(ejecutar_segundo)
        assert segundo_iniciado.wait(timeout=10)
        liberar.set()
        resultados = [uno.result(timeout=15), dos.result(timeout=15)]
    envio = next(r for r in resultados if "ejecutar_red" in r)
    assert envio["ejecutar_red"] == (primero == "admision")
    diario = a.op.consultar_envios_atencion("negocio_es")
    assert diario[0]["estado"] == ("en_transito" if primero == "admision" else "suprimido")
    assert a.autoridad.leer_atencion("negocio_es")["estado"] == "pausada"
    if envio["ejecutar_red"]:
        assert _resultado_prueba(a, envio, "aceptado")["estado"] == "aceptado"


def test_caida_reinicio_y_resultado_incierto_no_liberan_reenvio(operaciones_atencion):
    a = operaciones_atencion
    ticket = _crear_ticket_prueba(a)
    envio = _admitir_prueba(a, ticket)
    importlib.reload(a.op)
    assert not _admitir_prueba(a, ticket)["ejecutar_red"]
    assert a.op.consultar_envios_atencion("negocio_es")[0]["estado"] == "en_transito"
    desconocido = _resultado_prueba(a, envio, "desconocido")
    assert desconocido["estado"] == "desconocido" and not desconocido["ejecutar_red"]
    a.reloj["ahora"] += timedelta(days=50)
    importlib.reload(a.op)
    assert not _admitir_prueba(a, ticket)["ejecutar_red"]
    assert a.op.consultar_envios_atencion("negocio_es")[0]["estado"] == "desconocido"
    # Reconciliar no es repetir transporte ni comprobar vigencia del trabajo.
    aceptado = _resultado_prueba(a, envio, "aceptado")
    assert aceptado["estado"] == "aceptado" and not aceptado["ejecutar_red"]


@pytest.mark.parametrize("conocido", ["aceptado", "rechazado"])
def test_resultado_idempotente_no_pierde_evidencia_ni_libera_identidad(operaciones_atencion, conocido):
    a = operaciones_atencion
    ticket = _crear_ticket_prueba(a)
    envio = _admitir_prueba(a, ticket)
    terminado = _resultado_prueba(a, envio, conocido)
    a.reloj["ahora"] += timedelta(seconds=1)
    assert _resultado_prueba(a, envio, conocido) == terminado
    assert _resultado_prueba(a, envio, "desconocido") == terminado
    with pytest.raises(a.op.AtencionIdentidadEnConflicto):
        _resultado_prueba(a, envio, "rechazado" if conocido == "aceptado" else "aceptado")
    assert not _admitir_prueba(a, ticket)["ejecutar_red"]


def test_resultado_exige_propietario_y_no_convierte_supresion_en_entrega(operaciones_atencion):
    a = operaciones_atencion
    ticket = _crear_ticket_prueba(a)
    envio = _admitir_prueba(a, ticket)
    with pytest.raises(a.op.AtencionPropietarioInvalido):
        _resultado_prueba(a, envio, "aceptado", owner_token="0" * 32)
    _cambiar_prueba(a, "pausada", 0)
    suprimido = _admitir_prueba(a, ticket, fragmento=1)
    with pytest.raises(a.op.AtencionPropietarioInvalido):
        a.op.registrar_resultado_atencion("negocio_es", ticket["ticket_id"], "whatsapp", 1,
                                         owner_token="0" * 32, resultado="aceptado")
    assert suprimido["estado"] == "suprimido"
    assert a.op.consultar_envios_atencion("negocio_es")[0]["estado"] == "en_transito"


@pytest.mark.parametrize("event_at,expires_at", [
    (None, "2026-09-19T13:00:00Z"), ("2026-09-19", "2026-09-19T13:00:00Z"),
    ("2026-09-19Z", "2026-09-19T13:00:00Z"),
    ("2026-09-19T12:00:00+01:00", "2026-09-19T13:00:00Z"),
    ("2026-09-19T12:00:00Z", "2026-09-19T12:00:00Z"),
    ("2026-09-19T13:00:00Z", "2026-09-19T14:00:00Z"),
    ("2026-09-19T12:00:00Z", "2026-09-19T13:00:00"),
])
def test_fechas_invalidas_no_crean_tickets(operaciones_atencion, event_at, expires_at):
    a = operaciones_atencion
    with pytest.raises(ValueError):
        a.op.crear_ticket_atencion("negocio_es", "evento", event_at=event_at, expires_at=expires_at)
    with closing(a.db._get_db_connection()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM client_attention_tickets").fetchone()[0] == 0


@pytest.mark.parametrize("cambio", [{"fragmento": True}, {"fragmento": -1}, {"fragmento": "0"},
                                  {"canal": "WhatsApp"}, {"canal": "humano libre"},
                                  {"payload": "texto"}, {"payload": bytearray(b"mutable")}])
def test_admision_invalida_no_es_un_bypass(operaciones_atencion, cambio):
    a = operaciones_atencion
    ticket = _crear_ticket_prueba(a)
    with pytest.raises(ValueError):
        _admitir_prueba(a, ticket, **cambio)
    assert a.op.consultar_envios_atencion("negocio_es") == []


@pytest.mark.parametrize("operacion", ["ticket", "admision"])
def test_autoridad_corrupta_bloquea_tickets_y_admisiones(operaciones_atencion, operacion):
    a = operaciones_atencion
    ticket = _crear_ticket_prueba(a)
    _cambiar_prueba(a, "pausada", 0)
    with closing(a.db._get_db_connection()) as connection, connection:
        connection.execute("PRAGMA ignore_check_constraints=ON")
        connection.execute("UPDATE client_attention_state SET estado='desconocido'")
    with pytest.raises(a.autoridad.AtencionNoDisponible):
        if operacion == "ticket":
            _crear_ticket_prueba(a, "otro")
        else:
            _admitir_prueba(a, ticket)
    assert a.op.consultar_envios_atencion("negocio_es") == []


@pytest.mark.parametrize("campo,valor", [("version", -1), ("event_at", "2026-09-19Z"),
    ("expires_at", "2020-01-01T00:00:00Z"), ("estado", "desconocido"), ("motivo", "pausada")])
def test_ticket_corrupto_no_admite_red(operaciones_atencion, campo, valor):
    a = operaciones_atencion
    ticket = _crear_ticket_prueba(a)
    with closing(a.db._get_db_connection()) as connection, connection:
        connection.execute("PRAGMA ignore_check_constraints=ON")
        connection.execute("UPDATE client_attention_tickets SET %s=?" % campo, (valor,))
    with pytest.raises(a.autoridad.AtencionNoDisponible):
        _admitir_prueba(a, ticket)


@pytest.mark.parametrize("campo,valor", [("estado", "otro"), ("owner_token", ""),
    ("payload_hash", "x" * 64), ("resultado_at", "2026-09-19T12:00:00Z")])
def test_admision_corrupta_no_renueva_ni_oculta_incertidumbre(operaciones_atencion, campo, valor):
    a = operaciones_atencion
    ticket = _crear_ticket_prueba(a)
    _admitir_prueba(a, ticket)
    with closing(a.db._get_db_connection()) as connection, connection:
        connection.execute("PRAGMA ignore_check_constraints=ON")
        connection.execute("UPDATE client_attention_operations SET %s=?" % campo, (valor,))
    with pytest.raises(a.autoridad.AtencionNoDisponible):
        _admitir_prueba(a, ticket)
    with pytest.raises(a.autoridad.AtencionNoDisponible):
        a.op.consultar_envios_atencion("negocio_es")


def test_fallo_al_registrar_supresion_revierte_ticket_y_envio_juntos(operaciones_atencion):
    a = operaciones_atencion
    ticket = _crear_ticket_prueba(a)
    _cambiar_prueba(a, "pausada", 0)
    with closing(a.db._get_db_connection()) as connection, connection:
        connection.execute("CREATE TRIGGER romper_admision BEFORE INSERT ON client_attention_operations "
                           "BEGIN SELECT RAISE(ABORT, 'fallo local'); END")
    with pytest.raises(a.autoridad.AtencionNoDisponible):
        _admitir_prueba(a, ticket)
    with closing(a.db._get_db_connection()) as connection:
        assert connection.execute("SELECT estado FROM client_attention_tickets").fetchone()[0] == "vigente"
    assert a.op.consultar_envios_atencion("negocio_es") == []


def test_fallo_al_guardar_resultado_conserva_transito_sin_reenviar(operaciones_atencion):
    a = operaciones_atencion
    ticket = _crear_ticket_prueba(a)
    envio = _admitir_prueba(a, ticket)
    with closing(a.db._get_db_connection()) as connection, connection:
        connection.execute("CREATE TRIGGER romper_resultado BEFORE UPDATE ON client_attention_operations "
                           "BEGIN SELECT RAISE(ABORT, 'fallo local'); END")
    with pytest.raises(a.autoridad.AtencionNoDisponible):
        _resultado_prueba(a, envio, "aceptado")
    assert a.op.consultar_envios_atencion("negocio_es")[0]["estado"] == "en_transito"
    assert not _admitir_prueba(a, ticket)["ejecutar_red"]


def test_error_db_y_tabla_ausente_nunca_dan_permiso(operaciones_atencion, monkeypatch):
    a = operaciones_atencion
    ticket = _crear_ticket_prueba(a)
    with closing(a.db._get_db_connection()) as connection, connection:
        connection.execute("DROP TABLE client_attention_operations")
    with pytest.raises(a.autoridad.AtencionNoDisponible):
        _admitir_prueba(a, ticket)

    def db_rota():
        raise sqlite3.OperationalError("no disponible")

    monkeypatch.setattr(a.db, "_get_db_connection", db_rota)
    with pytest.raises(a.autoridad.AtencionNoDisponible):
        _crear_ticket_prueba(a)
    with pytest.raises(a.autoridad.AtencionNoDisponible):
        a.op.consultar_envios_atencion("negocio_es")


def test_migracion_idempotente_conserva_tickets_y_transito(operaciones_atencion):
    a = operaciones_atencion
    ticket = _crear_ticket_prueba(a)
    envio = _admitir_prueba(a, ticket)
    a.db._init_database()
    importlib.reload(a.op)
    assert _crear_ticket_prueba(a) == ticket
    assert not _admitir_prueba(a, ticket)["ejecutar_red"]
    assert a.op.consultar_envios_atencion("negocio_es")[0]["estado"] == "en_transito"
    assert _resultado_prueba(a, envio, "aceptado")["estado"] == "aceptado"
