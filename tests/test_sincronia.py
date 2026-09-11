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
import io
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


@pytest.fixture(autouse=True)
def _sin_sesiones_de_verdad(monkeypatch, tmp_path):
    # Ni las sesiones de Codex ni las de Claude de este PC: cada test pone las suyas.
    monkeypatch.setenv("SINCRONIA_HOME", str(tmp_path / "casa-vacia"))


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
    # El revisor fusiona en main con el git del propio script: necesita identidad.
    _git(repo, "config", "user.name", "Prueba")
    _git(repo, "config", "user.email", "prueba@example.com")
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


# --- el buzon y el revisor: se hablan sin que Pablo haga de mensajero ---------------

class EjecutorFalso:
    """Hace de pytest, de Claude, del despliegue y de codex queue sin salir del test."""

    def __init__(self, tests_ok=True, respuesta="Sin hallazgos.\nVEREDICTO: OK", despliegue_ok=True):
        self.tests_ok = tests_ok
        self.respuesta = respuesta
        self.despliegue_ok = despliegue_ok
        self.llamadas = []

    def pytest(self, arbol):
        self.llamadas.append(("pytest", str(arbol)))
        assert (pathlib.Path(arbol) / "backend").exists(), "los tests tienen que correr sobre una copia con el codigo"
        return self.tests_ok, "1 passed" if self.tests_ok else "FAILED tests/test_x.py::test_y\n1 failed"

    def claude(self, arbol, prompt):
        self.llamadas.append(("claude", prompt))
        return self.respuesta

    def desplegar(self, raiz):
        self.llamadas.append(("desplegar", str(raiz)))
        return self.despliegue_ok, "Despliegue completado"

    def entregar(self, sesion, texto):
        self.llamadas.append(("entregar", sesion, texto))
        return True, ""


def _tipos(ejecutor):
    return [llamada[0] for llamada in ejecutor.llamadas]


def _git_salida(repo, *args):
    return subprocess.run(["git"] + list(args), cwd=str(repo), check=True,
                          stdout=subprocess.PIPE).stdout.decode("utf-8", "replace")


def _ultimo_mensaje(repo):
    return sincronia._buzon(sincronia._arboles(repo))[-1]


@pytest.fixture()
def astra(repo, tmp_path):
    """El worktree de Astra, con un commit suyo listo para revisar."""
    arbol = tmp_path / "repo-astra"
    _git(repo, "worktree", "add", "-b", "astra/tarea", str(arbol))
    _commit(arbol, "backend/b.py", "y = 2\n", "fix: reprogramar a la primera" + ASTRA)
    return arbol


@necesita_git
def test_astra_pide_revision_y_claude_la_contesta_solo(repo, astra, home):
    sincronia.fichar(astra, "astra", home=home, sesion="hilo-de-astra")
    ok, _ = sincronia.pedir_revision(astra, "reprogramar a la primera")
    assert ok
    ejecutor = EjecutorFalso()
    sincronia.revisor(repo, ejecutor=ejecutor)

    assert _tipos(ejecutor) == ["pytest", "claude", "entregar"]
    assert "fix: reprogramar a la primera" in ejecutor.llamadas[1][1]  # Claude ve los commits de Astra
    assert ejecutor.llamadas[2][1] == "hilo-de-astra"                 # y la respuesta va a SU sesion
    respuesta = _ultimo_mensaje(repo)
    assert (respuesta["tipo"], respuesta["veredicto"]) == ("revision", "ok")
    # La copia temporal donde corrieron los tests no se queda colgando.
    assert sincronia.PREFIJO_REVISION not in _git_salida(repo, "worktree", "list")

    # Contestada: la siguiente pasada del revisor no la repite.
    otra = EjecutorFalso()
    assert sincronia.revisor(repo, ejecutor=otra) == "Nada pendiente."
    assert otra.llamadas == []

    # A Astra le llega en su siguiente mensaje, sin que Pablo diga nada.
    assert "revisión OK" in sincronia.fichar(astra, "astra", home=home, solo_novedades=True)


@necesita_git
def test_con_tests_en_rojo_la_revision_es_cambios_aunque_claude_diga_ok(repo, astra):
    sincronia.pedir_revision(astra, "x")
    sincronia.revisor(repo, ejecutor=EjecutorFalso(tests_ok=False))
    respuesta = _ultimo_mensaje(repo)
    assert respuesta["veredicto"] == "cambios"
    assert "FAILED tests/test_x.py::test_y" in respuesta["texto"]


@necesita_git
def test_sin_la_linea_de_veredicto_no_cuenta_como_ok(repo, astra):
    sincronia.pedir_revision(astra, "x")
    sincronia.revisor(repo, ejecutor=EjecutorFalso(respuesta="Parece que esta bien."))
    assert _ultimo_mensaje(repo)["veredicto"] == "sin_veredicto"


@necesita_git
def test_no_se_pide_revision_de_algo_a_medias(astra):
    (astra / "backend" / "b.py").write_text("y = 3\n", encoding="utf-8")
    ok, texto = sincronia.pedir_revision(astra, "x")
    assert not ok
    assert "sin commit" in texto


@necesita_git
def test_no_se_despliega_lo_que_claude_no_ha_revisado(repo, astra):
    sincronia.pedir_despliegue(astra, "Pablo dice que si")
    ejecutor = EjecutorFalso()
    sincronia.revisor(repo, ejecutor=ejecutor)
    assert "desplegar" not in _tipos(ejecutor)
    assert _ultimo_mensaje(repo)["veredicto"] == "rechazado"


@necesita_git
def test_un_commit_despues_de_la_revision_obliga_a_revisar_otra_vez(repo, astra):
    sincronia.pedir_revision(astra, "x")
    sincronia.revisor(repo, ejecutor=EjecutorFalso())
    _commit(astra, "backend/c.py", "z = 1\n", "fix: otra cosa" + ASTRA)
    sincronia.pedir_despliegue(astra, "Pablo dice que si")
    ejecutor = EjecutorFalso()
    sincronia.revisor(repo, ejecutor=ejecutor)
    assert "desplegar" not in _tipos(ejecutor)


@necesita_git
def test_lo_revisado_se_integra_en_main_y_se_despliega(repo, astra):
    sincronia.pedir_revision(astra, "reprogramar")
    sincronia.revisor(repo, ejecutor=EjecutorFalso())
    sincronia.pedir_despliegue(astra, "Pablo dice que si")
    ejecutor = EjecutorFalso()
    sincronia.revisor(repo, ejecutor=ejecutor)
    assert _tipos(ejecutor) == ["desplegar", "entregar"]
    commit_de_astra = _git_salida(repo, "rev-parse", "astra/tarea").strip()
    assert subprocess.run(["git", "merge-base", "--is-ancestor", commit_de_astra, "main"],
                          cwd=str(repo)).returncode == 0
    assert _ultimo_mensaje(repo)["veredicto"] == "ok"


@necesita_git
def test_con_trabajo_sin_guardar_en_main_no_se_despliega(repo, astra):
    sincronia.pedir_revision(astra, "x")
    sincronia.revisor(repo, ejecutor=EjecutorFalso())
    (repo / "backend" / "a.py").write_text("x = 5\n", encoding="utf-8")
    sincronia.pedir_despliegue(astra, "Pablo dice que si")
    ejecutor = EjecutorFalso()
    sincronia.revisor(repo, ejecutor=ejecutor)
    assert "desplegar" not in _tipos(ejecutor)
    assert "sin guardar en main" in _ultimo_mensaje(repo)["texto"]


@necesita_git
def test_en_cada_mensaje_solo_habla_si_hay_algo_nuevo(repo, home, tmp_path):
    sincronia.fichar(repo, "claude", home=home)
    assert sincronia.fichar(repo, "claude", home=home, solo_novedades=True) == ""

    otro = tmp_path / "repo-astra"
    _git(repo, "worktree", "add", "-b", "astra/tarea", str(otro))
    _commit(otro, "backend/b.py", "y = 2\n", "fix: reprogramar a la primera" + ASTRA)
    sincronia.avisar(otro, "astra", "claude", "¿Miras cómo quedó reprogramar?")

    novedades = sincronia.fichar(repo, "claude", home=home, solo_novedades=True)
    assert "¿Miras cómo quedó reprogramar?" in novedades
    assert "fix: reprogramar a la primera" in novedades
    assert sincronia.fichar(repo, "claude", home=home, solo_novedades=True) == ""


def test_el_hook_de_una_sesion_de_otro_proyecto_no_ficha_a_nadie(monkeypatch, tmp_path):
    """El hook de Astra es de usuario: salta tambien en sesiones que no son de Vantelia.

    Si fichara ahi, la pagina diria que Astra esta al dia sin haber visto nada.
    Paso de verdad: un JSON que no se dejaba leer hacia caer al directorio del
    script y ficho a Astra en el repo de verdad.
    """
    otro = tmp_path / "otro-proyecto"
    otro.mkdir()
    monkeypatch.chdir(str(otro))
    monkeypatch.setattr(sincronia, "fichar", lambda *a, **k: pytest.fail("ha fichado a Astra fuera de Vantelia"))
    monkeypatch.setattr(sincronia, "_enviar_en_segundo_plano", lambda *a, **k: None)

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(otro), "session_id": "x"})))
    assert sincronia.main(["--al-dia", "astra", "--hook"]) == 0
    # JSON ilegible: manda el directorio donde se lanza el hook, que es el de la sesion.
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"cwd":"C:\\Users\\otro"}'))
    assert sincronia.main(["--al-dia", "astra", "--hook"]) == 0


@necesita_git
def test_la_primera_vez_habla_aunque_venga_del_hook_de_cada_mensaje(repo, home):
    # Una sesion abierta antes de la sincronia solo tiene el hook de cada mensaje:
    # si callara por no haber "nada nuevo", nunca se enteraria de las reglas.
    informe = sincronia.fichar(repo, "astra", home=home, solo_novedades=True)
    assert "Primera puesta al día" in informe
    assert "AGENTS.md" in informe
    # A partir de ahi, solo lo nuevo.
    assert sincronia.fichar(repo, "astra", home=home, solo_novedades=True) == ""


@necesita_git
def test_la_sesion_del_hook_se_recuerda(repo, astra, home):
    sincronia.fichar(astra, "astra", home=home, sesion="hilo-1")
    sincronia.fichar(astra, "astra", home=home)  # un fichaje sin sesion no la borra
    assert sincronia._fichajes(sincronia._arboles(repo))["astra"]["sesion"] == "hilo-1"


# --- creditos: si uno se queda sin cuota, el otro lo sabe y sigue -----------------

UUID_ASTRA = "11111111-2222-3333-4444-555555555555"
TURNO_BIEN = {"type": "event_msg", "payload": {"type": "task_complete", "last_agent_message": "Hecho."}}


def _sesion_codex(home, eventos, uuid=UUID_ASTRA, cwd="E:\\Vantelia"):
    carpeta = home / ".codex" / "sessions" / "2026" / "09" / "11"
    carpeta.mkdir(parents=True, exist_ok=True)
    fichero = carpeta / ("rollout-2026-09-11T10-41-35-%s.jsonl" % uuid)
    filas = [{"type": "session_meta", "payload": {"id": uuid, "cwd": cwd}}] + list(eventos)
    fichero.write_text("\n".join(json.dumps(fila) for fila in filas) + "\n", encoding="utf-8")


def _se_acaba_la_cuota(renueva):
    """Lo que escribe Codex de verdad cuando Astra se queda sin creditos (11-sep-2026)."""
    return [
        {"type": "event_msg", "payload": {"type": "token_count", "rate_limits": {
            "primary": {"used_percent": 100.0, "window_minutes": 300, "resets_at": int(renueva.timestamp())},
            "secondary": {"used_percent": 16.0, "window_minutes": 10080,
                          "resets_at": int(renueva.timestamp()) + 86400}}}},
        {"type": "event_msg", "payload": {"type": "task_complete", "last_agent_message": None, "error": {
            "message": "You've hit your usage limit. Upgrade to Pro or try again at 3:30 PM.",
            "codex_error_info": "usage_limit_exceeded"}}},
    ]


@necesita_git
def test_si_astra_se_queda_sin_creditos_claude_se_entera_una_vez(repo, home):
    ahora = dt.datetime.now(dt.timezone.utc)
    sincronia.fichar(repo, "claude", home=home)
    _sesion_codex(home, _se_acaba_la_cuota(ahora + dt.timedelta(hours=2)))

    foto = sincronia.construir_foto(repo, ahora=ahora, home=home)
    astra = _agente(foto, "astra")
    assert astra["sin_creditos"] and astra["creditos_hasta"]
    assert foto["veredicto"]["titulo"].startswith("Astra está sin créditos")

    novedades = sincronia.fichar(repo, "claude", home=home, solo_novedades=True)
    assert "Astra está SIN CRÉDITOS" in novedades
    assert "hazlo tú" in novedades
    # No se repite en cada mensaje: ya lo sabe.
    assert sincronia.fichar(repo, "claude", home=home, solo_novedades=True) == ""

    # Cuando vuelve a trabajar, tambien se entera.
    _sesion_codex(home, _se_acaba_la_cuota(ahora + dt.timedelta(hours=2)) + [TURNO_BIEN])
    assert "Astra vuelve a tener créditos" in sincronia.fichar(repo, "claude", home=home, solo_novedades=True)


@necesita_git
def test_la_actividad_de_astra_sale_del_ultimo_evento_y_no_del_fichero(repo, home):
    # Codex tiene el fichero abierto y Windows no le cambia la fecha hasta cerrarlo.
    _sesion_codex(home, [dict(TURNO_BIEN, timestamp="2026-09-11T11:42:51.924Z")])
    assert _agente(sincronia.construir_foto(repo, home=home), "astra")["ultima_actividad"] == "2026-09-11T11:42:51Z"


@necesita_git
def test_pasada_la_hora_de_renovacion_ya_no_cuenta_como_sin_creditos(repo, home):
    ahora = dt.datetime.now(dt.timezone.utc)
    _sesion_codex(home, _se_acaba_la_cuota(ahora - dt.timedelta(minutes=5)))
    assert not _agente(sincronia.construir_foto(repo, ahora=ahora, home=home), "astra")["sin_creditos"]


@necesita_git
def test_astra_sin_creditos_a_medias_es_rojo_y_dice_quien_sigue(repo, astra, home):
    ahora = dt.datetime.now(dt.timezone.utc)
    _sesion_codex(home, _se_acaba_la_cuota(ahora + dt.timedelta(hours=2)))
    fichero = astra / "backend" / "b.py"
    fichero.write_text("y = 3\n", encoding="utf-8")
    hace_una_hora = (ahora - dt.timedelta(hours=1)).timestamp()
    os.utime(str(fichero), (hace_una_hora, hace_una_hora))
    semaforo = sincronia.construir_foto(repo, ahora=ahora, home=home)["veredicto"]
    assert semaforo["color"] == "rojo"
    assert semaforo["titulo"] == "Astra se quedó sin créditos a medias"
    assert "Claude" in semaforo["detalle"]


class EjecutorSinCreditos(EjecutorFalso):
    def claude(self, arbol, prompt):
        self.llamadas.append(("claude", prompt))
        raise sincronia.SinCreditos("Claude AI usage limit reached")


@necesita_git
def test_si_claude_esta_sin_creditos_la_revision_espera_y_no_se_pierde(repo, astra, home):
    sincronia.pedir_revision(astra, "x")
    assert "sin créditos" in sincronia.revisor(repo, ejecutor=EjecutorSinCreditos(), home=home)
    assert len(sincronia._pendientes(sincronia._buzon(sincronia._arboles(repo)))) == 1
    assert _agente(sincronia.construir_foto(repo, home=home), "claude")["sin_creditos"]

    # Mientras dure, no se reintenta ni se gasta nada.
    espera = EjecutorFalso()
    assert "sin créditos" in sincronia.revisor(repo, ejecutor=espera, home=home)
    assert espera.llamadas == []

    # Pasada la hora, se hace sola.
    (repo / ".sincronia" / "claude_limite.json").write_text(
        json.dumps({"hasta": "2000-01-01T00:00:00Z"}), encoding="utf-8")
    vuelta = EjecutorFalso()
    sincronia.revisor(repo, ejecutor=vuelta, home=home)
    assert _tipos(vuelta)[:2] == ["pytest", "claude"]


@necesita_git
def test_la_respuesta_busca_la_sesion_de_astra_y_no_la_despierta_sin_creditos(repo, astra, home):
    # Sin hook aprobado no hay sesion apuntada: se usa su ultima sesion de Codex en Vantelia.
    _sesion_codex(home, [TURNO_BIEN])
    sincronia.pedir_revision(astra, "x")
    ejecutor = EjecutorFalso()
    sincronia.revisor(repo, ejecutor=ejecutor, home=home)
    assert ejecutor.llamadas[-1][:2] == ("entregar", UUID_ASTRA)

    # Sin creditos, entregarselo solo abriria un turno que falla: le espera en el buzon.
    _sesion_codex(home, _se_acaba_la_cuota(dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)))
    _commit(astra, "backend/c.py", "z = 1\n", "fix: otra" + ASTRA)
    sincronia.pedir_revision(astra, "y")
    otro = EjecutorFalso()
    sincronia.revisor(repo, ejecutor=otro, home=home)
    assert "entregar" not in _tipos(otro)


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
