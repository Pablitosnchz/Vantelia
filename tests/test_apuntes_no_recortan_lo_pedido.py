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


@pytest.mark.parametrize('servicio', ['Corte caballero (sin lavar)', 'Corte-caballero'])
def test_nombre_exacto_con_separadores_no_pide_otro_toque(apunte_aislado, servicio):
    client, cookies = apunte_aislado
    _poner_servicio(client, cookies, servicio, 20)

    response = _interpretar(client, cookies, 'Ana, ' + servicio)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['servicio'] == servicio, data
    assert data['duracion'] == 20, data
    assert not data['pregunta'] and not data['candidatos'], data


@pytest.mark.parametrize('talla, tallas_pack', [
    ('corto', 'corto o medio'), ('largo', 'medio o largo'),
])
def test_un_pack_con_dos_tallas_sigue_compitiendo(apunte_aislado, talla, tallas_pack):
    client, cookies = apunte_aislado
    suelta, pack = 'Mechas ' + talla, 'Pack mechas ' + tallas_pack
    _poner_servicio(client, cookies, suelta, 75)
    _poner_servicio(client, cookies, pack, 360)
    response = _interpretar(client, cookies, 'Ana, mechas ' + talla)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['servicio'] == '', data
    assert {suelta, pack} <= {c['servicio'] for c in data['candidatos']}, data


def test_un_servicio_con_dos_tallas_admite_cualquiera_de_las_declaradas(apunte_aislado):
    client, cookies = apunte_aislado
    servicio = 'Hidratacion chico o corto'
    _poner_servicio(client, cookies, servicio, 20)
    data = _interpretar(client, cookies, 'Ana, hidratacion corto').json()
    assert data['servicio'] == servicio and data['duracion'] == 20, data


def test_dos_tallas_pedidas_no_se_reducen_a_una_sola(apunte_aislado):
    client, cookies = apunte_aislado
    _poner_servicio(client, cookies, 'Mechas medio', 75)
    data = _interpretar(client, cookies, 'Ana, mechas corto o medio').json()
    assert data['servicio'] == '' and data['pregunta'], data


def test_las_tallas_compuestas_y_sus_alias_no_se_parten(apunte_aislado):
    from backend import catalog_pick
    for texto, todas, principal in [
        ('por los hombros', ['medio'], 'medio'),
        ('corto o medio', ['corto', 'medio'], 'medio'),
        ('medio largo', ['medio largo'], 'medio largo'),
        ('extra largo o corto', ['extra largo', 'corto'], 'extra largo'),
        ('chico o corto', ['muy corto', 'corto'], 'muy corto'),
    ]:
        assert catalog_pick.tallas_de(texto) == todas
        # La eleccion unica conserva el criterio anterior; otros canales no cambian.
        assert catalog_pick.talla_de(texto) == principal


def test_nombre_mezclado_sin_coma_ofrece_el_servicio_sin_inventar_el_titular(apunte_aislado):
    client, cookies = apunte_aislado
    _poner_servicio(client, cookies, 'Pack mechas corto', 195)
    texto = 'Carmen pack mechas corto'
    data = _interpretar(client, cookies, texto).json()
    assert data['nombre'] == texto
    assert data['servicio'] == '' and data['pregunta'], data
    assert any(c['servicio'] == 'Pack mechas corto' and c['duracion'] == 195
               for c in data['candidatos']), data
