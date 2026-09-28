# -*- coding: utf-8 -*-
"""montar.sh (el puente SIP de Sara) nunca deja el puente caido si habia uno que funcionaba.

POR QUE EXISTE
--------------
28-sep-2026, revision de Astra: el script borraba el contenedor de antes y, si el nuevo no
arrancaba ("docker run" con error), `set -e` lo cortaba antes de volver a la version
anterior: sin puente, Sara no puede llamar. Tambien tiene que volver atras si arranca pero
no se registra en Zadarma, y no puede terminar con error despues de un montaje bueno.
Se ejecuta el script de verdad con un `docker` falso; se salta si no hay un bash usable.
"""
from __future__ import annotations

import os

from utiles_bash import ejecutar, ruta_posix

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MONTAR = os.path.join(RAIZ, "deploy", "sara-puente", "montar.sh")

DOCKER = """#!/bin/bash
echo "$*" >> "{registro}"
case "$1" in
  inspect) echo "imagen-vieja"; exit 0 ;;
  pull|rm) exit 0 ;;
  run)
    if [ "$2" = "--rm" ]; then echo 1000; exit 0; fi
    imagen="${{@: -1}}"
    if [ "$imagen" != "imagen-vieja" ] && [ "{nueva_falla}" = "1" ]; then exit 125; fi
    echo "$imagen" > "{estado}"; echo contenedor; exit 0 ;;
  exec)
    imagen=$(cat "{estado}" 2>/dev/null)
    if [ "$imagen" = "imagen-vieja" ] || [ "{nueva_registra}" = "1" ]; then
      echo " zadarma/sip:pbx.zadarma.com   zadarma   Registered   (exp. 290s)"
    else
      echo " zadarma/sip:pbx.zadarma.com   zadarma   Unregistered"
    fi
    exit 0 ;;
esac
exit 0
"""


def _escribir(ruta, texto, ejecutable=False):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write(texto)
    if ejecutable:
        os.chmod(ruta, 0o755)


def _montar(tmp_path, nueva_falla=False, nueva_registra=True):
    base = str(tmp_path)
    stubs = os.path.join(base, "stubs")
    registro = os.path.join(base, "docker.log")
    estado = os.path.join(base, "docker.estado")
    _escribir(os.path.join(stubs, "docker"), DOCKER.format(
        registro=ruta_posix(registro), estado=ruta_posix(estado),
        nueva_falla="1" if nueva_falla else "0", nueva_registra="1" if nueva_registra else "0"), True)
    _escribir(os.path.join(stubs, "openssl"), "#!/bin/bash\necho 00112233445566778899aabbccddeeff\n", True)
    for nombre in ("chown", "ss"):
        _escribir(os.path.join(stubs, nombre), "#!/bin/bash\nexit 0\n", True)
    destino = os.path.join(base, "sara-puente")
    for fichero in ("pjsip.conf", "extensions.conf", "modules.conf", "rtp.conf"):
        _escribir(os.path.join(destino, fichero), "%s ANTERIOR\n" % fichero)
    env_app = os.path.join(base, ".env")
    _escribir(env_app, "OTRA=1\nZADARMA_EXTENSION_USUARIO=594819-999\nZADARMA_EXTENSION_CLAVE=claveZadarma\n")
    resultado = ejecutar([ruta_posix(MONTAR)], stubs,
                         SARA_PUENTE_DESTINO=ruta_posix(destino), SARA_PUENTE_ENV=ruta_posix(env_app),
                         SARA_PUENTE_ESPERA="0", SARA_PUENTE_IMAGEN="imagen-nueva")
    with open(registro, encoding="utf-8") as f:
        ordenes = f.read()
    with open(os.path.join(destino, "pjsip.conf"), encoding="utf-8") as f:
        pjsip = f.read()
    return resultado, ordenes, pjsip


def _arranques(ordenes):
    return [l.split()[-1] for l in ordenes.splitlines() if l.startswith("run -d")]


def test_si_todo_va_bien_se_queda_el_nuevo_con_sus_credenciales(tmp_path):
    resultado, ordenes, pjsip = _montar(tmp_path)
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    assert _arranques(ordenes) == ["imagen-nueva"]
    assert "594819-999" in pjsip and "claveZadarma" in pjsip and "00112233445566778899aabbccddeeff" in pjsip
    for marcador in ("__ZADARMA_USUARIO__", "__ZADARMA_CLAVE__", "__CLAVE_ELEVENLABS__"):
        assert marcador not in pjsip, "no queda ningun marcador sin sustituir"
    with open(os.path.join(str(tmp_path), "sara-puente", "anterior", "pjsip.conf"), encoding="utf-8") as f:
        assert f.read() == "pjsip.conf ANTERIOR\n", "la configuracion de antes queda guardada"


def test_si_el_nuevo_no_arranca_vuelve_al_anterior(tmp_path):
    resultado, ordenes, pjsip = _montar(tmp_path, nueva_falla=True)
    assert resultado.returncode == 1
    assert _arranques(ordenes) == ["imagen-nueva", "imagen-vieja"], "el puente no puede quedarse caido"
    assert pjsip == "pjsip.conf ANTERIOR\n"
    assert "Vuelto a la version anterior" in resultado.stderr


def test_si_el_nuevo_no_se_registra_vuelve_al_anterior(tmp_path):
    resultado, ordenes, pjsip = _montar(tmp_path, nueva_registra=False)
    assert resultado.returncode == 1
    assert _arranques(ordenes) == ["imagen-nueva", "imagen-vieja"]
    assert pjsip == "pjsip.conf ANTERIOR\n"
