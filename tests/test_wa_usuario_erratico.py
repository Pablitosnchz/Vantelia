# -*- coding: utf-8 -*-
"""El cliente nunca puede quedarse encerrado en un paso del flujo de WhatsApp.

Caso real (19-ago-2026), en el paso de elegir profesional:

    Pablo  > puedo ir con niños a la peluqueria?
    Bot    > No he reconocido el profesional. Pulsa una opción del listado...
    Pablo  > los niños estan admitidos en la peluqueria?
    Bot    > No he reconocido el profesional. Pulsa una opción del listado...
    Pablo  > que es el gray blending
    Bot    > No he reconocido el profesional. Pulsa una opción del listado...
    Pablo  > hola
    Bot    > No he reconocido el profesional. Pulsa una opción del listado...

Cada paso respondia su error y volvia. La guarda `not flow.flow` protegia el
flujo de TODO —incluido un saludo— "para no romper el paso a paso", y el efecto
era el contrario: una persona con una duda razonable no tenia salida.

Aqui se simula al usuario que no sigue el guion: pregunta cosas en mitad de la
reserva, escribe basura, se va y vuelve, repite, cambia de idea. La regla que se
comprueba es una sola y vale para cualquier paso: **el asistente nunca responde
dos veces seguidas lo mismo sin ofrecer una salida**.
"""
from __future__ import annotations

import asyncio

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401

TELEFONO = "34600111222"
NUMERO = "phone_demo"


class Capturas:
    """Sustituye los envios reales y guarda lo que se le habria mandado."""

    def __init__(self):
        self.mensajes = []

    def instalar(self, monkeypatch, api_module):
        from backend import messaging

        async def texto(*, text="", **kwargs):
            self.mensajes.append(("texto", text))
            return True

        async def lista(*, body="", sections=None, **kwargs):
            filas = [f["title"] for s in (sections or []) for f in s.get("rows", [])]
            self.mensajes.append(("lista", "%s || %s" % (body, " / ".join(filas))))
            return True

        async def botones(*, body="", buttons=None, **kwargs):
            self.mensajes.append(("botones", body))
            return True

        async def cta(*, body="", **kwargs):
            self.mensajes.append(("cta", body))
            return True

        for nombre, doble in (
            ("_send_whatsapp_text", texto), ("_send_whatsapp_list", lista),
            ("_send_whatsapp_buttons", botones), ("_send_whatsapp_cta_url", cta),
        ):
            monkeypatch.setattr(messaging, nombre, doble)

    @property
    def ultimo(self):
        return self.mensajes[-1][1] if self.mensajes else ""

    def desde(self, marca):
        return [t for _, t in self.mensajes[marca:]]


@pytest.fixture
def conversacion(api_module, monkeypatch):
    """Devuelve una funcion que manda un mensaje y da lo que respondio el bot."""
    from backend import chat, whatsapp

    capturas = Capturas()
    capturas.instalar(monkeypatch, api_module)
    whatsapp._wa_clear_flow("demo", TELEFONO)

    # El cerebro no debe llamar a OpenAI en tests: responde algo plausible.
    async def cerebro(cliente_id, message, **kwargs):
        from api_models import RespuestaChat

        return RespuestaChat(
            respuesta="Te respondo a eso: %s" % message[:40],
            mostrar_formulario=False,
            session_id=kwargs.get("session_id", "s"),
            intent="rag",
        )

    monkeypatch.setattr(chat, "_process_chat_message", cerebro)

    def enviar(texto, interactive_id=""):
        marca = len(capturas.mensajes)
        asyncio.run(whatsapp._handle_whatsapp_message(
            cliente_id="demo", phone_number_id=NUMERO, from_number=TELEFONO,
            incoming_text=texto, interactive_id=interactive_id, request=None,
        ))
        return capturas.desde(marca)

    enviar.capturas = capturas
    return enviar


def _flujo(whatsapp):
    return whatsapp._wa_get_flow("demo", TELEFONO).flow


# ─── El caso que reporto el usuario ────────────────────────────────────────

def test_una_duda_en_mitad_de_la_reserva_se_responde(conversacion):
    conversacion("Agendar cita")
    respuestas = conversacion("¿puedo ir con niños a la peluqueria?")
    assert respuestas, "el asistente se quedo callado"
    assert not all("No he reconocido" in r for r in respuestas), (
        "una pregunta en mitad del flujo no puede contestarse solo con el error del paso: %r" % respuestas
    )


def test_preguntar_dos_veces_no_devuelve_el_mismo_muro(conversacion):
    conversacion("Agendar cita")
    primera = conversacion("¿puedo ir con niños?")
    segunda = conversacion("los niños estan admitidos en la peluqueria?")
    assert primera != segunda or not all("No he reconocido" in r for r in primera + segunda)


def test_hola_siempre_saca_del_flujo(conversacion, api_module):
    from backend import whatsapp

    conversacion("Agendar cita")
    assert _flujo(whatsapp), "no se abrio ningun flujo"
    respuestas = conversacion("hola")
    assert not _flujo(whatsapp), "un saludo tiene que sacar del flujo"
    assert not any("No he reconocido" in r for r in respuestas)


def test_menu_siempre_saca_del_flujo(conversacion):
    from backend import whatsapp

    conversacion("Agendar cita")
    conversacion("menu")
    assert not _flujo(whatsapp)


# ─── Usuarios que no siguen el guion ───────────────────────────────────────

ERRATICOS = [
    pytest.param(["Agendar cita", "hola", "Agendar cita"], id="empieza-saluda-reempieza"),
    pytest.param(["Agendar cita", "menu", "quiero cancelar mi cita"], id="cambia-de-idea"),
    pytest.param(["Agendar cita", "", "  ", "hola"], id="mensajes-vacios"),
    pytest.param(["Agendar cita", "asdfghjkl", "1234567890", "menu"], id="escribe-basura"),
    pytest.param(["Agendar cita", "😀😀😀", "hola"], id="solo-emojis"),
    pytest.param(["quiero cancelar mi cita", "no me acuerdo del codigo", "menu"], id="cancela-sin-codigo"),
    pytest.param(["Agendar cita", "¿cuanto cuesta?", "menu"], id="pregunta-precio-y-sale"),
    pytest.param(["Agendar cita", "Agendar cita", "Agendar cita"], id="repite-la-misma-orden"),
    pytest.param(["hola", "hola", "hola"], id="saluda-tres-veces"),
    pytest.param(["Agendar cita", "x" * 900, "menu"], id="mensaje-larguisimo"),
    pytest.param(["Agendar cita", "R-9999", "menu"], id="codigo-inexistente-en-reserva"),
    pytest.param(["menu", "menu", "Agendar cita", "hola"], id="menu-repetido"),
]


@pytest.mark.parametrize("secuencia", ERRATICOS)
def test_el_usuario_erratico_nunca_se_queda_encerrado(conversacion, secuencia):
    """Ninguna secuencia puede acabar con el bot repitiendo el mismo muro.

    No se comprueba que la respuesta sea la ideal —eso depende del paso— sino que
    el cliente SIEMPRE tenga una salida: o se le responde algo distinto, o se le
    ofrece el menu.
    """
    ultimas = []
    for mensaje in secuencia:
        respuestas = conversacion(mensaje)
        if mensaje.strip():
            assert respuestas, "el asistente se quedo callado ante %r" % mensaje[:40]
        ultimas.append(tuple(respuestas))

    repetidas = [
        ultimas[i] for i in range(2, len(ultimas))
        if ultimas[i] and ultimas[i] == ultimas[i - 1] == ultimas[i - 2]
        and any("No he reconocido" in r for r in ultimas[i])
    ]
    assert not repetidas, "el bot repite el mismo error tres veces sin salida: %r" % (repetidas[:1],)


def test_el_flujo_no_sobrevive_a_terminar_una_reserva(conversacion):
    """Tras salir por el menu, el paso viejo no puede seguir capturando mensajes."""
    from backend import whatsapp

    conversacion("Agendar cita")
    conversacion("menu")
    respuestas = conversacion("¿que horario teneis?")
    assert not any("No he reconocido" in r for r in respuestas)
    assert not _flujo(whatsapp)


# ─── Abandonar a medias y volver ───────────────────────────────────────────

def test_quien_abandona_y_vuelve_al_dia_siguiente_empieza_limpio(conversacion, api_module):
    """`last_seen` se guardaba y no lo miraba nadie.

    Quien dejaba la reserva a medias reaparecia dias despues en "elige
    profesional", contestando a una conversacion que ya no recordaba. Y el
    diccionario de flujos no se vaciaba nunca.
    """
    from backend import appstate, whatsapp

    conversacion("Agendar cita")
    assert _flujo(whatsapp)

    estado = appstate.whatsapp_flows[whatsapp._wa_flow_key("demo", TELEFONO)]
    estado.last_seen -= whatsapp._WA_FLOW_TTL_SECONDS + 60  # como si fuera de ayer

    assert _flujo(whatsapp) == "", "un paso caducado no puede seguir capturando mensajes"


def test_los_flujos_caducados_no_se_acumulan_en_memoria(api_module):
    """El diccionario vive en un proceso de larga duracion: sin purga, solo crece."""
    import time as _time

    from backend import appstate, whatsapp

    appstate.whatsapp_flows.clear()
    viejo = _time.time() - whatsapp._WA_FLOW_TTL_SECONDS - 600
    for i in range(50):
        clave = whatsapp._wa_flow_key("demo", "3460000%04d" % i)
        appstate.whatsapp_flows[clave] = appstate.WAFlowState(
            cliente_id="demo", from_number="3460000%04d" % i, flow="booking_service", last_seen=viejo,
        )
    assert len(appstate.whatsapp_flows) == 50

    whatsapp._wa_get_flow("demo", TELEFONO)  # una conversacion nueva dispara la purga
    assert len(appstate.whatsapp_flows) == 1, "los flujos caducados deben desaparecer"


def test_una_conversacion_viva_no_se_purga(api_module):
    from backend import appstate, whatsapp

    appstate.whatsapp_flows.clear()
    whatsapp._wa_get_flow("demo", "34600999888").flow = "booking_service"
    whatsapp._wa_get_flow("demo", TELEFONO)
    assert whatsapp._wa_get_flow("demo", "34600999888").flow == "booking_service"


# ─── Pulsar botones de mensajes viejos ─────────────────────────────────────

BOTONES_FUERA_DE_SITIO = [
    pytest.param("svc_corte_de_pelo", "Corte de pelo", id="servicio-de-un-mensaje-viejo"),
    pytest.param("emp_noexiste", "Alguien", id="profesional-que-ya-no-esta"),
    pytest.param("cat_3", "Peinados", id="categoria-vieja"),
    pytest.param("time_10:30", "10:30", id="hora-de-otra-conversacion"),
    pytest.param("date_2020-01-01", "1 de enero", id="fecha-del-pasado"),
    pytest.param("bkok_999999", "Confirmo", id="confirmar-una-cita-que-no-existe"),
    pytest.param("bkcancel_999999", "Cancelar cita", id="cancelar-una-cita-que-no-existe"),
    pytest.param("menu_starter_99", "Opcion inexistente", id="sugerencia-que-ya-no-existe"),
]


@pytest.mark.parametrize("interactive_id,titulo", BOTONES_FUERA_DE_SITIO)
def test_pulsar_un_boton_viejo_no_rompe_el_canal(conversacion, interactive_id, titulo):
    """WhatsApp deja pulsar botones de mensajes de hace dias.

    No se exige una respuesta concreta —depende del boton— pero el asistente
    tiene que CONTESTAR algo y no reventar: una excepcion aqui deja al cliente
    sin respuesta y, si Meta reintenta, repite el efecto del mensaje.
    """
    respuestas = conversacion(titulo, interactive_id=interactive_id)
    assert respuestas, "el asistente se quedo callado ante %r" % interactive_id


def test_boton_viejo_a_mitad_de_otro_flujo(conversacion):
    """Empieza a reservar y pulsa un boton de una conversacion anterior."""
    conversacion("Agendar cita")
    respuestas = conversacion("Confirmo", interactive_id="bkok_999999")
    assert respuestas


def test_sin_texto_ni_boton_no_se_queda_callado(conversacion):
    """Audio, foto o adjunto: llegan sin texto."""
    respuestas = conversacion("")
    assert respuestas
    assert any("consulta" in r.lower() or "menu" in r.lower() or "texto" in r.lower()
               for r in respuestas), respuestas


def test_primero_se_responde_la_duda_y_luego_se_retoma_el_paso(conversacion):
    """El orden importa: contestar y DESPUES reenviar el listado.

    Sin lo segundo, el cliente recibe su respuesta y ya no sabe que estaba a
    media reserva. Sin lo primero, sigue sin respuesta. Tras "Agendar cita" el
    flujo esta en `booking_service`, asi que lo que se reenvia es el catalogo.
    """
    from backend import whatsapp

    conversacion("Agendar cita")
    marca = len(conversacion.capturas.mensajes)
    conversacion("¿puedo ir con niños a la peluqueria?")
    enviados = conversacion.capturas.mensajes[marca:]

    assert len(enviados) >= 2, "faltan la respuesta o el listado: %r" % (enviados,)
    assert "Te respondo a eso" in enviados[0][1], "la duda se contesta primero"
    # Y despues se le vuelve a ofrecer donde elegir: sin esto recibe su respuesta
    # y ya no sabe que estaba a media reserva. Que listado sea depende del paso.
    assert any(tipo == "lista" for tipo, _ in enviados[1:]), "no se retomo el paso: %r" % (enviados,)
    assert _flujo(whatsapp), "el flujo no puede perderse por el camino"


# ─── Pedir auxilio en mitad del flujo ──────────────────────────────────────

AUXILIO = ["ayuda", "socorro", "operador", "humano", "info"]


@pytest.mark.parametrize("palabra", AUXILIO)
def test_pedir_ayuda_no_se_trata_como_un_fallo_al_elegir(conversacion, palabra):
    """Quien escribe "ayuda" u "operador" no esta fallando al elegir del listado.

    Recibia "No he reconocido el servicio", que es justo lo contrario de ayudar.
    Una sola palabra no llegaba al umbral de "parece una duda" (3 palabras).
    """
    conversacion("Agendar cita")
    respuestas = conversacion(palabra)
    assert respuestas
    assert not any("No he reconocido" in r for r in respuestas), (
        "%r merece una respuesta, no el error del paso: %r" % (palabra, respuestas)
    )


def test_un_intento_fallido_de_elegir_sigue_recibiendo_el_aviso_corto(conversacion):
    """Lo contrario tambien importa: "3" o "asdf" no deben irse al cerebro."""
    conversacion("Agendar cita")
    respuestas = conversacion("asdf")
    assert any("No he reconocido" in r for r in respuestas), respuestas
