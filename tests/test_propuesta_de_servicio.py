"""La alternativa no es una elección ni una autorización de reserva."""
from dataclasses import asdict

import pytest

from backend import appstate, reserva


def preparar(estado):
    return reserva.preparar_propuesta_servicio(
        estado, servicio_id="diagnostico", nombre="Diagnóstico",
        origen="regla:indecision", revision_config="politica-y-servicio-v1")


def responder(estado, propuesta, respuesta="acepta", revision="politica-y-servicio-v1"):
    return reserva.responder_propuesta_servicio(
        estado, propuesta.id, respuesta, revision_config=revision)


def test_ofrecer_y_aceptar_no_selecciona_ni_crea_la_cita():
    estado = reserva.Estado(intencion="reservar", servicio="Alisado", hora="15:00")
    antes = asdict(estado)
    propuesta = preparar(estado)
    assert not responder(estado, propuesta)  # no se llegó a enviar
    assert reserva.marcar_propuesta_ofrecida(estado, propuesta.id, "mensaje-1")
    assert responder(estado, propuesta)
    assert estado.propuesta_servicio.estado == "aceptada"
    despues = asdict(estado)
    despues.pop("propuesta_servicio")
    antes.pop("propuesta_servicio")
    assert despues == antes  # elegir exige resolver/revalidar con la tool


@pytest.mark.parametrize("respuesta", ["otra", "fecha", "", "si"])
def test_una_interpretacion_ambigua_no_acepta(respuesta):
    estado = reserva.Estado(intencion="reservar")
    propuesta = preparar(estado)
    reserva.marcar_propuesta_ofrecida(estado, propuesta.id, "mensaje-1")
    assert not responder(estado, propuesta, respuesta)
    assert estado.propuesta_servicio.estado == "ofrecida"


def test_rechazo_y_reentrega_no_reabren_la_propuesta():
    estado = reserva.Estado(intencion="reservar")
    propuesta = preparar(estado)
    reserva.marcar_propuesta_ofrecida(estado, propuesta.id, "mensaje-1")
    assert responder(estado, propuesta, "rechaza")
    assert not reserva.marcar_propuesta_ofrecida(estado, propuesta.id, "mensaje-1")
    assert not responder(estado, propuesta)
    assert estado.propuesta_servicio.estado == "rechazada"


def test_confirmacion_y_acuse_repetidos_son_inertes():
    estado = reserva.Estado(intencion="reservar")
    propuesta = preparar(estado)
    assert reserva.marcar_propuesta_ofrecida(estado, propuesta.id, "mensaje-1")
    assert not reserva.marcar_propuesta_ofrecida(estado, propuesta.id, "mensaje-2")
    assert estado.propuesta_servicio.mensaje_id == "mensaje-1"
    assert responder(estado, propuesta)
    assert not responder(estado, propuesta)


@pytest.mark.parametrize("tenant,conversacion", [("otro", "uno"), ("salon", "dos")])
def test_no_se_acepta_en_otro_tenant_o_conversacion(monkeypatch, tenant, conversacion):
    monkeypatch.setattr(appstate, "ESTADOS_DE_RESERVA", {}, raising=False)
    estado = reserva.cargar("salon", "uno")
    estado.intencion = "reservar"
    propuesta = preparar(estado)
    reserva.marcar_propuesta_ofrecida(estado, propuesta.id, "mensaje-1")
    otro = reserva.cargar(tenant, conversacion)
    otro.intencion = "reservar"
    preparar(otro)
    assert not responder(otro, propuesta)
    assert estado.propuesta_servicio.estado == "ofrecida"


def test_propuesta_nueva_y_reinicio_rechazan_ids_antiguos():
    estado = reserva.Estado(intencion="reservar")
    antigua = preparar(estado)
    reserva.marcar_propuesta_ofrecida(estado, antigua.id, "mensaje-1")
    nueva = preparar(estado)
    assert nueva.id != antigua.id
    assert not responder(estado, antigua)
    assert not responder(reserva.Estado(intencion="reservar"), nueva)


@pytest.mark.parametrize("cambio", ["politica", "gestion", "caducidad"])
def test_cambio_de_contexto_invalida_confirmacion(monkeypatch, cambio):
    estado = reserva.Estado(intencion="reservar")
    propuesta = preparar(estado)
    reserva.marcar_propuesta_ofrecida(estado, propuesta.id, "mensaje-1")
    estado.esperando_confirmacion = True
    revision = "politica-y-servicio-v1"
    if cambio == "politica":
        revision = "politica-y-servicio-v2"
    elif cambio == "gestion":
        estado.intencion = "reprogramar"
    else:
        monkeypatch.setattr(reserva.time, "time", lambda: propuesta.creada + reserva.CADUCA_EN + 1)
    assert not responder(estado, propuesta, revision=revision)
    assert estado.propuesta_servicio.estado == "invalidada"
    assert not estado.esperando_confirmacion


def test_invalidacion_explicita_impide_usar_un_boton_antiguo():
    estado = reserva.Estado(intencion="reservar")
    propuesta = preparar(estado)
    reserva.marcar_propuesta_ofrecida(estado, propuesta.id, "mensaje-1")
    reserva.invalidar_propuesta_servicio(estado)
    assert not responder(estado, propuesta)


@pytest.mark.parametrize("intencion", ["cancelar", "reprogramar", ""])
def test_no_se_prepara_alternativa_fuera_de_reserva(intencion):
    with pytest.raises(ValueError):
        preparar(reserva.Estado(intencion=intencion))
