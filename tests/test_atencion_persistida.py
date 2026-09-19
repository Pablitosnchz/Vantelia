"""La pausa tiene una autoridad duradera; un fallo no se convierte en permiso."""
import concurrent.futures
from contextlib import closing
import importlib
import json
import sqlite3
import subprocess
import sys
import threading

import pytest


@pytest.fixture
def autoridad_atencion(api_module, tmp_path, monkeypatch):
    # Entorno compartido de conftest: sin secretos, proveedores ni modelo real.
    from backend import atencion, db, settings

    monkeypatch.setattr(settings, "DB_PATH", tmp_path / "atencion.db")
    db._init_database()
    return atencion, db, settings


def _pausar_tenant(autoridad, cliente_id="negocio_es", version=0, **cambios):
    datos = {"version_esperada": version, "motivo": "temporada", "actor": "sistema"}
    datos.update(cambios)
    return autoridad.cambiar_atencion(cliente_id, "pausada", **datos)


def _auditoria_atencion(db):
    with closing(db._get_db_connection()) as connection:
        return [dict(row) for row in connection.execute(
            "SELECT * FROM client_channel_audit WHERE channel='atencion' ORDER BY id")]


def test_ausencia_es_activa_sin_crear_estado_ni_auditoria(autoridad_atencion):
    atencion, db, _ = autoridad_atencion
    esperado = {"cliente_id": "negocio_es", "estado": "activa", "version": 0,
                "fecha_efectiva": None, "motivo": None, "actor": None}
    assert atencion.leer_atencion("negocio_es") == esperado
    assert atencion.cambiar_atencion("negocio_es", "activa", version_esperada=0,
                                    motivo="comprobacion", actor="sistema") == esperado
    with closing(db._get_db_connection()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM client_attention_state").fetchone()[0] == 0
    assert _auditoria_atencion(db) == []


def test_dos_tenants_transiciones_idempotentes_y_auditoria(autoridad_atencion):
    atencion, db, settings = autoridad_atencion
    config_antes = settings.CONFIG_PATH.read_bytes()
    usuario = "usr_0123456789abcdef"
    pausada = _pausar_tenant(atencion, actor=usuario)
    assert pausada["estado"] == "pausada"
    assert pausada["version"] == 1
    assert pausada["actor"] == usuario
    assert pausada["fecha_efectiva"].endswith("Z")
    assert atencion.leer_atencion("negocio_en")["version"] == 0
    assert atencion.leer_atencion("negocio_en")["estado"] == "activa"
    assert _pausar_tenant(atencion, version=1, motivo="otro_motivo") == pausada
    activa = atencion.cambiar_atencion("negocio_es", "activa", version_esperada=1,
                                      motivo="fin_temporada", actor="sistema")
    assert activa["estado"] == "activa" and activa["version"] == 2
    assert atencion.leer_atencion("negocio_es") == activa
    assert settings.CONFIG_PATH.read_bytes() == config_antes
    auditoria = _auditoria_atencion(db)
    assert len(auditoria) == 2
    assert {row["cliente_id"] for row in auditoria} == {"negocio_es"}
    assert {row["event_type"] for row in auditoria} == {"atencion_transicion"}
    assert all(row["success"] == 1 and row["provider"] == "" for row in auditoria)
    assert json.loads(auditoria[0]["detail"]) == {
        "estado_anterior": "activa", "estado": "pausada", "version_anterior": 0,
        "version": 1, "motivo": "temporada", "actor": usuario}
    assert auditoria[0]["created_at"] == pausada["fecha_efectiva"]
    assert json.loads(auditoria[1]["detail"])["version"] == 2


@pytest.mark.parametrize("estado", ["activa", "pausada"])
def test_version_obsoleta_no_despausa_ni_simula_idempotencia(autoridad_atencion, estado):
    atencion, db, _ = autoridad_atencion
    pausada = _pausar_tenant(atencion)
    with pytest.raises(atencion.AtencionVersionObsoleta) as error:
        atencion.cambiar_atencion("negocio_es", estado, version_esperada=0,
                                  motivo="trabajo_viejo", actor="sistema")
    assert error.value.version_actual == 1
    assert atencion.leer_atencion("negocio_es") == pausada
    assert len(_auditoria_atencion(db)) == 1


def test_dos_escritores_con_la_misma_version_solo_uno_gana(autoridad_atencion):
    atencion, db, _ = autoridad_atencion
    _pausar_tenant(atencion)
    preparados = threading.Barrier(2)

    def reactivar():
        version = atencion.leer_atencion("negocio_es")["version"]
        preparados.wait(timeout=10)
        try:
            return atencion.cambiar_atencion("negocio_es", "activa", version_esperada=version,
                                            motivo="fin_temporada", actor="sistema")
        except atencion.AtencionVersionObsoleta as exc:
            return exc

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as workers:
        resultados = list(workers.map(lambda _: reactivar(), range(2)))
    assert sum(isinstance(r, dict) for r in resultados) == 1
    assert sum(isinstance(r, atencion.AtencionVersionObsoleta) for r in resultados) == 1
    assert atencion.leer_atencion("negocio_es")["version"] == 2
    assert len(_auditoria_atencion(db)) == 2


def test_recarga_y_otro_proceso_conservan_pausa_y_rechazan_version_vieja(autoridad_atencion):
    atencion, _, settings = autoridad_atencion
    pausada = _pausar_tenant(atencion)
    importlib.reload(atencion)
    assert atencion.leer_atencion("negocio_es") == pausada
    codigo = """
import json
import sys
from backend import atencion, settings
settings.DB_PATH = sys.argv[1]
foto = atencion.leer_atencion('negocio_es')
try:
    atencion.cambiar_atencion('negocio_es', 'activa', version_esperada=0,
                             motivo='viejo', actor='sistema')
except atencion.AtencionVersionObsoleta as exc:
    print(json.dumps({'foto': foto, 'version_actual': exc.version_actual}))
else:
    raise AssertionError('El proceso nuevo aceptó una versión vieja')
"""
    resultado = subprocess.run([sys.executable, "-c", codigo, str(settings.DB_PATH)],
                               capture_output=True, text=True, check=True, timeout=30)
    assert json.loads(resultado.stdout) == {"foto": pausada, "version_actual": 1}


def test_migracion_sobre_base_previa_es_idempotente_y_conserva_datos(autoridad_atencion):
    atencion, db, _ = autoridad_atencion
    with closing(db._get_db_connection()) as connection, connection:
        connection.execute("DROP TABLE client_attention_state")
        connection.execute("CREATE TABLE evidencia_previa (valor TEXT)")
        connection.execute("INSERT INTO evidencia_previa VALUES ('configuracion conservada')")
    db._init_database()
    pausada = _pausar_tenant(atencion)
    db._init_database()
    assert atencion.leer_atencion("negocio_es") == pausada
    with closing(db._get_db_connection()) as connection:
        assert connection.execute("SELECT valor FROM evidencia_previa").fetchone()[0] == "configuracion conservada"
    assert len(_auditoria_atencion(db)) == 1


@pytest.mark.parametrize("campo,valor", [
    ("estado", "PAUSADA"), ("estado", " pausada"), ("estado", "inactiva"),
    ("estado", None), ("estado", []),
    ("version_esperada", True), ("version_esperada", "0"), ("version_esperada", 0.0),
    ("version_esperada", -1), ("version_esperada", None), ("version_esperada", 2 ** 63),
    ("motivo", ""), ("motivo", "vacaciones de Maria"), ("motivo", "privado@example.com"),
    ("motivo", "x" * 65), ("motivo", None), ("motivo", "temporada\n"),
    ("actor", ""), ("actor", "María Pérez"), ("actor", "privado@example.com"),
    ("actor", None), ("actor", "usr_corto"), ("actor", "sistema\n"),
])
def test_entrada_invalida_no_deja_estado_ni_auditoria(autoridad_atencion, campo, valor):
    atencion, db, _ = autoridad_atencion
    datos = {"estado": "pausada", "version_esperada": 0, "motivo": "temporada", "actor": "sistema"}
    datos[campo] = valor
    with pytest.raises(ValueError):
        atencion.cambiar_atencion("negocio_es", **datos)
    assert atencion.leer_atencion("negocio_es")["version"] == 0
    assert not _auditoria_atencion(db)


@pytest.mark.parametrize("cliente_id", ["", "a", " negocio", "negocio ", "negocio\n", "a/b", None, True, "x" * 81])
def test_identidad_invalida_se_rechaza_antes_de_acceder_a_db(autoridad_atencion, monkeypatch, cliente_id):
    atencion, db, _ = autoridad_atencion

    def acceso_prohibido():
        pytest.fail("Una identidad inválida no debe alcanzar la base de datos")

    monkeypatch.setattr(db, "_get_db_connection", acceso_prohibido)
    with pytest.raises(ValueError):
        atencion.leer_atencion(cliente_id)
    with pytest.raises(ValueError):
        _pausar_tenant(atencion, cliente_id)


@pytest.mark.parametrize("cliente_id", ["_salon", "-salon", "x" * 80])
def test_conserva_vocabulario_comun_de_identidad_del_tenant(autoridad_atencion, cliente_id):
    atencion, _, settings = autoridad_atencion
    assert settings.CLIENT_ID_PATTERN.fullmatch(cliente_id)
    assert atencion.leer_atencion(cliente_id)["estado"] == "activa"
    assert _pausar_tenant(atencion, cliente_id)["cliente_id"] == cliente_id
    assert atencion.leer_atencion(cliente_id)["estado"] == "pausada"


def test_fecha_sin_hora_no_oculta_corrupcion_como_estado_activo(autoridad_atencion):
    atencion, db, _ = autoridad_atencion
    _pausar_tenant(atencion)
    with closing(db._get_db_connection()) as connection, connection:
        connection.execute("UPDATE client_attention_state SET estado='activa',fecha_efectiva='2026-09-19Z'")
    with pytest.raises(atencion.AtencionNoDisponible):
        atencion.leer_atencion("negocio_es")
    with pytest.raises(atencion.AtencionNoDisponible):
        atencion.cambiar_atencion("negocio_es", "activa", version_esperada=1,
                                  motivo="temporada", actor="sistema")


@pytest.mark.parametrize("operacion", ["leer", "cambiar"])
def test_error_al_abrir_db_no_da_permiso_ni_filtra_detalle(autoridad_atencion, monkeypatch, caplog, operacion):
    atencion, db, _ = autoridad_atencion

    def db_rota():
        raise sqlite3.OperationalError("error con privado@example.com")

    monkeypatch.setattr(db, "_get_db_connection", db_rota)
    with pytest.raises(atencion.AtencionNoDisponible) as error:
        if operacion == "leer":
            atencion.leer_atencion("negocio_es")
        else:
            _pausar_tenant(atencion)
    assert "privado@example.com" not in str(error.value)
    assert "privado@example.com" not in caplog.text
    assert "OperationalError" in caplog.text


def test_tabla_ausente_es_error_y_no_el_estado_activo_por_defecto(autoridad_atencion):
    atencion, db, _ = autoridad_atencion
    with closing(db._get_db_connection()) as connection, connection:
        connection.execute("DROP TABLE client_attention_state")
    with pytest.raises(atencion.AtencionNoDisponible):
        atencion.leer_atencion("negocio_es")
    with pytest.raises(atencion.AtencionNoDisponible):
        _pausar_tenant(atencion)


@pytest.mark.parametrize("campo,valor", [
    ("estado", "desconocido"), ("version", 0), ("version", 1.5),
    ("fecha_efectiva", "fecha rota"), ("fecha_efectiva", "2026-09-19T10:00:00"),
    ("motivo", "datos privados"), ("actor", "privado@example.com"),
])
def test_fila_corrupta_no_permite_atencion_ni_se_sobrescribe(autoridad_atencion, campo, valor):
    atencion, db, _ = autoridad_atencion
    _pausar_tenant(atencion)
    with closing(db._get_db_connection()) as connection, connection:
        connection.execute("PRAGMA ignore_check_constraints=ON")
        connection.execute("UPDATE client_attention_state SET %s=?" % campo, (valor,))
    with pytest.raises(atencion.AtencionNoDisponible):
        atencion.leer_atencion("negocio_es")
    for estado in ("activa", "pausada"):
        with pytest.raises(atencion.AtencionNoDisponible):
            atencion.cambiar_atencion("negocio_es", estado, version_esperada=1,
                                      motivo="fin_temporada", actor="sistema")
    assert len(_auditoria_atencion(db)) == 1


@pytest.mark.parametrize("ya_pausada", [False, True])
def test_fallo_de_auditoria_revierte_toda_la_transicion(autoridad_atencion, ya_pausada):
    atencion, db, _ = autoridad_atencion
    if ya_pausada:
        _pausar_tenant(atencion)
    anterior = atencion.leer_atencion("negocio_es")
    auditoria = _auditoria_atencion(db)
    with closing(db._get_db_connection()) as connection, connection:
        connection.execute("CREATE TRIGGER rechazar_auditoria BEFORE INSERT ON client_channel_audit "
                           "BEGIN SELECT RAISE(ABORT, 'fallo de auditoria'); END")
    with pytest.raises(atencion.AtencionNoDisponible):
        atencion.cambiar_atencion("negocio_es", "activa" if ya_pausada else "pausada",
                                  version_esperada=anterior["version"], motivo="temporada", actor="sistema")
    assert atencion.leer_atencion("negocio_es") == anterior
    assert _auditoria_atencion(db) == auditoria


@pytest.mark.parametrize("campo,valor", [("estado", "otro"), ("version", -1), ("version", 0),
                                        ("version", 1.5), ("fecha_efectiva", ""), ("motivo", ""), ("actor", "")])
def test_esquema_rechaza_filas_invalidas(autoridad_atencion, campo, valor):
    _, db, _ = autoridad_atencion
    datos = {"cliente_id": "negocio_es", "estado": "pausada", "version": 1,
             "fecha_efectiva": "2026-09-19T10:00:00Z", "motivo": "temporada", "actor": "sistema"}
    datos[campo] = valor
    with closing(db._get_db_connection()) as connection, connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO client_attention_state "
                               "(cliente_id,estado,version,fecha_efectiva,motivo,actor) VALUES (?,?,?,?,?,?)",
                               tuple(datos.values()))
