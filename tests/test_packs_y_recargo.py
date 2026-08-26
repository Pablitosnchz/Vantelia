# -*- coding: utf-8 -*-
"""Lo que aclaro la duenya del salon el 24 de agosto de 2026.

Tres cosas que se estaban haciendo mal, dichas por ella:

1. "Para coger unas mechas la cita hay que cogersela DIRECTAMENTE preguntandole
   como tiene el pelo de largo. Lo del diagnostico es simplemente para las
   clientas que pidan presupuesto." Se estaba mandando a valoracion a todo el
   mundo, tambien a quien venia a reservar.
2. "Cualquier servicio de mechas conlleva mas trabajos -matices, volumenes,
   tratamientos- y cualquier alisado conlleva poner el producto, dejarlo,
   secarlo y plancharlo": son PACKS. El pack es el que lleva la duracion real y
   los tiempos de espera; reservar el suelto se queda corto y descuadra la agenda.
3. "A mi que me apunte las citas la ultima, solo cuando no hay huecos con ellas o
   cuando alguien pida expresamente la cita conmigo."
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


@pytest.fixture
def salon_con_packs(api_module, client):  # noqa: F811
    from backend import agenda, appstate, clients, db, timeutils

    ahora = timeutils._utc_now_iso()
    with db._get_db_connection() as conexion:
        for nombre, minutos in (("Mechas medio", 75), ("Pack mechas o balayage medio", 220)):
            conexion.execute(
                "INSERT OR REPLACE INTO services (cliente_id, slug, name, category,"
                " duration_minutes, price_cents, description, is_active, sort_order,"
                " created_at, updated_at) VALUES ('demo', ?, ?, '', ?, 8000, '', 1, 0, ?, ?)",
                (agenda._normalize_service_id(nombre), nombre, minutos, ahora, ahora),
            )
        conexion.commit()
    config = clients._get_client_config("demo")
    previo = dict(config.get("booking") or {})
    config["booking"] = dict(previo, preferir_packs=True)
    yield
    config["booking"] = previo
    with db._get_db_connection() as conexion:
        conexion.execute(
            "DELETE FROM services WHERE cliente_id='demo' AND name IN"
            " ('Mechas medio','Pack mechas o balayage medio')"
        )
        conexion.commit()


def test_pedir_mechas_lleva_al_pack(salon_con_packs, api_module):  # noqa: F811
    """El pack tiene la duracion REAL y los tiempos de espera; el suelto no."""
    from backend import catalog_pick

    datos = {"familia": "mechas", "tecnica": "", "talla": "medio",
             "para_quien": "", "edad": None, "texto": "quiero unas mechas"}
    assert catalog_pick.elegir("demo", datos).servicio == "Pack mechas o balayage medio"


def test_sin_activarlo_se_reserva_el_suelto(api_module, client):  # noqa: F811
    """Es opt-in: un negocio que no venda por packs sigue como siempre."""
    from backend import agenda, catalog_pick, db, timeutils

    ahora = timeutils._utc_now_iso()
    with db._get_db_connection() as conexion:
        for nombre in ("Mechas medio", "Pack mechas o balayage medio"):
            conexion.execute(
                "INSERT OR REPLACE INTO services (cliente_id, slug, name, category,"
                " duration_minutes, price_cents, description, is_active, sort_order,"
                " created_at, updated_at) VALUES ('demo', ?, ?, '', 75, 8000, '', 1, 0, ?, ?)",
                (agenda._normalize_service_id(nombre), nombre, ahora, ahora),
            )
        conexion.commit()
    try:
        datos = {"familia": "mechas", "tecnica": "", "talla": "medio",
                 "para_quien": "", "edad": None, "texto": "quiero unas mechas"}
        assert catalog_pick.elegir("demo", datos).servicio == "Mechas medio"
    finally:
        with db._get_db_connection() as conexion:
            conexion.execute(
                "DELETE FROM services WHERE cliente_id='demo' AND name IN"
                " ('Mechas medio','Pack mechas o balayage medio')"
            )
            conexion.commit()


def test_reservar_no_se_convierte_en_valoracion(api_module, client):  # noqa: F811
    """Quien viene a RESERVAR se lleva su cita; la valoracion es para el presupuesto.

    Se hizo al reves y la duenya lo corrigio: "la cita hay que cogersela
    directamente; lo del diagnostico es simplemente para quien pida presupuesto".
    """
    import inspect

    from backend import voice

    fuente = inspect.getsource(voice._voice_perform_booking)
    assert "_servicio_tras_valoracion" not in fuente, (
        "la creacion de cita vuelve a cambiar el servicio por una valoracion"
    )


def test_la_ultima_opcion_se_deja_para_el_final(api_module, client):  # noqa: F811
    """"A mi que me apunte las citas la ultima"."""
    from backend import agenda, db, timeutils

    ahora = timeutils._utc_now_iso()
    with db._get_db_connection() as conexion:
        for eid, nombre, ultima in (("emp_jefa", "Alicia", 1), ("emp_equipo", "Conchi", 0)):
            conexion.execute(
                "INSERT OR REPLACE INTO employees (id, cliente_id, name, is_active,"
                " is_default, auto_assign_last, service_ids_json, created_at, updated_at)"
                " VALUES (?, 'demo', ?, 1, 0, ?, '[]', ?, ?)",
                (eid, nombre, ultima, ahora, ahora),
            )
        conexion.commit()
    try:
        jefa = agenda._get_employee_row("emp_jefa", cliente_id="demo")
        equipo = agenda._get_employee_row("emp_equipo", cliente_id="demo")
        assert agenda._es_ultima_opcion(jefa) is True
        assert agenda._es_ultima_opcion(equipo) is False
    finally:
        with db._get_db_connection() as conexion:
            conexion.execute("DELETE FROM employees WHERE id IN ('emp_jefa','emp_equipo')")
            conexion.commit()


def test_cada_servicio_lleva_su_texto_de_recargo(api_module, client):  # noqa: F811
    """El salon quiere un texto para los tecnicos y otro para el resto."""
    from backend import agenda, db, timeutils

    ahora = timeutils._utc_now_iso()
    with db._get_db_connection() as conexion:
        conexion.execute(
            "INSERT OR REPLACE INTO employees (id, cliente_id, name, is_active, is_default,"
            " price_surcharge_pct, surcharge_text, surcharge_text_tecnico, surcharge_familias,"
            " service_ids_json, created_at, updated_at)"
            " VALUES ('emp_jefa2', 'demo', 'Alicia', 1, 0, 25, 'texto corto',"
            " 'texto largo del alisado', 'alisado,mechas', '[]', ?, ?)",
            (ahora, ahora),
        )
        conexion.commit()
    try:
        fila = agenda._get_employee_row("emp_jefa2", cliente_id="demo")
        assert agenda.texto_del_recargo(fila, "Pack mechas o balayage medio") == "texto largo del alisado"
        assert agenda.texto_del_recargo(fila, "Corte señora") == "texto corto"
        assert agenda.texto_del_recargo(None, "lo que sea") == ""
    finally:
        with db._get_db_connection() as conexion:
            conexion.execute("DELETE FROM employees WHERE id='emp_jefa2'")
            conexion.commit()


def test_no_se_pregunta_con_quien_quiere(api_module, client):  # noqa: F811
    """"No quiero que se le pregunte; solo cuando la clienta lo diga de forma natural"."""
    from backend import agent

    r = agent._tool_consultar_profesionales("demo", {})
    assert "NO le preguntes con quien quiere" in r["nota"] or "NO le preguntes" in r["nota"]


def test_la_clienta_no_ve_la_palabra_pack(api_module, client):  # noqa: F811
    """"No digas que es un pack, es como si fuese el servicio".

    Para quien pide unas mechas eso son sus mechas, no un producto empaquetado.
    La palabra es del catalogo interno del salon -le dice que lleva matiz, volumen
    y tratamiento-, no algo que la clienta tenga que entender.
    """
    from backend import textnorm

    assert textnorm.nombre_de_servicio_publico("Pack mechas o balayage medio") == "Mechas o balayage medio"
    assert textnorm.nombre_de_servicio_publico("Pack de keratina premium corto") == "Keratina premium corto"
    # Lo que no es un pack se queda igual.
    assert textnorm.nombre_de_servicio_publico("Corte señora") == "Corte señora"
    assert textnorm.nombre_de_servicio_publico("") == ""


def test_el_nombre_sin_pack_sigue_encontrando_el_servicio(salon_con_packs, api_module):  # noqa: F811
    """Ocultar la palabra no puede romper la reserva.

    Si al cliente se le dice "Mechas o balayage medio", eso es lo que acabara
    diciendo el asistente al crear la cita: hay que saber volver al nombre real.
    """
    from backend import agenda

    fila = agenda._find_service_by_name("demo", "Mechas o balayage medio")
    assert fila is not None
    assert fila["name"] == "Pack mechas o balayage medio"


def test_el_catalogo_del_prompt_no_dice_pack(salon_con_packs, api_module):  # noqa: F811
    from backend import booking

    catalogo = "\n".join(booking._service_catalog_lines("demo"))
    assert "Mechas o balayage medio" in catalogo
    assert "Pack" not in catalogo


# ---------------------------------------------------------------------------
# Lo que salio al probarlo como una clienta de verdad (25-ago-2026): tres cosas
# en UNA sola conversacion. Pidio "unas mechas con Alicia", se le ofrecio elegir
# entre "Mechas o balayage" y "Cambio de color y mechas o balayage", contesto
# "mechas o balayage, lo tengo largo" y el asistente:
#   1. le asigno el CAMBIO DE COLOR -otro servicio, mas largo y mas caro-,
#   2. le llamo "Pack cambio de color y mechas o balayage largo" a la cara, y
#   3. no menciono el 25 % de Alicia ni cuando pregunto el precio.
# ---------------------------------------------------------------------------


def test_no_le_sube_el_servicio_por_su_cuenta(salon_con_packs, api_module):  # noqa: F811
    """Quien pide mechas no esta pidiendo tambien un cambio de color."""
    from backend import agenda, catalog_pick, db, timeutils

    ahora = timeutils._utc_now_iso()
    caro = "Pack cambio de color y mechas o balayage medio"
    with db._get_db_connection() as conexion:
        conexion.execute(
            "INSERT OR REPLACE INTO services (cliente_id, slug, name, category,"
            " duration_minutes, price_cents, description, is_active, sort_order,"
            " created_at, updated_at) VALUES ('demo', ?, ?, '', 200, 15000, '', 1, 0, ?, ?)",
            (agenda._normalize_service_id(caro), caro, ahora, ahora),
        )
        conexion.commit()
    try:
        datos = {"familia": "mechas", "tecnica": "balayage", "talla": "medio",
                 "para_quien": "", "edad": None,
                 "texto": "mechas o balayage, lo tengo por los hombros"}
        elegido = catalog_pick.elegir("demo", datos).servicio
        assert elegido == "Pack mechas o balayage medio", (
            "le ha subido el servicio sin preguntar: %r" % elegido
        )
    finally:
        with db._get_db_connection() as conexion:
            conexion.execute("DELETE FROM services WHERE cliente_id='demo' AND name = ?", (caro,))
            conexion.commit()


def test_a_la_clienta_no_se_le_dice_la_palabra_pack(api_module, client):  # noqa: F811
    """"No digas que es un pack, es como si fuese el servicio" (la duenya).

    El guardarrail de precios metia el nombre CRUDO en lo que lee el modelo, y de
    ahi salia tal cual: "el servicio que mencionas es el Pack cambio de color...".
    """
    from backend import agent, db, rules, timeutils

    ahora = timeutils._utc_now_iso()
    with db._get_db_connection() as conexion:
        conexion.execute(
            "INSERT OR REPLACE INTO services (cliente_id, slug, name, category,"
            " duration_minutes, price_cents, description, is_active, sort_order,"
            " created_at, updated_at) VALUES ('demo', 'valoracion', 'Valoracion',"
            " '', 15, 0, '', 1, 0, ?, ?)", (ahora, ahora))
        conexion.commit()
    regla = rules.guardar("demo", nombre="Mechas: precio tras ver el pelo",
                        intenciones=["precio"], familias=["mechas"],
                        accion="ofrecer_cita", texto="")
    try:
        salida = agent._valoracion_en_lugar_del_tratamiento(
            "demo", "Pack cambio de color y mechas o balayage largo",
        )
        assert salida, "la regla del negocio no llego a aplicarse"
        for clave in ("servicio", "en_lugar_de", "motivo", "nota"):
            assert "pack" not in str(salida.get(clave, "")).lower(), (
                "la clienta acaba leyendo 'pack' en %r" % clave
            )
    finally:
        rules.borrar("demo", regla["id"] if isinstance(regla, dict) else regla)
        with db._get_db_connection() as conexion:
            conexion.execute("DELETE FROM services WHERE cliente_id='demo' AND slug='valoracion'")
            conexion.commit()
    return
    for clave in ("servicio", "en_lugar_de", "motivo", "nota"):
        assert "pack" not in str(salida.get(clave, "")).lower(), (
            "la clienta acaba leyendo 'pack' en %r" % clave
        )


def test_si_pide_a_la_jefa_se_le_cuenta_el_recargo(api_module, client):  # noqa: F811
    """El 25 % no puede depender de que al modelo le apetezca consultarlo."""
    from backend import agent, db, timeutils

    ahora = timeutils._utc_now_iso()
    with db._get_db_connection() as conexion:
        conexion.execute(
            "INSERT OR REPLACE INTO employees (id, cliente_id, name, is_active,"
            " is_default, price_surcharge_pct, surcharge_text, service_ids_json,"
            " created_at, updated_at) VALUES ('emp_jefa_recargo', 'demo', 'Alicia Rincon',"
            " 1, 0, 25, ?, '[]', ?, ?)",
            ("Con Alicia el servicio sube un 25 % porque reserva su agenda.", ahora, ahora),
        )
        conexion.commit()
    try:
        aviso = agent._aviso_de_recargo("demo", "quiero unas mechas con alicia")
        assert "25" in aviso and "reserva su agenda" in aviso, (
            "pide a la jefa y no se le cuenta lo que cuesta: %r" % aviso
        )
        # Y el falso positivo que habria dado la vuelta: el salon SE LLAMA asi.
        assert agent._aviso_de_recargo("demo", "hola, quiero cita en Alicia Rincon Estilistas") == "", (
            "nombrar al salon no es pedir que te atienda ella"
        )
        assert agent._aviso_de_recargo("demo", "quiero unas mechas") == ""
    finally:
        with db._get_db_connection() as conexion:
            conexion.execute("DELETE FROM employees WHERE id='emp_jefa_recargo'")
            conexion.commit()


def test_el_recargo_se_explica_una_vez_no_en_cada_mensaje(api_module, client):  # noqa: F811
    """Parrafo y medio en cada respuesta cansa y ademas le hacia perder el hilo.

    Visto en produccion: se lo solto entero al pedir la cita y OTRA VEZ dos turnos
    despues; en medio se le habian ofrecido tres horas, y tras repetirlo volvio a
    preguntarle que dia queria.
    """
    import inspect

    from backend import agent, reserva

    assert hasattr(reserva.Estado(), "recargo_dicho"), "no hay donde recordarlo"
    fuente = inspect.getsource(agent.responder)
    assert 'if estado.recargo_dicho' in fuente or 'estado.recargo_dicho\n' in fuente, (
        "el aviso del recargo no mira si ya se le conto"
    )
    assert 'estado.recargo_dicho = True' in fuente, "nunca se marca como contado"


def test_ninguna_tool_le_pasa_la_palabra_pack_al_modelo(api_module, client):  # noqa: F811
    """Se tapo en `buscar_servicio` y siguio saliendo por otra tool.

    En produccion, ya con el primer arreglo puesto: "vamos a reservarte el pack de
    mechas o balayage largo" y 'el servicio que buscas es el "Pack mechas o
    balayage largo"'. Por eso se limpia en el unico sitio por el que pasan TODAS.
    """
    from backend import agent

    crudo = {
        "ok": True,
        "servicio": "Pack mechas o balayage largo",
        "servicio_en_agenda": "Pack mechas o balayage largo",
        "categoria": "Packs",
        "candidatos": [{"servicio": "Pack alisado keratina medio", "duracion_minutos": 200}],
        "opciones": ["Pack mechas o balayage corto", "Corte senora"],
        "huecos": ["10:00", "10:15"],
    }
    limpio = agent._sin_la_palabra_pack(crudo)

    assert limpio["servicio"] == "Mechas o balayage largo"
    assert limpio["candidatos"][0]["servicio"] == "Alisado keratina medio"
    assert limpio["opciones"][0] == "Mechas o balayage corto"
    assert limpio["opciones"][1] == "Corte senora"
    assert limpio["huecos"] == ["10:00", "10:15"], "no debe tocar lo que no son nombres"
    # Y lo de cocina ni se le ensenya: de ahi copiaba la palabra.
    assert "servicio_en_agenda" not in limpio
    assert "categoria" not in limpio
    # El original NO se toca: con el nombre exacto se crea la cita.
    assert crudo["servicio_en_agenda"] == "Pack mechas o balayage largo"


def test_el_nombre_que_se_dice_sigue_encontrando_el_servicio(salon_con_packs, api_module):  # noqa: F811
    """Si el catalogo no supiera volver del nombre publico al real, la cita se
    cogeria con la duracion equivocada: 30 minutos en vez de las horas del pack."""
    from backend import agenda, textnorm

    publico = textnorm.nombre_de_servicio_publico("Pack mechas o balayage medio")
    assert publico == "Mechas o balayage medio"
    fila = agenda._find_service_by_name("demo", publico)
    assert fila is not None and fila["name"] == "Pack mechas o balayage medio"
    assert int(fila["duration_minutes"]) == 220


def test_lo_que_ha_dicho_del_servicio_no_se_pierde_entre_mensajes(api_module):  # noqa: F811
    """"unas mechas" + "lo tengo por los hombros" son DOS datos, no uno.

    Paso de verdad (25-ago-2026): dijo que queria mechas, el asistente le pregunto
    cual de las tres tecnicas, ella contesto el largo del pelo... y le pregunto
    otra vez que servicio queria. Solo le llegaba su ULTIMO mensaje.
    """
    from backend import reserva

    estado = reserva.Estado()
    reserva.anotar_lo_que_dice(estado, "me gustaria hacerme unas mechas", "Europe/Madrid")
    reserva.anotar_lo_que_dice(estado, "lo tengo por los hombros", "Europe/Madrid")

    acumulado = estado.servicio_texto.lower()
    assert "mechas" in acumulado and "hombros" in acumulado

    # Con el servicio ya elegido deja de acumular: lo que diga despues es otra cosa.
    estado.servicio = "Pack mechas o balayage medio"
    reserva.anotar_lo_que_dice(estado, "el jueves por la tarde", "Europe/Madrid")
    assert "jueves" not in estado.servicio_texto.lower()


def test_la_busqueda_del_servicio_usa_todo_lo_dicho(api_module):  # noqa: F811
    import inspect

    from backend import agent

    fuente = inspect.getsource(agent.responder)
    assert 'llamada.function.name == "buscar_servicio" and estado.servicio_texto' in fuente, (
        "la busqueda del servicio vuelve a mirar solo el ultimo mensaje"
    )


def test_los_servicios_no_se_dicen_entre_comillas(salon_con_packs, api_module):  # noqa: F811
    """"que no ponga los servicios entre comillas, es muy poco natural" (el negocio)."""
    from backend import agent

    texto = agent._sin_comillas_en_los_servicios(
        "demo", 'Perfecto, te hago unas "Pack mechas o balayage medio" el jueves.')
    assert '"' not in texto
    assert "mechas o balayage medio" in texto.lower()

    # Lo que NO es un servicio se queda como esta: no se toca lo que cita a otro.
    otro = agent._sin_comillas_en_los_servicios("demo", 'Me dijiste "el jueves por la tarde".')
    assert otro == 'Me dijiste "el jueves por la tarde".'


def test_antes_de_repreguntar_mira_el_catalogo(api_module):  # noqa: F811
    """El fallo mas repetido de la medicion: 26 de 100 repiten la pregunta.

    Con algo dicho sobre el servicio y ninguno elegido, lo que toca es mirar el
    catalogo, no volver a preguntar. Se le OBLIGA, porque pedirselo por prompt es
    lo que llevaba fallando.
    """
    import inspect

    from backend import agent

    fuente = inspect.getsource(agent.responder)
    assert 'remate = "buscar_servicio"' in fuente, (
        "nada obliga a mirar el catalogo antes de repreguntar"
    )
    assert "catalogo_mirado" in fuente, "no se lleva la cuenta de si ya se miro"


def test_el_resumen_le_recuerda_lo_que_ella_dijo(api_module):  # noqa: F811
    from backend import reserva

    estado = reserva.Estado(servicio_texto="unas mechas lo tengo por los hombros")
    resumen = reserva.resumen(estado)
    assert "unas mechas" in resumen and "hombros" in resumen
    assert "NO le preguntes otra vez" in resumen

    # Con el servicio ya elegido, esa linea sobra.
    elegido = reserva.Estado(servicio="Pack mechas o balayage medio",
                             servicio_texto="unas mechas")
    assert "ya te ha dicho" not in reserva.resumen(elegido).lower()


def test_tampoco_cita_el_nombre_corto_que_le_ofrece(salon_con_packs, api_module):  # noqa: F811
    """Lo que mas entrecomillaba era la tecnica sin la talla."""
    from backend import agent

    texto = agent._sin_comillas_en_los_servicios(
        "demo", 'Puedes elegir "Mechas o balayage" o algo más suave.')
    assert '"Mechas o balayage"' not in texto
    assert "Mechas o balayage" in texto


def test_no_le_repite_la_misma_lista_de_opciones(api_module):  # noqa: F811
    """Preguntar esta bien; preguntar DOS VECES lo mismo es el muro.

    Visto: "unas mechas" -> le ofrece las tres tecnicas -> "quiero unas mechas" ->
    le ofrece las tres otra vez. Si ya se lo preguntaste y no se decide, o le
    preguntas otra cosa (el largo) o te mojas y le recomiendas una.
    """
    import inspect

    from backend import agent, reserva

    assert hasattr(reserva.Estado(), "ultimo_falta"), "no hay donde recordar la pregunta"
    fuente = inspect.getsource(agent.responder)
    assert 'falta == estado.ultimo_falta' in fuente, (
        "nada detecta que se le esta preguntando lo mismo otra vez"
    )
    assert "recomiendale UNA" in fuente, "no se le da salida cuando ella no se decide"


def test_quien_pregunta_el_precio_se_lleva_la_valoracion_no_el_tratamiento(api_module, client):  # noqa: F811
    """La regla del salon, aplicada donde se crea la cita y no solo al buscar.

    Medido con 100 conversaciones: 6 veces le cogio el tratamiento entero -"Pack
    keratina premium largo", cuatro horas- a alguien que solo habia preguntado
    cuanto costaba. La funcion que lo evitaba existia... y no la llamaba nadie.

    Ojo al matiz que corrigio la duenya: quien viene a RESERVAR unas mechas se
    lleva sus mechas. Esto es solo para quien viene a preguntar el precio.
    """
    import inspect

    from backend import agent

    fuente = inspect.getsource(agent.responder)
    assert "_valoracion_en_lugar_del_tratamiento(" in fuente, (
        "el guardarrail sigue siendo codigo muerto"
    )
    assert "estado.veces_sin_precio" in fuente, (
        "se aplicaria tambien a quien viene a reservar, que NO es la regla"
    )
    # Y se comprueba ANTES de crear nada.
    freno = fuente.index("_valoracion_en_lugar_del_tratamiento(")
    ejecuta = fuente.index("resultado = await _ejecutar(")
    assert freno < ejecuta, "se cambia el servicio despues de haber cogido la cita"


def test_el_recargo_va_en_el_resumen_que_firma_la_clienta(api_module, client):  # noqa: F811
    """Fiarlo al modelo no basta: se le paso el aviso y no dijo ni una palabra.

    Paso de verdad: "¿puede ser con Alicia?" -> "Claro, con Alicia" -> resumen con
    su nombre -> confirmado. Del 25 % ni mencion. La clienta firma un precio que
    no sabe, y el salon se come la diferencia o queda mal el dia de la cita.
    """
    from backend import agenda, db, timeutils, whatsapp, appstate

    ahora = timeutils._utc_now_iso()
    with db._get_db_connection() as conexion:
        conexion.execute(
            "INSERT OR REPLACE INTO employees (id, cliente_id, name, is_active,"
            " is_default, price_surcharge_pct, service_ids_json, created_at, updated_at)"
            " VALUES ('emp_jefa_resumen', 'demo', 'Alicia Rincon', 1, 0, 25, '[]', ?, ?)",
            (ahora, ahora))
        conexion.execute(
            "INSERT OR REPLACE INTO employees (id, cliente_id, name, is_active,"
            " is_default, price_surcharge_pct, service_ids_json, created_at, updated_at)"
            " VALUES ('emp_equipo_resumen', 'demo', 'Conchi', 1, 0, 0, '[]', ?, ?)",
            (ahora, ahora))
        conexion.commit()
    try:
        flow = appstate.WAFlowState(cliente_id="demo", from_number="34600111999")
        flow.employee_id = "emp_jefa_resumen"
        linea = whatsapp._wa_linea_de_recargo("demo", flow)
        assert "25" in linea and "Alicia" in linea, linea

        # Con el resto del equipo no se dice nada: cobran lo mismo.
        flow.employee_id = "emp_equipo_resumen"
        assert whatsapp._wa_linea_de_recargo("demo", flow) == ""

        # Y sin profesional elegido tampoco.
        flow.employee_id = ""
        assert whatsapp._wa_linea_de_recargo("demo", flow) == ""
    finally:
        with db._get_db_connection() as conexion:
            conexion.execute("DELETE FROM employees WHERE id IN"
                             " ('emp_jefa_resumen','emp_equipo_resumen')")
            conexion.commit()


def test_el_texto_del_25_por_ciento_sale_si_o_si_antes_del_resumen(api_module, client):  # noqa: F811
    """No puede depender de que al modelo le apetezca decirlo.

    Se le paso el aviso -el detector salta con "¿puede ser con Alicia?"- y lo
    ignoro porque estaba cerrando la cita: la clienta confirmo sin saber que
    llevaba un 25 % encima.
    """
    import inspect

    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._wa_send_booking_summary)
    assert "_wa_explicar_el_recargo" in fuente, (
        "el texto del negocio sigue dependiendo del modelo"
    )
    explicar = inspect.getsource(whatsapp._wa_explicar_el_recargo)
    assert "texto_del_recargo" in explicar, "no usa el texto que ha escrito el negocio"
    assert "recargo_dicho" in explicar, "se lo soltaria en cada resumen"


def test_al_ofrecer_opciones_dice_que_es_cada_una(api_module, client):  # noqa: F811
    """"No se ve bien la diferencia entre ellas" (el negocio, probandolo).

    Recitar "Mechas o balayage / Cambio de color mechas o balayage / Cambio de
    color y mechas o balayage" no ayuda a elegir: suenan igual. El negocio ya tiene
    escrito que es cada servicio (167 de 175 lo tienen), asi que se explica con SUS
    palabras en vez de inventarlas.
    """
    import inspect

    from backend import agent

    fuente = inspect.getsource(agent._tool_buscar_servicio)
    assert "opciones_explicadas" in fuente
    assert "que_es" in inspect.getsource(agent._detalle_servicio), (
        "el detalle del servicio no trae lo que el negocio escribio"
    )


def test_la_regla_del_precio_vale_aunque_no_sea_coger_cita(api_module, client):  # noqa: F811
    """Media condicion del salon se quedaba fuera.

    Para mechas y color su regla es "cita de valoracion"; para los alisados es
    PEDIR FOTO. El guardarrail solo miraba las del primer tipo, asi que a quien
    preguntaba el precio de una keratina se le cogia el tratamiento entero -cuatro
    horas- en vez de seguir la regla.
    """
    from backend import booking, db, rules, timeutils

    ahora = timeutils._utc_now_iso()
    with db._get_db_connection() as conexion:
        conexion.execute(
            "INSERT OR REPLACE INTO services (cliente_id, slug, name, category,"
            " duration_minutes, price_cents, description, is_active, sort_order,"
            " created_at, updated_at) VALUES ('demo', 'keratina_larga',"
            " 'Keratina premium largo', '', 240, 0, '', 1, 0, ?, ?)", (ahora, ahora))
        conexion.commit()
    regla = rules.guardar("demo", nombre="Alisado: pedir foto", intenciones=["precio"],
                          familias=["keratina"], accion="pedir_foto",
                          texto="Mandanos una foto del pelo y te decimos el precio.")
    try:
        encontrada = booking.regla_de_precio_para("demo", "Keratina premium largo")
        assert encontrada, "no encuentra la regla del negocio para ese servicio"
        assert encontrada["accion"] == "pedir_foto"
        assert "foto" in (encontrada.get("texto") or "").lower()

        # Un servicio sin regla de precio no se frena.
        assert booking.regla_de_precio_para("demo", "Corte senora") == {}
    finally:
        rules.borrar("demo", regla["id"])
        with db._get_db_connection() as conexion:
            conexion.execute("DELETE FROM services WHERE cliente_id='demo' AND slug='keratina_larga'")
            conexion.commit()
