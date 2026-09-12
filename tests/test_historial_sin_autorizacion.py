"""Perder la propuesta no convierte una pregunta antigua en autorización."""
import pytest


@pytest.mark.parametrize("dicho", ["sí", "vale", "de acuerdo"])
def test_sin_propuesta_no_se_acepta_por_el_texto_del_bot(monkeypatch, dicho):
    from backend import agent, booking, reserva
    monkeypatch.setattr(booking, "_servicio_de_valoracion", lambda *a, **k: {"nombre": "Diagnóstico"})
    charla = [{"role": "assistant", "content": "¿Quieres una cita de diagnóstico?"}]
    assert not agent._pide_la_valoracion("demo", dicho, mensajes=charla,
                                        estado=reserva.Estado(intencion="reservar"))
