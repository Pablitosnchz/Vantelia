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
import re
import asyncio
import io
import json
import os
import random
import sys
import unicodedata
from collections import Counter
from typing import Any, Dict, List

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MAX_TURNOS = 12          # una conversacion de WhatsApp no da mucho mas de si
MODELO_CLIENTA = "gpt-4o-mini"


def _norm(texto: str) -> str:
    limpio = unicodedata.normalize("NFKD", str(texto or "").lower())
    return "".join(c for c in limpio if not unicodedata.combining(c))


# ─── La clienta ────────────────────────────────────────────────────────────

def _hablar_como_clienta(guion: str, conversacion: List[Dict[str, str]], opciones=None) -> str:
    """El siguiente mensaje de la clienta. Vacio si el modelo falla."""
    from backend import settings
    from openai import OpenAI

    mensajes = [{"role": "system", "content": guion}]
    mensajes.append({"role": "system", "content": (
        "Puedes escribir texto libre o pulsar un boton disponible. Para pulsar devuelve "
        'solo un objeto JSON {"boton":"ID exacto"}, eligiendo uno de estos botones: '
        + json.dumps(opciones or [], ensure_ascii=False)
        + ". No inventes IDs. Un si escrito es texto, no una pulsacion.")})
    # Se le da la vuelta a los papeles: lo que dijo el asistente es lo que ELLA
    # lee, asi que entra como "user" desde su punto de vista.
    for linea in conversacion:
        if linea["quien"] == "clienta":
            mensajes.append({"role": "assistant", "content": linea["texto"]})
        else:
            mensajes.append({"role": "user", "content": linea["texto"]})
    if not conversacion:
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
        guion = (guion
                 .replace("{codigo}", previa["booking_code"])
                 .replace("{servicio}", str(previa.get("servicio") or "una cita"))
                 .replace("{cuando}", "%s a las %s" % (previa.get("booking_date", ""),
                                                       previa.get("booking_time", ""))))

    dichos = arnes.capturar_envios()
    whatsapp._wa_clear_flow(cliente_id, telefono)
    conversacion: List[Dict[str, str]] = []

    for _ in range(MAX_TURNOS):
        suyo = _hablar_como_clienta(guion, conversacion, dichos.opciones(cliente_id, telefono))
        if not suyo:
            break
        if _norm(suyo).strip().strip(".!") == "listo":
            break
        entrada = suyo
        try:
            candidata = json.loads(suyo)
            if isinstance(candidata, dict):
                entrada = candidata
        except (ValueError, TypeError):
            pass
        try:
            texto, boton = arnes.preparar_entrada(dichos, cliente_id, telefono, entrada)
        except arnes.AccionNoDisponible as exc:
            conversacion.append({"quien": "clienta", "texto": suyo})
            whatsapp._wa_clear_flow(cliente_id, telefono)
            return {"id": combinacion["id"], "objetivo": persona["objetivo"],
                    "veredicto": "fallo", "motivo": str(exc), "fallos": ["accion_no_disponible"],
                    "turnos": sum(t["quien"] == "clienta" for t in conversacion),
                    "conversacion": conversacion, "instrumento": arnes.VERSION_INTERACCION}
        conversacion.append({"quien": "clienta", "texto": texto, "interactive_id": boton})
        marca = len(dichos)
        try:
            asyncio.run(whatsapp._handle_whatsapp_message(
                cliente_id=cliente_id, phone_number_id="phone_sim",
                from_number=telefono, incoming_text=texto,
                interactive_id=boton, request=None,
            ))
        except arnes.InstrumentoNoCompatible:
            raise
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
    # Un servicio CORTO y neutro: cogiendo el primero del catalogo se llenaba la
    # copia de alisados de 260 EUR y ensuciaba el analisis de lo que pasaba.
    servicios = booking._public_services_for_booking(cliente_id)
    corto = [s for s in servicios if 0 < int(s.get("duration_minutes") or 0) <= 30]
    servicio = (corto or servicios or [{}])[0].get("nombre", "")
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
    # Callarse es un FALLO... salvo cuando es lo que se le ha pedido: quien pide
    # hablar con una persona quiere justo eso, que el asistente deje de contestar
    # encima. Sin esta excepcion, la clienta `pide-persona` salia 0 % haciendo
    # exactamente lo correcto (medido el 3-sep-2026, primera tirada con ella).
    if (dichos and not dichos[-1].strip()
            and objetivo != "hablar_con_persona"):
        resultado["fallos"].append("se_queda_callada")
    if _se_repite(dichos):
        resultado["fallos"].append("repite_la_misma_pregunta")

    # 2) ¿Consiguio lo que venia a buscar?
    if objetivo == "reservar":
        nuevas = [c for c in vivas if not previa or c["booking_code"] != previa["booking_code"]]
        if not nuevas:
            if persona.get("acepta_sin_cita") and _ofrecio_una_salida(cliente_id, dichos):
                # Hay clientas que NO pueden acabar con cita -quieren venir cuando
                # el salon esta cerrado-. Ahi lo que se juzga es que no se la deje
                # tirada, no que aparezca una cita imposible.
                resultado["veredicto"] = "bien"
            else:
                resultado["veredicto"] = "atascada"
                resultado["motivo"] = "se fue sin cita"
        elif len(nuevas) > 1:
            resultado["veredicto"] = "fallo"
            resultado["motivo"] = "le ha cogido %d citas" % len(nuevas)
            resultado["fallos"].append("cita_duplicada")
        elif _es_diagnostico(nuevas[0]) and persona.get("rechaza_valoracion"):
            # Ella dijo que NO queria el diagnostico. Cogerselo igual es no
            # escucharla, aunque sea la ruta habitual del negocio.
            resultado["veredicto"] = "fallo"
            resultado["motivo"] = "rechazo el diagnostico y le han cogido el diagnostico"
            resultado["fallos"].append("no_la_escucha")
        elif (_es_diagnostico(nuevas[0])
              and _tiene_regla_de_no_precio(cliente_id, persona.get("familia", ""))):
            # El salon NO reserva mechas sin ver el pelo: te cita para valorarlo.
            # Acabar con la cita de diagnostico es EXITO, no un servicio equivocado.
            resultado["veredicto"] = "bien"
        elif _es_diagnostico(nuevas[0]) and _ella_pidio_el_diagnostico(conversacion):
            # Lo pidio ELLA ("si, agendame el diagnostico"). Contarlo como servicio
            # equivocado castigaba al asistente por hacerle caso.
            resultado["veredicto"] = "bien"
        elif persona.get("familia") and not _ella_nombro_la_familia(
                conversacion, persona["familia"]):
            # La clienta simulada no ha jugado su papel: la persona `cambia-de-idea`
            # tenia que pedir un corte a mitad y nunca lo pidio, asi que reservar lo
            # que SI pidio es correcto. Es fallo del simulador, no del producto:
            # se aparta del recuento en vez de ensuciar los fallos caros.
            resultado["veredicto"] = "sin_montar"
            resultado["motivo"] = "la clienta nunca pidio %s" % persona["familia"]
        elif persona.get("familia") and not _familia_ok(persona["familia"], nuevas[0]):
            resultado["veredicto"] = "fallo"
            resultado["motivo"] = "queria %s y le ha cogido %r" % (
                persona["familia"], nuevas[0]["servicio"])
            resultado["fallos"].append("servicio_equivocado")
        else:
            resultado["veredicto"] = "bien"
    elif objetivo == "hablar_con_persona":
        # Lo que se juzga no es lo que diga, sino que el asistente se CALLE: la
        # conversacion pasa a una persona y el bot deja de contestar encima.
        from backend import inbox, whatsapp

        if inbox.bot_is_muted(whatsapp._whatsapp_session_id(cliente_id, telefono)):
            resultado["veredicto"] = "bien"
        else:
            resultado["veredicto"] = "fallo"
            resultado["motivo"] = "pidio hablar con una persona y el asistente siguio solo"
            resultado["fallos"].append("no_pasa_a_una_persona")
    elif objetivo == "cancelar":
        # Lo que se juzga es que SU cita quedara cancelada, no que no quede
        # ninguna. Una clienta puede anular y, en la misma conversacion, pedir
        # otra: eso es un final bueno y se contaba como atasco. Paso el
        # 2-sep-2026 con una clienta que dijo "anular" y luego "no queria
        # cancelar" -son sinonimos-, y el asistente hizo lo correcto: le explico
        # que no podia revertirla y le busco hueco nuevo.
        suya = previa["booking_code"] if previa else ""
        sigue = any(c["booking_code"] == suya for c in vivas) if suya else bool(vivas)
        if sigue:
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
        elif vivas and not previa and objetivo in ("preguntar_precio", "consejo"):
            # Que acabe cogiendo cita al preguntar el precio -o al pedir consejo-
            # es EL OBJETIVO del negocio: no doy precio, te cito para verlo. Pero
            # tiene que ser la cita de VALORACION de 15 minutos, no el tratamiento
            # de 260 EUR a alguien a quien no han visto el pelo.
            # OJO: solo se exige la valoracion si el negocio la exige PARA ESA
            # familia. Un alisado se reserva directo (su regla es "pedir foto", no
            # "ofrecer cita"), asi que cogerle cita de alisado a quien preguntaba
            # su precio es CORRECTO. Exigir diagnostico a todo el mundo daba por
            # rotas 15 conversaciones de 100 que estaban bien.
            exige = _tiene_regla_de_no_precio(cliente_id, persona.get("familia", ""))
            if _es_diagnostico(vivas[0]) or not exige:
                resultado["veredicto"] = "bien"
            else:
                resultado["veredicto"] = "fallo"
                resultado["motivo"] = "le ha cogido %r en vez de la valoracion" % (
                    vivas[0]["servicio"])
                resultado["fallos"].append("cita_del_tratamiento_en_vez_de_valoracion")
        elif vivas and not previa and not _ella_pidio_cita(conversacion):
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


def _ofrecio_una_salida(cliente_id: str, dichos: List[str]) -> bool:
    """¿Le dio horas concretas de otro dia, o el telefono del salon?

    Es lo que se le pide cuando la cita es imposible: cualquiera de las dos vale,
    lo que no vale es despedirla sin nada.
    """
    from backend import clients

    texto = " ".join(dichos)
    if re.search("[0-9]{1,2}:[0-9]{2}", texto):
        return True
    telefono = clients.call_us_line(cliente_id)
    if telefono:
        digitos = "".join(c for c in telefono if c.isdigit())[:6]
        if digitos and digitos in "".join(c for c in texto if c.isdigit()):
            return True
    if any(p in _norm(texto) for p in ("llamanos", "llamar al", "que llames")):
        return True
    # Ofrecerle la cita de VALORACION tambien es darle una salida: en las familias
    # donde el negocio la exige (extensiones), es la unica puerta que hay. Sin
    # esto se contaba como fracaso una conversacion en la que el asistente explica
    # la regla, se ofrece a reservar la valoracion y mantiene el criterio del
    # salon; el fracaso seria despedirla sin ofrecerle nada.
    try:
        from backend import booking

        valoracion = booking._servicio_de_valoracion(cliente_id) or {}
        nombre = _norm(str(valoracion.get("nombre") or ""))
        cabeza = nombre.split()[0] if nombre else ""
        if cabeza and len(cabeza) >= 5 and cabeza in _norm(texto):
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _ella_pidio_el_diagnostico(conversacion: List[Dict[str, str]]) -> bool:
    """¿Pidio ELLA la cita de diagnostico, con sus palabras?

    "Si, agendame el diagnostico" y acabar con esa cita es el asistente haciendole
    caso. Contarlo como servicio equivocado -porque su objetivo era "mechas"-
    castigaba justo lo que el negocio quiere que pase.
    """
    for linea in conversacion:
        if linea["quien"] != "clienta":
            continue
        dicho = _norm(linea["texto"])
        if ("diagnostico" in dicho or "valoracion" in dicho) and any(
                v in dicho for v in ("agenda", "cita", "reserv", "coge", "quiero", "vale", "si,")):
            return True
    return False


def _ella_nombro_la_familia(conversacion: List[Dict[str, str]], familia: str) -> bool:
    """¿Llego a pedir eso alguna vez?

    La clienta la escribe un modelo y a veces no hace su papel: la persona
    `cambia-de-idea` tiene que pedir un corte a mitad de conversacion y hay
    tiradas en las que no lo pide nunca. Juzgar al asistente por no adivinarlo es
    medir el simulador, no el producto.
    """
    limpia = _norm(familia or "")
    if not limpia:
        return True
    raiz = limpia[:5]
    return any(raiz in _norm(l["texto"]) for l in conversacion if l["quien"] == "clienta")


def _es_diagnostico(cita: Dict[str, Any]) -> bool:
    """La cita de valoracion que este negocio ofrece en vez de dar un precio."""
    nombre = _norm(str(cita.get("servicio") or ""))
    return "diagnostico" in nombre or "valoracion" in nombre or "presupuesto" in nombre


_PATRONES_CAROS = (
    # Dañan la agenda: un hueco ocupado que no se vende, o una cita que ya no esta.
    "duplicada", "cita_sin_pedirla", "hay 0", "hay 2",
    # Mienten: la clienta se va creyendo algo que no es.
    "dice_que_hay_cita_y_no_la_hay", "precio_inventado", "servicio_equivocado",
    "en vez de la valoracion",
    # Pidio una persona y no la tuvo. En un hotel eso es la queja, no el chiste.
    "no_pasa_a_una_persona",
)


def _es_caro(patron: str) -> bool:
    """¿Este fallo le cuesta dinero o credibilidad, o solo cansa?

    CARO: daña la agenda, dice algo falso, o ignora que le pidan una persona.
    MOLESTO: repetir una pregunta, o que la clienta se canse y se vaya sin cita.
    Lo segundo es venta perdida y producto flojo; lo primero es un problema que el
    negocio tiene que arreglar A MANO delante de su cliente.

    La distincion existe porque el porcentaje global los mezclaba: cambiar dos
    molestos por un caro sale "igual" en la cifra y es mucho peor en el salon.
    """
    return any(clave in _norm(patron) for clave in _PATRONES_CAROS)


def _tiene_regla_de_no_precio(cliente_id: str, familia: str) -> bool:
    """¿Este negocio manda a esta familia a una CITA para dar el precio?

    Solo cuenta la regla que ofrece cita. La del alisado dice "pide foto y te
    contestamos", que es lo contrario: ahi el precio SI se da por mensaje y coger
    la cita del tratamiento a quien la pide es correcto -lo confirmo la duenya el
    5-sep-2026-. Sin esta distincion, el juez daba por rotas 3 conversaciones de
    100 en las que el asistente hizo exactamente lo que ella manda.
    """
    from backend import booking

    if not familia:
        return False
    # Solo donde la valoracion es OBLIGATORIA para el negocio. En mechas la duenya
    # lo dijo el 7-sep-2026: "le cogemos cita para mechas directamente, no es un
    # fallo" -se sugiere el diagnostico y decide ella-. Contarlo como fallo
    # castigaba 3 conversaciones de 100 en las que el asistente hizo lo correcto.
    try:
        return booking.la_valoracion_es_obligatoria(cliente_id, familia)
    except Exception:  # noqa: BLE001 - si no se puede saber, no se exige
        return False


def _mentiras(cliente_id: str, dichos: List[str], vivas: List[Dict[str, Any]]) -> List[str]:
    """Afirmaciones falsas comprobables contra los datos del negocio."""
    from backend import agent

    fallos = []
    texto = " ".join(dichos)
    # Solo cuenta como mentira lo que le queda en la cabeza AL IRSE, y por eso se
    # miran los ultimos mensajes y no todos.
    #
    # Juntandolos todos, una CANCELACION salia siempre marcada: el asistente decia
    # "tu cita esta confirmada para el jueves" -verdad en ese momento-, despues la
    # cancelaba, y al final no habia ninguna cita viva. Se daba por mentira algo
    # que era cierto al decirlo, y encima en el flujo que mejor funciona.
    if agent._da_la_cita_por_hecha(" ".join(dichos[-2:])) and not vivas:
        fallos.append("dice_que_hay_cita_y_no_la_hay")

    # Un precio para algo que este negocio NO presupuesta por mensaje.
    from backend import rules

    # La FIANZA no es un precio. El negocio EXIGE que se diga -"para reservar se
    # abona una fianza de 50 €"- y llevaba a marcar como mentira justo lo que la
    # duenya pidio. Medido: 14 de 100 conversaciones dadas por malas por esto, y
    # las 14 estaban bien. Se quitan las frases de fianza antes de buscar cifras.
    sin_fianza = " ".join(
        trozo for trozo in re.split("(?<=[.!?" + chr(10) + "])", texto)
        if "fianza" not in _norm(trozo) and "senal" not in _norm(trozo)
    )
    plano_sin_fianza = _norm(sin_fianza)
    if (("€" in sin_fianza or " euros" in plano_sin_fianza)
            and _habla_de(plano_sin_fianza, ("mecha", "balayage", "balay"))):
        regla = rules.match(cliente_id, {"intencion": "precio", "familia": "mechas"})
        # Una cifra que el negocio TIENE ESCRITA no es un precio inventado. La
        # duenya publica "Mecha test - 45 minutos, 20 €" en su propia regla, y
        # repetirsela a la clienta es hacer lo que ella pidio. Contarlo como fallo
        # critico me hizo leer "2 criticos" donde no habia ninguno y estuve a punto
        # de revertir un arreglo bueno (3-sep-2026). Mismo motivo por el que arriba
        # se quitan las frases de fianza.
        if regla is not None and _cifras_inventadas(cliente_id, sin_fianza):
            fallos.append("da_un_precio_que_no_debe")
    return fallos


_CIFRA = re.compile(r"(\d{1,5})(?:[.,]\d{1,2})?\s*(?:€|EUR|euros)", re.IGNORECASE)
_PUBLICADAS: Dict[str, set] = {}


def _cifras_publicadas(cliente_id: str) -> set:
    """Las cifras que el negocio tiene escritas: sus reglas y sus Q&A.

    Se cachea por tenant: se lee una vez por tirada, no una por conversacion.
    """
    if cliente_id in _PUBLICADAS:
        return _PUBLICADAS[cliente_id]
    textos = []
    try:
        from backend import rules

        textos.extend(str(r["texto"] or "") for r in rules.listar(cliente_id))
    except Exception:  # noqa: BLE001
        pass
    try:
        from backend import db

        with db._get_db_connection() as conexion:
            filas = conexion.execute(
                "SELECT answer FROM kb_qa WHERE cliente_id = ?", (cliente_id,)
            ).fetchall()
        textos.extend(str(f["answer"] or "") for f in filas)
    except Exception:  # noqa: BLE001
        pass
    cifras = set()
    for t in textos:
        cifras.update(_CIFRA.findall(t))
    _PUBLICADAS[cliente_id] = cifras
    return cifras


def _cifras_inventadas(cliente_id: str, texto: str) -> set:
    """Las cifras del mensaje que el negocio NO tiene escritas en ningun sitio."""
    return set(_CIFRA.findall(texto or "")) - _cifras_publicadas(cliente_id)


def _habla_de(plano: str, pistas) -> bool:
    return any(p in plano for p in pistas)


def _familia_ok(familia: str, cita: Dict[str, Any]) -> bool:
    return _norm(familia) in _norm(str(cita.get("servicio") or ""))


def _ella_pidio_cita(conversacion) -> bool:
    """Lo dijo ELLA, con sus palabras, en algun momento de la conversacion.

    Venir preguntando el horario y acabar cogiendo cita no es que se la cojan sin
    permiso: es que la han convencido, que es justo lo que el negocio quiere. Se
    contaba como fallo y castigaba una conversion. Lo que hay que detectar es la
    cita que aparece SIN que ella la pida en ningun momento.
    """
    from backend import textnorm

    pistas = ("quiero", "me vale", "confirmo", "resérvame", "reservame", "cogeme",
              "cogedme", "apuntame", "apuntadme", "ponme", "cita", "me viene bien",
              "me llamo", "de acuerdo", "vale, ponme")
    for turno in conversacion:
        if turno.get("quien") != "clienta":
            continue
        dicho = textnorm._strip_accents(str(turno.get("texto") or "").lower())
        if any(p in dicho for p in pistas):
            return True
    return False


def _se_repite(dichos: List[str]) -> bool:
    """¿Esta contestando lo mismo una y otra vez?

    Visto de verdad: a una clienta que insistio cuatro veces le solto CUATRO veces
    la misma respuesta palabra por palabra. Para quien escribe, eso es un muro.
    """
    # El RESUMEN con botones no cuenta. Es un formulario, no una respuesta: cuando
    # ella corrige un dato hay que volver a ensenyarselo, y eso es lo correcto.
    # Contarlo como repetirse marcaba conversaciones bien llevadas.
    vistas = [_norm(t)[:80] for t in dichos
              if t.strip() and "resumen de tu cita" not in _norm(t)]
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
        # Un fallo CARO le cuesta dinero o credibilidad: una cita duplicada, una
        # perdida, un precio inventado, un "ya te la he cogido" sin cita. Uno
        # MOLESTO cansa a la clienta pero no cuesta nada. Pesaban igual en el
        # porcentaje, y por eso el numero global no servia para decidir: cambiar
        # dos molestos por un caro sale "igual" y es mucho peor.
        caros = [(p, n) for p, n in informe["patrones"] if _es_caro(p)]
        molestos = [(p, n) for p, n in informe["patrones"] if not _es_caro(p)]
        print("\n  FALLOS CAROS (dinero o credibilidad): %s"
              % ("ninguno" if not caros else ""))
        for patron, veces in caros:
            print("   %3d x  %s" % (veces, patron))
        if molestos:
            print("\n  FALLOS MOLESTOS (cansan, no cuestan):")
            for patron, veces in molestos:
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
    parser.add_argument("--modelo", default="",
                        help="prueba con otro modelo (gpt-4o, gpt-4.1-mini...). Solo "
                             "en ESTE proceso: no cambia lo que ven los clientes")
    parser.add_argument("--persona", default="", help="solo esta clienta (para mirar un patron)")
    args = parser.parse_args()

    from evals import arnes, clientas

    arnes.preparar_copia(args.db_origen, args.db_copia)

    if args.modelo:
        # El agente usa el modelo que el negocio tiene en su config. Se cambia
        # SOLO en la memoria de este proceso -que es el de la medicion, no el que
        # atiende a los clientes- para poder comparar modelos sin arriesgar nada.
        from backend import appstate, clients

        actual = dict(clients._get_client_config(args.cliente))
        actual["chat_model"] = args.modelo
        appstate.CONFIG_CLIENTES[args.cliente] = actual
        print("  (midiendo con el modelo %s)" % args.modelo)
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
        try:
            resultado = _conversar(args.cliente, combinacion, telefono)
        except arnes.InstrumentoNoCompatible as exc:
            print(str(exc))
            return 1
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
    informe["instrumento"] = arnes.VERSION_INTERACCION
    anterior = None
    if args.comparar and os.path.exists(args.comparar):
        with open(args.comparar, encoding="utf-8") as fichero:
            anterior = json.load(fichero)
        if anterior.get("instrumento") != arnes.VERSION_INTERACCION:
            print("Informe historico de otro instrumento: no se comparan porcentajes.")
            anterior = None
    _pintar(informe, anterior)

    if args.guardar:
        with open(args.guardar, "w", encoding="utf-8") as fichero:
            json.dump(informe, fichero, ensure_ascii=False, indent=2)
        print("\n  guardado en %s" % args.guardar)
        # Y las conversaciones que salieron mal, ENTERAS. Sin esto, el informe
        # dice "14 x repite_la_misma_pregunta" y averiguar QUE pregunta repite
        # obliga a pagar otra tirada de 100 conversaciones. Asi es gratis.
        rotas = [r for r in resultados if r["veredicto"] != "bien"]
        camino = args.guardar.rsplit(".", 1)[0] + ".fallos.json"
        with open(camino, "w", encoding="utf-8") as fichero:
            json.dump([{
                "id": r["id"], "objetivo": r["objetivo"], "veredicto": r["veredicto"],
                "motivo": r.get("motivo", ""), "fallos": r["fallos"],
                "conversacion": r["conversacion"],
            } for r in rotas], fichero, ensure_ascii=False, indent=2)
        print("  las %d rotas, enteras, en %s" % (len(rotas), camino))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
