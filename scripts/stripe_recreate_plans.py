"""Crea productos y precios nuevos para los planes Starter/Pro/Business.

Lee STRIPE_SECRET_KEY desde .env, archiva precios anteriores que estén
en STRIPE_PRICE_* del .env, y crea nuevos productos + precios mensuales y
anuales. Imprime los nuevos Price IDs listos para pegar en .env.
"""
from __future__ import annotations

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
        "STRIPE_PRICE_WEB",
        "STRIPE_PRICE_PRO",
        "STRIPE_PRICE_WHATSAPP",
        "STRIPE_PRICE_EMPRESA",
        "STRIPE_PRICE_COMPLETO",
        "STRIPE_PRICE_ESENCIAL_ANNUAL",
        "STRIPE_PRICE_WEB_ANNUAL",
        "STRIPE_PRICE_PRO_ANNUAL",
        "STRIPE_PRICE_WHATSAPP_ANNUAL",
        "STRIPE_PRICE_EMPRESA_ANNUAL",
        "STRIPE_PRICE_COMPLETO_ANNUAL",
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
            "key": "starter",
            "name": "Vantelia · Starter",
            "description": "Asistente IA con leads, documentos y marca personalizada.",
            "monthly_eur": 19,
            "annual_eur": 190,
        },
        {
            "key": "pro",
            "name": "Vantelia · Pro",
            "description": "Asistente IA con reservas, agenda integrada y Live Chat.",
            "monthly_eur": 49,
            "annual_eur": 490,
        },
        {
            "key": "business",
            "name": "Vantelia · Business",
            "description": "Asistente IA omnicanal con WhatsApp, integraciones y alto volumen.",
            "monthly_eur": 149,
            "annual_eur": 1490,
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
        a_unit = p["annual_eur"] * 100
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
        print(f"    annual   {a.id}  ({p['annual_eur']}€/año)")

    print("\n=== Pega esto en .env ===")
    for k, v in out.items():
        print(f"{k}={v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
