# -*- coding: utf-8 -*-
"""El modelo lleva la conversacion; las tools no le dejan mentir.

Peticion del salon: que la IA sea inteligente, que recomiende y guie, pero que
sepa lo que necesita para agendar. Las dos primeras versiones fallaron cada una
por un lado -una maquina de pasos que no recomienda, o un prompt que decidia
distinto cada vez y llego a decir "te he reservado" sin cita-.

Esta es la arquitectura que ya usa el asistente de VOZ: el modelo decide que decir
y las TOOLS ponen la fiabilidad. Aqui se comprueba lo segundo, que es lo que no
puede depender de como venga el modelo ese dia:

* No puede ofrecer un servicio que no exista en el catalogo.
* No puede ofrecer un hueco que no este libre.
* No puede dar una cita por hecha: el numero de reserva solo sale de `crear_cita`.
* Si el modelo falla, el canal tiene que poder seguir por su cuenta.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


@pytest.fixture
def catalogo(api_module, client):  # noqa: F811
    from backend import agenda, db, timeutils

    ahora = timeutils._utc_now_iso()
    with db._get_db_connection() as conexion:
        for nombre, categoria in (("Mechas medio", "Color"), ("Corte senora", "Cortes")):
            conexion.execute(
                "INSERT OR REPLACE INTO services (cliente_id, slug, name, category,"
                " duration_minutes, price_cents, description, is_active, sort_order,"
                " created_at, updated_at) VALUES ('demo', ?, ?, ?, 30, 1000, '', 1, 0, ?, ?)",
                (agenda._normalize_service_id(nombre), nombre, categoria, ahora, ahora),
            )
        conexion.commit()
    yield
    with db._get_db_connection() as conexion:
        conexion.execute(
            "DELETE FROM services WHERE cliente_id='demo' AND name IN ('Mechas medio','Corte senora')"
        )
        conexion.commit()


# ─── Las tools son la barrera ──────────────────────────────────────────────

def test_solo_devuelve_servicios_que_existen(catalogo, api_module, monkeypatch):  # noqa: F811
    """El modelo no puede inventarse un nombre: los saca de aqui."""
    from backend import agent, intents

    monkeypatch.setattr(intents, "extraer_datos_servicio", lambda *a, **k: {
        "familia": "mechas", "tecnica": "", "talla": "medio",
        "para_quien": "", "edad": None, "texto": "mechas medias",
    })
    resultado = agent._tool_buscar_servicio("demo", {"descripcion": "mechas"})
    assert resultado["ok"] is True
    assert resultado["servicio"] == "Mechas medio"


def test_lo_que_no_existe_se_dice_con_alternativas(catalogo, api_module, monkeypatch):  # noqa: F811
    from backend import agent, intents

    monkeypatch.setattr(intents, "extraer_datos_servicio", lambda *a, **k: {
        "familia": "manicura", "tecnica": "", "talla": "",
        "para_quien": "", "edad": None, "texto": "manicura",
    })
    resultado = agent._tool_buscar_servicio("demo", {"descripcion": "manicura"})
    assert resultado["ok"] is False
    assert "servicios_parecidos" in resultado


def test_cuando_falta_un_dato_lo_dice_en_vez_de_elegir(catalogo, api_module, monkeypatch):  # noqa: F811
    """Elegir por la clienta entre tecnicas distintas no es cosa del modelo."""
    from backend import agenda, agent, db, intents, timeutils

    ahora = timeutils._utc_now_iso()
    with db._get_db_connection() as conexion:
        for nombre in ("Keratina premium medio", "Acido lactico bio premium-medio"):
            conexion.execute(
                "INSERT OR REPLACE INTO services (cliente_id, slug, name, category,"
                " duration_minutes, price_cents, description, is_active, sort_order,"
                " created_at, updated_at) VALUES ('demo', ?, ?, 'Alisados', 30, 1000, '', 1, 0, ?, ?)",
                (agenda._normalize_service_id(nombre), nombre, ahora, ahora),
            )
        conexion.commit()
    monkeypatch.setattr(intents, "extraer_datos_servicio", lambda *a, **k: {
        "familia": "alisado", "tecnica": "", "talla": "medio",
        "para_quien": "", "edad": None, "texto": "un alisado",
    })
    try:
        resultado = agent._tool_buscar_servicio("demo", {"descripcion": "un alisado"})
        assert resultado["servicio"] == ""
        assert resultado["falta"] == "tecnica"
        assert len(resultado["opciones"]) >= 2
    finally:
        with db._get_db_connection() as conexion:
            conexion.execute(
                "DELETE FROM services WHERE cliente_id='demo' AND name IN"
                " ('Keratina premium medio','Acido lactico bio premium-medio')"
            )
            conexion.commit()


# ─── El agente no puede quedarse sin plan B ────────────────────────────────

def test_sin_clave_no_se_intenta(api_module, monkeypatch):  # noqa: F811
    from backend import agent

    monkeypatch.setattr(agent.settings, "OPENAI_API_KEY", "")
    assert agent.disponible("demo") is False
    texto, creada = asyncio.run(agent.responder(
        "demo", "quiero cita", session_id="s", telefono="34600000000",
    ))
    assert texto == "" and creada is False


def test_si_el_modelo_falla_devuelve_vacio(api_module, monkeypatch):  # noqa: F811
    """Vacio = "sigue tu": el canal tira de sus listas y nadie se queda colgado."""
    import sys
    import types

    from backend import agent

    monkeypatch.setattr(agent.settings, "OPENAI_API_KEY", "sk-test")

    class ClienteRoto:
        def __init__(self, *a, **k):
            raise RuntimeError("OpenAI caido")

    modulo = types.ModuleType("openai")
    modulo.OpenAI = ClienteRoto
    monkeypatch.setitem(sys.modules, "openai", modulo)

    texto, creada = asyncio.run(agent.responder(
        "demo", "quiero cita", session_id="s", telefono="34600000000",
    ))
    assert texto == "" and creada is False


def test_las_instrucciones_le_prohiben_dar_la_cita_por_hecha(api_module):  # noqa: F811
    from backend import agent, clients

    import datetime

    texto = agent._instrucciones(
        "demo", clients._get_client_config("demo"), datetime.date(2026, 9, 1),
    )
    assert "crear_cita" in texto
    assert "NUNCA digas que esta reservada" in texto
    assert "Inventarte un servicio" in texto
    # Y las fechas se le dan hechas: calcularlas de cabeza le sale mal ("el jueves
    # que viene, 29 de agosto" siendo el jueves el 27).
    assert "no calcules fechas de cabeza" in texto
    assert "martes 1 de septiembre" in texto


def test_tiene_herramienta_para_todo_lo_que_afirma(api_module):  # noqa: F811
    """Cada cosa que el asistente afirma tiene que poder consultarla.

    Si falta una herramienta, el modelo contesta de memoria: asi dijo que un dia
    estaba cerrado sin mirar la agenda y nego un servicio que si hacen.
    """
    from backend import agent

    nombres = {h["function"]["name"] for h in agent._herramientas()}
    assert {
        "consultar_horario",        # horarios y si esta abierto AHORA
        "buscar_servicio",          # el catalogo real
        "consultar_disponibilidad",  # huecos reales
        "crear_cita",
        "consultar_cita", "cancelar_cita", "reprogramar_cita",
        "politica_del_negocio",     # lo que ESTE negocio tiene escrito
    } <= nombres, "falta una herramienta: %s" % sorted(nombres)


def test_la_politica_sale_del_negocio_no_del_modelo(api_module):  # noqa: F811
    """Es lo que hace que el asistente sirva para cualquier negocio."""
    from backend import agent

    vacio = agent._tool_politica_del_negocio("demo", {"tema": ""})
    assert vacio["ok"] is False
    sin_nada = agent._tool_politica_del_negocio("demo", {"tema": "criptomonedas"})
    assert sin_nada["hay_politica"] is False
    assert "no te inventes" in sin_nada["aviso"].lower()


def test_el_horario_dice_si_esta_abierto_ahora(api_module):  # noqa: F811
    """"¿estais abiertos ahora?" no se responde con el horario semanal escrito."""
    from backend import agent

    horario = agent._tool_consultar_horario("demo", {})
    assert horario["ok"] is True
    assert "abierto_ahora" in horario
    assert horario["semana"], "sin horario, el modelo se lo inventa"


def test_la_cita_la_crea_el_mismo_despachador_que_la_voz(api_module):  # noqa: F811
    """Una sola forma de crear una cita en todo el producto."""
    import inspect

    from backend import agent

    fuente = inspect.getsource(agent._ejecutar)
    assert "_voice_dispatch_tool" in fuente


def test_whatsapp_cae_a_las_listas_si_el_agente_no_puede(api_module):  # noqa: F811
    import inspect

    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._wa_turno_del_agente)
    assert "return False" in fuente, "tiene que poder decir que no ha podido"
    manejo = inspect.getsource(whatsapp._handle_whatsapp_message)
    assert "_wa_send_service_picker" in manejo


def test_no_le_pide_el_telefono_a_quien_escribe_por_whatsapp(client, api_module):  # noqa: F811
    """Por WhatsApp el numero viene verificado: pedirlo es absurdo y bloquea la cita.

    Paso de verdad: pidio el telefono dos veces seguidas y la conversacion murio
    ahi, sin cita, despues de que la clienta hubiera dado servicio, dia, hora y
    nombre.
    """
    from backend import agent, clients

    instrucciones = agent._instrucciones(
        "demo", clients._get_client_config("demo"),
        __import__("datetime").date(2026, 8, 22),
    )
    assert "no se lo pidas" in instrucciones.lower()
    assert "telefono ya lo tienes" in instrucciones.lower()


def test_a_la_clienta_conocida_no_le_pregunta_como_se_llama(client, api_module):  # noqa: F811
    """Si ya reservo antes, el nombre lo pone el codigo: no se lo hace repetir."""
    import asyncio

    from backend import agent, crm

    crm._crm_upsert_contact("demo", name="Marta Ruiz", phone="+34600111222", source="test")
    quien = agent._quien_escribe("demo", "+34600111222")
    assert quien["nombre"] == "Marta Ruiz"

    # Y sin nombre en los argumentos, la tool NO rechaza la cita: la completa.
    creadas = []

    async def falso_dispatch(cliente_id, nombre, argumentos_json, **kwargs):
        creadas.append(__import__("json").loads(argumentos_json))
        return {"ok": True, "booking_code": "R-9999"}

    from backend import voice

    original = voice._voice_dispatch_tool
    voice._voice_dispatch_tool = falso_dispatch
    try:
        resultado = asyncio.run(agent._ejecutar(
            "demo", "crear_cita",
            {"servicio": "Corte de señora", "fecha": "2026-08-25", "hora": "10:00"},
            telefono="+34600111222", quien=quien,
        ))
    finally:
        voice._voice_dispatch_tool = original

    assert resultado.get("ok"), resultado
    assert creadas and creadas[0]["nombre"] == "Marta Ruiz"


def test_el_telefono_del_canal_basta_para_reservar(client, api_module):  # noqa: F811
    """Por WhatsApp el numero llega verificado: la tool no puede exigir que lo dicte.

    Paso de verdad: la clienta dio servicio, dia, hora y nombre, y la reserva
    moria con "Faltan el nombre o el telefono del cliente" porque el despachador
    solo miraba los argumentos del modelo, nunca el numero del canal.
    """
    import asyncio
    import json

    from backend import voice

    recibido = {}

    async def falso_booking(cliente_id, *, nombre, telefono, **kwargs):
        recibido["telefono"] = telefono
        return {"ok": True, "booking_code": "R-1234"}

    original = voice._voice_perform_booking
    voice._voice_perform_booking = falso_booking
    try:
        resultado = asyncio.run(voice._voice_dispatch_tool(
            "demo", "crear_cita",
            json.dumps({"servicio": "Corte", "fecha": "2026-09-01",
                        "hora": "10:00", "nombre": "Marta Ruiz"}),
            from_number="34600990000",
        ))
    finally:
        voice._voice_perform_booking = original

    assert resultado.get("ok"), resultado
    assert recibido["telefono"] == "34600990000"


def test_los_argumentos_que_declara_son_los_que_lee_el_despachador(api_module):  # noqa: F811
    """Contrato entre lo que el agente ANUNCIA y lo que la tool CONSUME.

    Estuvieron desalineados: el agente declaraba `codigo` y el despachador leia
    `codigo_reserva`, asi que consultar, cancelar y cambiar una cita por su numero
    no funcionaban desde el chat ni desde WhatsApp. El asistente respondia "no
    encuentro ninguna cita con ese numero" teniendo la cita delante, y no habia
    error en ningun log: la llamada se perdia en silencio.
    """
    import inspect
    import re

    from backend import agent, voice

    # `_voice_dispatch_tool` solo envuelve; el reparto real esta en la _impl.
    fuente = inspect.getsource(voice._voice_dispatch_tool_impl)
    # Lo que el despachador lee para cada tool: args.get("...")
    bloques = re.split(r'if name == "([a-z_]+)":', fuente)
    leidos = {}
    for i in range(1, len(bloques) - 1, 2):
        leidos[bloques[i]] = set(re.findall(r'args\.get\("([a-z_]+)"', bloques[i + 1]))

    # Si la extraccion no encuentra las tools, el test no prueba nada: mejor que
    # falle a que pase en vacio.
    for imprescindible in ("crear_cita", "cancelar_cita", "reprogramar_cita", "consultar_cita"):
        assert imprescindible in leidos, (
            "no se ha podido leer que argumentos consume %r" % imprescindible
        )

    propias = {"buscar_servicio", "consultar_horario", "politica_del_negocio"}
    for herramienta in agent._herramientas():
        funcion = herramienta["function"]
        nombre = funcion["name"]
        if nombre in propias or nombre not in leidos:
            continue
        declarados = set(funcion["parameters"]["properties"])
        desconocidos = declarados - leidos[nombre] - {"fecha_texto"}
        assert not desconocidos, (
            "%s declara %s y la tool no lo lee: la llamada se perderia" % (
                nombre, sorted(desconocidos))
        )
        for obligatorio in funcion["parameters"].get("required", []):
            assert obligatorio in leidos[nombre], (
                "%s exige %r pero la tool nunca lo mira" % (nombre, obligatorio)
            )


def test_lo_hablado_hace_dias_no_cuenta(client, api_module):  # noqa: F811
    """En WhatsApp la conversacion es el telefono y no se cierra nunca.

    Paso de verdad: dias despues de preguntar por un corte, la clienta saludo de
    nuevo y pulso "Agendar cita", y el asistente contesto "para el corte, ¿que tipo
    prefieres?" a alguien que en esa conversacion no habia dicho nada.
    """
    import datetime

    from backend import agent, db, timeutils

    sesion = "s_test_historial_viejo"
    ahora = timeutils._utc_now()
    viejo = ahora - datetime.timedelta(days=2)
    with db._get_db_connection() as conexion:
        conexion.execute("DELETE FROM chat_messages WHERE session_id=?", (sesion,))
        for rol, texto, cuando in (
            ("user", "quiero un corte", viejo),
            ("assistant", "¿Que tipo de corte prefieres?", viejo),
            ("user", "hola", ahora),
        ):
            conexion.execute(
                "INSERT INTO chat_messages (session_id, cliente_id, role, content,"
                " intent, created_at) VALUES (?,?,?,?,'',?)",
                (sesion, "demo", rol, texto, timeutils._to_utc_iso(cuando)),
            )
        conexion.commit()

    recordado = " ".join(m["content"] for m in agent._historial(sesion, "demo"))
    assert "hola" in recordado
    assert "corte" not in recordado, "se cuela la conversacion de hace dos dias"

    # Pero lo dicho hace un minuto SI cuenta: "y el jueves?" tiene que entenderse.
    with db._get_db_connection() as conexion:
        conexion.execute(
            "INSERT INTO chat_messages (session_id, cliente_id, role, content,"
            " intent, created_at) VALUES (?,?,?,?,'',?)",
            (sesion, "demo", "user", "quiero mechas",
             timeutils._to_utc_iso(ahora - datetime.timedelta(minutes=1))),
        )
        conexion.commit()
    assert "mechas" in " ".join(m["content"] for m in agent._historial(sesion, "demo"))


def test_no_puede_decir_que_esta_reservada_si_no_lo_esta(api_module):  # noqa: F811
    """Es el fallo que mas caro sale: la clienta se planta en el salon y no hay hueco.

    Paso ofreciendo dia: "el corte de señora esta reservado para el martes 25",
    sin haber creado nada. Ojo con las negaciones: "aun no esta reservada" es la
    respuesta CORRECTA y lleva la misma frase dentro.
    """
    from backend import agent

    assert agent._da_la_cita_por_hecha("El corte de señora está reservado para el martes 25")
    assert agent._da_la_cita_por_hecha("Te he apuntado el jueves a las 10")
    assert agent._da_la_cita_por_hecha("Tu cita queda confirmada")

    assert not agent._da_la_cita_por_hecha("Aún no está reservada: necesito tu nombre")
    assert not agent._da_la_cita_por_hecha("Todavía no te he apuntado, me falta un dato")
    assert not agent._da_la_cita_por_hecha("Te propongo el martes 25 a las 10:00, ¿te viene bien?")


def test_pregunta_que_antes_que_cuando(api_module):  # noqa: F811
    """De lo que se quiere hacer dependen la duracion y el precio: va primero.

    Al pulsar "Agendar cita" preguntaba el dia sin saber si venia a cortarse el
    pelo o a unas mechas de tres horas. Antes se vigilaba leyendo su respuesta
    ("¿esta preguntando el dia?"); ahora la decision es del codigo y se prueba sin
    modelo: ver tests/test_estado_de_la_reserva.py.
    """
    from backend import reserva

    estado = reserva.Estado()
    reserva.anotar_intencion(estado, "reservar")
    assert reserva.que_falta(estado) == "servicio"
    assert "No propongas dias ni horas" in reserva.instruccion(estado)
