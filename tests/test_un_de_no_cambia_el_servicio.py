# -*- coding: utf-8 -*-
""""Corte de señora" es "Corte señora": un "de" no puede cambiar el servicio.

POR QUE EXISTE
--------------
Medido el 11-sep-2026 contra una copia de produccion: el modelo llamo a
`crear_cita` con "Corte de señora" y el catalogo del salon tiene "Corte señora"
(20 min). No se encontraba, la duracion caia al paso de la agenda (15 min) y la
cita se cogia con un nombre que no existe: cinco minutos menos de los que hacen
falta. Ademas el estado de la reserva lo tomaba por OTRO servicio y soltaba el
bueno, asi que el resumen salia con el nombre del modelo.
"""
from __future__ import annotations

from test_booking_exhaustive import api_module, client  # noqa: F401


def _servicio(slug, nombre, minutos, activo=1):
    from backend import db

    with db._get_db_connection() as conexion:
        conexion.execute(
            "INSERT OR REPLACE INTO services (cliente_id, slug, name, duration_minutes,"
            " price_cents, is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("demo", slug, nombre, minutos, 2000, activo,
             "2026-09-11T00:00:00Z", "2026-09-11T00:00:00Z"),
        )
        conexion.commit()


def test_un_de_de_mas_no_cambia_el_servicio(api_module):  # noqa: F811
    from backend import agenda

    _servicio("corte_senora_prueba", "Corte señora prueba", 20)

    fila = agenda._find_service_by_name("demo", "Corte de señora prueba")

    assert fila is not None and fila["slug"] == "corte_senora_prueba"
    assert agenda._service_duration_minutes("demo", "Corte de señora prueba") == 20


def test_con_dos_parecidos_no_se_adivina(api_module):  # noqa: F811
    """Si quitando los "de" quedan dos candidatos, no se elige ninguno."""
    from backend import agenda

    _servicio("mechas_con_matiz_prueba", "Mechas con matiz prueba", 90)
    _servicio("mechas_del_matiz_prueba", "Mechas del matiz prueba", 60)

    assert agenda._find_service_by_name("demo", "Mechas matiz prueba") is None


def test_el_estado_no_suelta_el_servicio_por_un_de(api_module):  # noqa: F811
    from backend import reserva

    assert not reserva._es_otro_servicio("Corte señora", "Corte de señora")
    assert reserva._es_otro_servicio("Corte señora", "Corte hombre")
