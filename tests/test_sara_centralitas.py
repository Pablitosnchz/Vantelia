# -*- coding: utf-8 -*-
"""Sara ante centralitas, grabaciones y buzones, y como nombra al negocio.

POR QUE EXISTE
--------------
29-sep-2026, primer dia de llamadas reales (10): ninguna llego a la demo. Cuatro dieron con
una grabacion o un menu de centralita y Sara les hablaba (y colgo en plena espera); a la
persona que cogio despues no se le presento; a "ahora mismo esta ocupado" contesto
"Genial"; y "¿Hablo con Miguel Guerrero?" sonaba a buscar a una persona, no a su
peluqueria. Ademas, por SIP toda llamada que conecta tiene conversacion, asi que un buzon
o una centralita contaban como "hablamos" y ese negocio no se volvia a llamar nunca.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_booking_exhaustive import api_module  # noqa: F401
from test_captacion_voz import _Falso, captacion, envios  # noqa: F401
from test_lanzador_llamadas import MARTES_10_30, _llamada_previa, _prospecto, lanzador  # noqa: F401
from test_transcripciones_llamadas import _conversacion, llamada  # noqa: F401


# --- Como se nombra al negocio ----------------------------------------------------------

@pytest.mark.parametrize("negocio,sector,hablado", [
    ("Miguel Guerrero", "peluqueria", "la peluquería Miguel Guerrero"),
    ("Carmen Navarro Sagasta", "peluqueria y estetica", "la peluquería Carmen Navarro Sagasta"),
    ("Lola Ruiz", "Centro de Estética", "el centro de estética Lola Ruiz"),
    ("Paco", "barberia", "la barbería Paco"),
    ("Dra. López", "clinica dental", "la clínica dental Dra. López"),
    # Una marca, no una persona: tal cual. 29-sep salio "la peluqueria Templa Medical" (una
    # clinica mal etiquetada como peluqueria en la captacion).
    ("Templa Medical", "peluqueria y estetica", "Templa Medical"),
    ("Templa Wellness", "fisioterapia", "Templa Wellness"),
    ("Laura Gil Medical", "clinica privada", "Laura Gil Medical"),  # nombre de pila, pero ya dice lo que es
    ("Ginefiv San Sebastián de los Reyes", "clinica privada", "Ginefiv San Sebastián de los Reyes"),
    ("Sonrisas Madrid", "clinica dental", "Sonrisas Madrid"),
    # Ya dice lo que es: tal cual.
    ("Clinica Montecarmelo", "clinica estetica", "Clinica Montecarmelo"),
    ("Marian Vivar Centro de estética", "centro estetica", "Marian Vivar Centro de estética"),
    ("Peluquería Lola", "peluqueria", "Peluquería Lola"),
    ("Estetica Natura", "centro estetica", "Estetica Natura"),
    # Sector que no se reconoce: tal cual, sin inventar.
    ("Miguel Guerrero", "", "Miguel Guerrero"),
    ("Miguel Guerrero", "gestoria", "Miguel Guerrero"),
])
def test_como_nombra_al_negocio(captacion, negocio, sector, hablado):  # noqa: F811
    assert captacion.negocio_hablado(negocio, sector) == hablado


def test_el_saludo_pregunta_por_la_peluqueria_no_por_la_persona(captacion):  # noqa: F811
    hecho = captacion.llamar("911111111", "Miguel Guerrero", "peluqueria", "", origen="auto", cliente=_Falso())
    variables = captacion._variables(captacion._fila(hecho["llamada"]))
    assert variables["a_quien"] == "la peluquería Miguel Guerrero"
    assert variables["negocio"] == "Miguel Guerrero"
    sin_nombre = captacion.llamar("911111112", "", "peluqueria", "", origen="auto", cliente=_Falso())
    assert captacion._variables(captacion._fila(sin_nombre["llamada"]))["a_quien"] == "tu negocio"


def test_en_la_rellamada_se_sigue_preguntando_por_quien_decide(captacion):  # noqa: F811
    hecho = captacion.llamar("911111111", "Miguel Guerrero", "peluqueria", "", origen="auto", cliente=_Falso())
    captacion._actualizar(hecho["llamada"], rellamada_de="ll_antes", responsable_nombre="Marta")
    assert captacion._variables(captacion._fila(hecho["llamada"]))["a_quien"] == "Marta"


# --- El guion -------------------------------------------------------------------------

def test_el_guion_sabe_de_grabaciones_esperas_y_de_quien_esta_ocupado(captacion):  # noqa: F811
    agente = captacion.agente_de_captacion("https://app.test")
    guion = agente["conversation_config"]["agent"]["prompt"]["prompt"]
    assert "Eso NO es una persona: no le hables" in guion
    assert "No cuelgues por estar en espera" in guion
    assert "presentate entera con la misma apertura del principio" in guion
    assert "NO son permiso para la demostracion" in guion
    # Div@, 29-sep: le dijeron que la encargada no estaba y, tras la demo, pregunto "¿eres tu
    # quien lleva el salon?". Lo que toca es su nombre y cuando esta (la rellamada).
    assert "Si ya te han dicho que quien decide no esta" in guion
    assert "hablo_una_persona" in agente["platform_settings"]["data_collection"]


# --- Nombre sin relleno de buscador y ningun telefono de Pablo (30-sep) ---------------------

@pytest.mark.parametrize("negocio,corto", [
    ("Blow Dry Bar - Daniele Sigigliano - Peluquería en los Jerónimos Madrid", "Blow Dry Bar"),
    ("Allure Nails Madrid - Centro de estética", "Allure Nails Madrid"),
    ("Maison Eduardo Sánchez, peluquería. Barrio Salamanca", "Maison Eduardo Sánchez"),
    ("Espacio Isaac Salido - Peluquería & Concept Store", "Espacio Isaac Salido"),
    ("Peluqueria Madrid - Ananda Ferdi", "Ananda Ferdi"),            # el primer trozo es solo relleno
    ("Medicina Estética en Madrid - Dr. Rojas", "Dr. Rojas"),
    ("MARSYA Centro Médico-Estético", "MARSYA Centro Médico-Estético"),  # guion sin espacios: no se corta
    ("Clinica Montecarmelo", "Clinica Montecarmelo"),
    ("Peluquería Madrid - Centro de estética", "Peluquería Madrid"),  # todo relleno: el primero
])
def test_el_nombre_sin_relleno_de_buscador(captacion, negocio, corto):  # noqa: F811
    assert captacion.nombre_corto(negocio) == corto


def test_sara_dice_el_nombre_corto(captacion):  # noqa: F811
    hecho = captacion.llamar("911111111", "Medicina Estética en Madrid - Dr. Rojas", "estetica", "", origen="auto",
                             cliente=_Falso())
    variables = captacion._variables(captacion._fila(hecho["llamada"]))
    assert variables["negocio"] == "Dr. Rojas"
    assert variables["a_quien"] == "el centro de estética Dr. Rojas"


def test_ningun_mensaje_de_sara_da_el_movil_de_pablo(captacion, monkeypatch):  # noqa: F811
    """Pablo, 30-sep: quien devuelve la llamada llama al 91 (lo atendera Sara), no a su movil."""
    from backend import settings

    monkeypatch.setattr(settings, "CAPTACION_SIP_NUMERO", "+34919934321")
    guion = captacion.agente_de_captacion("https://app.test")["conversation_config"]["agent"]["prompt"]["prompt"]
    textos = [guion, captacion.texto_sms("Pelu", "https://x.es/d"), captacion.correo("Pelu", "https://x.es/d")["texto"],
              captacion.correo("Pelu", "https://x.es/d")["html"]]
    for texto in textos:
        assert "675" not in texto and "ochocientos dos" not in texto
    for texto in textos[1:]:
        assert "919 93 43 21" in texto and "info@vantelia.es" in texto
    assert "usa `pasar_a_pablo`" in guion


def test_quien_pide_una_persona_llega_a_pablo_y_sara_no_vuelve_a_llamarle(captacion, envios, lanzador):  # noqa: F811
    """Astra, 30-sep: Sara prometia "Pablo te llama" y nada le avisaba; y el lanzador podia
    volver a llamarle con Sara."""
    from backend import segunda_oportunidad

    hecho = captacion.llamar("911111111", "Pelu Marta", "peluqueria", "hola@pelu.es", origen="auto", cliente=_Falso())
    captacion._actualizar(hecho["llamada"], interlocutor="empleado", responsable_nombre="Marta",
                          responsable_cuando="por las tardes", conversation_id="conv_1")
    with captacion._db() as conn:  # la llamada fue el dia antes: ya tocaria rellamar
        conn.execute("UPDATE llamadas_voz SET creada=? WHERE id=?",
                     (lanzador._iso(MARTES_10_30 - timedelta(days=1)), hecho["llamada"]))
        conn.commit()
    tarde = MARTES_10_30 + timedelta(days=1, hours=6)  # 16:30 en Madrid, cuando dijeron que esta
    assert len(lanzador.rellamadas_dirigidas(tarde)) == 1, "control: sin pasar a Pablo, Sara le rellamaria"
    r = captacion.herramienta("pasar_a_pablo", {"_llamada": hecho["llamada"], "cuando": "mañana por la tarde",
                                               "nombre": "Lucia"})
    assert r["ok"] is True and "Pablo" in r["mensaje"]
    fila = captacion._fila(hecho["llamada"])
    assert fila["resultado"] == "llamar_pablo"
    assert len(envios["avisos"]) == 1 and "+34911111111" in envios["avisos"][0][1], "Pablo se entera, con el telefono"
    assert "mañana por la tarde" in envios["avisos"][0][1]
    # Ni rellamada dirigida con Sara ni segunda oportunidad por correo: le llama Pablo.
    assert lanzador.rellamadas_dirigidas(tarde) == []
    assert segunda_oportunidad.desenlace_de(fila, "") in segunda_oportunidad.DESENLACES_QUE_CIERRAN


def test_traspasos_y_esperas_eternas(captacion):  # noqa: F811
    guion = captacion.agente_de_captacion("https://app.test")["conversation_config"]["agent"]["prompt"]["prompt"]
    assert "Nunca te despidas ni cuelgues por eso" in guion       # Harmonie, 30-sep: "le pasamos con..."
    assert "se ha repetido cinco veces y no coge nadie" in guion  # Isaac Salido, 30-sep: 300 s en espera


# --- Apertura A (30-sep): permiso y una pregunta antes de ofrecer nada ----------------------

def test_apertura_permiso_y_pregunta_antes_de_ofrecer_nada(captacion):  # noqa: F811
    """Pablo, 30-sep: "la llamada se ve demasiado comercial". 24 llamadas, 0 demos: se perdian
    en el gancho de venta. Primero la apertura A de Astra; luego, el mismo dia, sin la frase
    "es una llamada comercial" y con la pregunta de como atienden a sus clientes."""
    agente = captacion.agente_de_captacion("https://app.test")["conversation_config"]
    guion = agente["agent"]["prompt"]["prompt"]
    assert captacion.APERTURA.endswith("¿Tienes treinta segundos?")
    paso_2 = guion.split("\n2. ", 1)[1].split("\n3. ", 1)[0]
    # 5-oct-2026: la pregunta de como atienden ("¿quien lo coge?") se le hacia a la recepcion,
    # que es quien lo coge: 7 de 12 colgaron justo despues. Ahora, tras el permiso, el motivo
    # y a donde mandar la demo para quien decide.
    assert "{{oferta}}" in paso_2 and "La oferta va TAL CUAL" in paso_2
    assert "¿quien lo coge?" not in guion.lower()
    assert "4. Solo si acepta claramente probarlo" in guion
    assert "soy justo lo que os ofrecemos" not in guion, "el gancho de venta, fuera"
    assert "Si quien contesta dice que es otra IA" in guion  # MARSYA, 29-sep
    assert "no avances de paso solo por seguir el guion" in guion  # Div@, 29-sep
    assert "Si es ella o se pone: pidele treinta segundos" in guion  # rellamada: "¿Esta Marta?"
    colgar = [t for t in agente["agent"]["prompt"]["tools"] if t["name"] == "end_call"][0]
    assert "traspaso" in colgar["description"]  # Harmonie, 30-sep


# --- Como un setter (Pablo, 30-sep): ver si le interesa y, si si, que le llame Pablo -------

def test_si_le_interesa_sara_propone_que_le_llame_pablo_con_dos_huecos(captacion):  # noqa: F811
    """Pablo: "que actue como un setter de ventas profesional"; el objetivo es ver si le
    interesa la IA que da sus citas, y el siguiente paso es que le llame el (L-V, a cualquier
    hora). Un setter no pregunta "¿cuando te va bien?": propone dos huecos."""
    agente = captacion.agente_de_captacion("https://app.test")["conversation_config"]["agent"]
    guion = agente["prompt"]["prompt"]
    paso_3 = guion.split("\n3. ", 1)[1].split("\n4. ", 1)[0]
    # 5-oct-2026: a la recepcion ya no se le pregunta si le vendria bien (no le toca decidir):
    # cada respuesta vuelve a la demo para quien decide.
    assert "usa `enviar_informacion` en ESE MISMO turno (paso 6)" in paso_3
    assert "Si dice que no es ella quien decide: justo por eso es la demo" in paso_3
    assert "es solo eso: me dices un email y la veis cuando podais" in paso_3, "a quien esta liada, lo minimo"
    # 1-oct (Pablo): el cierre es la demo gratuita por SMS o email, no "¿te llamo Pablo?". Si
    # prefiere que le llamen, entonces si los dos huecos concretos.
    paso_6 = guion.split("\n6. ", 1)[1].split("\n7. ", 1)[0]
    assert "LA DEMO GRATUITA" in paso_6 and '"{{oferta}}"' in paso_6
    for canal in ("sms", "email", "pedir_email"):
        oferta = captacion.oferta_de_demo(canal, "Pelu Marta", "hola arroba pelu punto es")
        assert "una pequeña demo gratuita" in oferta and "quien lleve el negocio" in oferta, canal
    assert "usa `enviar_informacion` en ESE MISMO turno" in paso_6
    assert "Si prefiere que le llamemos" in paso_6 and "{{huecos_pablo}}" in paso_6
    assert "usa `pasar_a_pablo` en ESE MISMO turno" in paso_6
    assert "si pide sabado o domingo, propon el lunes" in paso_6
    assert "¿Te parece que te llame Pablo" not in guion
    assert "Si pide que le mandes informacion: ve directa al paso 6" in guion
    assert "ofrece la demo gratuita (paso 6)" in guion  # si se alarga
    # Nada de frases de folleto.
    assert "Nada de frases de vendedora ni de folleto" in guion
    herramienta = [t for t in agente["prompt"]["tools"] if t["name"] == "pasar_a_pablo"][0]
    assert "Cuando prefiera que le llame Pablo" in herramienta["description"]
    # Las entrantes no traen huecos calculados: el valor por defecto sirve igual en la frase.
    assert agente["dynamic_variables"]["dynamic_variable_placeholders"]["huecos_pablo"] == (
        "entre semana, por la mañana o por la tarde")


@pytest.mark.parametrize("hora_utc,huecos", [
    ("2026-09-29T08:30:00+00:00", "mañana por la mañana o el jueves por la tarde"),  # martes
    ("2026-10-01T08:30:00+00:00", "mañana por la mañana o el lunes por la tarde"),  # jueves
    ("2026-10-02T08:30:00+00:00", "el lunes por la mañana o el martes por la tarde"),  # viernes
    ("2026-10-03T08:30:00+00:00", "el lunes por la mañana o el martes por la tarde"),  # sabado
    ("2026-10-04T08:30:00+00:00", "mañana por la mañana o el martes por la tarde"),  # domingo
    # 23:30 UTC del lunes ya es martes en Madrid: cuenta el dia de Madrid.
    ("2026-09-28T23:30:00+00:00", "mañana por la mañana o el jueves por la tarde"),
])
def test_los_huecos_de_pablo_son_de_lunes_a_viernes_y_nunca_hoy(captacion, hora_utc, huecos):  # noqa: F811
    from datetime import datetime

    assert captacion.huecos_de_pablo(datetime.fromisoformat(hora_utc)) == huecos


def test_a_quien_le_interesa_le_llama_pablo_y_el_aviso_lo_dice(captacion, envios):  # noqa: F811
    hecho = captacion.llamar("911111111", "Pelu Marta", "peluqueria", "", origen="auto", cliente=_Falso())
    r = captacion.herramienta("pasar_a_pablo", {"_llamada": hecho["llamada"], "cuando": "el jueves por la tarde",
                                               "notas": "pierden llamadas cuando estan con clientas"})
    assert r["ok"] is True and "Confirmaselo" in r["mensaje"]
    fila = captacion._fila(hecho["llamada"])
    assert fila["resultado"] == "llamar_pablo" and "Le llama Pablo" in fila["notas"]
    asunto, texto = envios["avisos"][0][0], envios["avisos"][0][1]
    assert asunto.startswith("🙋 Llámale") and "han quedado en que les llamas tu" in texto
    assert "el jueves por la tarde" in texto and "pierden llamadas" in texto


def test_al_llamar_calla_y_la_apertura_cuando_contestan(captacion):  # noqa: F811
    """Pablo, 30-sep: soltaba la apertura en el segundo 0, encima del "¿digame?", y se paso a
    "¿Hola?" primero. 5-oct: ese "¿Hola?" se pisaba con el saludo de la recepcion, le
    contestaban "hola" y la cortaban: "Hola, soy... Hola, soy Sara... Hola, soy Sara, una IA" en
    4 de 16 llamadas. Ahora calla hasta que hablan (o SEGUNDOS_ANTES_DE_EMPEZAR), y un "hola"
    o un "buenos dias" sueltos no la interrumpen. En una entrante coge ella: saludo entero."""
    config = captacion.agente_de_captacion("https://app.test")["conversation_config"]
    agente = config["agent"]
    assert agente["first_message"] == ""
    assert agente["dynamic_variables"]["dynamic_variable_placeholders"]["primera"] == captacion.SALUDO_ENTRANTE
    assert config["turn"]["initial_wait_time"] == captacion.SEGUNDOS_ANTES_DE_EMPEZAR
    assert {"hola", "buenos días", "dígame"} <= set(config["turn"]["interruption_ignore_terms"])
    assert "no" not in config["turn"]["interruption_ignore_terms"], "un no tiene que cortarla"
    hecho = captacion.llamar("911111111", "Pelu Marta", "peluqueria", "", origen="auto", cliente=_Falso())
    variables = captacion._variables(captacion._fila(hecho["llamada"]))
    # "primera" se sigue mandando, vacia: un agente aun sin sincronizar la exige.
    assert (variables["primera"], variables["saludo"]) == ("", captacion.APERTURA)
    paso_1 = agente["prompt"]["prompt"].split("\n1. ", 1)[1].split("\n2. ", 1)[0]
    assert "No dices nada hasta que contesten" in paso_1 and '"{{saludo}}"' in paso_1
    assert "no vuelvas a empezar: termina la frase" in paso_1


# --- Revision de Astra (29-sep): coherencia del guion y tope de duracion --------------------

def test_al_apuntar_a_la_duena_la_herramienta_no_manda_repetir_la_demo(captacion):  # noqa: F811
    """El paso 5 pregunta por quien decide DESPUES de la demo, y la herramienta contestaba
    "sigue con la demostracion": dos ordenes que chocan."""
    hecho = captacion.llamar("911111111", "Pelu Marta", "peluqueria", "", origen="auto", cliente=_Falso())
    r = captacion.herramienta("anotar_responsable", {"_llamada": hecho["llamada"], "interlocutor": "duena_o_encargada"})
    assert r["ok"] is True and "demostracion" not in r["mensaje"]


def test_las_salidas_mandan_y_estan_claras(captacion):  # noqa: F811
    guion = captacion.agente_de_captacion("https://app.test")["conversation_config"]["agent"]["prompt"]["prompt"]
    assert "las SALIDAS de abajo mandan sobre estos pasos" in guion
    assert "nunca cuelgues sin despedirte" in guion  # 30-sep: colgo tras "no, gracias" sin decir nada
    assert "Si pide que le mandes informacion: ve directa al paso 6" in guion
    assert "sin repetir la apertura entera" in guion
    assert "ni finjas que le pasas la llamada" in guion
    # Rellamada a quien decide que no esta: sin demo a quien coge.
    assert "sin preguntas ni demostracion a quien te ha cogido" in guion
    # Menu de teclas (5-oct, "para español pulse 1"): solo la opcion de español, recepcion, cita
    # o una persona, una vez; si vuelve el menu o nada encaja, colgar sin decir nada.
    assert "pulsa esa tecla UNA sola vez con `play_keypad_touch_tone`" in guion
    assert "Nunca pulses ninguna otra opcion" in guion
    assert "Si tras pulsar vuelve el mismo menu, o si ninguna opcion encaja, cuelga" in guion


def test_la_llamada_tiene_un_tope_de_duracion(captacion):  # noqa: F811
    agente = captacion.agente_de_captacion("https://app.test")
    assert agente["conversation_config"]["conversation"]["max_duration_seconds"] == 300
    assert agente["conversation_config"]["turn"]["silence_end_call_timeout"] == 75, "el silencio, como estaba"


# --- Si no hablo nadie: se reintenta y no hay correo --------------------------------------

def _analisis(**datos):
    base = {"interlocutor": "no_se_sabe", "desenlace": "buzon", "hablo_una_persona": False}
    base.update(datos)
    return {"data_collection_results": {k: {"value": v} for k, v in base.items()}}


@pytest.mark.parametrize("datos,resultado", [
    ({}, "contestador"),                                                    # centralita o buzon
    ({"hablo_una_persona": "false"}, "contestador"),                        # en texto
    ({"desenlace": "colgo_al_principio"}, "contestador"),                   # Montecarmelo, 29-sep
    ({"hablo_una_persona": True, "desenlace": "colgo_al_principio"}, ""),   # colgo una persona
    ({"hablo_una_persona": None}, ""),                                      # no se sabe: no se toca
    ({"desenlace": "rechazo"}, ""),                                         # contradice: ante la duda, no
    ({"desenlace": "ocupado_sin_rechazo"}, ""),
])
def test_solo_un_no_claro_la_marca_como_contestador(llamada, envios, datos, resultado):  # noqa: F811
    llamada_id, transcripciones = llamada
    transcripciones.guardar(_conversacion(**_analisis(**datos)), "aviso")
    assert transcripciones.captacion_voz._fila(llamada_id)["resultado"] == resultado


def test_no_pisa_lo_que_apunto_sara(llamada, envios, captacion):  # noqa: F811
    llamada_id, transcripciones = llamada
    captacion.herramienta("no_volver_a_llamar", {"_llamada": llamada_id, "motivo": "no llameis"})
    transcripciones.guardar(_conversacion(**_analisis()), "aviso")
    assert captacion._fila(llamada_id)["resultado"] == "no_llamar"


def test_si_no_hablo_nadie_no_se_manda_nada_aunque_el_analisis_diga_que_si(llamada, envios):  # noqa: F811
    _, transcripciones = llamada
    # Sin desenlace (con "buzon" el respaldo ya se frena solo): lo que frena es el orden,
    # marcar "contestador" ANTES de mirar el respaldo.
    transcripciones.guardar(_conversacion(**_analisis(desenlace="", quiere_informacion=True,
                                                      email_para_informacion="jose@pelu.es")), "aviso")
    assert envios["email"] == [] and envios["sms"] == []


def test_un_buzon_o_una_centralita_se_vuelve_a_llamar(lanzador):  # noqa: F811
    """Por SIP la llamada tiene conversacion aunque solo contestara una grabacion."""
    _prospecto(lanzador, "centralita@clinica.es", "911111111", sector="clinica estetica")
    _prospecto(lanzador, "persona@pelu.es", "912222222")
    hace_tres_dias = MARTES_10_30 - timedelta(days=3)
    _llamada_previa(lanzador, "+34911111111", hace_tres_dias, resultado="contestador")
    _llamada_previa(lanzador, "+34912222222", hace_tres_dias, resultado="")
    with lanzador._db() as conn:
        conn.execute("UPDATE llamadas_voz SET conversation_id='conv_' || telefono")
        conn.commit()
    candidatos = lanzador.candidatos(MARTES_10_30)
    assert [(c["telefono"], c["intentos"]) for c in candidatos] == [("+34911111111", 1)], (
        "la centralita vuelve (segundo intento); con quien hablo una persona, no")

    # Y como mucho dos intentos: si el segundo tambien es centralita, se acabo.
    _llamada_previa(lanzador, "+34911111111", MARTES_10_30 - timedelta(days=1), resultado="contestador")
    assert lanzador.candidatos(MARTES_10_30 + timedelta(days=3)) == []


def test_si_no_hablo_nadie_no_hay_segunda_oportunidad(captacion):  # noqa: F811
    from backend import segunda_oportunidad

    analisis = '{"data_collection_results": {"desenlace": {"value": "colgo_al_principio"}}}'
    assert segunda_oportunidad.desenlace_de({"resultado": "contestador"}, analisis) == "buzon"
    assert segunda_oportunidad.desenlace_de({"resultado": ""}, analisis) == "colgo_al_principio"
