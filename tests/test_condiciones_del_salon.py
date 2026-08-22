# -*- coding: utf-8 -*-
"""Las condiciones que ha pedido el salon, uña por uña.

Son las que Alicia fue mandando por WhatsApp entre el 19 y el 21 de agosto de
2026. Se comprueban de forma DETERMINISTA -contra la configuracion y las reglas,
no contra lo que conteste el modelo ese dia- porque son el contrato con la
clienta: si una deja de cumplirse hay que enterarse aqui, no en su salon.

Las condiciones que dependen de como redacte el modelo (que sea calido, que
recomiende) no se prueban aqui: se prueban conversando, en
`scripts/qa_alicia.py`.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401

TELEFONO = "625 120 100"


@pytest.fixture
def salon(api_module, client):
    """El tenant con las reglas y el tono del salon, como los deja su script."""
    import importlib.util
    import os
    import sys

    from backend import clients, db, rules

    with db._get_db_connection() as conexion:
        conexion.execute("DELETE FROM business_rules WHERE cliente_id='demo'")
        conexion.commit()

    ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "scripts", "reglas_alicia.py")
    spec = importlib.util.spec_from_file_location("reglas_alicia", ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["reglas_alicia"] = modulo
    spec.loader.exec_module(modulo)

    for datos in modulo.REGLAS:
        rules.guardar(
            "demo", nombre=datos["nombre"], intenciones=datos["intenciones"],
            familias=datos.get("familias", []), accion=datos["accion"],
            texto=datos["texto"], prioridad=datos["prioridad"], activa=True,
        )

    config = clients._get_client_config("demo")
    previo_tono = config.get("tono")
    previo_contacto = dict(config.get("contacto") or {})
    config["tono"] = {
        "estilo": "cercano", "emojis": "muchos", "tratamiento": "tu",
        "notas": (
            "Dirigete a quien te escribe como 'cariño' ('hola cariño, muy buenas'): "
            "vale igual para mujer y para hombre. Tambien puedes usar 'guapa' o "
            "'preciosa' cuando sepas que es una mujer. "
            "Cuando te despidas al cerrar la conversacion, termina siempre con estos "
            "tres emoticonos juntos: 😉🤗😘"
        ),
    }
    config.setdefault("contacto", {})["telefono"] = TELEFONO
    yield modulo
    with db._get_db_connection() as conexion:
        conexion.execute("DELETE FROM business_rules WHERE cliente_id='demo'")
        conexion.commit()
    if previo_tono is None:
        config.pop("tono", None)
    else:
        config["tono"] = previo_tono
    config["contacto"] = previo_contacto


# ─── Tono ──────────────────────────────────────────────────────────────────

def test_se_dirige_a_la_clienta_como_carino(salon, api_module):  # noqa: F811
    """"que utilice la IA la palabra cariño, asi nos vale para mujer y hombre"."""
    from backend import clients, textnorm

    bloque = textnorm._tono_prompt_block(clients._get_client_config("demo"))
    assert "cariño" in bloque
    assert "mujer y para hombre" in bloque


def test_se_despide_con_sus_tres_emoticonos(salon, api_module):  # noqa: F811
    """"yo siempre me despido mandando estos tres emoticonos 😉🤗😘"."""
    from backend import clients, textnorm

    bloque = textnorm._tono_prompt_block(clients._get_client_config("demo"))
    assert "😉🤗😘" in bloque


def test_gracias_se_contesta_gracias_a_ti(salon, api_module):  # noqa: F811
    """"siempre que la clienta de las gracias quiero que le conteste Gracias a ti"."""
    from backend import chat

    respuesta = chat._con_gracias_a_ti("muchas gracias!", "Abrimos de 10 a 20.")
    assert respuesta.startswith("¡Gracias a ti!")


def test_el_tono_llega_a_los_tres_canales(salon, api_module):  # noqa: F811
    """Chat, WhatsApp y telefono salen de la MISMA fuente."""
    import inspect

    from backend import rag, voice

    assert "_tono_prompt_block" in inspect.getsource(rag._build_system_prompt)
    assert "_tono_prompt_block" in inspect.getsource(voice._voice_build_instructions)


# ─── Precios ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("familia", [
    "mechas", "balayage", "balay", "jazz", "grey", "landing", "color",
    "cambio de color", "tinte", "decoloracion",
])
def test_no_da_precio_de_los_trabajos_tecnicos(salon, api_module, familia):  # noqa: F811
    """"para precios de mechas, balay, jazz, Grey, Landing, cambios de color la IA
    no tiene que dar los precios"."""
    from backend import rules

    regla = rules.match("demo", {"intencion": "precio", "familia": familia})
    assert regla is not None, "sin regla para %r: daria el precio" % familia
    assert regla["accion"] == "ofrecer_cita"


def test_ofrece_la_cita_de_diagnostico_de_15_minutos(salon, api_module):  # noqa: F811
    """"que coja una cita de 15 minutos, diagnostico y presupuesto sin compromiso
    y sin coste"."""
    from backend import rules

    regla = rules.match("demo", {"intencion": "presupuesto", "familia": "mechas"})
    texto = regla["texto"].lower()
    assert "15 minutos" in texto
    assert "sin compromiso" in texto
    assert "sin ningún coste" in texto or "sin coste" in texto


def test_los_servicios_con_precio_cerrado_siguen_teniendolo(salon, api_module):  # noqa: F811
    """La regla NO puede tapar el catalogo: un corte tiene precio y se dice."""
    from backend import rules

    for familia in ("corte", "peinado", "recogido", "maquillaje"):
        assert rules.match("demo", {"intencion": "precio", "familia": familia}) is None, (
            "la regla de precios esta tapando %r" % familia
        )


# ─── Alisados ──────────────────────────────────────────────────────────────

def test_presupuesto_de_alisado_pide_foto_por_detras(salon, api_module):  # noqa: F811
    """"solo tiene que pedir foto cuando quieran cita para Alisado pero quieran
    presupuesto: se le pide la foto por detras"."""
    from backend import rules

    regla = rules.match("demo", {"intencion": "presupuesto", "familia": "alisado"})
    assert regla is not None
    assert regla["accion"] == "pedir_foto"
    texto = regla["texto"].lower()
    assert "por detrás" in texto or "por detras" in texto


def test_y_dice_que_le_contestaran_ellas(salon, api_module):  # noqa: F811
    """"en breve nos pondremos en contacto para darle el presupuesto"."""
    from backend import rules

    texto = rules.match("demo", {"intencion": "presupuesto", "familia": "alisado"})["texto"]
    assert "en contacto" in texto.lower()


def test_para_coger_cita_de_alisado_no_se_pide_foto(salon, api_module):  # noqa: F811
    """"Los alisados, si quieren coger cita directamente, no hace falta que manden
    foto: solo que digan como lo tienen de largo"."""
    from backend import rules

    assert rules.match("demo", {"intencion": "reservar", "familia": "alisado"}) is None, (
        "le esta pidiendo una foto a quien solo quiere cita"
    )


def test_el_largo_del_pelo_es_lo_unico_que_se_pregunta(salon, api_module):  # noqa: F811
    """"solo que digan como lo tiene de largo y la IA coja la cita con los tiempos
    que yo ya le he marcado"."""
    from backend import catalog_pick

    assert catalog_pick.talla_de("lo tengo por los hombros") == "medio"
    assert catalog_pick.talla_de("muy largo") == "extra largo"


# ─── Extensiones ───────────────────────────────────────────────────────────

def test_extensiones_manda_a_hablar_con_ellas(salon, api_module):  # noqa: F811
    """"la IA le tiene que decir que tiene que hablar con nosotras, que lo ideal es
    un diagnostico, y le puede coger cita para diagnostico"."""
    from backend import rules

    for intencion in ("precio", "presupuesto", "info"):
        regla = rules.match("demo", {"intencion": intencion, "familia": "extensiones"})
        assert regla is not None, "sin regla para %r en extensiones" % intencion
        texto = regla["texto"].lower()
        assert "diagnóstico" in texto or "diagnostico" in texto
        assert "presupuesto" in texto


# ─── La agenda ─────────────────────────────────────────────────────────────

def test_los_ratos_de_espera_quedan_libres(salon, api_module):  # noqa: F811
    """"hay un pack de mechas de seis o siete horas, pero entremedias hay huecos
    que tienen que quedar libres para coger cita a otras clientas"."""
    from backend import agenda

    tramos = '[{"activo": 60, "espera": 90}, {"activo": 30, "espera": 0}]'
    trabajo = agenda._tramos_de_trabajo(tramos, 10 * 60, 180)
    ocupado = sum(b - a for a, b in trabajo)
    assert ocupado == 90, "la profesional deberia estar ocupada 90 de los 180 minutos"
    assert (11 * 60, 12 * 60 + 30) not in trabajo, "el rato de espera no puede estar ocupado"


# ─── Antes de perder la cita, que llamen ───────────────────────────────────

def test_se_ofrece_llamar_con_su_texto(salon, api_module):  # noqa: F811
    """"puedes llamarnos al salon. En ocasiones podemos revisar personalmente la
    agenda e intentar encontrar alguna alternativa"."""
    from backend import clients

    config = clients._get_client_config("demo")
    config["booking"]["rescate_texto"] = (
        "Si ninguna de estas opciones te encaja, puedes llamarnos al {telefono} 😊. "
        "En ocasiones podemos revisar personalmente la agenda e intentar encontrar "
        "alguna alternativa. Estaremos encantadas de ayudarte."
    )
    try:
        linea = clients.call_us_line("demo")
        assert TELEFONO in linea
        assert "revisar personalmente la agenda" in linea
    finally:
        config["booking"].pop("rescate_texto", None)


def test_no_se_ofrece_llamar_todo_el_rato(salon, api_module):  # noqa: F811
    """"no quiero que se ofrezca llamar constantemente, solo cuando la conversacion
    puede terminar sin cita"."""
    import inspect

    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._wa_atender_duda_sin_perder_el_paso)
    assert "intentos_fallidos >= 2" in fuente, (
        "tiene que esperar al segundo intento fallido, no ofrecerlo al primero"
    )
