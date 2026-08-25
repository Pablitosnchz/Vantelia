# -*- coding: utf-8 -*-
"""Lo que el negocio configura no puede desaparecer al guardar.

El mismo fallo ha mordido TRES veces: se activa algo desde el portal, funciona, y
el siguiente arranque se lo come sin decir nada. Paso con el modo de reserva
conversacional (22-ago-2026), con los canales por los que sale cada aviso de cita,
y con la direccion del salon (el asistente volvio a inventarse donde estaba).

La causa era siempre la misma: `_serialize_client_config` y
`_normalize_client_config` construian un diccionario EXPLICITO, asi que lo que no
estuviera enumerado se caia en silencio -ni error, ni aviso, simplemente no esta-.

Ya no. `clients._conservar_lo_no_reconocido` invierte la regla: guardar es lo de
serie y perder es la excepcion. Los primeros tests son los tres incidentes reales;
los ultimos cierran la clase entera, para no ir tapando el cuarto.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module  # noqa: F401


@pytest.mark.parametrize("clave,valor", [
    ("estilo", "conversacional"),
    ("rescate_enabled", False),
    ("rescate_texto", "Llamanos al {telefono} y te cuadramos hueco."),
])
def test_sobrevive_al_guardar_y_volver_a_cargar(api_module, clave, valor):  # noqa: F811
    from backend import clients

    config = {
        "nombre": "Salon", "icono": "💇", "color": "#000", "bienvenida": "Hola",
        "allowed_origins": [], "booking": {"enabled": True, clave: valor},
    }
    guardado = clients._serialize_client_config(config)
    assert guardado["booking"].get(clave) == valor, (
        "%r se pierde al guardar el config" % clave
    )
    recargado = clients._normalize_client_config("demo", guardado)
    assert recargado["booking"].get(clave) == valor, (
        "%r se pierde al arrancar" % clave
    )


def test_el_modo_de_reserva_sobrevive_al_ciclo_completo(api_module):  # noqa: F811
    """El caso real: se activo en produccion y no quedaba rastro."""
    from backend import clients, whatsapp

    config = clients._normalize_client_config("demo", clients._serialize_client_config({
        "nombre": "Salon", "icono": "💇", "color": "#000", "bienvenida": "Hola",
        "allowed_origins": [], "booking": {"enabled": True, "estilo": "conversacional"},
    }))
    assert whatsapp._wa_modo_conversacional(config) is True


def test_los_canales_de_aviso_sobreviven_al_arranque(api_module, client):  # noqa: F811
    """Por que canales sale cada aviso de cita es CONFIGURACION del negocio.

    Sin registrarla en la whitelist, lo que marcaba en su portal se perdia en el
    siguiente arranque y los avisos volvian a salir solo por email: a un salon que
    trabaja por WhatsApp eso le deja al cliente sin enterarse de que le han
    cancelado la cita.
    """
    from backend import clients, textnorm

    base = dict(clients._get_client_config("demo"))
    base["message_template_channels"] = {
        "cancelled": {"email": True, "whatsapp": True, "sms": False},
        "rescheduled": {"email": True, "whatsapp": True, "sms": False},
    }
    guardado = clients._serialize_client_config(base)
    assert "message_template_channels" in guardado, "se descarta al guardar"

    recargado = clients._normalize_client_config("demo", guardado)
    canales = textnorm._normalize_message_template_channels(
        recargado.get("message_template_channels")
    )
    assert canales["cancelled"]["whatsapp"] is True
    assert canales["rescheduled"]["whatsapp"] is True


def test_la_direccion_y_el_mapa_sobreviven_al_despliegue(api_module, client):  # noqa: F811
    """Sin la direccion, el asistente se inventa donde esta el salon.

    Paso: a "¿donde estais ubicados?" contesto "en el centro de la ciudad, en una
    zona muy accesible". Se le puso la direccion, y el siguiente despliegue se la
    comio: `contacto` tambien es una whitelist y solo guardaba email y telefono.
    """
    from backend import clients

    base = dict(clients._get_client_config("demo"))
    base["contacto"] = dict(base.get("contacto") or {},
                            direccion="Calle Mayor 1, Elche",
                            mapa="https://maps.example/ficha")
    guardado = clients._serialize_client_config(base)
    assert guardado["contacto"]["direccion"] == "Calle Mayor 1, Elche"
    assert guardado["contacto"]["mapa"] == "https://maps.example/ficha"

    recargado = clients._normalize_client_config("demo", guardado)
    assert recargado["contacto"]["direccion"] == "Calle Mayor 1, Elche"
    assert recargado["contacto"]["mapa"] == "https://maps.example/ficha"


# ---------------------------------------------------------------------------
# Y de raiz: guardar es lo de serie, perder es la excepcion.
#
# Los tres tests de arriba son el mismo fallo tres veces (el modo de reserva, los
# canales de aviso, la direccion del salon): alguien configura algo, funciona, y
# el siguiente arranque se lo come porque nadie lo apunto en una lista. Los de
# abajo cierran la clase entera en vez de ir tapando casos: lo que el negocio
# escribe se conserva AUNQUE el codigo no lo conozca.
# ---------------------------------------------------------------------------


def _ida_y_vuelta(config):
    """Lo que le pasa a un config entre que se guarda y el siguiente arranque."""
    from backend import clients

    return clients._normalize_client_config("demo", clients._serialize_client_config(config))


def test_una_seccion_nueva_sobrevive_sin_apuntarla_en_ninguna_lista(api_module, client):  # noqa: F811
    from backend import clients

    base = dict(clients._get_client_config("demo"))
    base["seccion_que_nadie_registro"] = {"algo": "que el negocio configuro", "n": 3}

    vuelta = _ida_y_vuelta(base)
    assert vuelta.get("seccion_que_nadie_registro") == {"algo": "que el negocio configuro", "n": 3}


@pytest.mark.parametrize("seccion", ["booking", "contacto", "branding", "whatsapp", "voice"])
def test_una_clave_nueva_dentro_de_una_seccion_conocida_sobrevive(api_module, client, seccion):  # noqa: F811
    """Las secciones conocidas se reconstruyen clave a clave: ahi es donde se perdia."""
    from backend import clients

    base = dict(clients._get_client_config("demo"))
    base[seccion] = dict(base.get(seccion) or {}, ajuste_nuevo="valor del negocio")

    vuelta = _ida_y_vuelta(base)
    assert (vuelta.get(seccion) or {}).get("ajuste_nuevo") == "valor del negocio", (
        "un ajuste nuevo de %r se pierde entre guardar y arrancar" % seccion
    )


def test_recorre_todas_las_secciones_del_config_real(api_module, client):  # noqa: F811
    """El barrido: mete un dato en CADA seccion y comprueba que ninguna lo tira.

    Este es el test que sustituye a ir apuntando claves en una whitelist: si
    manyana alguien anyade una seccion, ya esta cubierta.
    """
    from backend import clients

    base = dict(clients._get_client_config("demo"))
    secciones = [k for k, v in base.items() if isinstance(v, dict)]
    assert len(secciones) >= 5, "el config de demo deberia tener varias secciones"
    for nombre in secciones:
        base[nombre] = dict(base[nombre], marca_de_agua=nombre)
    base["escalar_suelto"] = "no soy un diccionario"

    vuelta = _ida_y_vuelta(base)

    perdidas = [n for n in secciones if (vuelta.get(n) or {}).get("marca_de_agua") != n]
    assert not perdidas, "estas secciones se comen lo que no conocen: %s" % ", ".join(perdidas)
    assert vuelta.get("escalar_suelto") == "no soy un diccionario"
