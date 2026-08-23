# -*- coding: utf-8 -*-
"""Cien clientas hablando con el asistente. Un porcentaje, no anecdotas.

POR QUE EXISTE
--------------
El banco de casos son 28 guiones escritos a mano: sirven para que un fallo
conocido no vuelva. Pero los fallos que aparecen en casa del cliente vienen de las
otras mil formas de decir lo mismo, y esas no se escriben a mano.

Aqui la clienta la hace un modelo (`evals/clientas.py`: doce personas por varias
formas de escribir) y conversa sola con el asistente por el recorrido REAL de
WhatsApp hasta conseguir lo suyo o cansarse. Al final se juzga lo unico que
importa en el salon:

    ¿acabo habiendo la cita que queria, EN LA AGENDA?
    ¿se atasco por el camino?
    ¿le dijo algo falso?

USO
---
    python scripts/simular_clientas.py --cliente alicia_rincon_estilistas \\
        --db-copia /tmp/sim.db --conversaciones 40

    python scripts/simular_clientas.py ... --guardar linea_base.json
    python scripts/simular_clientas.py ... --comparar linea_base.json

CUESTA DINERO: son dos modelos hablando (el asistente y la clienta). Unos
centimos por cada 40 conversaciones.

EXIGE --db-copia: las clientas reservan y cancelan de verdad.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import random
import sys
import unicodedata
from collections import Counter
from typing import Any, Dict, List

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MAX_TURNOS = 12          # una conversacion de WhatsApp no da mucho mas de si
MODELO_CLIENTA = "gpt-4o-mini"


def _norm(texto: str) -> str:
    limpio = unicodedata.normalize("NFKD", str(texto or "").lower())
    return "".join(c for c in limpio if not unicodedata.combining(c))


# ─── La clienta ────────────────────────────────────────────────────────────

def _hablar_como_clienta(guion: str, conversacion: List[Dict[str, str]]) -> str:
    """El siguiente mensaje de la clienta. Vacio si el modelo falla."""
    from backend import settings
    from openai import OpenAI

    mensajes = [{"role": "system", "content": guion}]
    # Se le da la vuelta a los papeles: lo que dijo el asistente es lo que ELLA
    # lee, asi que entra como "user" desde su punto de vista.
    for linea in conversacion:
        if linea["quien"] == "clienta":
            mensajes.append({"role": "assistant", "content": linea["texto"]})
        else:
            mensajes.append({"role": "user", "content": linea["texto"]})
    if len(mensajes) == 1:
        mensajes.append({"role": "user", "content": "(escribes tu el primer mensaje)"})
    try:
        cliente = OpenAI(api_key=settings.OPENAI_API_KEY)
        respuesta = cliente.chat.completions.create(
            model=MODELO_CLIENTA, messages=mensajes, temperature=1.0, max_tokens=120,
        )
        return (respuesta.choices[0].message.content or "").strip()
    except Exception as exc:  # noqa: BLE001
        print("   (la clienta no ha podido escribir: %s)" % exc)
        return ""


# ─── Una conversacion entera ───────────────────────────────────────────────

def _conversar(cliente_id: str, combinacion: Dict[str, Any], telefono: str) -> Dict[str, Any]:
    from evals import arnes, clientas
    from backend import whatsapp

    persona = combinacion["persona"]
    previa = None
    if persona.get("con_cita"):
        previa = _dejarle_una_cita(cliente_id, telefono)
        if not previa:
            return {"id": combinacion["id"], "veredicto": "sin_montar",
                    "motivo": "no se le ha podido dejar una cita", "turnos": 0,
                    "conversacion": []}

    guion = clientas.guion(persona, combinacion["estilo"])
    if previa:
        guion = guion.replace("{codigo}", previa["booking_code"])

    dichos = arnes.capturar_envios()
    whatsapp._wa_clear_flow(cliente_id, telefono)
    conversacion: List[Dict[str, str]] = []

    for _ in range(MAX_TURNOS):
        suyo = _hablar_como_clienta(guion, conversacion)
        if not suyo:
            break
        if _norm(suyo).strip().strip(".!") == "listo":
            break
        conversacion.append({"quien": "clienta", "texto": suyo})

        marca = len(dichos)
        try:
            asyncio.run(whatsapp._handle_whatsapp_message(
                cliente_id=cliente_id, phone_number_id="phone_sim",
                from_number=telefono, incoming_text=suyo,
                interactive_id="", request=None,
            ))
        except Exception as exc:  # noqa: BLE001
            conversacion.append({"quien": "asistente", "texto": "[REVENTO] %r" % exc})
            break
        for respuesta in dichos[marca:]:
            conversacion.append({"quien": "asistente", "texto": respuesta})
        if len(dichos) == marca:  # se ha quedado callado
            conversacion.append({"quien": "asistente", "texto": ""})

    whatsapp._wa_clear_flow(cliente_id, telefono)
    return _juzgar(cliente_id, combinacion, telefono, conversacion, previa)


def _dejarle_una_cita(cliente_id: str, telefono: str):
    """Una cita ya cogida, para las que vienen a cancelar o a cambiarla."""
    import datetime

    from backend import agenda, booking, db, timeutils

    with db._get_db_connection() as conexion:
        empleados = conexion.execute(
            "SELECT * FROM employees WHERE cliente_id=? AND is_active=1 LIMIT 1",
            (cliente_id,),
        ).fetchall()
    if not empleados:
        return None
    servicios = booking._public_services_for_booking(cliente_id)
    servicio = servicios[0]["nombre"] if servicios else ""
    hoy = timeutils._utc_now().date()
    for salto in range(21):
        fecha = (hoy + datetime.timedelta(days=2 + salto)).isoformat()
        huecos = asyncio.run(agenda._available_slots_for_day(cliente_id, fecha)) or []
        for hora in reversed(huecos):
            try:
                fila = asyncio.run(booking._create_booking_core(
                    cliente_id, employee_row=empleados[0], nombre="Clienta Simulada",
                    email="", telefono=telefono, servicio=servicio,
                    booking_date=fecha, booking_time=hora, notas="",
                    source="sim", send_confirmation=False,
                ))
                return dict(fila)
            except Exception:  # noqa: BLE001
                continue
    return None


# ─── El veredicto ──────────────────────────────────────────────────────────

def _juzgar(cliente_id, combinacion, telefono, conversacion, previa) -> Dict[str, Any]:
    """Que ha pasado de verdad. La agenda manda sobre lo que diga el chat."""
    from evals import arnes

    persona = combinacion["persona"]
    objetivo = persona["objetivo"]
    dichos = [t["texto"] for t in conversacion if t["quien"] == "asistente"]
    vivas = arnes.citas_vivas(cliente_id, telefono)
    resultado = {
        "id": combinacion["id"], "objetivo": objetivo,
        "turnos": sum(1 for t in conversacion if t["quien"] == "clienta"),
        "conversacion": conversacion, "fallos": [],
    }

    # 1) Lo que NUNCA puede pasar, mire lo que mire la clienta.
    resultado["fallos"].extend(_mentiras(cliente_id, dichos, vivas))
    if any("[REVENTO]" in t["texto"] for t in conversacion):
        resultado["fallos"].append("revienta")
    if dichos and not dichos[-1].strip():
        resultado["fallos"].append("se_queda_callada")
    if _se_repite(dichos):
        resultado["fallos"].append("repite_la_misma_pregunta")

    # 2) ¿Consiguio lo que venia a buscar?
    if objetivo == "reservar":
        nuevas = [c for c in vivas if not previa or c["booking_code"] != previa["booking_code"]]
        if not nuevas:
            resultado["veredicto"] = "atascada"
            resultado["motivo"] = "se fue sin cita"
        elif len(nuevas) > 1:
            resultado["veredicto"] = "fallo"
            resultado["motivo"] = "le ha cogido %d citas" % len(nuevas)
            resultado["fallos"].append("cita_duplicada")
        elif (_es_diagnostico(nuevas[0])
              and _tiene_regla_de_no_precio(cliente_id, persona.get("familia", ""))):
            # El salon NO reserva mechas sin ver el pelo: te cita para valorarlo.
            # Acabar con la cita de diagnostico es EXITO, no un servicio equivocado.
            resultado["veredicto"] = "bien"
        elif persona.get("familia") and not _familia_ok(persona["familia"], nuevas[0]):
            resultado["veredicto"] = "fallo"
            resultado["motivo"] = "queria %s y le ha cogido %r" % (
                persona["familia"], nuevas[0]["servicio"])
            resultado["fallos"].append("servicio_equivocado")
        else:
            resultado["veredicto"] = "bien"
    elif objetivo == "cancelar":
        if vivas:
            resultado["veredicto"] = "atascada"
            resultado["motivo"] = "la cita sigue viva"
        else:
            resultado["veredicto"] = "bien"
    elif objetivo == "reprogramar":
        if len(vivas) != 1:
            resultado["veredicto"] = "fallo"
            resultado["motivo"] = "tiene que quedar UNA cita y hay %d" % len(vivas)
            resultado["fallos"].append("cita_duplicada")
        elif (vivas[0]["booking_date"], vivas[0]["booking_time"]) == (
                previa["booking_date"], previa["booking_time"]):
            resultado["veredicto"] = "atascada"
            resultado["motivo"] = "la cita no se ha movido"
        else:
            resultado["veredicto"] = "bien"
    else:  # preguntar_precio, consejo, informacion
        if not dichos:
            resultado["veredicto"] = "atascada"
            resultado["motivo"] = "no le contesto nada"
        elif vivas and not previa and objetivo == "preguntar_precio":
            # Que acabe cogiendo cita al preguntar el precio es EL OBJETIVO del
            # negocio (no doy precio, te cito para verlo). Pero tiene que ser la
            # cita de valoracion de 15 minutos, no el tratamiento de 260 EUR a
            # alguien a quien no han visto el pelo.
            if _es_diagnostico(vivas[0]):
                resultado["veredicto"] = "bien"
            else:
                resultado["veredicto"] = "fallo"
                resultado["motivo"] = "le ha cogido %r en vez de la valoracion" % (
                    vivas[0]["servicio"])
                resultado["fallos"].append("cita_del_tratamiento_en_vez_de_valoracion")
        elif vivas and not previa:
            resultado["veredicto"] = "fallo"
            resultado["motivo"] = "le ha cogido una cita que no habia pedido"
            resultado["fallos"].append("cita_sin_pedirla")
        else:
            resultado["veredicto"] = "bien"

    if resultado["fallos"] and resultado["veredicto"] == "bien":
        resultado["veredicto"] = "fallo"
        resultado["motivo"] = ", ".join(resultado["fallos"])
    resultado.setdefault("motivo", "")
    return resultado


def _es_diagnostico(cita: Dict[str, Any]) -> bool:
    """La cita de valoracion que este negocio ofrece en vez de dar un precio."""
    nombre = _norm(str(cita.get("servicio") or ""))
    return "diagnostico" in nombre or "valoracion" in nombre or "presupuesto" in nombre


def _tiene_regla_de_no_precio(cliente_id: str, familia: str) -> bool:
    """¿Este negocio ha dicho que de esta familia no da precio por mensaje?"""
    from backend import rules

    if not familia:
        return False
    return rules.match(cliente_id, {"intencion": "precio", "familia": familia}) is not None


def _mentiras(cliente_id: str, dichos: List[str], vivas: List[Dict[str, Any]]) -> List[str]:
    """Afirmaciones falsas comprobables contra los datos del negocio."""
    from backend import agent

    fallos = []
    texto = " ".join(dichos)
    if agent._da_la_cita_por_hecha(texto) and not vivas:
        fallos.append("dice_que_hay_cita_y_no_la_hay")

    # Un precio para algo que este negocio NO presupuesta por mensaje.
    from backend import rules

    plano = _norm(texto)
    if ("€" in texto or " euros" in plano) and _habla_de(plano, ("mecha", "balayage", "balay")):
        regla = rules.match(cliente_id, {"intencion": "precio", "familia": "mechas"})
        if regla is not None:
            fallos.append("da_un_precio_que_no_debe")
    return fallos


def _habla_de(plano: str, pistas) -> bool:
    return any(p in plano for p in pistas)


def _familia_ok(familia: str, cita: Dict[str, Any]) -> bool:
    return _norm(familia) in _norm(str(cita.get("servicio") or ""))


def _se_repite(dichos: List[str]) -> bool:
    """¿Esta contestando lo mismo una y otra vez?

    Visto de verdad: a una clienta que insistio cuatro veces le solto CUATRO veces
    la misma respuesta palabra por palabra. Para quien escribe, eso es un muro.
    """
    vistas = [_norm(t)[:80] for t in dichos if t.strip()]
    return any(a == b for a, b in zip(vistas, vistas[1:])) or (
        len(vistas) >= 3 and len(set(vistas)) <= len(vistas) - 2
    )


# ─── El informe ────────────────────────────────────────────────────────────

def _informe(resultados: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(resultados) or 1
    cuenta = Counter(r["veredicto"] for r in resultados)
    patrones = Counter()
    for resultado in resultados:
        for fallo in resultado["fallos"]:
            patrones[fallo] += 1
        if resultado["veredicto"] == "atascada":
            patrones["atascada: " + (resultado["motivo"] or "?")] += 1
    por_objetivo = {}
    for resultado in resultados:
        datos = por_objetivo.setdefault(resultado["objetivo"], {"total": 0, "bien": 0})
        datos["total"] += 1
        datos["bien"] += 1 if resultado["veredicto"] == "bien" else 0
    return {
        "total": len(resultados),
        "bien": cuenta["bien"],
        "atascada": cuenta["atascada"],
        "fallo": cuenta["fallo"],
        "pct_bien": round(100.0 * cuenta["bien"] / total, 1),
        "pct_atascada": round(100.0 * cuenta["atascada"] / total, 1),
        "pct_fallo": round(100.0 * cuenta["fallo"] / total, 1),
        "patrones": patrones.most_common(),
        "por_objetivo": por_objetivo,
    }


def _pintar(informe: Dict[str, Any], anterior: Dict[str, Any] = None) -> None:
    print("\n" + "=" * 68)
    print("  %d conversaciones" % informe["total"])
    print()
    for etiqueta, clave, pct in (
        ("Consiguio lo que queria", "bien", "pct_bien"),
        ("Se atasco", "atascada", "pct_atascada"),
        ("Fallo (dijo o hizo algo mal)", "fallo", "pct_fallo"),
    ):
        linea = "  %-32s %5.1f%%  (%d)" % (etiqueta, informe[pct], informe[clave])
        if anterior:
            delta = informe[pct] - anterior.get(pct, 0)
            linea += "   %+.1f vs antes" % delta
        print(linea)

    print("\n  POR LO QUE VENIA:")
    for objetivo, datos in sorted(informe["por_objetivo"].items()):
        pct = 100.0 * datos["bien"] / (datos["total"] or 1)
        print("   %-16s %5.1f%%  (%d de %d)" % (objetivo, pct, datos["bien"], datos["total"]))

    if informe["patrones"]:
        print("\n  PATRONES DE FALLO (agrupados):")
        for patron, veces in informe["patrones"]:
            print("   %3d x  %s" % (veces, patron))
    print("=" * 68)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cliente", default="alicia_rincon_estilistas")
    parser.add_argument("--db-copia", required=True, help="OBLIGATORIO: las clientas reservan de verdad")
    parser.add_argument("--db-origen", default="storage/vantelia.db")
    parser.add_argument("--conversaciones", type=int, default=40)
    parser.add_argument("--semilla", type=int, default=0)
    parser.add_argument("--guardar", default="", help="escribe el informe en un JSON")
    parser.add_argument("--comparar", default="", help="compara contra un informe guardado")
    parser.add_argument("--detalle", action="store_true", help="imprime las conversaciones que fallan")
    parser.add_argument("--persona", default="", help="solo esta clienta (para mirar un patron)")
    args = parser.parse_args()

    from evals import arnes, clientas

    arnes.preparar_copia(args.db_origen, args.db_copia)
    arnes.comprobar_aislamiento(args.db_copia)
    arnes.cortar_el_mundo_exterior()

    todas = clientas.combinaciones()
    if args.persona:
        todas = [c for c in todas if c["persona"]["id"] == args.persona] or todas
    random.seed(args.semilla or None)
    # Barajar ANTES de ciclar: con 5 conversaciones se probaban las 5 primeras de
    # la lista (todas la misma persona) en vez de cinco clientas distintas.
    random.shuffle(todas)
    elegidas = [todas[i % len(todas)] for i in range(args.conversaciones)]

    resultados = []
    for indice, combinacion in enumerate(elegidas):
        telefono = "34600%06d" % (700000 + indice)
        resultado = _conversar(args.cliente, combinacion, telefono)
        if resultado["veredicto"] == "sin_montar":
            continue
        resultados.append(resultado)
        marca = {"bien": "ok", "atascada": "..", "fallo": "XX"}.get(resultado["veredicto"], "??")
        print("  %s  %-28s %2d turnos  %s" % (
            marca, combinacion["id"], resultado["turnos"], resultado.get("motivo", "")))
        if args.detalle and resultado["veredicto"] != "bien":
            for linea in resultado["conversacion"]:
                quien = "ELLA" if linea["quien"] == "clienta" else "  IA"
                print("        %s: %s" % (quien, linea["texto"].replace("\n", " ")[:150]))

    informe = _informe(resultados)
    anterior = None
    if args.comparar and os.path.exists(args.comparar):
        with open(args.comparar, encoding="utf-8") as fichero:
            anterior = json.load(fichero)
    _pintar(informe, anterior)

    if args.guardar:
        with open(args.guardar, "w", encoding="utf-8") as fichero:
            json.dump(informe, fichero, ensure_ascii=False, indent=2)
        print("\n  guardado en %s" % args.guardar)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
