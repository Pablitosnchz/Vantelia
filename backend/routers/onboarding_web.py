"""Endpoints: seccion onboarding_web (refactor F3).

Decoran directamente la app de backend.main para preservar el orden de
registro de rutas identico al monolito original.
"""
from __future__ import annotations

import copy
import sqlite3
from typing import List
from urllib.parse import urlparse

from fastapi import (
    Depends,
    HTTPException,
    Request,
)


import onboarding_utils
from api_models import *  # noqa: F401,F403
from backend import (
    agenda,
    appstate,
    clients,
    commerce,
    onboarding,
    portal,
    rag,
    security,
    settings,
    textnorm,
    timeutils,
)
from backend.main import app

@app.get("/onboarding/state", response_model=OnboardingStateResponse)
async def onboarding_state(
    user: sqlite3.Row = Depends(security._require_self_serve_user),
) -> OnboardingStateResponse:
    cliente_id = (user["cliente_id"] or "").strip()
    if not cliente_id:
        return OnboardingStateResponse(step="name")
    state = onboarding._read_onboarding_state(cliente_id)
    cfg = appstate.CONFIG_CLIENTES.get(cliente_id, {})
    info_path = settings.DATA_DIR / cliente_id / "info.txt"
    has_kb = info_path.exists() and info_path.stat().st_size > 200
    return OnboardingStateResponse(
        cliente_id=cliente_id,
        nombre=cfg.get("nombre", ""),
        website_url=state.get("website_url", ""),
        step=state.get("step", "learn"),
        bienvenida=cfg.get("bienvenida", ""),
        prompt_extra=cfg.get("prompt_extra", ""),
        starter_questions=state.get("starter_questions", []) or [],
        has_kb=has_kb,
    )


@app.post("/onboarding/start", response_model=OnboardingStartResponse)
async def onboarding_start(
    data: OnboardingStartPayload,
    request: Request,
    user: sqlite3.Row = Depends(security._require_self_serve_user),
) -> OnboardingStartResponse:
    existing_cliente = (user["cliente_id"] or "").strip()
    if existing_cliente and existing_cliente in appstate.CONFIG_CLIENTES:
        # already provisioned; reuse and bounce wizard step forward
        state = onboarding._read_onboarding_state(existing_cliente)
        return OnboardingStartResponse(
            cliente_id=existing_cliente,
            nombre=appstate.CONFIG_CLIENTES[existing_cliente].get("nombre", ""),
            step=state.get("step", "learn"),
        )
    cliente_id = onboarding._provision_self_serve_cliente(owner_user_id=user["id"], nombre=data.nombre)
    portal._try_record_analytics_event(
        {
            "event": "bot_created",
            "event_source": "vantelia_app",
            "widget_client_id": cliente_id,
            "cliente_id": cliente_id,
            "user_id": user["id"],
            "bot_name": data.nombre,
            "source": "self_serve",
        },
        request,
    )
    return OnboardingStartResponse(cliente_id=cliente_id, nombre=data.nombre, step="learn")


@app.post("/onboarding/learn", response_model=OnboardingLearnResponse)
async def onboarding_learn(
    data: OnboardingLearnPayload,
    user: sqlite3.Row = Depends(security._require_self_serve_user),
) -> OnboardingLearnResponse:
    cliente_id = (user["cliente_id"] or "").strip()
    if not cliente_id:
        raise HTTPException(status_code=400, detail="Inicia el wizard primero (paso name).")
    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY no configurada en el servidor.")
    if not data.website_url:
        raise HTTPException(status_code=400, detail="Por ahora solo se soporta URL de web.")

    try:
        max_pages = 1 if data.just_this_page else min(data.max_paginas, settings.ONBOARDING_MAX_PAGES_DEFAULT)
        result = onboarding_utils.run_onboarding(
            website_url=data.website_url,
            api_key=settings.OPENAI_API_KEY,
            nombre_bot=appstate.CONFIG_CLIENTES.get(cliente_id, {}).get("nombre", cliente_id),
            tono=data.tono,
            idioma=data.idioma,
            max_paginas=max_pages,
        )
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("Onboarding learn fallo para %s: %s", cliente_id, exc)
        raise HTTPException(status_code=502, detail=f"No se pudo analizar la web: {exc}") from exc

    cliente_data_dir = settings.DATA_DIR / cliente_id
    cliente_data_dir.mkdir(parents=True, exist_ok=True)
    (cliente_data_dir / "info.txt").write_text(result.info_txt, encoding="utf-8")
    agenda._sync_services_from_info(cliente_id, result.info_txt, deactivate_missing=True)
    commerce._seed_commerce_from_info(cliente_id, result.info_txt)

    try:
        explicit_pairs = list(getattr(result, "faq_pairs", []) or [])
        rag._autocreate_qa_from_info(
            cliente_id,
            result.info_txt,
            user["id"],
            explicit_pairs=explicit_pairs,
            max_pairs=rag.AUTO_QA_MAX_PAIRS,
        )
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("Auto-Q&A en onboarding fallo para %s: %s", cliente_id, exc)

    # update config with detected business name + allowed origin
    try:
        parsed = urlparse(data.website_url)
        origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    except Exception:  # noqa: BLE001
        origin = ""
    with appstate.state_lock:
        next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
        cfg = next_configs.get(cliente_id, {})
        if result.detected_business_name and not cfg.get("nombre"):
            cfg["nombre"] = result.detected_business_name
        if origin and origin not in cfg.get("allowed_origins", []):
            cfg.setdefault("allowed_origins", []).append(origin)
        cfg["bienvenida"] = cfg.get("bienvenida") or result.suggested_welcome
        next_configs[cliente_id] = cfg
        clients._update_runtime_configs(next_configs)
    clients._persist_configs_to_disk(next_configs)

    # invalidate llama-index cache so next chat reindexes
    try:
        with appstate.state_lock:
            appstate.indices.pop(cliente_id, None)
    except NameError:
        pass

    # No generamos preguntas sugeridas con IA: el widget muestra las 3 fijas y
    # solo anade las extras que el cliente escriba manualmente.
    starters: List[str] = []
    suggested_prompt_extra = (
        "Habla con tono profesional y cercano. Responde solo con informacion del negocio. "
        "Si no sabes algo, ofrece contactar con el equipo humano."
    )
    state = onboarding._read_onboarding_state(cliente_id)
    state.update({
        "step": "personality",
        "website_url": data.website_url,
        "tono": data.tono,
        "idioma": data.idioma,
        "starter_questions": starters,
        "suggested_prompt_extra": suggested_prompt_extra,
        "learned_at": timeutils._utc_now_iso(),
    })
    onboarding._write_onboarding_state(cliente_id, state)
    return OnboardingLearnResponse(
        ok=True,
        cliente_id=cliente_id,
        detected_business_name=result.detected_business_name,
        info_excerpt=result.info_txt[:1200],
        suggested_welcome=result.suggested_welcome,
        suggested_prompt_extra=suggested_prompt_extra,
        suggested_starters=starters,
        pages_indexed=len(result.links),
    )


@app.post("/onboarding/personality", response_model=OnboardingPersonalityResponse)
async def onboarding_personality(
    data: OnboardingPersonalityPayload,
    user: sqlite3.Row = Depends(security._require_self_serve_user),
) -> OnboardingPersonalityResponse:
    cliente_id = (user["cliente_id"] or "").strip()
    if not cliente_id:
        raise HTTPException(status_code=400, detail="Inicia el wizard primero.")
    sanitized = [
        textnorm._sanitize_text(q)[:140] for q in (data.starter_questions or []) if textnorm._sanitize_text(q)
    ]
    cleaned_starters = settings._strip_base_from_extras(sanitized)
    with appstate.state_lock:
        next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
        cfg = next_configs.get(cliente_id, {})
        cfg["bienvenida"] = textnorm._sanitize_text(data.bienvenida, allow_multiline=True)[:600]
        cfg["prompt_extra"] = textnorm._sanitize_text(data.prompt_extra, allow_multiline=True)[:4000]
        cfg["starter_questions"] = cleaned_starters
        next_configs[cliente_id] = cfg
        clients._update_runtime_configs(next_configs)
    clients._persist_configs_to_disk(next_configs)
    state = onboarding._read_onboarding_state(cliente_id)
    state.update({"step": "try", "starter_questions": cleaned_starters})
    onboarding._write_onboarding_state(cliente_id, state)
    return OnboardingPersonalityResponse(
        ok=True,
        cliente_id=cliente_id,
        bienvenida=cfg["bienvenida"],
        prompt_extra=cfg["prompt_extra"],
        starter_questions=cleaned_starters,
    )


@app.post("/onboarding/finalize", response_model=OnboardingFinalizeResponse)
async def onboarding_finalize(
    request: Request,
    user: sqlite3.Row = Depends(security._require_self_serve_user),
) -> OnboardingFinalizeResponse:
    cliente_id = (user["cliente_id"] or "").strip()
    if not cliente_id:
        raise HTTPException(status_code=400, detail="Inicia el wizard primero.")
    assets = clients._build_install_snippet(cliente_id, request)
    api_base = assets["api_base_url"]
    share_link = f"{api_base}/demo/{cliente_id}"
    state = onboarding._read_onboarding_state(cliente_id)
    state.update({"step": "use", "finalized_at": timeutils._utc_now_iso()})
    onboarding._write_onboarding_state(cliente_id, state)
    return OnboardingFinalizeResponse(
        ok=True,
        cliente_id=cliente_id,
        install_snippet=assets["install_snippet"],
        widget_script_url=assets["widget_script_url"],
        demo_url=assets["demo_url"],
        share_link=share_link,
        dashboard_url=f"{api_base}/app",
    )


