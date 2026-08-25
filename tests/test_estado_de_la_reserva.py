# -*- coding: utf-8 -*-
"""El codigo sabe que falta para coger la cita, y en que orden se pregunta.

Esto sustituye a los doce detectores que leian el texto del modelo. Aquellos solo
se podian probar conversando (caro, lento y distinto cada vez); esto se prueba sin
modelo, asi que la decision es la MISMA siempre y se puede afirmar en un test.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


@pytest.fixture
def estado(api_module):  # noqa: F811
    from backend import reserva

    return reserva.Estado()


# ─── El orden de las preguntas ─────────────────────────────────────────────

def test_primero_que_se_quiere_hacer(estado, api_module):  # noqa: F811
    """De eso dependen la duracion y el precio: preguntar el dia antes fue un fallo."""
    from backend import reserva

    reserva.anotar_intencion(estado, "reservar")
    assert reserva.que_falta(estado) == "servicio"


def test_luego_el_dia_y_luego_la_hora(estado, api_module):  # noqa: F811
    from backend import reserva

    reserva.anotar_intencion(estado, "reservar")
    reserva.anotar_resultado(estado, "buscar_servicio", {},
                             {"ok": True, "servicio": "Corte señora", "duracion_minutos": 30})
    assert reserva.que_falta(estado) == "dia"

    reserva.anotar_resultado(estado, "consultar_disponibilidad", {"fecha": "2026-09-01"},
                             {"ok": True, "huecos": ["10:00", "10:15"]})
    assert reserva.que_falta(estado) == "hora"

    estado.hora = "10:00"
    assert reserva.que_falta(estado) == "nombre"

    estado.nombre = "Marta"
    assert reserva.que_falta(estado) == ""


def test_a_la_clienta_conocida_no_le_falta_el_nombre(estado, api_module):  # noqa: F811
    from backend import reserva

    reserva.anotar_intencion(estado, "reservar")
    estado.servicio, estado.fecha, estado.hora = "Corte señora", "2026-09-01", "10:00"
    assert reserva.que_falta(estado, nombre_conocido="Marta Ruiz") == ""


# ─── Gestionar una cita ya cogida ──────────────────────────────────────────

def test_para_cancelar_no_se_pregunta_el_servicio(estado, api_module):  # noqa: F811
    """Le preguntaba que tratamiento queria a quien solo iba a anular su cita."""
    from backend import reserva

    reserva.anotar_intencion(estado, "cancelar")
    assert reserva.que_falta(estado) == "codigo"

    reserva.anotar_resultado(estado, "consultar_cita", {},
                             {"ok": True, "codigo_reserva": "R-1234",
                              "servicio": "Mechas", "fecha": "2026-09-01", "hora": "10:00"})
    assert reserva.que_falta(estado) == ""
    assert "cancelar_cita" in reserva.instruccion(estado)


def test_al_reprogramar_se_remata_con_reprogramar_no_con_crear(estado, api_module):  # noqa: F811
    """Forzar `crear_cita` en plena reprogramacion creaba una SEGUNDA cita."""
    from backend import reserva

    reserva.anotar_intencion(estado, "reprogramar")
    reserva.anotar_resultado(estado, "consultar_cita", {},
                             {"ok": True, "codigo_reserva": "R-1234", "servicio": "Mechas",
                              "fecha": "2026-09-01", "hora": "10:00"})
    reserva.anotar_resultado(estado, "consultar_disponibilidad", {"fecha": "2026-09-02"},
                             {"ok": True, "huecos": ["11:00"]})
    estado.hora = "11:00"
    instruccion = reserva.instruccion(estado)
    assert "reprogramar_cita" in instruccion
    assert "crear_cita" not in instruccion


def test_hecha_la_gestion_un_vale_no_la_rehace(estado, api_module):  # noqa: F811
    """Reprogramaba bien, la clienta decia "vale", y la devolvia a su hora."""
    from backend import reserva

    reserva.anotar_intencion(estado, "reprogramar")
    reserva.anotar_resultado(estado, "reprogramar_cita", {},
                             {"ok": True, "codigo_reserva": "R-1234",
                              "fecha": "2026-09-02", "hora": "11:00"})
    assert estado.hecho
    assert reserva.que_falta(estado) == ""
    assert "acuse de recibo" in reserva.instruccion(estado)


# ─── Lo que dice la clienta ────────────────────────────────────────────────

def test_le_da_igual_el_dia_y_no_se_le_repregunta(estado, api_module):  # noqa: F811
    """"cualquier otro hueco que tengas me vale" y le seguia preguntando el dia."""
    from backend import reserva

    reserva.anotar_intencion(estado, "reservar")
    estado.servicio = "Corte señora"
    reserva.anotar_lo_que_dice(estado, "cualquier otro hueco que tengas me vale")
    assert estado.dia_le_da_igual
    assert "NO le preguntes que dia" in reserva.instruccion(estado)


def test_con_el_dia_igual_y_huecos_se_coge_el_primero(estado, api_module):  # noqa: F811
    from backend import reserva

    reserva.anotar_intencion(estado, "reservar")
    estado.servicio = "Corte señora"
    reserva.anotar_lo_que_dice(estado, "el primer hueco que tengas")
    reserva.anotar_resultado(estado, "consultar_disponibilidad", {"fecha": "2026-09-01"},
                             {"ok": True, "huecos": ["10:00", "10:15"]})
    assert "10:00" in reserva.instruccion(estado)


# ─── El estado sale de las tools, no del modelo ────────────────────────────

def test_una_tool_que_falla_no_ensucia_el_estado(estado, api_module):  # noqa: F811
    """Si `buscar_servicio` no encontro nada, el servicio NO esta elegido."""
    from backend import reserva

    reserva.anotar_intencion(estado, "reservar")
    reserva.anotar_resultado(estado, "buscar_servicio", {},
                             {"ok": False, "error": "Dime que te quieres hacer."})
    assert estado.servicio == ""
    assert reserva.que_falta(estado) == "servicio"


def test_un_dia_sin_huecos_no_se_da_por_elegido(estado, api_module):  # noqa: F811
    from backend import reserva

    reserva.anotar_intencion(estado, "reservar")
    estado.servicio = "Corte señora"
    reserva.anotar_resultado(estado, "consultar_disponibilidad", {"fecha": "2026-09-01"},
                             {"ok": True, "huecos": [], "hay_huecos": False})
    assert estado.fecha == ""
    assert reserva.que_falta(estado) == "dia"


def test_lo_que_ya_sabe_se_le_recuerda(estado, api_module):  # noqa: F811
    from backend import reserva

    estado.servicio, estado.duracion = "Mechas medio", 75
    estado.fecha, estado.hora = "2026-09-01", "10:00"
    texto = reserva.resumen(estado, nombre_conocido="Marta")
    assert "Mechas medio (75 min)" in texto
    assert "2026-09-01" in texto and "10:00" in texto and "Marta" in texto


def test_la_conversacion_de_otro_dia_no_cuenta(api_module):  # noqa: F811
    """Mismo criterio que el historial: un silencio largo cierra la conversacion."""
    import time

    from backend import reserva

    estado = reserva.Estado(servicio="Mechas")
    reserva.guardar("demo", "34600111222", estado)
    # Guardar refresca la marca a proposito (guardar = hay actividad), asi que se
    # envejece DESPUES para simular el silencio.
    estado.tocado = time.time() - (reserva.CADUCA_EN + 60)
    assert not estado.vigente()

    recuperado = reserva.cargar("demo", "34600111222")
    assert recuperado.servicio == "", "se cuela la conversacion caducada"


def test_sin_intencion_no_dirige_la_conversacion(estado, api_module):  # noqa: F811
    """Quien pregunta cuanto dura unas mechas NO esta cogiendo cita.

    Al remodelar, el estado empezo a contestar "dime que te quieres hacer" a
    cualquiera: secuestraba las preguntas informativas y el asistente dejo de
    decir la duracion y de reconocer que la manicura no la hacen.
    """
    from backend import reserva

    assert reserva.que_falta(estado) == ""
    assert reserva.instruccion(estado) == "" or "servicio" not in reserva.instruccion(estado)

    # Con intencion declarada si dirige.
    reserva.anotar_intencion(estado, "reservar")
    assert reserva.que_falta(estado) == "servicio"


def test_lo_que_ella_dice_tambien_cuenta(estado, api_module):  # noqa: F811
    """Si el estado solo escuchara a las tools, "el jueves" no quedaria anotado.

    Medido: repetir la misma pregunta se disparo de 3 a 15 conversaciones de 40
    cuando el estado solo se llenaba con resultados de herramientas.
    """
    from backend import reserva

    reserva.anotar_intencion(estado, "reservar")
    estado.servicio = "Corte señora"
    reserva.anotar_lo_que_dice(estado, "me viene bien el 15 de septiembre a las 10:30",
                               "Europe/Madrid")
    assert estado.fecha and estado.hora == "10:30"
    assert reserva.que_falta(estado) == "nombre"


def test_no_le_repite_la_misma_pregunta(estado, api_module):  # noqa: F811
    """Preguntar lo mismo con las mismas palabras dos veces es un muro."""
    from backend import reserva

    reserva.anotar_intencion(estado, "reservar")
    primera = reserva.instruccion(estado)
    reserva.guardar("demo", "34600999888", estado, pedido="servicio")
    segunda = reserva.instruccion(estado)
    assert segunda != primera
    assert "de otra manera" in segunda


def test_el_codigo_de_reserva_se_pilla_del_mensaje(estado, api_module):  # noqa: F811
    from backend import reserva

    reserva.anotar_intencion(estado, "cancelar")
    reserva.anotar_lo_que_dice(estado, "es la R-123456", "Europe/Madrid")
    assert estado.codigo == "R-123456"


def test_solo_se_le_dirige_para_cerrar(estado, api_module):  # noqa: F811
    """La conversacion la lleva el modelo; el cierre lo decide el codigo.

    Medido en tres tiradas de 40 conversaciones: dirigiendole tambien la recogida
    de datos, repetir la misma pregunta paso de 3 a 15; sin dirigirle nada, la
    reserva no se cerraba nunca (critico, 2 de 2).
    """
    from backend import reserva

    reserva.anotar_intencion(estado, "reservar")
    # El PRIMER dato si se dirige (ver el test de abajo): sin saber que se quiere
    # hacer, ofrecer horas es empezar por el tejado.
    assert "no le ofrezcas dias ni horas" in reserva.instruccion_de_cierre(estado)
    # A partir de ahi, recogiendo datos, el modelo va libre.
    estado.servicio = "Corte señora"
    assert reserva.instruccion_de_cierre(estado) == ""

    # Con todo en la mano: se le dice que remate, y con que herramienta.
    estado.fecha, estado.hora, estado.nombre = "2026-09-01", "10:00", "Marta"
    assert "crear_cita" in reserva.instruccion_de_cierre(estado)


def test_el_servicio_se_pide_una_vez_y_no_se_repite(estado, api_module):  # noqa: F811
    """Sin saber que se quiere hacer, ofrecer horas es empezar por el tejado.

    Pero pedirlo con las mismas palabras turno tras turno era el muro que disparo
    "repite la misma pregunta" de 3 a 15 conversaciones de cada 40. Se dirige la
    primera vez; despues, el modelo busca otra forma.
    """
    from backend import reserva

    reserva.anotar_intencion(estado, "reservar")
    primera = reserva.instruccion_de_cierre(estado)
    assert "no le ofrezcas dias ni horas" in primera

    reserva.guardar("demo", "34600777111", estado, pedido="servicio")
    assert reserva.instruccion_de_cierre(estado) == ""


def test_entiende_la_hora_dicha_en_cristiano(estado, api_module):  # noqa: F811
    """"a las 14" no lo entendia el parser (solo "14:00") y se perdia.

    Paso de verdad: la clienta eligio "a las 14", el estado se quedo sin hora, no
    se monto el resumen para confirmar y se quedo esperando.
    """
    from backend import reserva

    reserva.anotar_intencion(estado, "reservar")
    estado.servicio = "Color raices"
    reserva.anotar_resultado(estado, "consultar_disponibilidad", {"fecha": "2026-09-01"},
                             {"ok": True, "huecos": ["10:00", "14:00", "17:00", "17:30"]})
    reserva.anotar_lo_que_dice(estado, "a las 14", "Europe/Madrid")
    assert estado.hora == "14:00"


def test_una_hora_que_no_existe_no_se_anota(estado, api_module):  # noqa: F811
    """Se contrasta con los huecos REALES: no se puede inventar una hora."""
    from backend import reserva

    reserva.anotar_intencion(estado, "reservar")
    estado.servicio = "Color raices"
    reserva.anotar_resultado(estado, "consultar_disponibilidad", {"fecha": "2026-09-01"},
                             {"ok": True, "huecos": ["10:00", "10:15"]})
    reserva.anotar_lo_que_dice(estado, "a las 23", "Europe/Madrid")
    assert estado.hora == ""


def test_las_cinco_de_la_tarde_son_las_17(estado, api_module):  # noqa: F811
    from backend import reserva

    assert reserva._hora_coloquial("las 5 de la tarde", ["10:00", "17:00"]) == "17:00"
    assert reserva._hora_coloquial("sobre las 17", ["17:00", "17:30"]) == "17:00"


def test_una_cita_cogida_no_se_vuelve_a_montar(estado, api_module):  # noqa: F811
    """Olvidar el estado no basta: el modelo relee la conversacion y monta otra.

    Medido con 100 clientas simuladas: cinco citas DUPLICADAS y "repite la misma
    pregunta" disparado de 14 a 38. La clienta decia que si por educacion a un
    resumen que no habia pedido, y nacia una segunda cita.
    """
    from backend import reserva

    reserva.anotar_intencion(estado, "reservar")
    estado.servicio, estado.fecha, estado.hora, estado.nombre = "Corte", "2026-09-01", "10:00", "Ana"
    reserva.guardar("demo", "34600555111", estado)

    reserva.marcar_hecha("demo", "34600555111", "R-1234")
    despues = reserva.cargar("demo", "34600555111")
    assert despues.hecho and despues.codigo == "R-1234"

    instruccion = reserva.instruccion_de_cierre(despues)
    assert "YA ESTA COGIDA" in instruccion
    assert "R-1234" in instruccion
    assert reserva.tool_que_remata(despues) == "", "no puede rematar nada mas"


def test_delante_del_resumen_se_puede_cambiar_de_idea(api_module, client):  # noqa: F811
    """"Pulsa Confirmar o Cancelar" es un callejon sin salida.

    Paso de verdad: con el resumen delante, el cliente escribio "quiero un alisado
    de acido lactico" y la unica respuesta fue "Pulsa Confirmar o Cancelar". O
    aceptaba una cita que no queria, o se iba.
    """
    from backend import whatsapp

    # Nombrar otro servicio, o decir "mejor...", cuenta como cambio de idea.
    assert whatsapp._wa_cambia_el_servicio("demo", "espera, mejor un alisado")
    assert whatsapp._wa_cambia_el_servicio("demo", "prefiero otra cosa")
    assert whatsapp._wa_cambia_el_servicio("demo", "en vez de eso, un corte")
    # Un si o un gracias no lo son.
    assert not whatsapp._wa_cambia_el_servicio("demo", "si, confirmo")
    assert not whatsapp._wa_cambia_el_servicio("demo", "gracias")


def test_mirar_la_agenda_no_es_elegir_dia(estado, api_module):  # noqa: F811
    """El modelo consulta varios dias seguidos para poder ofrecer.

    El estado se quedaba con el ULTIMO consultado: decia "mañana miercoles 26" y
    el resumen ponia "jueves 27". La clienta lo corrigio CUATRO veces sin exito.
    """
    from backend import reserva

    reserva.anotar_intencion(estado, "reservar")
    estado.servicio = "Corte señora"
    reserva.anotar_lo_que_dice(estado, "podria ir el miercoles 26 de agosto", "Europe/Madrid")
    elegido = estado.fecha
    assert elegido, "no ha cogido la fecha que dijo ella"

    # Consultar otros dias NO cambia el elegido.
    for otro in ("2026-08-27", "2026-08-28"):
        reserva.anotar_resultado(estado, "consultar_disponibilidad", {"fecha": otro},
                                 {"ok": True, "huecos": ["10:00", "10:15"]})
    assert estado.fecha == elegido


def test_si_corrige_la_fecha_se_le_hace_caso(estado, api_module):  # noqa: F811
    """Corregir un dato es lo primero que hace quien ve un resumen equivocado."""
    from backend import reserva

    reserva.anotar_intencion(estado, "reservar")
    estado.servicio = "Corte señora"
    reserva.anotar_lo_que_dice(estado, "el 27 de agosto", "Europe/Madrid")
    primera = estado.fecha
    estado.hora = "10:00"

    reserva.anotar_lo_que_dice(estado, "no, el 26 de agosto", "Europe/Madrid")
    assert estado.fecha != primera, "no le hace caso al corregir"
    assert estado.hora == "", "el hueco de otro dia no puede darse por bueno"


def test_decir_cancelar_basta_para_que_se_cancele(api_module):  # noqa: F811
    """Sin declarar la intencion, nadie obligaba a llamar a `cancelar_cita`.

    A "quiero cancelar mi cita" el asistente contestaba preguntandole que servicio
    queria y para que dia: la cita seguia en pie y el cliente creyendo lo
    contrario. La intencion la fija el CODIGO leyendo lo que ella pide.
    """
    from backend import reserva

    estado = reserva.Estado(codigo="R-1234", servicio="Corte", fecha="2026-09-01",
                            hora="10:00", nombre="Ana")
    reserva.anotar_lo_que_dice(estado, "quiero cancelar mi cita", "Europe/Madrid")
    assert estado.intencion == "cancelar"
    assert reserva.tool_que_remata(estado, "Ana") == "cancelar_cita"


def test_si_duda_entre_cancelar_y_cambiar_no_se_decide_por_ella(api_module):  # noqa: F811
    from backend import reserva

    estado = reserva.Estado(codigo="R-1234")
    reserva.anotar_lo_que_dice(estado, "quiero cancelar o cambiar mi cita", "Europe/Madrid")
    assert estado.intencion == "", "se ha decidido por ella en vez de preguntarle"


def test_pedir_moverla_declara_reprogramar(api_module):  # noqa: F811
    from backend import reserva

    estado = reserva.Estado(codigo="R-1234")
    reserva.anotar_lo_que_dice(estado, "puedo moverla a otro dia?", "Europe/Madrid")
    assert estado.intencion == "reprogramar"

    # Sin cita que mover no se declara nada: quien pregunta si puede cambiar de
    # dia antes de tener cita no esta reprogramando nada.
    otra = reserva.Estado()
    reserva.anotar_lo_que_dice(otra, "puedo moverla a otro dia?", "Europe/Madrid")
    assert otra.intencion == ""


def test_se_puede_pedir_una_segunda_cita_en_la_misma_conversacion(api_module):  # noqa: F811
    """Paso de verdad y la segunda cita no se creo NUNCA.

    Cogio una cita, luego pidio otra para un alisado, y el asistente le contesto
    tres veces seguidas describiendole la PRIMERA ("ya tienes tu cita de mechas
    mañana a las 10:00"). El estado se queda en "hecho" a proposito -para que no
    monte dos veces la misma y salgan duplicadas- pero eso la dejaba sin poder
    pedir una segunda.
    """
    from backend import reserva

    estado = reserva.Estado(intencion="reservar", servicio="Mechas o balayage medio",
                            fecha="2026-08-26", hora="10:00", nombre="Pablo",
                            codigo="R-1234", hecho=True, recargo_dicho=True)
    reserva.anotar_lo_que_dice(estado, "quiero cita para el alisado", "Europe/Madrid")

    assert estado.hecho is False, "sigue creyendo que ya termino"
    assert estado.servicio == "" and estado.fecha == "" and estado.hora == ""
    assert estado.codigo == "", "arrastraba el numero de la cita anterior"
    assert estado.intencion == "reservar"
    # Lo que se sabe de ELLA no se toca: repreguntarlo es lo que molesta.
    assert estado.nombre == "Pablo"
    assert estado.recargo_dicho is True


def test_hablar_de_la_cita_que_ya_tiene_no_empieza_otra(api_module):  # noqa: F811
    """Cancelar o mover la de siempre NO es pedir una nueva."""
    from backend import reserva

    for dicho in ("quiero cancelar mi cita", "puedes mover la cita a otro dia?",
                  "a que hora era mi cita?"):
        estado = reserva.Estado(servicio="Corte", fecha="2026-08-26", hora="10:00",
                                codigo="R-1234", hecho=True)
        reserva.anotar_lo_que_dice(estado, dicho, "Europe/Madrid")
        assert estado.codigo == "R-1234", "se ha cargado la cita que tenia: %r" % dicho


def test_la_segunda_cita_se_monta_de_verdad(api_module):  # noqa: F811
    """Y con el estado limpio, el motor vuelve a pedir lo que falta."""
    from backend import reserva

    estado = reserva.Estado(hecho=True, nombre="Pablo")
    reserva.anotar_lo_que_dice(estado, "tambien quiero una cita para un corte", "Europe/Madrid")
    assert reserva.que_falta(estado, "Pablo") == "servicio"


def test_la_primera_que_tengas_elige_hora_de_verdad(api_module):  # noqa: F811
    """Estaba escrito como instruccion y el modelo volvia a ofrecer la lista.

    Medido: es el fallo mas repetido de todas las tiradas, y se llevaba por
    delante el caso mas simple que existe -venir a cortarse el pelo-. La clienta
    decia "la primera que tengas", le ofrecian horas otra vez, decia "vale", y le
    ofrecian horas OTRA VEZ. Se iba sin cita.
    """
    from backend import reserva

    estado = reserva.Estado(intencion="reservar", servicio="Corte senora",
                            huecos=["10:00", "10:15", "10:30"],
                            fecha_de_los_huecos="2026-08-27")
    reserva.anotar_lo_que_dice(estado, "la primera que tengas", "Europe/Madrid")

    assert estado.hora == "10:00", "no ha elegido: seguira preguntando la hora"
    assert estado.fecha == "2026-08-27"
    assert reserva.que_falta(estado, "Ana") == "", "aun cree que falta algo"


def test_si_dice_una_hora_concreta_manda_la_suya(api_module):  # noqa: F811
    from backend import reserva

    estado = reserva.Estado(intencion="reservar", servicio="Corte senora",
                            huecos=["10:00", "10:15", "10:30"],
                            fecha_de_los_huecos="2026-08-27")
    reserva.anotar_lo_que_dice(estado, "mejor la de las 10:30", "Europe/Madrid")
    assert estado.hora == "10:30"
