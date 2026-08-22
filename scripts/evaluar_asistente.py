# -*- coding: utf-8 -*-
"""Mide el asistente contra el banco de casos. Un numero, no una sensacion.

Los fallos aparecian de uno en uno, en casa del cliente, y cada arreglo era un
parche. Esto lo convierte en una tirada que se repite igual: si algo empeora se ve
aqui, con nombre y apellidos.

    python scripts/evaluar_asistente.py --cliente alicia_rincon_estilistas
    python scripts/evaluar_asistente.py --caso precio-mechas-sin-cifra
    python scripts/evaluar_asistente.py --db-copia /tmp/qa.db

Habla con el modelo de verdad (cuesta unos centimos) por el recorrido REAL de
WhatsApp. Con `--db-copia` las citas que cree caen en esa copia y no en la agenda
del negocio: uselo siempre contra un cliente vivo.

SALIDA: exit 1 si falla algun caso CRITICO. Los criticos son los que le cuestan
dinero o credibilidad al negocio (inventarse un precio, dar por hecha una cita que
no existe, negar un servicio que si hace).
"""
from __future__ import annotations

import argparse
import asyncio
import io
import os
import shutil
import sys
import unicodedata

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _norm(texto: str) -> str:
    limpio = unicodedata.normalize("NFKD", str(texto or "").lower())
    return "".join(c for c in limpio if not unicodedata.combining(c))


def _cargar_casos():
    from evals import casos_asistente

    return casos_asistente.CASOS


def _preparar_copia(origen: str, destino: str) -> None:
    """Trabajar sobre una copia: las citas de prueba no tocan la agenda real."""
    shutil.copyfile(origen, destino)
    os.environ["DB_PATH"] = destino


def _instalar_captura():
    """Sustituye los envios de WhatsApp y devuelve la lista donde caen."""
    from backend import messaging

    dichos = []

    async def texto(*, text="", **kwargs):
        dichos.append(text)
        return True

    async def lista(*, body="", sections=None, **kwargs):
        filas = [f["title"] for s in (sections or []) for f in s.get("rows", [])]
        dichos.append("%s || %s" % (body, " / ".join(filas)))
        return True

    async def botones(*, body="", **kwargs):
        dichos.append(body)
        return True

    async def cta(*, body="", **kwargs):
        dichos.append(body)
        return True

    messaging._send_whatsapp_text = texto
    messaging._send_whatsapp_list = lista
    messaging._send_whatsapp_buttons = botones
    messaging._send_whatsapp_cta_url = cta
    return dichos


def _ejecutar_caso(cliente_id: str, caso, dichos, indice: int):
    """Devuelve (paso, respuestas, motivo)."""
    from backend import whatsapp

    telefono = "34600%06d" % (990000 + indice)
    whatsapp._wa_clear_flow(cliente_id, telefono)
    marca = len(dichos)
    for mensaje in caso["mensajes"]:
        try:
            asyncio.run(whatsapp._handle_whatsapp_message(
                cliente_id=cliente_id, phone_number_id="phone_eval",
                from_number=telefono, incoming_text=mensaje,
                interactive_id="", request=None,
            ))
        except Exception as exc:  # noqa: BLE001
            whatsapp._wa_clear_flow(cliente_id, telefono)
            return False, [], "ha reventado: %r" % exc
    whatsapp._wa_clear_flow(cliente_id, telefono)

    respuestas = dichos[marca:]
    if caso.get("exige_respuesta") and not respuestas:
        return False, respuestas, "se ha quedado callada"
    # Se mira la ULTIMA respuesta y el conjunto: hay casos donde lo importante
    # esta en el cierre y otros donde vale que aparezca en cualquier momento.
    todo = _norm(" ".join(respuestas))
    ultimo = _norm(respuestas[-1]) if respuestas else ""

    debe = caso.get("debe") or []
    if debe and not any(_norm(p) in todo for p in debe):
        return False, respuestas, "no dice nada de %s" % debe

    for prohibido in caso.get("no_debe") or []:
        objetivo = ultimo if caso["id"] == "no-dar-la-cita-por-hecha" else todo
        if _norm(prohibido) in objetivo:
            return False, respuestas, "no deberia decir %r" % prohibido
    return True, respuestas, ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cliente", default="alicia_rincon_estilistas")
    parser.add_argument("--caso", default="", help="ejecutar solo este id")
    parser.add_argument("--db-copia", default="", help="copia la BD aqui y trabaja sobre ella")
    parser.add_argument("--db-origen", default="storage/vantelia.db")
    parser.add_argument("--detalle", action="store_true", help="imprime lo que contesta")
    args = parser.parse_args()

    if args.db_copia:
        _preparar_copia(args.db_origen, args.db_copia)

    casos = [c for c in _cargar_casos() if not args.caso or c["id"] == args.caso]
    if not casos:
        print("no hay ningun caso con ese id")
        return 2

    dichos = _instalar_captura()
    fallos = {"critico": [], "importante": [], "deseable": []}
    aciertos = 0

    for indice, caso in enumerate(casos):
        paso, respuestas, motivo = _ejecutar_caso(args.cliente, caso, dichos, indice)
        marca = "  OK  " if paso else "FALLA "
        print("%s [%-11s] %-34s" % (marca, caso["gravedad"], caso["id"]))
        if paso:
            aciertos += 1
        else:
            fallos[caso["gravedad"]].append((caso, motivo, respuestas))
            print("           %s" % motivo)
            print("           por que importa: %s" % caso.get("por_que", ""))
        if args.detalle and respuestas:
            for r in respuestas:
                print("           > %s" % r.replace("\n", " ")[:160])

    print("\n" + "=" * 68)
    print("  %d de %d" % (aciertos, len(casos)))
    for gravedad in ("critico", "importante", "deseable"):
        if fallos[gravedad]:
            print("  %s: %s" % (
                gravedad.upper(), ", ".join(c["id"] for c, _m, _r in fallos[gravedad])
            ))
    if fallos["critico"]:
        print("\n  HAY CRITICOS ROTOS: esto no se pone delante de un cliente.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
