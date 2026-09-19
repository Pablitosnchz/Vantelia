# -*- coding: utf-8 -*-
"""Lo pedido no se recorta al pasar por el fallback del interprete de apuntes.

Casos encontrados por lectura en la revision del 19-sep-2026. No se sustituye
catalog_pick.elegir: se usa el endpoint y el catalogo sintetico creado por la API.
"""
import copy

import pytest
from fastapi.testclient import TestClient

from conftest import DEFAULT_DEMO_CONFIG
from test_api_smoke import _portal_admin_cookies
from test_entender_el_apunte import _interpretar, _poner_servicio


@pytest.fixture
def apunte_aislado(vantelia_env_factory):
    config = copy.deepcopy(DEFAULT_DEMO_CONFIG)
    # Comportamiento legitimo por defecto: el negocio vende tambien aplicaciones
    # sueltas. La ambiguedad debe preguntarse aunque no prefiera packs.
    config['demo']['booking']['preferir_packs'] = False
    api = vantelia_env_factory(config)
    with TestClient(api.app) as client:
        yield client, _portal_admin_cookies(api)


def test_sinonimo_del_largo_no_oculta_un_pack_mucho_mas_largo(apunte_aislado):
    """Media melena y medio son la misma talla: 75 frente a 360 sigue siendo ambiguo."""
    client, cookies = apunte_aislado
    _poner_servicio(client, cookies, 'Mechas medio', 75)
    _poner_servicio(client, cookies, 'Pack mechas o balayage medio', 360)

    response = _interpretar(client, cookies, 'Ana, mechas media melena')
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['servicio'] == '', (
        'El sinonimo media melena oculta al rival de 360 minutos y permite aplicar la suelta: %s' % data)
    assert data['pregunta'] and data['candidatos'], data


def test_tecnica_pedida_ausente_no_se_sustituye_por_la_generica(apunte_aislado):
    """Pedir balayage no autoriza aplicar el generico si el catalogo no tiene esa tecnica."""
    client, cookies = apunte_aislado
    _poner_servicio(client, cookies, 'Mechas largo', 60)

    response = _interpretar(client, cookies, 'Ana, mechas balayage largo')
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['servicio'] == '', (
        'El fallback ha quitado balayage de lo pedido y aplicado el generico: %s' % data)
    assert data['duracion'] == 0, data
