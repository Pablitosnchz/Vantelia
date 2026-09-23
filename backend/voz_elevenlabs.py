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
from typing import Any, Dict, List, Optional

import httpx

from backend import appstate, clients, settings, textnorm, voice

API = "https://api.elevenlabs.io"
# Un agente en espanol solo admite los modelos rapidos (lo exige ElevenLabs). Flash es
# el que sono bien a Pablo en calidad de telefono y tarda ~0,2 s en empezar a hablar.
MODELO_VOZ = "eleven_flash_v2_5"
LLM_POR_DEFECTO = "gemini-2.5-flash"
CABECERA_SECRETO = "X-Vantelia-Voz"
# Herramientas nuestras que tienen equivalente de sistema en ElevenLabs.
_DE_SISTEMA = {"finalizar_llamada": "end_call"}
# Solo tienen sentido con telefono (se anadiran con el numero).
_SOLO_TELEFONO = {"transferir_a_humano"}


def configurado() -> bool:
    return bool(settings.ELEVENLABS_API_KEY and settings.ELEVENLABS_TOOL_SECRET)


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


def herramientas(cliente_id: str, config: Dict[str, Any], base_url: str) -> List[Dict[str, Any]]:
    """Las tools de cita del negocio en el formato de ElevenLabs."""
    salida: List[Dict[str, Any]] = []
    for tool in voice._voice_booking_tools(cliente_id, config):
        nombre = str(tool.get("name") or "")
        if nombre in _SOLO_TELEFONO:
            continue
        if nombre in _DE_SISTEMA:
            sistema = _DE_SISTEMA[nombre]
            salida.append({"type": "system", "name": sistema, "description": tool.get("description", ""),
                           "params": {"system_tool_type": sistema}})
            continue
        salida.append({
            "type": "webhook",
            "name": nombre,
            "description": str(tool.get("description") or nombre),
            "api_schema": {
                "url": "%s/voice/el/%s/tool/%s" % (base_url.rstrip("/"), cliente_id, nombre),
                "method": "POST",
                "request_headers": {CABECERA_SECRETO: settings.ELEVENLABS_TOOL_SECRET},
                "request_body_schema": _esquema(
                    tool.get("parameters") or {"type": "object", "properties": {}}, nombre),
            },
        })
    if not any(t.get("name") == "end_call" for t in salida):
        salida.append({"type": "system", "name": "end_call",
                       "description": "Termina la llamada cuando la conversacion ha concluido. Despidete antes.",
                       "params": {"system_tool_type": "end_call"}})
    return salida


def agente_para(cliente_id: str, config: Dict[str, Any], base_url: str) -> Dict[str, Any]:
    """Lo que se manda a ElevenLabs para crear o actualizar el agente del negocio."""
    voice_cfg = config.get("voice") or {}
    nombre = str(config.get("empresa") or config.get("nombre") or cliente_id).strip()
    return {
        "name": "%s (%s)" % (nombre, cliente_id),
        "conversation_config": {
            "agent": {
                "first_message": textnorm._voice_default_greeting(config, voice_cfg),
                "language": "es",
                "prompt": {
                    "prompt": voice._voice_build_instructions(cliente_id, config),
                    "llm": str(voice_cfg.get("elevenlabs_llm") or LLM_POR_DEFECTO),
                    "temperature": 0.5,
                    "tools": herramientas(cliente_id, config, base_url),
                },
            },
            "tts": {
                "voice_id": str(voice_cfg.get("elevenlabs_voice_id") or settings.ELEVENLABS_VOICE_ID),
                "model_id": MODELO_VOZ,
                "agent_output_audio_format": "pcm_44100",
            },
            "turn": {"speculative_turn": True},
        },
    }


def _guardar_agent_id(cliente_id: str, agent_id: str) -> None:
    siguientes = copy.deepcopy(appstate.CONFIG_CLIENTES)
    siguientes[cliente_id].setdefault("voice", {})["elevenlabs_agent_id"] = agent_id
    clients._persist_configs_to_disk(siguientes)
    clients._update_runtime_configs(siguientes)


def _tool_ids(cliente: httpx.Client, agent_id: str) -> List[str]:
    r = cliente.get("%s/v1/convai/agents/%s" % (API, agent_id), headers=_cabeceras())
    r.raise_for_status()
    prompt = ((r.json().get("conversation_config") or {}).get("agent") or {}).get("prompt") or {}
    return list(prompt.get("tool_ids") or [])


def sincronizar_agente(cliente_id: str, *, base_url: str = "",
                       cliente: Optional[httpx.Client] = None) -> Dict[str, Any]:
    """Crea o actualiza el agente del negocio en ElevenLabs. Devuelve su id y el enlace de prueba.

    Cada guardado con tools en linea crea herramientas nuevas en la cuenta; las que el
    agente deja de usar se borran para que no se acumulen (una por tool y guardado).
    """
    if not configurado():
        raise RuntimeError("Falta ELEVENLABS_API_KEY o ELEVENLABS_TOOL_SECRET.")
    textnorm._assert_valid_client_id(cliente_id)
    config = clients._get_client_config(cliente_id)
    cuerpo = agente_para(cliente_id, config, base_url or settings.APP_BASE_URL)
    agent_id = str((config.get("voice") or {}).get("elevenlabs_agent_id") or "")
    propio = cliente is None
    cliente = cliente or httpx.Client(timeout=60.0)
    try:
        antes: List[str] = _tool_ids(cliente, agent_id) if agent_id else []
        if agent_id:
            r = cliente.patch("%s/v1/convai/agents/%s" % (API, agent_id), headers=_cabeceras(), json=cuerpo)
        else:
            r = cliente.post(API + "/v1/convai/agents/create", headers=_cabeceras(), json=cuerpo)
        if r.status_code >= 400:
            raise RuntimeError("ElevenLabs rechazo el agente (%s): %s" % (r.status_code, r.text[:300]))
        if not agent_id:
            agent_id = str(r.json()["agent_id"])
            _guardar_agent_id(cliente_id, agent_id)
        ahora = set(_tool_ids(cliente, agent_id))
        for viejo in antes:
            if viejo not in ahora:
                cliente.delete("%s/v1/convai/tools/%s" % (API, viejo), headers=_cabeceras(),
                               params={"force": "true"})
    finally:
        if propio:
            cliente.close()
    return {"agent_id": agent_id,
            "enlace": "https://elevenlabs.io/app/talk-to?agent_id=%s" % agent_id,
            "herramientas": [t["name"] for t in cuerpo["conversation_config"]["agent"]["prompt"]["tools"]]}
