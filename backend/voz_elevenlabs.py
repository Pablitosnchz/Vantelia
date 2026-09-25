"""Voz con ElevenLabs Agents: la voz y los turnos los pone ElevenLabs, lo demas es nuestro.

POR QUE EXISTE
--------------
Pablo comparo a oido (23-sep-2026) las voces de OpenAI (gpt-realtime y GPT-Live) con
voces castellanas nativas de ElevenLabs y eligio "Laura": las de OpenAI nacen en
ingles y se les nota el acento. ElevenLabs Agents pone la voz, el oido y el modelo de
turnos; nosotros seguimos poniendo lo que la voz DICE y lo que HACE.

QUE ES NUESTRO (una sola fuente, compartida con la voz de OpenAI)
------------------------------------------------------------------
- instrucciones: `voice._voice_build_instructions`
- saludo:        `textnorm._voice_default_greeting` (con el aviso de IA del art. 50)
- herramientas:  `voice._voice_booking_tools`, convertidas a herramientas "webhook" de
  ElevenLabs. ElevenLabs llama a `POST /voice/el/{cliente_id}/tool/{nombre}` y ahi se
  ejecuta `voice._voice_dispatch_tool`: la UNICA forma de tocar la agenda desde la voz.

Un agente por negocio, creado o actualizado con `sincronizar_agente`; su id se guarda
en `config['voice']['elevenlabs_agent_id']`. Sin `ELEVENLABS_API_KEY` y
`ELEVENLABS_TOOL_SECRET` no se hace nada.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional

import httpx

from backend import appstate, clients, settings, textnorm, voice

API = "https://api.elevenlabs.io"
# Un agente en espanol solo admite los modelos rapidos (lo exige ElevenLabs). Flash es
# el que sono bien a Pablo en calidad de telefono y tarda ~0,2 s en empezar a hablar.
MODELO_VOZ = "eleven_flash_v2_5"
# gpt-4.1-mini: Gemini 2.5 Flash colo frases en ingles y se quedo mudo al cerrar
# (segunda llamada de prueba de Sara, 24-sep-2026).
LLM_POR_DEFECTO = "gpt-4.1-mini"
CABECERA_SECRETO = "X-Vantelia-Voz"
# Herramientas nuestras que tienen equivalente de sistema en ElevenLabs.
_DE_SISTEMA = {"finalizar_llamada": "end_call"}
# Solo tienen sentido con telefono (se anadiran con el numero).
_SOLO_TELEFONO = {"transferir_a_humano"}


def configurado() -> bool:
    return bool(settings.ELEVENLABS_API_KEY and settings.ELEVENLABS_TOOL_SECRET)


def secreto_valido(recibido: str) -> bool:
    """La peticion trae el secreto que solo conocemos nosotros y ElevenLabs."""
    import hmac

    esperado = settings.ELEVENLABS_TOOL_SECRET
    return bool(esperado) and hmac.compare_digest(str(recibido or "").encode(), esperado.encode())


def _cabeceras() -> Dict[str, str]:
    return {"xi-api-key": settings.ELEVENLABS_API_KEY}


def _esquema(parametros: Dict[str, Any], nombre: str = "") -> Dict[str, Any]:
    """JSON Schema de nuestras tools -> el de ElevenLabs, que exige descripcion en todo."""
    tipo = parametros.get("type") or "string"
    salida: Dict[str, Any] = {"type": tipo,
                              "description": str(parametros.get("description") or nombre or "Dato")}
    if tipo == "object":
        propiedades = parametros.get("properties") or {}
        salida["properties"] = {clave: _esquema(valor or {}, clave) for clave, valor in propiedades.items()}
        salida["required"] = [r for r in (parametros.get("required") or []) if r in propiedades]
    elif tipo == "array":
        salida["items"] = _esquema(parametros.get("items") or {"type": "string"}, nombre)
    if parametros.get("enum"):
        salida["enum"] = list(parametros["enum"])
    return salida


# Por telefono, quien llama llega como variable de la conversacion (la pasamos al
# registrar la llamada) y viaja en cada tool: es con lo que se verifica que una cita
# es suya antes de cancelarla o moverla, igual que en el puente de Twilio.
VARIABLE_LLAMANTE = "llamante"
CAMPO_LLAMANTE = "_llamante"


def herramienta_webhook(nombre: str, descripcion: str, url: str, esquema: Dict[str, Any],
                        variables: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Una tool de ElevenLabs que llama a nuestra API con el secreto compartido.

    `variables` = {campo: variable_dinamica}: campos que rellena ElevenLabs con datos de
    la conversacion (quien llama, a quien llamamos), no el modelo.
    """
    cuerpo = copy.deepcopy(esquema)
    cuerpo.setdefault("properties", {})
    for campo, variable in (variables or {}).items():
        cuerpo["properties"][campo] = {"type": "string", "dynamic_variable": variable}
    return {
        "type": "webhook",
        "name": nombre,
        "description": descripcion or nombre,
        "api_schema": {
            "url": url,
            "method": "POST",
            "request_headers": {CABECERA_SECRETO: settings.ELEVENLABS_TOOL_SECRET},
            "request_body_schema": cuerpo,
        },
    }


def colgar(descripcion: str = "") -> Dict[str, Any]:
    return {"type": "system", "name": "end_call",
            "description": descripcion or "Termina la llamada cuando la conversacion ha concluido. Despidete antes.",
            "params": {"system_tool_type": "end_call"}}


def herramientas(cliente_id: str, config: Dict[str, Any], base_url: str, *,
                 telefono: bool = False) -> List[Dict[str, Any]]:
    """Las tools de cita del negocio en el formato de ElevenLabs."""
    salida: List[Dict[str, Any]] = []
    variables = {CAMPO_LLAMANTE: VARIABLE_LLAMANTE} if telefono else None
    for tool in voice._voice_booking_tools(cliente_id, config):
        nombre = str(tool.get("name") or "")
        if nombre in _SOLO_TELEFONO:
            continue
        if nombre in _DE_SISTEMA:
            salida.append(colgar(str(tool.get("description") or "")))
            continue
        salida.append(herramienta_webhook(
            nombre, str(tool.get("description") or nombre),
            "%s/voice/el/%s/tool/%s" % (base_url.rstrip("/"), cliente_id, nombre),
            _esquema(tool.get("parameters") or {"type": "object", "properties": {}}, nombre),
            variables))
    if not any(t.get("name") == "end_call" for t in salida):
        salida.append(colgar())
    return salida


# Voz mas estable que la de serie (0,5 / 0,8): en la primera llamada de prueba de un
# negocio (24-sep-2026) Pablo noto que "a veces le cambiaba la voz". Mas estabilidad =
# menos saltos de tono entre frases; mas parecido = mas fiel a la Laura original.
AJUSTES_DE_VOZ = {"stability": 0.7, "similarity_boost": 0.9}


def formato_de_audio(telefono: bool) -> Dict[str, Any]:
    """Web a 44,1 kHz; telefono en u-law 8 kHz, lo que habla Twilio (entrada y salida).
    Lleva tambien los ajustes de voz, comunes a Sara y a los agentes de los negocios."""
    if telefono:
        return {"asr": {"user_input_audio_format": "ulaw_8000"},
                "tts": dict(AJUSTES_DE_VOZ, agent_output_audio_format="ulaw_8000")}
    return {"asr": {}, "tts": dict(AJUSTES_DE_VOZ, agent_output_audio_format="pcm_44100")}


# Por telefono ya sabemos desde que numero llaman. En la primera llamada de prueba
# (24-sep-2026) la agente se lo pidio igualmente a quien llamaba desde el.
LLAMANTE_EN_EL_PROMPT = (
    "\n\nTELEFONO DE QUIEN LLAMA: {{" + VARIABLE_LLAMANTE + "}}. Si aparece un numero, es el telefono "
    "desde el que llama: usalo como su telefono al crear la cita y NO se lo pidas. Solo si dice que "
    "quiere dar otro, usa el que te diga.")


def agente_para(cliente_id: str, config: Dict[str, Any], base_url: str, *,
                telefono: bool = False) -> Dict[str, Any]:
    """Lo que se manda a ElevenLabs para crear o actualizar el agente del negocio."""
    voice_cfg = config.get("voice") or {}
    nombre = str(config.get("empresa") or config.get("nombre") or cliente_id).strip()
    audio = formato_de_audio(telefono)
    agente: Dict[str, Any] = {
        "first_message": textnorm._voice_default_greeting(config, voice_cfg),
        "language": "es",
        "prompt": {
            "prompt": voice._voice_build_instructions(cliente_id, config),
            "llm": str(voice_cfg.get("elevenlabs_llm") or LLM_POR_DEFECTO),
            "temperature": 0.5,
            "tools": herramientas(cliente_id, config, base_url, telefono=telefono),
        },
    }
    if telefono:
        agente["dynamic_variables"] = {"dynamic_variable_placeholders": {VARIABLE_LLAMANTE: ""}}
        agente["prompt"]["prompt"] += LLAMANTE_EN_EL_PROMPT
    return {
        "name": "%s (%s)%s" % (nombre, cliente_id, " - telefono" if telefono else ""),
        "conversation_config": {
            "agent": agente,
            "asr": audio["asr"],
            "tts": dict({
                "voice_id": str(voice_cfg.get("elevenlabs_voice_id") or settings.ELEVENLABS_VOICE_ID),
                "model_id": MODELO_VOZ,
            }, **audio["tts"]),
            "turn": {"speculative_turn": True},
        },
    }


def guardar_en_voz(cliente_id: str, clave: str, valor: str) -> None:
    """Guarda un dato de voz del negocio. Vacio = quitarlo: la vuelta atras de una rotacion
    tiene que dejar SIN agente de telefono a quien no lo tenia (revision de Astra, 25-sep)."""
    siguientes = copy.deepcopy(appstate.CONFIG_CLIENTES)
    voz = siguientes[cliente_id].setdefault("voice", {})
    if valor:
        voz[clave] = valor
    else:
        voz.pop(clave, None)
    clients._persist_configs_to_disk(siguientes)
    clients._update_runtime_configs(siguientes)


def _tool_ids(cliente: httpx.Client, agent_id: str) -> Optional[List[str]]:
    """Las tools del agente, o None si el agente no existe en esta cuenta."""
    r = cliente.get("%s/v1/convai/agents/%s" % (API, agent_id), headers=_cabeceras())
    if r.status_code == 404:
        return None
    r.raise_for_status()
    prompt = ((r.json().get("conversation_config") or {}).get("agent") or {}).get("prompt") or {}
    return list(prompt.get("tool_ids") or [])


# Voces de la biblioteca de ElevenLabs que usamos: id -> (dueno publico, nombre). Con el
# dueno se anade la voz a una cuenta nueva y conserva el mismo id.
VOCES_DE_BIBLIOTECA = {
    "uQw4jpKzMLrZuo0RLPS9": ("a878d61205d24b1a767fae2ab15c6dcf56cebdf388f11c8ad6a80f5a20e137f1",
                             "Laura - Customer service"),
}


def asegurar_voz(cliente: httpx.Client, voice_id: str) -> None:
    """La voz tiene que estar en la cuenta de la clave: en una cuenta nueva no esta
    (cambio a otra cuenta Creator, 24-sep-2026). Si es de la biblioteca, se anade."""
    dueno = VOCES_DE_BIBLIOTECA.get(voice_id)
    if not dueno:
        return
    if cliente.get("%s/v1/voices/%s" % (API, voice_id), headers=_cabeceras()).status_code == 200:
        return
    r = cliente.post("%s/v1/voices/add/%s/%s" % (API, dueno[0], voice_id), headers=_cabeceras(),
                     json={"new_name": dueno[1]})
    if r.status_code >= 400:
        raise RuntimeError("No se pudo anadir la voz %s a la cuenta (%s): %s" % (dueno[1], r.status_code, r.text[:200]))


def publicar_agente(cliente: httpx.Client, cuerpo: Dict[str, Any], agent_id: str = "") -> str:
    """Crea (sin id) o actualiza (con id) un agente. Devuelve su id.

    Cada guardado con tools en linea crea herramientas nuevas en la cuenta; las que el
    agente deja de usar se borran para que no se acumulen (una por tool y guardado).
    """
    asegurar_voz(cliente, str(((cuerpo.get("conversation_config") or {}).get("tts") or {}).get("voice_id") or ""))
    antes: List[str] = []
    if agent_id:
        previas = _tool_ids(cliente, agent_id)
        if previas is None:
            # El id guardado es de otra cuenta (se cambio la clave de ElevenLabs, 24-sep-2026):
            # se crea uno nuevo en la cuenta actual en vez de fallar.
            agent_id = ""
        else:
            antes = previas
    if agent_id:
        r = cliente.patch("%s/v1/convai/agents/%s" % (API, agent_id), headers=_cabeceras(), json=cuerpo)
    else:
        r = cliente.post(API + "/v1/convai/agents/create", headers=_cabeceras(), json=cuerpo)
    if r.status_code >= 400:
        raise RuntimeError("ElevenLabs rechazo el agente (%s): %s" % (r.status_code, r.text[:300]))
    agent_id = agent_id or str(r.json()["agent_id"])
    posteriores = _tool_ids(cliente, agent_id)
    if posteriores is None:
        # Sin una lectura buena del agente recien guardado no se limpia nada: borrar a
        # ciegas dejaba al agente sin herramientas (revision de Astra, 24-sep-2026).
        raise RuntimeError("ElevenLabs no devuelve el agente %s despues de guardarlo." % agent_id)
    ahora = set(posteriores)
    for viejo in antes:
        if viejo not in ahora:
            cliente.delete("%s/v1/convai/tools/%s" % (API, viejo), headers=_cabeceras(),
                           params={"force": "true"})
    return agent_id


def sincronizar_agente(cliente_id: str, *, base_url: str = "",
                       cliente: Optional[httpx.Client] = None) -> Dict[str, Any]:
    """Crea o actualiza los dos agentes del negocio (web y telefono) desde su config actual."""
    if not configurado():
        raise RuntimeError("Falta ELEVENLABS_API_KEY o ELEVENLABS_TOOL_SECRET.")
    textnorm._assert_valid_client_id(cliente_id)
    config = clients._get_client_config(cliente_id)
    base = base_url or settings.APP_BASE_URL
    propio = cliente is None
    cliente = cliente or httpx.Client(timeout=60.0)
    salida: Dict[str, Any] = {}
    try:
        for telefono, clave in ((False, "elevenlabs_agent_id"), (True, "elevenlabs_agent_id_telefono")):
            cuerpo = agente_para(cliente_id, config, base, telefono=telefono)
            previo = str((clients._get_client_config(cliente_id).get("voice") or {}).get(clave) or "")
            agent_id = publicar_agente(cliente, cuerpo, previo)
            if agent_id != previo:
                guardar_en_voz(cliente_id, clave, agent_id)
            salida["agente_telefono" if telefono else "agent_id"] = agent_id
            if not telefono:
                salida["herramientas"] = [t["name"] for t in cuerpo["conversation_config"]["agent"]["prompt"]["tools"]]
    finally:
        if propio:
            cliente.close()
    salida["enlace"] = "https://elevenlabs.io/app/talk-to?agent_id=%s" % salida["agent_id"]
    return salida


def agente_de_telefono(cliente_id: str) -> str:
    """El agente que coge el telefono del negocio, o "" si sigue con el motor de siempre.

    Se activa negocio a negocio con `config['voice']['engine'] = 'elevenlabs'`, para
    poder volver atras sin tocar codigo.
    """
    if not configurado():
        return ""
    voice_cfg = (appstate.CONFIG_CLIENTES.get(cliente_id) or {}).get("voice") or {}
    if str(voice_cfg.get("engine") or "").strip().lower() != "elevenlabs":
        return ""
    return str(voice_cfg.get("elevenlabs_agent_id_telefono") or "")


def twiml_registrar_llamada(agent_id: str, desde: str, hacia: str, direccion: str,
                            variables: Optional[Dict[str, str]] = None,
                            cliente: Optional[httpx.Client] = None) -> str:
    """El TwiML que conecta una llamada de Twilio con un agente ("register call").

    Twilio sigue siendo nuestro: ElevenLabs no necesita nuestras credenciales. La
    contrapartida es que no puede transferir llamadas.
    """
    propio = cliente is None
    cliente = cliente or httpx.Client(timeout=20.0)
    try:
        r = cliente.post(API + "/v1/convai/twilio/register-call", headers=_cabeceras(), json={
            "agent_id": agent_id, "from_number": desde, "to_number": hacia, "direction": direccion,
            "conversation_initiation_client_data": {"dynamic_variables": dict(variables or {})}})
    finally:
        if propio:
            cliente.close()
    if r.status_code >= 400 or "<Response" not in r.text:
        raise RuntimeError("ElevenLabs no registro la llamada (%s): %s" % (r.status_code, r.text[:200]))
    return r.text


def id_de_conversacion(twiml: str) -> str:
    """El TwiML de register-call lleva la conversacion como <Parameter>: con ella se
    lee despues la transcripcion. "" si no viene."""
    encontrado = re.search(r'name="conversation_id"\s+value="([A-Za-z0-9_-]+)"', twiml or "")
    return encontrado.group(1) if encontrado else ""
