# -*- coding: utf-8 -*-
"""Una cita no puede comerse varios servicios, ni bajar de gama sin preguntar.

INCIDENTE REAL que origina este fichero (26-ago-2026, salon piloto). La clienta
fue sumando cosas por WhatsApp:

    "Corte de senora"
    "Pero quiero cortarme y secarme tambien"
    "He pensado que tambien quisiera hacer el lumen elumen, cortar y secar"
    "He pensado que quiero un alisado"

La cita creada fue `corte_senora`, de 14:00 a 14:20. VEINTE MINUTOS para cuatro
servicios. Los otros tres se perdieron sin que nadie se enterara, y el negocio
se habria encontrado a una clienta que viene a estar tres horas en un hueco de
veinte minutos.

Y de la misma familia, encontrado al arreglar el anterior: a quien pide un
tratamiento por su nombre largo ("acido lactico bio premium", de 30 a 180
minutos segun el largo) se le asignaba el de nombre corto, de QUINCE, sin
preguntarle nada.

Los dos son el mismo fallo: apartar MENOS tiempo del que hace falta, en
silencio. El modelo no lo ve como un error -para el la cita se creo bien-, asi
que lo impide el codigo.
"""
from __future__ import annotations

import uuid

import pytest

CLIENTE = "demo"

# Un catalogo con la forma del real: servicios sueltos de familias distintas, un
# pack que combina dos, y un tratamiento con variantes por largo mas su version
# corta de otro nombre.
CATALOGO = [
    # (nombre, categoria, minutos)
    ("Corte senora", "Cortes", 20),
    ("Secado al aire medio", "Peinados", 10),
    ("Elumen corto-medio", "Trabajos de color", 15),
    ("Pack color raiz y elumen medio", "Packs", 120),
    ("Hidratacion bio premium-medio", "Tratamientos", 30),
    ("Hidratacion bio premium-largo", "Tratamientos", 180),
    ("Hidratacion chico o corto", "Tratamientos", 15),
]


@pytest.fixture(scope="module")
def salon(api_module):
    """Deja el catalogo de prueba montado y los caches limpios."""
    from backend import appstate, db, timeutils

    ahora = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        for nombre, categoria, minutos in CATALOGO:
            connection.execute(
                """
                INSERT OR REPLACE INTO services
                    (cliente_id, slug, name, duration_minutes, price_cents,
                     description, is_active, sort_order, category, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1000, '', 1, 0, ?, ?, ?)
                """,
                (CLIENTE, "svc_" + uuid.uuid5(uuid.NAMESPACE_DNS, nombre).hex[:10],
                 nombre, minutos, categoria, ahora, ahora),
            )
        connection.commit()
    # Las familias del tenant se cachean 10 minutos: sin vaciarlo, el catalogo
    # que acabamos de meter no existiria para la deteccion.
    with appstate.state_lock:
        appstate.intent_cache.clear()
    yield
    with appstate.state_lock:
        appstate.intent_cache.clear()


def _mensajes(*textos):
    return [{"role": "user", "content": t} for t in textos]


# ─── Lo que paso de verdad ────────────────────────────────────────────────

def test_pedir_cuatro_cosas_no_reserva_una_de_veinte_minutos(salon, api_module):
    from backend import agent

    mensajes = _mensajes(
        "Corte de senora",
        "Pero quiero cortarme y secarme tambien",
        "He pensado que tambien quisiera hacer el elumen",
        "He pensado que quiero un alisado",
    )
    freno = agent._freno_de_varios_servicios(
        CLIENTE, mensajes, {"servicio": "Corte senora"}
    )

    assert freno is not None, "la cita de 20 minutos se habria creado otra vez"
    assert freno["ok"] is False
    # Y le dice al modelo QUE hacer, no solo que no.
    assert freno["que_hacer"]


def test_una_sola_cosa_se_reserva_como_siempre(salon, api_module):
    """El freno no puede estorbar a quien pide UN servicio: seria peor el remedio."""
    from backend import agent

    for conversacion in (
        ["Quiero un corte de senora"],
        ["Quiero un corte", "lo tengo largo"],
        ["Hola", "que precio tiene el elumen?"],
    ):
        freno = agent._freno_de_varios_servicios(
            CLIENTE, _mensajes(*conversacion), {"servicio": "Corte senora"}
        )
        assert freno is None, "freno de mas en: %r" % conversacion


def test_describir_el_pelo_no_cuenta_como_pedir_un_corte(salon, api_module):
    """"Lo tengo corto" es el LARGO, no un servicio. Sin esto el freno saltaba
    cada vez que una clienta describia su pelo."""
    from backend import agent

    freno = agent._freno_de_varios_servicios(
        CLIENTE,
        _mensajes("Quiero el elumen", "lo tengo corto, por los hombros"),
        {"servicio": "Elumen corto-medio"},
    )
    assert freno is None


def test_si_hay_un_pack_que_lo_cubre_se_ofrece_en_vez_de_negarse(salon, api_module):
    from backend import agent

    freno = agent._freno_de_varios_servicios(
        CLIENTE,
        _mensajes("Quiero color en la raiz", "y tambien el elumen"),
        {"servicio": "Elumen corto-medio"},
    )

    assert freno is not None
    opciones = freno.get("opciones_que_lo_cubren") or []
    assert opciones, "tiene un pack que lo cubre y no lo ofrecio"
    assert any("Pack color raiz y elumen" in o["servicio"] for o in opciones)
    # Con su duracion REAL, que es el dato que evita el hueco corto.
    assert any(o["duracion_minutos"] == 120 for o in opciones)


def test_el_servicio_elegido_si_cubre_todo_no_se_frena(salon, api_module):
    """Si ya va a reservar el pack correcto, el freno tiene que apartarse."""
    from backend import agent

    freno = agent._freno_de_varios_servicios(
        CLIENTE,
        _mensajes("Quiero color en la raiz", "y tambien el elumen"),
        {"servicio": "Pack color raiz y elumen medio"},
    )
    assert freno is None


# ─── Bajar de gama sin preguntar ──────────────────────────────────────────

@pytest.fixture()
def sin_modelo(monkeypatch):
    """Lo que el extractor sacaria del mensaje, fijado a mano.

    Se clava el caso REAL: el extractor devolvio la tecnica en su forma CORTA
    ("acido lactico") aunque ella habia dicho el nombre largo. Ahi nacia el
    fallo, y sin fijarlo el test dependeria del modelo y de la red.
    """
    from backend import intents

    def _fijo(cliente_id, descripcion, **kwargs):
        return {
            "familia": "tratamientos", "tecnica": "hidratacion", "talla": "",
            "para_quien": "", "edad": None, "texto": descripcion,
        }

    monkeypatch.setattr(intents, "extraer_datos_servicio", _fijo)


def test_no_baja_al_servicio_corto_lo_que_pidio_por_su_nombre_largo(salon, sin_modelo):
    from backend import agent

    resultado = agent._tool_buscar_servicio(
        CLIENTE, {"descripcion": "quiero la hidratacion bio premium"}
    )

    # No puede resolverlo solo: no sabe el largo y va de 30 a 180 minutos.
    assert resultado.get("servicio") != "Hidratacion chico o corto", (
        "le asigno el de 15 minutos habiendo pedido el bio premium"
    )
    assert resultado.get("falta") == "talla"


def test_no_da_una_cifra_de_duracion_cuando_depende_del_largo(salon, sin_modelo):
    """La queja literal del salon: "tendria que preguntar cual es tu largo"."""
    from backend import agent

    resultado = agent._tool_buscar_servicio(
        CLIENTE, {"descripcion": "quiero la hidratacion bio premium"}
    )

    assert resultado.get("duracion_varia_segun_la_opcion") is True
    assert resultado["duracion_minutos_max"] >= 180
    # Y se le prohibe expresamente soltar un numero suelto.
    assert "NO le des una cifra sola" in resultado.get("nota", "")


def test_no_inventa_la_duracion_de_algo_que_no_tiene(salon, api_module, monkeypatch):
    """Una tecnica que este salon no hace no se sustituye por su vecina de estante.

    El extractor se fija a mano A PROPOSITO. Tal y como estaba, este test llamaba
    al modelo de verdad: cada tirada devolvia algo distinto -a veces con tecnica, a
    veces sin ella-, asi que pasaba o fallaba a suertes y ademas gastaba saldo en
    cada ejecucion de la suite. Un test que no da siempre el mismo resultado no
    prueba nada.
    """
    from backend import agent, intents

    monkeypatch.setattr(intents, "extraer_datos_servicio", lambda *a, **k: {
        "familia": "tratamiento", "tecnica": "plasma capilar", "talla": "",
        "para_quien": "", "edad": None,
        "texto": "un tratamiento de plasma capilar con laser",
    })
    resultado = agent._tool_buscar_servicio(
        CLIENTE, {"descripcion": "un tratamiento de plasma capilar con laser"}
    )

    assert resultado.get("ok") is False
    assert "no_inventes" in resultado
    # Y viene el hueco para ensenyarle lo que SI hay (vacio si no se parece a nada,
    # que es el caso aqui: en este catalogo no hay nada cercano al plasma capilar).
    assert "servicios_parecidos" in resultado


# ─── La duracion se lee del catalogo, no se estima ────────────────────────

class _EstadoFalso(object):
    """Lo minimo que mira el codigo: que servicio hay elegido ahora mismo."""

    def __init__(self, servicio_exacto="", servicio=""):
        self.servicio_exacto = servicio_exacto
        self.servicio = servicio


def test_reconoce_las_formas_reales_de_preguntar_cuanto_tarda():
    """Los mensajes son los de la conversacion que fallo, tal cual se escribieron."""
    from backend import agent

    for mensaje in [
        "Que suele tardar?",
        "Tengo el pelo por los hombros, me puedes decir lo que tarda un Alisado por favor?",
        "Quiero una queratina que tarda",
        "Y si me quiero hacer el acido lactico bio premium que tardo?",
        "cuanto dura el pack?",
    ]:
        assert agent._pregunta_cuanto_dura(mensaje), mensaje

    for mensaje in ["quiero un corte", "cuanto cuesta?", "el jueves me viene bien",
                    "me lo puedo llevar a casa?"]:
        assert not agent._pregunta_cuanto_dura(mensaje), mensaje


def test_da_los_minutos_exactos_del_servicio_que_se_esta_hablando(salon, api_module):
    from backend import agent

    aviso = agent._duracion_si_la_pregunta(
        CLIENTE, "y eso que suele tardar?", _EstadoFalso(servicio_exacto="Corte senora")
    )

    assert "20 minutos" in aviso
    assert "No lo redondees" in aviso


def test_si_lo_que_hay_elegido_es_un_pack_da_la_duracion_DEL_PACK(salon, api_module):
    """Un pack no dura lo que su trozo suelto.

    "Pack color raiz y elumen medio" son 120 minutos; el "Elumen corto-medio"
    suelto son 15. Si el negocio trabaja por packs y se contesta con los 15, se
    aparta un hueco ocho veces mas corto que el trabajo real.
    """
    from backend import agent

    aviso = agent._duracion_si_la_pregunta(
        CLIENTE, "cuanto tarda?",
        _EstadoFalso(servicio_exacto="Pack color raiz y elumen medio"),
    )

    assert "120 minutos" in aviso
    assert "15 minutos" not in aviso


def test_la_duracion_que_dice_es_la_que_aparta_la_agenda(salon, api_module):
    """La garantia de verdad: el numero sale del MISMO resolutor que reserva.

    Si se contestara desde una copia de la logica, un dia divergirian y la
    clienta tendria un hueco que no le da para su servicio.
    """
    from backend import agenda, agent

    for nombre, _categoria, minutos in CATALOGO:
        assert agent._duracion_del_catalogo(CLIENTE, nombre) == \
            agenda._service_duration_minutes(CLIENTE, nombre) == minutos, nombre


def test_sin_servicio_elegido_obliga_a_mirar_el_catalogo(salon, api_module):
    from backend import agent

    aviso = agent._duracion_si_la_pregunta(CLIENTE, "que suele tardar?", _EstadoFalso())

    assert "buscar_servicio" in aviso
    assert "NUNCA una cifra a ojo" in aviso


def test_sin_duracion_configurada_no_se_inventa_una_cifra(salon, api_module):
    from backend import agent, db, timeutils

    ahora = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO services
                (cliente_id, slug, name, duration_minutes, price_cents, description,
                 is_active, sort_order, category, created_at, updated_at)
            VALUES (?, 'svc_sin_duracion', 'Ritual sin tiempo', 0, 1000, '', 1, 0,
                    'Tratamientos', ?, ?)
            """,
            (CLIENTE, ahora, ahora),
        )
        connection.commit()

    aviso = agent._duracion_si_la_pregunta(
        CLIENTE, "cuanto tarda?", _EstadoFalso(servicio_exacto="Ritual sin tiempo")
    )

    assert "no tiene duracion configurada" in aviso
    assert "NO te inventes" in aviso


def test_no_dice_nada_si_no_le_han_preguntado_por_el_tiempo(salon, api_module):
    """No puede colarse en cada turno: solo cuando de verdad lo preguntan."""
    from backend import agent

    assert agent._duracion_si_la_pregunta(
        CLIENTE, "quiero pedir cita para un corte", _EstadoFalso(servicio_exacto="Corte senora")
    ) == ""


def test_frenar_la_cita_no_tira_lo_que_ella_ya_ha_dado(salon, api_module):
    """La cita no se crea -y bien-, pero su nombre y su hora siguen valiendo.

    Conversacion real: la clienta comparo dos alisados, y al dar su nombre el freno
    rechazo la llamada. Con ella se fueron el nombre, el dia y la hora que traia
    dentro, asi que la conversacion tenia que empezar de cero justo en el ultimo
    paso. Ahi se fue.

    Rechazar la reserva y perder los datos son dos cosas distintas.
    """
    from backend import reserva

    estado = reserva.Estado()
    reserva.anotar_resultado(
        estado, "crear_cita",
        {"servicio": "Pack keratina premium medio", "fecha": "2026-09-08",
         "hora": "14:00", "nombre": "Alicia Rincon Espinosa"},
        {"ok": False, "conserva_los_datos": True,
         "error": "Ha pedido varias cosas y no hay un servicio que las cubra juntas."},
    )
    assert estado.nombre == "Alicia Rincon Espinosa"
    assert estado.fecha == "2026-09-08"
    assert estado.hora == "14:00"
    # Pero NO se da por lista para confirmar: no hay nada que confirmar.
    assert estado.esperando_confirmacion is False


def test_un_rechazo_normal_sigue_sin_tocar_el_estado(salon, api_module):
    """Solo se conservan los datos cuando quien rechaza dice que son buenos."""
    from backend import reserva

    estado = reserva.Estado()
    reserva.anotar_resultado(
        estado, "crear_cita", {"nombre": "Inventado", "hora": "23:00"},
        {"ok": False, "error": "Ese horario ya no esta disponible."},
    )
    assert estado.nombre == "" and estado.hora == ""


def test_un_rechazo_no_pisa_lo_que_ya_se_sabia(salon, api_module):
    """Lo que ella dijo antes manda sobre lo que traiga una llamada rechazada."""
    from backend import reserva

    estado = reserva.Estado()
    estado.nombre = "Laura"
    reserva.anotar_resultado(
        estado, "crear_cita", {"nombre": "Otra cosa", "hora": "14:00"},
        {"ok": False, "conserva_los_datos": True, "error": "..."},
    )
    assert estado.nombre == "Laura"
    assert estado.hora == "14:00"
