# -*- coding: utf-8 -*-
"""WhatsApp tiene que entender lo MISMO que el chat de la web.

POR QUE EXISTE
--------------
La comprension de intenciones y las reglas del negocio se enchufaron en
`chat._process_chat_message`. WhatsApp NO las llama directamente: tiene su propio
recorrido (saludo, menu, palabras clave, bonos, disparadores por texto exacto) y
solo al final delega en ese cerebro.

Es decir: que funcione en el widget no demuestra nada sobre WhatsApp, que es el
canal que el salon quiere usar. Aqui se comprueba el recorrido de WhatsApp de
verdad, con el webhook, y que:

1. Una peticion de cita escrita de forma natural ("me pones una cita?") arranca
   el flujo guiado. Los disparadores por texto de WhatsApp son una lista de CINCO
   frases exactas ("agendar", "reservar", "cita"...): sin la comprension, todo lo
   demas se caia a la IA generica.
2. Una regla del negocio contesta su texto tambien por WhatsApp.
3. Una pregunta que el negocio tiene respondida se contesta igual por los dos
   canales.
4. Lo que el negocio configura a mano (palabras clave) sigue mandando y NO se
   reinterpreta.
"""
from __future__ import annotations

import asyncio

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401

TELEFONO = "34600333444"
NUMERO = "phone_demo"


class Capturas:
    """Sustituye los envios reales de WhatsApp y guarda lo que se mandaria."""

    def __init__(self):
        self.mensajes = []

    def instalar(self, monkeypatch):
        from backend import messaging

        async def texto(*, text="", **kwargs):
            self.mensajes.append(text)
            return True

        async def lista(*, body="", sections=None, **kwargs):
            filas = [f["title"] for s in (sections or []) for f in s.get("rows", [])]
            self.mensajes.append("%s || %s" % (body, " / ".join(filas)))
            return True

        async def botones(*, body="", buttons=None, **kwargs):
            self.mensajes.append(body)
            return True

        async def cta(*, body="", **kwargs):
            self.mensajes.append(body)
            return True

        for nombre, doble in (
            ("_send_whatsapp_text", texto), ("_send_whatsapp_list", lista),
            ("_send_whatsapp_buttons", botones), ("_send_whatsapp_cta_url", cta),
        ):
            monkeypatch.setattr(messaging, nombre, doble)


@pytest.fixture
def por_whatsapp(api_module, client, monkeypatch):  # noqa: F811
    """Manda un mensaje por el webhook y devuelve lo que respondio el asistente."""
    from backend import whatsapp

    capturas = Capturas()
    capturas.instalar(monkeypatch)
    whatsapp._wa_clear_flow("demo", TELEFONO)

    def enviar(texto):
        marca = len(capturas.mensajes)
        asyncio.run(whatsapp._handle_whatsapp_message(
            cliente_id="demo", phone_number_id=NUMERO, from_number=TELEFONO,
            incoming_text=texto, interactive_id="", request=None,
        ))
        return capturas.mensajes[marca:]

    yield enviar
    whatsapp._wa_clear_flow("demo", TELEFONO)


@pytest.fixture
def comprension_encendida(api_module, client, monkeypatch):  # noqa: F811
    """Simula el modelo: sin llamadas reales, pero con el recorrido real."""
    from backend import intents

    monkeypatch.setattr(intents, "enabled_for", lambda *a, **k: True)

    def clasificar(cliente_id, message, **kwargs):
        atajo = intents.atajo_local(message)
        if atajo:
            return {"intencion": atajo, "familia": "", "confianza": 1.0,
                    "fuente": "atajo", "qa_id": "", "qa_answer": ""}
        texto = message.lower()
        if "cita" in texto or "hueco" in texto or "reserv" in texto:
            return {"intencion": "reservar", "familia": "", "confianza": 0.9,
                    "fuente": "modelo", "qa_id": "", "qa_answer": ""}
        if "cuesta" in texto or "precio" in texto:
            return {"intencion": "precio", "familia": "alisado", "confianza": 0.9,
                    "fuente": "modelo", "qa_id": "", "qa_answer": ""}
        if "aparcar" in texto:
            return {"intencion": "info", "familia": "", "confianza": 0.9,
                    "fuente": "modelo", "qa_id": "qa1",
                    "qa_answer": "Tenemos parking en la puerta."}
        return None

    monkeypatch.setattr(intents, "classify", clasificar)
    return clasificar


@pytest.fixture
def sin_reglas(api_module, client):  # noqa: F811
    from backend import db

    def limpiar():
        with db._get_db_connection() as conexion:
            conexion.execute("DELETE FROM business_rules WHERE cliente_id='demo'")
            conexion.commit()

    limpiar()
    yield
    limpiar()


# ─── 1. Pedir cita con palabras normales ───────────────────────────────────

def test_pedir_cita_a_su_manera_arranca_el_flujo_de_whatsapp(
    por_whatsapp, comprension_encendida, sin_reglas
):
    """Los disparadores de WhatsApp son CINCO frases exactas. Esto no es ninguna."""
    from backend import whatsapp

    respuestas = por_whatsapp("me pones una cita?")
    assert respuestas, "el asistente se quedo callado"
    # El estado, no el texto: el mensaje de arranque tambien dice "servicio" y
    # daria por bueno un flujo que no se abrio.
    paso = whatsapp._wa_get_flow("demo", TELEFONO).flow
    assert paso.startswith("booking"), (
        "no se abrio el flujo guiado (paso=%r), respondio: %r" % (paso, respuestas)
    )


def test_sin_comprension_esa_misma_frase_no_arranca_nada(
    por_whatsapp, sin_reglas, monkeypatch, api_module  # noqa: F811
):
    """La prueba de que lo anterior lo hace la comprension y no otra cosa.

    Sin ella el mensaje cae al cerebro generico (aqui, un doble: en los tests no
    se llama a OpenAI) y NO se abre el flujo de reserva.
    """
    from backend import chat, intents, whatsapp

    monkeypatch.setattr(intents, "enabled_for", lambda *a, **k: False)

    async def cerebro_generico(cliente_id, message, **kwargs):
        from api_models import RespuestaChat

        return RespuestaChat(respuesta="Te cuento lo que sé del negocio.",
                             mostrar_formulario=False,
                             session_id=kwargs.get("session_id", "s"), intent="rag")

    monkeypatch.setattr(chat, "_process_chat_message", cerebro_generico)

    por_whatsapp("me pones una cita?")
    assert not whatsapp._wa_get_flow("demo", TELEFONO).flow, (
        "sin comprension no deberia haberse abierto ningun flujo de reserva"
    )


# ─── 2. Las reglas del negocio, tambien por WhatsApp ───────────────────────

def test_una_regla_del_negocio_contesta_por_whatsapp(
    por_whatsapp, comprension_encendida, sin_reglas
):
    from backend import rules

    rules.guardar("demo", nombre="Foto alisado", intenciones=["precio", "presupuesto"],
                  familias=["alisado"], accion="pedir_foto", prioridad=10,
                  texto="Mandanos una foto por detras y te decimos precio.")

    respuestas = por_whatsapp("cuanto cuesta un alisado?")
    assert any("foto por detras" in r for r in respuestas), (
        "la regla del negocio no llego a WhatsApp: %r" % respuestas
    )


# ─── 3. Misma pregunta, misma respuesta en los dos canales ─────────────────

def test_los_dos_canales_contestan_lo_mismo(
    por_whatsapp, comprension_encendida, sin_reglas, client  # noqa: F811
):
    """Una Q&A reconocida por el modelo no puede depender del canal."""
    from backend import rules

    rules.guardar("demo", nombre="Aparcar", intenciones=["info"], accion="responder",
                  texto="Hay parking justo enfrente.")

    por_wa = por_whatsapp("se puede aparcar cerca?")
    assert any("parking" in r.lower() for r in por_wa), (
        "WhatsApp no contesto lo configurado: %r" % por_wa
    )

    respuesta_web = client.post(
        "/chat",
        json={"cliente_id": "demo", "mensaje": "se puede aparcar cerca?",
              "session_id": "web-aparcar"},
        headers={"Origin": "http://testserver"},
    )
    assert respuesta_web.status_code == 200, respuesta_web.text
    texto_web = respuesta_web.json()["respuesta"].lower()
    assert "parking" in texto_web, "el chat web contesto otra cosa: %r" % texto_web


# ─── 4. Lo que el negocio escribe a mano sigue mandando ────────────────────

def test_las_palabras_clave_no_las_pisa_la_comprension(
    por_whatsapp, comprension_encendida, sin_reglas, api_module  # noqa: F811
):
    """Son configuracion literal del negocio: van ANTES, tambien en WhatsApp."""
    from backend import clients, keywords

    config = clients._get_client_config("demo")
    config.setdefault("keyword_rules", {})["enabled"] = True
    regla = keywords.create_rule(
        "demo", label="Spa", keywords=["spa"], reply="Para el spa llama al 971 747 878.",
        match_mode="any", active=True, created_by_user_id="",
    )
    try:
        respuestas = por_whatsapp("hola, queria una cita de spa")
        assert any("971 747 878" in r for r in respuestas), (
            "la palabra clave del negocio no gano: %r" % respuestas
        )
    finally:
        keywords.delete_rule("demo", regla["id"])
        config.setdefault("keyword_rules", {})["enabled"] = False


# ─── 5. No prometer lo que ese canal no tiene ──────────────────────────────

def test_no_se_promete_un_formulario_que_whatsapp_no_tiene(
    por_whatsapp, comprension_encendida, sin_reglas
):
    """La clienta leia "Te muestro el formulario" y recibia una lista.

    El texto sale del cerebro comun y WhatsApp lo reenvia tal cual antes de abrir
    su flujo guiado. En el widget web si aparece un formulario; en WhatsApp no
    existe: lo que llega es un selector de servicios.
    """
    respuestas = por_whatsapp("me pones una cita?")
    junto = " ".join(respuestas).lower()
    assert "formulario" not in junto, (
        "se le esta prometiendo un formulario que WhatsApp no tiene: %r" % respuestas
    )


def test_los_textos_de_reserva_salen_de_una_sola_fuente(api_module):  # noqa: F811
    """Estaban escritos cuatro veces: cambiar uno dejaba los otros mintiendo."""
    import inspect

    from backend import chat

    fuente = inspect.getsource(chat)
    assert fuente.count('"📅 Te muestro el formulario') == 0
    assert "BOOKING_START_TEXT" in fuente


def test_la_disponibilidad_tampoco_promete_formularios(api_module):  # noqa: F811
    """Los huecos se responden por los dos canales con el mismo texto."""
    import inspect

    from backend import rag

    fuente = inspect.getsource(rag)
    assert "te abro el formulario" not in fuente


# ─── 6. El detalle del salon vale en los dos canales ───────────────────────

def test_gracias_a_ti_tambien_en_whatsapp(
    por_whatsapp, comprension_encendida, sin_reglas, api_module  # noqa: F811
):
    """Peticion del salon: si la clienta agradece, se le responde "Gracias a ti".

    El chat web lo aplica en sus cuatro ramas; WhatsApp tiene ramas PROPIAS
    (palabras clave, saldo de bonos) que contestan antes de llegar al cerebro
    comun, y ahi se perdia.
    """
    from backend import clients, keywords

    config = clients._get_client_config("demo")
    config.setdefault("keyword_rules", {})["enabled"] = True
    regla = keywords.create_rule(
        "demo", label="Spa", keywords=["spa"], reply="Para el spa llama al 971 747 878.",
        match_mode="any", active=True, created_by_user_id="",
    )
    try:
        respuestas = por_whatsapp("gracias por lo del spa")
        junto = " ".join(respuestas).lower()
        assert "gracias a ti" in junto, (
            "la clienta agradecio y WhatsApp no le devolvio el detalle: %r" % respuestas
        )
        assert "971 747 878" in junto, "y ademas tiene que seguir contestando la regla"
    finally:
        keywords.delete_rule("demo", regla["id"])
        config.setdefault("keyword_rules", {})["enabled"] = False


def test_el_gracias_no_se_pone_dos_veces(api_module):  # noqa: F811
    """Se aplica en varias capas: tiene que ser idempotente."""
    from backend import chat

    una = chat._con_gracias_a_ti("muchas gracias", "Abrimos de 10 a 20.")
    dos = chat._con_gracias_a_ti("muchas gracias", una)
    assert una.count("Gracias a ti") == 1
    assert dos == una, "aplicarlo dos veces duplicaba el agradecimiento"

    # Y si la respuesta del negocio ya lo trae escrito, tampoco se antepone.
    propia = chat._con_gracias_a_ti("gracias!", "¡Gracias a ti, guapa! Te esperamos.")
    assert propia.count("Gracias a ti") == 1


def test_la_respuesta_del_modelo_no_se_toca(api_module):  # noqa: F811
    """El salon ya se lo pide al modelo en su prompt: no se puede pisar encima.

    Por eso `_con_gracias_a_ti` se aplica SOLO a las respuestas deterministas
    (Q&A, reglas, palabras clave) y nunca a lo que redacta el modelo.
    """
    import inspect

    from backend import chat

    # Las cuatro capas deterministas, ni una mas: palabras clave (en el turno) y
    # Q&A literal, Q&A reconocida y regla del negocio (en la decision compartida).
    fuente = (inspect.getsource(chat._process_chat_message)
              + inspect.getsource(chat.decision_del_negocio))
    assert fuente.count("_con_gracias_a_ti(") == 4


# ─── 7. La configuracion del negocio manda sobre nuestros disparadores ─────

def test_su_horario_escrito_gana_a_los_huecos_del_dia(
    por_whatsapp, comprension_encendida, sin_reglas, api_module  # noqa: F811
):
    """"horarios" disparaba la disponibilidad y se saltaba su Q&A.

    En la web ganaba su respuesta escrita; en WhatsApp, no. La misma clienta
    recibia dos cosas distintas segun donde escribiera.
    """
    import json
    import uuid

    from backend import db, timeutils

    ident = "qa_" + uuid.uuid4().hex[:10]
    ahora = timeutils._utc_now_iso()
    with db._get_db_connection() as conexion:
        conexion.execute(
            "INSERT INTO kb_qa (id, cliente_id, question, answer, tags_json, created_at, updated_at)"
            " VALUES (?, 'demo', ?, ?, ?, ?, ?)",
            (ident, "¿Cuál es vuestro horario?", "Lunes cerrado, martes de 10 a 18:30.",
             json.dumps(["horarios"]), ahora, ahora),
        )
        conexion.commit()
    try:
        respuestas = por_whatsapp("horarios")
        junto = " ".join(respuestas)
        assert "Lunes cerrado" in junto, (
            "gano el listado de huecos en vez de su horario escrito: %r" % respuestas
        )
    finally:
        with db._get_db_connection() as conexion:
            conexion.execute("DELETE FROM kb_qa WHERE id=?", (ident,))
            conexion.commit()


def test_una_regla_sobre_cancelar_se_aplica_en_whatsapp(
    por_whatsapp, comprension_encendida, sin_reglas
):
    """Antes no: el disparador de cancelar iba primero y la regla no existia."""
    from backend import rules

    rules.guardar("demo", nombre="Cancelaciones", intenciones=["cancelar"],
                  accion="responder", prioridad=5,
                  texto="Para cancelar llamanos al 966 670 924, te atendemos al momento.")

    respuestas = por_whatsapp("quiero cancelar mi cita")
    assert any("966 670 924" in r for r in respuestas), (
        "su regla de cancelaciones no se aplico: %r" % respuestas
    )


def test_sin_regla_cancelar_sigue_pidiendo_el_numero_de_reserva(
    por_whatsapp, comprension_encendida, sin_reglas
):
    """Y sin regla suya, el flujo de siempre no puede haberse roto."""
    respuestas = por_whatsapp("quiero cancelar mi cita")
    junto = " ".join(respuestas).lower()
    assert "reserva" in junto or "r-" in junto, (
        "deberia pedir el numero de reserva: %r" % respuestas
    )


def test_los_dos_canales_reconocen_las_mismas_formas_de_pedir_cita(
    por_whatsapp, sin_reglas, monkeypatch, api_module  # noqa: F811
):
    """Sin la capa de IA, WhatsApp reconocia CINCO frases exactas y la web, patrones.

    Un negocio que no active la comprension tambien merece los dos canales igual.
    """
    from backend import chat, intents, whatsapp

    monkeypatch.setattr(intents, "enabled_for", lambda *a, **k: False)

    async def cerebro_generico(cliente_id, message, **kwargs):
        from api_models import RespuestaChat

        return RespuestaChat(respuesta="...", mostrar_formulario=False,
                             session_id=kwargs.get("session_id", "s"), intent="rag")

    monkeypatch.setattr(chat, "_process_chat_message", cerebro_generico)

    por_whatsapp("quiero pedir cita")
    assert whatsapp._wa_get_flow("demo", TELEFONO).flow.startswith("booking"), (
        "'quiero pedir cita' lo reconoce la web y WhatsApp no"
    )
