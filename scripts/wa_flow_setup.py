#!/usr/bin/env python3
"""Alta del formulario de reserva de WhatsApp (Flows) en Meta.

Hace, en este orden y de forma idempotente:

1. Genera un par de claves RSA-2048 (si no lo tienes ya) y sube la publica al
   numero: Meta cifra con ella cada peticion al endpoint de datos.
2. Crea el Flow en la WABA, sube el JSON de pantallas y apunta el endpoint a
   `<APP_BASE_URL>/whatsapp/flow`.
3. Lo publica y te imprime las dos variables de entorno que hay que poner.

Uso:
    python scripts/wa_flow_setup.py --waba-id 123 --phone-number-id 456
    python scripts/wa_flow_setup.py --waba-id 123 --phone-number-id 456 --only-keys
    python scripts/wa_flow_setup.py --flow-id 789 --update-json   # solo re-subir pantallas

Requiere WHATSAPP_ACCESS_TOKEN con permisos sobre esa WABA.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FLOW_JSON_PATH = Path(__file__).resolve().parent / "wa_flow_booking.json"
GRAPH = "https://graph.facebook.com"


def _env(nombre: str, defecto: str = "") -> str:
    for linea in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if linea.strip().startswith(f"{nombre}="):
            return linea.split("=", 1)[1].strip()
    return defecto


TOKEN = _env("WHATSAPP_ACCESS_TOKEN")
API = _env("WHATSAPP_API_VERSION", "v22.0")
BASE_URL = _env("APP_BASE_URL", "https://app.vantelia.es").rstrip("/")


def _check(response: requests.Response, paso: str) -> dict:
    try:
        data = response.json()
    except Exception:  # noqa: BLE001
        data = {"raw": response.text[:400]}
    if response.status_code >= 300 or "error" in data:
        print(f"  ERROR en {paso}: {json.dumps(data, ensure_ascii=False)[:500]}", file=sys.stderr)
        raise SystemExit(1)
    return data


def generar_claves() -> str:
    """Par RSA-2048. Devuelve la privada en PEM (la publica se sube a Meta)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    privada = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")
    publica = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode("utf-8")
    return privada, publica


def subir_clave_publica(phone_number_id: str, publica: str) -> None:
    print("· Subiendo la clave publica al numero...")
    respuesta = requests.post(
        f"{GRAPH}/{API}/{phone_number_id}/whatsapp_business_encryption",
        data={"business_public_key": publica, "access_token": TOKEN},
        timeout=30,
    )
    _check(respuesta, "subida de clave publica")
    print("  clave publica registrada")


def crear_flow(waba_id: str) -> str:
    print("· Creando el Flow...")
    respuesta = requests.post(
        f"{GRAPH}/{API}/{waba_id}/flows",
        data={
            "name": "Reserva de cita",
            "categories": json.dumps(["APPOINTMENT_BOOKING"]),
            "endpoint_uri": f"{BASE_URL}/whatsapp/flow",
            "access_token": TOKEN,
        },
        timeout=30,
    )
    data = _check(respuesta, "creacion del flow")
    flow_id = str(data.get("id"))
    print(f"  flow creado: {flow_id}")
    return flow_id


def subir_json(flow_id: str) -> None:
    print("· Subiendo las pantallas...")
    with FLOW_JSON_PATH.open("rb") as fh:
        respuesta = requests.post(
            f"{GRAPH}/{API}/{flow_id}/assets",
            data={"name": "flow.json", "asset_type": "FLOW_JSON", "access_token": TOKEN},
            files={"file": ("flow.json", fh, "application/json")},
            timeout=60,
        )
    data = _check(respuesta, "subida del JSON")
    errores = data.get("validation_errors") or []
    if errores:
        print("  AVISO, validaciones de Meta:")
        for err in errores:
            print("   -", json.dumps(err, ensure_ascii=False)[:300])
    else:
        print("  pantallas subidas sin errores de validacion")


def publicar(flow_id: str) -> None:
    print("· Publicando...")
    respuesta = requests.post(
        f"{GRAPH}/{API}/{flow_id}/publish", data={"access_token": TOKEN}, timeout=30
    )
    _check(respuesta, "publicacion")
    print("  flow publicado")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--waba-id", default="")
    parser.add_argument("--phone-number-id", default="")
    parser.add_argument("--flow-id", default="")
    parser.add_argument("--only-keys", action="store_true", help="solo generar y subir claves")
    parser.add_argument("--update-json", action="store_true", help="solo re-subir las pantallas")
    parser.add_argument("--no-publish", action="store_true")
    args = parser.parse_args()

    if not TOKEN:
        print("ERROR: falta WHATSAPP_ACCESS_TOKEN en .env", file=sys.stderr)
        raise SystemExit(1)

    if args.update_json:
        if not args.flow_id:
            print("ERROR: --update-json necesita --flow-id", file=sys.stderr)
            raise SystemExit(1)
        subir_json(args.flow_id)
        if not args.no_publish:
            publicar(args.flow_id)
        return

    if not args.phone_number_id:
        print("ERROR: falta --phone-number-id", file=sys.stderr)
        raise SystemExit(1)

    privada, publica = generar_claves()
    subir_clave_publica(args.phone_number_id, publica)
    privada_b64 = base64.b64encode(privada.encode("utf-8")).decode("ascii")

    flow_id = args.flow_id
    if not args.only_keys:
        if not args.waba_id:
            print("ERROR: falta --waba-id", file=sys.stderr)
            raise SystemExit(1)
        flow_id = flow_id or crear_flow(args.waba_id)
        subir_json(flow_id)
        if not args.no_publish:
            publicar(flow_id)

    print("\n=== Pega esto en el .env (local y produccion) ===")
    print(f"WHATSAPP_FLOW_PRIVATE_KEY_B64={privada_b64}")
    if flow_id:
        print(f"WHATSAPP_BOOKING_FLOW_ID={flow_id}")
    print("\nGuarda la clave privada: no se puede recuperar, habria que regenerar el par.")


if __name__ == "__main__":
    main()
