# -*- coding: utf-8 -*-
"""Las conversaciones malas se encuentran solas, sin que las cuente el cliente.

Los ocho fallos del 25 y 26 de agosto de 2026 se descubrieron todos igual: el
duenyo pegando capturas de WhatsApp. Los que nadie cuenta -la clienta a la que se
le dijo "a las 10:30 ya tengo una cita" siendo mentira- no se veian jamas: esa no
se queja, simplemente no viene.

Aqui se comprueban las dos formas de que esto no sirva para nada:

* que NO pille lo que ya sabemos que estaba mal (inutil), y
* que marque conversaciones BUENAS (ruido: el negocio deja de mirarlo).

Las senyales son funciones puras sobre una `Conversacion`, asi que casi todo esto
se prueba sin base de datos y sin red.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


def _conv(pares, **extra):
    """Una conversacion de mentira: [(quien, texto)] con quien = 'ella'|'ia'."""
    from backend import calidad

    return calidad.Conversacion(
        cliente_id=extra.pop("cliente_id", "demo"),
        session_id=extra.pop("session_id", "s1"),
        mensajes=[calidad.Mensaje(de_ella=(quien == "ella"), texto=texto)
                  for quien, texto in pares],
        **extra,
    )


# ─── Lo que tiene que pillar ───────────────────────────────────────────────

def test_pilla_que_se_repitio(api_module):  # noqa: F811
    from backend import calidad

    muro = ("Sin ver tu cabello no puedo decirte cual te recomendariamos. "
            "Si coges cita te asesoramos en persona.")
    conv = _conv([("ella", "cuanto cuesta?"), ("ia", muro),
                  ("ella", "dime un aproximado"), ("ia", muro)])
    senyales = [h.senyal for h in calidad.revisar(conv)]
    assert "repite_lo_mismo" in senyales


def test_pilla_el_resumen_que_no_acabo_en_cita(api_module):  # noqa: F811
    """Es donde mas se pierde: lo hizo todo bien y no cerro."""
    from backend import calidad

    conv = _conv([("ella", "quiero cita"),
                  ("ia", "Resumen de tu cita\\n\\nCorte señora\\n\\n¿Confirmamos la cita?")],
                 hubo_cita=False)
    hallazgos = calidad.revisar(conv)
    assert "resumen_sin_cita" in [h.senyal for h in hallazgos]
    assert any(h.gravedad == "alta" for h in hallazgos)


def test_pilla_el_precio_donde_no_se_dan(api_module):  # noqa: F811
    from backend import calidad

    conv = _conv([("ella", "cuanto vale?"), ("ia", "Son unos 45 € mas o menos")],
                 precios_ocultos=True)
    assert "dio_un_precio" in [h.senyal for h in calidad.revisar(conv)]


def test_pilla_el_un_momento_que_nunca_vuelve(api_module):  # noqa: F811
    """"Vamos a ver las horas. Un momento, por favor" -y ahi se quedo-."""
    from backend import calidad

    conv = _conv([("ella", "el viernes?"),
                  ("ia", "Vamos a ver las horas para el viernes. Un momento, por favor 😉")])
    assert "lo_anuncio_y_no_volvio" in [h.senyal for h in calidad.revisar(conv)]


def test_pilla_la_conversacion_larga_que_no_acaba_en_nada(api_module):  # noqa: F811
    from backend import calidad

    pares = []
    for i in range(9):
        pares.append(("ella", "mensaje %d" % i))
        pares.append(("ia", "respuesta distinta numero %d, con su texto propio" % i))
    assert "larga_y_sin_nada" in [h.senyal for h in calidad.revisar(_conv(pares))]


def test_pilla_que_dijo_cerrado_un_dia_que_se_abre(api_module, client):  # noqa: F811
    """El fallo real: dijo "manyana estamos cerrados" un jueves de 10:00 a 20:30."""
    from backend import calidad

    conv = _conv([("ella", "puede ser el 2026-08-27?"),
                  ("ia", "Cariño, mañana estamos cerrados 😔")],
                 dias_mencionados=["2026-08-27"])   # jueves: el demo abre
    assert "dijo_que_cerramos" in [h.senyal for h in calidad.revisar(conv)]


# ─── Lo que NO puede marcar (o se convierte en ruido) ──────────────────────

def test_una_conversacion_buena_no_se_marca(api_module):  # noqa: F811
    """Si marca 200 de 200, el negocio deja de mirarlo y no sirve de nada."""
    from backend import calidad

    conv = _conv([
        ("ella", "hola, quiero cita para un corte"),
        ("ia", "¡Hola cariño! ¿Para ti o para otra persona?"),
        ("ella", "para mi, corte de señora"),
        ("ia", "Perfecto. ¿Que dia te viene bien? Tengo mañana o el viernes"),
        ("ella", "mañana a las 10"),
        ("ia", "Resumen de tu cita\\n\\nCorte señora\\n\\n¿Confirmamos la cita?"),
        ("ella", "confirmo"),
        ("ia", "✅ Cita confirmada. Te esperamos 😉"),
    ], hubo_cita=True)
    assert calidad.revisar(conv) == []


def test_repetir_un_acuse_corto_no_cuenta(api_module):  # noqa: F811
    """Decir "perfecto" dos veces no molesta a nadie."""
    from backend import calidad

    conv = _conv([("ella", "vale"), ("ia", "Perfecto 😊"),
                  ("ella", "si"), ("ia", "Perfecto 😊")], hubo_cita=True)
    assert "repite_lo_mismo" not in [h.senyal for h in calidad.revisar(conv)]


def test_el_precio_no_se_marca_si_el_negocio_si_los_da(api_module):  # noqa: F811
    from backend import calidad

    conv = _conv([("ella", "cuanto vale?"), ("ia", "El corte son 25 €")],
                 precios_ocultos=False, hubo_cita=True)
    assert calidad.revisar(conv) == []


# ─── Que no se caiga ni pierda lo atendido ─────────────────────────────────

def test_una_senyal_rota_no_tumba_el_repaso(api_module, monkeypatch):  # noqa: F811
    """Un repaso que revienta no avisa de nada, que es peor que no tenerlo."""
    from backend import calidad

    def _revienta(_conv):
        raise RuntimeError("boom")

    rota = calidad.Senyal("rota", "alta", _revienta)
    monkeypatch.setattr(calidad, "SENYALES", [rota] + calidad.SENYALES[:2])
    conv = _conv([("ella", "hola"), ("ia", "Resumen\\n¿Confirmamos la cita?")])
    assert "resumen_sin_cita" in [h.senyal for h in calidad.revisar(conv)]


def test_repasar_dos_veces_no_borra_lo_ya_atendido(api_module, client):  # noqa: F811
    """El negocio marca una como vista; el repaso del dia siguiente no la revive."""
    from backend import calidad, db

    conv = _conv([("ella", "hola"), ("ia", "Resumen\\n¿Confirmamos la cita?")],
                 session_id="s_atendida")
    hallazgos = calidad.revisar(conv)
    try:
        calidad._guardar_revision("demo", conv, hallazgos)
        assert any(p["session_id"] == "s_atendida" for p in calidad.pendientes("demo"))

        assert calidad.marcar_atendida("demo", "s_atendida") is True
        assert not any(p["session_id"] == "s_atendida" for p in calidad.pendientes("demo"))

        calidad._guardar_revision("demo", conv, hallazgos)   # se repasa otra vez
        assert not any(p["session_id"] == "s_atendida" for p in calidad.pendientes("demo")), (
            "el repaso ha revivido una conversacion que ya habian mirado"
        )
    finally:
        with db._get_db_connection() as conexion:
            conexion.execute("DELETE FROM conversation_reviews WHERE session_id='s_atendida'")
            conexion.commit()


def test_lo_mas_grave_sale_primero(api_module, client):  # noqa: F811
    from backend import calidad, db

    grave = _conv([("ella", "x"), ("ia", "Resumen\\n¿Confirmamos la cita?")], session_id="s_alta")
    leve = _conv([("ella", "x"), ("ia", "Voy a mirar la agenda, un momento")], session_id="s_media")
    try:
        calidad._guardar_revision("demo", leve, calidad.revisar(leve))
        calidad._guardar_revision("demo", grave, calidad.revisar(grave))
        ids = [p["session_id"] for p in calidad.pendientes("demo")]
        assert ids.index("s_alta") < ids.index("s_media")
    finally:
        with db._get_db_connection() as conexion:
            conexion.execute("DELETE FROM conversation_reviews WHERE session_id IN ('s_alta','s_media')")
            conexion.commit()


def test_no_llama_al_modelo(api_module):  # noqa: F811
    """Un repaso que cueste dinero por conversacion no se puede dejar corriendo."""
    import inspect

    from backend import calidad

    fuente = inspect.getsource(calidad)
    for prohibido in ("OpenAI", "chat.completions", "openai"):
        assert prohibido not in fuente, (
            "la vigilancia ha empezado a llamar al modelo (%r): eso cuesta dinero "
            "en cada conversacion revisada" % prohibido
        )
