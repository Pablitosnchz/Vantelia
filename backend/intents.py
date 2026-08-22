# -*- coding: utf-8 -*-
"""Qué quiere el cliente: comprensión de intenciones para el chat.

POR QUE EXISTE ESTE MODULO
--------------------------
La intención se adivinaba con expresiones regulares. De 19 formas naturales de
pedir cita, se reconocian DOS: "quiero agendare una cita" contestaba pidiendo los
datos a mano, y "me pones una cita?", "resérvame el jueves" o "quiero pedir hora"
no abrian el formulario. Cada variante nueva era un parche, y el español tiene
infinitas maneras de pedir lo mismo.

Aquí la intención la decide el MODELO, que es lo que sabe hacer: leer una frase y
decir qué pide. Los patrones siguen existiendo como ATAJO —si uno casa, no se
gasta una llamada— pero dejan de ser la única fuente de verdad.

COMO ENCAJA
-----------
1. `atajo_local()`   resuelve gratis lo evidente ("agendar cita", "cancelar").
2. `classify()`      pregunta al modelo cuando el atajo no lo tiene claro.
3. `backend/rules.py` decide QUE HACER con esa intención, según lo que cada
   negocio haya configurado.

REGLAS DE LA CASA
-----------------
* Esto NUNCA puede dejar a un cliente sin respuesta: si el modelo falla, tarda o
  no está configurado, se devuelve `None` y el chat sigue por donde iba.
* Las familias de servicio salen del CATALOGO del propio tenant, no de una lista
  fija: en un salón serán alisados y mechas; en una clínica, tratamientos.
* Opt-in por tenant (`config['ai_intents']['enabled']`), para poder encenderlo en
  un cliente sin tocar a los demás.
"""
from __future__ import annotations

import json
import time
import unicodedata
from typing import Any, Dict, List, Optional

from backend import agenda, appstate, clients, rag, settings

# Lo que un cliente puede querer. Cerrada a proposito: una lista abierta hace que
# el modelo invente etiquetas y que las reglas del negocio no casen nunca.
INTENCIONES = (
    "reservar",        # quiere cita
    "cancelar",        # quiere anular una que tiene
    "reprogramar",     # quiere moverla
    "disponibilidad",  # pregunta si hay hueco / cuando
    "precio",          # cuanto cuesta
    "presupuesto",     # quiere que le presupuesten su caso concreto
    "info",            # duda general del negocio (horario, donde estan, que hacen)
    "pago",            # quiere pagar / enlace de pago
    "agradecimiento",  # da las gracias
    "queja",           # esta molesto
    "otro",
)

# Cuanto se guarda la clasificacion de un mensaje identico (segundos). Evita
# pagar dos veces por el mismo texto en una conversacion que se repite.
_CACHE_TTL = 600
_CACHE_MAX = 500
# El catalogo y las Q&A los edita una persona desde el panel: no hace falta
# releerlos en cada mensaje, pero tampoco pueden tardar en verse.
_CATALOGO_TTL = 300

# Por debajo de esto se descarta la clasificacion y el chat sigue como siempre.
# Actuar con una corazonada floja es peor que no actuar: le abre un formulario de
# cita a quien solo preguntaba una direccion.
CONFIANZA_MINIMA = 0.55


def _norm(texto: str) -> str:
    limpio = unicodedata.normalize("NFKD", str(texto or "").lower())
    return " ".join("".join(c for c in limpio if not unicodedata.combining(c)).split())


def config_enabled(cliente_id: str, config: Optional[Dict[str, Any]] = None) -> bool:
    """Lo que el negocio ha PEDIDO en su panel, tenga o no clave de OpenAI.

    Separado de `enabled_for` a proposito: el interruptor del panel tiene que
    mostrar lo que el negocio guardo, no si hoy podemos ejecutarlo. Si no, al
    faltar la clave el interruptor volveria solo a apagado despues de encenderlo.
    """
    try:
        cfg = config if config is not None else clients._get_client_config(cliente_id)
    except Exception:  # noqa: BLE001
        return False
    seccion = cfg.get("ai_intents") if isinstance(cfg, dict) else None
    return bool(isinstance(seccion, dict) and seccion.get("enabled"))


def enabled_for(cliente_id: str, config: Optional[Dict[str, Any]] = None) -> bool:
    """¿Se puede clasificar ahora mismo? Lo que pidio el negocio Y hay con que."""
    if not settings.OPENAI_API_KEY:
        return False
    try:
        cfg = config if config is not None else clients._get_client_config(cliente_id)
    except Exception:  # noqa: BLE001
        return False
    seccion = cfg.get("ai_intents") if isinstance(cfg, dict) else None
    return bool(isinstance(seccion, dict) and seccion.get("enabled"))


def _cacheado(clave: str, calcular):
    """Memoria corta para datos que edita una persona, no el trafico.

    El catalogo de un salon puede tener cientos de servicios: releerlo entero en
    cada mensaje es trabajo tirado. Unos minutos de desfase tras editar el panel
    es un precio razonable.
    """
    with appstate.state_lock:
        entrada = appstate.intent_cache.get(clave)
        if entrada and time.time() - entrada["ts"] <= _CATALOGO_TTL:
            return entrada["valor"]
    valor = calcular()
    with appstate.state_lock:
        appstate.intent_cache[clave] = {"ts": time.time(), "valor": valor}
    return valor


def familias_del_tenant(cliente_id: str) -> List[str]:
    """Familias de servicio de ESTE negocio, sacadas de su catalogo.

    Se usan las categorias que el negocio ya tiene (Alisados, Trabajos de color,
    Peinados...) mas las primeras palabras de los servicios: asi el modelo puede
    decir "alisado" o "mechas" sin que nadie haya escrito esa lista a mano.
    """
    return _cacheado("familias|%s" % cliente_id, lambda: _familias_del_tenant(cliente_id))


def _familias_del_tenant(cliente_id: str) -> List[str]:
    familias: List[str] = []
    vistas = set()
    try:
        servicios = agenda._catalog_services(cliente_id)
    except Exception:  # noqa: BLE001
        return []
    for servicio in servicios:
        for candidata in (servicio.get("category"), (servicio.get("nombre") or "").split(" ")[0]):
            clave = _norm(candidata)
            if len(clave) < 4 or clave in vistas:
                continue
            vistas.add(clave)
            familias.append(clave)
    return familias[:40]


def preguntas_del_tenant(cliente_id: str, limite: int = 40) -> List[Dict[str, str]]:
    """Preguntas que el negocio ya tiene respondidas, para que el modelo las reconozca.

    Antes casaban por etiquetas literales y habia que escribir a mano cada forma
    de preguntar lo mismo. El limite existe porque estas preguntas viajan en el
    prompt: con mas de 40 conviene acotar antes por otro medio.
    """
    return _cacheado(
        "preguntas|%s|%d" % (cliente_id, limite),
        lambda: _preguntas_del_tenant(cliente_id, limite),
    )


def _preguntas_del_tenant(cliente_id: str, limite: int = 40) -> List[Dict[str, str]]:
    try:
        filas = rag._list_qa_rows(cliente_id)
    except Exception:  # noqa: BLE001
        return []
    salida: List[Dict[str, str]] = []
    for fila in filas[:limite]:
        pregunta = str(fila["question"] if "question" in fila.keys() else "").strip()
        respuesta = str(fila["answer"] if "answer" in fila.keys() else "").strip()
        if pregunta and respuesta:
            salida.append({
                "id": str(fila["id"] if "id" in fila.keys() else ""),
                "question": pregunta,
                "answer": respuesta,
            })
    return salida


# ─── Atajos: lo evidente no necesita modelo ────────────────────────────────

_ATAJOS = (
    # (intencion, frases que la dan por segura)
    ("cancelar", ("quiero cancelar", "cancelar mi cita", "anular mi cita")),
    ("reprogramar", ("quiero cambiar mi cita", "cambiar la cita", "reprogramar mi cita")),
    ("agradecimiento", ("gracias", "muchas gracias", "mil gracias")),
    ("reservar", ("agendar cita", "pedir cita", "coger cita", "reservar cita")),
)


def atajo_local(message: str) -> str:
    """Intencion segura sin gastar una llamada. Cadena vacia si no esta claro."""
    texto = _norm(message)
    if not texto:
        return ""
    for intencion, frases in _ATAJOS:
        if any(frase in texto for frase in frases):
            # "gracias" a secas es agradecimiento; con una pregunta detras, no.
            if intencion == "agradecimiento" and ("?" in message or len(texto.split()) > 4):
                continue
            return intencion
    return ""


# ─── Del lenguaje de la clienta al servicio exacto ─────────────────────────

_PROMPT_SERVICIO = """Eres quien coge las citas en un negocio. La clienta describe
lo que quiere con sus palabras; tu tarea es decidir QUE servicio del catalogo es.

CATALOGO (son los unicos nombres validos):
{catalogo}

Lo que ha dicho la clienta hasta ahora:
{dicho}

Responde SOLO con un JSON:

{{"servicio": "<nombre EXACTO del catalogo>", "pregunta": "", "opciones": []}}

Reglas:
- Si con lo dicho basta para elegir UNO, pon su nombre exacto y deja "pregunta" vacia.
- Si YA te ha dado el dato que faltaba (por ejemplo el largo del pelo), ELIGE. No
  vuelvas a preguntar por algo que ya ha dicho, ni le pidas otro detalle mas.
- Pregunta UNA sola cosa por turno, y que sea justo lo que separa a los servicios
  entre los que dudas. Si dudas entre "Corte hombre" y "Corte señora", lo que falta
  es para quien es, no el largo.
- Si los candidatos son TECNICAS distintas -sus nombres EMPIEZAN distinto, como
  "Keratina premium largo" y "Acido lactico bio premium-largo"- NO elijas por ella
  aunque sepas el largo: son tratamientos diferentes, con precio y proceso propios.
  Preguntale cual prefiere, con naturalidad, y anade que si no lo tiene claro se lo
  asesoran en la cita.
- Si son la MISMA tecnica en tallas distintas (corto / medio / largo) y ya sabes su
  largo, elige sin preguntar.
- Si lo que falta es el LARGO, preguntaselo por su pelo ("¿como tienes el pelo de
  largo?"), no por "que tipo de servicio quieres": ella no conoce vuestros nombres.
- Escribe la pregunta como se la haria una companera del salon: una frase corta,
  calida y natural. Nada de listas numeradas, tecnicismos ni "por favor indique".
- Si dudas entre pocos servicios concretos, ponlos en "opciones" (nombres exactos)
  ademas de la pregunta.
- NUNCA propongas un servicio que no resuelve lo que te cuenta. Un alisado no
  frena la caida del pelo ni rejuvenece: si lo que describe es un PROBLEMA del
  cabello, mira la familia que le corresponde (tratamientos, color, corte...).
- Si lo que dice es vago ("no se que hacerme", "quiero verme mejor", "algo para un
  evento"), NO adivines un tratamiento concreto: si el catalogo tiene una cita de
  diagnostico o valoracion, ofrecesela; si no, preguntale que tipo de servicio
  busca nombrando 2 o 3 FAMILIAS del catalogo, no servicios sueltos.
- Si ya te ha dado un dato que decide por si solo (la edad de un niño, el largo
  del pelo, para quien es), ELIGE con ese dato en vez de volver a preguntarlo.
- Si lo que pide NO existe en el catalogo, deja "servicio" y "opciones" vacios y en
  "pregunta" dilo con amabilidad y ofrece lo mas parecido que si haya.
- NUNCA te inventes un nombre que no este en el catalogo.
- No hables de precios: no los menciones aunque los veas en la lista."""


def resolver_servicio(
    cliente_id: str, dicho: str, *, config: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, Any]]:
    """Que servicio quiere, o que hay que preguntarle para saberlo.

    `dicho` es TODO lo que la clienta ha dicho sobre el servicio (se va acumulando
    entre turnos: "mechas" + "por los hombros").

    Devuelve {"servicio", "pregunta", "opciones"} o None si no se puede resolver
    (sin clave, sin catalogo o fallo del modelo): quien llama debe tener siempre un
    plan B, porque quedarse sin respuesta no es una opcion.
    """
    texto = str(dicho or "").strip()
    if not texto or not settings.OPENAI_API_KEY:
        return None
    try:
        from backend import booking

        catalogo, _completo = booking._service_catalog_prompt_block(cliente_id)
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("[servicio] sin catalogo (%s): %s", cliente_id, exc)
        return None
    if not catalogo.strip():
        return None

    try:
        from openai import OpenAI as OpenAISdkClient

        cliente = OpenAISdkClient(api_key=settings.OPENAI_API_KEY, timeout=12.0)
        respuesta = cliente.chat.completions.create(
            model=settings.DEFAULT_CHAT_MODEL,
            messages=[
                {"role": "system", "content": _PROMPT_SERVICIO.format(
                    catalogo=catalogo, dicho=texto[:600],
                )},
                {"role": "user", "content": texto[:600]},
            ],
            temperature=0,
            max_tokens=220,
            response_format={"type": "json_object"},
        )
        datos = json.loads((respuesta.choices[0].message.content or "").strip())
    except Exception as exc:  # noqa: BLE001 - nunca puede dejar a nadie sin respuesta
        settings.logger.warning("[servicio] no se pudo resolver (%s): %s", cliente_id, exc)
        return None

    nombres = {
        linea.lstrip("- ").split(" · ")[0].strip()
        for linea in catalogo.splitlines() if linea.startswith("- ")
    }
    elegido = str(datos.get("servicio") or "").strip()
    if elegido and elegido not in nombres:
        # El modelo se ha inventado un nombre: se trata como "no resuelto" en vez de
        # intentar reservar algo que no existe.
        settings.logger.info("[servicio] nombre fuera de catalogo (%s): %r", cliente_id, elegido)
        elegido = ""
    opciones = [o for o in (datos.get("opciones") or []) if isinstance(o, str) and o in nombres]
    return {
        "servicio": elegido,
        "pregunta": str(datos.get("pregunta") or "").strip()[:300],
        "opciones": opciones[:4],
    }


# ─── Comprension con el modelo ─────────────────────────────────────────────

_PROMPT = """Eres un clasificador para el asistente de un negocio. Lee el mensaje
del cliente y responde SOLO con un JSON:

{{"intencion": "...", "familia": "...", "pregunta": 0, "confianza": 0.0}}

"intencion" es EXACTAMENTE una de estas: {intenciones}
  - reservar: quiere cita (aunque no diga "cita": "me pones algo el jueves", "hazme un hueco")
  - cancelar / reprogramar: sobre una cita que YA tiene
  - disponibilidad: pregunta si hay hueco o cuando hay
  - precio: cuanto cuesta algo, en general
  - presupuesto: quiere que le presupuesten SU caso ("cuanto me costaria a mi")
  - info: horario, direccion, que servicios hacen, dudas del negocio
  - pago: quiere pagar o el enlace de pago
  - agradecimiento / queja / otro

"familia" es el tipo de servicio si lo menciona, en minusculas y sin tildes.
Familias de este negocio: {familias}
Si no menciona ninguno, "familia": "".

"pregunta": el negocio tiene estas preguntas ya respondidas. Si el cliente esta
haciendo UNA DE ELLAS —aunque lo diga con otras palabras— pon su numero. Si no
esta preguntando ninguna de estas, pon 0.
{preguntas}

"confianza" de 0 a 1: cuan seguro estas.

No expliques nada. Solo el JSON."""


def _cache_get(clave: str) -> Optional[Dict[str, Any]]:
    with appstate.state_lock:
        entrada = appstate.intent_cache.get(clave)
        if not entrada:
            return None
        if time.time() - entrada["ts"] > _CACHE_TTL:
            appstate.intent_cache.pop(clave, None)
            return None
        return dict(entrada["valor"])


def _cache_put(clave: str, valor: Dict[str, Any]) -> None:
    with appstate.state_lock:
        ahora = time.time()
        if len(appstate.intent_cache) >= _CACHE_MAX:
            for vieja in [k for k, v in appstate.intent_cache.items()
                          if ahora - v["ts"] > _CACHE_TTL][:100]:
                appstate.intent_cache.pop(vieja, None)
            if len(appstate.intent_cache) >= _CACHE_MAX:
                appstate.intent_cache.clear()
        appstate.intent_cache[clave] = {"ts": ahora, "valor": dict(valor)}


def classify(
    cliente_id: str, message: str, *, config: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, Any]]:
    """Qué pide el cliente. `None` si no se puede saber (y el chat sigue igual).

    Devuelve {"intencion", "familia", "confianza", "fuente"}. `fuente` es
    "atajo" o "modelo", util para depurar por que se respondio lo que se respondio.
    """
    texto = _norm(message)
    if not texto:
        return None
    # Un "1" del menu es una tecla, no una frase: no hay nada que entender ni que
    # pagar. Los atajos y el menu de siempre se encargan.
    if texto.isdigit():
        return None

    atajo = atajo_local(message)
    if atajo:
        return {"intencion": atajo, "familia": "", "confianza": 1.0, "fuente": "atajo"}

    if not enabled_for(cliente_id, config):
        return None

    clave = "%s|%s" % (cliente_id, texto[:200])
    guardada = _cache_get(clave)
    if guardada is not None:
        return guardada

    familias = familias_del_tenant(cliente_id)
    preguntas = preguntas_del_tenant(cliente_id)
    listado = "\n".join(
        "%d. %s" % (i + 1, q["question"][:140]) for i, q in enumerate(preguntas)
    ) or "(ninguna)"
    try:
        from openai import OpenAI as OpenAISdkClient  # import local, como en voice

        cliente = OpenAISdkClient(api_key=settings.OPENAI_API_KEY, timeout=8.0)
        respuesta = cliente.chat.completions.create(
            model=settings.DEFAULT_CHAT_MODEL,
            messages=[
                {"role": "system", "content": _PROMPT.format(
                    intenciones=", ".join(INTENCIONES),
                    familias=", ".join(familias) or "(sin catalogo)",
                    preguntas=listado,
                )},
                {"role": "user", "content": str(message)[:600]},
            ],
            temperature=0,
            max_tokens=80,
            response_format={"type": "json_object"},
        )
        crudo = (respuesta.choices[0].message.content or "").strip()
        datos = json.loads(crudo)
    except Exception as exc:  # noqa: BLE001 - entender nunca puede tumbar el chat
        settings.logger.warning("[intents] no se pudo clasificar (%s): %s", cliente_id, exc)
        return None

    intencion = _norm(datos.get("intencion"))
    if intencion not in INTENCIONES:
        return None
    try:
        confianza = max(0.0, min(1.0, float(datos.get("confianza") or 0)))
    except (TypeError, ValueError):
        confianza = 0.0
    if confianza < CONFIANZA_MINIMA:
        settings.logger.info(
            "[intents] descartada por poca confianza (%.2f) en %s: %s",
            confianza, cliente_id, texto[:80],
        )
        return None
    resultado = {
        "intencion": intencion,
        "familia": _norm(datos.get("familia"))[:60],
        "confianza": confianza,
        "fuente": "modelo",
        "qa_id": "",
        "qa_answer": "",
    }
    # ¿Le estan haciendo una de las preguntas que el negocio ya tiene respondidas?
    try:
        indice = int(datos.get("pregunta") or 0)
    except (TypeError, ValueError):
        indice = 0
    if 1 <= indice <= len(preguntas):
        elegida = preguntas[indice - 1]
        resultado["qa_id"] = elegida.get("id", "")
        resultado["qa_answer"] = elegida.get("answer", "")
    _cache_put(clave, resultado)
    return resultado
