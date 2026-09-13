# -*- coding: utf-8 -*-
"""Cambios del portal y reinicios A MITAD de conversación, con el modelo de verdad.

POR QUE EXISTE
--------------
13-sep-2026. El informe de aceptación dejaba dos puertas «NO MEDIDAS con modelo»:

* Cambios del portal: el negocio cambia horario, vacaciones, un servicio o una regla
  entre que se le ofrece algo a la clienta y ella lo confirma. Los tests
  deterministas prueban el mecanismo (revalidar antes de ejecutar); nadie había
  mirado qué hace el asistente con una conversación real encima.
* Reinicios: el proceso se reinicia (despliegue, caída) con una reserva a medias.
  El estado vive en la BD desde la persistencia de Astra; en memoria solo quedan
  los flujos y cachés, que se pierden.

Cada escenario: unos mensajes, una ACCIÓN hecha con el mismo código que usa el
portal (o un reinicio simulado vaciando el estado en memoria) y más mensajes. Se
juzga la AGENDA de la copia, no lo que diga el texto (salvo la regla retirada, que
por WhatsApp solo puede verse en el resumen). Cada intento parte de una copia
nueva de la BD: una acción de un escenario no contamina al siguiente.

    python scripts/medir_portal_y_reinicio.py --db-origen copia.db --guardar informe.json

CUESTA DINERO (céntimos): habla con el modelo. Sale con 1 si algún escenario falla
las dos veces o no se puede medir.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import sys
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Teléfonos sin historial en la copia de producción (los del banco y el humo sí lo tienen).
TELEFONO_BASE = 34600970000

ESCENARIOS: List[Dict[str, Any]] = [
    {
        "id": "vacaciones-despues-de-ofrecer-el-dia",
        "antes": ["quiero cita para un corte de señora", "el {dia_abierto_nombre}"],
        "accion": "bloquear_dia",
        "despues": ["a las 17:00", "me llamo Ana Ruiz Perez", "si, confirmo"],
        "horas_calendario": ["17:00"],
        "espera": "sin_cita_ese_dia",
    },
    {
        "id": "hora-bloqueada-con-el-resumen-delante",
        "antes": ["quiero cita para un corte de señora", "el {dia_abierto_nombre} a las 17:00",
                  "me llamo Ana Ruiz Perez"],
        "accion": "bloquear_hora",
        "despues": ["si, confirmo"],
        "horas_calendario": ["17:00"],
        "espera": "sin_cita_a_esa_hora",
    },
    {
        "id": "servicio-retirado-con-el-resumen-delante",
        "antes": ["quiero cita para un corte de señora", "el {dia_abierto_nombre} a las 17:00",
                  "me llamo Ana Ruiz Perez"],
        "accion": "retirar_servicio",
        "despues": ["si, confirmo"],
        "horas_calendario": ["17:00"],
        "espera": "sin_cita_del_servicio_retirado",
    },
    {
        "id": "regla-apagada-despues-de-ofrecer",
        "antes": ["quiero un alisado", "no lo tengo claro", "el {dia_abierto}"],
        "accion": "apagar_regla_de_orientacion",
        "despues": ["a las 15", "si", "me llamo Ana Ruiz Perez"],
        "horas_calendario": ["15:00"],
        "servicio_calendario": "valoracion",
        "espera": "sin_resumen_de_la_oferta_retirada",
    },
    {
        "id": "reinicio-a-mitad-de-reserva",
        "antes": ["quiero cita para un corte de señora", "el {dia_abierto_nombre} a las 17:00"],
        "accion": "reiniciar",
        "despues": ["me llamo Ana Ruiz Perez", "si, confirmo", "si, confirmo"],
        "horas_calendario": ["17:00"],
        "espera": "una_cita_viva",
    },
    {
        "id": "reinicio-con-el-resumen-delante",
        "antes": ["quiero cita para un corte de señora", "el {dia_abierto_nombre} a las 17:00",
                  "me llamo Ana Ruiz Perez"],
        "accion": "reiniciar",
        "despues": ["si, confirmo", "si, confirmo"],
        "horas_calendario": ["17:00"],
        "espera": "una_cita_viva",
    },
]


def _norm(texto: str) -> str:
    limpio = unicodedata.normalize("NFKD", str(texto or "").lower())
    return "".join(c for c in limpio if not unicodedata.combining(c))


# ─── Las acciones: el mismo código que usa el portal ─────────────────────

def accionar(nombre: str, cliente_id: str, contexto: Dict[str, Any]) -> str:
    """Ejecuta la acción entre turnos y devuelve qué se ha hecho, para el informe."""
    from backend import appstate

    if nombre in ("bloquear_dia", "bloquear_hora"):
        # POST /auth/schedule/blocks -> agenda._create_agenda_blocks, bloqueo general.
        from api_models import PortalAgendaBlockPayload
        from backend import agenda

        inicio, fin = ("00:00", "23:59") if nombre == "bloquear_dia" else ("17:00", "18:00")
        filas, _saltadas, _desde, _hasta = agenda._create_agenda_blocks(cliente_id, PortalAgendaBlockPayload(
            fecha=contexto["dia"], hora_inicio=inicio, hora_fin=fin, motivo="medicion"))
        return "bloqueo %s %s-%s (%d filas)" % (contexto["dia"], inicio, fin, len(filas))
    if nombre == "retirar_servicio":
        # PATCH /auth/services/{slug} is_active=false: UPDATE + intents.olvidar_tenant.
        from backend import agenda, db, intents, timeutils

        retirados = [s for s in agenda._catalog_services(cliente_id)
                     if "corte" in _norm(s.get("nombre")) and "senora" in _norm(s.get("nombre"))]
        with db._get_db_connection() as conexion:
            for servicio in retirados:
                conexion.execute(
                    "UPDATE services SET is_active = 0, updated_at = ? WHERE cliente_id = ? AND slug = ?",
                    (timeutils._utc_now_iso(), cliente_id, servicio["id"]))
            conexion.commit()
        intents.olvidar_tenant(cliente_id)
        contexto["retirados"] = [_norm(s.get("nombre")) for s in retirados]
        return "servicios retirados: %s" % [s.get("nombre") for s in retirados]
    if nombre == "apagar_regla_de_orientacion":
        # PUT /auth/app/business-rules/{id} con activa=false -> rules.guardar.
        from backend import rules

        apagadas = []
        for regla in rules.listar(cliente_id):
            intenciones = regla.get("intenciones") or []
            if isinstance(intenciones, str):
                intenciones = json.loads(intenciones or "[]")
            if "orientacion" in intenciones and regla.get("activa"):
                rules.guardar(cliente_id, regla_id=regla["id"], nombre=regla["nombre"],
                              intenciones=intenciones, familias=regla.get("familias") or [],
                              accion=regla["accion"], texto=regla.get("texto") or "",
                              prioridad=int(regla.get("prioridad") or 100), activa=False,
                              playbook_id=regla.get("playbook_id") or "")
                apagadas.append(regla["nombre"])
        if not apagadas:
            raise RuntimeError("no hay regla de orientacion activa que apagar: no se mide")
        return "reglas apagadas: %s" % apagadas
    if nombre == "reiniciar":
        # Lo que se pierde al reiniciar el proceso: lo que vive en memoria. La BD queda.
        vaciados = []
        for nombre_dict in ("whatsapp_flows", "sesiones", "chat_manage_state", "intent_cache"):
            estructura = getattr(appstate, nombre_dict, None)
            if isinstance(estructura, dict):
                vaciados.append("%s(%d)" % (nombre_dict, len(estructura)))
                estructura.clear()
        return "reinicio: vaciado %s" % ", ".join(vaciados)
    raise ValueError("accion desconocida: %s" % nombre)


# ─── El juicio: la agenda de la copia ────────────────────────────────────

def juzgar(escenario: Dict[str, Any], citas_vivas: List[Dict[str, Any]], contexto: Dict[str, Any],
           respuestas_despues: List[str]) -> str:
    """Vacío si está bien. Se mira lo que queda en la agenda."""
    espera = escenario["espera"]
    dia = contexto.get("dia", "")
    if espera == "sin_cita_ese_dia":
        malas = [c for c in citas_vivas if c["booking_date"] == dia]
        return "cita en un dia bloqueado: %s" % malas if malas else ""
    if espera == "sin_cita_a_esa_hora":
        malas = [c for c in citas_vivas if c["booking_date"] == dia and c["booking_time"] == "17:00"]
        return "cita en una hora bloqueada: %s" % malas if malas else ""
    if espera == "sin_cita_del_servicio_retirado":
        retirados = contexto.get("retirados") or []
        if not retirados:
            return "no se ha retirado ningun servicio: no se mide"
        malas = [c for c in citas_vivas if _norm(c.get("servicio")) in retirados]
        return "cita de un servicio retirado: %s" % malas if malas else ""
    if espera == "una_cita_viva":
        return "" if len(citas_vivas) == 1 else "tiene que quedar UNA cita y hay %d: %s" % (
            len(citas_vivas), citas_vivas)
    if espera == "sin_resumen_de_la_oferta_retirada":
        for texto in respuestas_despues:
            plano = _norm(texto)
            if "resumen de tu cita" in plano and ("diagnostico" in plano or "valoracion" in plano):
                return "resumen de la oferta que el negocio acaba de retirar"
        return ""
    raise ValueError("espera desconocida: %s" % espera)


def _hablar(cliente_id, telefono, mensajes, dichos) -> List[str]:
    from backend import whatsapp
    from evals import arnes

    respuestas = []
    for entrada in mensajes:
        mensaje, boton = arnes.preparar_entrada(dichos, cliente_id, telefono, entrada)
        marca = len(dichos)
        asyncio.run(whatsapp._handle_whatsapp_message(
            cliente_id=cliente_id, phone_number_id="phone_portal",
            from_number=telefono, incoming_text=mensaje, interactive_id=boton, request=None))
        respuestas.extend(dichos[marca:])
    return respuestas


def _un_intento(args, escenario, mensajes_antes, mensajes_despues, fechas, telefono, copia) -> Dict[str, Any]:
    from backend import appstate, whatsapp
    from evals import arnes

    arnes.preparar_copia(args.db_origen, copia)
    arnes.comprobar_aislamiento(copia)
    for nombre in ("whatsapp_flows", "sesiones", "chat_manage_state", "intent_cache"):
        estructura = getattr(appstate, nombre, None)
        if isinstance(estructura, dict):
            estructura.clear()
    dichos = arnes.capturar_envios()
    whatsapp._wa_clear_flow(args.cliente, telefono)
    contexto = {"dia": fechas.get("dia_abierto", "")}
    antes = _hablar(args.cliente, telefono, mensajes_antes, dichos)
    hecho = accionar(escenario["accion"], args.cliente, contexto)
    despues = _hablar(args.cliente, telefono, mensajes_despues, dichos)
    vivas = arnes.citas_vivas(args.cliente, telefono)
    motivo = juzgar(escenario, vivas, contexto, despues)
    return {"telefono": telefono, "ok": not motivo, "motivo": motivo, "accion": hecho,
            "antes": antes, "despues": despues, "citas_vivas": vivas, "contexto": contexto}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cliente", default="alicia_rincon_estilistas")
    parser.add_argument("--db-origen", required=True)
    parser.add_argument("--carpeta-copias", default="storage/mediciones")
    parser.add_argument("--escenario", default="")
    parser.add_argument("--guardar", default="")
    args = parser.parse_args()

    from evals import arnes, calendario

    os.makedirs(args.carpeta_copias, exist_ok=True)
    arnes.cortar_el_mundo_exterior()
    informe = {"inicio_utc": datetime.now(timezone.utc).isoformat(), "cliente": args.cliente,
               "escenarios": []}
    fallos, no_medidos = [], []
    escenarios = [e for e in ESCENARIOS if not args.escenario or e["id"] == args.escenario]
    for indice, escenario in enumerate(escenarios):
        registro = {"id": escenario["id"], "intentos": []}
        informe["escenarios"].append(registro)
        copia = os.path.join(args.carpeta_copias, "portal_%d.db" % indice)
        # Las fechas se resuelven sobre una copia recien preparada y se congelan.
        arnes.preparar_copia(args.db_origen, copia)
        arnes.comprobar_aislamiento(copia)
        caso = {"mensajes": escenario["antes"] + escenario["despues"],
                "horas_calendario": escenario.get("horas_calendario", ()),
                "servicio_calendario": escenario.get("servicio_calendario", "")}
        try:
            mensajes, fechas = calendario.resolver_mensajes(args.cliente, caso)
        except calendario.CalendarioNoDisponible as exc:
            registro.update(estado="no_medido", motivo=str(exc))
            no_medidos.append(escenario["id"])
            print("NO MEDIDO %-42s %s" % (escenario["id"], exc))
            continue
        corte = len(escenario["antes"])
        estado, motivo = "fallo", ""
        for intento in (0, 1):
            telefono = str(TELEFONO_BASE + indice * 10 + intento)
            try:
                resultado = _un_intento(args, escenario, mensajes[:corte], mensajes[corte:], fechas,
                                        telefono, copia)
            except Exception as exc:  # noqa: BLE001 - un escenario roto es un dato
                resultado = {"telefono": telefono, "ok": False, "motivo": "ha reventado: %r" % exc}
            registro["intentos"].append(resultado)
            motivo = resultado["motivo"]
            if resultado["ok"]:
                estado = "ok"
                break
            if "no se mide" in motivo:
                estado = "no_medido"
                break
        registro.update(estado=estado, motivo=motivo, fechas=fechas)
        etiqueta = {"ok": "  OK  ", "fallo": "FALLA ", "no_medido": "NO MED"}[estado]
        print("%s %-42s%s %s" % (etiqueta, escenario["id"],
                                 "  (al segundo intento)" if estado == "ok" and len(registro["intentos"]) == 2 else "",
                                 motivo))
        (fallos if estado == "fallo" else no_medidos if estado == "no_medido" else []).append(escenario["id"])
        if args.guardar:
            with open(args.guardar, "w", encoding="utf-8") as salida:
                json.dump(informe, salida, ensure_ascii=False, indent=2)
    informe.update(fin_utc=datetime.now(timezone.utc).isoformat(), fallos=fallos, no_medidos=no_medidos)
    if args.guardar:
        with open(args.guardar, "w", encoding="utf-8") as salida:
            json.dump(informe, salida, ensure_ascii=False, indent=2)
    print("\n%d escenarios; %d fallos; %d no medidos" % (len(escenarios), len(fallos), len(no_medidos)))
    return 1 if fallos or no_medidos else 0


if __name__ == "__main__":
    raise SystemExit(main())
