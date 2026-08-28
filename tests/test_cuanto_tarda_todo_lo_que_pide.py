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


def test_la_pregunta_sigue_viva_cuando_llega_la_respuesta(salon):
    """Preguntar lo que falta esta bien; olvidarse de PARA QUE se preguntaba, no.

    Conversacion real por WhatsApp:

        ELLA: cuanto tarda un corte y secado?
          IA: ¿como tienes el pelo de largo? ¿de hombre, de senyora o de ninyo?
        ELLA: medio largo y es para mi, soy un hombre
          IA: [le ofrece horas para reservar]

    Nunca le dijo el tiempo. La guia solo se armaba si el mensaje DE ESE TURNO
    llevaba "cuanto tarda", y el segundo no lo llevaba: solo traia la respuesta.
    """
    from backend import agent, reserva

    estado = reserva.Estado()
    primera = "cuanto tarda un corte y secado?"
    assert agent._duracion_si_la_pregunta(salon, primera, estado, pedido=primera)
    assert estado.duracion_pendiente > 0, "la pregunta no se ha quedado apuntada"

    respuesta = "es para mi, soy un hombre"
    assert not agent._pregunta_cuanto_dura(respuesta), (
        "si este mensaje ya pidiera la duracion, el test no probaria nada"
    )
    guia = agent._duracion_si_la_pregunta(
        salon, respuesta, estado, pedido=primera + " " + respuesta)
    assert guia, "se ha olvidado de que le habian preguntado cuanto tarda"
    assert "CUANTO TARDA" in guia


def test_cuando_se_contesta_la_pregunta_se_cierra(salon):
    """Si no se cerrara, seguiria dando la duracion en cada mensaje."""
    from backend import agent, reserva

    estado = reserva.Estado()
    dicho = "corte de senora y secado, lo tengo largo, cuanto tarda?"
    guia = agent._duracion_si_la_pregunta(salon, dicho, estado, pedido=dicho)
    assert "EXACTAMENTE" in guia
    assert estado.duracion_pendiente == 0


def test_no_se_queda_preguntando_para_siempre(salon):
    """Si la conversacion se fue a otra cosa, se deja de insistir."""
    from backend import agent, reserva

    estado = reserva.Estado()
    primera = "cuanto tarda un corte y secado?"
    agent._duracion_si_la_pregunta(salon, primera, estado, pedido=primera)
    for _ in range(agent.TURNOS_QUE_DURA_LA_PREGUNTA + 1):
        agent._duracion_si_la_pregunta(salon, "vale", estado, pedido=primera + " vale")
    assert estado.duracion_pendiente == 0
    assert agent._duracion_si_la_pregunta(salon, "vale", estado, pedido="vale") == ""


def test_el_catalogo_se_lee_una_vez_por_eleccion(api_module):  # noqa: F811
    """Calcular las tecnicas dentro del bucle releia los 175 servicios 175 veces.

    Con el catalogo de un salon real eso pasaba de milisegundos a MINUTOS, y se
    colo hasta produccion. La comprobacion es de forma, no de reloj: los tests no
    pueden depender de lo rapido que vaya la maquina.
    """
    import inspect

    from backend import catalog_pick

    fuente = inspect.getsource(catalog_pick.elegir)
    dentro = fuente[fuente.index("def _encaja("):]
    dentro = dentro[:dentro.index("candidatos = [")]
    assert "_tecnicas_de_la_familia(" not in dentro, (
        "se ha vuelto a meter la lectura del catalogo dentro del bucle"
    )
    assert "servicios=servicios" in fuente, (
        "se relee el catalogo en vez de reusar el que ya esta cargado"
    )


def test_dos_alternativas_no_se_suman(salon):
    """"¿Y si me hago el otro?" es elegir, no anyadir.

    Conversacion real del salon: pregunto por la keratina y despues "y si me quiero
    hacer el acido lactico bio premium, ¿que tardo?". Se le contesto "en total
    serian 555 minutos" -sumando los dos tratamientos-, y a partir de ahi ya no
    hubo forma de cerrar la cita: no cabian juntos en ningun hueco.

    Se suma lo que pide EN EL MISMO mensaje ("corte y secado"), que es como se
    piden las cosas que van juntas.
    """
    from backend import agent, reserva

    estado = reserva.Estado()
    acumulado = "quiero una keratina que tarda. Y si me hago un corte que tardo?"
    ultimo = "Y si me hago un corte que tardo?"
    guia = agent._duracion_si_la_pregunta(salon, ultimo, estado, pedido=acumulado)
    assert "en total" not in (guia or "").lower(), guia


def test_lo_pedido_junto_se_sigue_sumando(salon):
    """La otra mitad: "corte y secado" en un mensaje sigue siendo una suma."""
    from backend import agent, reserva

    dicho = "quiero un corte de senora y un secado, lo tengo largo, cuanto tarda?"
    guia = agent._duracion_si_la_pregunta(salon, dicho, reserva.Estado(), pedido=dicho)
    assert "EXACTAMENTE 35 minutos" in guia, guia


def test_la_cifra_va_en_la_guia_y_no_se_deja_al_modelo(salon):
    """Un dato correcto que el modelo se salta es un dato perdido.

    Paso de verdad: `buscar_servicio` devolvio "de 160 a 280 minutos segun el
    largo" y el asistente contesto "no tengo informacion sobre la duracion de la
    queratina" -dos mensajes despues de haber dicho 220-. La herramienta acerto y
    la respuesta salio mal igual.

    Asi que cuando lo que nombra esta en el catalogo, la cifra va escrita en la
    guia y el modelo no tiene que ir a buscarla.
    """
    from backend import agent, reserva

    # En este catalogo el secado va de 10 a 15 minutos segun el largo: el mismo
    # caso que la keratina del salon real, que va de 160 a 280.
    guia = agent._duracion_si_la_pregunta(
        salon, "quiero un secado, que tarda?", reserva.Estado(),
        pedido="quiero un secado, que tarda?")
    assert "10" in guia and "15" in guia, guia
    assert "NUNCA digas que no tienes el dato" in guia


def test_un_solo_servicio_da_la_cifra_exacta(salon):
    from backend import agent, reserva

    guia = agent._duracion_si_la_pregunta(
        salon, "cuanto tarda un corte de senora?", reserva.Estado(),
        pedido="cuanto tarda un corte de senora?")
    assert "EXACTAMENTE 20 minutos" in guia, guia


def test_lo_que_no_existe_se_manda_a_mirar_el_catalogo(salon):
    """Sin inventarse un abanico para algo que el negocio no hace."""
    from backend import agent, reserva

    guia = agent._duracion_si_la_pregunta(
        salon, "cuanto tarda un chiringuito?", reserva.Estado(),
        pedido="cuanto tarda un chiringuito?")
    assert "buscar_servicio" in guia
