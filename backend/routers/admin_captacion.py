"""Endpoints: seccion admin_captacion (refactor F3).

Decoran directamente la app de backend.main para preservar el orden de
registro de rutas identico al monolito original.
"""
from __future__ import annotations

import csv
import json
import os
import threading
from datetime import timedelta
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import (
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
)
from pydantic import BaseModel, Field


from api_models import *  # noqa: F401,F403
from backend import (
    instagram,
    messaging,
    outreach,
    security,
    settings,
    tiktok,
    timeutils,
    wa_capture,
)
from backend.instagram import (  # noqa: F401
    IGProfile, ig_create_draft, ig_deep_link, ig_discover_usernames,
    ig_fetch_candidates, ig_is_autosend_enabled, ig_upsert_profile,
)
from backend.main import app

@app.post("/admin/outreach/replies", dependencies=[Depends(security._require_admin_token)])
def outreach_record_reply(payload: OutreachReplyPayload):
    email = str(payload.email).lower().strip()
    with outreach._outreach_db() as conn:
        conn.execute(
            "INSERT INTO events (email, type, stage, ts) VALUES (?,?,?,?)",
            (email, "reply", payload.stage, outreach._outreach_now()),
        )
        conn.execute(
            "UPDATE prospects SET status='replied', updated_at=? WHERE email=?",
            (outreach._outreach_now(), email),
        )
        conn.commit()
    return {"ok": True}


# === END OUTREACH ====================================================


# =====================================================================
# === INSTAGRAM =======================================================
# Captacion via Instagram DMs. Modo hibrido compliant por defecto:
# discovery + drafts + envio manual 1-clic via ig.me deep link.
# Autosend automatizado opt-in via IG_AUTOSEND_ENABLED (riesgo ban Meta).
# =====================================================================















# ----- Pydantic -----


class InstagramProspectIn(BaseModel):
    username: str = Field(..., min_length=1, max_length=80)
    full_name: str = ""
    bio: str = ""
    business_category: str = ""
    niche: str = ""
    city: str = ""
    followers_count: int = 0
    following_count: int = 0
    posts_count: int = 0
    website: str = ""
    public_email: str = ""
    public_phone: str = ""
    profile_url: str = ""
    avatar_url: str = ""
    is_business_account: int = 0
    is_verified: int = 0
    score: int = 0
    status: str = "new"
    notes: str = ""
    tags: str = ""
    source: str = "manual"
    service_hint: str = ""


class InstagramProspectPatch(BaseModel):
    full_name: Optional[str] = None
    bio: Optional[str] = None
    business_category: Optional[str] = None
    niche: Optional[str] = None
    city: Optional[str] = None
    followers_count: Optional[int] = None
    following_count: Optional[int] = None
    posts_count: Optional[int] = None
    website: Optional[str] = None
    public_email: Optional[str] = None
    public_phone: Optional[str] = None
    is_business_account: Optional[int] = None
    is_verified: Optional[int] = None
    score: Optional[int] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[str] = None
    source: Optional[str] = None
    service_hint: Optional[str] = None


class InstagramDiscoverRequest(BaseModel):
    usernames: List[str] = Field(default_factory=list)
    niche: str = ""
    city: str = ""
    source: str = "discover"
    min_followers: int = 0
    max_followers: int = 0
    has_website: bool = False
    is_business: bool = False
    use_graph: bool = True


class InstagramDraftRequest(BaseModel):
    stage: str = "cold"
    max: int = 20
    after_days: int = 5


class InstagramSendRequest(BaseModel):
    stage: str = "cold"
    max: int = 10
    dry_run: bool = True


class InstagramSessionCookies(BaseModel):
    sessionid: str = Field(..., min_length=10)
    csrftoken: str = Field(..., min_length=10)
    ds_user_id: str = Field(..., min_length=1)
    mid: str = ""
    rur: str = ""


class InstagramSuppressRequest(BaseModel):
    username: str = Field(..., min_length=1)
    reason: str = "manual"


class InstagramTemplateOverride(BaseModel):
    stage: str
    opener: str = ""
    body: str = ""


class InstagramAutopilotPayload(BaseModel):
    enabled: Optional[bool] = None
    targets: Optional[List[Dict[str, Any]]] = None
    daily_new_target: Optional[int] = None
    daily_outreach_cap: Optional[int] = None
    auto_followups: Optional[bool] = None


class InstagramReplyPayload(BaseModel):
    username: str
    stage: str = ""
    note: str = ""


class InstagramManualContactPayload(BaseModel):
    username: str = Field(..., min_length=1, max_length=80)
    full_name: str = ""
    message_text: str = Field(..., min_length=1, max_length=2000)
    stage: str = ""
    contacted_at: str = ""
    notes: str = ""
    profile_url: str = ""
    city: str = ""
    niche: str = ""


# ----- Helpers de row -> dict -----


















# ----- Stats -----


@app.get("/admin/instagram/stats", dependencies=[Depends(security._require_admin_token)])
def instagram_stats():
    with instagram._instagram_db() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM ig_prospects").fetchone()["c"]
        suppressed = conn.execute("SELECT COUNT(*) AS c FROM ig_suppressions").fetchone()["c"]
        replied = conn.execute(
            "SELECT COUNT(DISTINCT username) AS c FROM ig_events WHERE type='reply'"
        ).fetchone()["c"]
        clients = conn.execute(
            "SELECT COUNT(*) AS c FROM ig_prospects WHERE status='client'"
        ).fetchone()["c"]
        drafts_pending = conn.execute(
            "SELECT COUNT(*) AS c FROM ig_sends WHERE mode='draft' AND ready=1"
        ).fetchone()["c"]
        sent_total = conn.execute(
            "SELECT COUNT(*) AS c FROM ig_sends WHERE mode IN ('sent','sent_auto')"
        ).fetchone()["c"]
        sent_distinct = conn.execute(
            "SELECT COUNT(DISTINCT username) AS c FROM ig_sends WHERE mode IN ('sent','sent_auto')"
        ).fetchone()["c"]
        today = timeutils._utc_now().date().isoformat()
        sent_today = conn.execute(
            "SELECT COUNT(*) AS c FROM ig_sends WHERE mode IN ('sent','sent_auto') AND substr(sent_at,1,10)=?",
            (today,),
        ).fetchone()["c"]
        per_stage_rows = conn.execute(
            "SELECT stage, COUNT(*) AS c FROM ig_sends WHERE mode IN ('sent','sent_auto') GROUP BY stage"
        ).fetchall()
        per_stage = {row["stage"]: int(row["c"]) for row in per_stage_rows}
        funnel = {stage: per_stage.get(stage, 0) for stage in instagram.IG_STAGES}

    reply_rate = (replied / sent_distinct * 100) if sent_distinct else 0.0
    return {
        "totals": {
            "prospects": total,
            "suppressed": suppressed,
            "drafts_pending": drafts_pending,
            "sent_total": sent_total,
            "sent_distinct": sent_distinct,
            "sent_today": sent_today,
            "replies_unique": replied,
            "clients": clients,
        },
        "funnel": funnel,
        "reply_rate": round(reply_rate, 2),
        "autosend_enabled": bool(instagram.IG_AVAILABLE and ig_is_autosend_enabled()),
        "in_window": instagram._ig_in_window(),
    }


# ----- Prospects CRUD -----


@app.get("/admin/instagram/prospects", dependencies=[Depends(security._require_admin_token)])
def instagram_list_prospects(
    q: str = "",
    status: str = "",
    niche: str = "",
    city: str = "",
    source: str = "",
    page: int = 1,
    page_size: int = 50,
):
    page = max(1, page)
    page_size = max(1, min(200, page_size))
    where = []
    params: List[Any] = []
    if q:
        where.append("(username LIKE ? OR full_name LIKE ? OR bio LIKE ?)")
        like = f"%{q.strip()}%"
        params.extend([like, like, like])
    if status:
        where.append("status=?"); params.append(status)
    if niche:
        where.append("niche LIKE ?"); params.append(f"%{niche}%")
    if city:
        where.append("city LIKE ?"); params.append(f"%{city}%")
    if source:
        where.append("source LIKE ?"); params.append(f"%{source}%")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    with instagram._instagram_db() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM ig_prospects {where_sql}", params
        ).fetchone()["c"]
        rows = conn.execute(
            f"""SELECT * FROM ig_prospects {where_sql}
                ORDER BY score DESC, updated_at DESC
                LIMIT ? OFFSET ?""",
            params + [page_size, (page - 1) * page_size],
        ).fetchall()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [instagram._ig_row_dict(r) for r in rows],
    }


@app.get("/admin/instagram/prospects/{username}", dependencies=[Depends(security._require_admin_token)])
def instagram_get_prospect(username: str):
    user = instagram._ig_resolve_username(username)
    with instagram._instagram_db() as conn:
        row = conn.execute("SELECT * FROM ig_prospects WHERE username=?", (user,)).fetchone()
        if not row:
            raise HTTPException(404, "Prospect no encontrado")
        sends = conn.execute(
            "SELECT * FROM ig_sends WHERE username=? ORDER BY drafted_at DESC LIMIT 50",
            (user,),
        ).fetchall()
        events = conn.execute(
            "SELECT * FROM ig_events WHERE username=? ORDER BY ts DESC LIMIT 50",
            (user,),
        ).fetchall()
    return {
        "prospect": instagram._ig_row_dict(row),
        "sends": [instagram._ig_row_dict(s) for s in sends],
        "events": [instagram._ig_row_dict(e) for e in events],
    }




@app.post("/admin/instagram/manual-contact", dependencies=[Depends(security._require_admin_token)])
def instagram_manual_contact(payload: InstagramManualContactPayload):
    user = instagram._ig_resolve_username(payload.username)
    if not user:
        raise HTTPException(400, "username invalido")
    now = instagram._ig_parse_ts(payload.contacted_at)
    stage = instagram._ig_normalize_manual_stage(payload.stage)
    with instagram._instagram_db() as conn:
        existing = conn.execute("SELECT * FROM ig_prospects WHERE username=?", (user,)).fetchone()
        if not stage:
            stage = instagram._ig_stage_from_history(conn, user) if existing else "cold"
        if stage not in set(instagram.IG_STAGES) | {"reply", "interested", "lost", "client", "demo"}:
            raise HTTPException(400, "stage invalido")
        if not existing:
            conn.execute(
                """INSERT INTO ig_prospects
                     (username, full_name, niche, city, profile_url, status, notes, source,
                      created_at, updated_at, last_contacted_at, next_followup_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    user,
                    payload.full_name.strip(),
                    payload.niche.strip(),
                    payload.city.strip(),
                    payload.profile_url.strip() or f"https://www.instagram.com/{user}/",
                    "new",
                    payload.notes.strip(),
                    "manual",
                    now,
                    now,
                    "",
                    "",
                ),
            )
        else:
            conn.execute(
                """UPDATE ig_prospects
                   SET full_name=CASE WHEN COALESCE(full_name,'')='' THEN ? ELSE full_name END,
                       niche=CASE WHEN COALESCE(niche,'')='' THEN ? ELSE niche END,
                       city=CASE WHEN COALESCE(city,'')='' THEN ? ELSE city END,
                       profile_url=CASE WHEN COALESCE(profile_url,'')='' THEN ? ELSE profile_url END,
                       notes=CASE WHEN ?<>'' THEN TRIM(COALESCE(notes,'') || CASE WHEN COALESCE(notes,'')='' THEN '' ELSE char(10) END || ?) ELSE notes END,
                       updated_at=?
                   WHERE username=?""",
                (
                    payload.full_name.strip(),
                    payload.niche.strip(),
                    payload.city.strip(),
                    payload.profile_url.strip() or f"https://www.instagram.com/{user}/",
                    payload.notes.strip(),
                    payload.notes.strip(),
                    now,
                    user,
                ),
            )

        event_data = {"message_text": payload.message_text.strip(), "notes": payload.notes.strip(), "manual": True}
        next_info = {"next_stage": "", "next_followup_at": ""}
        if stage in instagram.IG_STAGES:
            conn.execute(
                """INSERT INTO ig_sends (username, stage, variant, message_text, mode, ready, sent_at, drafted_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (user, stage, "manual", payload.message_text.strip(), "sent", 0, now, now),
            )
            conn.execute(
                "INSERT INTO ig_events (username, type, stage, data_json, ts) VALUES (?,?,?,?,?)",
                (user, "sent", stage, json.dumps(event_data, ensure_ascii=False), now),
            )
            next_info = instagram._ig_next_followup(stage, now)
            conn.execute(
                """UPDATE ig_prospects
                   SET status=CASE WHEN status IN ('replied','client','lost','dnc') THEN status ELSE 'contacted' END,
                       last_contacted_at=?, next_followup_at=?, updated_at=?
                   WHERE username=?""",
                (now, next_info["next_followup_at"], now, user),
            )
        else:
            event_type = {"reply": "reply", "interested": "interest", "lost": "lost", "client": "client", "demo": "demo"}.get(stage, "note")
            status = {"reply": "replied", "interested": "replied", "lost": "lost", "client": "client", "demo": "replied"}.get(stage, "contacted")
            conn.execute(
                "INSERT INTO ig_events (username, type, stage, data_json, ts) VALUES (?,?,?,?,?)",
                (user, event_type, stage, json.dumps(event_data, ensure_ascii=False), now),
            )
            conn.execute(
                "UPDATE ig_prospects SET status=?, next_followup_at='', updated_at=? WHERE username=?",
                (status, now, user),
            )
        conn.commit()
        row = conn.execute("SELECT * FROM ig_prospects WHERE username=?", (user,)).fetchone()
    return {
        "ok": True,
        "username": user,
        "stage": stage,
        "next_stage": next_info["next_stage"],
        "next_followup_at": next_info["next_followup_at"],
        "prospect": instagram._ig_row_dict(row) if row else None,
    }


@app.get("/admin/instagram/followup-queue", dependencies=[Depends(security._require_admin_token)])
def instagram_followup_queue(limit: int = 50, include_upcoming: bool = False):
    with instagram._instagram_db() as conn:
        return {"items": instagram._ig_followup_queue_items(conn, limit, include_upcoming)}


@app.get("/admin/instagram/prospects/{username}/timeline", dependencies=[Depends(security._require_admin_token)])
def instagram_prospect_timeline(username: str):
    user = instagram._ig_resolve_username(username)
    with instagram._instagram_db() as conn:
        row = conn.execute("SELECT * FROM ig_prospects WHERE username=?", (user,)).fetchone()
        if not row:
            raise HTTPException(404, "Prospect no encontrado")
        sends = [instagram._ig_row_dict(r) for r in conn.execute(
            "SELECT id, username, 'send' AS kind, stage, mode AS type, message_text AS text, sent_at AS ts, drafted_at FROM ig_sends WHERE username=?",
            (user,),
        ).fetchall()]
        events = [instagram._ig_row_dict(r) for r in conn.execute(
            "SELECT id, username, 'event' AS kind, stage, type, data_json AS text, ts, '' AS drafted_at FROM ig_events WHERE username=?",
            (user,),
        ).fetchall()]
    items = sorted(sends + events, key=lambda x: x.get("ts") or x.get("drafted_at") or "", reverse=True)
    return {"prospect": instagram._ig_row_dict(row), "items": items}


@app.get("/admin/instagram/ops-summary", dependencies=[Depends(security._require_admin_token)])
def instagram_ops_summary():
    today = timeutils._utc_now().date().isoformat()
    week_cutoff = (timeutils._utc_now() - timedelta(days=7)).isoformat(timespec="seconds")
    with instagram._instagram_db() as conn:
        sent_today = conn.execute(
            "SELECT COUNT(*) AS c FROM ig_sends WHERE mode IN ('sent','sent_auto') AND substr(sent_at,1,10)=?",
            (today,),
        ).fetchone()["c"]
        sent_week = conn.execute(
            "SELECT COUNT(*) AS c FROM ig_sends WHERE mode IN ('sent','sent_auto') AND sent_at>=?",
            (week_cutoff,),
        ).fetchone()["c"]
        replies = conn.execute(
            "SELECT COUNT(DISTINCT username) AS c FROM ig_events WHERE type IN ('reply','interest','demo')"
        ).fetchone()["c"]
        interested = conn.execute(
            "SELECT COUNT(*) AS c FROM ig_prospects WHERE status IN ('replied','client')"
        ).fetchone()["c"]
        status_rows = conn.execute(
            "SELECT status, COUNT(*) AS c FROM ig_prospects GROUP BY status"
        ).fetchall()
        recent_rows = conn.execute(
            """SELECT username, type, stage, data_json, ts
               FROM ig_events
               ORDER BY ts DESC, id DESC
               LIMIT 12"""
        ).fetchall()
        queue_due = instagram._ig_followup_queue_items(conn, 20, False)
        queue_all = instagram._ig_followup_queue_items(conn, 20, True)
    response_rate = round((replies / sent_week * 100), 2) if sent_week else 0.0
    return {
        "totals": {
            "sent_today": sent_today,
            "sent_week": sent_week,
            "replies": replies,
            "interested": interested,
            "followups_due": len(queue_due),
            "followups_upcoming": max(0, len(queue_all) - len(queue_due)),
            "response_rate": response_rate,
        },
        "status_counts": {r["status"] or "new": int(r["c"]) for r in status_rows},
        "followups_due": queue_due[:8],
        "recent_activity": [instagram._ig_row_dict(r) for r in recent_rows],
    }


@app.post("/admin/instagram/prospects", dependencies=[Depends(security._require_admin_token)])
def instagram_create_prospect(payload: InstagramProspectIn):
    user = instagram._ig_resolve_username(payload.username)
    if not user:
        raise HTTPException(400, "username invalido")
    data = payload.model_dump()
    data["username"] = user
    data["now"] = instagram._instagram_now()
    with instagram._instagram_db() as conn:
        exists = conn.execute("SELECT 1 FROM ig_prospects WHERE username=?", (user,)).fetchone()
        if exists:
            raise HTTPException(409, "Prospect ya existe")
        conn.execute(
            """INSERT INTO ig_prospects
                 (username, full_name, bio, business_category, niche, city,
                  followers_count, following_count, posts_count, website,
                  public_email, public_phone, profile_url, avatar_url,
                  is_business_account, is_verified, score, status,
                  notes, tags, source, service_hint, created_at, updated_at)
               VALUES
                 (:username, :full_name, :bio, :business_category, :niche, :city,
                  :followers_count, :following_count, :posts_count, :website,
                  :public_email, :public_phone, :profile_url, :avatar_url,
                  :is_business_account, :is_verified, :score, :status,
                  :notes, :tags, :source, :service_hint, :now, :now)""",
            data,
        )
        conn.commit()
    return {"ok": True, "username": user}


@app.patch("/admin/instagram/prospects/{username}", dependencies=[Depends(security._require_admin_token)])
def instagram_patch_prospect(username: str, payload: InstagramProspectPatch):
    user = instagram._ig_resolve_username(username)
    fields = []
    params: List[Any] = []
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(400, "Sin cambios")
    for key, value in data.items():
        fields.append(f"{key}=?")
        params.append(value)
    fields.append("updated_at=?"); params.append(instagram._instagram_now())
    params.append(user)
    with instagram._instagram_db() as conn:
        cur = conn.execute(
            f"UPDATE ig_prospects SET {', '.join(fields)} WHERE username=?",
            params,
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "Prospect no encontrado")
        conn.commit()
    return {"ok": True, "username": user}


@app.delete("/admin/instagram/prospects/{username}", dependencies=[Depends(security._require_admin_token)])
def instagram_delete_prospect(username: str):
    user = instagram._ig_resolve_username(username)
    with instagram._instagram_db() as conn:
        cur = conn.execute("DELETE FROM ig_prospects WHERE username=?", (user,))
        conn.commit()
    return {"ok": True, "deleted": cur.rowcount}


# ----- Import / Export -----


@app.post("/admin/instagram/import", dependencies=[Depends(security._require_admin_token)])
async def instagram_import_csv(request: Request):
    raw = (await request.body()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(StringIO(raw))
    if not reader.fieldnames:
        raise HTTPException(400, "CSV vacio o sin cabecera")
    added = updated = skipped = 0
    with instagram._instagram_db() as conn:
        for row in reader:
            user = instagram._ig_resolve_username(row.get("username", ""))
            if not user:
                skipped += 1
                continue
            profile = IGProfile(
                username=user,
                full_name=(row.get("full_name") or "").strip(),
                bio=(row.get("bio") or "").strip(),
                business_category=(row.get("business_category") or "").strip(),
                niche=(row.get("niche") or "").strip(),
                city=(row.get("city") or "").strip(),
                followers_count=int(row.get("followers_count") or 0),
                following_count=int(row.get("following_count") or 0),
                posts_count=int(row.get("posts_count") or 0),
                website=(row.get("website") or "").strip(),
                public_email=(row.get("public_email") or "").strip(),
                public_phone=(row.get("public_phone") or "").strip(),
                profile_url=(row.get("profile_url") or "").strip(),
                avatar_url=(row.get("avatar_url") or "").strip(),
                is_business_account=int(row.get("is_business_account") or 0),
                is_verified=int(row.get("is_verified") or 0),
                tags=(row.get("tags") or "").strip(),
                source=(row.get("source") or "csv").strip(),
            )
            a, u = ig_upsert_profile(conn, profile)
            if a:
                added += 1
            elif u:
                updated += 1
            else:
                skipped += 1
        conn.commit()
    return {"added": added, "updated": updated, "skipped": skipped}


@app.get("/admin/instagram/export.csv", dependencies=[Depends(security._require_admin_token)])
def instagram_export_csv():
    with instagram._instagram_db() as conn:
        rows = conn.execute("SELECT * FROM ig_prospects ORDER BY created_at DESC").fetchall()
    buf = StringIO()
    if rows:
        fieldnames = list(rows[0].keys())
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(instagram._ig_row_dict(r))
    return Response(content=buf.getvalue(), media_type="text/csv")


# ----- Discovery -----


@app.post("/admin/instagram/discover", dependencies=[Depends(security._require_admin_token)])
def instagram_discover(payload: InstagramDiscoverRequest, background_tasks: BackgroundTasks):
    if not instagram.IG_AVAILABLE:
        raise HTTPException(503, "Modulo IG no disponible")
    if not payload.usernames:
        raise HTTPException(400, "usernames requerido")
    params_json = json.dumps(payload.model_dump(), ensure_ascii=False)
    with instagram._instagram_db() as conn:
        cur = conn.execute(
            "INSERT INTO ig_jobs (kind, status, params_json, started_at) VALUES (?,?,?,?)",
            ("discover", "queued", params_json, instagram._instagram_now()),
        )
        job_id = cur.lastrowid
        conn.commit()

    def _run() -> None:
        try:
            with instagram._instagram_db() as conn2:
                conn2.execute("UPDATE ig_jobs SET status='running' WHERE id=?", (job_id,))
                conn2.commit()
            profiles = ig_discover_usernames(
                payload.usernames,
                niche=payload.niche,
                city=payload.city,
                source_label=payload.source or "discover",
                use_graph=payload.use_graph,
                min_followers=payload.min_followers,
                max_followers=payload.max_followers,
                has_website=payload.has_website,
                is_business=payload.is_business,
            )
            added = updated = 0
            with instagram._instagram_db() as conn2:
                for p in profiles:
                    a, u = ig_upsert_profile(conn2, p)
                    if a:
                        added += 1
                    elif u:
                        updated += 1
                conn2.execute(
                    "UPDATE ig_jobs SET status='done', log=?, finished_at=? WHERE id=?",
                    (
                        json.dumps({"profiles": len(profiles), "added": added, "updated": updated}),
                        instagram._instagram_now(),
                        job_id,
                    ),
                )
                conn2.commit()
        except Exception as exc:  # noqa: BLE001
            try:
                with instagram._instagram_db() as conn2:
                    conn2.execute(
                        "UPDATE ig_jobs SET status='error', log=?, finished_at=? WHERE id=?",
                        (f"error: {exc}", instagram._instagram_now(), job_id),
                    )
                    conn2.commit()
            except Exception:
                pass

    background_tasks.add_task(_run)
    return {"ok": True, "job_id": job_id}


@app.get("/admin/instagram/jobs", dependencies=[Depends(security._require_admin_token)])
def instagram_jobs(limit: int = 50):
    with instagram._instagram_db() as conn:
        rows = conn.execute(
            "SELECT * FROM ig_jobs ORDER BY id DESC LIMIT ?",
            (max(1, min(200, limit)),),
        ).fetchall()
    return {"items": [instagram._ig_row_dict(r) for r in rows]}


@app.get("/admin/instagram/jobs/{job_id}", dependencies=[Depends(security._require_admin_token)])
def instagram_job(job_id: int):
    with instagram._instagram_db() as conn:
        row = conn.execute("SELECT * FROM ig_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Job no encontrado")
    return instagram._ig_row_dict(row)


# ----- Drafts -----


@app.post("/admin/instagram/draft", dependencies=[Depends(security._require_admin_token)])
def instagram_generate_drafts(payload: InstagramDraftRequest):
    if payload.stage not in instagram.IG_STAGES:
        raise HTTPException(400, "stage invalido")
    created: List[Dict[str, Any]] = []
    with instagram._instagram_db() as conn:
        rows = ig_fetch_candidates(conn, payload.stage, max(1, payload.max), max(1, payload.after_days))
        for r in rows:
            draft = ig_create_draft(conn, r, payload.stage)
            created.append(draft)
        conn.commit()
    return {"created": len(created), "drafts": created}


@app.get("/admin/instagram/drafts", dependencies=[Depends(security._require_admin_token)])
def instagram_drafts_queue(stage: str = "", niche: str = "", city: str = "", limit: int = 100):
    # Single-touch: con follow-ups desactivados, descarta cualquier draft no-cold
    # que quedara en cola (de versiones anteriores) para que no se envie ni se vea.
    if not instagram._ig_env_bool("IG_AUTONOMOUS_FOLLOWUPS", False):
        with instagram._instagram_db() as conn:
            conn.execute(
                "UPDATE ig_sends SET mode='skipped', ready=0, skip_reason='followups_off' "
                "WHERE mode='draft' AND ready=1 AND stage<>'cold'"
            )
            conn.commit()
    where = ["s.mode='draft'", "s.ready=1"]
    params: List[Any] = []
    if stage:
        where.append("s.stage=?"); params.append(stage)
    if niche:
        where.append("p.niche LIKE ?"); params.append(f"%{niche}%")
    if city:
        where.append("p.city LIKE ?"); params.append(f"%{city}%")
    where_sql = " AND ".join(where)
    params.append(max(1, min(500, limit)))
    with instagram._instagram_db() as conn:
        rows = conn.execute(
            f"""SELECT s.id AS send_id, s.username, s.stage, s.variant, s.message_text,
                       s.drafted_at, p.full_name, p.bio, p.niche, p.city,
                       p.followers_count, p.avatar_url, p.score, p.business_category
                FROM ig_sends s
                LEFT JOIN ig_prospects p ON p.username=s.username
                WHERE {where_sql}
                ORDER BY p.score DESC, s.id ASC
                LIMIT ?""",
            params,
        ).fetchall()
    items: List[Dict[str, Any]] = []
    for r in rows:
        d = instagram._ig_row_dict(r)
        d["deep_link"] = ig_deep_link(r["username"], r["message_text"])
        items.append(d)
    return {"items": items, "count": len(items)}


class InstagramDraftEditPayload(BaseModel):
    message_text: str = Field(..., min_length=1, max_length=1000)


@app.patch("/admin/instagram/drafts/{send_id}", dependencies=[Depends(security._require_admin_token)])
def instagram_edit_draft(send_id: int, payload: InstagramDraftEditPayload):
    with instagram._instagram_db() as conn:
        row = conn.execute("SELECT * FROM ig_sends WHERE id=? AND mode='draft'", (send_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Draft no encontrado")
        conn.execute(
            "UPDATE ig_sends SET message_text=? WHERE id=?",
            (payload.message_text.strip(), send_id),
        )
        conn.commit()
    return {"ok": True, "deep_link": ig_deep_link(row["username"], payload.message_text.strip())}


@app.post("/admin/instagram/drafts/{send_id}/mark-sent", dependencies=[Depends(security._require_admin_token)])
def instagram_mark_draft_sent(send_id: int):
    with instagram._instagram_db() as conn:
        row = conn.execute("SELECT * FROM ig_sends WHERE id=?", (send_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Draft no encontrado")
        if row["mode"] not in ("draft", "preview"):
            raise HTTPException(409, "El draft ya fue marcado como enviado")
        now = instagram._instagram_now()
        conn.execute(
            "UPDATE ig_sends SET mode='sent', ready=0, sent_at=? WHERE id=?",
            (now, send_id),
        )
        conn.execute(
            "INSERT INTO ig_events (username, type, stage, ts) VALUES (?,?,?,?)",
            (row["username"], "sent", row["stage"], now),
        )
        next_info = instagram._ig_next_followup(row["stage"], now)
        conn.execute(
            """UPDATE ig_prospects
               SET status=CASE WHEN status IN ('replied','client','lost','dnc') THEN status ELSE 'contacted' END,
                   last_contacted_at=?, next_followup_at=?, updated_at=?
               WHERE username=?""",
            (now, next_info["next_followup_at"], now, row["username"]),
        )
        conn.commit()
    return {"ok": True}


@app.post("/admin/instagram/drafts/{send_id}/skip", dependencies=[Depends(security._require_admin_token)])
def instagram_skip_draft(send_id: int, reason: str = "skip"):
    with instagram._instagram_db() as conn:
        row = conn.execute("SELECT * FROM ig_sends WHERE id=?", (send_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Draft no encontrado")
        conn.execute(
            "UPDATE ig_sends SET mode='skipped', ready=0, skip_reason=? WHERE id=?",
            (reason[:120], send_id),
        )
        conn.commit()
    return {"ok": True}


# ----- Autosend opt-in -----


@app.post("/admin/instagram/send", dependencies=[Depends(security._require_admin_token)])
def instagram_autosend(payload: InstagramSendRequest, background_tasks: BackgroundTasks):
    if not ig_is_autosend_enabled():
        raise HTTPException(412, "IG_AUTOSEND_ENABLED=false. Usa /draft + envio manual.")
    try:
        from instagram_autosend import autosend_drafts  # type: ignore
    except ImportError:
        raise HTTPException(503, "scripts/instagram_autosend.py no disponible. Instala playwright.")
    if payload.stage not in instagram.IG_STAGES:
        raise HTTPException(400, "stage invalido")
    with instagram._instagram_db() as conn:
        rows = ig_fetch_candidates(conn, payload.stage, max(1, payload.max), 5)
        drafts = [ig_create_draft(conn, r, payload.stage) for r in rows]
        conn.commit()

    def _run() -> None:
        try:
            autosend_drafts(drafts, dry_run=payload.dry_run)
        except Exception as exc:  # noqa: BLE001
            settings.logger.warning(f"IG autosend error: {exc}")

    background_tasks.add_task(_run)
    return {"ok": True, "queued": len(drafts), "dry_run": payload.dry_run}


# ----- Sesion Instagram (cookies pegadas desde navegador) -----


@app.get("/admin/instagram/autosend/status", dependencies=[Depends(security._require_admin_token)])
def instagram_autosend_status():
    try:
        from instagram_autosend import session_info  # type: ignore
    except ImportError:
        raise HTTPException(503, "scripts/instagram_autosend.py no disponible.")
    return {
        "autosend_enabled": ig_is_autosend_enabled(),
        "autonomous_autosend": instagram._ig_env_bool("IG_AUTONOMOUS_AUTOSEND", False),
        "session": session_info(),
    }


@app.post("/admin/instagram/autosend/connect", dependencies=[Depends(security._require_admin_token)])
def instagram_autosend_connect(payload: InstagramSessionCookies):
    try:
        from instagram_autosend import save_session_from_cookies, session_info  # type: ignore
    except ImportError:
        raise HTTPException(503, "scripts/instagram_autosend.py no disponible.")
    try:
        path = save_session_from_cookies(
            sessionid=payload.sessionid,
            csrftoken=payload.csrftoken,
            ds_user_id=payload.ds_user_id,
            mid=payload.mid,
            rur=payload.rur,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "saved_at": str(path), "session": session_info()}


@app.post("/admin/instagram/autosend/disconnect", dependencies=[Depends(security._require_admin_token)])
def instagram_autosend_disconnect():
    try:
        from instagram_autosend import clear_session  # type: ignore
    except ImportError:
        raise HTTPException(503, "scripts/instagram_autosend.py no disponible.")
    removed = clear_session()
    return {"ok": True, "removed": removed}


@app.post("/admin/instagram/autosend/test", dependencies=[Depends(security._require_admin_token)])
def instagram_autosend_test():
    """Comprueba si la sesion guardada sigue valida pidiendo /accounts/edit/ a IG."""
    try:
        from instagram_autosend import session_info  # type: ignore
    except ImportError:
        raise HTTPException(503, "scripts/instagram_autosend.py no disponible.")
    info = session_info()
    if not info.get("connected"):
        return {"ok": False, "reason": "sin_sesion"}
    sessionid = ""
    csrftoken = ""
    ds_user_id = info.get("ds_user_id") or ""
    try:
        state_path = Path(info.get("path") or "")
        if state_path.exists():
            data = json.loads(state_path.read_text(encoding="utf-8"))
            for c in data.get("cookies", []):
                if c.get("name") == "sessionid":
                    sessionid = c.get("value") or ""
                elif c.get("name") == "csrftoken":
                    csrftoken = c.get("value") or ""
    except Exception as exc:
        raise HTTPException(500, f"No se pudo leer sesion: {exc}")
    if not sessionid:
        return {"ok": False, "reason": "sin_sessionid"}
    cookies = {"sessionid": sessionid, "csrftoken": csrftoken, "ds_user_id": ds_user_id}
    headers = {
        "User-Agent": os.getenv("IG_AUTOSEND_USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
        "Accept-Language": "es-ES,es;q=0.9",
        "X-IG-App-ID": "936619743392459",
    }
    try:
        with httpx.Client(timeout=10.0, follow_redirects=False) as client:
            r = client.get("https://www.instagram.com/api/v1/accounts/edit/web_form_data/",
                           cookies=cookies, headers=headers)
        ok = r.status_code == 200 and "username" in (r.text or "")
        return {"ok": ok, "status_code": r.status_code,
                "session": info,
                "hint": "Cookies validas" if ok else "Cookies caducadas o cuenta bloqueada. Reconecta."}
    except Exception as exc:
        return {"ok": False, "reason": f"http_error: {exc}", "session": info}


# ----- Suppressions -----


@app.post("/admin/instagram/suppress", dependencies=[Depends(security._require_admin_token)])
def instagram_suppress(payload: InstagramSuppressRequest):
    user = instagram._ig_resolve_username(payload.username)
    if not user:
        raise HTTPException(400, "username invalido")
    with instagram._instagram_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO ig_suppressions (username, reason, added_at) VALUES (?,?,?)",
            (user, payload.reason or "manual", instagram._instagram_now()),
        )
        conn.execute(
            "UPDATE ig_prospects SET status='dnc', updated_at=? WHERE username=?",
            (instagram._instagram_now(), user),
        )
        conn.commit()
    return {"ok": True, "username": user}


@app.delete("/admin/instagram/suppress/{username}", dependencies=[Depends(security._require_admin_token)])
def instagram_remove_suppress(username: str):
    user = instagram._ig_resolve_username(username)
    with instagram._instagram_db() as conn:
        conn.execute("DELETE FROM ig_suppressions WHERE username=?", (user,))
        conn.commit()
    return {"ok": True}


@app.get("/admin/instagram/suppressions", dependencies=[Depends(security._require_admin_token)])
def instagram_list_suppressions(limit: int = 200):
    with instagram._instagram_db() as conn:
        rows = conn.execute(
            "SELECT * FROM ig_suppressions ORDER BY added_at DESC LIMIT ?",
            (max(1, min(1000, limit)),),
        ).fetchall()
    return {"items": [instagram._ig_row_dict(r) for r in rows]}


# ----- Templates overrides -----


@app.get("/admin/instagram/templates", dependencies=[Depends(security._require_admin_token)])
def instagram_templates():
    with instagram._instagram_db() as conn:
        rows = conn.execute("SELECT * FROM ig_templates_overrides").fetchall()
    return {"overrides": [instagram._ig_row_dict(r) for r in rows], "stages": instagram.IG_STAGES}


@app.put("/admin/instagram/templates", dependencies=[Depends(security._require_admin_token)])
def instagram_save_template(payload: InstagramTemplateOverride):
    if payload.stage not in instagram.IG_STAGES:
        raise HTTPException(400, "stage invalido")
    with instagram._instagram_db() as conn:
        conn.execute(
            """INSERT INTO ig_templates_overrides (stage, opener, body, updated_at)
               VALUES (?,?,?,?)
               ON CONFLICT(stage) DO UPDATE SET opener=excluded.opener, body=excluded.body, updated_at=excluded.updated_at""",
            (payload.stage, payload.opener, payload.body, instagram._instagram_now()),
        )
        conn.commit()
    return {"ok": True}


# ----- Hot leads + AB stats -----


@app.get("/admin/instagram/hot-leads", dependencies=[Depends(security._require_admin_token)])
def instagram_hot_leads(limit: int = 15):
    with instagram._instagram_db() as conn:
        rows = conn.execute(
            """SELECT p.* FROM ig_prospects p
               WHERE p.status IN ('contacted','queued')
               AND EXISTS (SELECT 1 FROM ig_sends s WHERE s.username=p.username AND s.mode IN ('sent','sent_auto'))
               AND NOT EXISTS (SELECT 1 FROM ig_events e WHERE e.username=p.username AND e.type='reply')
               ORDER BY p.score DESC, p.updated_at DESC
               LIMIT ?""",
            (max(1, min(50, limit)),),
        ).fetchall()
    items: List[Dict[str, Any]] = []
    for r in rows:
        d = instagram._ig_row_dict(r)
        d["deep_link"] = ig_deep_link(r["username"], "")
        items.append(d)
    return {"items": items}


@app.get("/admin/instagram/ab-stats", dependencies=[Depends(security._require_admin_token)])
def instagram_ab_stats(stage: str = "cold", days: int = 30):
    if stage not in instagram.IG_STAGES:
        raise HTTPException(400, "stage invalido")
    cutoff = (timeutils._utc_now() - timedelta(days=max(1, days))).isoformat(timespec="seconds")
    with instagram._instagram_db() as conn:
        rows = conn.execute(
            """SELECT variant,
                      COUNT(*) AS sent,
                      SUM(CASE WHEN EXISTS(SELECT 1 FROM ig_events e WHERE e.username=ig_sends.username AND e.type='reply' AND e.ts>=ig_sends.sent_at) THEN 1 ELSE 0 END) AS replies
                FROM ig_sends
                WHERE stage=? AND mode IN ('sent','sent_auto') AND sent_at>=?
                GROUP BY variant""",
            (stage, cutoff),
        ).fetchall()
    out = []
    for r in rows:
        sent = int(r["sent"] or 0)
        replies = int(r["replies"] or 0)
        out.append({
            "variant": r["variant"] or "?",
            "sent": sent,
            "replies": replies,
            "reply_rate": round(replies / sent * 100, 2) if sent else 0.0,
        })
    return {"stage": stage, "days": days, "variants": out}


# ----- Autopilot config -----


@app.get("/admin/instagram/autopilot-config", dependencies=[Depends(security._require_admin_token)])
def instagram_autopilot_get():
    with instagram._instagram_db() as conn:
        row = conn.execute("SELECT * FROM ig_autopilot_config WHERE id=1").fetchone()
        if not row:
            return {"config": None}
        cfg = instagram._ig_row_dict(row)
        try:
            cfg["targets"] = json.loads(cfg.get("targets_json") or "[]")
        except Exception:
            cfg["targets"] = []
        # contadores diarios
        today = timeutils._utc_now().date().isoformat()
        cfg["sent_today"] = conn.execute(
            "SELECT COUNT(*) AS c FROM ig_sends WHERE mode IN ('sent','sent_auto') AND substr(sent_at,1,10)=?",
            (today,),
        ).fetchone()["c"]
        cfg["autosent_today"] = conn.execute(
            "SELECT COUNT(*) AS c FROM ig_sends WHERE mode='sent_auto' AND substr(sent_at,1,10)=?",
            (today,),
        ).fetchone()["c"]
        cfg["drafts_pending"] = conn.execute(
            "SELECT COUNT(*) AS c FROM ig_sends WHERE mode='draft' AND ready=1"
        ).fetchone()["c"]
    db_cap = int(cfg.get("daily_outreach_cap") or 0)
    env_cap = int(os.getenv("IG_AUTOSEND_DAILY_CAP", "20") or 20)
    cfg["effective_daily_cap"] = db_cap if db_cap > 0 else env_cap
    return {"config": cfg, "autosend_enabled": ig_is_autosend_enabled(),
            "autonomous_enabled": instagram._ig_env_bool("IG_AUTONOMOUS_ENABLED", False),
            "autonomous_autosend": instagram._ig_env_bool("IG_AUTONOMOUS_AUTOSEND", False)}


@app.put("/admin/instagram/autopilot-config", dependencies=[Depends(security._require_admin_token)])
def instagram_autopilot_put(payload: InstagramAutopilotPayload):
    fields: List[str] = []
    params: List[Any] = []
    data = payload.model_dump(exclude_unset=True)
    if "enabled" in data:
        fields.append("enabled=?"); params.append(1 if data["enabled"] else 0)
    if "targets" in data:
        fields.append("targets_json=?"); params.append(json.dumps(data["targets"] or [], ensure_ascii=False))
    if "daily_new_target" in data:
        fields.append("daily_new_target=?"); params.append(int(data["daily_new_target"] or 0))
    if "daily_outreach_cap" in data:
        fields.append("daily_outreach_cap=?"); params.append(int(data["daily_outreach_cap"] or 0))
    if "auto_followups" in data:
        fields.append("auto_followups=?"); params.append(1 if data["auto_followups"] else 0)
    if not fields:
        raise HTTPException(400, "Sin cambios")
    fields.append("updated_at=?"); params.append(instagram._instagram_now())
    with instagram._instagram_db() as conn:
        conn.execute(f"UPDATE ig_autopilot_config SET {', '.join(fields)} WHERE id=1", params)
        conn.commit()
    return {"ok": True}




@app.post("/admin/instagram/autopilot-tick", dependencies=[Depends(security._require_admin_token)])
def instagram_autopilot_tick():
    stats = instagram._ig_autopilot_run_once()
    return {"ok": True, "stats": stats, "ts": instagram._instagram_now()}


# =====================================================================
# === CAMPAIGN v2: discovery real + DMs naturales + 1 boton Empezar  ==
# =====================================================================


class InstagramCampaignStart(BaseModel):
    target_count: int = Field(30, ge=1, le=200)






















@app.get("/admin/instagram/campaign", dependencies=[Depends(security._require_admin_token)])
def instagram_campaign_get():
    state = instagram._ig_campaign_state()
    try:
        from instagram_autosend import session_info  # type: ignore
        session = session_info()
    except Exception:
        session = {"connected": False}
    return {"campaign": state, "session": session,
            "autosend_enabled": ig_is_autosend_enabled() if instagram.IG_AVAILABLE else False,
            "autonomous_autosend": instagram._ig_env_bool("IG_AUTONOMOUS_AUTOSEND", False)}


@app.post("/admin/instagram/campaign/start", dependencies=[Depends(security._require_admin_token)])
def instagram_campaign_start(payload: InstagramCampaignStart):
    if not instagram.IG_AVAILABLE:
        raise HTTPException(503, "Modulo instagram no disponible")
    if not ig_is_autosend_enabled():
        raise HTTPException(412, "IG_AUTOSEND_ENABLED=false en env")
    try:
        from instagram_autosend import session_info  # type: ignore
        if not session_info().get("connected"):
            raise HTTPException(412, "Sesion IG no conectada. Pega cookies primero.")
    except HTTPException:
        raise
    except Exception:
        pass
    instagram._ig_campaign_migrate()
    instagram._ig_campaign_update(
        target_count=int(payload.target_count),
        status="discovering",
        error_msg="",
        started_at=instagram._instagram_now(),
        completed_at="",
    )
    return {"ok": True, "state": instagram._ig_campaign_state()}


@app.post("/admin/instagram/campaign/pause", dependencies=[Depends(security._require_admin_token)])
def instagram_campaign_pause():
    instagram._ig_campaign_migrate()
    instagram._ig_campaign_update(status="paused")
    return {"ok": True, "state": instagram._ig_campaign_state()}


class InstagramDmTemplatesPayload(BaseModel):
    variant_a: Optional[str] = None
    variant_b: Optional[str] = None
    variant_c: Optional[str] = None






@app.get("/admin/instagram/dm-templates", dependencies=[Depends(security._require_admin_token)])
def instagram_dm_templates_get():
    instagram._ig_dm_templates_ensure()
    out = {"A": "", "B": "", "C": ""}
    with instagram._instagram_db() as conn:
        rows = conn.execute("SELECT variant, body FROM ig_dm_templates_v2").fetchall()
        for r in rows:
            v = (r["variant"] or "").upper()
            if v in out:
                out[v] = r["body"] or ""
    defaults = {v: instagram._ig_dm_default(v) for v in ("A", "B", "C")}
    placeholders_help = ""
    try:
        from instagram_templates_v2 import PLACEHOLDERS_HELP  # type: ignore
        placeholders_help = PLACEHOLDERS_HELP
    except Exception:
        pass
    return {"templates": out, "defaults": defaults, "placeholders_help": placeholders_help}


@app.put("/admin/instagram/dm-templates", dependencies=[Depends(security._require_admin_token)])
def instagram_dm_templates_put(payload: InstagramDmTemplatesPayload):
    instagram._ig_dm_templates_ensure()
    now = instagram._instagram_now()
    data = {"A": payload.variant_a, "B": payload.variant_b, "C": payload.variant_c}
    saved: List[str] = []
    with instagram._instagram_db() as conn:
        for variant, body in data.items():
            if body is None:
                continue
            body_clean = body.strip()
            if body_clean:
                conn.execute(
                    """INSERT INTO ig_dm_templates_v2 (variant, body, updated_at)
                       VALUES (?,?,?)
                       ON CONFLICT(variant) DO UPDATE SET body=excluded.body, updated_at=excluded.updated_at""",
                    (variant, body_clean, now),
                )
                saved.append(variant)
            else:
                conn.execute("DELETE FROM ig_dm_templates_v2 WHERE variant=?", (variant,))
                saved.append(variant + " (reset)")
        conn.commit()
    return {"ok": True, "saved": saved}


@app.post("/admin/instagram/dm-templates/preview", dependencies=[Depends(security._require_admin_token)])
def instagram_dm_templates_preview(variant: str = "A",
                                    business_name: str = "Clinica Sonrisa",
                                    niche: str = "clinica dental",
                                    city: str = "Madrid"):
    try:
        from instagram_templates_v2 import render_natural  # type: ignore
    except ImportError:
        raise HTTPException(503, "templates_v2 no disponible")
    text = render_natural(
        username=f"preview_{variant.lower()}",
        business_name=business_name,
        niche=niche,
        city=city,
        variant=variant.upper(),
        db_path=str(instagram._instagram_db_path()),
    )
    return {"variant": variant.upper(), "text": text}


@app.post("/admin/instagram/campaign/resume", dependencies=[Depends(security._require_admin_token)])
def instagram_campaign_resume():
    if not ig_is_autosend_enabled():
        raise HTTPException(412, "IG_AUTOSEND_ENABLED=false en env")
    instagram._ig_campaign_migrate()
    # Resume: si hay drafts pendientes, va directo a sending; si no, discovering.
    state = instagram._ig_campaign_state()
    next_status = "sending" if (state.get("pending_drafts") or 0) > 0 else "discovering"
    instagram._ig_campaign_update(status=next_status, error_msg="")
    return {"ok": True, "state": instagram._ig_campaign_state()}


# ----- Manual reply mark -----


@app.post("/admin/instagram/replies", dependencies=[Depends(security._require_admin_token)])
def instagram_record_reply(payload: InstagramReplyPayload):
    user = instagram._ig_resolve_username(payload.username)
    if not user:
        raise HTTPException(400, "username invalido")
    with instagram._instagram_db() as conn:
        conn.execute(
            "INSERT INTO ig_events (username, type, stage, data_json, ts) VALUES (?,?,?,?,?)",
            (user, "reply", payload.stage, json.dumps({"note": payload.note}, ensure_ascii=False), instagram._instagram_now()),
        )
        conn.execute(
            "UPDATE ig_prospects SET status='replied', updated_at=? WHERE username=?",
            (instagram._instagram_now(), user),
        )
        conn.commit()
    return {"ok": True}


@app.post("/admin/instagram/replies/poll", dependencies=[Depends(security._require_admin_token)])
def instagram_replies_poll_now():
    if not instagram.IG_REPLIES_AVAILABLE or instagram.ig_replies_poll is None:
        raise HTTPException(503, "Poller IG no disponible (falta IG_GRAPH_TOKEN o httpx)")
    db_path = instagram._instagram_db_path()
    stats = instagram.ig_replies_poll(db_path)
    return {"ok": True, "stats": stats}


# ----- Workers -----










# === END INSTAGRAM ===================================================


# =====================================================================
# === WHATSAPP OUTREACH ===============================================
# Cold outbound por WhatsApp Web (Playwright, tu propio numero). Coge los
# telefonos de los prospects de Captacion (outreach.db) — NO hace discovery
# propio. Un unico mensaje por telefono (dedup). Envio automatico opt-in via
# WA_AUTOSEND_ENABLED + numero vinculado por QR. Riesgo ban Meta: numero 2ario.
# =====================================================================



class WhatsAppMessagePayload(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


class WhatsAppSendPayload(BaseModel):
    count: int = Field(20, ge=1, le=200)
    dry_run: bool = False










@app.get("/admin/whatsapp/stats", dependencies=[Depends(security._require_admin_token)])
def whatsapp_stats():
    with wa_capture._whatsapp_db() as conn:
        s = wa_capture.wa_outreach.stats(conn)
    return {"stats": s, "autosend_enabled": wa_capture._wa_autosend_enabled(),
            "session": wa_capture._wa_session_info(), "progress": wa_capture._wa_send_progress()}


@app.get("/admin/whatsapp/recent", dependencies=[Depends(security._require_admin_token)])
def whatsapp_recent(limit: int = 30):
    with wa_capture._whatsapp_db() as conn:
        return {"items": wa_capture.wa_outreach.recent(conn, limit)}


@app.get("/admin/whatsapp/message", dependencies=[Depends(security._require_admin_token)])
def whatsapp_message_get():
    with wa_capture._whatsapp_db() as conn:
        tpl = wa_capture.wa_outreach.get_message_template(conn)
    return {"message": tpl, "default": wa_capture.wa_outreach.DEFAULT_MESSAGE,
            "placeholders_help": wa_capture.wa_outreach.PLACEHOLDERS_HELP}


@app.put("/admin/whatsapp/message", dependencies=[Depends(security._require_admin_token)])
def whatsapp_message_put(payload: WhatsAppMessagePayload):
    with wa_capture._whatsapp_db() as conn:
        wa_capture.wa_outreach.set_message_template(conn, payload.message)
    return {"ok": True}


@app.post("/admin/whatsapp/send", dependencies=[Depends(security._require_admin_token)])
def whatsapp_send(payload: WhatsAppSendPayload, background_tasks: BackgroundTasks):
    if not wa_capture.WA_AVAILABLE:
        raise HTTPException(503, "Modulo whatsapp no disponible")
    if not payload.dry_run:
        if not wa_capture._wa_autosend_enabled():
            raise HTTPException(412, "WA_AUTOSEND_ENABLED=false en el .env del servidor")
        if not wa_capture._wa_session_info().get("connected"):
            raise HTTPException(412, "WhatsApp no conectado. Vincula tu numero (QR) en Configuracion.")
    target_count = int(payload.count)
    candidate_limit = min(500, max(target_count, target_count * 4))
    with wa_capture._whatsapp_db() as conn:
        # Rellena una bolsa extra de candidatos: los numero_invalido no cuentan
        # contra el objetivo de enviados reales.
        existing = len(wa_capture.wa_outreach.fetch_queued(conn, candidate_limit))
        need = max(0, candidate_limit - existing)
        if need:
            wa_capture.wa_outreach.enqueue(conn, need)
        items = [{"phone": q["phone"], "message": q["message"]}
                 for q in wa_capture.wa_outreach.fetch_queued(conn, candidate_limit)]
    if not items:
        return {"ok": True, "queued": 0, "detail": "No quedan telefonos nuevos por contactar."}

    if not wa_capture._wa_send_job_lock.acquire(blocking=False):
        raise HTTPException(409, "Ya hay un envio WhatsApp en curso. Espera a que termine antes de lanzar otro.")

    with wa_capture._wa_send_lock:
        wa_capture._wa_send_state.update({
            "running": True,
            "phase": "queued",
            "requested": target_count,
            "queued": target_count,
            "candidates": len(items),
            "attempted": 0,
            "sent": 0,
            "skipped": 0,
            "current_phone": "",
            "last_reason": "",
            "dry_run": bool(payload.dry_run),
            "started_at": timeutils._utc_now().isoformat(),
            "finished_at": "",
        })

    def _run() -> None:
        try:
            from whatsapp_autosend import autosend_messages  # type: ignore
        except Exception as exc:  # noqa: BLE001
            settings.logger.warning("wa autosend no disponible: %s", exc)
            with wa_capture._wa_send_lock:
                wa_capture._wa_send_state.update({
                    "running": False,
                    "phase": "error",
                    "last_reason": str(exc)[:160],
                    "finished_at": timeutils._utc_now().isoformat(),
                })
            try:
                wa_capture._wa_send_job_lock.release()
            except RuntimeError:
                pass
            return

        def _attempt(phone: str) -> None:
            with wa_capture._wa_send_lock:
                wa_capture._wa_send_state.update({"phase": "sending", "current_phone": phone, "last_reason": ""})
            try:
                with wa_capture.wa_outreach.connect() as c:
                    wa_capture.wa_outreach.mark_sending(c, phone)
            except Exception:
                pass

        def _mark(phone: str, ok: bool, reason: str) -> None:
            with wa_capture._wa_send_lock:
                wa_capture._wa_send_state["attempted"] = int(wa_capture._wa_send_state.get("attempted") or 0) + 1
                if ok:
                    wa_capture._wa_send_state["sent"] = int(wa_capture._wa_send_state.get("sent") or 0) + 1
                else:
                    wa_capture._wa_send_state["skipped"] = int(wa_capture._wa_send_state.get("skipped") or 0) + 1
                wa_capture._wa_send_state.update({
                    "phase": "skipping" if reason == "numero_invalido" else "pausing",
                    "current_phone": phone,
                    "last_reason": "" if ok else (reason or ""),
                })
            try:
                with wa_capture.wa_outreach.connect() as c:
                    if ok:
                        wa_capture.wa_outreach.mark_sent(c, phone)
                    else:
                        wa_capture.wa_outreach.mark_skipped(c, phone, reason)
            except Exception as exc:  # noqa: BLE001
                settings.logger.warning("wa mark %s: %s", phone, exc)

        try:
            autosend_messages(
                items,
                dry_run=payload.dry_run,
                on_result=_mark,
                on_attempt=_attempt,
                target_ok=target_count,
            )
        except Exception as exc:  # noqa: BLE001
            settings.logger.warning("wa autosend error: %s", exc)
            with wa_capture._wa_send_lock:
                wa_capture._wa_send_state.update({"phase": "error", "last_reason": str(exc)[:160]})
        finally:
            with wa_capture._wa_send_lock:
                if wa_capture._wa_send_state.get("phase") not in ("error",):
                    wa_capture._wa_send_state["phase"] = "done"
                wa_capture._wa_send_state.update({
                    "running": False,
                    "current_phone": "",
                    "finished_at": timeutils._utc_now().isoformat(),
                })
            try:
                wa_capture._wa_send_job_lock.release()
            except RuntimeError:
                pass

    background_tasks.add_task(_run)
    return {"ok": True, "queued": target_count, "target": target_count, "candidates": len(items), "dry_run": payload.dry_run}


@app.get("/admin/whatsapp/session", dependencies=[Depends(security._require_admin_token)])
def whatsapp_session():
    return {"session": wa_capture._wa_session_info(),
            "autosend_enabled": wa_capture._wa_autosend_enabled(),
            "login_running": bool(wa_capture._wa_login_state.get("running")),
            "login_status": wa_capture._wa_login_state.get("status", ""),
            "login_result": wa_capture._wa_login_state.get("result")}


@app.post("/admin/whatsapp/connect", dependencies=[Depends(security._require_admin_token)])
def whatsapp_connect():
    if not wa_capture.WA_AVAILABLE:
        raise HTTPException(503, "Modulo whatsapp no disponible")
    try:
        from whatsapp_autosend import start_login_session  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"whatsapp_autosend no disponible: {exc}")
    with wa_capture._wa_login_lock:
        if wa_capture._wa_login_state.get("running"):
            return {"ok": True, "already_running": True}
        wa_capture._wa_login_state.update({"running": True, "result": None, "status": "arrancando"})

    def _login() -> None:
        def _status(msg: str) -> None:
            wa_capture._wa_login_state["status"] = msg
        try:
            res = start_login_session(timeout_sec=180, headless=True, on_status=_status)
            wa_capture._wa_login_state["result"] = res
        except Exception as exc:  # noqa: BLE001
            wa_capture._wa_login_state["result"] = {"connected": False, "reason": str(exc)[:200]}
        finally:
            wa_capture._wa_login_state["running"] = False

    threading.Thread(target=_login, name="wa-login", daemon=True).start()
    return {"ok": True, "started": True}


@app.get("/admin/whatsapp/qr", dependencies=[Depends(security._require_admin_token)])
def whatsapp_qr():
    try:
        from whatsapp_autosend import latest_qr_bytes  # type: ignore
    except Exception:  # noqa: BLE001
        raise HTTPException(503, "whatsapp_autosend no disponible")
    data = latest_qr_bytes()
    if not data:
        raise HTTPException(404, "QR aun no disponible")
    return Response(content=data, media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@app.get("/admin/whatsapp/debug-shot", dependencies=[Depends(security._require_admin_token)])
def whatsapp_debug_shot():
    """Ultima captura del navegador headless (diagnostico de envio)."""
    try:
        from whatsapp_autosend import latest_debug_bytes  # type: ignore
    except Exception:  # noqa: BLE001
        raise HTTPException(503, "whatsapp_autosend no disponible")
    data = latest_debug_bytes()
    if not data:
        raise HTTPException(404, "Sin captura de debug todavia")
    return Response(content=data, media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@app.post("/admin/whatsapp/disconnect", dependencies=[Depends(security._require_admin_token)])
def whatsapp_disconnect():
    try:
        from whatsapp_autosend import clear_session  # type: ignore
    except Exception:  # noqa: BLE001
        raise HTTPException(503, "whatsapp_autosend no disponible")
    removed = clear_session()
    wa_capture._wa_login_state.update({"running": False, "result": None, "status": ""})
    return {"ok": True, "removed": removed}


@app.post("/admin/whatsapp/test", dependencies=[Depends(security._require_admin_token)])
def whatsapp_test():
    try:
        from whatsapp_autosend import verify_session  # type: ignore
    except Exception:  # noqa: BLE001
        raise HTTPException(503, "whatsapp_autosend no disponible")
    return verify_session(timeout_sec=40)


# === END WHATSAPP ====================================================


# =====================================================================
# === TIKTOK ==========================================================
# Captacion via TikTok DMs. Mismo flujo que IG campaign:
# discovery (Places + web scrape handle) → drafts → autosend Playwright.
# =====================================================================
















class TKCampaignStart(BaseModel):
    target_count: int = Field(30, ge=1, le=200)


class TKSessionCookies(BaseModel):
    sessionid: str = Field(..., min_length=10)
    sessionid_ss: str = ""
    tt_csrf_token: str = ""
    ms_token: str = ""
    ttwid: str = ""


class TKDmTemplatesPayload(BaseModel):
    variant_a: Optional[str] = None
    variant_b: Optional[str] = None
    variant_c: Optional[str] = None


class TKSuppressRequest(BaseModel):
    username: str = Field(..., min_length=1)
    reason: str = "manual"






















# ----- Endpoints campaign -----

@app.get("/admin/tiktok/campaign", dependencies=[Depends(security._require_admin_token)])
def tiktok_campaign_get():
    state = tiktok._tk_campaign_state()
    try:
        from tiktok_autosend import session_info  # type: ignore
        session = session_info()
    except Exception:
        session = {"connected": False}
    return {"campaign": state, "session": session,
            "autosend_enabled": tiktok.tk_is_autosend_enabled() if tiktok.TK_AVAILABLE else False,
            "autonomous_autosend": tiktok._tk_env_bool("TK_AUTONOMOUS_AUTOSEND", False)}


@app.post("/admin/tiktok/campaign/start", dependencies=[Depends(security._require_admin_token)])
def tiktok_campaign_start(payload: TKCampaignStart):
    if not tiktok.TK_AVAILABLE:
        raise HTTPException(503, "Modulo TikTok no disponible")
    if not tiktok.tk_is_autosend_enabled():
        raise HTTPException(412, "TK_AUTOSEND_ENABLED=false en env")
    try:
        from tiktok_autosend import session_info  # type: ignore
        if not session_info().get("connected"):
            raise HTTPException(412, "Sesion TikTok no conectada. Pega cookies primero.")
    except HTTPException:
        raise
    except Exception:
        pass
    tiktok._tk_migrate()
    tiktok._tk_campaign_update(
        target_count=int(payload.target_count),
        status="discovering",
        error_msg="",
        started_at=tiktok._tk_now(),
        completed_at="",
    )
    return {"ok": True, "state": tiktok._tk_campaign_state()}


@app.post("/admin/tiktok/campaign/pause", dependencies=[Depends(security._require_admin_token)])
def tiktok_campaign_pause():
    tiktok._tk_migrate()
    tiktok._tk_campaign_update(status="paused")
    return {"ok": True, "state": tiktok._tk_campaign_state()}


@app.post("/admin/tiktok/campaign/resume", dependencies=[Depends(security._require_admin_token)])
def tiktok_campaign_resume():
    if not tiktok.tk_is_autosend_enabled():
        raise HTTPException(412, "TK_AUTOSEND_ENABLED=false en env")
    tiktok._tk_migrate()
    state = tiktok._tk_campaign_state()
    next_status = "sending" if (state.get("pending_drafts") or 0) > 0 else "discovering"
    tiktok._tk_campaign_update(status=next_status, error_msg="")
    return {"ok": True, "state": tiktok._tk_campaign_state()}


# ----- Sesion / cookies -----

@app.get("/admin/tiktok/autosend/status", dependencies=[Depends(security._require_admin_token)])
def tiktok_autosend_status():
    try:
        from tiktok_autosend import session_info  # type: ignore
    except ImportError:
        raise HTTPException(503, "scripts/tiktok_autosend.py no disponible")
    return {
        "autosend_enabled": tiktok.tk_is_autosend_enabled(),
        "autonomous_autosend": tiktok._tk_env_bool("TK_AUTONOMOUS_AUTOSEND", False),
        "session": session_info(),
    }


@app.post("/admin/tiktok/autosend/connect", dependencies=[Depends(security._require_admin_token)])
def tiktok_autosend_connect(payload: TKSessionCookies):
    try:
        from tiktok_autosend import save_session_from_cookies, session_info  # type: ignore
    except ImportError:
        raise HTTPException(503, "scripts/tiktok_autosend.py no disponible")
    try:
        path = save_session_from_cookies(
            sessionid=payload.sessionid,
            sessionid_ss=payload.sessionid_ss,
            tt_csrf_token=payload.tt_csrf_token,
            ms_token=payload.ms_token,
            ttwid=payload.ttwid,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "saved_at": str(path), "session": session_info()}


@app.post("/admin/tiktok/autosend/disconnect", dependencies=[Depends(security._require_admin_token)])
def tiktok_autosend_disconnect():
    try:
        from tiktok_autosend import clear_session  # type: ignore
    except ImportError:
        raise HTTPException(503, "scripts/tiktok_autosend.py no disponible")
    removed = clear_session()
    return {"ok": True, "removed": removed}


@app.post("/admin/tiktok/autosend/test", dependencies=[Depends(security._require_admin_token)])
def tiktok_autosend_test():
    try:
        from tiktok_autosend import session_info  # type: ignore
    except ImportError:
        raise HTTPException(503, "scripts/tiktok_autosend.py no disponible")
    info = session_info()
    if not info.get("connected"):
        return {"ok": False, "reason": "sin_sesion"}
    sessionid = ""
    try:
        state_path = Path(info.get("path") or "")
        if state_path.exists():
            data = json.loads(state_path.read_text(encoding="utf-8"))
            for c in data.get("cookies", []):
                if c.get("name") == "sessionid":
                    sessionid = c.get("value") or ""
                    break
    except Exception as exc:
        raise HTTPException(500, f"No se pudo leer sesion: {exc}")
    if not sessionid:
        return {"ok": False, "reason": "sin_sessionid"}
    cookies = {"sessionid": sessionid}
    headers = {
        "User-Agent": os.getenv("TK_AUTOSEND_USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
        "Accept-Language": "es-ES,es;q=0.9",
    }
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            r = client.get("https://www.tiktok.com/foryou", cookies=cookies, headers=headers)
        ok = r.status_code == 200 and ("tiktok" in (r.text or "").lower())
        return {"ok": ok, "status_code": r.status_code, "session": info,
                "hint": "Cookies validas" if ok else "Cookies caducadas. Reconecta."}
    except Exception as exc:
        return {"ok": False, "reason": f"http_error: {exc}", "session": info}


# ----- DM templates editor -----



@app.get("/admin/tiktok/dm-templates", dependencies=[Depends(security._require_admin_token)])
def tiktok_dm_templates_get():
    tiktok._tk_migrate()
    out = {"A": "", "B": "", "C": ""}
    with tiktok._tk_db() as conn:
        rows = conn.execute("SELECT variant, body FROM tk_dm_templates_v2").fetchall()
        for r in rows:
            v = (r["variant"] or "").upper()
            if v in out:
                out[v] = r["body"] or ""
    defaults = {v: tiktok._tk_dm_default(v) for v in ("A", "B", "C")}
    placeholders_help = ""
    try:
        from tiktok_templates_v2 import PLACEHOLDERS_HELP  # type: ignore
        placeholders_help = PLACEHOLDERS_HELP
    except Exception:
        pass
    return {"templates": out, "defaults": defaults, "placeholders_help": placeholders_help}


@app.put("/admin/tiktok/dm-templates", dependencies=[Depends(security._require_admin_token)])
def tiktok_dm_templates_put(payload: TKDmTemplatesPayload):
    tiktok._tk_migrate()
    now = tiktok._tk_now()
    data = {"A": payload.variant_a, "B": payload.variant_b, "C": payload.variant_c}
    saved: List[str] = []
    with tiktok._tk_db() as conn:
        for variant, body in data.items():
            if body is None:
                continue
            body_clean = body.strip()
            if body_clean:
                conn.execute(
                    """INSERT INTO tk_dm_templates_v2 (variant, body, updated_at)
                       VALUES (?,?,?)
                       ON CONFLICT(variant) DO UPDATE SET body=excluded.body, updated_at=excluded.updated_at""",
                    (variant, body_clean, now),
                )
                saved.append(variant)
            else:
                conn.execute("DELETE FROM tk_dm_templates_v2 WHERE variant=?", (variant,))
                saved.append(variant + " (reset)")
        conn.commit()
    return {"ok": True, "saved": saved}


@app.post("/admin/tiktok/dm-templates/preview", dependencies=[Depends(security._require_admin_token)])
def tiktok_dm_templates_preview(variant: str = "A",
                                 business_name: str = "Clinica Sonrisa",
                                 niche: str = "clinica dental",
                                 city: str = "Madrid"):
    try:
        from tiktok_templates_v2 import render_natural  # type: ignore
    except ImportError:
        raise HTTPException(503, "tiktok_templates_v2 no disponible")
    text = render_natural(
        username=f"preview_{variant.lower()}",
        business_name=business_name,
        niche=niche,
        city=city,
        variant=variant.upper(),
        db_path=str(tiktok.TK_DEFAULT_DB),
    )
    return {"variant": variant.upper(), "text": text}


# ----- Suppressions / stats / prospects -----

@app.get("/admin/tiktok/stats", dependencies=[Depends(security._require_admin_token)])
def tiktok_stats():
    tiktok._tk_migrate()
    today = timeutils._utc_now().date().isoformat()
    with tiktok._tk_db() as conn:
        sent_today = conn.execute(
            "SELECT COUNT(*) AS c FROM tk_sends WHERE mode='sent_auto' AND substr(sent_at,1,10)=?",
            (today,),
        ).fetchone()["c"]
        sent_total = conn.execute(
            "SELECT COUNT(*) AS c FROM tk_sends WHERE mode='sent_auto'"
        ).fetchone()["c"]
        replies = conn.execute(
            "SELECT COUNT(*) AS c FROM tk_prospects WHERE status='replied'"
        ).fetchone()["c"]
        drafts = conn.execute(
            "SELECT COUNT(*) AS c FROM tk_sends WHERE mode='draft' AND ready=1"
        ).fetchone()["c"]
        prospects = conn.execute("SELECT COUNT(*) AS c FROM tk_prospects").fetchone()["c"]
    return {"totals": {"prospects": prospects, "sent_today": sent_today,
                       "sent_total": sent_total, "replies_unique": replies,
                       "drafts_pending": drafts}}


@app.post("/admin/tiktok/suppress", dependencies=[Depends(security._require_admin_token)])
def tiktok_suppress(payload: TKSuppressRequest):
    user = tiktok._tk_resolve_username(payload.username)
    if not user:
        raise HTTPException(400, "username invalido")
    tiktok._tk_migrate()
    with tiktok._tk_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO tk_suppressions (username, reason, added_at) VALUES (?,?,?)",
            (user, payload.reason or "manual", tiktok._tk_now()),
        )
        conn.execute(
            "UPDATE tk_prospects SET status='dnc', updated_at=? WHERE username=?",
            (tiktok._tk_now(), user),
        )
        conn.commit()
    return {"ok": True, "username": user}


@app.delete("/admin/tiktok/suppress/{username}", dependencies=[Depends(security._require_admin_token)])
def tiktok_remove_suppress(username: str):
    user = tiktok._tk_resolve_username(username)
    tiktok._tk_migrate()
    with tiktok._tk_db() as conn:
        conn.execute("DELETE FROM tk_suppressions WHERE username=?", (user,))
        conn.commit()
    return {"ok": True}


@app.get("/admin/tiktok/suppressions", dependencies=[Depends(security._require_admin_token)])
def tiktok_list_suppressions(limit: int = 200):
    tiktok._tk_migrate()
    with tiktok._tk_db() as conn:
        rows = conn.execute(
            "SELECT username, reason, added_at FROM tk_suppressions ORDER BY added_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return {"items": [dict(r) for r in rows]}


@app.get("/admin/tiktok/prospects", dependencies=[Depends(security._require_admin_token)])
def tiktok_prospects(limit: int = 100, status: str = ""):
    tiktok._tk_migrate()
    q = "SELECT * FROM tk_prospects"
    params: List[Any] = []
    if status:
        q += " WHERE status=?"
        params.append(status)
    q += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with tiktok._tk_db() as conn:
        rows = conn.execute(q, params).fetchall()
    return {"items": [dict(r) for r in rows]}


# ----- Worker startup/shutdown -----





# === END TIKTOK ======================================================


# ─── VOICE / TWILIO ──────────────────────────────────────────────────────────
# Canal de voz (Nivel 1: desvio de llamada -> numero Twilio -> Media Streams ->
# OpenAI Realtime API). El cliente configura en su operadora un desvio hacia el
# numero Twilio asignado. Twilio llama a POST /voice/{cliente_id}, recibe TwiML
# con <Connect><Stream> y abre un WebSocket de audio bidireccional contra
# /voice/stream/{cliente_id}, que hace de puente con OpenAI Realtime.


try:  # validador oficial Twilio si esta instalado; si no, fallback nativo HMAC-SHA1
    pass
except Exception:  # noqa: BLE001
    messaging._TwilioRequestValidator = None




































































