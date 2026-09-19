"""Binding demo, autoridad y diario comparten el mismo commit SQLite."""
import concurrent.futures
from contextlib import closing
from datetime import timedelta
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


@pytest.fixture
def demo_application(operaciones_atencion):
    from backend import wa_demo

    a = operaciones_atencion
    a.wa = wa_demo
    with closing(a.db._get_db_connection()) as conn, conn:
        conn.executemany(
            """INSERT INTO wa_demo_codes
               (code,cliente_id,active,expires_at,uses,created_at)
               VALUES (?,?,1,'2099-01-01T00:00:00Z',0,'2026-09-19T00:00:00Z')""",
            [("SAL234", "negocio_es"), ("HOT456", "negocio_en")],
        )
    return a


def _wa1_query(a, code="SAL234", phone="34600111222", hub="hub-1"):
    return a.wa.resolve_incoming_readonly(hub, phone, "DEMO " + code)


def _wa1_apply(a, decision, ticket, evento=None, tenant=None):
    return a.wa.apply_demo_resolution(decision, cliente_id=tenant or ticket["cliente_id"],
        ticket_id=ticket["ticket_id"], evento_id=evento or ticket["evento_id"])


def _wa1_rows(a):
    with closing(a.db._get_db_connection()) as conn:
        return {
            table: [tuple(r) for r in conn.execute("SELECT * FROM " + table + " ORDER BY 1")]
            for table in ("wa_demo_routes", "wa_demo_codes", "client_attention_operations")
        }


def _wa1_pause(a, tenant="negocio_es", version=0):
    return a.autoridad.cambiar_atencion(tenant, "pausada", version_esperada=version,
                                        motivo="temporada", actor="sistema")


def _wa1_replay_in_new_interpreter(a, ticket):
    # Patrón de atencion_proceso_aislado.py: solo valores serializados y SQLite,
    # sin api_module, objetos vivos, .env ni configuración real en el hijo.
    root = Path(__file__).resolve().parents[1]
    database = Path(a.settings.DB_PATH).resolve()
    temporary = database.parent
    environment = {k: v for k, v in os.environ.items() if k.upper() in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP")}
    environment.update(PYTHONPATH=str(root), PYTHONIOENCODING="utf-8",
        VANTELIA_DATA_DIR=str(temporary), VANTELIA_STORAGE_DIR=str(temporary),
        VANTELIA_CONFIG_PATH=str(temporary / "config_no_cargada.json"))
    values = dict(hub="hub-1", phone="34600111222", text="DEMO SAL234",
                  cliente_id=ticket["cliente_id"], ticket_id=ticket["ticket_id"],
                  evento_id=ticket["evento_id"], replay_at=a.reloj["ahora"].isoformat())
    code = """
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import dotenv
dotenv.load_dotenv = lambda *args, **kwargs: False
from backend import settings, timeutils, wa_demo
settings.DB_PATH = Path(sys.argv[1])
values = json.loads(sys.argv[2])
timeutils._utc_now = lambda: datetime.fromisoformat(values['replay_at'])
resolution = wa_demo.resolve_incoming_readonly(values['hub'], values['phone'], values['text'])
result = wa_demo.apply_demo_resolution(resolution, cliente_id=values['cliente_id'],
    ticket_id=values['ticket_id'], evento_id=values['evento_id'])
assert 'api' not in sys.modules and 'backend.main' not in sys.modules
assert 'backend.booking' not in sys.modules
print(json.dumps({'pid': os.getpid(), 'result': result}))
"""
    completed = subprocess.run([sys.executable, "-c", code, str(database), json.dumps(values)],
        cwd=str(temporary), env=environment, capture_output=True, text=True,
        encoding="utf-8", timeout=30, check=True)
    output = json.loads(completed.stdout)
    assert output["pid"] != os.getpid()
    return output["result"]


def test_pausa_entre_consulta_y_binding_suprime_sin_efectos(demo_application):
    a = demo_application
    ticket = _crear_ticket_prueba(a)
    decision = _wa1_query(a)
    before = _wa1_rows(a)
    _wa1_pause(a)
    result = _wa1_apply(a, decision, ticket)
    assert result["estado"] == "suprimido" and not result["binding_aplicado_ahora"]
    after = _wa1_rows(a)
    assert after["wa_demo_routes"] == before["wa_demo_routes"]
    assert after["wa_demo_codes"] == before["wa_demo_codes"]
    assert a.op.consultar_operaciones_atencion("negocio_es", tipo="wa_demo")[0]["motivo"] == "pausada"


def test_reactivar_no_recicla_ticket_ni_evento_y_admite_evento_nuevo(demo_application):
    a = demo_application
    stale = _crear_ticket_prueba(a)
    decision = _wa1_query(a)
    _wa1_pause(a)
    a.reloj["ahora"] += timedelta(seconds=1)
    a.autoridad.cambiar_atencion("negocio_es", "activa", version_esperada=1,
                                 motivo="fin_temporada", actor="sistema")
    assert _wa1_apply(a, decision, stale)["estado"] == "suprimido"
    a.reloj["ahora"] += timedelta(seconds=1)
    fresh = _crear_ticket_prueba(a, evento="evento_nuevo")
    assert _wa1_apply(a, decision, fresh)["binding_aplicado_ahora"]
    replay = _wa1_apply(a, _wa1_query(a), stale)
    assert replay["estado"] == "suprimido" and replay["repetido"]


@pytest.mark.parametrize("change", ["revocado", "caducado", "tenant", "vigencia"])
def test_foto_codigo_obsoleta_rechaza_sin_resolver_otro_tenant(demo_application, change):
    a = demo_application
    ticket = _crear_ticket_prueba(a)
    decision = _wa1_query(a)
    sql, values = {
        "revocado": ("UPDATE wa_demo_codes SET active=0 WHERE code=?", ("SAL234",)),
        "caducado": ("UPDATE wa_demo_codes SET expires_at=? WHERE code=?",
                     (a.reloj["ahora"].strftime("%Y-%m-%dT%H:%M:%SZ"), "SAL234")),
        "tenant": ("UPDATE wa_demo_codes SET cliente_id=? WHERE code=?", ("negocio_en", "SAL234")),
        "vigencia": ("UPDATE wa_demo_codes SET expires_at=? WHERE code=?", ("2098-01-01T00:00:00Z", "SAL234")),
    }[change]
    with closing(a.db._get_db_connection()) as conn, conn:
        conn.execute(sql, values)
    before = _wa1_rows(a)
    result = _wa1_apply(a, decision, ticket)
    assert result["estado"] == "rechazado" and not result["binding_aplicado_ahora"]
    after = _wa1_rows(a)
    assert after["wa_demo_routes"] == before["wa_demo_routes"]
    assert after["wa_demo_codes"] == before["wa_demo_codes"]
    assert _wa1_apply(a, _wa1_query(a), ticket)["repetido"]


def test_cambio_de_ruta_entre_consulta_y_aplicacion_no_se_sobrescribe(demo_application):
    a = demo_application
    a.wa.bind_phone("34600111222", "SAL234")
    decision = _wa1_query(a, code="HOT456")
    ticket = _crear_ticket_prueba(a, tenant="negocio_en")
    a.wa.bind_phone("34600111222", "HOT456")
    before = _wa1_rows(a)
    assert _wa1_apply(a, decision, ticket)["estado"] == "rechazado"
    after = _wa1_rows(a)
    assert after["wa_demo_routes"] == before["wa_demo_routes"]
    assert after["wa_demo_codes"] == before["wa_demo_codes"]


def test_dos_workers_mismo_evento_solo_un_binding_y_un_uso(demo_application):
    a = demo_application
    ticket = _crear_ticket_prueba(a)
    decision = _wa1_query(a)
    ready = threading.Barrier(2)

    def apply():
        ready.wait(timeout=10)
        return _wa1_apply(a, decision, ticket)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: apply(), range(2)))
    assert sum(r["binding_aplicado_ahora"] for r in results) == 1
    assert sum(r["repetido"] for r in results) == 1
    rows = _wa1_rows(a)
    assert len(rows["wa_demo_routes"]) == len(rows["client_attention_operations"]) == 1
    assert next(r for r in rows["wa_demo_codes"] if r[0] == "SAL234")[5] == 1


def test_otro_telefono_no_invalida_codigo_y_otro_hub_aisla_tenant(demo_application):
    a = demo_application
    first = _wa1_query(a)
    second = _wa1_query(a, phone="34600333444")
    other_tenant = _wa1_query(a, code="HOT456", phone="34600555666", hub="hub-2")
    assert _wa1_apply(a, first, _crear_ticket_prueba(a))["binding_aplicado_ahora"]
    assert _wa1_apply(a, second, _crear_ticket_prueba(a, evento="evento_2"))["binding_aplicado_ahora"]
    assert _wa1_apply(a, other_tenant, _crear_ticket_prueba(a, tenant="negocio_en"))["binding_aplicado_ahora"]
    assert a.wa.route_for_phone("34600111222") == a.wa.route_for_phone("34600333444") == "negocio_es"
    assert a.wa.route_for_phone("34600555666") == "negocio_en"


def test_binding_ganador_termina_antes_de_la_pausa_competidora(demo_application, monkeypatch):
    a = demo_application
    ticket = _crear_ticket_prueba(a)
    decision = _wa1_query(a)
    entered, finish, pause_started = threading.Event(), threading.Event(), threading.Event()
    original = a.wa._bind_demo_phone_en_transaccion

    def held_binding(*args):
        result = original(*args)
        entered.set()
        assert finish.wait(timeout=10)
        return result

    def pause():
        pause_started.set()
        return _wa1_pause(a)

    monkeypatch.setattr(a.wa, "_bind_demo_phone_en_transaccion", held_binding)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as workers:
        applying = workers.submit(_wa1_apply, a, decision, ticket)
        try:
            assert entered.wait(timeout=10)
            pausing = workers.submit(pause)
            assert pause_started.wait(timeout=10)
            assert not pausing.done()
        finally:
            finish.set()
        assert applying.result(timeout=10)["binding_aplicado_ahora"]
        assert pausing.result(timeout=10)["estado"] == "pausada"
    assert a.op.consultar_operaciones_atencion("negocio_es", tipo="wa_demo")[0]["estado"] == "aceptado"


@pytest.mark.parametrize("failure_at", ["uses", "resultado"])
def test_fallo_sql_revierte_binding_uses_y_diario_juntos(demo_application, failure_at):
    a = demo_application
    ticket = _crear_ticket_prueba(a)
    decision = _wa1_query(a)
    with closing(a.db._get_db_connection()) as conn, conn:
        if failure_at == "uses":
            conn.execute("""CREATE TRIGGER wa1_fail BEFORE UPDATE OF uses ON wa_demo_codes
                            BEGIN SELECT RAISE(ABORT,'wa1_uses'); END""")
        else:
            conn.execute("""CREATE TRIGGER wa1_fail BEFORE UPDATE OF estado ON client_attention_operations
                            WHEN NEW.tipo='wa_demo' AND NEW.estado='aceptado'
                            BEGIN SELECT RAISE(ABORT,'wa1_resultado'); END""")
    before = _wa1_rows(a)
    with pytest.raises(a.autoridad.AtencionNoDisponible):
        _wa1_apply(a, decision, ticket)
    assert _wa1_rows(a) == before


@pytest.mark.parametrize("after", ["pausa", "revocacion", "caducidad"])
def test_reinicio_replay_conocido_no_vincula_ni_devuelve_permiso(demo_application, after):
    a = demo_application
    ticket = _crear_ticket_prueba(a)
    assert _wa1_apply(a, _wa1_query(a), ticket)["binding_aplicado_ahora"]
    if after == "pausa":
        _wa1_pause(a)
    elif after == "revocacion":
        a.wa.revoke_code("SAL234")
    else:
        a.reloj["ahora"] += timedelta(minutes=20)
        with closing(a.db._get_db_connection()) as conn, conn:
            conn.execute("UPDATE wa_demo_codes SET expires_at='2020-01-01T00:00:00Z'")
    before = _wa1_rows(a)
    result = _wa1_replay_in_new_interpreter(a, ticket)
    assert result == {"cliente_id": "negocio_es", "estado": "aceptado",
                      "binding_aplicado_ahora": False, "repetido": True}
    assert _wa1_rows(a) == before


def test_ticket_de_otro_evento_o_tenant_no_aplica(demo_application):
    a = demo_application
    ticket = _crear_ticket_prueba(a)
    before = _wa1_rows(a)
    with pytest.raises(a.op.AtencionIdentidadEnConflicto):
        _wa1_apply(a, _wa1_query(a), ticket, evento="otro_evento")
    with pytest.raises(a.op.AtencionOperacionNoEncontrada):
        _wa1_apply(a, _wa1_query(a), ticket, tenant="negocio_en")
    assert _wa1_rows(a) == before


def test_evento_no_reaparece_como_otro_tenant_ni_revela_el_original(demo_application):
    a = demo_application
    first = _crear_ticket_prueba(a)
    decision = _wa1_query(a)
    assert _wa1_apply(a, decision, first)["binding_aplicado_ahora"]
    with closing(a.db._get_db_connection()) as conn, conn:
        conn.execute("UPDATE wa_demo_codes SET cliente_id='negocio_en' WHERE code='SAL234'")
    second = _crear_ticket_prueba(a, tenant="negocio_en")
    changed = _wa1_query(a)
    assert changed.input_hash == decision.input_hash  # Entrada estable, tenant resuelto distinto.
    before = _wa1_rows(a)
    with pytest.raises(a.op.AtencionIdentidadEnConflicto) as error:
        _wa1_apply(a, changed, second)
    assert all(secret not in str(error.value) for secret in ("negocio_es", "SAL234", "34600111222"))
    assert _wa1_rows(a) == before


@pytest.mark.parametrize("change", ["telefono", "codigo"])
def test_mismo_evento_con_entrada_distinta_es_conflicto(demo_application, change):
    a = demo_application
    ticket = _crear_ticket_prueba(a)
    _wa1_apply(a, _wa1_query(a), ticket)
    changed = _wa1_query(a, phone="34600999888") if change == "telefono" else _wa1_query(a, code="HOT456")
    before = _wa1_rows(a)
    with pytest.raises(a.op.AtencionIdentidadEnConflicto):
        _wa1_apply(a, changed, ticket)
    assert _wa1_rows(a) == before


@pytest.mark.parametrize("component", ["hub", "evento"])
def test_clave_usa_hub_y_evento_completos_sin_truncar(demo_application, component):
    a = demo_application
    prefix = "e" * 127
    first = _crear_ticket_prueba(a, evento=prefix + "1")
    assert _wa1_apply(a, _wa1_query(a, hub=prefix + "1"), first)["binding_aplicado_ahora"]
    second = first if component == "hub" else _crear_ticket_prueba(a, evento=prefix + "2")
    assert _wa1_apply(a, _wa1_query(a, hub=prefix + ("2" if component == "hub" else "1")), second)["binding_aplicado_ahora"]
    operations = a.op.consultar_operaciones_atencion("negocio_es", tipo="wa_demo")
    assert len({r["clave_intento"] for r in operations}) == 2
    assert all(len(r["clave_intento"]) == 64 for r in operations)
    assert all("SAL234" not in str(r) and "34600111222" not in str(r) for r in operations)


@pytest.mark.parametrize("state", ["activa", "pausada", "ruta_cambiada"])
def test_ruta_sin_binding_verifica_ticket_y_foto_sin_fingir_mutacion(demo_application, state):
    a = demo_application
    a.wa.bind_phone("34600111222", "SAL234")
    decision = a.wa.resolve_incoming_readonly("hub-1", "34600111222", "hola, buenas")
    ticket = _crear_ticket_prueba(a)
    if state == "pausada":
        _wa1_pause(a)
    elif state == "ruta_cambiada":
        a.wa.bind_phone("34600111222", "HOT456")
    before = _wa1_rows(a)
    result = _wa1_apply(a, decision, ticket)
    assert result["estado"] == {"activa": "ruta_vigente", "pausada": "suprimido", "ruta_cambiada": "rechazado"}[state]
    assert not result["binding_aplicado_ahora"]
    assert _wa1_rows(a) == before


def test_migracion_preserva_tres_tipos_y_unicidad_wa_demo_cruzada(demo_application):
    a = demo_application
    ticket = _crear_ticket_prueba(a)
    for tipo, accion, ref in [("envio", "email", ""), ("reserva", "crear", "bk_original"),
                               ("pago", "crear_enlace", "pay_original")]:
        key = "" if tipo == "envio" else "intento_1"
        op = a.op.admitir_operacion_atencion("negocio_es", ticket["ticket_id"],
            tipo=tipo, canal=accion, clave_intento=key, payload=b"original")
        a.op.registrar_resultado_operacion_atencion("negocio_es", ticket["ticket_id"],
            tipo=tipo, canal=accion, clave_intento=key, owner_token=op["owner_token"],
            resultado="aceptado", result_ref=ref)
    with closing(a.db._get_db_connection()) as conn, conn:
        original = [tuple(r) for r in conn.execute("SELECT * FROM client_attention_operations ORDER BY tipo")]
        schema = conn.execute("SELECT sql FROM sqlite_master WHERE name='client_attention_operations'").fetchone()[0]
        conn.execute("DROP TABLE client_attention_operations")
        conn.execute(schema.replace(", 'wa_demo'", ""))
        conn.executemany("INSERT INTO client_attention_operations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", original)
    a.db._init_database()
    a.db._init_database()
    with closing(a.db._get_db_connection()) as conn:
        assert [tuple(r) for r in conn.execute("SELECT * FROM client_attention_operations ORDER BY tipo")] == original
    assert _wa1_apply(a, _wa1_query(a), ticket)["binding_aplicado_ahora"]
    other = _crear_ticket_prueba(a, tenant="negocio_en")
    with closing(a.db._get_db_connection()) as conn, conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("""INSERT INTO client_attention_operations
                SELECT ?, ?,tipo,canal,fragmento,clave_intento,payload_hash,request_hash,estado,
                       owner_token,motivo,created_at,resultado_at,result_ref
                FROM client_attention_operations WHERE tipo='wa_demo'""",
                ("negocio_en", other["ticket_id"]))
