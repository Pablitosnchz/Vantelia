# Auditoría de refactorización — rama `refactor/estable-v1`

Fecha: 2026-06-11. Base: `main@2a0f29c` (working tree limpio).
Plan completo: refactorización en 7 fases (F0 auditoría → F6 documentación) con el
objetivo de misma funcionalidad observable y mejor estructura interna.

## Baseline verificado (antes de tocar nada)

| Check | Resultado |
| --- | --- |
| `python -m pytest -q` | **259 passed**, 0 fallos (9 min 27 s; 349 warnings de deprecación FastAPI/httpx) |
| `python -m py_compile api.py auto_onboarding.py onboarding_utils.py` | OK |
| `npm run build` | OK (`widget/widget.min.js` 47.5 kB) |
| `python scripts/qa_e2e.py` | exit 0, sin BUGs |

Gates externos que deben seguir en verde: `.github/workflows/ci.yml` (py_compile de
los 3 entrypoints + pytest + build del widget + `git diff --exit-code widget/widget.min.js`)
y `deploy/deploy.ps1` (mismos py_compile + pytest antes de empaquetar).

Dato corregido: `api.py` tiene **33.170 líneas** (~1.019 funciones top-level), no las
"8k" que indica CLAUDE.md (se corregirá en F6).

---

## 1. Clasificación de código muerto

### 1.1 SEGURO de borrar (≥90% certeza, evidencia por grep en todo el repo)

Raíz del repo (cero referencias en código, docs, deploy, CI o UIs):

| Archivo | Evidencia |
| --- | --- |
| `_leads_audit.py` | 0 referencias. Script puntual de inspección de outreach.db (19 líneas). |
| `_send_leads.py` | 0 referencias. One-off con email hardcodeado `reservas@thenookmadrid.com`. |
| `_send_leads2.py` | 0 referencias. Variante del anterior. |

`scripts/` — clúster de one-offs usados para construir/transformar `hostinger_site/`
en su día. Hoy el flujo documentado (CLAUDE.md) es editar `hostinger_site/` a mano y
replicar a `site_exports/`. Ninguno está referenciado por CLAUDE.md, README, docs/,
deploy/, CI ni package.json:

| Archivo | Evidencia |
| --- | --- |
| `scripts/build-pages.py` | Solo referenciado por build-legal.py (comentario) y footer-mailto-to-consultas.py — ambos dentro de este mismo clúster a borrar. |
| `scripts/build-legal.py` | Ídem (solo dentro del clúster). |
| `scripts/deploy-legal.py` | 0 referencias. |
| `scripts/deploy-one.py` | Solo su propio string de uso. |
| `scripts/replace-admin-css.py` | 0 referencias. |
| `scripts/extract-home-css.py` | 0 referencias. |
| `scripts/fix-favicon.py` | Solo un permiso obsoleto en `.claude/settings.local.json` que apunta a `e:\Vantelia` (ruta antigua, no funcional). |
| `scripts/footer-mailto-to-consultas.py` | Solo referencia a build-pages/build-legal (mismo clúster). |
| `scripts/resize-logos.py` | 0 referencias. Utilidad de imágenes one-off. |
| `scripts/convert-webp.py` | Solo su propio string de uso. |
| `scripts/connect-vantelia-chat.py` | 0 referencias. |
| `scripts/_set_demo_claimable.py` | Solo sus propios strings de uso. Hoy existe gestión de clientes vía panel/endpoints admin. |

Nota: todo es recuperable desde el historial de git. El mensaje de commit de F1
incluirá la lista exacta.

### 1.2 DUDOSO (decide el usuario; no se borra)

| Ítem | Situación |
| --- | --- |
| Coexistencia `instagram_templates.py` + `instagram_templates_v2.py` (y `instagram_discover.py` + `_v2`) | **Ambas versiones están activas**: v1 la importan api.py:28843/28848, `scripts/instagram_campaign.py` y hasta `tests/test_api_smoke.py:3583`; v2 se importa lazy en api.py (render_natural, pick_variant, discover_real). No es código muerto, pero es deuda: candidata a consolidación en una iteración futura, fuera del alcance de este refactor. |
| Permiso obsoleto en `.claude/settings.local.json` apuntando a `e:\Vantelia\scripts\fix-favicon.py` | Limpieza cosmética opcional (archivo local de configuración del harness). |

### 1.3 NO TOCAR (verificado activo u operativo)

| Ítem | Por qué |
| --- | --- |
| `email-validator` (requirements.txt) | `EmailStr` se usa 18 veces (api.py x6, api_models.py x12); es extra requerido de pydantic. |
| Resto de requirements.txt y package.json | Todo importado/usado (uvicorn vía CLI, playwright opcional gated por env, esbuild para el build). |
| `onboarding_ui/` | Servido por api.py:19345 (`ONBOARDING_UI_DIR / "index.html"`). |
| `auto_onboarding.py`, `onboarding_utils.py` | Entrypoints de los gates py_compile (CI, deploy.ps1, CLAUDE.md); README documenta `streamlit run auto_onboarding.py`. |
| `scripts/scale_tracker.py` | Citado como respaldo operativo en CLAUDE.md:554 y docs/SEGUIMIENTO_PLAN_ESCALA.md:85. |
| `scripts/clone_public_site.py` | Documentado en site_exports/README.md como generador de snapshots. |
| Scripts operativos de captación | outreach_*, instagram_*, tiktok_*, whatsapp_*, seed_outreach_templates, stripe_* — importados por api.py o documentados en CLAUDE.md. |
| `hostinger_site/`, `site_exports/` | 100% sincronizados entre sí; fuera del alcance del refactor. |
| `storage/`, `data/`, `.env*`, `config.json`, `secrets` | Datos/secretos. Intocables. |
| `deploy/`, `Dockerfile`, `.github/workflows/ci.yml` | Pipeline; `uvicorn api:app` debe seguir funcionando sin cambios. |

### 1.4 Local no versionado (informativo, sin commit posible)

- `.env.ftp` — gitignored (`.env.*`); resto de config FTP antigua.
- `.tools/` — gitignored; patches SVN antiguos. Borrable a mano si se quiere.

---

## 2. Inventario de duplicación backend (objetivos FASE 2)

No existe **ninguna** función/clase top-level definida dos veces en api.py, ni
colisiones de nombre entre api.py y onboarding_utils.py. Tampoco hay TODO/FIXME/HACK.
La deduplicación de F2 es de *patrones*, no de nombres:

| Patrón | Ocurrencias | Acción F2 |
| --- | --- | --- |
| `sqlite3.connect(...)` directo | 19 (vs 184 usos de `_get_db_connection()`) | Unificar SOLO los que apuntan a la DB principal. ⚠️ Varios son de DBs separadas (outreach.db, instagram.db, tiktok.db, whatsapp.db) — esos NO se unifican. |
| `datetime.now(timezone.utc)` | 83 (vs 20 usos de `_utc_now()`) | Normalizar a `_utc_now()` donde sea semánticamente idéntico. Beneficio extra: más código respeta el time-travel de los tests (que monkeypatchean `_utc_now`). Revisar caso a caso. |
| Bloque de defaults de booking (`"rescheduled_from_booking_id": ""`, `"reminder_*_sent_at": ""`, ...) | x5 idéntico | Extraer helper de defaults de fila de booking. |
| 35 ventanas de 5 líneas repetidas >2 veces (heurística) | — | Revisar durante F3; extraer solo equivalencias demostrables. |

---

## 3. Inventario frontend (objetivos FASE 4)

### admin_ui/index.html (10.894 líneas)

| Hallazgo | Evidencia | Acción |
| --- | --- | --- |
| `openClientSection` declarada DOS veces en el MISMO scope | Líneas 4903 (`tab="profile"`, versión antigua con setView/setClientTab) y 5293 (`tab="resumen"`, versión drawer). Por hoisting JS la segunda pisa a la primera: **la de 4903 es código muerto**. | Borrar la de 4903. |
| `escapeHtml` interior haciendo shadowing | Línea 9737 (scope anidado de un módulo) vs 4379 (scope principal). Implementaciones equivalentes (mismos 5 caracteres escapados, mismo manejo de null). | Borrar la interior; resuelve a la exterior. |
| `loadStats` x3, `loadProspects` x2, `loadAutopilot` x2, `loadHotLeads` x2, `loadJobs` x2, `loadSuppressions` x2, `addSuppression` x2, `runDiscovery` x2, `loadFollowupQueue` x2 | Scopes ANIDADOS distintos (módulos de Captación / Instagram / WhatsApp, cada uno autocontenido). | NO tocar: no son duplicados reales. |

### app_ui/index.html (5.344 líneas) y access_ui/index.html (884 líneas)

Sin duplicados reales (solo variables locales con el mismo nombre en funciones
distintas). Sin acción.

### Entre SPAs (deliberado, sin acción)

`api()`, `formatDetail()`/`formatApiDetail()` y `escapeHtml()` se repiten entre las
tres SPAs con variaciones mínimas. Se mantienen: las SPAs son single-file
autocontenidas por diseño.

### widget/

Modular y limpio; `widget.min.js` al día (CI verifica reproducibilidad). Solo
rebuild de verificación en F4.

---

## 4. Tests (objetivos FASE 5)

- 5 archivos (`test_api_smoke`, `test_booking_exhaustive`, `test_client_channels`,
  `test_crm_light`, `test_ai_payment_link`), **sin `conftest.py`**: la fixture
  session-scoped `api_module` (crea dirs temporales + ~30 env vars + reimporta `api`)
  está duplicada en los 5.
- **110 sitios** de `monkeypatch.setattr(api_module, ...)` — el shim proxy de F3 los
  soporta sin tocarlos; en F5 se centralizan fixtures en `conftest.py`.
- `scripts/qa_e2e.py` itera `dir(api)` y hace `setattr` dinámico de `_send_whatsapp*`
  (líneas 87-98) — contrato que el shim debe respetar (`__dir__` + `__setattr__`).

---

## 5. Estado de ejecución de fases

| Fase | Estado | Commit |
| --- | --- | --- |
| Preparación (rama + baseline) | ✅ Hecha | — |
| F0 Auditoría | ✅ | be07543 |
| F1 Borrado de lo "seguro" (15 archivos, aprobado) | ✅ | 4f53a9e |
| F2 Deduplicación backend | ✅ | c092a58 |
| F3.0 Esqueleto backend/ + proxy + guardias shim | ✅ | 58502bc |
| F3.1 backend/settings.py | ✅ | f273828 |
| F3.2 backend/appstate.py (alias "state" colisionaba con OAuth) | ✅ | 0a1af2a |
| F3.3 backend/timeutils.py + backend/textnorm.py + CONFIG_CLIENTES | ✅ | 9479eaf |
| F3.4 backend/db.py | ✅ | 6b93c07 |
| F3.5 backend/clients.py | ✅ | be4f757 |
| F3.6 backend/security.py (+extras textnorm/clients/timeutils) | ✅ | b8c62ed |
| F3.7 backend/emailing.py + messaging.py + stripe_gateway.py | ✅ | 4ada884 |
| F3.8 backend/agenda.py | ✅ | 69812e5 |
| F3.9 backend/rag.py | ✅ | a1f1031 |
| F3.10 backend/booking.py + crm.py + demo_agenda.py | ✅ | 511b19f |
| F3.11 backend/chat.py + whatsapp.py | ✅ | d74eb90 |
| F3.12 onboarding/outreach/instagram/tiktok/wa_capture/voice/growth/billing/portal | ✅ | d60df59 |
| **CHECKPOINT A**: 26 módulos backend; api.py 33.170→13.176 líneas (solo endpoints+app+proxy) | ✅ | — |
| F3.13 backend/main.py (app/middlewares/mounts/eventos) | Pendiente | — |
| F3.14+ routers por dominio (333 endpoints) + shim final api.py | Pendiente | — |
| F4 Frontend | Pendiente | — |
| F5 Tests + conftest | Pendiente | — |
| F6 Documentación | Pendiente | — |

Notas de transición F3 (para retomar en sesiones futuras):
- Patrón por módulo: cortar bloque → `backend/<mod>.py` con acceso cualificado
  (herramienta `scripts/_refactor_qualify.py`, mapeo maestro por AST) → api.py
  re-importa los nombres como copias transitorias → añadir módulo a
  `_HOME_MODULES` del epílogo proxy de api.py → pytest completo en verde.
- Estado mutable: SIEMPRE cualificado (`appstate.X`), nunca copia.
- Aliases que colisionan con locales de api.py: `state` (OAuth) y `settings`
  (canales/outreach). Por eso el módulo de estado se llama `appstate`; cuando
  se muevan canales/outreach, renombrar sus locales `settings` al moverlos.
- Gate rápido: `python -m pytest -q -p no:warnings` (~1,5 min vs ~10 min).
- Herramientas de empalme en %TEMP%: `extract_lib.py` (master_mapping por AST,
  block_analysis, extract_defs por nombre, closure transitivo) — si se pierde,
  regenerarla a partir del patrón de los commits f3.4-f3.7.
- Tras cada extracción: (1) escaneo AST de nombres no resueltos en backend/*.py
  (detecta imports que faltan que py_compile no ve), (2) strip de
  auto-referencias `<mod>.` dentro del propio módulo (basado en tokens, NO
  regex plano — los docstrings sufren), (3) pop de los nombres del propio
  módulo destino del mapeo antes de cualificar.
- El canal Bash de la sesión se come `\\` — generar código con chr(10) o Edit.
- Riesgos ya mordidos (no repetir): NO usar strip de auto-referencias por regex
  (machacó params llamados `booking`); los nombres de módulo no deben chocar con
  locals/estado histórico (`state`→appstate, `whatsapp_flows`→whatsapp módulo,
  `wa_outreach`→wa_capture); los try/except de imports de scripts y los probes
  *_AVAILABLE deben moverse ENTEROS con su dominio.
- Bug latente pre-existente (sin tocar): `discovered_count` sin asignar en el
  log de `_outreach_run_discovery_job` (backend/outreach.py ~1789-1802).
- F3.14 routers: preservar ORDEN de registro de rutas (first-match de FastAPI);
  mover endpoints por secciones contiguas e incluir routers en el orden
  original de aparición.

Si una sesión se queda sin contexto: dejar todo committeado y actualizar esta tabla.
