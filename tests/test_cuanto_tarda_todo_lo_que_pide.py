# -*- coding: utf-8 -*-
"""Cuando pide varias cosas, "¿cuanto tarda?" se contesta SUMANDO.

La duenya del salon, palabra por palabra:

    "Le pregunte que queria corte y secado y le dije que que suele tardar, y me
    contesto esto y no suele tardar lo que viene en la tabla que le enseñe, que
    creo que es un corte 15 minutos y un secador aproximadamente 30. Entonces
    tendria que haberme dicho que tarda unos 45 minutos, ya depende del largo; en
    todo caso tendria que preguntar cual es tu largo para que la informacion que
    le hemos metido le sirva. Pero que ponga que hagamos un diagnostico para un
    corte y un secador no tiene sentido."

Tres cosas, y las tres se comprueban aqui:

* se SUMAN las duraciones (no se contesta solo por una),
* si falta un dato -el largo, para quien es- se PREGUNTA, y la pregunta es LA
  MISMA que hace el flujo de reserva cuando le falta ese dato, y
* nunca se manda a una cita de valoracion para saber cuanto tarda.

Las cifras salen del catalogo con el MISMO resolutor que elige el servicio al
reservar, asi que el numero que oye la clienta y el hueco que se le aparta no
pueden discrepar.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401

# Catalogo de prueba con las duraciones REALES del salon piloto (agosto 2026), no
# con numeros elegidos para que cuadre un ejemplo. Las cifras son suyas:
#   Corte señora 20 | Corte hombre 30 | Secado al aire corto 10, medio 10, largo 15
# Se copian aqui para que el test no dependa de la base de datos de produccion.
CATALOGO = [
    ("dur_corte_sra", "Corte senora", "Cortes", 20),
    ("dur_corte_hom", "Corte hombre", "Cortes", 30),
    ("dur_secado_cor", "Secado al aire corto", "Peinados", 10),
    ("dur_secado_med", "Secado al aire medio", "Peinados", 10),
    ("dur_secado_lar", "Secado al aire largo", "Peinados", 15),
]


@pytest.fixture()
def salon(api_module, client):  # noqa: F811
    """Deja el catalogo puesto y la cache de familias limpia."""
    from backend import appstate, db, timeutils

    ahora = timeutils._utc_now().isoformat()
    with db._get_db_connection() as conexion:
        for slug, nombre, categoria, minutos in CATALOGO:
            conexion.execute(
                "INSERT OR REPLACE INTO services (cliente_id, slug, name, category,"
                " duration_minutes, price_cents, description, is_active, sort_order,"
                " created_at, updated_at) VALUES ('demo',?,?,?,?,0,'',1,0,?,?)",
                (slug, nombre, categoria, minutos, ahora, ahora))
        conexion.commit()
    with appstate.state_lock:
        appstate.intent_cache.clear()
    try:
        yield "demo"
    finally:
        with db._get_db_connection() as conexion:
            conexion.execute(
                "DELETE FROM services WHERE cliente_id='demo' AND slug LIKE 'dur_%'")
            conexion.commit()
        with appstate.state_lock:
            appstate.intent_cache.clear()


def test_con_todos_los_datos_da_el_total_exacto_y_el_desglose(salon):
    """Corte senora 20 + Secado al aire largo 15 = 35, segun SU catalogo.

    OJO al numero: la duenya dijo de memoria "un corte 15 y un secador 30, o sea
    45". Su catalogo configurado dice otra cosa, y manda el catalogo -es lo que la
    agenda aparta-. Que las dos cifras no coincidan es un asunto de SUS datos, no
    del codigo, y esta anotado para que lo revise en su panel.
    """
    from backend import agent

    guia = agent._cuanto_duran_juntos(
        salon, "corte de senora y secado, lo tengo largo, cuanto tarda?")
    assert guia, "no ha sumado nada"
    assert "EXACTAMENTE 35 minutos" in guia, guia
    assert "Corte senora 20 min" in guia and "15 min" in guia, "falta el desglose"
    assert "valoracion" in guia.lower(), "tiene que prohibir mandarla a valoracion"


def test_el_largo_cambia_el_total(salon):
    """Si no cambiara, la informacion que metio el negocio no serviria de nada."""
    from backend import agent

    corto = agent._cuanto_duran_juntos(salon, "corte de senora y secado, lo tengo corto, cuanto tarda?")
    assert "EXACTAMENTE 30 minutos" in corto, corto
    largo = agent._cuanto_duran_juntos(salon, "corte de senora y secado, lo tengo largo, cuanto tarda?")
    assert "EXACTAMENTE 35 minutos" in largo, largo


def test_si_falta_un_dato_lo_pregunta_con_la_pregunta_del_catalogo(salon):
    """Y es LA MISMA pregunta que hace el flujo de reserva: un solo sitio."""
    from backend import agent, catalog_pick

    guia = agent._cuanto_duran_juntos(salon, "quiero un corte y un secado, cuanto tarda?")
    assert guia
    assert "tienes que preguntarle" in guia, guia
    esperada = catalog_pick.pregunta_para(
        catalog_pick.elegir(salon, {"familia": "cortes"}))
    assert esperada and esperada in guia, (
        "la pregunta esta escrita aparte en vez de salir del catalogo"
    )
    assert "valoracion" in guia.lower()


def test_lo_que_ya_se_sabe_no_se_tira(salon):
    """Sabe el corte y le falta el secado: lo que ya tiene se dice igual."""
    from backend import agent

    guia = agent._cuanto_duran_juntos(salon, "corte de senora y un secado, cuanto tarda?")
    assert "20 minutos" in guia, guia


def test_una_sola_cosa_no_pasa_por_aqui(salon):
    """El camino de un solo servicio ya funcionaba: no se toca."""
    from backend import agent

    assert agent._cuanto_duran_juntos(salon, "quiero un corte, cuanto tarda?") == ""


def test_lo_pregunte_como_lo_pregunte_entra_por_el_mismo_sitio(api_module):  # noqa: F811
    """El enganche en el turno: sin el, todo esto no lo lee nadie."""
    import inspect

    from backend import agent

    fuente = inspect.getsource(agent.responder)
    assert "_duracion_si_la_pregunta(" in fuente
    assert "pedido=_lo_que_ha_escrito(mensajes)" in fuente, (
        "solo mira el ultimo mensaje: 'y tambien secado' dicho aparte se pierde"
    )
    directa = inspect.getsource(agent._duracion_si_la_pregunta)
    assert "_cuanto_duran_juntos" in directa
    assert directa.index("_cuanto_duran_juntos") < directa.index("servicio_exacto"), (
        "con un servicio ya elegido contestaria solo por ese"
    )


def test_para_quien_solo_si_lo_dice(api_module):  # noqa: F811
    """Adivinarlo mal elige el servicio equivocado.

    "Un corte para mi HIJO" salia como mujer, porque "para mi" estaba en la lista.
    """
    from backend import agent

    assert agent._para_quien_dice("corte de senora") == "mujer"
    assert agent._para_quien_dice("un corte para mi hijo") == "nino"
    assert agent._para_quien_dice("corte de caballero") == "hombre"
    assert agent._para_quien_dice("quiero un corte") == ""
