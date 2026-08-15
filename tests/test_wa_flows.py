"""Reserva como formulario dentro de WhatsApp (WhatsApp Flows).

El flujo por mensajes llegaba a nueve interacciones. Con Flows el cliente recibe
UN mensaje y elige servicio, profesional y hora dentro de una pantalla.

Meta cifra cada peticion al endpoint de datos, asi que aqui se simula a Meta de
verdad: se genera un par RSA, se cifra como lo hace ella (AES-128-GCM + clave
envuelta con RSA-OAEP SHA-256) y se comprueba que la respuesta se puede descifrar
con el IV invertido. Si el protocolo se rompe, el formulario deja de abrirse.

Tambien se fija lo que NO puede fallar: sin configurar, el canal sigue usando el
flujo por mensajes de siempre; y un flow_token manipulado o caducado no reserva.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from test_booking_exhaustive import api_module  # noqa: F401


@pytest.fixture()
def claves(api_module, monkeypatch):
    """Par RSA de prueba, montado como lo haria el .env de produccion."""
    from backend import settings

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    monkeypatch.setattr(
        settings, "WHATSAPP_FLOW_PRIVATE_KEY_B64",
        base64.b64encode(pem).decode("ascii"), raising=False,
    )
    monkeypatch.setattr(settings, "WHATSAPP_BOOKING_FLOW_ID", "flow-de-prueba", raising=False)
    return key


def _cifrar_como_meta(key, payload: dict):
    """Reproduce el cifrado de Meta: AES-128-GCM + clave envuelta con RSA-OAEP."""
    aes_key = os.urandom(16)
    iv = os.urandom(16)
    cifrado = AESGCM(aes_key).encrypt(iv, json.dumps(payload).encode("utf-8"), None)
    envuelta = key.public_key().encrypt(
        aes_key,
        asym_padding.OAEP(
            mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return {
        "encrypted_flow_data": base64.b64encode(cifrado).decode("ascii"),
        "encrypted_aes_key": base64.b64encode(envuelta).decode("ascii"),
        "initial_vector": base64.b64encode(iv).decode("ascii"),
    }, aes_key, iv


def _descifrar_respuesta(cifrada_b64: str, aes_key: bytes, iv: bytes) -> dict:
    """Lo que hara Meta al recibir nuestra respuesta: descifrar con el IV invertido."""
    flipped = bytes(b ^ 0xFF for b in iv)
    claro = AESGCM(aes_key).decrypt(flipped, base64.b64decode(cifrada_b64), None)
    return json.loads(claro.decode("utf-8"))


# --- Protocolo de cifrado --------------------------------------------------


def test_ida_y_vuelta_cifrada_con_meta(api_module, claves):
    from backend import wa_flows

    body, aes_key, iv = _cifrar_como_meta(claves, {"version": "3.0", "action": "ping"})
    payload, k, i = wa_flows.decrypt_request(body)
    assert payload["action"] == "ping"

    respuesta = asyncio.run(wa_flows.handle_data_exchange(payload))
    assert respuesta == {"data": {"status": "active"}}
    assert _descifrar_respuesta(wa_flows.encrypt_response(respuesta, k, i), aes_key, iv) == respuesta


def test_sin_clave_privada_no_se_descifra(api_module, monkeypatch):
    from backend import settings, wa_flows

    monkeypatch.setattr(settings, "WHATSAPP_FLOW_PRIVATE_KEY_B64", "", raising=False)
    with pytest.raises(Exception):
        wa_flows.decrypt_request({"encrypted_flow_data": "x", "encrypted_aes_key": "y", "initial_vector": "z"})


def test_la_notificacion_de_error_se_reconoce(api_module, claves):
    from backend import wa_flows

    respuesta = asyncio.run(wa_flows.handle_data_exchange(
        {"version": "3.0", "action": "data_exchange", "error": "algo", "flow_token": "x"}
    ))
    assert respuesta == {"data": {"acknowledged": True}}


# --- Token de la conversacion ----------------------------------------------


def test_el_token_ata_la_conversacion_a_su_negocio(api_module, claves):
    from backend import wa_flows

    token = wa_flows.make_flow_token("demo", "34600111222")
    leido = wa_flows.read_flow_token(token)
    assert leido == {"cliente_id": "demo", "phone": "34600111222"}


def test_un_token_manipulado_no_vale(api_module, claves):
    from backend import wa_flows

    token = wa_flows.make_flow_token("demo", "34600111222")
    cuerpo, _, firma = token.partition(".")
    # Cambiar el negocio manteniendo la firma no debe colar.
    falso = base64.urlsafe_b64encode(b"van|34600111222|2026-08-15T00:00:00Z").decode().rstrip("=")
    assert wa_flows.read_flow_token(f"{falso}.{firma}") == {}
    assert wa_flows.read_flow_token("basura") == {}
    assert wa_flows.read_flow_token("") == {}


def test_un_token_caducado_no_vale(api_module, claves, monkeypatch):
    from backend import wa_flows

    token = wa_flows.make_flow_token("demo", "34600111222")
    monkeypatch.setattr(wa_flows, "TOKEN_TTL_HOURS", 0)
    assert wa_flows.read_flow_token(token) == {}


# --- Pantallas -------------------------------------------------------------


def test_la_primera_pantalla_ofrece_los_servicios_del_negocio(api_module, claves):
    from backend import wa_flows

    token = wa_flows.make_flow_token("demo", "34600111222")
    respuesta = asyncio.run(wa_flows.handle_data_exchange(
        {"version": "3.0", "action": "INIT", "flow_token": token, "data": {}}
    ))
    assert respuesta["screen"] == wa_flows.SCREEN_SERVICE
    assert isinstance(respuesta["data"]["servicios"], list)


def test_con_token_invalido_no_se_filtra_ningun_dato(api_module, claves):
    """Sin token valido no se puede saber de que negocio es: no se listan servicios."""
    from backend import wa_flows

    respuesta = asyncio.run(wa_flows.handle_data_exchange(
        {"version": "3.0", "action": "INIT", "flow_token": "falso", "data": {}}
    ))
    assert respuesta["data"]["servicios"] == []
    assert "caducado" in respuesta["data"]["aviso"]


def test_tras_elegir_hueco_se_piden_los_datos(api_module, claves):
    from backend import wa_flows

    token = wa_flows.make_flow_token("demo", "34600111222")
    respuesta = asyncio.run(wa_flows.handle_data_exchange({
        "version": "3.0", "action": "data_exchange", "flow_token": token,
        "screen": wa_flows.SCREEN_SLOT,
        "data": {"servicio": "Corte", "employee_id": "", "hueco": "2026-09-01T10:00"},
    }))
    assert respuesta["screen"] == wa_flows.SCREEN_DATA
    assert respuesta["data"]["hueco"] == "2026-09-01T10:00"


# --- Respuesta del formulario ----------------------------------------------


def test_se_leen_los_datos_de_la_cita(api_module, claves):
    from backend import wa_flows

    datos = wa_flows.parse_flow_response(json.dumps({
        "flow_token": "t", "servicio": "Corte", "employee_id": "emp_1",
        "hueco": "2026-09-01T10:30", "nombre": "Pablo Sanchez",
        "email": "PABLO@Example.com ", "notas": "  alergia  ",
    }))
    assert datos["fecha"] == "2026-09-01"
    assert datos["hora"] == "10:30"
    assert datos["email"] == "pablo@example.com"
    assert datos["notas"] == "alergia"


def test_una_respuesta_corrupta_no_revienta(api_module, claves):
    from backend import wa_flows

    assert wa_flows.parse_flow_response("{no es json") == {}
    assert wa_flows.parse_flow_response("")["fecha"] == ""


# --- Interruptor -----------------------------------------------------------


def test_apagado_por_defecto(api_module, monkeypatch):
    """Sin configurar, el canal sigue con el flujo por mensajes de siempre."""
    from backend import settings, wa_flows

    monkeypatch.setattr(settings, "WHATSAPP_BOOKING_FLOW_ID", "", raising=False)
    monkeypatch.setattr(settings, "WHATSAPP_FLOW_PRIVATE_KEY_B64", "", raising=False)
    assert wa_flows.enabled() is False


def test_activo_solo_con_las_dos_piezas(api_module, claves, monkeypatch):
    from backend import settings, wa_flows

    assert wa_flows.enabled() is True
    monkeypatch.setattr(settings, "WHATSAPP_BOOKING_FLOW_ID", "", raising=False)
    assert wa_flows.enabled() is False


def test_si_meta_rechaza_el_formulario_se_usa_el_flujo_de_siempre(api_module, claves, monkeypatch):
    from backend import messaging, whatsapp

    async def fake_payload(**kwargs):
        return False  # Meta lo rechaza

    monkeypatch.setattr(messaging, "_send_whatsapp_payload", fake_payload)
    enviado = asyncio.run(whatsapp._wa_send_booking_form(
        cliente_id="demo", phone_number_id="PN", to_number="34600111222",
    ))
    assert enviado is False


# --- De la respuesta del formulario a la cita ------------------------------


def test_la_respuesta_del_formulario_crea_la_cita(api_module, claves, monkeypatch):
    """El formulario solo cambia COMO se recogen los datos: la reserva la sigue
    creando el mismo `_wa_create_booking` que el flujo por mensajes."""
    from backend import whatsapp

    capturado = {}

    async def fake_create(**kwargs):
        capturado["flow"] = kwargs["flow"]
        return True

    monkeypatch.setattr(whatsapp, "_wa_create_booking", fake_create)

    token = whatsapp.wa_flows.make_flow_token("demo", "34600111222")
    respuesta = json.dumps({
        "flow_token": token, "servicio": "Corte", "employee_id": "",
        "hueco": "2026-09-01T10:30", "nombre": "Pablo Sanchez",
        "email": "pablo@example.com", "notas": "",
    })
    ok = asyncio.run(whatsapp._wa_handle_flow_reply(
        cliente_id="demo", phone_number_id="PN", from_number="34600111222",
        response_json=respuesta, request=None,
    ))
    assert ok is True
    flow = capturado["flow"]
    assert (flow.servicio, flow.fecha, flow.hora) == ("Corte", "2026-09-01", "10:30")
    assert flow.nombre == "Pablo Sanchez"


def test_un_formulario_de_otro_negocio_no_reserva(api_module, claves, monkeypatch):
    """El token dice a que negocio pertenece: si no coincide, no se crea nada."""
    from backend import messaging, whatsapp

    creadas = []

    async def fake_create(**kwargs):
        creadas.append(kwargs)
        return True

    async def fake_text(**kwargs):
        return True

    monkeypatch.setattr(whatsapp, "_wa_create_booking", fake_create)
    monkeypatch.setattr(messaging, "_send_whatsapp_text", fake_text)

    token_de_otro = whatsapp.wa_flows.make_flow_token("van", "34600111222")
    ok = asyncio.run(whatsapp._wa_handle_flow_reply(
        cliente_id="demo", phone_number_id="PN", from_number="34600111222",
        response_json=json.dumps({"flow_token": token_de_otro, "hueco": "2026-09-01T10:30"}),
        request=None,
    ))
    assert ok is False
    assert creadas == []


def test_sin_hora_elegida_no_reserva(api_module, claves, monkeypatch):
    from backend import messaging, whatsapp

    creadas = []

    async def fake_create(**kwargs):
        creadas.append(kwargs)
        return True

    async def fake_text(**kwargs):
        return True

    monkeypatch.setattr(whatsapp, "_wa_create_booking", fake_create)
    monkeypatch.setattr(messaging, "_send_whatsapp_text", fake_text)

    token = whatsapp.wa_flows.make_flow_token("demo", "34600111222")
    ok = asyncio.run(whatsapp._wa_handle_flow_reply(
        cliente_id="demo", phone_number_id="PN", from_number="34600111222",
        response_json=json.dumps({"flow_token": token, "hueco": ""}),
        request=None,
    ))
    assert ok is False
    assert creadas == []
