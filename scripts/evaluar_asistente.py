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
import pathlib
import re
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
    """Trabajar sobre una copia: las citas de prueba no tocan la agenda real.

    OJO: `settings.DB_PATH` se calcula al IMPORTAR y no lee la variable de entorno,
    asi que exportar DB_PATH no aislaba nada. Costo siete citas de prueba metidas en
    la agenda de un salon real. Hay que reapuntar el modulo, y despues comprobarlo.
    """
    import sqlite3

    from backend import settings

    # Con `shutil.copyfile` la copia sale DESFASADA: SQLite en modo WAL guarda los
    # ultimos cambios en un fichero aparte (-wal) que no se copia, asi que la copia
    # traia citas ya borradas y el dedup las daba por vivas. `backup()` consolida.
    for sufijo in ("", "-wal", "-shm"):
        try:
            os.remove(destino + sufijo)
        except OSError:
            pass
    origen_db = sqlite3.connect(origen)
    destino_db = sqlite3.connect(destino)
    with destino_db:
        origen_db.backup(destino_db)
    origen_db.close()
    destino_db.close()
    os.environ["DB_PATH"] = destino
    settings.DB_PATH = pathlib.Path(destino)


def _comprobar_aislamiento(destino: str) -> None:
    """Se niega a seguir si las escrituras irian a la base de datos de verdad."""
    from backend import db, settings

    efectiva = str(settings.DB_PATH)
    if os.path.abspath(efectiva) != os.path.abspath(destino):
        raise SystemExit(
            "NO se esta usando la copia (%s), sino %s. Se aborta para no tocar la "
            "agenda del negocio." % (destino, efectiva)
        )
    with db._get_db_connection() as conexion:
        fichero = conexion.execute("PRAGMA database_list").fetchone()[2]
    if os.path.abspath(fichero) != os.path.abspath(destino):
        raise SystemExit(
            "las conexiones siguen abriendo %s. Se aborta." % fichero
        )


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


def _citas_del_telefono(cliente_id: str, telefono: str):
    """Las citas vivas de ese telefono. Sirve para mirar la AGENDA, no el texto."""
    from backend import db

    with db._get_db_connection() as conexion:
        filas = conexion.execute(
            "SELECT booking_code, status, booking_date, booking_time FROM bookings"
            " WHERE cliente_id=? AND REPLACE(REPLACE(telefono,' ',''),'+','') LIKE ?"
            " ORDER BY created_at", (cliente_id, "%" + telefono[-9:]),
        ).fetchall()
    return [dict(f) for f in filas]


def _preparar_cita(cliente_id: str, telefono: str, indice: int = 0):
    """Le deja una cita ya cogida, para poder probar cancelar y reprogramar.

    Cada caso coge un dia distinto y el ULTIMO hueco: los casos comparten la copia
    de la agenda y, cogiendo todos el primer hueco libre, se quitaban el sitio unos
    a otros y fallaban por colision, no por el asistente.

    Se crea por el nucleo de siempre (`_create_booking_core`), no a mano: si eso se
    rompe, el caso falla al prepararlo, que tambien es informacion.
    """
    from backend import agenda, booking, db, timeutils

    hoy = timeutils._utc_now().date()
    with db._get_db_connection() as conexion:
        empleados = conexion.execute(
            "SELECT * FROM employees WHERE cliente_id=? AND is_active=1 LIMIT 1",
            (cliente_id,),
        ).fetchall()
    if not empleados:
        return None
    servicios = booking._public_services_for_booking(cliente_id)
    servicio = servicios[0]["nombre"] if servicios else ""
    for salto in range(21):
        dia = hoy + __import__("datetime").timedelta(days=2 + salto)
        fecha = dia.isoformat()
        huecos = asyncio.run(agenda._available_slots_for_day(cliente_id, fecha)) or []
        if not huecos:
            continue
        # Empezando por el final y desplazado por caso: asi dos casos no pelean por
        # el mismo hueco (y ninguno le quita el primero al que reserva hablando).
        orden = list(reversed(huecos))
        orden = orden[(indice * 2) % len(orden):] + orden[:(indice * 2) % len(orden)]
        for hora in orden:
            try:
                fila = asyncio.run(booking._create_booking_core(
                    cliente_id, employee_row=empleados[0], nombre="Prueba Eval",
                    email="", telefono=telefono, servicio=servicio,
                    booking_date=fecha, booking_time=hora, notas="",
                    source="eval", send_confirmation=False,
                ))
                return dict(fila)
            except Exception:  # noqa: BLE001
                continue
    return None


def _ejecutar_caso(cliente_id: str, caso, dichos, indice: int):
    """Devuelve (paso, respuestas, motivo)."""
    from backend import whatsapp

    telefono = "34600%06d" % (990000 + indice)
    whatsapp._wa_clear_flow(cliente_id, telefono)
    marca = len(dichos)

    # Casos que necesitan una cita ya cogida (cancelar, cambiar de hora).
    previa = _preparar_cita(cliente_id, telefono, indice) if caso.get("con_cita") else None
    if caso.get("con_cita") and not previa:
        return False, [], "no se ha podido dejar una cita para probar"
    antes = _citas_del_telefono(cliente_id, telefono)

    mensajes = [m.replace("{codigo}", (previa or {}).get("booking_code", ""))
                for m in caso["mensajes"]]
    for mensaje in mensajes:
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

    # Lo que cuenta de una reserva no es lo que diga, es lo que quede en la agenda.
    exigido = caso.get("agenda")
    if exigido:
        despues = _citas_del_telefono(cliente_id, telefono)
        vivas = [c for c in despues if c["status"] in ("confirmed", "pending_review")]
        nuevas = len(despues) - len(antes)
        if exigido == "crea" and nuevas < 1:
            return False, respuestas, "no ha quedado ninguna cita en la agenda"
        if exigido == "no_crea" and nuevas > 0:
            return False, respuestas, "ha cogido una cita que nadie confirmo"
        if exigido == "cancela" and vivas:
            return False, respuestas, "la cita sigue viva: %s" % vivas
        if exigido == "cambia":
            # Mover no es duplicar: llego a crear una SEGUNDA cita y "reprogramar"
            # la original a su propio sitio. Con solo mirar si habia alguna en otra
            # fecha, eso pasaba por bueno.
            if len(vivas) != 1:
                return False, respuestas, (
                    "tiene que quedar UNA cita viva y hay %d: %s" % (
                        len(vivas), [(c["booking_date"], c["booking_time"]) for c in vivas])
                )
            movidas = [c for c in vivas
                       if (c["booking_date"], c["booking_time"])
                       != ((previa or {}).get("booking_date"), (previa or {}).get("booking_time"))]
            if not movidas:
                return False, respuestas, "la cita no se ha movido de sitio"
    # Se mira la ULTIMA respuesta y el conjunto: hay casos donde lo importante
    # esta en el cierre y otros donde vale que aparezca en cualquier momento.
    todo = _norm(" ".join(respuestas))
    ultimo = _norm(respuestas[-1]) if respuestas else ""

    # Hay cosas que no se pueden medir por vocabulario: el modelo dice "¿que te
    # parece el martes?" o "¿cuando te viene bien?" y las dos valen. Lo que si es
    # objetivo es si le ha soltado un puñado de horas.
    if caso.get("sin_horas"):
        horas = set(re.findall(r"\d{1,2}[:.]\d{2}", " ".join(respuestas)))
        if len(horas) >= 2:
            return False, respuestas, "ofrece horas (%s) sin saber que dia quiere" % sorted(horas)[:4]

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
        _comprobar_aislamiento(args.db_copia)
    elif any(c.get("agenda") or c.get("con_cita") for c in _cargar_casos()):
        # Hay casos que RESERVAN de verdad. Sin copia irian a la agenda del negocio.
        print("Estos casos crean y cancelan citas: usa --db-copia /tmp/eval.db")
        return 2

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
