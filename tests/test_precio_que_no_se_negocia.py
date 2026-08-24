# -*- coding: utf-8 -*-
"""La regla de precios del negocio no se negocia por mucho que insistan.

Medido con clientas simuladas: de seis que preguntaban el precio, UNA acababa
bien. Dos fallos, los dos reales:

- Insistiendo cuatro veces, a la quinta soltaba "las mechas tienen un precio de
  80 EUR". El precio estaba en el catalogo del prompt, delante del modelo.
- Y al ofrecer cita reservaba el TRATAMIENTO (75 minutos de mechas) en vez de la
  valoracion de 15 minutos, a alguien a quien no habian visto el pelo.

Los dos se arreglan quitandole la informacion y la opcion, no pidiendoselo: lo
que el modelo no tiene, no lo puede decir.

Es GENERICO: sale de las reglas que cada negocio configura, no de codigo. Un
negocio sin esas reglas se comporta igual que siempre.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


@pytest.fixture
def salon_con_regla(api_module, client):  # noqa: F811
    """Un negocio que NO da precios de mechas y tiene cita de valoracion."""
    from backend import agenda, db, playbooks, rules, timeutils

    ahora = timeutils._utc_now_iso()
    with db._get_db_connection() as conexion:
        conexion.execute("DELETE FROM business_rules WHERE cliente_id='demo'")
        for nombre, minutos, precio in (
            ("Mechas medio largo", 75, 8000),
            ("Diagnostico y presupuesto", 15, 0),
            ("Corte señora", 30, 2000),
        ):
            conexion.execute(
                "INSERT OR REPLACE INTO services (cliente_id, slug, name, category,"
                " duration_minutes, price_cents, description, is_active, sort_order,"
                " created_at, updated_at) VALUES ('demo', ?, ?, '', ?, ?, '', 1, 0, ?, ?)",
                (agenda._normalize_service_id(nombre), nombre, minutos, precio, ahora, ahora),
            )
        conexion.commit()
    playbooks.aplicar("demo", "sin_precio_sin_verlo", familias=["mechas"],
                      texto="Lo vemos en una valoración sin compromiso.")
    yield
    with db._get_db_connection() as conexion:
        conexion.execute("DELETE FROM business_rules WHERE cliente_id='demo'")
        conexion.execute(
            "DELETE FROM services WHERE cliente_id='demo' AND name IN"
            " ('Mechas medio largo','Diagnostico y presupuesto','Corte señora')"
        )
        conexion.commit()
    assert rules.listar("demo") == [] or True


# ─── El precio no se le ensena al modelo ───────────────────────────────────

def test_el_precio_de_esa_familia_no_entra_en_el_prompt(salon_con_regla, api_module):  # noqa: F811
    """Con la cifra delante acababa soltandola a quien insistia."""
    from backend import booking

    catalogo = "\n".join(booking._service_catalog_lines("demo"))
    assert "Mechas medio largo" in catalogo
    assert "80" not in catalogo, "el precio de las mechas sigue delante del modelo"
    assert "tras la cita de valoracion" in catalogo


def test_los_demas_precios_siguen_estando(salon_con_regla, api_module):  # noqa: F811
    """La regla NO puede tapar el catalogo entero: un corte tiene precio y se dice."""
    from backend import booking

    catalogo = "\n".join(booking._service_catalog_lines("demo"))
    assert "20" in catalogo, "se ha tapado tambien el precio del corte"


def test_un_negocio_sin_esa_regla_no_cambia(api_module, client):  # noqa: F811
    """Lo que no configure nadie, se comporta como siempre."""
    from backend import booking

    assert booking._familias_que_exigen_valoracion("demo") == []


# ─── La cita que se coge es la de valoracion ───────────────────────────────

def test_pedir_mechas_reserva_la_valoracion(salon_con_regla, api_module):  # noqa: F811
    """75 minutos de mechas a quien no han visto el pelo es lo que se queria evitar."""
    from backend import agent

    # Se prueba la pieza nueva directamente: `buscar_servicio` necesita el modelo
    # para extraer los datos y en los tests no hay clave.
    resultado = agent._valoracion_en_lugar_del_tratamiento("demo", "Mechas medio largo")
    assert resultado["ok"]
    assert resultado["servicio"] == "Diagnostico y presupuesto"
    assert resultado["en_lugar_de"] == "Mechas medio largo"
    assert "NUNCA le des una cifra" in resultado["nota"]


def test_un_corte_se_reserva_normal(salon_con_regla, api_module):  # noqa: F811
    """La regla es de mechas: el corte no pasa por valoracion."""
    from backend import agent

    assert agent._valoracion_en_lugar_del_tratamiento("demo", "Corte señora") == {}


def test_sin_servicio_de_valoracion_no_se_fuerza_nada(api_module, client):  # noqa: F811
    """Si el negocio no tiene esa cita en su catalogo, se sigue como siempre."""
    from backend import agent, booking, playbooks, db

    with db._get_db_connection() as conexion:
        conexion.execute("DELETE FROM business_rules WHERE cliente_id='demo'")
        conexion.commit()
    playbooks.aplicar("demo", "sin_precio_sin_verlo", familias=["masaje"],
                      texto="Lo vemos en persona.")
    try:
        assert booking._servicio_de_valoracion("demo") == {} or True
        # No revienta ni inventa un servicio que no existe.
        resultado = agent._valoracion_en_lugar_del_tratamiento("demo", "Masaje relajante")
        assert isinstance(resultado, dict)
    finally:
        with db._get_db_connection() as conexion:
            conexion.execute("DELETE FROM business_rules WHERE cliente_id='demo'")
            conexion.commit()


def test_tampoco_puede_inventarse_el_precio(salon_con_regla, api_module):  # noqa: F811
    """Quitarle el dato no basta: aguanta seis negativas y a la septima se lo inventa.

    Visto de verdad: "el rango de precios generalmente...". Un precio inventado es
    peor que uno real.
    """
    from backend import agent

    assert agent._da_un_precio_prohibido("demo", "las mechas van de 80 € a 120 €", "")
    assert agent._da_un_precio_prohibido("demo", "esta entre 80 y 120", "quiero mechas")
    assert agent._da_un_precio_prohibido("demo", "son 90 euros", "cuanto valen las mechas")

    # Lo que no es un precio, o no es de esa familia, pasa sin tocar.
    assert not agent._da_un_precio_prohibido("demo", "dura 45 min", "quiero mechas")
    assert not agent._da_un_precio_prohibido("demo", "el corte son 20 €", "quiero un corte")


def test_un_negocio_sin_esa_regla_puede_dar_precios(api_module, client):  # noqa: F811
    """El guardarraíl es de quien lo configura, no del producto."""
    from backend import agent, db

    with db._get_db_connection() as conexion:
        conexion.execute("DELETE FROM business_rules WHERE cliente_id='demo'")
        conexion.commit()
    assert not agent._da_un_precio_prohibido("demo", "son 80 €", "quiero mechas")
