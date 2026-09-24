# -*- coding: utf-8 -*-
"""El proxy de la web tiene que ver al contenedor de la app despues de cada despliegue.

POR QUE EXISTE
--------------
nginx-proxy-manager reenvia app.vantelia.es a "vantelia-app" por NOMBRE: solo resuelve
si los dos contenedores comparten una red de Docker. El 24-sep-2026 un despliegue
recreo el contenedor solo en la red por defecto del compose; la app respondia 200 por
dentro y la web publica daba 502 (unos 10 minutos, hasta conectarla a mano). La red del
proxy tiene que venir declarada en el compose de produccion para que cada despliegue la
traiga puesta.
"""
from __future__ import annotations

import os
import re

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPOSE = os.path.join(RAIZ, "deploy", "hostinger", "docker-compose.yml")


def _compose() -> str:
    with open(COMPOSE, encoding="utf-8") as fichero:
        return fichero.read()


def test_la_app_esta_en_la_red_del_proxy():
    texto = _compose()
    servicio = texto.split("\nnetworks:", 1)[0]
    redes_del_servicio = re.search(r"\n    networks:\n((?:      - .+\n)+)", servicio)
    assert redes_del_servicio, "el servicio de la app no declara redes"
    redes = re.findall(r"- (\S+)", redes_del_servicio.group(1))
    assert "proxy" in redes, "sin la red del proxy, la web publica da 502"
    assert "default" in redes, "quitar la red por defecto rompe lo que ya habla con la app por ella"


def test_la_red_del_proxy_es_la_de_nginx_proxy_manager_y_ya_existe():
    bloque = _compose().split("\nnetworks:", 1)[1]
    proxy = re.search(r"\n  proxy:\n((?:    .+\n?)+)", bloque)
    assert proxy, "falta la definicion de la red 'proxy'"
    assert "external: true" in proxy.group(1), "es la red del proxy: si compose la crea, es otra red distinta"
    assert "name: nginx-proxy-manager_default" in proxy.group(1)
