# -*- coding: utf-8 -*-
"""Que la IA entienda qué le piden, y que el negocio decida qué hacer.

EL PROBLEMA QUE RESUELVE
------------------------
La intención se adivinaba con expresiones regulares. Medido: de 19 formas
naturales de pedir cita se reconocían DOS. "me pones una cita?", "resérvame el
jueves" o "quiero pedir hora" no abrían el formulario, y cada variante nueva era
un parche más.

Ahora hay tres piezas:

* `intents.atajo_local`  resuelve gratis lo evidente (sin gastar una llamada).
* `intents.classify`     pregunta al modelo lo que el atajo no tiene claro, y de
                         paso reconoce si le están haciendo una de las preguntas
                         que el negocio ya tiene respondidas.
* `rules`                lo que el negocio ha dicho que se haga con cada intención.

LO QUE NUNCA PUEDE PASAR
------------------------
Que esto deje a un cliente sin respuesta. Si el modelo falla, tarda, o el negocio
no lo ha activado, se devuelve `None` y el chat sigue exactamente como antes.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


# ─── Atajos: lo evidente, sin gastar una llamada ───────────────────────────

@pytest.mark.parametrize("mensaje,esperada", [
    ("quiero cancelar mi cita", "cancelar"),
    ("cancelar mi cita", "cancelar"),
    ("quiero cambiar mi cita", "reprogramar"),
    ("gracias", "agradecimiento"),
    ("muchas gracias", "agradecimiento"),
    ("agendar cita", "reservar"),
    ("pedir cita", "reservar"),
])
def test_los_atajos_resuelven_lo_obvio(mensaje, esperada):
    from backend import intents, rules  # noqa: F401

    assert intents.atajo_local(mensaje) == esperada


def test_gracias_con_pregunta_detras_no_es_solo_agradecimiento():
    """"gracias, ¿a qué hora abrís?" pide un horario, no solo cortesía."""
    from backend import intents, rules  # noqa: F401

    assert intents.atajo_local("gracias, ¿a que hora abris?") != "agradecimiento"


def test_sin_atajo_devuelve_vacio():
    from backend import intents, rules  # noqa: F401

    assert intents.atajo_local("me pones una cita?") == ""
    assert intents.atajo_local("") == ""


# ─── Nunca deja al cliente sin respuesta ───────────────────────────────────

def test_sin_activar_no_clasifica(api_module, client, monkeypatch):  # noqa: F811
    """Opt-in: un negocio que no lo active se comporta igual que siempre."""
    from backend import intents

    monkeypatch.setattr(intents, "enabled_for", lambda *a, **k: False)
    assert intents.classify("demo", "me pones una cita?") is None


def test_si_el_modelo_falla_el_chat_sigue(api_module, client, monkeypatch):  # noqa: F811
    """Lo que no puede pasar es que entender rompa el responder."""
    from backend import intents

    monkeypatch.setattr(intents, "enabled_for", lambda *a, **k: True)
    monkeypatch.setattr(intents.settings, "OPENAI_API_KEY", "sk-test")

    class ClienteRoto:
        def __init__(self, *a, **k):
            raise RuntimeError("OpenAI caido")

    import sys
    import types

    modulo = types.ModuleType("openai")
    modulo.OpenAI = ClienteRoto
    monkeypatch.setitem(sys.modules, "openai", modulo)

    assert intents.classify("demo", "me pones una cita el jueves?") is None


# ─── Reglas del negocio ────────────────────────────────────────────────────

@pytest.fixture
def sin_reglas(api_module, client):  # noqa: F811
    """Pide `client` a proposito: la base de datos se inicializa al arrancar la
    app, no al importar el modulo."""
    from backend import db

    with db._get_db_connection() as conexion:
        conexion.execute("DELETE FROM business_rules WHERE cliente_id = 'demo'")
        conexion.commit()
    yield
    with db._get_db_connection() as conexion:
        conexion.execute("DELETE FROM business_rules WHERE cliente_id = 'demo'")
        conexion.commit()


def test_una_regla_casa_su_intencion(sin_reglas):
    from backend import intents, rules  # noqa: F401

    rules.guardar("demo", nombre="Reservar", intenciones=["reservar"], accion="formulario")
    regla = rules.match("demo", {"intencion": "reservar", "familia": ""})
    assert regla and regla["accion"] == "formulario"


def test_una_regla_no_casa_otra_intencion(sin_reglas):
    from backend import intents, rules  # noqa: F401

    rules.guardar("demo", nombre="Reservar", intenciones=["reservar"], accion="formulario")
    assert rules.match("demo", {"intencion": "cancelar", "familia": ""}) is None


def test_la_regla_con_familia_solo_vale_para_esa(sin_reglas):
    """El caso real del salón: pedir foto SOLO si es presupuesto de alisado."""
    from backend import intents, rules  # noqa: F401

    rules.guardar("demo", nombre="Foto alisado", intenciones=["presupuesto"],
                  familias=["alisado"], accion="pedir_foto",
                  texto="Mándanos una foto por detrás.", prioridad=10)
    rules.guardar("demo", nombre="Precio general", intenciones=["presupuesto", "precio"],
                  accion="ofrecer_cita", texto="Te vemos y te decimos.", prioridad=50)

    foto = rules.match("demo", {"intencion": "presupuesto", "familia": "alisado"})
    assert foto["accion"] == "pedir_foto"

    general = rules.match("demo", {"intencion": "presupuesto", "familia": "mechas"})
    assert general["accion"] == "ofrecer_cita", "sin familia, gana la general"


def test_manda_la_prioridad(sin_reglas):
    from backend import intents, rules  # noqa: F401

    rules.guardar("demo", nombre="Segunda", intenciones=["reservar"], accion="responder",
                  texto="B", prioridad=90)
    rules.guardar("demo", nombre="Primera", intenciones=["reservar"], accion="responder",
                  texto="A", prioridad=10)
    assert rules.match("demo", {"intencion": "reservar", "familia": ""})["texto"] == "A"


def test_una_regla_desactivada_no_responde(sin_reglas):
    from backend import intents, rules  # noqa: F401

    rules.guardar("demo", nombre="Off", intenciones=["reservar"], accion="responder",
                  texto="no", activa=False)
    assert rules.match("demo", {"intencion": "reservar", "familia": ""}) is None


def test_no_se_admite_una_accion_inventada(sin_reglas):
    from backend import intents, rules  # noqa: F401

    with pytest.raises(ValueError):
        rules.guardar("demo", nombre="Mala", intenciones=["reservar"], accion="hacer_magia")


def test_editar_y_borrar_una_regla(sin_reglas):
    from backend import intents, rules  # noqa: F401

    creada = rules.guardar("demo", nombre="Una", intenciones=["precio"], accion="responder",
                           texto="primero")
    rules.guardar("demo", regla_id=creada["id"], nombre="Una", intenciones=["precio"],
                  accion="responder", texto="segundo")
    assert rules.match("demo", {"intencion": "precio", "familia": ""})["texto"] == "segundo"
    assert rules.borrar("demo", creada["id"]) is True
    assert rules.match("demo", {"intencion": "precio", "familia": ""}) is None


def test_las_reglas_son_de_cada_negocio(sin_reglas):
    """Multi-tenant: lo que configure un salón no puede afectar a otro."""
    from backend import intents, rules  # noqa: F401

    rules.guardar("demo", nombre="Suya", intenciones=["reservar"], accion="formulario")
    assert rules.match("otro_negocio", {"intencion": "reservar", "familia": ""}) is None


def test_sin_servicio_no_gana_la_regla_de_ese_servicio(sin_reglas):
    """Bug real: "" casaba con cualquier familia (`"" in "alisado"` es True), asi
    que un "¿cuanto cuesta?" a secas pedia la foto del alisado."""
    from backend import intents, rules  # noqa: F401

    rules.guardar("demo", nombre="Foto alisado", intenciones=["presupuesto"],
                  familias=["alisado"], accion="pedir_foto", prioridad=10)
    assert rules.match("demo", {"intencion": "presupuesto", "familia": ""}) is None


# ─── Cautelas: cuando NO hay que hacer caso al modelo ──────────────────────

def test_una_tecla_del_menu_no_se_clasifica(api_module, client, monkeypatch):  # noqa: F811
    """Un "1" es una tecla, no una frase: ni se entiende ni se paga por ella."""
    from backend import intents

    monkeypatch.setattr(intents, "enabled_for", lambda *a, **k: True)

    def _no_deberia_llamarse(*a, **k):
        raise AssertionError("se ha llamado al modelo para clasificar un digito")

    monkeypatch.setattr(intents, "familias_del_tenant", _no_deberia_llamarse)
    assert intents.classify("demo", "1") is None
    assert intents.classify("demo", " 3 ") is None


def test_una_corazonada_floja_se_descarta(api_module, client, monkeypatch):  # noqa: F811
    """Abrirle el formulario a quien solo preguntaba una direccion es peor que callar."""
    from backend import intents

    monkeypatch.setattr(intents, "enabled_for", lambda *a, **k: True)
    monkeypatch.setattr(intents, "familias_del_tenant", lambda cid: [])
    monkeypatch.setattr(intents, "preguntas_del_tenant", lambda cid, limite=40: [])
    monkeypatch.setattr(intents.settings, "OPENAI_API_KEY", "sk-test")

    def _responde(confianza):
        import sys
        import types

        class _Mensaje:
            content = '{"intencion": "reservar", "familia": "", "pregunta": 0,' \
                      ' "confianza": %s}' % confianza

        class _Choice:
            message = _Mensaje()

        class _Respuesta:
            choices = [_Choice()]

        class _Completions:
            def create(self, **kwargs):
                return _Respuesta()

        class _Chat:
            completions = _Completions()

        class _Cliente:
            def __init__(self, *a, **k):
                self.chat = _Chat()

        modulo = types.ModuleType("openai")
        modulo.OpenAI = _Cliente
        monkeypatch.setitem(sys.modules, "openai", modulo)

    _responde(0.2)
    assert intents.classify("demo", "mi prima vino ayer") is None
    _responde(0.9)
    seguro = intents.classify("demo", "me pones algo el jueves")
    assert seguro and seguro["intencion"] == "reservar"
