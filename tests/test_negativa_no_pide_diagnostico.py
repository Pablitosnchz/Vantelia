"""Nombrar el diagnóstico para rechazarlo no selecciona ese servicio."""
import pytest

from test_booking_exhaustive import api_module  # noqa: F401


@pytest.mark.parametrize("dicho", ["no quiero diagnóstico", "sin diagnóstico, por favor"])
@pytest.mark.parametrize("obligatoria", [False, True])
def test_rechazar_no_es_pedir_una_valoracion(api_module, monkeypatch, dicho, obligatoria):
    from backend import agent, booking
    monkeypatch.setattr(booking, "_servicio_de_valoracion",
                        lambda *a, **k: {"nombre": "Diagnóstico y presupuesto"})
    monkeypatch.setattr(booking, "la_valoracion_es_obligatoria", lambda *a: obligatoria)
    assert not agent._pide_la_valoracion("demo", dicho)
    _, acumulado = agent._descripcion_para_buscar("demo", dicho, "quiero un alisado")
    assert acumulado, "El rechazo no debe borrar el servicio que la clienta venía pidiendo"


@pytest.mark.parametrize("dicho", ["quiero un diagnóstico", "cógeme una cita de valoración", "quiero una cita de diagnóstico directamente"])
def test_la_peticion_explicita_sigue_valiendo(api_module, monkeypatch, dicho):
    from backend import agent, booking
    monkeypatch.setattr(booking, "_servicio_de_valoracion",
                        lambda *a, **k: {"nombre": "Diagnóstico y presupuesto"})
    assert agent._pide_la_valoracion("demo", dicho)
