# -*- coding: utf-8 -*-
"""Dos negocios con reglas OPUESTAS no se contaminan, con el modelo de verdad.

POR QUE EXISTE
--------------
Fase 3 del plan de consolidación (docs/PLAN_CONSOLIDACION_IA.md): «dos tenants con reglas
opuestas no se contaminan». Los tests prueban el mecanismo con la clasificación simulada; esto
lo mide con `intents.classify` de verdad. Primera medición el 14-sep-2026: 21/21.

Entorno aislado: config, datos y BD en una carpeta temporal que se borra al acabar, dos
negocios sintéticos sin datos de clientas y, del `.env` del repo, solo la clave del modelo
(nunca se imprime). Las credenciales de salida se VACÍAN antes de importar el backend
(`settings` hace load_dotenv y repondría las borradas) y SMTP/IMAP quedan bloqueados en el
proceso, como en tests/conftest.py. La misma pregunta de precio se hace intercalada a los dos:

- A contesta él mismo ("[A] ..."), B pasa a una persona ("[B] ...", `pasar_a_humano`).
- Se edita la regla de A: su siguiente respuesta es la nueva ("[A2]").
- Se borra la regla de B: B deja de responder con regla y NUNCA con la de A.

    python scripts/medir_reglas_opuestas.py --guardar informe.json

CUESTA DINERO (céntimos): unas veinte clasificaciones con el modelo. Sale con 1 si algún
intento falla.
"""
from __future__ import annotations

import argparse
import datetime
import importlib
import io
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
A, B = "medida_regla_a", "medida_regla_b"
CATALOGO = ("Servicios\n\nTinte raíz\nPrecio: 35 €\nDuración: 60 min\n\n"
            "Mechas\nPrecio: 80 €\nDuración: 120 min\n\nCorte señora\nPrecio: 25 €\nDuración: 30 min\n")
PREGUNTAS = ["¿Cuánto cuesta un tinte?", "q precio tienen las mechas", "cuanto vale cortarse el pelo?"]
# Las mismas que tests/conftest.py (sin la del modelo, que aquí sí hace falta) + Stripe y webhooks.
CREDENCIALES = (
    "SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM_EMAIL", "SMTP_REPLY_TO",
    "IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD",
    "OUTREACH_SMTP_HOST", "OUTREACH_SMTP_USERNAME", "OUTREACH_SMTP_PASSWORD", "OUTREACH_BCC",
    "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_DEFAULT_PHONE_NUMBER", "TWILIO_SMS_SENDER",
    "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_APP_SECRET",
    "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "WEBHOOK_DEFAULT",
)


def _bloquear_correo():
    import imaplib
    import smtplib

    def prohibido(*_args, **_kwargs):
        raise RuntimeError("medir_reglas_opuestas no manda ni lee correo")

    smtplib.SMTP = smtplib.SMTP_SSL = prohibido
    imaplib.IMAP4 = imaplib.IMAP4_SSL = prohibido


def _preparar_entorno(raiz):
    """Entorno aislado ANTES de importar el backend: `settings` lee las rutas al importar."""
    from dotenv import dotenv_values

    valores = dotenv_values(os.path.join(REPO, ".env"))
    if not valores.get("OPENAI_API_KEY"):
        raise SystemExit("sin OPENAI_API_KEY en el .env: no se mide")
    for clave in CREDENCIALES:
        os.environ[clave] = ""   # vacía, no borrada: load_dotenv no pisa lo que ya existe
    os.environ["OPENAI_API_KEY"] = valores["OPENAI_API_KEY"]
    if valores.get("CHAT_MODEL"):
        os.environ["CHAT_MODEL"] = valores["CHAT_MODEL"]
    _bloquear_correo()
    config = {}
    for cid, nombre in ((A, "Peluquería A"), (B, "Peluquería B")):
        os.makedirs(os.path.join(raiz, "data", cid), exist_ok=True)
        with open(os.path.join(raiz, "data", cid, "info.txt"), "w", encoding="utf-8") as f:
            f.write(CATALOGO)
        config[cid] = {"nombre": nombre, "empresa": nombre, "bienvenida": "Hola", "allowed_origins": [],
                       "booking": {"enabled": True, "timezone": "Europe/Madrid"},
                       "ai_intents": {"enabled": True}}
    os.makedirs(os.path.join(raiz, "storage"), exist_ok=True)
    with open(os.path.join(raiz, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    os.environ.update({
        "VANTELIA_DATA_DIR": os.path.join(raiz, "data"),
        "VANTELIA_STORAGE_DIR": os.path.join(raiz, "storage"),
        "VANTELIA_CONFIG_PATH": os.path.join(raiz, "config.json"),
        "ADMIN_API_TOKEN": "medida", "APP_BASE_URL": "https://medida.local",
    })
    return config


def medir(config, informe):
    sys.path.insert(0, REPO)
    os.chdir(REPO)
    importlib.import_module("api")   # carga el backend con el entorno aislado
    from backend import chat, rules, settings

    raiz = os.environ["VANTELIA_STORAGE_DIR"]
    if os.path.normcase(os.path.abspath(str(settings.DB_PATH))).find(os.path.normcase(os.path.abspath(raiz))) != 0:
        raise SystemExit("la BD no esta aislada: %s" % settings.DB_PATH)
    vivas = sorted(c for c in CREDENCIALES if os.environ.get(c))
    if vivas:
        raise SystemExit("credenciales de salida vivas tras importar el backend: %s" % vivas)
    informe["modelo"] = os.environ.get("CHAT_MODEL", "por defecto")

    regla_a = rules.guardar(A, nombre="Precio: lo decimos nosotros", intenciones=["precio", "presupuesto"],
                            accion="responder", texto="[A] En Peluquería A el precio te lo damos en el salón.")
    regla_b = rules.guardar(B, nombre="Precio: pasar a persona", intenciones=["precio", "presupuesto"],
                            accion="pasar_a_humano", texto="[B] Te paso con una persona del equipo para el precio.")

    def preguntar(cid, mensaje, fase, espera):
        decision = chat.decision_del_negocio(cid, mensaje, config=config[cid])
        texto = str((decision or {}).get("texto") or "")
        accion = (decision or {}).get("accion") or ""
        ok = espera(texto, accion)
        fila = {"fase": fase, "negocio": cid, "mensaje": mensaje, "accion": accion,
                "intencion": (decision or {}).get("intencion") or "", "texto": texto[:120], "ok": ok}
        informe["intentos"].append(fila)
        if not ok:
            informe["fallos"].append(fila)
        print("%-5s %-8s %s %-15s %s" % ("ok" if ok else "FALLA", fase, cid[-1:], accion, texto[:70]))

    def es_a(marca="[A]"):
        return lambda t, a: t.startswith(marca) and a == "responder"

    def es_b(t, a):
        return t.startswith("[B]") and a == "pasar_a_humano"

    for mensaje in PREGUNTAS:
        preguntar(A, mensaje, "opuestas", es_a())
        preguntar(B, mensaje, "opuestas", es_b)
        preguntar(A, mensaje, "opuestas", es_a())

    rules.guardar(A, regla_id=regla_a["id"], nombre="Precio: lo decimos nosotros",
                  intenciones=["precio", "presupuesto"], accion="responder",
                  texto="[A2] Ahora el precio te lo mandamos por escrito.")
    for mensaje in PREGUNTAS:
        preguntar(A, mensaje, "editada", es_a("[A2]"))
        preguntar(B, mensaje, "editada", es_b)

    rules.borrar(B, regla_b["id"])
    for mensaje in PREGUNTAS:
        preguntar(B, mensaje, "borrada", lambda t, a: not t.startswith("[A") and not t.startswith("[B]"))
        preguntar(A, mensaje, "borrada", es_a("[A2]"))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--guardar", default="", help="ruta del informe JSON")
    args = parser.parse_args()
    raiz = tempfile.mkdtemp(prefix="medida_reglas_")
    informe = {"inicio": datetime.datetime.now().isoformat(timespec="seconds"), "intentos": [], "fallos": []}
    try:
        config = _preparar_entorno(raiz)
        medir(config, informe)
    finally:
        informe["fin"] = datetime.datetime.now().isoformat(timespec="seconds")
        informe["resumen"] = {"intentos": len(informe["intentos"]), "fallos": len(informe["fallos"])}
        if args.guardar:
            with open(args.guardar, "w", encoding="utf-8") as f:
                json.dump(informe, f, ensure_ascii=False, indent=2)
        shutil.rmtree(raiz, ignore_errors=True)
        print("resumen", informe["resumen"], "| carpeta temporal borrada:", not os.path.exists(raiz))
    return 1 if informe["fallos"] or not informe["intentos"] else 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.exit(main())
