# -*- coding: utf-8 -*-
"""Un negocio que no da precios no puede acabar dandolos por la puerta de atras.

INCIDENTE. El salon tiene configurado que no se den precios de color y mechas
("Te lo digo con sinceridad: el precio depende mucho de tu pelo... lo vemos en
una valoracion"). A "cuanto cuestan unas mechas?" el asistente contestaba:

    "Para poder darte el precio de las mechas, necesito saber como tienes el
     pelo de largo. ¿Es corto, medio, largo o extra largo?"

O sea: preguntando el largo COMO PASO PREVIO a decir una cifra que ese negocio
no da. Lo configurado en su panel se quedaba sin efecto.

La causa no era el modelo despistado: eran DOS INSTRUCCIONES DEL PROPIO CODIGO
contradiciendose en el mismo turno. Una decia "aqui no se dan precios" y la nota
del catalogo decia "si pregunta cuanto cuesta, contestale con estos datos".
Ganaba la segunda por ir despues.

Se arreglo en los dos sitios: la nota ya no invita a dar precio cuando el negocio
los oculta, la instruccion de precio prohibe expresamente ese rodeo, y va la
ULTIMA de la guia para que no se pierda entre las demas.
"""
from __future__ import annotations

import uuid

import pytest

CLIENTE = "demo"

# Dos tallas del mismo servicio con la MISMA duracion: asi el catalogo pide
# concretar la talla pero sin abanico de tiempo, que es la rama donde vivia la
# frase que invitaba a dar precio.
CATALOGO = [
    ("Tinte raiz corto", "Trabajos de color", 45),
    ("Tinte raiz largo", "Trabajos de color", 45),
]


@pytest.fixture(scope="module")
def salon_de_color(api_module):
    from backend import appstate, db, timeutils

    ahora = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        for nombre, categoria, minutos in CATALOGO:
            connection.execute(
                """
                INSERT OR REPLACE INTO services
                    (cliente_id, slug, name, duration_minutes, price_cents,
                     description, is_active, sort_order, category, created_at, updated_at)
                VALUES (?, ?, ?, ?, 4500, '', 1, 0, ?, ?, ?)
                """,
                (CLIENTE, "svc_" + uuid.uuid5(uuid.NAMESPACE_DNS, nombre).hex[:10],
                 nombre, minutos, categoria, ahora, ahora),
            )
        connection.commit()
    with appstate.state_lock:
        appstate.intent_cache.clear()
    yield
    with appstate.state_lock:
        appstate.intent_cache.clear()


class _Estado(object):
    veces_sin_precio = 0
    servicio = ""
    servicio_texto = ""


def _nota(monkeypatch, oculta):
    from backend import agent, booking, intents

    monkeypatch.setattr(booking, "precios_ocultos", lambda cliente_id: oculta)
    monkeypatch.setattr(
        intents, "extraer_datos_servicio",
        lambda cliente_id, descripcion, **kwargs: {
            "familia": "trabajos de color", "tecnica": "tinte", "talla": "",
            "para_quien": "", "edad": None, "texto": descripcion,
        },
    )
    resultado = agent._tool_buscar_servicio(CLIENTE, {"descripcion": "un tinte de raiz"})
    return resultado.get("nota", "")


def test_si_el_negocio_oculta_precios_el_catalogo_no_invita_a_darlos(
    salon_de_color, monkeypatch
):
    nota = _nota(monkeypatch, oculta=True)

    assert nota, "el catalogo tenia que pedir concretar la talla"
    assert "cuanto cuesta" not in nota
    assert "no se dan" in nota


def test_el_negocio_que_si_publica_precios_sigue_igual(salon_de_color, monkeypatch):
    """El arreglo no puede callar los precios de quien si los ensena."""
    nota = _nota(monkeypatch, oculta=False)

    assert "cuanto cuesta" in nota


def test_no_puede_pedir_el_largo_para_poder_dar_un_precio(monkeypatch):
    from backend import agent, booking

    monkeypatch.setattr(booking, "precios_ocultos", lambda cliente_id: True)
    monkeypatch.setattr(
        booking, "no_se_da_precio_de",
        lambda cliente_id, texto: {"texto": "", "familias": ["mechas"]},
    )

    salida = agent._salida_para_quien_pregunta_el_precio(
        CLIENTE, _Estado(), "cuanto cuestan unas mechas?"
    )

    assert "NO le preguntes el largo" in salida
    assert "valoracion" in salida


def test_si_el_negocio_escribio_su_texto_manda_el_suyo(monkeypatch):
    """Lo que el negocio redacta en su panel gana sobre nuestra frase generica."""
    from backend import agent, booking

    suyo = "Lo vemos en una valoracion sin compromiso y te lo decimos cerrado."
    monkeypatch.setattr(booking, "precios_ocultos", lambda cliente_id: True)
    monkeypatch.setattr(
        booking, "no_se_da_precio_de",
        lambda cliente_id, texto: {"texto": suyo, "familias": ["mechas"]},
    )

    salida = agent._salida_para_quien_pregunta_el_precio(
        CLIENTE, _Estado(), "cuanto cuestan unas mechas?"
    )

    assert suyo in salida


def test_la_instruccion_del_precio_va_la_ultima_de_la_guia():
    """Iba antes que la nota del catalogo y perdia. El orden es el arreglo."""
    import inspect

    from backend import agent

    fuente = inspect.getsource(agent.responder)
    guia = fuente[fuente.index("guia = [t for t in"):]
    guia = guia[:guia.index("]")]

    assert guia.index("cuanto_dura") < guia.index("sin_precio"), (
        "sin_precio tiene que ir DESPUES de la nota de duracion/catalogo"
    )
