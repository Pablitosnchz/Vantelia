# -*- coding: utf-8 -*-
"""Cinco conversaciones enteras antes de dar un despliegue por bueno.

POR QUE EXISTE
--------------
El 26 de agosto de 2026 meti DOS regresiones en produccion en la misma tarde:

* un freno nuevo rechazaba una hora que el propio asistente acababa de ofrecer
  ("vale, la primera opcion que me has dicho" -> "no puedo mover tu cita a la hora
  que te he ofrecido"), y
* al separar "Mechas o balayage" en dos opciones, elegir "mechas" dejo de resolver
  nada y la conversacion entraba en bucle.

Las dos pasaron los 1.373 tests. Y es logico: esos tests comprueban el MECANISMO
-"¿salta el detector con esta frase?"- y en los dos casos el detector saltaba
perfectamente. Lo que se rompio fue el CAMINO: la clienta no acababa con su cita.

Esto comprueba lo otro. Cinco conversaciones de principio a fin por el recorrido
REAL de WhatsApp, y se exige el resultado en la AGENDA, no lo que diga el texto.

QUE MIRA
--------
1. El resultado: ¿acabo habiendo cita? ¿se cancelo? ¿se movio -y no se duplico-?
   ¿a quien pregunto el precio se le cogio el diagnostico y no el tratamiento?
2. La traza: si una herramienta se llama tres veces sin que la conversacion
   avance, eso es un BUCLE, y falla aunque el resultado final salga bien. Asi se
   caza el fallo antes de que se lleve una cita por delante.

COMO SE USA
-----------
    python scripts/humo.py --cliente alicia_rincon_estilistas

Sale con codigo 1 si algo falla, para que el despliegue se pueda parar solo.
Trabaja SIEMPRE sobre una copia de la base de datos: no toca la agenda de nadie.

CUESTA DINERO (unos centimos) porque habla con el modelo de verdad. Ese es el
punto: un humo que no llame al modelo no habria pillado ninguna de las dos.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import os
import sys
from typing import Any, Dict, List

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Un telefono por caso: asi cada conversacion tiene su agenda y no se pisan.
TELEFONO_BASE = 34600900000

# Cuantas veces puede llamarse a la MISMA herramienta antes de que eso sea un
# bucle. Tres turnos preguntando lo mismo es lo que hizo que la clienta se fuera.
BUCLE = 3


CASOS: List[Dict[str, Any]] = [
    {
        "id": "corte-acaba-en-cita",
        "por_que": "El camino mas simple que existe. Si este falla, no se despliega nada.",
        # NADA de "manana": la agenda de un negocio real cambia sola. El 28-ago-2026
        # este caso se puso rojo dos veces seguidas -y provoco una vuelta atras de
        # produccion- porque ese dia el sabado estaba lleno para ese servicio. No
        # habia ninguna regresion: el guion pedia un dia concreto y ese dia no
        # habia hueco. Un caso de prueba que depende del calendario acusa al codigo
        # de lo que hace la agenda.
        "mensajes": ["hola, quiero cita para un corte de senora",
                     "la primera que tengas", "me llamo Ana Ruiz", "si, confirmo"],
        "espera": "cita_viva",
    },
    {
        "id": "elegir-una-opcion-resuelve",
        "por_que": ("Al separar 'mechas o balayage' en dos opciones, contestar 'mechas' "
                    "dejo de resolver y la conversacion entraba en bucle."),
        "mensajes": ["quiero unas mechas", "mechas", "lo tengo medio",
                     "la primera que tengas", "me llamo Ana Ruiz", "si, confirmo"],
        "espera": "cita_viva",
    },
    {
        "id": "preguntar-precio-lleva-al-diagnostico",
        "por_que": ("La regla del salon: de mechas y color no se da precio sin ver el "
                    "pelo. Acabar con el tratamiento de cuatro horas es el fallo caro."),
        "mensajes": ["cuanto me costarian unas mechas?", "lo tengo medio",
                     "vale, cogeme cita", "la primera que tengas",
                     "me llamo Ana Ruiz", "si, confirmo"],
        "espera": "cita_de_diagnostico_o_ninguna",
    },
    {
        "id": "cancelar-cancela-de-verdad",
        "por_que": "Decir que se cancelo sin cancelar deja el hueco ocupado y a la clienta creyendo que no.",
        "con_cita": True,
        "mensajes": ["quiero cancelar mi cita", "si, cancelala"],
        "espera": "sin_citas_vivas",
    },
    {
        "id": "reprogramar-mueve-la-cita",
        "por_que": "Reprogramar tiene que MOVER la cita, no crear otra ni dejarla igual.",
        "con_cita": True,
        "mensajes": ["necesito cambiar mi cita de dia",
                     "cualquier otro hueco que tengas me vale",
                     "vale, la primera opcion", "si, confirmo"],
        "espera": "una_cita_movida",
    },
]


def _telefono(indice: int) -> str:
    return str(TELEFONO_BASE + indice)


def _dejarle_una_cita(cliente_id: str, telefono: str):
    """Una cita ya cogida, para los casos que vienen a cancelar o a mover."""
    import datetime

    from backend import agenda, booking, timeutils

    empleados = agenda._list_public_employee_rows(cliente_id)
    servicios = [s for s in booking._public_services_for_booking(cliente_id)
                 if 0 < int(s.get("duration_minutes") or 0) <= 30]
    if not empleados or not servicios:
        return None
    servicio = str(servicios[0].get("nombre") or servicios[0].get("name") or "")
    hoy = timeutils._utc_now().date()
    for salto in range(2, 16):
        dia = (hoy + datetime.timedelta(days=salto)).isoformat()
        try:
            huecos = asyncio.run(agenda._available_slots_for_day(cliente_id, dia)) or []
        except Exception:  # noqa: BLE001
            continue
        for hora in huecos[:6]:
            for empleado in empleados:
                try:
                    return asyncio.run(booking._create_booking_core(
                        cliente_id, employee_row=empleado, nombre="Ana Ruiz",
                        telefono=telefono, email="", servicio=servicio,
                        booking_date=dia, booking_time=hora, notas="",
                        source="humo", send_confirmation=False))
                except Exception:  # noqa: BLE001 - ese hueco no valia
                    continue
    return None


def _hablar(cliente_id: str, telefono: str, mensajes: List[str]) -> List[Dict[str, str]]:
    """Le manda los mensajes por el camino REAL de WhatsApp y devuelve el ida y vuelta."""
    from evals import arnes
    from backend import whatsapp

    dichos = arnes.capturar_envios()
    whatsapp._wa_clear_flow(cliente_id, telefono)
    conversacion: List[Dict[str, str]] = []
    for mensaje in mensajes:
        conversacion.append({"quien": "clienta", "texto": mensaje})
        marca = len(dichos)
        # La cita se cierra pulsando: su "confirmo" se entrega como el boton.
        boton = ""
        if arnes.le_han_pedido_confirmar(conversacion) and arnes.dice_que_si(mensaje):
            boton = "confirm_yes"
        asyncio.run(whatsapp._handle_whatsapp_message(
            cliente_id=cliente_id, phone_number_id="phone_humo",
            from_number=telefono, incoming_text=mensaje,
            interactive_id=boton, request=None))
        for respuesta in dichos[marca:]:
            conversacion.append({"quien": "asistente", "texto": respuesta})
    whatsapp._wa_clear_flow(cliente_id, telefono)
    return conversacion


def _hay_bucle(cliente_id: str, telefono: str) -> str:
    """Repetir la MISMA llamada tres veces es dar vueltas.

    Con solo el nombre no vale: pedir el catalogo tres turnos seguidos mientras la
    clienta va dando datos ("unas mechas" -> "mechas" -> "lo tengo medio") es
    exactamente lo que tiene que hacer. Lo que no puede es preguntar tres veces lo
    MISMO, que es como se cansa y se va.
    """
    from backend import trazas, whatsapp

    session_id = whatsapp._whatsapp_session_id(cliente_id, telefono)
    seguidas: Dict[str, int] = {}
    for turno in trazas.llamadas_por_turno(cliente_id, session_id):
        claves = {"%s|%s" % (ll["nombre"], ll["args"]) for ll in turno}
        for clave in list(seguidas):
            if clave not in claves:
                seguidas[clave] = 0
        for clave in claves:
            seguidas[clave] = seguidas.get(clave, 0) + 1
            if seguidas[clave] >= BUCLE:
                return "%s se ha llamado %d veces con lo mismo: esta dando vueltas" % (
                    clave.split("|")[0], seguidas[clave])
    return ""


def _juzgar(cliente_id: str, telefono: str, caso: Dict[str, Any], previa) -> str:
    """Vacio si esta bien. Se mira la AGENDA, no lo que diga el texto."""
    from evals import arnes

    vivas = arnes.citas_vivas(cliente_id, telefono)
    espera = caso["espera"]

    if espera == "cita_viva":
        if not vivas:
            return "no ha quedado ninguna cita en la agenda"
    elif espera == "sin_citas_vivas":
        if vivas:
            return "la cita sigue viva despues de pedir que se cancele"
    elif espera == "una_cita_movida":
        if len(vivas) != 1:
            return "tiene que quedar UNA cita y hay %d" % len(vivas)
        antes = "%s %s" % (previa["booking_date"], previa["booking_time"]) if previa else ""
        ahora = "%s %s" % (vivas[0]["booking_date"], vivas[0]["booking_time"])
        if antes and antes == ahora:
            return "la cita no se ha movido de sitio"
    elif espera == "cita_de_diagnostico_o_ninguna":
        for cita in vivas:
            nombre = str(cita.get("servicio") or "").lower()
            if not any(p in nombre for p in ("diagnostico", "valoracion", "presupuesto")):
                return "pregunto el precio y se le ha cogido %r" % cita.get("servicio")
    return _hay_bucle(cliente_id, telefono)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cliente", default="alicia_rincon_estilistas")
    parser.add_argument("--db-origen", default="storage/vantelia.db")
    parser.add_argument("--db-copia", default="storage/mediciones/humo.db")
    parser.add_argument("--caso", default="", help="ejecutar solo este id")
    args = parser.parse_args()

    from evals import arnes

    os.makedirs(os.path.dirname(args.db_copia) or ".", exist_ok=True)
    arnes.preparar_copia(args.db_origen, args.db_copia)
    arnes.comprobar_aislamiento(args.db_copia)
    arnes.cortar_el_mundo_exterior()

    casos = [c for c in CASOS if not args.caso or c["id"] == args.caso]
    fallos = []
    print("humo: %d conversaciones enteras sobre una copia de la base de datos" % len(casos))
    print()
    for indice, caso in enumerate(casos):
        # Al otro lado hay un modelo, no una funcion: la misma conversacion puede
        # salir distinta dos veces. Un fallo DE VERDAD falla las dos; un tropiezo,
        # no. Sin esto, el humo bloquea despliegues por azar, se le pierde la fe y
        # acaba ignorandose, que es como si no existiera.
        motivo = ""
        for intento in (0, 1):
            telefono = _telefono(indice * 10 + intento)
            previa = _dejarle_una_cita(args.cliente, telefono) if caso.get("con_cita") else None
            if caso.get("con_cita") and previa is None:
                motivo = "(no se le ha podido dejar una cita)"
                break
            try:
                _hablar(args.cliente, telefono, caso["mensajes"])
                motivo = _juzgar(args.cliente, telefono, caso, previa)
            except Exception as exc:  # noqa: BLE001 - un caso roto es un fallo, no un crash
                motivo = "ha reventado: %s" % str(exc)[:160]
            if not motivo:
                if intento:
                    print("  ok   %-38s (al segundo intento)" % caso["id"])
                else:
                    print("  ok   %-38s" % caso["id"])
                break
            if not intento:
                print("  ..   %-38s %s -- se reintenta" % (caso["id"], motivo))
        if motivo:
            fallos.append((caso, motivo))
            print("  MAL  %-38s %s (las DOS veces)" % (caso["id"], motivo))
            print("       por que importa: %s" % caso["por_que"])

    print()
    if fallos:
        print("=" * 70)
        print("  NO DESPLEGAR: %d de %d caminos rotos" % (len(fallos), len(casos)))
        print("=" * 70)
        return 1
    print("  los %d caminos llegan hasta el final" % len(casos))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
