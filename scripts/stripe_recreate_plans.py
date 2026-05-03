"""Crea productos y precios nuevos para los planes Web/WhatsApp/Completo.

Lee STRIPE_SECRET_KEY desde .env, archiva precios anteriores que estén
en STRIPE_PRICE_* del .env, y crea nuevos productos + precios mensuales y
anuales. Imprime los nuevos Price IDs listos para pegar en .env.
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

    old_price_keys = [
        "STRIPE_PRICE_ESENCIAL",
        "STRIPE_PRICE_PRO",
        "STRIPE_PRICE_EMPRESA",
        "STRIPE_PRICE_ESENCIAL_ANNUAL",
        "STRIPE_PRICE_PRO_ANNUAL",
        "STRIPE_PRICE_EMPRESA_ANNUAL",
    ]
    for k in old_price_keys:
        old_id = env.get(k, "").strip()
        if not old_id:
            continue
        try:
            stripe.Price.modify(old_id, active=False)
            print(f"  archivado {k} ({old_id})")
        except Exception as exc:
            print(f"  WARN no se pudo archivar {k}={old_id}: {exc}")

    plans = [
        {
            "key": "web",
            "name": "Vantelia · Plan Web",
            "description": "Asistente IA en tu web (widget). 1 mes gratis.",
            "monthly_eur": 49,
            "annual_monthly_eur": 42,
        },
        {
            "key": "whatsapp",
            "name": "Vantelia · Plan WhatsApp",
            "description": "Asistente IA en WhatsApp Business. 1 mes gratis.",
            "monthly_eur": 79,
            "annual_monthly_eur": 67,
        },
        {
            "key": "completo",
            "name": "Vantelia · Plan Completo",
            "description": "Asistente IA en web + WhatsApp con un solo cerebro. 1 mes gratis.",
            "monthly_eur": 89,
            "annual_monthly_eur": 76,
        },
    ]

    out: dict[str, str] = {}
    for p in plans:
        product = stripe.Product.create(
            name=p["name"],
            description=p["description"],
            metadata={"plan": p["key"]},
        )
        print(f"  producto {p['key']} -> {product.id}")

        m = stripe.Price.create(
            product=product.id,
            currency="eur",
            unit_amount=p["monthly_eur"] * 100,
            recurring={"interval": "month"},
            nickname=f"{p['key']}-monthly",
            metadata={"plan": p["key"], "billing_period": "monthly"},
        )
        a_unit = p["annual_monthly_eur"] * 12 * 100
        a = stripe.Price.create(
            product=product.id,
            currency="eur",
            unit_amount=a_unit,
            recurring={"interval": "year"},
            nickname=f"{p['key']}-annual",
            metadata={"plan": p["key"], "billing_period": "annual"},
        )
        out[f"STRIPE_PRICE_{p['key'].upper()}"] = m.id
        out[f"STRIPE_PRICE_{p['key'].upper()}_ANNUAL"] = a.id
        print(f"    monthly  {m.id}  ({p['monthly_eur']}€/mes)")
        print(f"    annual   {a.id}  ({p['annual_monthly_eur']*12}€/año = {p['annual_monthly_eur']}€/mes)")

    print("\n=== Pega esto en .env ===")
    for k, v in out.items():
        print(f"{k}={v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
