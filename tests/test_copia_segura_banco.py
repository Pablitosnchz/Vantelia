"""El destino del banco nunca puede borrar su origen antes de copiar SQLite."""
import os
import pathlib
import sqlite3
import sys

import pytest

from scripts import evaluar_asistente as banco


def _sqlite_sintetica(path):
    with sqlite3.connect(str(path)) as conexion:
        conexion.execute("CREATE TABLE prueba (dato TEXT)")
        conexion.execute("INSERT INTO prueba VALUES ('conservar')")
    return path.read_bytes()


@pytest.mark.parametrize("alias", ["igual", "relativo", "mayusculas", "enlace_duro", "sidecar"])
def test_copia_rechaza_alias_antes_de_eliminar_o_abrir_backup(api_module, monkeypatch, tmp_path, alias):
    from backend import settings
    origen = tmp_path / "origen.db"
    antes = _sqlite_sintetica(origen)
    destino = str(origen)
    if alias == "relativo":
        monkeypatch.chdir(tmp_path)
        destino = os.path.join(".", "carpeta", "..", "origen.db")
        (tmp_path / "carpeta").mkdir()
    elif alias == "mayusculas":
        if os.name != "nt":
            pytest.skip("Alias por mayúsculas del sistema Windows")
        destino = str(origen).upper()
    elif alias == "enlace_duro":
        enlace = tmp_path / "alias.db"
        os.link(str(origen), str(enlace))
        destino = str(enlace)
    elif alias == "sidecar":
        destino = str(tmp_path / "copia.db")
        origen.rename(destino + "-wal")
        origen = tmp_path / "copia.db-wal"
    borrados, conexiones = [], []
    quitar = os.remove
    def borrar(path):
        borrados.append(path)
        return quitar(path)
    def conectar(*args, **kwargs):
        conexiones.append(args)
        raise RuntimeError("Spy: no llegar a backup sobre origen y destino iguales")
    monkeypatch.setattr(banco.os, "remove", borrar)
    monkeypatch.setattr(sqlite3, "connect", conectar)
    monkeypatch.setattr(settings, "DB_PATH", tmp_path / "sin-cambios.db")
    monkeypatch.setenv("DB_PATH", "sin-cambios")
    error = None
    try:
        banco._preparar_copia(str(origen), destino)
    except (SystemExit, RuntimeError) as exc:
        error = exc
    assert borrados == [], "No se debe intentar borrar ningún destino o sidecar si es alias del origen"
    assert conexiones == [], "La validación debe preceder incluso a abrir el backup"
    assert origen.read_bytes() == antes
    assert isinstance(error, SystemExit)
    assert settings.DB_PATH == tmp_path / "sin-cambios.db"
    assert os.environ["DB_PATH"] == "sin-cambios"


def test_origen_inexistente_no_crea_db_vacia_ni_borra_destino(api_module, monkeypatch, tmp_path):
    from backend import settings
    monkeypatch.setattr(settings, "DB_PATH", settings.DB_PATH)
    monkeypatch.setenv("DB_PATH", os.environ.get("DB_PATH", ""))
    origen = tmp_path / "no-existe.db"
    destino = tmp_path / "copia.db"
    antes = _sqlite_sintetica(destino)
    borrados = []
    quitar = os.remove
    def borrar(path):
        borrados.append(path)
        return quitar(path)
    monkeypatch.setattr(banco.os, "remove", borrar)
    error = None
    try:
        banco._preparar_copia(str(origen), str(destino))
    except SystemExit as exc:
        error = exc
    assert not origen.exists(), "sqlite3.connect no debe crear un origen inexistente"
    assert borrados == []
    assert destino.read_bytes() == antes
    assert isinstance(error, SystemExit)


def test_copia_distinta_conserva_datos_wal_y_apunta_a_copia(api_module, monkeypatch, tmp_path):
    from backend import settings
    origen, destino = tmp_path / "origen.db", tmp_path / "copia.db"
    monkeypatch.setattr(settings, "DB_PATH", origen)
    monkeypatch.setenv("DB_PATH", str(origen))
    conexion = sqlite3.connect(str(origen))
    try:
        conexion.execute("PRAGMA journal_mode=WAL")
        conexion.execute("CREATE TABLE prueba (dato TEXT)")
        conexion.execute("INSERT INTO prueba VALUES ('desde-wal')")
        conexion.commit()
        assert (tmp_path / "origen.db-wal").exists()
        banco._preparar_copia(str(origen), str(destino))
        with sqlite3.connect(str(destino)) as copia:
            assert copia.execute("SELECT dato FROM prueba").fetchall() == [("desde-wal",)]
        assert settings.DB_PATH == destino
        assert os.environ["DB_PATH"] == str(destino)
    finally:
        conexion.close()


def test_origen_desaparecido_antes_de_abrir_no_se_recrea(api_module, monkeypatch, tmp_path):
    origen, destino = tmp_path / "origen.db", tmp_path / "copia.db"
    _sqlite_sintetica(origen)
    antes = _sqlite_sintetica(destino)
    conectar = sqlite3.connect
    def desaparece(*args, **kwargs):
        origen.unlink()
        return conectar(*args, **kwargs)
    monkeypatch.setattr(sqlite3, "connect", desaparece)
    with pytest.raises(SystemExit, match="No se puede abrir"):
        banco._preparar_copia(str(origen), str(destino))
    assert not origen.exists()
    assert destino.read_bytes() == antes


@pytest.mark.parametrize("campo", ["origen", "copia"])
@pytest.mark.parametrize("sufijo", ["-wal", "-shm"])
def test_informe_no_toca_sidecars_de_sqlite_vivo(monkeypatch, tmp_path, campo, sufijo):
    origen, copia = tmp_path / "origen.db", tmp_path / "copia.db"
    protegida = origen if campo == "origen" else copia
    conexion = sqlite3.connect(str(protegida))
    try:
        conexion.execute("PRAGMA journal_mode=WAL")
        conexion.execute("CREATE TABLE evidencia (valor TEXT)")
        conexion.execute("INSERT INTO evidencia VALUES ('conservar')")
        conexion.commit()
        archivos = [pathlib.Path(str(protegida) + s) for s in ("", "-wal", "-shm")]
        antes = {p: p.read_bytes() for p in archivos}
        escrituras = []
        def impedir_io(*args):
            escrituras.append(args)
            raise RuntimeError("Spy: no escribir ni copiar si informe apunta a SQLite")
        monkeypatch.setattr(banco, "_guardar_informe", impedir_io)
        monkeypatch.setattr(banco, "_preparar_copia", impedir_io)
        monkeypatch.setattr(banco, "_sha_del_banco", lambda: "sintetico")
        monkeypatch.setattr(banco, "_arbol_sucio_del_banco", lambda: False)
        monkeypatch.setattr(sys, "argv", ["banco", "--db-origen", str(origen), "--db-copia", str(copia),
            "--guardar", str(protegida) + sufijo])
        salida = None
        try:
            banco.main()
        except (SystemExit, RuntimeError) as exc:
            salida = exc
        assert escrituras == []
        assert isinstance(salida, SystemExit) and salida.code == 2
        assert {p: p.read_bytes() for p in archivos} == antes
    finally:
        conexion.close()


def test_ruta_con_tilde_se_copia_y_supera_aislamiento(api_module, monkeypatch, tmp_path):
    from backend import settings
    origen, destino = tmp_path / "origen.db", tmp_path / "copia.db"
    _sqlite_sintetica(origen)
    try:
        relativo = destino.relative_to(pathlib.Path.home())
    except ValueError:
        pytest.skip("El temporal debe estar bajo home para probar ~ sin modificar el entorno")
    con_tilde = "~/" + relativo.as_posix()
    monkeypatch.setattr(settings, "DB_PATH", origen)
    monkeypatch.setenv("DB_PATH", str(origen))
    banco._preparar_copia(str(origen), con_tilde)
    banco._comprobar_aislamiento(con_tilde)
    assert destino.exists()
    with sqlite3.connect(str(destino)) as conexion:
        assert conexion.execute("SELECT dato FROM prueba").fetchone()[0] == "conservar"
