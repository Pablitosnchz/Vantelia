"""Asigna las imagenes oficiales de thenookmadrid.com al catalogo del tenant
`thenook` (servicios + bonos) via la API del portal.

- Descarga cada imagen de su web UNA vez, la sube al servidor destino
  (POST /auth/app/uploads/image, self-host) y cachea origen->url_destino.
- Elige imagen por tipo de masaje/ritual a partir del nombre.
- PATCH servicios (/auth/services/{slug}) y POST bonos (/auth/packages/{id}).

Uso:
  python scripts/set_thenook_catalog_images.py --base https://app.vantelia.es \
      --email admin@... --password '...' [--commit]

Sin --commit hace dry-run (no escribe). Las credenciales tambien se leen de
PORTAL_ADMIN_EMAIL / PORTAL_ADMIN_PASSWORD del entorno o .env si no se pasan.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

import requests

CID = "thenook"
UP = "https://www.thenookmadrid.com/wp-content/uploads"

# Imagen canonica (full-size) por tipo.
IMAGES = {
    "descontracturante": f"{UP}/2022/12/masaje-descontractuante.jpg",
    "relajante":         f"{UP}/2022/12/masaje-relajante.jpg",
    "deportivo":         f"{UP}/2022/12/MASAJE-DEPORTIVO.jpg",
    "drenaje":           f"{UP}/2022/12/fw-muscular-therapy-lympahic-drainage-massage.jpg",
    "piedras":           f"{UP}/2022/12/Captura-de-pantalla-2022-10-13-a-las-18.59.03-1024x520.webp",
    "piernas":           f"{UP}/2023/01/piernas_cansadas_1200.jpg",
    "embarazadas":       f"{UP}/2022/12/masaje-embarazo.jpg",
    "reflexologia":      f"{UP}/2022/12/Reflexologia-podal.jpg",
    "cuatromanos":       f"{UP}/2022/12/Captura-de-pantalla-2022-10-17-a-las-10.25.22.webp",
    "pareja":            f"{UP}/2022/12/Fotolia_24754819_Subscription_XXL.png",
    "antiestres":        f"{UP}/2022/12/antiestres.jpg",
    "shiatsu":           f"{UP}/2022/12/shiatsu.jpg",
    "kobido":            f"{UP}/2022/12/kobido.jpg",
    "beauty":            f"{UP}/2022/12/ritual_beauty.jpg",
    "energizante":       f"{UP}/2022/12/ritual_energizante.png",
    "sakura":            f"{UP}/2022/12/ritual_sakura.jpg",
    "romantico":         f"{UP}/2022/12/ritual_esencias_florales.jpg",
}

# Orden: tecnica especifica primero; pareja/dos personas como fallback generico.
RULES = [
    ("cuatromanos",   ["cuatro manos"]),
    ("piernas",       ["piernas cansadas"]),
    ("embarazadas",   ["futura mam", "embaraz"]),
    ("reflexologia",  ["reflexolog"]),
    ("drenaje",       ["drenaje"]),
    ("piedras",       ["piedras", "bamb"]),
    ("shiatsu",       ["shiatsu"]),
    ("deportivo",     ["anticelul", "reductor", "deportivo"]),
    ("kobido",        ["kobido"]),
    ("beauty",        ["beauty"]),
    ("energizante",   ["energizante"]),
    ("sakura",        ["sakura"]),
    ("romantico",     ["romantic", "romántic", "rom_ntic"]),
    ("antiestres",    ["antiestr"]),
    ("descontracturante", ["descontracturante"]),
    ("relajante",     ["relajante", "extra largo", "90 min", "90 minutos"]),
    ("pareja",        ["dos personas", "para dos", "pareja"]),
]


def pick(name: str) -> str:
    low = name.lower()
    for key, kws in RULES:
        if any(k in low for k in kws):
            return key
    return "relajante"


def login(base: str, email: str, password: str) -> requests.Session:
    s = requests.Session()
    r = s.post(f"{base}/auth/login", json={"email": email, "password": password}, timeout=20)
    if not r.ok:
        raise SystemExit(f"Login fallo: {r.status_code} {r.text[:160]}")
    m = re.search(r"vantelia_portal_session=([^;]+)", r.headers.get("set-cookie", ""))
    if not m:
        raise SystemExit("Login sin cookie de sesion.")
    host = re.sub(r"^https?://", "", base).split("/")[0].split(":")[0]
    s.cookies.set("vantelia_portal_session", m.group(1), domain=host)
    return s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.getenv("APP_BASE_URL", "https://app.vantelia.es"))
    ap.add_argument("--email", default=os.getenv("PORTAL_ADMIN_EMAIL", ""))
    ap.add_argument("--password", default=os.getenv("PORTAL_ADMIN_PASSWORD", ""))
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    if not args.email or not args.password:
        raise SystemExit("Faltan credenciales (--email/--password o env).")

    s = login(base, args.email, args.password)
    q = f"?cliente_id={CID}"

    services = s.get(f"{base}/auth/services{q}", timeout=20).json().get("items", [])
    packages = s.get(f"{base}/auth/packages{q}", timeout=20).json().get("items", [])
    print(f"servicios={len(services)} bonos={len(packages)} commit={args.commit}")

    cache: dict = {}

    def hosted_url(src: str) -> str:
        if src in cache:
            return cache[src]
        img = requests.get(src, timeout=30)
        img.raise_for_status()
        fname = src.rsplit("/", 1)[-1]
        up = s.post(f"{base}/auth/app/uploads/image",
                    files={"file": (fname, img.content, "application/octet-stream")},
                    data={"cliente_id": CID}, timeout=30)
        if not up.ok:
            raise SystemExit(f"Upload fallo {src}: {up.status_code} {up.text[:160]}")
        url = up.json()["url"]
        cache[src] = url
        return url

    # Servicios
    for svc in services:
        if not svc.get("is_active"):
            continue
        key = pick(svc["nombre"])
        src = IMAGES[key]
        print(f"  SVC {svc['id']:44} -> {key}")
        if args.commit:
            url = hosted_url(src)
            r = s.patch(f"{base}/auth/services/{svc['id']}{q}", json={"image_url": url}, timeout=20)
            if not r.ok:
                print(f"    ! patch fallo {r.status_code} {r.text[:120]}")

    # Bonos (POST update con payload completo + image_url)
    for p in packages:
        if not p.get("is_active"):
            continue
        key = pick(p["name"])
        src = IMAGES[key]
        print(f"  BONO {p['id']:40} -> {key}")
        if args.commit:
            url = hosted_url(src)
            payload = {
                "name": p["name"], "description": p.get("description", ""),
                "items": p.get("items", []), "price_cents": int(p["price_cents"]),
                "validity_days": int(p.get("validity_days", 365)),
                "is_active": bool(p["is_active"]), "image_url": url,
            }
            r = s.post(f"{base}/auth/packages/{p['id']}{q}", json=payload, timeout=20)
            if not r.ok:
                print(f"    ! update fallo {r.status_code} {r.text[:120]}")

    print(f"imagenes unicas subidas: {len(cache)}")
    if not args.commit:
        print("[DRY RUN] usa --commit para escribir.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
