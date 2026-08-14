#!/usr/bin/env python3
"""Provisioning del tenant `caprocat` (Hotel Cap Rocat, Cala Blava, Mallorca).

El hotel NO quiere agenda ni chatbot conversacional complejo: quiere respuestas
automaticas por palabra clave en su WhatsApp ("spa"/"masaje" -> telefono del
hotel). Este script deja eso listo para que lo prueben:

- Usuario de portal (owner, plan pro: WhatsApp esta gateado a Pro).
- Reglas por palabra clave reales, ya cargadas y activas (backend/keywords.py).
- Q&A del asistente con la informacion publica de su web, por si el huesped
  pregunta algo que no cubre ninguna regla.

Idempotente: se puede relanzar. Reemplaza SUS reglas y Q&A; no toca otros
tenants. El tenant tiene que existir ya en config.json (ver docs/TENANTS_PROD.md).

Uso:
    python scripts/seed_caprocat.py
    python scripts/seed_caprocat.py --password "..."   # fija la del portal
    python scripts/seed_caprocat.py --purge            # solo limpiar
"""
from __future__ import annotations

import argparse
import secrets
import sqlite3
import string
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import api  # noqa: E402  (carga config/storage reales)
from backend import keywords, rag, security, settings  # noqa: E402

CID = "caprocat"
PORTAL_EMAIL = "reservas@caprocat.com"
PORTAL_NAME = "Cap Rocat"
TELEFONO = "(+34) 971 74 78 78"
EMAIL_HOTEL = "info@caprocat.com"

# Reglas de arranque. Son un PUNTO DE PARTIDA editable por el hotel desde el
# panel: los textos salen de su web y del ejemplo que pidieron por email.
REGLAS = [
    {
        "label": "Spa y tratamientos",
        "keywords": ["spa", "masaje", "hammam", "ayurveda", "tratamiento", "circuito", "wellness"],
        "reply": (
            "Para reservas o informacion sobre el Spa, por favor llame al "
            f"{TELEFONO} o escriba a {EMAIL_HOTEL}. "
            "Nuestro equipo le atendera y le propondra el tratamiento que mejor encaje con su estancia."
        ),
    },
    {
        "label": "Restaurantes y reservas de mesa",
        "keywords": ["restaurante", "cena", "cenar", "comer", "mesa", "menu", "carta",
                     "fortaleza", "sea club", "desayuno"],
        "reply": (
            "Cap Rocat cuenta con el restaurante La Fortaleza (cocina mallorquina de autor) y el "
            "Sea Club (cocina mediterranea junto al mar). Para reservar mesa o consultar la carta, "
            f"llame al {TELEFONO} o escriba a {EMAIL_HOTEL}."
        ),
    },
    {
        "label": "Reservas de alojamiento",
        "keywords": ["reserva", "reservar", "habitacion", "suite", "disponibilidad",
                     "noche", "alojamiento", "precio", "tarifa"],
        "reply": (
            "Para consultar disponibilidad y tarifas de alojamiento puede reservar en "
            "www.caprocat.com o contactar directamente con nosotros en "
            f"{TELEFONO} o {EMAIL_HOTEL}. Estaremos encantados de ayudarle."
        ),
    },
    {
        "label": "Check-in y check-out",
        "keywords": ["check in", "checkin", "check out", "checkout", "entrada", "salida",
                     "llegada", "equipaje"],
        "reply": (
            "Para cualquier gestion sobre su llegada, salida o equipaje, nuestro equipo de recepcion "
            f"le atiende en el {TELEFONO}. Si lo prefiere, escribanos a {EMAIL_HOTEL} y le respondemos."
        ),
    },
    {
        "label": "Como llegar y parking",
        "keywords": ["como llegar", "direccion", "ubicacion", "parking", "aparcar",
                     "taxi", "aeropuerto", "coche"],
        "reply": (
            "Cap Rocat se encuentra en la Ctra. d'Enderrocat, s/n, 07609 Cala Blava (Mallorca), "
            "a unos 25 minutos en coche de Palma y del aeropuerto. "
            f"Si necesita ayuda con traslados, llamenos al {TELEFONO}."
        ),
    },
    {
        "label": "Tarjetas regalo",
        "keywords": ["tarjeta regalo", "regalo", "regalar", "gift card", "bono regalo"],
        "reply": (
            "Puede regalar una experiencia Cap Rocat con nuestras tarjetas regalo, en formato digital "
            "o fisico: https://caprocat.com/regale-cap-rocat "
            f"Si prefiere que le acompanemos en la eleccion, llamenos al {TELEFONO}."
        ),
    },
    {
        "label": "Eventos, bodas y grupos",
        "keywords": ["evento", "boda", "celebracion", "grupo", "empresa", "privatizar",
                     "banquete"],
        "reply": (
            "Para eventos, celebraciones o reservas de grupo, nuestro equipo comercial preparara una "
            f"propuesta a medida. Escribanos a {EMAIL_HOTEL} o llame al {TELEFONO}."
        ),
    },
]

# Preguntas frecuentes con respuesta VERBATIM, por si el huesped pregunta algo
# que ninguna regla cubre. Solo informacion publicada en su web.
QA_PAIRS = [
    (
        "Donde esta el hotel",
        "Cap Rocat esta en la Ctra. d'Enderrocat, s/n, 07609 Cala Blava (Mallorca), en el extremo de "
        "una reserva natural con vistas a la Bahia de Palma, a unos 25 minutos en coche de Palma.",
    ),
    (
        "Que tipo de hotel es Cap Rocat",
        "Cap Rocat es un hotel boutique ubicado en una antigua fortaleza militar del siglo XIX, "
        "declarada Bien de Interes Cultural y Monumento Nacional. Su rehabilitacion recibio el Premio "
        "Europa Nostra y el Premio Hispania Nostra.",
    ),
    (
        "Que habitaciones tiene el hotel",
        "El hotel dispone de habitaciones Doble Fortaleza, Centinelas (en las antiguas garitas de "
        "vigilancia), Suite Cap Rocat, Suite El Cabo y Suite del Mar. Para disponibilidad y tarifas, "
        f"contacte con nosotros en el {TELEFONO}.",
    ),
    (
        "Como es el spa",
        "El Spa de Cap Rocat esta excavado a 12 metros bajo la roca, en el lugar mas protegido de la "
        "fortaleza, con piscina de agua salada e iluminacion natural, hammam y tratamientos ayurvedicos. "
        f"Para reservas e informacion, llame al {TELEFONO}.",
    ),
    (
        "Cual es el telefono del hotel",
        f"Puede contactar con nosotros en el {TELEFONO} o por email en {EMAIL_HOTEL}.",
    ),
]


def _random_password() -> str:
    alphabet = string.ascii_letters + string.digits
    return "CapRocat-" + "".join(secrets.choice(alphabet) for _ in range(10))


def purge() -> None:
    for rule in keywords.list_rules(CID):
        keywords.delete_rule(CID, rule["id"])
    with sqlite3.connect(api.DB_PATH) as conn:
        conn.execute("DELETE FROM kb_qa WHERE cliente_id=?", (CID,))
        conn.commit()
    print("- Reglas y Q&A previas eliminadas.")


def ensure_portal_user(password: str) -> str:
    """Crea la cuenta del hotel si no existe. Si ya existe, NO toca su contrasenya."""
    user = security._get_user_by_email(PORTAL_EMAIL)
    created = False
    if not user:
        user = security._create_user(
            email=PORTAL_EMAIL,
            password=password,
            role="client",
            display_name=PORTAL_NAME,
            cliente_id=CID,
            portal_role="owner",
        )
        created = True
    else:
        with sqlite3.connect(api.DB_PATH) as conn:
            conn.execute(
                "UPDATE users SET cliente_id=?, portal_role='owner', is_active=1 WHERE id=?",
                (CID, user["id"]),
            )
            conn.commit()
    api.db_set_client_owner(CID, user["id"], source="seed_caprocat")
    api.db_set_subscription_from_stripe(user_id=user["id"], plan_slug="pro", status="active")
    if created:
        print(f"- Cuenta creada: {PORTAL_EMAIL} / {password}  (owner, plan pro)")
    else:
        print(f"- Cuenta ya existente confirmada como owner del tenant: {PORTAL_EMAIL} (contrasenya intacta)")
    return user["id"]


def seed_rules(user_id: str) -> None:
    for position, rule in enumerate(REGLAS):
        keywords.create_rule(
            CID,
            label=rule["label"],
            keywords=rule["keywords"],
            reply=rule["reply"],
            match_mode="any",
            active=True,
            position=position,
            created_by_user_id=user_id,
        )
    print(f"- {len(REGLAS)} reglas por palabra clave creadas y activas.")


def seed_qa(user_id: str) -> None:
    info_path = settings.DATA_DIR / CID / "info.txt"
    info_txt = info_path.read_text(encoding="utf-8") if info_path.exists() else ""
    created = rag._autocreate_qa_from_info(CID, info_txt, user_id, explicit_pairs=QA_PAIRS)
    print(f"- {created} preguntas frecuentes cargadas.")


def check_config() -> None:
    if CID not in api.CONFIG_CLIENTES:
        print(f"ERROR: el tenant '{CID}' no existe en config.json.", file=sys.stderr)
        sys.exit(1)
    section = api.CONFIG_CLIENTES[CID].get(keywords.CONFIG_SECTION) or {}
    if not section.get("enabled"):
        print(
            "AVISO: config['keyword_rules']['enabled'] esta en false para este tenant: "
            "las reglas quedan cargadas pero NO se aplicaran hasta activarlo.",
            file=sys.stderr,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--purge", action="store_true", help="solo limpiar reglas y Q&A")
    parser.add_argument("--password", default="", help="contrasenya del portal si hay que crear la cuenta")
    args = parser.parse_args()

    check_config()
    purge()
    if args.purge:
        return
    password = args.password or _random_password()
    user_id = ensure_portal_user(password)
    seed_rules(user_id)
    seed_qa(user_id)
    print(f"\nListo. Panel: https://app.vantelia.es/acceso   Prueba del chat: https://app.vantelia.es/demo/{CID}")


if __name__ == "__main__":
    main()
