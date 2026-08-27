# -*- coding: utf-8 -*-
"""Poner (o quitar) la fianza de un grupo de servicios de un negocio.

POR QUE EXISTE
--------------
La duenya del salon piloto pidio que sus alisados, permanentes y mechas llevaran
fianza. Son dieciseis servicios y hacerlo a mano en el panel, uno a uno, es una
tarde y una errata. Pero es un cambio que toca lo que se le COBRA a una clienta
real, asi que:

* no hace nada salvo que se diga `--aplicar` (por defecto solo ensena lo que
  haria),
* nunca pone una fianza mayor que el precio del servicio -seria cobrar de mas y
  devolver la diferencia-, y
* deja escrito el SQL para deshacerlo, con los valores que habia antes.

COMO SE USA
-----------
    # ver que tocaria, sin tocar nada
    python scripts/poner_fianza.py --cliente alicia_rincon_estilistas \
        --categorias Alisados,Moldeados --importe 20

    # ver los que casan por nombre
    python scripts/poner_fianza.py --cliente alicia_rincon_estilistas \
        --contiene mecha,balayage,grey --importe 20

    # hacerlo de verdad
    ... --aplicar
"""
from __future__ import annotations

import argparse
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _candidatos(conexion, cliente_id, categorias, contiene, incluir_con_fianza):
    filas = conexion.execute(
        "SELECT slug, name, category, price_cents, payment_type, payment_mode,"
        " deposit_amount_cents FROM services WHERE cliente_id=? AND is_active=1"
        " ORDER BY category, name",
        (cliente_id,),
    ).fetchall()
    salida = []
    for fila in filas:
        if not incluir_con_fianza and str(fila["payment_type"] or "") == "deposit":
            continue
        categoria = str(fila["category"] or "").strip().lower()
        nombre = str(fila["name"] or "").strip().lower()
        if categorias and categoria in [c.strip().lower() for c in categorias]:
            salida.append(fila)
        elif contiene and any(p.strip().lower() in nombre for p in contiene if p.strip()):
            salida.append(fila)
    return salida


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cliente", required=True)
    parser.add_argument("--categorias", default="", help="Alisados,Moldeados")
    parser.add_argument("--contiene", default="", help="mecha,balayage,grey")
    parser.add_argument("--importe", type=float, required=True, help="fianza en euros; 0 la quita")
    parser.add_argument("--minimo-precio", type=float, default=0.0,
                        help="no tocar servicios que cuesten menos que esto")
    parser.add_argument("--incluir-con-fianza", action="store_true",
                        help="tambien los que ya la tienen (para cambiarles el importe)")
    parser.add_argument("--aplicar", action="store_true", help="sin esto no escribe nada")
    parser.add_argument("--deshacer-en", default="storage/mediciones/fianza_deshacer.sql")
    args = parser.parse_args()

    from backend import db

    categorias = [c for c in args.categorias.split(",") if c.strip()]
    contiene = [c for c in args.contiene.split(",") if c.strip()]
    if not categorias and not contiene:
        print("Dime --categorias o --contiene: sin filtro no se toca un catalogo entero.")
        return 2

    importe_cents = int(round(args.importe * 100))
    minimo_cents = int(round(args.minimo_precio * 100))

    with db._get_db_connection() as conexion:
        filas = _candidatos(conexion, args.cliente, categorias, contiene,
                            args.incluir_con_fianza)
        if not filas:
            print("Ningun servicio encaja con ese filtro.")
            return 0

        tocan, saltan = [], []
        for fila in filas:
            precio = int(fila["price_cents"] or 0)
            if precio and precio < max(minimo_cents, importe_cents):
                saltan.append((fila, "cuesta %.2f y la fianza seria %.2f"
                               % (precio / 100.0, importe_cents / 100.0)))
                continue
            tocan.append(fila)

        print("Negocio: %s" % args.cliente)
        print("Fianza:  %.2f EUR%s" % (args.importe, "" if importe_cents else "  (SE QUITA)"))
        print()
        print("SE CAMBIAN (%d):" % len(tocan))
        for fila in tocan:
            print("   %-46s %7.2f  (antes: %s / %s)"
                  % (fila["name"], (fila["price_cents"] or 0) / 100.0,
                     fila["payment_type"], (fila["deposit_amount_cents"] or 0) / 100.0))
        if saltan:
            print()
            print("NO SE TOCAN (%d):" % len(saltan))
            for fila, motivo in saltan:
                print("   %-46s %s" % (fila["name"], motivo))

        if not args.aplicar:
            print()
            print("Ensayo: no se ha escrito nada. Anade --aplicar para hacerlo.")
            return 0

        os.makedirs(os.path.dirname(args.deshacer_en) or ".", exist_ok=True)
        with open(args.deshacer_en, "w", encoding="utf-8") as fichero:
            fichero.write("-- Para dejarlo como estaba antes de este cambio\n")
            for fila in tocan:
                fichero.write(
                    "UPDATE services SET payment_type=%r, payment_mode=%r,"
                    " deposit_amount_cents=%d WHERE cliente_id=%r AND slug=%r;\n"
                    % (str(fila["payment_type"] or "full"),
                       str(fila["payment_mode"] or "payment_disabled"),
                       int(fila["deposit_amount_cents"] or 0), args.cliente,
                       str(fila["slug"])))

        for fila in tocan:
            if importe_cents:
                conexion.execute(
                    "UPDATE services SET payment_type='deposit',"
                    " payment_mode='payment_required', deposit_amount_cents=?"
                    " WHERE cliente_id=? AND slug=?",
                    (importe_cents, args.cliente, fila["slug"]))
            else:
                conexion.execute(
                    "UPDATE services SET payment_type='full',"
                    " payment_mode='payment_disabled', deposit_amount_cents=0"
                    " WHERE cliente_id=? AND slug=?",
                    (args.cliente, fila["slug"]))
        conexion.commit()

    print()
    print("Hecho en %d servicios. Para deshacerlo: %s" % (len(tocan), args.deshacer_en))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
