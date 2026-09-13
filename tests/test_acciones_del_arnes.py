"""El instrumento elige botones enviados; nunca traduce un si en consentimiento."""
import pytest

from evals import arnes


@pytest.fixture
def captura(monkeypatch):
    monkeypatch.setattr(arnes, "_propuesta_vigente", lambda *a: {
        "id": "actual", "estado": "ofrecida"}, raising=False)
    return arnes.CapturaEnvios()


def ofrecer(captura, identidad="actual", cliente="demo", numero="600", enviado=True):
    captura.registrar("Resumen", "botones", cliente, numero,
                      [("confirm_yes:" + identidad, "Confirmar")], enviado=enviado)


@pytest.mark.parametrize("texto", ["sí", "si, confirmo", "¿confirmamos?", "sí, pero a las cinco"])
def test_texto_libre_nunca_se_convierte_en_click(captura, texto):
    ofrecer(captura)
    assert arnes.preparar_entrada(captura, "demo", "600", texto) == (texto, "")
    assert captura.opciones("demo", "600") == []


def test_accion_explicita_usa_id_emitido_y_se_consume(captura):
    ofrecer(captura)
    assert arnes.preparar_entrada(captura, "demo", "600", {
        "accion": "aceptar_oferta"}) == ("Confirmar", "confirm_yes:actual")
    with pytest.raises(arnes.AccionNoDisponible):
        arnes.preparar_entrada(captura, "demo", "600", {"boton": "confirm_yes:actual"})


@pytest.mark.parametrize("causa", ["otro_tenant", "otro_numero", "rechazada", "vieja", "id_inventado"])
def test_no_se_corrige_una_accion_sin_oferta_valida(captura, causa):
    ofrecer(captura, identidad="vieja" if causa == "vieja" else "actual",
            enviado=causa != "rechazada")
    with pytest.raises(arnes.AccionNoDisponible):
        arnes.preparar_entrada(captura, "otro" if causa == "otro_tenant" else "demo",
            "otro" if causa == "otro_numero" else "600",
            {"boton": "confirm_yes:inventado" if causa == "id_inventado" else "confirm_yes:actual"})


def test_texto_del_resumen_sin_botones_no_ofrece_accion(captura):
    captura.registrar("Resumen de tu cita. ¿Confirmamos?", "texto", "demo", "600")
    assert captura.opciones("demo", "600") == []


def test_ultima_oferta_sustituye_la_anterior(captura):
    ofrecer(captura, "vieja")
    ofrecer(captura)
    assert captura.opciones("demo", "600") == [
        {"id": "confirm_yes:actual", "titulo": "Confirmar"}]


@pytest.mark.parametrize("estado", ["preparada", "aceptada", "hecha"])
def test_propuesta_que_no_esta_ofrecida_no_admite_click(captura, monkeypatch, estado):
    ofrecer(captura)
    monkeypatch.setattr(arnes, "_propuesta_vigente", lambda *a: {"id": "actual", "estado": estado})
    with pytest.raises(arnes.AccionNoDisponible):
        arnes.preparar_entrada(captura, "demo", "600", {"accion": "aceptar_oferta"})
