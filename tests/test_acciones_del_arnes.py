"""El instrumento elige botones enviados; nunca traduce un si en consentimiento."""
import pytest

from evals import arnes


@pytest.fixture
def captura():
    return arnes.CapturaEnvios()


def ofrecer(captura, identidad="actual", cliente="demo", numero="600", enviado=True):
    captura.registrar("Resumen", "botones", cliente, numero,
                      [("confirm_yes:" + identidad, "Confirmar")], enviado=enviado)


@pytest.mark.parametrize("texto", ["sí", "si, confirmo", "¿confirmamos?", "sí, pero a las cinco"])
def test_texto_libre_nunca_se_convierte_en_click(captura, texto):
    ofrecer(captura)
    assert arnes.preparar_entrada(captura, "demo", "600", texto) == (texto, "")
    assert captura.opciones("demo", "600") == []


def test_indice_actual_y_repeticion_explicita_del_id_emitido(captura):
    ofrecer(captura)
    assert arnes.preparar_entrada(captura, "demo", "600", {
        "accion": "pulsar_boton", "indice": 0}) == ("Confirmar", "confirm_yes:actual")
    assert arnes.preparar_entrada(captura, "demo", "600", {
        "boton": "confirm_yes:actual"}) == ("Confirmar", "confirm_yes:actual")


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


def test_id_antiguo_emitido_llega_al_producto(captura):
    ofrecer(captura, "vieja")
    ofrecer(captura, "actual")
    assert arnes.preparar_entrada(captura, "demo", "600", {
        "boton": "confirm_yes:vieja"}) == ("Confirmar", "confirm_yes:vieja")


@pytest.mark.parametrize("indice", [-1, 1, True, "0"])
def test_indice_inexistente_no_se_corrige(captura, indice):
    ofrecer(captura)
    with pytest.raises(arnes.AccionNoDisponible):
        arnes.preparar_entrada(captura, "demo", "600", {"accion": "pulsar_boton", "indice": indice})
