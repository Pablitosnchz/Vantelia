# -*- coding: utf-8 -*-
"""Las reglas del salon dejan de ser una instruccion del prompt y pasan a ser datos.

Estaban escritas dentro del `prompt_extra`: el modelo podia ignorarlas, no habia
forma de saber cuantas veces se aplicaban, y para cambiar una frase habia que
tocar la configuracion del tenant a mano. Ahora son filas de `business_rules`,
las ve el negocio en su panel y se ejecutan siempre.

Idempotente: se identifica cada regla por su nombre y se actualiza si ya existe.

    python scripts/reglas_alicia.py [--cliente alicia_rincon_estilistas] [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TELEFONO = "625 120 100"

REGLAS = [
    {
        "nombre": "Presupuesto de alisado: pedir foto",
        "intenciones": ["presupuesto", "precio"],
        "familias": ["alisado"],
        "accion": "pedir_foto",
        "prioridad": 10,
        "texto": (
            "¡Claro que sí, cariño! 😊 El alisado sí te lo podemos presupuestar por aquí, pero "
            "necesitamos ver cómo tienes el pelo: ¿nos mandas una foto por detrás, con el pelo "
            "suelto y a la luz natural?\n\n"
            "En cuanto la veamos nos ponemos en contacto contigo para darte el presupuesto "
            "personalmente 💛\n\n"
            "Y si lo que quieres es cogerte la cita directamente, dime cómo lo tienes de largo "
            "y te la busco sin más 😉"
        ),
    },
    {
        "nombre": "Extensiones: cita de valoracion",
        "intenciones": ["presupuesto", "precio", "info"],
        "familias": ["extensiones"],
        "accion": "ofrecer_cita",
        "prioridad": 20,
        "texto": (
            "¡Sí que ponemos extensiones, cariño! ✨ Todo depende de la cantidad que te pongamos, "
            "del largo y del color, así que esto es mejor verlo en persona: nosotras te aconsejamos "
            "qué necesitas y te damos el presupuesto sin compromiso.\n\n"
            "Te puedo coger una cita de diagnóstico para que te veamos y te digamos precio. "
            "¿Te busco hueco? 😊"
        ),
    },
    {
        # Ella lo dijo asi: "para precios de mechas, balay, jazz, Grey, Landing,
        # extensiones y cambios de color la IA no tiene que dar los precios".
        # Acotada a esas familias a proposito: su catalogo SI tiene precio cerrado
        # para corte, peinado o recogido, y taparlo seria un paso atras.
        "nombre": "Color y mechas: precio tras diagnostico",
        "intenciones": ["presupuesto", "precio"],
        "familias": ["mechas", "mecha", "balayage", "balay", "babylights", "jazz",
                     "grey", "grey blending", "landing", "color", "coloracion",
                     "cambio de color", "tinte", "decoloracion"],
        "accion": "ofrecer_cita",
        "prioridad": 50,
        "texto": (
            "Te lo digo con sinceridad, cariño: el precio depende mucho de tu pelo (el largo, "
            "el color que tengas de base y el resultado que busques), así que no queremos darte "
            "una cifra a ciegas 😊\n\n"
            "Lo que hacemos es cogerte una cita de 15 minutos para hacerte un diagnóstico y darte "
            "el presupuesto en persona, sin compromiso y sin ningún coste.\n\n"
            "¿Te busco un hueco para el diagnóstico, o prefieres llamarnos al " + TELEFONO + "?"
        ),
    },
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cliente", default="alicia_rincon_estilistas")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--activar", action="store_true",
        help="enciende config['ai_intents'] para ese tenant (requiere reiniciar el proceso)",
    )
    args = parser.parse_args()

    from backend import rules

    existentes = {r["nombre"]: r for r in rules.listar(args.cliente)}
    for datos in REGLAS:
        previa = existentes.get(datos["nombre"])
        accion = "actualiza" if previa else "crea"
        print("[%s] %s -> %s" % (accion, datos["nombre"], datos["accion"]))
        if args.dry_run:
            continue
        rules.guardar(
            args.cliente,
            regla_id=previa["id"] if previa else "",
            nombre=datos["nombre"],
            intenciones=datos["intenciones"],
            familias=datos.get("familias", []),
            accion=datos["accion"],
            texto=datos["texto"],
            prioridad=datos["prioridad"],
            activa=True,
        )

    # El tono que pidio el salon, como configuracion y no dentro del prompt.
    TONO = {
        "estilo": "cercano",
        "emojis": "muchos",
        "tratamiento": "tu",
        "notas": (
            "Dirigete a quien te escribe como 'cariño' ('hola cariño, muy buenas'): "
            "vale igual para mujer y para hombre. Tambien puedes usar 'guapa' o "
            "'preciosa' cuando sepas que es una mujer. "
            "Cuando te despidas al cerrar la conversacion, termina siempre con estos "
            "tres emoticonos juntos: 😉🤗😘"
        ),
    }

    if args.activar and not args.dry_run:
        import copy

        from backend import appstate, clients

        with appstate.state_lock:
            siguiente = copy.deepcopy(appstate.CONFIG_CLIENTES)
            cfg = siguiente.get(args.cliente)
            if cfg is None:
                print("no existe el tenant %s" % args.cliente)
                return 1
            seccion = dict(cfg.get("ai_intents", {}) or {})
            seccion["enabled"] = True
            cfg["ai_intents"] = seccion
            cfg["tono"] = dict(TONO)
            # Sin listas: la IA guia la conversacion, como pidio el salon.
            reserva = dict(cfg.get("booking") or {})
            reserva["estilo"] = "conversacional"
            reserva["rescate_texto"] = (
                "Si ninguna de estas opciones te encaja, puedes llamarnos al {telefono} 😊. "
                "En ocasiones podemos revisar personalmente la agenda e intentar encontrar "
                "alguna alternativa. Estaremos encantadas de ayudarte."
            )
            cfg["booking"] = reserva
            siguiente[args.cliente] = cfg
            clients._update_runtime_configs(siguiente)
        clients._persist_configs_to_disk(siguiente)
        print("comprension ACTIVADA y tono aplicado en %s (reinicia el proceso)" % args.cliente)

    if not args.dry_run:
        print("\nreglas del salon:")
        for regla in rules.listar(args.cliente):
            print("  %3d  %-45s %s" % (regla["prioridad"], regla["nombre"], regla["accion"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
