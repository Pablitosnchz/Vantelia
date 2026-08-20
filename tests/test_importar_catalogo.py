"""El importador del Excel del salon: las dos trampas que costaron datos absurdos.

El script vive en scripts/ y solo se usa en un alta, pero lo que escribe es el
catalogo entero de un negocio: la duracion bloquea su agenda y el precio es lo
que cobra. Dos errores reales al importar un salon (ago 2026):

1. Los tiempos de un paso son DOS y se suman: lo que la profesional tarda en
   hacerlo (hoja Servicios) y lo que despues actua el producto (hoja Packs). Se
   tomaba el segundo EN LUGAR del primero, y el pack de mechas del salon --6,6 h
   de reloj-- quedaba en 3,6: encima de esa cita se colaban otras.
2. Un tratamiento de dos horas salia a 4 EUR, porque sus pasos valen 0 EUR (el
   precio real vive en otro servicio del catalogo).

Se prueban las funciones puras: no hace falta openpyxl para esto.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]


def _cargar_modulo():
    """Importa el script sin ejecutar su main ni exigir openpyxl instalado."""
    ruta = RAIZ / "scripts" / "importar_catalogo_excel.py"
    spec = importlib.util.spec_from_file_location("importar_catalogo_excel", ruta)
    modulo = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(modulo)
    except SystemExit:  # el script sale si falta openpyxl
        pytest.skip("openpyxl no instalado")
    sys.modules.setdefault("importar_catalogo_excel", modulo)
    return modulo


imp = _cargar_modulo()


def _servicio(nombre, precio_cents, minutos, categoria="COLOR", operario="Todos"):
    return {
        "nombre": nombre, "categoria": categoria, "precio_cents": precio_cents,
        "minutos": minutos, "operario": operario, "descripcion": "",
    }


def test_un_paso_dura_su_trabajo_MAS_su_espera():
    """Los dos tiempos se suman; no son alternativos.

    En la hoja de servicios esta lo que la profesional TARDA en hacer el paso; en
    la de packs, el "tiempo de exposicion" que el producto necesita despues, y
    durante el cual ella queda libre. Aqui se tomaba la exposicion EN LUGAR de la
    duracion: el pack de mechas del salon quedaba en 3,6 h cuando son 6,6, y
    encima de esa cita se colaban otras.
    """
    servicios = [_servicio("COLOR", 3000, 60)]
    packs = [{"nombre": "PACK Y", "pasos": [("COLOR", 70)]}]
    compuestos, _ = imp.componer_packs(packs, servicios)
    assert compuestos[0]["minutos"] == 130          # 60 trabajando + 70 esperando
    assert compuestos[0]["tramos"] == [{"activo": 60, "espera": 70}]


def test_un_paso_sin_espera_solo_ocupa_su_trabajo():
    """Celda vacia o cero: ese paso no tiene tiempo de exposicion."""
    servicios = [
        _servicio("GREY BLENDING CORTO", 15000, 120),
        _servicio("BRUSING CORTO", 1300, 30),
    ]
    packs = [{"nombre": "PACK X", "pasos": [("GREY BLENDING CORTO", 0), ("BRUSING CORTO", None)]}]
    compuestos, _ = imp.componer_packs(packs, servicios)
    assert compuestos[0]["minutos"] == 150          # 120 + 30, sin esperas
    assert compuestos[0]["tramos"] == [
        {"activo": 120, "espera": 0}, {"activo": 30, "espera": 0}
    ]


def test_los_tramos_dejan_la_agenda_libre_mientras_actua_el_producto():
    """El pack real del salon: 6,6 h de reloj pero solo 4 de trabajo."""
    servicios = [
        _servicio("MECHAS MUY LARGO", 11000, 105),
        _servicio("MATIZ", 3000, 30),
        _servicio("BRUSING LARGO", 1900, 60),
    ]
    packs = [{"nombre": "PACK MECHAS", "pasos": [
        ("MECHAS MUY LARGO", 90), ("MATIZ", 30), ("BRUSING LARGO", None)]}]
    compuestos, _ = imp.componer_packs(packs, servicios)
    pack = compuestos[0]
    trabajo = sum(t["activo"] for t in pack["tramos"])
    espera = sum(t["espera"] for t in pack["tramos"])
    assert (trabajo, espera, pack["minutos"]) == (195, 120, 315)


def test_un_pack_sin_precio_real_queda_a_consultar():
    """Sumar pasos de 0 EUR daba "dos horas por 4 EUR". Mejor no publicar precio."""
    servicios = [
        _servicio("APLICAR KERATINA", 0, 20),
        _servicio("SECADO Y PLANCHA", 0, 60),
        _servicio("LAVADO", 400, 15),
    ]
    packs = [{"nombre": "PACK KERATINA", "pasos": [
        ("APLICAR KERATINA", 20), ("SECADO Y PLANCHA", 60), ("LAVADO", 15)]}]
    compuestos, _ = imp.componer_packs(packs, servicios)
    assert compuestos[0]["precio_cents"] == 0  # a consultar, no 4 EUR


def test_un_pack_con_precio_coherente_se_respeta():
    servicios = [_servicio("MECHAS", 7000, 90), _servicio("MATIZ", 3000, 30)]
    packs = [{"nombre": "PACK MECHAS", "pasos": [("MECHAS", 90), ("MATIZ", 30)]}]
    compuestos, _ = imp.componer_packs(packs, servicios)
    assert compuestos[0]["precio_cents"] == 10000


def test_los_pasos_internos_no_se_venden_sueltos():
    """Valen 0 EUR y solo existen dentro de packs: no se ofrecen al cliente."""
    servicios = [_servicio("SECADO Y PLANCHA", 0, 60), _servicio("CORTE", 2000, 20)]
    packs = [{"nombre": "PACK Z", "pasos": [("SECADO Y PLANCHA", 60)]}]
    imp.componer_packs(packs, servicios)
    assert servicios[0]["solo_en_pack"] is True
    assert servicios[1]["solo_en_pack"] is False


def test_la_fianza_se_aplica_a_los_trabajos_que_nombra():
    fianzas = [
        {"nombre": "FIANZA EXTENSIONES", "precio_cents": 10000},
        {"nombre": "FIANZA MECHAS-ALISADOS-DECOLORACIONES", "precio_cents": 5000},
    ]
    assert imp.senal_para(_servicio("MECHAS CORTO", 7000, 90), fianzas) == 5000
    assert imp.senal_para(_servicio("DECOLORACION LARGO", 7500, 90), fianzas) == 5000
    assert imp.senal_para(_servicio("EXTENSIONES ADHESIVAS", 23000, 120), fianzas) == 10000
    assert imp.senal_para(_servicio("CORTE SENORA", 2000, 20), fianzas) == 0


def test_la_descripcion_no_decide_la_fianza():
    """"Elumen" se describe como "coloracion PERMANENTE": no es una permanente."""
    fianzas = [{"nombre": "FIANZA PERMANENTE", "precio_cents": 5000}]
    elumen = _servicio("ELUMEN CORTO", 3100, 30)
    elumen["descripcion"] = "aplicar coloracion permanente sin amoniaco"
    assert imp.senal_para(elumen, fianzas) == 0


def test_no_se_pide_senal_mayor_que_el_servicio():
    assert imp.pide_senal({"senal_cents": 5000, "precio_cents": 7000}) is True
    assert imp.pide_senal({"senal_cents": 5000, "precio_cents": 3000}) is False
    assert imp.pide_senal({"senal_cents": 0, "precio_cents": 7000}) is False


def test_el_equipo_sale_de_la_columna_operario():
    servicios = [
        _servicio("A", 100, 30, operario="Todos"),
        _servicio("B", 100, 30, operario="Alicia, Conchi"),
        _servicio("C", 100, 30, operario="Lorena, Alicia"),
    ]
    assert imp.equipo_del_excel(servicios) == ["Alicia", "Conchi", "Lorena"]
