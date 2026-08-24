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
