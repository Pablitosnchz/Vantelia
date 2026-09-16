"""Recuperación real: intérpretes distintos sobre una SQLite temporal."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


CHILD = r'''
import json, sys
from backend import db, reserva
db._init_database()
accion, tenant, canal_id = sys.argv[1:4]
estado = reserva.cargar(tenant, canal_id)
if accion == "ofrecer":
    estado.intencion = "reservar"
    estado.servicio = "Color"
    propuesta = reserva.preparar_propuesta_servicio(estado, servicio_id="diag",
        nombre="Diagnóstico", origen="regla:prueba", revision_config="v1")
    reserva.marcar_propuesta_ofrecida(estado, propuesta.id, "acuse-prueba")
    reserva.guardar(tenant, canal_id, estado)
elif accion == "rechazar":
    p = estado.propuesta_servicio
    assert p is not None
    assert reserva.responder_propuesta_servicio(estado, p.id, "rechaza", revision_config="v1")
    reserva.guardar(tenant, canal_id, estado)
elif accion == "rechazar_creacion":
    reserva.anotar_resultado(estado, "crear_cita", {}, {"ok": False})
    reserva.guardar(tenant, canal_id, estado)
elif accion == "validar_creacion":
    reserva.anotar_resultado(estado, "crear_cita", {}, {"pendiente_de_confirmacion": True})
    reserva.guardar(tenant, canal_id, estado)
elif accion == "competir":
    from backend import booking
    booking.alternativa_vigente_de_propuesta = lambda *a: {
        "servicio_id": "diag", "nombre": "Diagnóstico", "duracion": 20, "revision": "v1"}
    print("LISTO", flush=True)
    sys.stdin.readline()
    ok = booking.contestar_alternativa_de_precio(tenant, estado, estado.propuesta_servicio.id, sys.argv[4])
    print(json.dumps({"resultado": ok}), flush=True)
p = estado.propuesta_servicio
print(json.dumps({"id": p.id if p else None, "estado": p.estado if p else None,
                  "servicio": estado.servicio, "hecho": estado.hecho,
                  "creacion_rechazada": reserva.creacion_requiere_aclaracion(estado)}))
'''


@pytest.fixture
def proceso_estado(tmp_path):
    env = os.environ.copy()
    for key, name in (("VANTELIA_STORAGE_DIR", "storage"), ("VANTELIA_DATA_DIR", "data")):
        folder = tmp_path / name
        folder.mkdir()
        env[key] = str(folder)
    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    env["VANTELIA_CONFIG_PATH"] = str(config)
    env["PYTHONIOENCODING"] = "utf-8"

    def ejecutar(accion, tenant="uno", identidad="whatsapp:600111222"):
        result = subprocess.run([sys.executable, "-c", CHILD, accion, tenant, identidad],
                                cwd=str(Path(__file__).resolve().parents[1]), env=env,
                                capture_output=True, text=True, encoding="utf-8", timeout=60)
        assert result.returncode == 0, result.stderr[-2000:]
        return json.loads(result.stdout.strip().splitlines()[-1])
    ejecutar.env = env
    return ejecutar


def test_propuesta_enviada_se_recupera_en_otro_proceso(proceso_estado):
    ofrecida = proceso_estado("ofrecer")
    recuperada = proceso_estado("leer")
    assert recuperada == ofrecida
    assert recuperada["estado"] == "ofrecida"
    assert not recuperada["hecho"]


def test_rechazo_no_desaparece_al_reiniciar(proceso_estado):
    proceso_estado("ofrecer")
    rechazada = proceso_estado("rechazar")
    assert proceso_estado("leer") == rechazada
    assert rechazada["estado"] == "rechazada"


def test_rechazo_creacion_sobrevive_al_proceso_y_se_resuelve_al_validar(proceso_estado):
    assert proceso_estado("rechazar_creacion")["creacion_rechazada"]
    assert proceso_estado("leer")["creacion_rechazada"]
    assert not proceso_estado("leer", tenant="dos")["creacion_rechazada"]
    assert not proceso_estado("validar_creacion")["creacion_rechazada"]
    assert not proceso_estado("leer")["creacion_rechazada"]


def test_tenant_y_canal_no_comparten_autorizacion(proceso_estado):
    ofrecida = proceso_estado("ofrecer")
    assert proceso_estado("leer", tenant="dos")["id"] is None
    assert proceso_estado("leer", identidad="web:600111222")["id"] is None
    assert proceso_estado("leer")["id"] == ofrecida["id"]


def test_dos_procesos_no_publican_respuestas_contradictorias(proceso_estado):
    proceso_estado("ofrecer")
    procesos = []
    try:
        for respuesta in ("acepta", "rechaza"):
            p = subprocess.Popen([sys.executable, "-c", CHILD, "competir", "uno",
                                  "whatsapp:600111222", respuesta], env=proceso_estado.env,
                                 cwd=str(Path(__file__).resolve().parents[1]),
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, encoding="utf-8")
            procesos.append(p)
        for p in procesos:
            assert p.stdout.readline().strip() == "LISTO"
        for p in procesos:
            p.stdin.write("seguir\n")
            p.stdin.flush()
        resultados = []
        for p in procesos:
            out, err = p.communicate(timeout=60)
            assert p.returncode == 0, err[-2000:]
            resultados.append(json.loads(out.splitlines()[0])["resultado"])
        assert sorted(resultados) == [False, True]
        actual = proceso_estado("leer")
        assert actual["estado"] == ("aceptada" if resultados[0] else "rechazada")
        assert actual["servicio"] == ("Diagnóstico" if resultados[0] else "Color")
        assert not actual["hecho"]
    finally:
        for p in procesos:
            if p.poll() is None:
                p.kill()
            p.communicate()
