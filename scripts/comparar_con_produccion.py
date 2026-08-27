# -*- coding: utf-8 -*-
"""Comparar la copia local con PRODUCCION antes de medir o de dar algo por bueno.

POR QUE EXISTE
--------------
Dos veces en el mismo dia se perdieron horas persiguiendo fallos que no existian,
las dos por lo mismo: la copia local no era como produccion.

* `booking.estilo` no estaba en conversacional, asi que la tirada contestaba con el
  RAG generico -"llama al salon"- y los casos salian OK sin ejercitar ni una linea
  de lo que se estaba probando: aprobados falsos.
* `mostrar_precios` no estaba puesto, asi que el asistente daba precios porque asi
  estaba configurado, y dos casos CRITICOS salian rojos sin haber nada roto.

Medir contra una configuracion que no es la del cliente no mide su producto.

COMO SE USA
-----------
    # 1) en el servidor (dentro del contenedor):
    python scripts/comparar_con_produccion.py --exportar --cliente CLIENTE > prod.json

    # 2) en local, con ese fichero:
    python scripts/comparar_con_produccion.py --cliente CLIENTE --contra prod.json

Sale con codigo 1 si hay diferencias que cambian el COMPORTAMIENTO, para poder
ponerlo delante de una medicion y que no arranque a ciegas.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Lo que cambia lo que el asistente CONTESTA. No es la config entera a proposito:
# comparar todo llena la pantalla de ruido (tokens, urls, contadores) y lo
# importante se pierde.
AJUSTES_QUE_MANDAN = (
    ("booking", "estilo"),
    ("booking", "mostrar_precios"),
    ("booking", "preferir_packs"),
    ("booking", "recargo_pct"),
    ("booking", "rescate_enabled"),
    ("booking", "enabled"),
    ("booking", "timezone"),
    ("ai_intents", "enabled"),
    ("keyword_rules", "enabled"),
    ("chat_menu", "enabled"),
    ("reviews", "enabled"),
)


def _retrato(cliente_id: str) -> dict:
    """Lo que hay que comparar, sacado de donde se este ejecutando."""
    from backend import clients, db

    config = clients._get_client_config(cliente_id) or {}
    ajustes = {}
    for seccion, clave in AJUSTES_QUE_MANDAN:
        ajustes["%s.%s" % (seccion, clave)] = (config.get(seccion) or {}).get(clave)

    with db._get_db_connection() as conexion:
        servicios = conexion.execute(
            "SELECT COUNT(*) FROM services WHERE cliente_id=? AND is_active=1",
            (cliente_id,)).fetchone()[0]
        con_fianza = conexion.execute(
            "SELECT COUNT(*) FROM services WHERE cliente_id=? AND is_active=1"
            " AND payment_type='deposit'", (cliente_id,)).fetchone()[0]
        empleados = conexion.execute(
            "SELECT COUNT(*) FROM employees WHERE cliente_id=? AND is_active=1",
            (cliente_id,)).fetchone()[0]
        reglas = conexion.execute(
            "SELECT COUNT(*) FROM business_rules WHERE cliente_id=? AND activa=1",
            (cliente_id,)).fetchone()[0]
        qa = conexion.execute(
            "SELECT COUNT(*) FROM kb_qa WHERE cliente_id=?", (cliente_id,)).fetchone()[0]
    return {
        "cliente_id": cliente_id,
        "ajustes": ajustes,
        "catalogo": {"servicios_activos": servicios, "con_fianza": con_fianza,
                     "empleados_activos": empleados, "reglas_activas": reglas,
                     "preguntas_qa": qa},
    }


def _comparar(local: dict, produccion: dict) -> list:
    diferencias = []
    for clave in sorted(set(local["ajustes"]) | set(produccion["ajustes"])):
        aqui = local["ajustes"].get(clave)
        alli = produccion["ajustes"].get(clave)
        if aqui != alli:
            diferencias.append(("ajuste", clave, aqui, alli))
    for clave in sorted(set(local["catalogo"]) | set(produccion["catalogo"])):
        aqui = local["catalogo"].get(clave)
        alli = produccion["catalogo"].get(clave)
        if aqui != alli:
            diferencias.append(("datos", clave, aqui, alli))
    return diferencias


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cliente", required=True)
    parser.add_argument("--exportar", action="store_true",
                        help="imprime el retrato de DONDE se ejecuta (usar en el servidor)")
    parser.add_argument("--contra", default="", help="fichero con el retrato de produccion")
    args = parser.parse_args()

    if args.exportar:
        print(json.dumps(_retrato(args.cliente), ensure_ascii=False, indent=2))
        return 0

    if not args.contra or not os.path.exists(args.contra):
        print("Dime --contra con el retrato de produccion (o usa --exportar en el servidor).")
        return 2

    with open(args.contra, encoding="utf-8") as fichero:
        produccion = json.load(fichero)
    local = _retrato(args.cliente)

    diferencias = _comparar(local, produccion)
    print("Cliente: %s" % args.cliente)
    print()
    if not diferencias:
        print("  Local y produccion coinciden en todo lo que cambia el comportamiento.")
        return 0

    print("  %d DIFERENCIA(S). Medir asi mide otro producto:" % len(diferencias))
    print()
    print("  %-10s %-28s %-16s %s" % ("", "que", "local", "produccion"))
    for tipo, clave, aqui, alli in diferencias:
        print("  %-10s %-28s %-16s %s" % (tipo, clave, repr(aqui), repr(alli)))
    print()
    print("  Los AJUSTES se alinean en config.json; los DATOS son del catalogo del")
    print("  cliente y casi nunca conviene copiarlos: lo que hay que saber es que")
    print("  no son los mismos.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
