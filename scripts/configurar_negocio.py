# -*- coding: utf-8 -*-
"""Deja el asistente de un negocio listo: tono, situaciones y estilo de reserva.

Sustituye a los scripts por cliente. Antes, cada negocio nuevo significaba escribir
un `reglas_<cliente>.py` a mano; ahora se describe lo que quiere en un fichero de
texto y esto lo aplica.

    python scripts/configurar_negocio.py --cliente mi_salon --perfil perfiles/mi_salon.json
    python scripts/configurar_negocio.py --cliente mi_salon --ver

El perfil es un JSON con lo que el negocio ha pedido:

    {
      "tono": {"estilo": "cercano", "emojis": "muchos", "tratamiento": "tu",
               "notas": "Llamales 'cariño'. Despidete con 😉🤗😘"},
      "reserva": "conversacional",
      "rescate": "Si no te encaja nada, llamanos al {telefono} 😊.",
      "situaciones": [
        {"id": "sin_precio_sin_verlo", "familias": ["mechas", "balayage"],
         "texto": "El precio depende de tu pelo: lo vemos en persona."},
        {"id": "pedir_foto", "familias": ["alisado"],
         "texto": "Mandanos una foto por detras y te decimos precio."}
      ]
    }

Solo `situaciones` es obligatorio; el resto se deja como este.

OJO: escribir el config NO cambia el proceso vivo. Tras aplicarlo hay que
reiniciar el contenedor, o hacerlo desde el panel, que actualiza las dos cosas.
"""
from __future__ import annotations

import argparse
import copy
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _ver(cliente_id: str) -> int:
    from backend import clients, playbooks, textnorm, whatsapp

    config = clients._get_client_config(cliente_id)
    print("NEGOCIO: %s" % (config.get("empresa") or config.get("nombre") or cliente_id))
    print("  reserva      : %s" % ("hablando" if whatsapp._wa_modo_conversacional(config)
                                   else "con listas"))
    tono = textnorm._tono_config(config) or {}
    print("  tono         : %s / emojis %s / %s" % (
        tono.get("estilo") or "-", tono.get("emojis") or "-", tono.get("tratamiento") or "-"))
    rescate = clients.call_us_line(cliente_id)
    print("  si no hay hueco: %s" % (rescate.strip().replace("\n", " ")[:70] or "(no ofrece llamar)"))
    print("\n  SITUACIONES:")
    for situacion in playbooks.estado(cliente_id):
        marca = "[x]" if situacion["activa"] else "[ ]"
        donde = (" · " + ", ".join(situacion["familias"])) if situacion["familias"] else ""
        print("   %s %-42s%s" % (marca, situacion["titulo"], donde))
    return 0


def _aplicar(cliente_id: str, perfil, seco: bool) -> int:
    import backend.appstate as appstate
    from backend import clients, playbooks

    situaciones = perfil.get("situaciones") or []
    if not situaciones:
        print("el perfil no trae ninguna situacion")
        return 2

    for situacion in situaciones:
        identificador = situacion.get("id", "")
        print("[%s] %-28s %s" % (
            "seco" if seco else "aplica", identificador,
            ", ".join(situacion.get("familias") or []) or "(cualquier servicio)"))
        if seco:
            continue
        try:
            playbooks.aplicar(
                cliente_id, identificador,
                familias=situacion.get("familias") or [],
                texto=situacion.get("texto", ""),
                activa=situacion.get("activa", True),
                nombre=situacion.get("nombre", ""),
            )
        except ValueError as exc:
            print("   !! %s" % exc)
            return 1

    cambia_config = any(k in perfil for k in ("tono", "reserva", "rescate"))
    if cambia_config and not seco:
        with appstate.state_lock:
            siguiente = copy.deepcopy(appstate.CONFIG_CLIENTES)
            config = siguiente.get(cliente_id)
            if config is None:
                print("no existe el negocio %s" % cliente_id)
                return 1
            if perfil.get("tono"):
                config["tono"] = dict(perfil["tono"])
            booking = dict(config.get("booking") or {})
            if perfil.get("reserva") in ("guiado", "conversacional"):
                booking["estilo"] = perfil["reserva"]
            if perfil.get("rescate"):
                booking["rescate_texto"] = perfil["rescate"]
            config["booking"] = booking
            siguiente[cliente_id] = config
            clients._update_runtime_configs(siguiente)
        clients._persist_configs_to_disk(siguiente)
        print("\nconfig guardado (reinicia el proceso para que lo lea)")

    print()
    return _ver(cliente_id)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cliente", required=True)
    parser.add_argument("--perfil", default="", help="JSON con lo que ha pedido el negocio")
    parser.add_argument("--ver", action="store_true", help="solo mostrar como esta")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.ver or not args.perfil:
        return _ver(args.cliente)
    with open(args.perfil, encoding="utf-8") as fichero:
        perfil = json.load(fichero)
    return _aplicar(args.cliente, perfil, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
