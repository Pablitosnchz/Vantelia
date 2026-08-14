"""Endpoints del portal: contenido del asistente (Leads, Q&A, Knowledge, Tune AI).

Extraido de portal_app.py (refactor: partir el router monolitico). Decora la
misma app de backend.main; main.py lo importa justo despues de portal_app para
preservar el comportamiento. Los handlers son autocontenidos (sin estado
compartido con portal_app salvo modulos backend.*).
"""
from __future__ import annotations

import copy
import json
import re
import secrets
import sqlite3
from typing import Dict

from fastapi import (
    Depends,
    HTTPException,
    Response,
)


import onboarding_utils
from api_models import *  # noqa: F401,F403
from backend import (
    agenda,
    appstate,
    chat,
    clients,
    commerce,
    crm,
    db,
    keywords,
    rag,
    security,
    settings,
    textnorm,
    timeutils,
)
from backend.main import app


# --- Sem 4: Leads ----------------------------------------------------------



@app.get("/auth/app/leads", response_model=AppLeadsListResponse)
async def app_leads_list(
    page: int = 1,
    page_size: int = 50,
    q: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppLeadsListResponse:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    offset = (page - 1) * page_size
    q_clean = (q or "").strip()
    with db._get_db_connection() as connection:
        if q_clean:
            like = f"%{q_clean.lower()}%"
            total = connection.execute(
                """
                SELECT COUNT(*) FROM bot_leads
                WHERE cliente_id = ?
                  AND (LOWER(name) LIKE ? OR LOWER(email) LIKE ? OR LOWER(phone) LIKE ? OR LOWER(message) LIKE ?)
                """,
                (cliente_id, like, like, like, like),
            ).fetchone()[0]
            rows = connection.execute(
                """
                SELECT * FROM bot_leads
                WHERE cliente_id = ?
                  AND (LOWER(name) LIKE ? OR LOWER(email) LIKE ? OR LOWER(phone) LIKE ? OR LOWER(message) LIKE ?)
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (cliente_id, like, like, like, like, page_size, offset),
            ).fetchall()
        else:
            total = connection.execute(
                "SELECT COUNT(*) FROM bot_leads WHERE cliente_id = ?", (cliente_id,)
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM bot_leads WHERE cliente_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (cliente_id, page_size, offset),
            ).fetchall()
    return AppLeadsListResponse(
        items=[crm._lead_row_to_public(r) for r in rows],
        total=int(total or 0),
        page=page,
        page_size=page_size,
    )


@app.post("/auth/app/leads", response_model=AppLeadPublic)
async def app_lead_create(
    data: AppLeadPayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppLeadPublic:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    name = textnorm._sanitize_text(data.name)[:200]
    email = textnorm._sanitize_text(data.email)[:200]
    phone = textnorm._sanitize_text(data.phone)[:80]
    message = textnorm._sanitize_text(data.message, allow_multiline=True)[:4000]
    if not (name or email or phone or message):
        raise HTTPException(status_code=400, detail="Indica al menos nombre, email, telefono o mensaje.")
    lead_id = "lead_" + secrets.token_hex(10)
    now_iso = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO bot_leads
                (id, cliente_id, session_id, name, email, phone, message, source, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', ?)
            """,
            (
                lead_id,
                cliente_id,
                textnorm._sanitize_text(data.session_id)[:200],
                name,
                email,
                phone,
                message,
                textnorm._sanitize_text(data.source)[:40] or "manual",
                now_iso,
            ),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM bot_leads WHERE id = ?", (lead_id,)).fetchone()
    contact_id = crm._crm_upsert_contact(
        cliente_id,
        name=name,
        email=email,
        phone=phone,
        source=textnorm._sanitize_text(data.source)[:40] or "manual",
        status="interesado",
        entity_type="lead",
        entity_id=lead_id,
        actor=f"user:{user['id']}",
    )
    if contact_id and data.session_id:
        with db._get_db_connection() as connection:
            crm._crm_link(connection, cliente_id, contact_id, "chat", textnorm._sanitize_text(data.session_id)[:200], "chat")
            connection.commit()
    return crm._lead_row_to_public(row)


@app.delete("/auth/app/leads/{lead_id}")
async def app_lead_delete(
    lead_id: str,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, bool]:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    with db._get_db_connection() as connection:
        cur = connection.execute(
            "DELETE FROM bot_leads WHERE id = ? AND cliente_id = ?",
            (lead_id, cliente_id),
        )
        connection.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Lead no encontrado.")
    return {"ok": True}


@app.get("/auth/app/leads/export.csv")
async def app_leads_export(
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Response:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    with db._get_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM bot_leads WHERE cliente_id = ? ORDER BY created_at DESC",
            (cliente_id,),
        ).fetchall()
    import csv
    import io
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["created_at", "name", "email", "phone", "message", "source", "session_id"])
    for r in rows:
        writer.writerow([
            r["created_at"], r["name"] or "", r["email"] or "", r["phone"] or "",
            (r["message"] or "").replace("\n", " ").replace("\r", " "),
            r["source"] or "", r["session_id"] or "",
        ])
    filename = f"leads_{cliente_id}_{timeutils._utc_now().strftime('%Y%m%d')}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- Sem 4: Q&A -------------------------------------------------------------



@app.get("/auth/app/qa", response_model=AppQAListResponse)
async def app_qa_list(
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppQAListResponse:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    with db._get_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM kb_qa WHERE cliente_id = ? ORDER BY created_at DESC",
            (cliente_id,),
        ).fetchall()
    items = [rag._qa_row_to_public(r) for r in rows]
    return AppQAListResponse(items=items, total=len(items))


@app.post("/auth/app/qa", response_model=AppQAItem)
async def app_qa_create(
    data: AppQAPayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppQAItem:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    qa_id = "qa_" + secrets.token_hex(10)
    now_iso = timeutils._utc_now_iso()
    tags = [textnorm._sanitize_text(t)[:40] for t in (data.tags or []) if textnorm._sanitize_text(t)][:10]
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO kb_qa (id, cliente_id, question, answer, tags_json,
                               created_at, updated_at, created_by_user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                qa_id,
                cliente_id,
                textnorm._sanitize_text(data.question, allow_multiline=True)[:400],
                textnorm._sanitize_text(data.answer, allow_multiline=True)[:4000],
                json.dumps(tags, ensure_ascii=False),
                now_iso,
                now_iso,
                user["id"],
            ),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM kb_qa WHERE id = ?", (qa_id,)).fetchone()
    rag._maybe_regenerate_info_with_qa(cliente_id)
    return rag._qa_row_to_public(row)


@app.patch("/auth/app/qa/{qa_id}", response_model=AppQAItem)
async def app_qa_update(
    qa_id: str,
    data: AppQAUpdatePayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppQAItem:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    with db._get_db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM kb_qa WHERE id = ? AND cliente_id = ?",
            (qa_id, cliente_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Q&A no encontrada.")
        next_q = textnorm._sanitize_text(data.question, allow_multiline=True)[:400] if data.question is not None else row["question"]
        next_a = textnorm._sanitize_text(data.answer, allow_multiline=True)[:4000] if data.answer is not None else row["answer"]
        if data.tags is not None:
            tags = [textnorm._sanitize_text(t)[:40] for t in data.tags if textnorm._sanitize_text(t)][:10]
            tags_json = json.dumps(tags, ensure_ascii=False)
        else:
            tags_json = row["tags_json"]
        connection.execute(
            "UPDATE kb_qa SET question = ?, answer = ?, tags_json = ?, updated_at = ? WHERE id = ?",
            (next_q, next_a, tags_json, timeutils._utc_now_iso(), qa_id),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM kb_qa WHERE id = ?", (qa_id,)).fetchone()
    rag._maybe_regenerate_info_with_qa(cliente_id)
    return rag._qa_row_to_public(row)


@app.delete("/auth/app/qa/{qa_id}")
async def app_qa_delete(
    qa_id: str,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, bool]:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    with db._get_db_connection() as connection:
        cur = connection.execute(
            "DELETE FROM kb_qa WHERE id = ? AND cliente_id = ?",
            (qa_id, cliente_id),
        )
        connection.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Q&A no encontrada.")
    rag._maybe_regenerate_info_with_qa(cliente_id)
    return {"ok": True}


# --- Respuestas automaticas por palabra clave (opt-in por tenant) ----------
#
# Capa determinista previa a la IA: el negocio define "si el mensaje contiene X,
# responde exactamente Y". Ver backend/keywords.py. Apagada por defecto, asi que
# los tenants que no la activen no cambian de comportamiento.


def _keyword_rules_response(cliente_id: str) -> AppKeywordRulesResponse:
    items = [AppKeywordRuleItem(**r) for r in keywords.list_rules(cliente_id)]
    return AppKeywordRulesResponse(
        enabled=keywords.rules_enabled(cliente_id),
        items=items,
        total=len(items),
    )


@app.get("/auth/app/keyword-rules", response_model=AppKeywordRulesResponse)
async def app_keyword_rules_list(
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppKeywordRulesResponse:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    return _keyword_rules_response(cliente_id)


@app.put("/auth/app/keyword-rules/config", response_model=AppKeywordRulesResponse)
async def app_keyword_rules_config(
    data: AppKeywordRulesConfigPayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppKeywordRulesResponse:
    """Activa/desactiva la funcion para este negocio. manager+ (configuracion)."""
    security._require_portal_min_role(user, "manager")
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    with appstate.state_lock:
        next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
        cfg = next_configs.get(cliente_id, {})
        section = dict(cfg.get(keywords.CONFIG_SECTION, {}) or {})
        section["enabled"] = bool(data.enabled)
        cfg[keywords.CONFIG_SECTION] = section
        next_configs[cliente_id] = cfg
        clients._update_runtime_configs(next_configs)
    clients._persist_configs_to_disk(next_configs)
    return _keyword_rules_response(cliente_id)


@app.post("/auth/app/keyword-rules", response_model=AppKeywordRuleItem)
async def app_keyword_rule_create(
    data: AppKeywordRulePayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppKeywordRuleItem:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    try:
        rule = keywords.create_rule(
            cliente_id,
            label=data.label,
            keywords=data.keywords,
            reply=data.reply,
            match_mode=data.match_mode,
            active=data.active,
            created_by_user_id=user["id"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return AppKeywordRuleItem(**rule)


@app.patch("/auth/app/keyword-rules/{rule_id}", response_model=AppKeywordRuleItem)
async def app_keyword_rule_update(
    rule_id: str,
    data: AppKeywordRuleUpdatePayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppKeywordRuleItem:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    patch = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    try:
        rule = keywords.update_rule(cliente_id, rule_id, patch)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not rule:
        raise HTTPException(status_code=404, detail="Regla no encontrada.")
    return AppKeywordRuleItem(**rule)


@app.delete("/auth/app/keyword-rules/{rule_id}")
async def app_keyword_rule_delete(
    rule_id: str,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, bool]:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    if not keywords.delete_rule(cliente_id, rule_id):
        raise HTTPException(status_code=404, detail="Regla no encontrada.")
    return {"ok": True}


# --- Menu de opciones del asistente (opt-out por tenant) -------------------


@app.get("/auth/app/chat-menu")
async def app_chat_menu_get(
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, bool]:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    return {"enabled": chat._menu_enabled(cliente_id)}


@app.put("/auth/app/chat-menu")
async def app_chat_menu_put(
    data: AppChatMenuPayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, bool]:
    """Enciende/apaga el menu de opciones al saludar. manager+ (configuracion)."""
    security._require_portal_min_role(user, "manager")
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    with appstate.state_lock:
        next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
        cfg = next_configs.get(cliente_id, {})
        section = dict(cfg.get(chat.MENU_CONFIG_SECTION, {}) or {})
        section["enabled"] = bool(data.enabled)
        cfg[chat.MENU_CONFIG_SECTION] = section
        next_configs[cliente_id] = cfg
        clients._update_runtime_configs(next_configs)
    clients._persist_configs_to_disk(next_configs)
    return {"enabled": chat._menu_enabled(cliente_id)}


# --- Sem 4: Knowledge (text snippets + URLs) -----------------------------

_KB_BLOCK_MARKER = "===== AÑADIDO DESDE PANEL ====="


























@app.get("/auth/app/knowledge", response_model=AppKnowledgeListResponse)
async def app_knowledge_list(
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppKnowledgeListResponse:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    with db._get_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM kb_documents WHERE cliente_id = ? ORDER BY uploaded_at DESC",
            (cliente_id,),
        ).fetchall()
    info = rag._read_info(cliente_id)
    return AppKnowledgeListResponse(
        items=[rag._kb_row_to_public(r) for r in rows],
        info_chars=len(info),
        info_excerpt=info[:1200],
        info_full=info,
    )


@app.post("/auth/app/knowledge/text", response_model=AppKnowledgeItem)
async def app_knowledge_add_text(
    data: AppKnowledgeTextPayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppKnowledgeItem:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    title = textnorm._sanitize_text(data.title)[:200] or "Nota manual"
    content = textnorm._sanitize_text(data.content, allow_multiline=True)[:20000]
    now_iso = timeutils._utc_now_iso()
    kb_id = "kb_" + secrets.token_hex(10)
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO kb_documents
                (id, cliente_id, filename, mime_type, size_bytes, sha256,
                 source, source_url, storage_path, indexed_at, uploaded_at, uploaded_by_user_id)
            VALUES (?, ?, ?, 'text/plain', ?, '', 'text', '', '', ?, ?, ?)
            """,
            (kb_id, cliente_id, title, len(content.encode("utf-8")), now_iso, now_iso, user["id"]),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM kb_documents WHERE id = ?", (kb_id,)).fetchone()
    info = rag._read_info(cliente_id)
    block = f"\n\n{_KB_BLOCK_MARKER}\n[{title}]\n{content}\n"
    if rag._KB_QA_BLOCK_MARKER in info:
        before, after = info.split(rag._KB_QA_BLOCK_MARKER, 1)
        info = before.rstrip() + block + "\n" + rag._KB_QA_BLOCK_MARKER + after
    else:
        info = info.rstrip() + block
    rag._write_info(cliente_id, info)
    return rag._kb_row_to_public(row)


@app.post("/auth/app/knowledge/url", response_model=AppKnowledgeItem)
async def app_knowledge_add_url(
    data: AppKnowledgeUrlPayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppKnowledgeItem:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    url = textnorm._sanitize_text(data.url)
    if not re.match(r"^https?://", url):
        raise HTTPException(status_code=400, detail="URL invalida (https:// requerido).")
    canonical_url = rag._canonical_knowledge_url(url)
    with db._get_db_connection() as connection:
        existing_url_rows = connection.execute(
            """
            SELECT source_url
            FROM kb_documents
            WHERE cliente_id = ? AND source = 'url'
            """,
            (cliente_id,),
        ).fetchall()
    if any(rag._canonical_knowledge_url(row["source_url"] or "") == canonical_url for row in existing_url_rows):
        raise HTTPException(
            status_code=409,
            detail="Esta fuente ya esta añadida al conocimiento. Quita la fuente existente antes de volver a indexarla.",
        )
    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY no configurada.")
    try:
        max_pages = 1 if data.just_this_page else settings.ONBOARDING_MAX_PAGES_DEFAULT
        result = onboarding_utils.run_onboarding(
            website_url=canonical_url,
            api_key=settings.OPENAI_API_KEY,
            nombre_bot=appstate.CONFIG_CLIENTES.get(cliente_id, {}).get("nombre", cliente_id),
            tono="Profesional y cercano",
            idioma="Espanol",
            max_paginas=max_pages,
        )
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("KB URL ingest fallo %s: %s", cliente_id, exc)
        raise HTTPException(status_code=502, detail=f"No se pudo analizar la URL: {exc}") from exc

    now_iso = timeutils._utc_now_iso()
    kb_id = "kb_" + secrets.token_hex(10)
    info_chars = len(result.info_txt.encode("utf-8"))
    stored_url = canonical_url
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO kb_documents
                (id, cliente_id, filename, mime_type, size_bytes, sha256,
                 source, source_url, storage_path, indexed_at, uploaded_at, uploaded_by_user_id)
            VALUES (?, ?, ?, 'text/html', ?, '', 'url', ?, '', ?, ?, ?)
            """,
            (
                kb_id, cliente_id,
                result.detected_business_name or stored_url,
                info_chars,
                stored_url,
                now_iso, now_iso, user["id"],
            ),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM kb_documents WHERE id = ?", (kb_id,)).fetchone()

    if data.replace:
        new_info = result.info_txt
    else:
        existing = rag._read_info(cliente_id)
        block = f"\n\n{_KB_BLOCK_MARKER}\n[Web: {stored_url}]\n{result.info_txt}\n"
        if rag._KB_QA_BLOCK_MARKER in existing:
            before, after = existing.split(rag._KB_QA_BLOCK_MARKER, 1)
            new_info = before.rstrip() + block + "\n" + rag._KB_QA_BLOCK_MARKER + after
        else:
            new_info = existing.rstrip() + block
    rag._write_info(cliente_id, new_info)
    agenda._sync_services_from_info(cliente_id, new_info, deactivate_missing=bool(data.replace))
    commerce._seed_commerce_from_info(cliente_id, new_info)
    qa_created = 0
    try:
        explicit_pairs = list(getattr(result, "faq_pairs", []) or [])
        qa_created = rag._autocreate_qa_from_info(
            cliente_id,
            result.info_txt,
            user["id"],
            explicit_pairs=explicit_pairs,
            max_pairs=rag.AUTO_QA_MAX_PAIRS,
        )
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("Auto-Q&A extraction failed for %s: %s", cliente_id, exc)
    public = rag._kb_row_to_public(row)
    public.qa_created = qa_created
    return public


@app.delete("/auth/app/knowledge/{kb_id}")
async def app_knowledge_delete(
    kb_id: str,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, bool]:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    with db._get_db_connection() as connection:
        cur = connection.execute(
            "DELETE FROM kb_documents WHERE id = ? AND cliente_id = ?",
            (kb_id, cliente_id),
        )
        connection.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Recurso no encontrado.")
    # NOTE: we intentionally do NOT auto-truncate info.txt — text was merged in
    # at ingest time and cannot be cleanly de-merged. User can use /reindex.
    return {"ok": True}


@app.post("/auth/app/knowledge/reindex", response_model=AppKnowledgeReindexResponse)
async def app_knowledge_reindex(
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppKnowledgeReindexResponse:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    try:
        with appstate.state_lock:
            appstate.indices.pop(cliente_id, None)
    except NameError:
        pass
    info = rag._read_info(cliente_id)
    return AppKnowledgeReindexResponse(ok=True, cliente_id=cliente_id, info_chars=len(info))


# --- Sem 4: Tune AI -------------------------------------------------------

AVAILABLE_CHAT_MODELS = settings.AVAILABLE_CHAT_MODELS_BOOT


@app.get("/auth/app/tune", response_model=AppTuneResponse)
async def app_tune_get(
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppTuneResponse:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    cfg = appstate.CONFIG_CLIENTES.get(cliente_id, {})
    return AppTuneResponse(
        cliente_id=cliente_id,
        prompt_extra=cfg.get("prompt_extra", ""),
        chat_model=cfg.get("chat_model", settings.DEFAULT_CHAT_MODEL),
        temperature=float(cfg.get("temperature", 0.2)),
        available_models=AVAILABLE_CHAT_MODELS,
    )


@app.post("/auth/app/tune", response_model=AppTuneResponse)
async def app_tune_post(
    data: AppTunePayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppTuneResponse:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    with appstate.state_lock:
        next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
        cfg = next_configs.get(cliente_id, {})
        if data.prompt_extra is not None:
            cfg["prompt_extra"] = textnorm._sanitize_text(data.prompt_extra, allow_multiline=True)[:8000]
        if data.chat_model is not None and data.chat_model.strip() in AVAILABLE_CHAT_MODELS:
            cfg["chat_model"] = data.chat_model.strip()
        if data.temperature is not None:
            cfg["temperature"] = max(0.0, min(2.0, float(data.temperature)))
        next_configs[cliente_id] = cfg
        clients._update_runtime_configs(next_configs)
    clients._persist_configs_to_disk(next_configs)
    try:
        with appstate.state_lock:
            appstate.indices.pop(cliente_id, None)
    except NameError:
        pass
    return await app_tune_get(user)
