# -*- coding: utf-8 -*-
"""El resumen dice el servicio que quiere AHORA, no el primero que nombro.

Conversacion real del salon piloto (26-ago-2026). La clienta empieza asi:

    ELLA: Pues me gustaria hacerme unas mechas y cortarme
    ELLA: Mi cabello es medio por los hombros y el corte es para mi de senyora

y ahi se guarda "Corte senora". VEINTE mensajes despues esta eligiendo un
alisado: pregunta por la queratina, por el acido lactico bio premium, pide hora
con Alicia, da su nombre... y el resumen final dice:

    IA: Te resumo lo que tenemos:
        - Servicio: Corte senora

POR QUE PASABA: al frenar la creacion para que la confirme ella, el estado solo
rellenaba los campos VACIOS. El servicio ya no estaba vacio -llevaba veinte
mensajes ahi-, asi que ganaba siempre lo PRIMERO que se dijo, pasara lo que
pasara despues.

Lo que la clienta va a ver y confirmar es lo que trae la llamada: el estado no
puede contradecirlo.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module  # noqa: F401


def _pendiente(estado, servicio):
    """Lo que ocurre cuando el agente frena `crear_cita` esperando el boton."""
    from backend import reserva

    reserva.anotar_resultado(
        estado, "crear_cita",
        {"servicio": servicio, "fecha": "2026-09-03", "hora": "14:00",
         "nombre": "Alicia Rincon Espinosa"},
        {"ok": False, "pendiente_de_confirmacion": True},
    )
    return estado


def test_el_servicio_nuevo_pisa_al_de_hace_veinte_mensajes(api_module):  # noqa: F811
    from backend import reserva

    estado = reserva.Estado()
    estado.servicio = "Corte senora"          # de cuando dijo "y cortarme"
    estado.servicio_exacto = "Corte senora"
    estado.duracion = 20

    _pendiente(estado, "Acido lactico bio premium largo")

    assert estado.servicio == "Acido lactico bio premium largo", (
        "el resumen volveria a decirle 'Corte senora' despues de veinte mensajes "
        "hablando de un alisado"
    )
    assert estado.servicio_exacto == "", (
        "el nombre exacto era el del servicio viejo: hay que resolverlo de nuevo"
    )
    assert estado.duracion == 0, "20 minutos para un alisado de horas"


def test_el_mismo_servicio_dicho_de_otra_forma_no_se_toca(api_module):  # noqa: F811
    """"Pack keratina premium medio" y "keratina premium medio" son el MISMO
    servicio dicho de dos maneras... pero en el catalogo tambien existen como dos
    servicios distintos, de 30 minutos y de casi cuatro horas. Soltar el nombre
    exacto aqui es como se cogio media hora para un tratamiento de cuatro."""
    from backend import reserva

    estado = reserva.Estado()
    estado.servicio = "Keratina premium medio"
    estado.servicio_exacto = "Pack keratina premium medio"
    estado.duracion = 225

    _pendiente(estado, "Keratina premium medio")

    assert estado.servicio_exacto == "Pack keratina premium medio"
    assert estado.duracion == 225


def test_sin_servicio_guardado_se_coge_el_de_la_llamada(api_module):  # noqa: F811
    from backend import reserva

    estado = reserva.Estado()
    _pendiente(estado, "Corte senora")
    assert estado.servicio == "Corte senora"


def test_una_llamada_sin_servicio_no_borra_el_que_habia(api_module):  # noqa: F811
    """Si el modelo se deja el campo, lo que ya se sabia sigue valiendo."""
    from backend import reserva

    estado = reserva.Estado()
    estado.servicio = "Corte senora"
    estado.servicio_exacto = "Corte senora"
    reserva.anotar_resultado(
        estado, "crear_cita", {"fecha": "2026-09-03", "hora": "14:00", "nombre": "Ana"},
        {"ok": False, "pendiente_de_confirmacion": True},
    )
    assert estado.servicio == "Corte senora"
    assert estado.servicio_exacto == "Corte senora"


@pytest.mark.parametrize("guardado,pedido,otro", [
    ("Corte senora", "Acido lactico bio premium largo", True),
    ("Pack keratina premium medio", "Keratina premium medio", False),
    ("Keratina premium medio", "Pack keratina premium medio", False),
    ("Corte senora", "Corte senora", False),
    ("", "Corte senora", True),
    ("Corte senora", "", False),
])
def test_cuando_dos_nombres_son_el_mismo_servicio(api_module, guardado, pedido, otro):  # noqa: F811
    from backend import reserva

    assert reserva._es_otro_servicio(guardado, pedido) is otro


# ─── "¿Y esto cuanto tarda?" cuando "esto" es otra cosa ───────────────────

CATALOGO = [
    ("qat_corte", "Corte senora", "Cortes", 20),
    ("qat_kera", "Keratina premium medio", "Alisados", 225),
]


@pytest.fixture()
def salon(api_module, client):  # noqa: F811
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
            conexion.execute("DELETE FROM services WHERE cliente_id='demo' AND slug LIKE 'qat_%'")
            conexion.commit()
        with appstate.state_lock:
            appstate.intent_cache.clear()


class _Estado(object):
    def __init__(self, servicio):
        self.servicio_exacto = servicio
        self.servicio = servicio


def test_no_le_da_la_duracion_del_servicio_viejo(salon):
    """Con "Corte senora" pegado en el estado, a "quiero una queratina, ¿que
    tarda?" se le contestaba "son EXACTAMENTE 20 minutos". Una cifra falsa dicha
    con esa seguridad es peor que una inventada."""
    from backend import agent

    guia = agent._duracion_si_la_pregunta(
        salon, "Quiero una queratina que tarda", _Estado("Corte senora"))
    assert "20 minutos" not in guia, guia
    assert "buscar_servicio" in guia, "tiene que ir a mirarlo al catalogo"


def test_si_pregunta_por_lo_que_ya_tiene_elegido_si_contesta(salon):
    """La otra mitad: mandarla a buscar lo que ya esta decidido es dar vueltas."""
    from backend import agent

    guia = agent._duracion_si_la_pregunta(
        salon, "cuanto dura el corte?", _Estado("Corte senora"))
    assert "EXACTAMENTE 20 minutos" in guia


def test_una_pregunta_suelta_se_refiere_a_lo_que_hay_encima_de_la_mesa(salon):
    """"¿Que tarda?" sin nombrar nada es por el servicio elegido."""
    from backend import agent

    guia = agent._duracion_si_la_pregunta("demo", "que tarda?", _Estado("Corte senora"))
    assert "EXACTAMENTE 20 minutos" in guia


@pytest.mark.parametrize("dicho,esperado", [
    ("quiero una queratina", "keratina"),
    ("quiero una keratina", "keratina"),
])
def test_se_escriba_como_se_escriba_es_la_misma_familia(salon, dicho, esperado):
    """La clienta escribe QUERATINA y el catalogo dice KERATINA."""
    from backend import catalog_pick

    assert esperado in catalog_pick.familias_pedidas(salon, dicho)


def test_el_dia_y_la_hora_tambien_son_los_ultimos_dichos(api_module):  # noqa: F811
    """Conversacion real: pidio "el martes 2 a las 11:15" TRES veces y el resumen
    decia "martes 1 de septiembre, 10:00" -el primer dia que se habia consultado-.
    Al confirmar, ese hueco ya estaba cogido y la conversacion se fue al garete.
    """
    from backend import reserva

    estado = reserva.Estado()
    estado.fecha = "2026-09-01"      # el primer dia que se miro
    estado.hora = "10:00"
    reserva.anotar_resultado(
        estado, "crear_cita",
        {"servicio": "Mechas o balayage medio", "fecha": "2026-09-02",
         "hora": "11:15", "nombre": "Laura"},
        {"ok": False, "pendiente_de_confirmacion": True},
    )
    assert estado.fecha == "2026-09-02", "el resumen le ensenyaria otro dia"
    assert estado.hora == "11:15"


def test_si_la_llamada_no_trae_dia_se_conserva_el_que_habia(api_module):  # noqa: F811
    from backend import reserva

    estado = reserva.Estado()
    estado.fecha = "2026-09-01"
    estado.hora = "10:00"
    reserva.anotar_resultado(
        estado, "crear_cita", {"servicio": "Corte senora", "nombre": "Laura"},
        {"ok": False, "pendiente_de_confirmacion": True},
    )
    assert estado.fecha == "2026-09-01" and estado.hora == "10:00"


def test_el_hueco_ocupado_no_acaba_en_el_menu_principal(api_module):  # noqa: F811
    """"Ese hueco se acaba de ocupar, tengo 10:15, 11:00, 11:15" e inmediatamente
    despues el menu principal. Es mandarla a empezar de cero justo cuando se le
    acaban de dar alternativas buenas."""
    import inspect

    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._handle_whatsapp_message)
    trozo = fuente[fuente.index("if iid == \"confirm_yes\""):]
    trozo = trozo[:trozo.index("confirm_no")]
    assert "_wa_send_main_menu" not in trozo, (
        "vuelve a soltarle el menu despues de ofrecerle horas reales"
    )
