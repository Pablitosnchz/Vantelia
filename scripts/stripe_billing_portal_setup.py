"""Configura el Stripe Customer Billing Portal con los ajustes recomendados.

- Cancelacion: al final del periodo (no inmediato).
- Actualizacion del metodo de pago: ON.
- Actualizacion de datos personales: ON.
- Historial de facturas: ON.
- Cambio de plan: OFF (lo gestionamos desde el portal de Vantelia).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if not ENV_PATH.exists():
        return env
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()
    return env


def main() -> int:
    env = load_env()
    sk = env.get("STRIPE_SECRET_KEY", "").strip()
    if not sk:
        print("ERROR: STRIPE_SECRET_KEY no esta en .env", file=sys.stderr)
        return 1

    import stripe  # type: ignore

    stripe.api_key = sk

    privacy_url = "https://www.vantelia.es/legal/privacidad/"
    terms_url = "https://www.vantelia.es/legal/terminos/"

    features = {
        "customer_update": {
            "enabled": True,
            "allowed_updates": ["email", "address", "phone", "tax_id"],
        },
        "invoice_history": {"enabled": True},
        "payment_method_update": {"enabled": True},
        "subscription_cancel": {
            "enabled": True,
            "mode": "at_period_end",
            "proration_behavior": "none",
            "cancellation_reason": {
                "enabled": True,
                "options": [
                    "too_expensive",
                    "missing_features",
                    "switched_service",
                    "unused",
                    "customer_service",
                    "too_complex",
                    "low_quality",
                    "other",
                ],
            },
        },
        "subscription_update": {"enabled": False},
    }

    business_profile = {
        "headline": "Gestiona tu suscripcion de Vantelia",
        "privacy_policy_url": privacy_url,
        "terms_of_service_url": terms_url,
    }

    existing = stripe.billing_portal.Configuration.list(is_default=True, limit=1).data
    if existing:
        cfg = existing[0]
        print(f"Configuracion default encontrada: {cfg.id}, actualizando...")
        updated = stripe.billing_portal.Configuration.modify(
            cfg.id,
            features=features,
            business_profile=business_profile,
            default_return_url="https://app.vantelia.es/portal",
        )
        print(f"OK actualizada: {updated.id}")
    else:
        print("No hay configuracion default, creando una nueva...")
        created = stripe.billing_portal.Configuration.create(
            features=features,
            business_profile=business_profile,
            default_return_url="https://app.vantelia.es/portal",
        )
        print(f"OK creada: {created.id}")

    print("\nResumen:")
    print(f"  cancel mode: at_period_end")
    print(f"  payment method update: ON")
    print(f"  customer update: email/address/phone/tax_id")
    print(f"  invoice history: ON")
    print(f"  subscription update from portal: OFF (se gestiona desde Vantelia)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
