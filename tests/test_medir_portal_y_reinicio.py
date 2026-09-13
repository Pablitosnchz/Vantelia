# -*- coding: utf-8 -*-
"""El juez del instrumento de cambios del portal y reinicios mira la agenda correcta.

POR QUE EXISTE
--------------
`scripts/medir_portal_y_reinicio.py` mide con el modelo real qué pasa si el negocio
cambia algo desde el portal a mitad de conversación, o si el proceso se reinicia
con una reserva a medias (13-sep-2026, puertas del informe de aceptación que
estaban «NO MEDIDAS con modelo»). Un juez que diera por buena una cita en un día
bloqueado, o que no notara una cita duplicada tras el reinicio, haría pasar por
verde justo lo que viene a vigilar.
"""
from __future__ import annotations

import pytest

from scripts import medir_portal_y_reinicio as instrumento


def _escenario(espera):
    return {"id": "x", "espera": espera}


CITA_17 = {"booking_date": "2030-01-08", "booking_time": "17:00", "servicio": "Corte señora",
           "status": "confirmed"}
CITA_OTRO_DIA = dict(CITA_17, booking_date="2030-01-09")


@pytest.mark.parametrize("espera,vivas,contexto,roto", [
    ("sin_cita_ese_dia", [CITA_17], {"dia": "2030-01-08"}, True),
    ("sin_cita_ese_dia", [CITA_OTRO_DIA], {"dia": "2030-01-08"}, False),
    ("sin_cita_a_esa_hora", [CITA_17], {"dia": "2030-01-08"}, True),
    ("sin_cita_a_esa_hora", [dict(CITA_17, booking_time="10:00")], {"dia": "2030-01-08"}, False),
    ("sin_cita_del_servicio_retirado", [CITA_17], {"retirados": ["corte senora"]}, True),
    ("sin_cita_del_servicio_retirado", [dict(CITA_17, servicio="Mechas corto")],
     {"retirados": ["corte senora"]}, False),
    ("una_cita_viva", [], {}, True),
    ("una_cita_viva", [CITA_17], {}, False),
    ("una_cita_viva", [CITA_17, CITA_OTRO_DIA], {}, True),   # duplicada tras el reinicio
])
def test_el_juez_mira_la_agenda(espera, vivas, contexto, roto):
    motivo = instrumento.juzgar(_escenario(espera), vivas, contexto, [])
    assert bool(motivo) is roto, motivo


def test_sin_servicio_retirado_no_se_da_por_medido():
    motivo = instrumento.juzgar(_escenario("sin_cita_del_servicio_retirado"), [CITA_17], {}, [])
    assert "no se mide" in motivo


@pytest.mark.parametrize("respuesta,roto", [
    ("📋 *Resumen de tu cita* | 🛍️ Diagnostico y presupuesto | ¿Confirmamos la cita?", True),
    ("📋 *Resumen de tu cita* | 🛍️ Corte señora | ¿Confirmamos la cita?", False),
    ("Esa opcion ya no esta disponible. ¿Que servicio te gustaria?", False),
])
def test_regla_retirada_no_puede_acabar_en_su_resumen(respuesta, roto):
    motivo = instrumento.juzgar(_escenario("sin_resumen_de_la_oferta_retirada"), [], {}, [respuesta])
    assert bool(motivo) is roto, motivo


def test_reiniciar_vacia_lo_que_vive_en_memoria(monkeypatch):
    from backend import appstate

    for nombre in ("whatsapp_flows", "sesiones", "chat_manage_state", "intent_cache"):
        monkeypatch.setattr(appstate, nombre, {"clave": object()})

    hecho = instrumento.accionar("reiniciar", "salon", {})

    for nombre in ("whatsapp_flows", "sesiones", "chat_manage_state", "intent_cache"):
        assert getattr(appstate, nombre) == {}, "tras el reinicio sigue en memoria: %s" % nombre
    assert "reinicio" in hecho


def test_accion_desconocida_no_pasa_en_silencio():
    with pytest.raises(ValueError):
        instrumento.accionar("inventada", "salon", {})
