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


def test_la_cita_la_confirma_la_clienta_no_el_modelo(client, api_module):  # noqa: F811
    """Con `remate_manual`, `crear_cita` se BLOQUEA hasta que ella lo confirme.

    No basta con dejar de forzar la herramienta: el modelo la llamaba igual y la
    cita nacia antes de que nadie confirmase nada. Y el orden importa: frenando
    ANTES de validar el nombre se colaba uno inventado y el resumen decia
    "👤 cliente".
    """
    import asyncio

    from backend import agent

    frenada = asyncio.run(agent._ejecutar(
        "demo", "crear_cita",
        {"servicio": "Corte", "fecha": "2026-09-01", "hora": "10:00", "nombre": "Marta Ruiz"},
        telefono="34600111000", remate_manual=True,
    ))
    assert frenada["pendiente_de_confirmacion"] is True
    assert not frenada["ok"]

    # Con un nombre que no lo es, se rechaza por el nombre ANTES de frenar.
    sin_nombre = asyncio.run(agent._ejecutar(
        "demo", "crear_cita",
        {"servicio": "Corte", "fecha": "2026-09-01", "hora": "10:00", "nombre": "clienta"},
        telefono="34600111000", remate_manual=True,
    ))
    assert "nombre" in (sin_nombre.get("error") or "").lower()


def test_los_datos_de_la_llamada_frenada_no_se_pierden(api_module):  # noqa: F811
    """El nombre no lo devuelve ninguna herramienta: viaja en esa llamada.

    Sin recogerlo, el resumen para confirmar no se podia montar y la conversacion
    se quedaba colgada esperando un dato que ya se habia dado.
    """
    from backend import reserva

    estado = reserva.Estado()
    reserva.anotar_intencion(estado, "reservar")
    reserva.anotar_resultado(
        estado, "crear_cita",
        {"servicio": "Corte señora", "fecha": "2026-09-01", "hora": "10:00",
         "nombre": "Pablo Sanchez"},
        {"ok": False, "pendiente_de_confirmacion": True},
    )
    assert estado.nombre == "Pablo Sanchez"
    assert estado.servicio == "Corte señora"
    assert not estado.hecho, "una cita frenada NO esta hecha"
    assert reserva.que_falta(estado) == ""


def test_no_se_inventa_donde_esta_el_negocio(client, api_module):  # noqa: F811
    """A "¿donde estais ubicados?" contesto "en el centro de la ciudad".

    Eso no lo dice ningun dato suyo: se lo invento. Un cliente que se fia de eso no
    llega al salon.
    """
    import datetime

    from backend import agent, clients

    config = clients._get_client_config("demo")
    previo = dict(config.get("contacto") or {})
    try:
        # Sin direccion: tiene que DECIR que no la tiene, no inventarla.
        config["contacto"] = {"telefono": "600 000 000"}
        sin = agent._instrucciones("demo", config, datetime.date(2026, 9, 1))
        assert "NO tienes la direccion" in sin

        # Con direccion: va en el prompt, tal cual.
        config["contacto"] = dict(previo, direccion="Calle Mayor 1, Elche",
                                  mapa="https://maps.example/abc")
        con = agent._instrucciones("demo", config, datetime.date(2026, 9, 1))
        assert "Calle Mayor 1, Elche" in con
        assert "https://maps.example/abc" in con
        assert "NO tienes la direccion" not in con
    finally:
        config["contacto"] = previo


def test_no_puede_decir_que_acaba_de_tocar_la_agenda_si_no_la_ha_tocado(api_module):  # noqa: F811
    """Dos mentiras seguidas en pruebas reales (25-ago-2026), la misma causa.

    El guardarrail miraba `estado.hecho`, que dura TODA la conversacion. Asi que
    en cuanto se completaba una gestion quedaba desactivado para siempre:

    * "cancelar mi cita" (se cancela de verdad) -> "vuelvela a abrir" -> "tu cita
      esta de nuevo abierta". No existe reabrir una cita: en la agenda no habia
      nada, y el cliente se presenta en el salon.
    * Y en otra conversacion, "te he agendado el Grey Blending para mañana a las
      10:00" sin haber llamado a `crear_cita` en ningun momento.

    Lo que se afirma HABER HECHO se comprueba contra este turno, no contra el
    recuerdo de que algo se hizo alguna vez.
    """
    from backend import agent

    assert agent._dice_que_acaba_de_hacerlo("Tu cita está de nuevo abierta, cariño")
    assert agent._dice_que_acaba_de_hacerlo("La he reabierto sin problema")
    assert agent._dice_que_acaba_de_hacerlo("Te he agendado el Grey Blending para mañana")
    assert agent._dice_que_acaba_de_hacerlo("He cancelado tu cita de las 12:00")
    assert agent._dice_que_acaba_de_hacerlo("He reprogramado tu cita para hoy a las 12:00")

    # Lo correcto sigue pasando: negar, proponer, o contar lo que YA existe
    # (eso se comprueba aparte, contra `consultar_cita`).
    assert not agent._dice_que_acaba_de_hacerlo("Aún no te he apuntado nada")
    assert not agent._dice_que_acaba_de_hacerlo("Te propongo mañana a las 10:00, ¿te va bien?")
    assert not agent._dice_que_acaba_de_hacerlo("Tienes una cita confirmada para hoy a las 14:00")


def test_el_guardarrail_no_se_apaga_por_una_gestion_anterior(api_module):  # noqa: F811
    """La comprobacion tiene que ser POR TURNO, no por conversacion."""
    import inspect

    from backend import agent

    fuente = inspect.getsource(agent.responder)
    assert "_dice_que_acaba_de_hacerlo(texto_final) and not mutada" in fuente, (
        "afirmar que se acaba de tocar la agenda ya no se contrasta con este turno"
    )
    assert "mutada = True" in fuente, "nadie marca que una tool haya cambiado la agenda"


def test_pedir_cancelar_no_puede_acabar_en_una_reprogramacion(api_module):  # noqa: F811
    """Paso de verdad y deja al cliente con la cita puesta.

    A "quiero cancelar mi cita" el modelo llamo a `reprogramar_cita` con el MISMO
    dia y la MISMA hora, contesto "listo, he reprogramado tu cita" y en la agenda
    no habia cambiado nada: ni cancelada, ni movida. El cliente cree que la ha
    anulado y el hueco sigue ocupado.
    """
    from backend import agent

    assert agent._pide_anular_y_solo_eso("quiero cancelar mi cita")
    assert agent._pide_anular_y_solo_eso("anula la cita del jueves porfa")
    assert agent._pide_anular_y_solo_eso("al final no voy a poder ir")

    # Si habla de cambiarla, NO se fuerza: ahi hay que preguntarle cual quiere.
    assert not agent._pide_anular_y_solo_eso("quiero cancelar o cambiar mi cita")
    assert not agent._pide_anular_y_solo_eso("puedo moverla a otro dia?")
    assert not agent._pide_anular_y_solo_eso("quiero pedir cita para unas mechas")


def test_el_freno_actua_antes_de_tocar_la_agenda(api_module):  # noqa: F811
    """De poco sirve avisar despues de haber movido la cita."""
    import inspect

    from backend import agent

    fuente = inspect.getsource(agent.responder)
    freno = fuente.index("_pide_anular_y_solo_eso(mensaje)")
    ejecuta = fuente.index("resultado = await _ejecutar(")
    assert freno < ejecuta, "el freno se comprueba despues de ejecutar la herramienta"


def test_mover_una_cita_al_mismo_hueco_no_es_moverla(api_module, client):  # noqa: F811
    """La reprogramacion que no cambia nada se rechaza en el despachador.

    Es la que dejo pasar el "listo, reprogramada" con la cita intacta. Vale para
    todos los canales, tambien la voz.
    """
    import inspect

    from backend import voice

    fuente = inspect.getsource(voice._voice_reschedule_booking)
    assert 'row["booking_date"]' in fuente and 'row["booking_time"]' in fuente, (
        "no se compara con el dia y la hora que ya tenia"
    )
    assert "cancelar_cita" in fuente, "no se le dice que lo que quiere puede ser anularla"


def test_no_mueve_la_cita_a_una_hora_que_nadie_ha_pedido(api_module):  # noqa: F811
    """Paso de verdad: a "vuelvela a abrir" movio la cita de las 10:00 a las 11:00.

    Nadie hablo de las once. Mover la cita de alguien a un hueco inventado sale
    caro de verdad: el cliente se presenta a su hora y su hueco ya no existe.
    """
    from backend import agent, reserva

    estado = reserva.Estado()
    # Ni lo ha dicho ella ni se le ha ofrecido -> se frena.
    assert agent._hora_que_nadie_ha_pedido(estado, "vuelvela a abrir", "11:00")

    # Lo que ELLA dice vale, aunque lo escriba a su manera.
    assert not agent._hora_que_nadie_ha_pedido(estado, "me viene mejor a las 11", "11:00")
    assert not agent._hora_que_nadie_ha_pedido(estado, "a las 5 de la tarde", "17:00")
    assert not agent._hora_que_nadie_ha_pedido(estado, "ponme a las 12:30", "12:30")

    # Y lo que se le ha ofrecido, tambien: eso lo eligio de una lista real.
    estado.huecos = ["10:00", "10:15", "10:30"]
    assert not agent._hora_que_nadie_ha_pedido(estado, "la segunda", "10:15")
    assert agent._hora_que_nadie_ha_pedido(estado, "la segunda", "13:45")


def test_una_cita_cancelada_no_se_puede_dar_por_viva(api_module):  # noqa: F811
    """Se canceló de verdad, y al pedir "vuelvela a abrir" contesto que seguia en pie.

    Es la misma mentira de antes por otro lado: no afirmaba haber HECHO nada
    (por eso el otro freno no saltaba), afirmaba que la cita EXISTE. Y el cliente
    se planta en el salon a una hora que ya no es suya.
    """
    from backend import reserva

    estado = reserva.Estado(codigo="R-1234")
    reserva.anotar_resultado(estado, "cancelar_cita", {}, {"ok": True, "codigo_reserva": "R-1234"})
    assert estado.cancelada is True

    # Y al reves: crear o mover NO la marcan como anulada.
    otra = reserva.Estado(codigo="R-9")
    reserva.anotar_resultado(otra, "crear_cita", {}, {"ok": True, "codigo_reserva": "R-9"})
    assert otra.cancelada is False


def test_el_freno_de_la_cita_cancelada_esta_enchufado(api_module):  # noqa: F811
    import inspect

    from backend import agent

    fuente = inspect.getsource(agent.responder)
    assert "estado.cancelada and not mutada" in fuente, (
        "nadie comprueba que no se de por viva una cita anulada"
    )
    assert "se puede reabrir" in fuente, (
        "no se le explica que lo que procede es cogerle una cita nueva"
    )


def test_una_norma_del_negocio_se_consulta_no_se_recuerda(api_module):  # noqa: F811
    """Se invento el protocolo del alisado, y era peor que el de verdad.

    A "¿hay algun protocolo?" contesto "ven con el pelo limpio y seco y evita gel
    o spray". El del salon dice TRES lavados con champu y nada despues: ni
    mascarilla, ni acondicionador, ni serum. Quien siga la version inventada se
    lleva un alisado peor, y encima cree que ha hecho lo que le dijeron.
    """
    import inspect

    from backend import agent

    assert agent._pregunta_por_una_norma("hay algun protocolo?")
    assert agent._pregunta_por_una_norma("como tengo que venir para el alisado?")
    assert agent._pregunta_por_una_norma("me lavo el pelo antes de venir?")
    assert agent._pregunta_por_una_norma("como se paga la fianza?")
    assert agent._pregunta_por_una_norma("y si cancelo? que politica teneis")
    assert not agent._pregunta_por_una_norma("quiero cita para unas mechas")

    fuente = inspect.getsource(agent.responder)
    assert 'remate = "politica_del_negocio"' in fuente, (
        "nada obliga a mirar lo que el negocio ha escrito"
    )


def test_al_reservar_un_alisado_se_manda_el_protocolo_sin_preguntar(api_module, client):  # noqa: F811
    """"Aunque no pregunte por el protocolo, si se hace un alisado hay que decirselo".

    El mecanismo ya existia -una nota por servicio que sale en la confirmacion de
    WhatsApp-, pero por chat se perdia. Y en el catalogo del salon estaba puesta
    en unos servicios si y en otros no: los PACKS, que son justo los que se
    reservan cuando alguien pide un alisado, la tenian vacia.
    """
    import inspect

    from backend import agent, booking

    fuente = inspect.getsource(agent.responder)
    assert "avisale_de" in fuente, "por chat no se le cuenta como venir preparada"
    assert "_nota_del_servicio" in fuente

    # Y la fuente es la nota del negocio, no un texto nuestro.
    assert "booking_note" in inspect.getsource(booking.service_booking_note)


def test_no_le_suelta_dos_veces_la_misma_frase(api_module):  # noqa: F811
    """El fallo mas frecuente de las tres mediciones: 33-35 de cada 100.

    Tres de cada cuatro veces pasa cuando el negocio tiene que decir que NO -no
    damos precios, no puedo aconsejarte sin verte, eso no lo hacemos-: la clienta
    insiste y recibe el mismo parrafo copiado. Para quien escribe eso es un muro,
    y se va.
    """
    from backend import agent

    frase = ("Sin ver tu cabello no puedo decirte cual te recomendariamos. "
             "Si coges cita te asesoramos en persona.")
    historial = [{"role": "user", "content": "hola"},
                 {"role": "assistant", "content": frase}]

    assert agent._ya_dijo_esto(historial, frase)
    assert agent._ya_dijo_esto(historial, frase.upper()), "no depende de mayusculas"

    # Otra respuesta distinta pasa.
    assert not agent._ya_dijo_esto(historial, "Te cojo la cita el jueves a las 10, ¿te va bien?")
    # Y los acuses cortos no cuentan: repetir "perfecto" no molesta a nadie.
    assert not agent._ya_dijo_esto([{"role": "assistant", "content": "Perfecto 😊"}], "Perfecto 😊")


def test_el_freno_de_repetirse_esta_enchufado(api_module):  # noqa: F811
    import inspect

    from backend import agent

    fuente = inspect.getsource(agent.responder)
    assert "_ya_dijo_esto(historial, texto_final)" in fuente, (
        "nada impide que suelte la misma frase dos veces"
    )


def test_quedarse_sin_hueco_no_es_estar_cerrado(api_module, client):  # noqa: F811
    """Dijo "manyana estamos cerrados" un jueves que se abre de 10:00 a 20:30.

    Lo unico que pasaba es que no cabia un alisado de casi cuatro horas. Para el
    cliente no es lo mismo: si le dices que cierras, se va a otro sitio; si le
    dices que ese dia lo tienes completo, pregunta por otro.
    """
    import inspect

    from backend import agent, voice

    assert agent._dice_que_cierran("Cariño, mañana estamos cerrados 😔")
    assert agent._dice_que_cierran("Ese día no abrimos")
    assert not agent._dice_que_cierran("Ese día lo tengo completo, ¿te miro el viernes?")

    fuente = inspect.getsource(agent.responder)
    assert "_dice_que_cierran(texto_final)" in fuente, "nada lo impide"
    assert "dias_abiertos_vistos" in fuente, "no se sabe si el dia abria o no"

    # Y la herramienta lo dice claro, para todos los canales.
    disponibilidad = inspect.getsource(voice._voice_check_availability)
    assert "dia_cerrado" in disponibilidad and "nota_del_dia" in disponibilidad


def test_sabe_si_un_dia_el_negocio_abre(api_module, client):  # noqa: F811
    from backend import voice

    # El tenant de pruebas cierra los domingos (closed_weekdays por defecto).
    assert voice._dia_cerrado("demo", "2026-08-30") is True    # domingo
    assert voice._dia_cerrado("demo", "2026-08-27") is False   # jueves


def test_usa_el_modelo_que_el_negocio_ha_elegido(api_module):  # noqa: F811
    """Estaba en su panel, validado y guardado... y no lo leia nadie.

    El agente -que hoy es el cerebro del chat y de WhatsApp- llamaba siempre al
    modelo de la casa, asi que quien pagaba por uno mejor no lo tenia.
    """
    from backend import agent, settings

    assert agent._modelo_del_negocio({"chat_model": "gpt-4o"}) == "gpt-4o"
    # Lo que no este en la lista no se usa: un valor raro tumbaria la conversacion.
    assert agent._modelo_del_negocio({"chat_model": "modelo-inventado"}) == settings.DEFAULT_CHAT_MODEL
    assert agent._modelo_del_negocio({}) == settings.DEFAULT_CHAT_MODEL

    assert agent._temperatura_del_negocio({"temperature": 0.1}) == 0.1
    assert agent._temperatura_del_negocio({}) == 0.3
    assert agent._temperatura_del_negocio({"temperature": "no"}) == 0.3
    assert agent._temperatura_del_negocio({"temperature": 99}) == 1.5


def test_las_dos_llamadas_del_agente_usan_ese_modelo(api_module):  # noqa: F811
    import inspect

    from backend import agent

    fuente = inspect.getsource(agent.responder)
    assert "settings.DEFAULT_CHAT_MODEL" not in fuente, (
        "alguna llamada sigue ignorando lo que el negocio eligio"
    )
    assert fuente.count("_modelo_del_negocio(cfg)") >= 2


def test_decir_que_una_hora_esta_cogida_exige_haber_mirado(api_module):  # noqa: F811
    """Dijo "a las 10:30 ya tengo una cita" sin mirar. Estaba libre para las CINCO.

    La clienta se va con una hora que le venia bien y que existia. Y venia de
    haberle ofrecido "10:00, 14:00 y 18:00": de ahi dedujo que el resto estaba
    cogido, en vez de consultarlo.
    """
    from backend import agent

    assert agent._afirma_sobre_la_agenda("Lo siento, a las 10:30 ya tengo una cita")
    assert agent._afirma_sobre_la_agenda("Esa hora está ocupada, cariño")
    assert agent._afirma_sobre_la_agenda("Esa hora ya está cogida")
    assert not agent._afirma_sobre_la_agenda("Te espero el jueves, cariño")


def test_anunciar_no_es_hacer(api_module):  # noqa: F811
    """"Vamos a ver las horas disponibles. Un momento, por favor" -y ahi se quedo-.

    La clienta espera un mensaje que no llega nunca.
    """
    import inspect

    from backend import agent

    assert agent._lo_anuncia_en_vez_de_hacerlo("Un momento, por favor 😉")
    assert agent._lo_anuncia_en_vez_de_hacerlo("Ahora te digo las horas")
    assert agent._lo_anuncia_en_vez_de_hacerlo("Voy a mirar la agenda")
    assert not agent._lo_anuncia_en_vez_de_hacerlo("Tengo estas horas: 10:00 o 10:15")

    fuente = inspect.getsource(agent.responder)
    assert "_lo_anuncia_en_vez_de_hacerlo(texto_final) and not consultada" in fuente


def test_los_huecos_seguidos_se_ofrecen_como_rango(api_module):  # noqa: F811
    """Tres horas sueltas de una lista de veinte hacen creer que el resto no hay."""
    from backend import voice

    seguidos = ["10:00", "10:15", "10:30", "10:45", "11:00"]
    assert voice._rango_de_huecos(seguidos) == "de 10:00 a 11:00, cada 15 minutos"

    # Si no son seguidos NO se resume: seria mentir por otro lado.
    assert voice._rango_de_huecos(["10:00", "10:15", "18:00"]) == ""
    assert voice._rango_de_huecos(["10:00"]) == ""


def test_con_el_servicio_elegido_no_lo_vuelve_a_recomendar(api_module):  # noqa: F811
    from backend import reserva

    estado = reserva.Estado(servicio="Mechas o balayage medio", duracion=360)
    resumen = reserva.resumen(estado)
    assert "YA esta elegido" in resumen


def test_elegir_una_hora_que_le_han_ofrecido_no_es_inventarsela(api_module):  # noqa: F811
    """Mi propio freno bloqueaba lo mas normal del mundo.

    "Vale, la primera opcion que me has dicho" -> el asistente contestaba "no puedo
    mover tu cita a la hora que te he ofrecido", que no hay por donde cogerlo. La
    hora venia de su propia lista, pero no estaba en el estado.
    """
    from backend import agent

    historial = [
        {"role": "user", "content": "cualquier hueco me vale"},
        {"role": "assistant",
         "content": "Tengo el martes 1 a las 18:00 o el miércoles 2 a las 19:00"},
    ]
    ofrecidas = agent._horas_ya_ofrecidas(historial)
    assert "18:00" in ofrecidas and "19:00" in ofrecidas

    # Lo que dijo ELLA no cuenta como ofrecido por el asistente.
    assert agent._horas_ya_ofrecidas([{"role": "user", "content": "a las 11"}]) == set()


def test_no_vale_alternar_dos_parrafos_para_repetir(api_module):  # noqa: F811
    """A-B-A es el mismo muro que A-A: ya se lo habian contestado.

    El freno miraba SOLO la respuesta anterior, asi que alternando dos parrafos se
    colaba. Quien escribe no nota la diferencia: recibe otra vez lo mismo.
    """
    from backend import agent

    muro = ("Sin ver tu cabello no puedo decirte un precio, cada cabeza es un mundo "
            "y depende del largo y del punto de color que tengas ahora.")
    otra = "Claro que si, dime que dia te viene mejor y miro la agenda."
    historial = [
        {"role": "assistant", "content": muro},
        {"role": "user", "content": "pero dime algo aproximado"},
        {"role": "assistant", "content": otra},
        {"role": "user", "content": "es que necesito saber el precio"},
    ]
    assert agent._ya_dijo_esto(historial, muro) is True, (
        "alternar dos parrafos no puede saltarse el freno de repeticion"
    )


def test_algo_dicho_hace_mucho_ya_no_cuenta_como_repetirse(api_module):  # noqa: F811
    """Si contara TODA la conversacion, decir dos veces "¿que dia te viene bien?"
    en una charla larga saltaria el freno, y eso es normal y correcto."""
    from backend import agent

    frase = "Perfecto, entonces dime que dia te viene mejor y te miro los huecos que hay."
    historial = [{"role": "assistant", "content": frase}]
    for i in range(agent.ULTIMAS_QUE_CUENTAN + 1):
        historial.append({"role": "user", "content": "vale %d" % i})
        historial.append({"role": "assistant", "content": "respuesta distinta numero %d con su texto propio" % i})
    assert agent._ya_dijo_esto(historial, frase) is False


def test_un_si_a_te_la_cojo_cuenta_como_pedir_cita(api_module):  # noqa: F811
    """El freno de "nadie acaba con una cita que no ha pedido" mira SUS palabras,
    y hay un camino legitimo que no lleva ninguna: pregunta el horario, se le
    ofrece cogerle cita y contesta "si, porfa". Bloquearla ahi es perder una
    reserva de verdad por evitar una falsa.
    """
    from backend import agent

    historial = [
        {"role": "user", "content": "hola, a que hora abris manana?"},
        {"role": "assistant", "content": "Abrimos de 10:00 a 20:30, cariño. ¿Te cojo cita?"},
    ]
    assert agent._le_ofrecieron_cita_y_dijo_que_si(historial, "si, porfa") is True


def test_un_si_a_otra_cosa_no_cuenta_como_pedir_cita(api_module):  # noqa: F811
    """Si lo ultimo que le preguntaron no era una cita, su "si" no es una cita."""
    from backend import agent

    historial = [
        {"role": "user", "content": "hacéis mechas?"},
        {"role": "assistant", "content": "Si, cariño, hacemos mechas de varios tipos. ¿Las conoces?"},
    ]
    assert agent._le_ofrecieron_cita_y_dijo_que_si(historial, "si") is False


def test_sin_ofrecimiento_ni_si_el_freno_sigue_puesto(api_module):  # noqa: F811
    """La mitad que protege: quien solo pregunta el horario no se va con cita."""
    from backend import agent, reserva

    assert reserva.ha_pedido_cita("a que hora abris manana?") is False
    assert agent._le_ofrecieron_cita_y_dijo_que_si(
        [{"role": "assistant", "content": "Abrimos de 10:00 a 20:30, cariño."}],
        "vale, gracias") is False


def test_cancelar_no_deja_dar_por_hecha_una_cita_que_no_existe(api_module):  # noqa: F811
    """Lo peor que puede decir el asistente, visto en una tirada de 100.

    Transcripcion real: la clienta cambia de idea, el asistente cancela sus mechas
    y remata con "tengo tu nueva cita para cortarte las puntas el martes a las
    11:00". Nunca la creo. Ella se va convencida de que tiene cita; el salon, con
    un hueco libre que nadie ocupara y una clienta que se presentara.

    El freno miraba `mutada` -"¿ha cambiado algo en la agenda?"- y cancelar cambia
    algo, asi que lo daba por bueno. Lo que hay que mirar es si ha nacido una cita.
    """
    import inspect

    from backend import agent

    fuente = inspect.getsource(agent.responder)
    assert "creada = False" in fuente, "ya no se distingue crear de cancelar"
    assert 'if llamada.function.name != "cancelar_cita":' in fuente
    # Y el freno de "la da por hecha" cuelga de eso, no de `mutada`.
    # El SEGUNDO: el primero es el de la cita ya cancelada, que si mira `mutada`.
    trozo = fuente[fuente.index('traza.freno("daba_la_cita_por_hecha")') - 400:]
    trozo = trozo[:trozo.index('traza.freno("daba_la_cita_por_hecha")')]
    assert "creada" in trozo and "mutada" not in trozo, (
        "el freno ha vuelto a colgarse de `mutada`: una cancelacion deja pasar "
        "que se invente la cita siguiente"
    )


DICE_QUE_LO_HA_HECHO = [
    # Sin el "he": la forma mas comun de colarlo. Visto de verdad: la clienta
    # cambia de idea al final -corte en vez de mechas- y recibe "tu cita queda
    # para el corte de puntas el jueves a las 10:30". En la agenda seguian las
    # mechas. Nadie toco nada, y ella se presenta el jueves.
    "tu cita queda para el corte de puntas el jueves a las 10:30",
    "Perfecto, la cita queda cambiada a las 11:00",
    "ya esta modificada",
    "te la he cambiado",
    "la he cancelado",
    "te la he cogido para el jueves",
]

NO_LO_DA_POR_HECHO = [
    # Todas llevan dentro la misma frase, negada. Marcarlas seria regañar al
    # asistente por contestar BIEN, y a base de eso se estropea lo que va bien.
    "no la he cambiado",
    "aun no esta reservada",
    "todavia no te he apuntado",
    "no queda cancelada",
    "no te he cogido nada",
    "no la he cancelado",
    "¿quieres que te la cambie?",
    "te paso el resumen para que lo confirmes",
]


@pytest.mark.parametrize("texto", DICE_QUE_LO_HA_HECHO)
def test_afirmar_que_lo_ha_hecho_se_detecta(api_module, texto):  # noqa: F811
    from backend import agent

    assert agent._dice_que_acaba_de_hacerlo(texto) is True, repr(texto)


@pytest.mark.parametrize("texto", NO_LO_DA_POR_HECHO)
def test_lo_negado_no_cuenta_como_afirmarlo(api_module, texto):  # noqa: F811
    """La negacion se solapa con lo que se busca ("no LA HE CAMBIADO"), asi que
    mirando solo lo de ANTES del trozo no aparecia nunca entera."""
    from backend import agent

    assert agent._dice_que_acaba_de_hacerlo(texto) is False, repr(texto)


def test_anunciar_que_va_a_mirar_la_agenda_cuenta_como_no_mirarla(api_module):  # noqa: F811
    """"Dejame consultar la agenda" CUATRO veces seguidas a la misma clienta.

    Medido en una tirada de 100. Anunciar que vas a mirar y no mirar es el muro
    mas absurdo que hay: la herramienta esta ahi, en el mismo turno.
    """
    from backend import agent

    assert agent._lo_anuncia_en_vez_de_hacerlo(
        "Lo siento, cariño, no tengo la disponibilidad aún. Déjame consultar la agenda")
    assert agent._lo_anuncia_en_vez_de_hacerlo("dame un momento y te digo")
    # Y dar las horas NO es anunciar: eso es haberlo hecho.
    assert not agent._lo_anuncia_en_vez_de_hacerlo(
        "Tengo disponibilidad el jueves de 10:00 a 19:15, cada 15 minutos")
