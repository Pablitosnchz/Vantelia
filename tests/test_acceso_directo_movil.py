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
import json
import os
import struct

from fastapi.testclient import TestClient

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


def test_el_panel_cabe_en_una_pantalla_de_movil():
    """Reglas medidas contra un iPhone de 390px con Playwright (sep-2026).

    Sin ellas: la fila de arriba desbordaba y los iconos se montaban sobre el
    titulo; la cabecera de la agenda empujaba el panel a 524px (barra de scroll
    lateral en toda la pestana Citas); los cajones de 420px se salian por la
    izquierda; los KPIs de Ventas cortaban la cifra ("2543,00" sin el euro); y la
    ultima sub-pestana de Ventas quedaba fuera de la pantalla.
    """
    t = _html("app_ui/index.html")
    reglas = (
        ".user-chip .meta,",                      # nombre y correo fuera en movil
        ".side-panel, .booking-drawer { width: 100vw;",
        "@media (max-width: 900px) { .gcal-header { flex-wrap:wrap; } }",
        ".vsell-kpis { grid-template-columns: 1fr; }",
        'class="ventas-subtabs" style="margin-left:auto; display:flex; gap:6px; flex-wrap:wrap;"',
    )
    for regla in reglas:
        assert regla in t, "falta la regla de movil: %s" % regla
    # El titulo tiene que poder encogerse o vuelve a empujar a los iconos.
    assert "min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" in t


def test_el_manifiesto_permite_instalar_el_panel(client: TestClient):
    """Sin manifiesto, "Instalar" del navegador deja un acceso directo generico.

    Se sirve en la RAIZ a proposito: el alcance de un manifiesto es su propio
    directorio, asi que desde /brand-assets/ no cubriria /app y la instalacion
    quedaria fuera de alcance.
    """
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200
    assert "manifest" in r.headers["content-type"]
    m = json.loads(r.content.decode("utf-8"))
    assert m["start_url"] == "/app" and m["scope"] == "/"
    assert m["display"] == "standalone"
    for icono in m["icons"]:
        destino = os.path.join(RAIZ, "brand_assets", os.path.basename(icono["src"]))
        assert os.path.exists(destino), icono["src"]
        cabecera = io.open(destino, "rb").read(26)
        ancho, alto = struct.unpack(">II", cabecera[16:24])
        assert (ancho, alto) == tuple(int(x) for x in icono["sizes"].split("x"))


def test_las_dos_pantallas_enlazan_el_manifiesto():
    for nombre in PAGINAS:
        assert '<link rel="manifest" href="/manifest.webmanifest" />' in _html(nombre), nombre
