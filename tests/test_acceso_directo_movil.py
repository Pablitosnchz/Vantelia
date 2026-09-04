# -*- coding: utf-8 -*-
"""El portal se anade a la pantalla de inicio del movil como si fuera una app.

Alicia (piloto) opera desde el iPhone. Sin estas metas, "Anadir a pantalla de
inicio" abre el panel CON la barra de Safari y con una miniatura de la pagina por
icono: no parece una app y no se distingue de un marcador cualquiera.

Se vigila aqui porque el fallo es silencioso: nadie lo nota hasta que el cliente
mira su movil. El icono debe ser cuadrado y SIN transparencia (iOS no la respeta,
la pinta de negro) o se ve un cuadro negro en su pantalla de inicio.
"""
import io
import os
import struct

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGINAS = ("app_ui/index.html", "access_ui/index.html")
ICONO = os.path.join(RAIZ, "brand_assets", "apple-touch-icon.png")


def _html(nombre):
    return io.open(os.path.join(RAIZ, nombre), encoding="utf-8").read()


def test_las_dos_pantallas_se_pueden_anadir_al_inicio():
    for nombre in PAGINAS:
        t = _html(nombre)
        assert 'name="apple-mobile-web-app-capable" content="yes"' in t, nombre
        assert 'rel="apple-touch-icon"' in t, nombre
        assert 'name="apple-mobile-web-app-title" content="Vantelia"' in t, nombre


def test_el_icono_existe_donde_lo_apunta_el_html():
    # El href es /brand-assets/... y ese mount sirve el directorio brand_assets.
    for nombre in PAGINAS:
        assert '/brand-assets/apple-touch-icon.png' in _html(nombre), nombre
    assert os.path.exists(ICONO), "falta brand_assets/apple-touch-icon.png"


def test_el_icono_es_cuadrado_y_opaco():
    cabecera = io.open(ICONO, "rb").read(26)
    ancho, alto = struct.unpack(">II", cabecera[16:24])
    assert ancho == alto == 180, (ancho, alto)
    # Tipo de color 6 = RGBA y 4 = gris+alfa: iOS pintaria de negro lo transparente.
    assert cabecera[25] not in (4, 6), "el icono no puede llevar transparencia"
