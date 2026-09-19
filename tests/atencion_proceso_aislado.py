"""Consulta y rechazo de un intento persistido desde un intérprete nuevo."""
import json
import os
from pathlib import Path
import subprocess
import sys


def comprobar_intento_en_interprete_nuevo(db_path, ticket_id, *, tipo, accion, clave, solicitud):
    raiz = Path(__file__).resolve().parents[1]
    temporal = Path(db_path).resolve().parent
    entorno = {k: v for k, v in os.environ.items() if k.upper() in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP")}
    entorno.update(PYTHONPATH=str(raiz), PYTHONIOENCODING="utf-8",
        VANTELIA_DATA_DIR=str(temporal), VANTELIA_STORAGE_DIR=str(temporal),
        VANTELIA_CONFIG_PATH=str(temporal / "config_no_cargada.json"))
    datos = dict(ticket_id=ticket_id, tipo=tipo, accion=accion, clave=clave, solicitud=solicitud)
    codigo = """
import json
from pathlib import Path
import sys
import dotenv
# Este proceso no lee .env, secretos, configuración de negocio ni storage.
dotenv.load_dotenv = lambda *args, **kwargs: False
from backend import atencion_contexto, atencion_operaciones, settings
settings.DB_PATH = Path(sys.argv[1])
datos = json.loads(sys.argv[2])
fila = atencion_operaciones.consultar_intento_operacion_atencion(
    'demo', datos['ticket_id'], datos['accion'], datos['clave'], tipo=datos['tipo'])
assert fila is not None
lectura = {'estado': fila['estado'], 'result_ref': fila['result_ref']}
with atencion_contexto.turno_atencion('demo', datos['ticket_id'], datos['clave']):
    try:
        atencion_contexto.comprobar_intento_mutacion_atencion(
            'demo', datos['accion'], datos['solicitud'], tipo=datos['tipo'])
    except atencion_contexto.AtencionDetenida as exc:
        corte = {'estado': exc.estado, 'result_ref': exc.result_ref}
    else:
        raise AssertionError('El proceso nuevo concedió preparación a un intento ya registrado')
assert corte == lectura, (corte, lectura)
assert 'backend.booking' not in sys.modules and 'backend.main' not in sys.modules
print(json.dumps(corte))
"""
    resultado = subprocess.run([sys.executable, "-c", codigo, str(db_path), json.dumps(datos)],
        cwd=str(temporal), env=entorno, capture_output=True, text=True, timeout=30, check=True)
    return json.loads(resultado.stdout)
