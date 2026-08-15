"""Reserva de cita como formulario dentro de WhatsApp (WhatsApp Flows, ago 2026).

El flujo por mensajes obligaba a hasta nueve interacciones para pedir hora. Con
Flows, el cliente recibe UN mensaje, abre un formulario dentro de WhatsApp y
elige servicio, profesional y hueco sin salir de la pantalla.

Meta cifra cada peticion a este endpoint: manda una clave AES envuelta con
nuestra clave publica RSA, y espera la respuesta cifrada con esa misma AES y el
vector de inicializacion invertido (XOR 0xFF). Todo eso vive aqui.

Las pantallas NO tienen logica de negocio propia: reutilizan el mismo catalogo,
los mismos profesionales y los mismos huecos que el flujo por mensajes, para que
no puedan divergir (`booking._public_services_for_booking`,
`whatsapp._wa_employees_for_service`, `agenda._available_slots_for_day`).

Apagado por defecto: sin `WHATSAPP_BOOKING_FLOW_ID` ni clave privada, el canal
sigue usando el flujo por mensajes de siempre.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend import agenda, booking, clients, settings, textnorm, timeutils

FLOW_JSON_VERSION = "7.2"
DATA_API_VERSION = "3.0"

SCREEN_SERVICE = "SERVICIO"
SCREEN_EMPLOYEE = "PROFESIONAL"
SCREEN_SLOT = "HUECO"
SCREEN_DATA = "DATOS"

# Cuantos dias mirar hacia delante al listar huecos, y cuantos ofrecer.
SLOT_LOOKAHEAD_DAYS = 21
MAX_SLOT_OPTIONS = 20
MAX_DROPDOWN_OPTIONS = 20

TOKEN_TTL_HOURS = 6


# --- Configuracion ---------------------------------------------------------


def flow_id() -> str:
    return str(getattr(settings, "WHATSAPP_BOOKING_FLOW_ID", "") or "").strip()


def _private_key_pem() -> str:
    raw = str(getattr(settings, "WHATSAPP_FLOW_PRIVATE_KEY_B64", "") or "").strip()
    if not raw:
        return ""
    try:
        return base64.b64decode(raw).decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("WHATSAPP_FLOW_PRIVATE_KEY_B64 no es base64 valido: %s", exc)
        return ""


def enabled() -> bool:
    """El formulario solo se ofrece si Meta esta configurado de punta a punta."""
    return bool(flow_id() and _private_key_pem())


# --- Token de la conversacion ----------------------------------------------
#
# El flow_token viaja al formulario y vuelve en la respuesta. Lleva firmado a que
# negocio y a que telefono pertenece, para no fiarnos de lo que devuelva el cliente.


def _token_secret() -> bytes:
    base = (
        str(getattr(settings, "WHATSAPP_APP_SECRET", "") or "")
        or str(getattr(settings, "ADMIN_API_TOKEN", "") or "")
    )
    return base.encode("utf-8") or b"vantelia-flow"


def make_flow_token(cliente_id: str, phone: str) -> str:
    payload = f"{cliente_id}|{phone}|{timeutils._utc_now_iso()}"
    raw = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    firma = hmac.new(_token_secret(), raw.encode("ascii"), hashlib.sha256).hexdigest()[:32]
    return f"{raw}.{firma}"


def read_flow_token(token: str) -> Dict[str, str]:
    """Devuelve {cliente_id, phone} si el token es autentico y no ha caducado."""
    try:
        raw, firma = str(token or "").split(".", 1)
        esperada = hmac.new(_token_secret(), raw.encode("ascii"), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(firma, esperada):
            return {}
        relleno = "=" * (-len(raw) % 4)
        cliente_id, phone, emitido = base64.urlsafe_b64decode(raw + relleno).decode("utf-8").split("|", 2)
    except Exception:  # noqa: BLE001 - token manipulado o de otra version
        return {}
    emitido_dt = timeutils._from_utc_iso(emitido)
    if not emitido_dt or timeutils._utc_now() - emitido_dt > timedelta(hours=TOKEN_TTL_HOURS):
        return {}
    return {"cliente_id": cliente_id, "phone": phone}


# --- Cifrado ---------------------------------------------------------------


def decrypt_request(body: Dict[str, Any]) -> Tuple[Dict[str, Any], bytes, bytes]:
    """Descifra la peticion de Meta. Devuelve (payload, clave AES, iv)."""
    pem = _private_key_pem()
    if not pem:
        raise RuntimeError("Falta la clave privada del Flow.")
    private_key = serialization.load_pem_private_key(pem.encode("utf-8"), password=None)

    encrypted_aes_key = base64.b64decode(body["encrypted_aes_key"])
    encrypted_flow_data = base64.b64decode(body["encrypted_flow_data"])
    iv = base64.b64decode(body["initial_vector"])

    aes_key = private_key.decrypt(
        encrypted_aes_key,
        asym_padding.OAEP(
            mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    # El tag de autenticacion (16 bytes) viaja al final del cuerpo cifrado.
    payload = AESGCM(aes_key).decrypt(iv, encrypted_flow_data, None)
    return json.loads(payload.decode("utf-8")), aes_key, iv


def encrypt_response(response: Dict[str, Any], aes_key: bytes, iv: bytes) -> str:
    """Cifra la respuesta con el IV invertido (XOR 0xFF), como exige Meta."""
    flipped_iv = bytes(b ^ 0xFF for b in iv)
    cifrado = AESGCM(aes_key).encrypt(
        flipped_iv, json.dumps(response, ensure_ascii=False).encode("utf-8"), None
    )
    return base64.b64encode(cifrado).decode("ascii")


# --- Datos de las pantallas (reutilizan el motor de siempre) ---------------


def _opciones_servicios(cliente_id: str, location_id: str = "") -> List[Dict[str, str]]:
    servicios = booking._public_services_for_booking(cliente_id, location_id=location_id)
    opciones: List[Dict[str, str]] = []
    for svc in servicios[:MAX_DROPDOWN_OPTIONS]:
        nombre = str(svc.get("nombre") or svc.get("name") or "").strip()
        if not nombre:
            continue
        detalle = []
        if svc.get("duration_minutes"):
            detalle.append(f"{int(svc['duration_minutes'])} min")
        if svc.get("price_label"):
            detalle.append(str(svc["price_label"]))
        opciones.append({
            "id": nombre[:80],
            "title": nombre[:30],
            "description": " · ".join(detalle)[:60],
        })
    return opciones


def _opciones_profesionales(cliente_id: str, servicio: str, location_id: str = "") -> List[Dict[str, str]]:
    from backend import whatsapp  # import tardio: whatsapp importa este modulo

    empleados = whatsapp._wa_employees_for_service(cliente_id, servicio, location_id=location_id)
    opciones = [{"id": "", "title": "Sin preferencia", "description": "El primer hueco disponible"}]
    for emp in empleados[:MAX_DROPDOWN_OPTIONS - 1]:
        opciones.append({
            "id": str(emp["id"]),
            "title": str(emp["name"] or "Profesional")[:30],
            "description": str(emp["role_label"] or "")[:60],
        })
    return opciones


async def _opciones_huecos(
    cliente_id: str, servicio: str, employee_id: str = "", location_id: str = ""
) -> List[Dict[str, str]]:
    """Proximos huecos reales, ya mezclando dias: el cliente elige "cuando", no
    "que dia" y luego "que hora"."""
    config = clients._get_client_config(cliente_id)
    tz_name = (config.get("booking") or {}).get("timezone") or settings.DEFAULT_TIMEZONE
    try:
        from zoneinfo import ZoneInfo

        hoy = timeutils._utc_now().astimezone(ZoneInfo(tz_name)).date()
    except Exception:  # noqa: BLE001
        hoy = timeutils._utc_now().date()

    opciones: List[Dict[str, str]] = []
    for offset in range(SLOT_LOOKAHEAD_DAYS):
        if len(opciones) >= MAX_SLOT_OPTIONS:
            break
        dia = hoy + timedelta(days=offset)
        try:
            if employee_id:
                _, libres = await agenda._employee_slot_sets_for_day(
                    cliente_id, dia.isoformat(), employee_id=employee_id, servicio=servicio,
                )
            else:
                _, libres = await agenda._public_slot_sets_for_day(
                    cliente_id, dia.isoformat(), servicio=servicio, location_id=location_id,
                )
        except Exception:  # noqa: BLE001 - un dia problematico no corta el listado
            continue
        etiqueta_dia = textnorm._format_date_es(dia).capitalize()
        for hora in sorted(libres):
            if len(opciones) >= MAX_SLOT_OPTIONS:
                break
            opciones.append({
                "id": f"{dia.isoformat()}T{hora}",
                "title": f"{etiqueta_dia} · {hora}"[:30],
                "description": "",
            })
    return opciones


# --- Maquina de pantallas --------------------------------------------------


def _pantalla(screen: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return {"screen": screen, "data": data}


async def handle_data_exchange(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Decide la siguiente pantalla a partir de lo que el cliente acaba de elegir."""
    action = str(payload.get("action") or "")
    if action == "ping":
        return {"data": {"status": "active"}}
    if payload.get("error") or action == "error_notification":
        return {"data": {"acknowledged": True}}

    contexto = read_flow_token(str(payload.get("flow_token") or ""))
    if not contexto:
        return _pantalla(SCREEN_SERVICE, {
            "servicios": [],
            "aviso": "Esta solicitud ha caducado. Escribe *cita* para empezar de nuevo.",
            "hay_aviso": True,
        })

    cliente_id = contexto["cliente_id"]
    datos = payload.get("data") or {}
    screen = str(payload.get("screen") or "")
    location_id = str(datos.get("location_id") or "")

    if action == "INIT" or not screen:
        return _pantalla(SCREEN_SERVICE, {
            "servicios": _opciones_servicios(cliente_id, location_id),
            "aviso": "",
            "hay_aviso": False,
        })

    if screen == SCREEN_SERVICE:
        servicio = str(datos.get("servicio") or "")
        profesionales = _opciones_profesionales(cliente_id, servicio, location_id)
        # Con un solo profesional real no hay nada que elegir: se salta la pantalla.
        if len(profesionales) <= 2:
            employee_id = profesionales[1]["id"] if len(profesionales) == 2 else ""
            huecos = await _opciones_huecos(cliente_id, servicio, employee_id, location_id)
            return _pantalla(SCREEN_SLOT, {
                "servicio": servicio, "employee_id": employee_id, "huecos": huecos,
            })
        return _pantalla(SCREEN_EMPLOYEE, {"servicio": servicio, "profesionales": profesionales})

    if screen == SCREEN_EMPLOYEE:
        servicio = str(datos.get("servicio") or "")
        employee_id = str(datos.get("employee_id") or "")
        huecos = await _opciones_huecos(cliente_id, servicio, employee_id, location_id)
        return _pantalla(SCREEN_SLOT, {
            "servicio": servicio, "employee_id": employee_id, "huecos": huecos,
        })

    if screen == SCREEN_SLOT:
        return _pantalla(SCREEN_DATA, {
            "servicio": str(datos.get("servicio") or ""),
            "employee_id": str(datos.get("employee_id") or ""),
            "hueco": str(datos.get("hueco") or ""),
        })

    # Pantalla final: el formulario se cierra y la cita se crea al recibir el
    # webhook con la respuesta (nfm_reply), no aqui.
    return {"screen": "SUCCESS", "data": {"extension_message_response": {"params": {"flow_token": payload.get("flow_token", "")}}}}


def parse_flow_response(response_json: str) -> Dict[str, str]:
    """Extrae los datos de la cita de la respuesta que devuelve el formulario."""
    try:
        datos = json.loads(response_json or "{}")
    except Exception:  # noqa: BLE001
        return {}
    hueco = str(datos.get("hueco") or "")
    fecha, _, hora = hueco.partition("T")
    return {
        "flow_token": str(datos.get("flow_token") or ""),
        "servicio": str(datos.get("servicio") or ""),
        "employee_id": str(datos.get("employee_id") or ""),
        "fecha": fecha,
        "hora": hora,
        "nombre": str(datos.get("nombre") or "").strip(),
        "email": str(datos.get("email") or "").strip().lower(),
        "notas": str(datos.get("notas") or "").strip(),
    }
