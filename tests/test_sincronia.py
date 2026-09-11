"""La pagina de sincronia dice la verdad sobre Claude y Astra.

Pablo cambia de agente cuando a uno se le acaban los tokens y necesita saber si
el otro ha visto lo ultimo. Aqui se comprueba, sobre repos git de verdad en un
tmp_path, que el semaforo sale de HECHOS (commits, ficheros sin guardar, cuando
se puso al dia cada uno) y no de lo que diga un agente; y que el servidor guarda
la foto solo con su token propio y la ensena solo al admin.
"""
from __future__ import annotations

import datetime as dt
import importlib
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

RAIZ = pathlib.Path(__file__).resolve().parents[1]
CLAUDE = "\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
ASTRA = "\n\nAgente: astra"


def _cargar_script():
    spec = importlib.util.spec_from_file_location("sincronia_script", RAIZ / "scripts" / "sincronia.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


sincronia = _cargar_script()
necesita_git = pytest.mark.skipif(shutil.which("git") is None, reason="sin git")


def _git(repo, *args):
    subprocess.run(
        ["git", "-c", "user.name=Prueba", "-c", "user.email=prueba@example.com",
         "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false"] + list(args),
        cwd=str(repo), check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def _commit(repo, fichero, texto, mensaje):
    ruta = repo / fichero
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto, encoding="utf-8")
    _git(repo, "add", fichero)
    _git(repo, "commit", "-q", "-m", mensaje)


def _agente(foto, agente):
    return next(a for a in foto["agentes"] if a["id"] == agente)


@pytest.fixture()
def repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q"], cwd=str(repo), check=True)
    _commit(repo, "backend/a.py", "x = 1\n", "feat: inicio" + CLAUDE)
    return repo


@pytest.fixture()
def home(tmp_path):
    # Un HOME vacio: el test no mira las sesiones de verdad de Pablo.
    carpeta = tmp_path / "home"
    carpeta.mkdir()
    return carpeta


# --- quien hizo cada cosa -----------------------------------------------------------

def test_quien_hizo_cada_commit_sale_de_la_linea_que_deja_cada_agente():
    assert sincronia.agente_del_commit("fix: algo" + CLAUDE) == "claude"
    assert sincronia.agente_del_commit("fix: algo" + ASTRA) == "astra"
    assert sincronia.agente_del_commit("fix: algo\n\nAgente: Astra") == "astra"
    assert sincronia.agente_del_commit("arreglo a mano") == "pablo"
    # Nombrar a Claude en el texto no le convierte en autor.
    assert sincronia.agente_del_commit("docs: lo revisa Claude antes de desplegar") == "pablo"


# --- lo que ha visto cada uno ---------------------------------------------------------

@necesita_git
def test_claude_ve_lo_que_astra_hizo_despues_de_ponerse_al_dia(repo, home):
    sincronia.fichar(repo, "claude", home=home)
    assert _agente(sincronia.construir_foto(repo, home=home), "claude")["estado"] == "al_dia"

    _git(repo, "checkout", "-q", "-b", "astra/reprogramar")
    _commit(repo, "backend/b.py", "y = 2\n", "fix: reprogramar a la primera" + ASTRA)

    foto = sincronia.construir_foto(repo, home=home)
    claude = _agente(foto, "claude")
    assert claude["estado"] == "atrasado"
    assert [c["asunto"] for c in claude["no_vistos"]] == ["fix: reprogramar a la primera"]
    assert claude["no_vistos"][0]["agente"] == "astra"
    assert foto["veredicto"]["color"] == "amarillo"
    assert foto["ramas_sin_integrar"] == [{"rama": "astra/reprogramar", "commits": 1}]

    # Ponerse al dia le ENSENA lo que no habia visto, y desde ese momento cuenta como visto.
    informe = sincronia.fichar(repo, "claude", home=home)
    assert "fix: reprogramar a la primera" in informe
    assert _agente(sincronia.construir_foto(repo, home=home), "claude")["estado"] == "al_dia"


@necesita_git
def test_los_commits_propios_no_cuentan_como_no_vistos(repo, home):
    sincronia.fichar(repo, "claude", home=home)
    _commit(repo, "backend/c.py", "z = 3\n", "feat: otra cosa" + CLAUDE)
    foto = sincronia.construir_foto(repo, home=home)
    assert _agente(foto, "claude")["estado"] == "al_dia"
    # Astra no se ha puesto al dia nunca: eso no es "sincronizados".
    assert _agente(foto, "astra")["estado"] == "nunca"
    assert foto["veredicto"]["color"] == "amarillo"
    assert "Astra no se ha puesto al día nunca" in foto["veredicto"]["titulo"]


@necesita_git
def test_verde_cuando_los_dos_han_visto_todo_y_no_hay_nada_a_medias(repo, home):
    sincronia.fichar(repo, "claude", home=home)
    sincronia.fichar(repo, "astra", home=home)
    foto = sincronia.construir_foto(repo, home=home)
    # Los propios fichajes (.sincronia/) no son trabajo sin guardar.
    assert all(a["sin_guardar_total"] == 0 for a in foto["arboles"]), foto["arboles"]
    assert foto["veredicto"]["color"] == "verde", foto["veredicto"]


@necesita_git
def test_trabajo_sin_guardar_reciente_es_amarillo_y_abandonado_es_rojo(repo, home):
    sincronia.fichar(repo, "claude", home=home)
    sincronia.fichar(repo, "astra", home=home)
    fichero = repo / "backend" / "a.py"
    fichero.write_text("x = 2\n", encoding="utf-8")
    ahora = dt.datetime.now(dt.timezone.utc)

    foto = sincronia.construir_foto(repo, ahora=ahora, home=home)
    assert foto["arboles"][0]["sin_guardar"] == ["backend/a.py"]
    assert foto["veredicto"]["color"] == "amarillo"
    assert "trabajando" in foto["veredicto"]["titulo"]

    # Nadie lo toca desde hace dos horas: a alguien se le acabaron los tokens a medias.
    hace_dos_horas = (ahora - dt.timedelta(hours=2)).timestamp()
    os.utime(str(fichero), (hace_dos_horas, hace_dos_horas))
    foto = sincronia.construir_foto(repo, ahora=ahora, home=home)
    assert foto["veredicto"]["color"] == "rojo"


@necesita_git
def test_el_worktree_de_astra_cuenta_igual_que_el_arbol_principal(repo, home, tmp_path):
    otro = tmp_path / "repo-astra"
    _git(repo, "worktree", "add", "-b", "astra/tarea", str(otro))
    sincronia.fichar(otro, "astra", home=home)
    (otro / "backend" / "a.py").write_text("x = 9\n", encoding="utf-8")

    foto = sincronia.construir_foto(repo, home=home)
    assert _agente(foto, "astra")["estado"] == "al_dia"
    sucios = [a for a in foto["arboles"] if a["sin_guardar_total"]]
    assert [a["rama"] for a in sucios] == ["astra/tarea"]


@necesita_git
def test_lo_que_hay_en_curso_sale_de_estado_actual(repo, home):
    (repo / "docs").mkdir()
    (repo / "docs" / "ESTADO_ACTUAL.md").write_text(
        "# Estado\n\n## En curso\n\n"
        "- **Testigo:** Astra\n- **Tarea:** reprogramar a la primera\n"
        "- **Rama:** `astra/reprogramar`\n"
        "- **Siguiente:** test que falle sin el arreglo\n\n"
        "## Otra seccion\n\n- **Tarea:** esta no es\n",
        encoding="utf-8",
    )
    en_curso = sincronia.construir_foto(repo, home=home)["en_curso"]
    assert en_curso["testigo"] == "Astra"
    assert en_curso["tarea"] == "reprogramar a la primera"
    # La pagina lo pinta como texto: las marcas de markdown no pueden verse.
    assert en_curso["rama"] == "astra/reprogramar"
    assert en_curso["siguiente"] == "test que falle sin el arreglo"


# --- el servidor ---------------------------------------------------------------------

@pytest.fixture(scope="module")
def api_module(tmp_path_factory):
    runtime_dir = tmp_path_factory.mktemp("vantelia-sincronia")
    data_dir = runtime_dir / "data"
    storage_dir = runtime_dir / "storage"
    config_path = runtime_dir / "config.json"
    (data_dir / "demo").mkdir(parents=True)
    storage_dir.mkdir(parents=True)
    (data_dir / "demo" / "info.txt").write_text("===== DEMO =====\n", encoding="utf-8")
    config_path.write_text(json.dumps({
        "demo": {
            "nombre": "Demo Sincronia",
            "icono": "DS",
            "color": "#00b1d9",
            "bienvenida": "Hola.",
            "allowed_origins": ["http://testserver"],
            "branding": {"powered_by": "Vantelia"},
            "booking": {"enabled": False, "timezone": "Europe/Madrid", "provider": "internal"},
        }
    }), encoding="utf-8")
    os.environ.update({
        "VANTELIA_DATA_DIR": str(data_dir),
        "VANTELIA_STORAGE_DIR": str(storage_dir),
        "VANTELIA_CONFIG_PATH": str(config_path),
        "OPENAI_API_KEY": "",
        "ADMIN_API_TOKEN": "test-admin-token",
        "SINCRONIA_TOKEN": "tok-sincronia",
        "PORTAL_ADMIN_EMAIL": "admin@example.com",
        "PORTAL_ADMIN_PASSWORD": "admin-password-123",
        "APP_BASE_URL": "https://app.test.local",
        "PORTAL_COOKIE_NAME": "vantelia_portal_session",
        "PORTAL_COOKIE_DOMAIN": "",
        "REMINDER_RUN_INTERVAL_MINUTES": "0",
        "WEBHOOK_DEFAULT": "",
        "EXTRA_CORS_ORIGINS": "http://testserver",
        "WHATSAPP_ACCESS_TOKEN": "",
        "WHATSAPP_APP_SECRET": "",
        "OUTREACH_DB_PATH": str(storage_dir / "outreach" / "outreach.db"),
    })
    sys.modules.pop("api", None)
    return importlib.import_module("api")


@pytest.fixture()
def client(api_module):
    # Uno nuevo por test: un login no puede colarse en el test siguiente por la cookie.
    return TestClient(api_module.app)


FOTO = {"version": 1, "generada": "2026-09-11T10:00:00Z", "veredicto": {"color": "rojo", "titulo": "Hay trabajo a medias"}}
ESCRIBE = {"Authorization": "Bearer tok-sincronia"}
ADMIN = {"Authorization": "Bearer test-admin-token"}


def test_el_servidor_guarda_la_foto_solo_con_su_token(client):
    assert client.post("/admin/sincronia", json=FOTO).status_code == 401
    assert client.post("/admin/sincronia", json=FOTO, headers={"Authorization": "Bearer otro"}).status_code == 403
    # Cada token abre solo lo suyo: el de admin tampoco escribe la foto.
    assert client.post("/admin/sincronia", json=FOTO, headers=ADMIN).status_code == 403
    assert client.post("/admin/sincronia", content=b"no es json", headers=ESCRIBE).status_code == 400
    assert client.post("/admin/sincronia", json=[1, 2], headers=ESCRIBE).status_code == 400
    assert client.post("/admin/sincronia", json={"relleno": "x" * (300 * 1024)}, headers=ESCRIBE).status_code == 413
    respuesta = client.post("/admin/sincronia", json=FOTO, headers=ESCRIBE)
    assert respuesta.status_code == 200, respuesta.text


def test_la_foto_solo_la_ve_el_admin(client):
    assert client.post("/admin/sincronia", json=FOTO, headers=ESCRIBE).status_code == 200
    assert client.get("/admin/sincronia").status_code == 401
    # El token que escribe no sirve para leer.
    assert client.get("/admin/sincronia", headers=ESCRIBE).status_code == 403
    respuesta = client.get("/admin/sincronia", headers=ADMIN)
    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["foto"]["veredicto"]["color"] == "rojo"
    assert datos["recibida"] and datos["ahora"]
    assert isinstance(datos["produccion"], dict)


def test_la_pagina_es_solo_para_el_admin(client):
    fuera = client.get("/sincronia", follow_redirects=False)
    assert fuera.status_code in (302, 307)
    assert fuera.headers["location"].startswith("/acceso")
    login = client.post("/auth/login", json={"email": "admin@example.com", "password": "admin-password-123"})
    assert login.status_code == 200, login.text
    dentro = client.get("/sincronia", cookies={"vantelia_portal_session": login.cookies["vantelia_portal_session"]})
    assert dentro.status_code == 200
    assert "Sincronía" in dentro.text
