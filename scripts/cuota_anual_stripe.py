"""Cuota anual domiciliada (SEPA) de un cliente, con Stripe Billing.

Para negocios que pagan al ano y aceptan la domiciliacion (Cap Rocat, oct-2026). Stripe
cobra solo cada ano y manda la factura; si falla, avisa y reintenta.

    python scripts/cuota_anual_stripe.py alta-cliente caprocat --nombre "CAP ROCAT HOTEL SL" \
        --cif B57667099 --email oficina@caprocat.com --direccion "Carretera d'Enderrocat s/n" \
        --cp 07609 --ciudad "Cala Blava, Llucmajor" --provincia "Illes Balears"
    python scripts/cuota_anual_stripe.py enlace caprocat        # pagina para domiciliar (24 h, no cobra)
    python scripts/cuota_anual_stripe.py suscribir caprocat --primer-cobro 2026-10-20
    python scripts/cuota_anual_stripe.py estado caprocat

REGLAS (cada una evita un fallo concreto):
- Nada lleva metadata `cliente_id` ni `client_reference_id`: el webhook de Vantelia
  (routers/billing_web.py) los usa para CAMBIAR EL PLAN del tenant. El enlace con Stripe va
  en `metadata.vantelia_tenant`, que el webhook no lee.
- El precio anual ya lleva el IVA (tax_behavior=inclusive): la suscripcion lleva el tipo
  "IVA 21 %" incluido para que la factura lo desglose, y el NIF del emisor.
- `suscribir` exige un mandato SEPA ya firmado y no cobra hasta `--primer-cobro` (el dia
  que acaba la prueba): crear antes de tiempo seria cobrar durante la prueba gratuita.
La clave sale de STRIPE_SECRET_KEY (entorno o .env de la raiz).
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import httpx

API = "https://api.stripe.com/v1"
NIF_EMISOR = "02751906W"
PIE_FACTURA = ("Emisor: Pablo Sánchez Sánchez (Vantelia) · NIF 02751906W · Calle Garabay S/N, Portal 7, "
               "Planta 2, Puerta C, 28850 Torrejón de Ardoz (Madrid) · info@vantelia.es")
PRECIO_PRO_ANUAL_ENV = "STRIPE_PRICE_PRO_ANNUAL"
IVA_MARCA = "vantelia_iva_21_incluido"


def _clave() -> str:
    clave = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if not clave:
        env = pathlib.Path(__file__).resolve().parents[1] / ".env"
        for linea in env.read_text(encoding="utf-8").splitlines() if env.exists() else []:
            if linea.startswith("STRIPE_SECRET_KEY="):
                clave = linea.split("=", 1)[1].strip()
    if not clave:
        sys.exit("Falta STRIPE_SECRET_KEY.")
    return clave


def _valor_env(nombre: str) -> str:
    valor = os.environ.get(nombre, "").strip()
    env = pathlib.Path(__file__).resolve().parents[1] / ".env"
    if not valor and env.exists():
        for linea in env.read_text(encoding="utf-8").splitlines():
            if linea.startswith(nombre + "="):
                valor = linea.split("=", 1)[1].strip()
    return valor


class Stripe:
    def __init__(self, clave: str):
        self.h = {"Authorization": f"Bearer {clave}"}

    def __call__(self, metodo: str, ruta: str, **datos):
        if metodo == "GET":
            r = httpx.get(f"{API}/{ruta}", headers=self.h, params=datos or None, timeout=30)
        else:
            r = httpx.post(f"{API}/{ruta}", headers=self.h, data=datos or None, timeout=30)
        if r.status_code >= 300:
            sys.exit(f"Stripe {metodo} {ruta} -> {r.status_code}: {r.text[:500]}")
        return r.json()


def cliente_de(s: Stripe, tenant: str) -> dict:
    hallados = s("GET", "customers/search", query=f"metadata['vantelia_tenant']:'{tenant}'")["data"]
    if not hallados:
        sys.exit(f"No hay cliente de Stripe con vantelia_tenant={tenant}. Usa alta-cliente.")
    if len(hallados) > 1:
        sys.exit(f"Hay {len(hallados)} clientes con vantelia_tenant={tenant}: revisalo en Stripe.")
    return hallados[0]


def nif_emisor(s: Stripe) -> str:
    for t in s("GET", "tax_ids", **{"owner[type]": "self"})["data"]:
        if t["value"].upper() == NIF_EMISOR:
            return t["id"]
    return s("POST", "tax_ids", type="es_cif", value=NIF_EMISOR, **{"owner[type]": "self"})["id"]


def iva_21(s: Stripe) -> str:
    for t in s("GET", "tax_rates", active="true", limit="100")["data"]:
        if (t.get("metadata") or {}).get("marca") == IVA_MARCA:
            return t["id"]
    return s("POST", "tax_rates", display_name="IVA", percentage="21", inclusive="true", country="ES",
             jurisdiction="ES", description="IVA 21 % incluido en el precio",
             **{"metadata[marca]": IVA_MARCA})["id"]


def alta_cliente(s: Stripe, a) -> None:
    hallados = s("GET", "customers/search", query=f"metadata['vantelia_tenant']:'{a.tenant}'")["data"]
    if hallados:
        print("Ya existe:", hallados[0]["id"], hallados[0]["name"])
        return
    c = s("POST", "customers", **{
        "name": a.nombre, "email": a.email, "preferred_locales[0]": "es",
        "address[line1]": a.direccion, "address[postal_code]": a.cp, "address[city]": a.ciudad,
        "address[state]": a.provincia, "address[country]": "ES",
        "tax_id_data[0][type]": "es_cif", "tax_id_data[0][value]": a.cif,
        "invoice_settings[footer]": PIE_FACTURA, "metadata[vantelia_tenant]": a.tenant,
    })
    print("Cliente creado:", c["id"], c["name"])


def enlace(s: Stripe, a) -> None:
    c = cliente_de(s, a.tenant)
    ses = s("POST", "checkout/sessions", **{
        "mode": "setup", "currency": "eur", "customer": c["id"], "locale": "es",
        "payment_method_types[0]": "sepa_debit",
        "success_url": "https://www.vantelia.es/?domiciliacion=ok", "cancel_url": "https://www.vantelia.es/",
        "metadata[vantelia_tenant]": a.tenant, "metadata[proposito]": "domiciliacion_cuota_anual",
    })
    print("Pagina para domiciliar (caduca en 24 h, no cobra nada):")
    print(ses["url"])


def mandato_sepa(s: Stripe, cliente_id: str) -> str:
    metodos = s("GET", f"customers/{cliente_id}/payment_methods", type="sepa_debit")["data"]
    return metodos[0]["id"] if metodos else ""


def suscribir(s: Stripe, a) -> None:
    c = cliente_de(s, a.tenant)
    for sub in s("GET", "subscriptions", customer=c["id"], status="all")["data"]:
        if sub["status"] not in ("canceled", "incomplete_expired"):
            sys.exit(f"{a.tenant} ya tiene la suscripcion {sub['id']} ({sub['status']}). No se crea otra.")
    metodo = mandato_sepa(s, c["id"])
    if not metodo:
        sys.exit("Aun no han domiciliado (no hay mandato SEPA). Mandales el enlace primero.")
    dia = datetime.strptime(a.primer_cobro, "%Y-%m-%d").date()
    # A las 10:00 de Madrid del dia del primer cobro.
    momento = datetime.combine(dia, time(10, 0), ZoneInfo("Europe/Madrid")).astimezone(timezone.utc)
    if momento <= datetime.now(timezone.utc):
        sys.exit("La fecha del primer cobro tiene que ser futura.")
    precio = a.precio or _valor_env(PRECIO_PRO_ANUAL_ENV)
    if not precio:
        sys.exit(f"Falta el precio ({PRECIO_PRO_ANUAL_ENV} o --precio).")
    sub = s("POST", "subscriptions", **{
        "customer": c["id"],
        "items[0][price]": precio,
        "trial_end": str(int(momento.timestamp())),
        "collection_method": "charge_automatically",
        "default_payment_method": metodo,
        "payment_settings[payment_method_types][0]": "sepa_debit",
        "default_tax_rates[0]": iva_21(s),
        "invoice_settings[account_tax_ids][0]": nif_emisor(s),
        "metadata[vantelia_tenant]": a.tenant,
    })
    print(f"Suscripcion {sub['id']} ({sub['status']}): primer cobro el {dia:%d/%m/%Y} y cada ano despues.")


def estado(s: Stripe, a) -> None:
    c = cliente_de(s, a.tenant)
    print("Cliente:", c["id"], c["name"], c.get("email"))
    print("Mandato SEPA:", mandato_sepa(s, c["id"]) or "NO (falta que domicilien)")
    for sub in s("GET", "subscriptions", customer=c["id"], status="all")["data"]:
        fin = sub.get("trial_end") or sub.get("current_period_end")
        cuando = datetime.fromtimestamp(fin, timezone.utc).astimezone(ZoneInfo("Europe/Madrid")) if fin else None
        print(f"Suscripcion {sub['id']}: {sub['status']} · proximo cobro {cuando:%d/%m/%Y}" if cuando
              else f"Suscripcion {sub['id']}: {sub['status']}")
    print("NIF emisor en Stripe:", nif_emisor(s), "· IVA 21 %:", iva_21(s))


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sp = p.add_subparsers(dest="orden", required=True)
    al = sp.add_parser("alta-cliente")
    al.add_argument("tenant")
    for campo in ("nombre", "cif", "email", "direccion", "cp", "ciudad", "provincia"):
        al.add_argument(f"--{campo}", required=True)
    for orden in ("enlace", "estado"):
        sp.add_parser(orden).add_argument("tenant")
    su = sp.add_parser("suscribir")
    su.add_argument("tenant")
    su.add_argument("--primer-cobro", required=True, help="AAAA-MM-DD: el dia que acaba la prueba")
    su.add_argument("--precio", default="", help=f"price de Stripe (por defecto {PRECIO_PRO_ANUAL_ENV})")
    a = p.parse_args(argv)
    s = Stripe(_clave())
    {"alta-cliente": alta_cliente, "enlace": enlace, "suscribir": suscribir, "estado": estado}[a.orden](s, a)


if __name__ == "__main__":
    main()
