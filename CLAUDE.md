# Vantelia - Guia de contexto para agentes

## Resumen

Vantelia es una plataforma SaaS multi-tenant para asistentes IA embebibles en webs B2B del mercado espanol. El cliente instala un widget JavaScript, el widget habla con una API FastAPI, y la API responde con RAG, agenda inteligente, emails transaccionales y WhatsApp Cloud API.

La web comercial publica vive separada como sitio estatico en Hostinger. La aplicacion operativa vive en `app.vantelia.es`: API, panel admin, portal cliente y widget.

## Mapa del repositorio

```text
api.py               Backend FastAPI monolitico. Mantener en un solo archivo salvo peticion explicita.
widget/              Widget embebible vanilla JS. Fuente en modulos, build en widget.min.js.
admin_ui/            SPA del dashboard admin, HTML/CSS/JS en un solo index.html.
access_ui/           SPA de login/acceso.
app_ui/              SPA del portal cliente real, servida en GET /app.
hostinger_site/      Web comercial publica para Hostinger static hosting.
site_exports/        Snapshots limpios para subir a Hostinger. Deben reflejar hostinger_site cuando toque.
data/                Bases documentales por cliente para RAG: data/<cliente>/info.txt.
storage/             SQLite + indices llama-index. Gitignored, no tocar ni commitear.
docs/                Manuales operativos, legales y guias.
deploy/              Docker, compose y guias de despliegue.
scripts/             Backups, FTP y utilidades.
config.json          Config multi-tenant de clientes.
.env.example         Plantilla de entorno. No copiar secretos reales.
```

## Stack

| Capa | Tecnologia |
| --- | --- |
| Backend | Python 3.11, FastAPI, uvicorn, Pydantic |
| IA/RAG | llama-index, OpenAI, `gpt-4o-mini`, `text-embedding-3-small` |
| Persistencia | SQLite local e indices vectoriales en `storage/` |
| Widget | JavaScript ES6 vanilla, bundle con esbuild |
| UI admin/portal | HTML/CSS/JS sin framework |
| Web publica | HTML/CSS/JS estatico |
| Hosting API | Hostinger VPS con Docker |
| Hosting web | Hostinger static/FTP |
| Canales | Web widget, portal, email SMTP, WhatsApp Cloud API |
| Agenda | Interna por cliente |

## Reglas de oro

- Trabaja en espanol para textos visibles, contenido comercial, emails, legales y mensajes de usuario.
- No introduzcas frameworks frontend. El proyecto usa HTML/CSS/JS vanilla.
- No dividas `api.py` en modulos salvo que el usuario pida una refactorizacion grande.
- No metas secretos en git. `.env`, `storage/`, DBs, service accounts reales y tokens deben quedarse locales.
- No rompas compatibilidad del widget: muchas webs dependeran del snippet y de `data-*`.
- Cambios en `hostinger_site/` deben replicarse en `site_exports/vantelia_static_clean/` cuando sean para produccion.
- El sitemap no debe contener fragmentos `#`. Solo URLs limpias indexables.
- Mantener `allowed_origins` por cliente y `EXTRA_CORS_ORIGINS` alineados con dominios reales.
- Si modificas agenda, emails, auth o WhatsApp, ejecuta tests backend como minimo.
- Respeta cambios existentes no relacionados. En este repo puede haber archivos modificados por el usuario.

## Comandos habituales

Instalacion local:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
npm install
copy .env.example .env
```

Arranque backend:

```powershell
uvicorn api:app --host 0.0.0.0 --port 8000
```

Build del widget:

```powershell
npm run build
```

Tests y checks minimos:

```powershell
python -m pytest
npm run build
python -m py_compile api.py auto_onboarding.py onboarding_utils.py
```

QA E2E manual del portal (entorno AISLADO, no toca datos reales) — recorre todo
lo que un cliente puede hacer (agenda web/portal/WhatsApp, servicios, IA, cerebro,
Q&A, apariencia, leads, billing, equipo, horarios, asistencia, chats...). Crea
config/storage/data temporales y un usuario cliente con plan business. Sale con
codigo 1 si hay BUGs (500 o fallo real). Usar para probar "como usuario real":

```powershell
python scripts/qa_e2e.py
```

Backup local:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\backup.ps1
```

Despliegue API en VPS:

```bash
docker compose -f deploy/hostinger/docker-compose.yml up -d --build
```

Subida web estatica a Hostinger:

```powershell
.\scripts\deploy-ftp.ps1
```

## Backend API

`api.py` tiene unas 8k lineas y concentra modelos, helpers, persistencia, auth, booking, endpoints, WhatsApp y UI serving. Antes de editar, busca el bloque exacto con `rg`.

Endpoints publicos principales:

- `GET /health`
- `GET /cliente/{cliente_id}`
- `GET /profesionales/{cliente_id}`
- `POST /chat`
- `GET /disponibilidad`
- `POST /agendar`
- `GET /servicios/{cliente_id}`
- `GET /booking/manage/{manage_token}`
- `GET /legal/{documento}`
- `GET /acceso`, `/login`, `/portal`, `/dashboard`, `/demo/{cliente_id}`
- `GET/POST /whatsapp/webhook`
- `GET/POST /whatsapp/webhook/{cliente_id}`
- `POST /consulta` — captura leads desde el formulario de `vantelia.es/consultas/`. Acepta `ConsultaLeadPayload` (nombre, email, telefono?, empresa?, servicio?, mensaje?). Rate limit 5/min por IP. Envia dos emails via SMTP desde `SMTP_FROM_EMAIL` (info@vantelia.es): notificacion a `CONSULTA_NOTIFICATION_EMAIL` (asunto "Nueva consulta recibida", Reply-To = email del lead) y confirmacion al lead (asunto "Hemos recibido tu consulta").

Endpoints de portal/auth:

- `POST /auth/login`, `/auth/logout`
- `POST /auth/password/change`, `/auth/password/forgot`, `/auth/password/reset`
- `GET /auth/me`, `/auth/dashboard`, `/auth/bookings`, `/auth/chats`
- `GET/POST /auth/ai-config`, `/auth/brain`, `/auth/schedule`
- Gestion de empleados, bloqueos, citas, usuarios y exportaciones bajo `/auth/*`.

Endpoints admin con token:

- `POST /admin/alta-express`
- `POST /admin/reindex/{cliente_id}`
- `GET /admin/stats`
- `POST /admin/clientes/{cliente_id}/demo-agenda` — genera datos demo en la agenda (~1 mes de citas repartidas entre 3 profesionales `empdemo_*`, citas marcadas `source='demo_seed'`). Idempotente: regenera limpiando lo anterior. No toca datos reales.
- `DELETE /admin/clientes/{cliente_id}/demo-agenda` — borra todos los datos demo (bookings `demo_seed` + empleados `empdemo_*` + sus bloqueos/auditoria).
- Endpoints de clientes, bookings y chats definidos cerca del bloque admin.

## Configuracion multi-tenant

`config.json` es la fuente de verdad de clientes. Cada cliente debe tener:

- Identidad: `nombre`, `icono`, `color`, `bienvenida`, `branding`.
- Seguridad: `allowed_origins`.
- RAG: `data/<cliente_id>/info.txt`.
- Agenda: `booking.enabled`, timezone, horario, proveedor y mensajes.
- WhatsApp opcional: `whatsapp.enabled`, `phone_number_id`, token por entorno si aplica.

Cuando se cambie informacion RAG de un cliente, reindexar con:

```powershell
curl -X POST http://localhost:8000/admin/reindex/CLIENTE_ID -H "Authorization: Bearer TOKEN"
```

No borrar `storage/` sin backup si contiene datos reales.

## Variables de entorno clave

Grupos importantes en `.env.example`:

- OpenAI: `OPENAI_API_KEY`, `CHAT_MODEL`.
- Admin/portal: `ADMIN_API_TOKEN`, `PORTAL_ADMIN_EMAIL`, `PORTAL_ADMIN_PASSWORD`, `PORTAL_COOKIE_DOMAIN`.
- URLs/CORS: `APP_BASE_URL`, `EXTRA_CORS_ORIGINS`.
- SMTP: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`, `SMTP_REPLY_TO`.
- WhatsApp: `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_APP_SECRET`, `WHATSAPP_PHONE_CLIENT_MAP`.
- Booking: `MAX_BOOKING_ADVANCE_DAYS`, `BOOKING_AUTO_COMPLETE_HOURS`.
- Limites: `SESSION_TTL_SECONDS`, `MAX_MESSAGES_PER_SESSION`, `CHAT_RATE_LIMIT_PER_MINUTE`, `BOOKING_RATE_LIMIT_PER_MINUTE`.
- Recordatorios: `REMINDER_24H_HOURS`, `REMINDER_2H_HOURS`, `REMINDER_RUN_INTERVAL_MINUTES`.

## Widget

Fuente:

```text
widget/widget.js     Entrada, init, carga config, monta UI.
widget/ui.js         DOM principal del widget.
widget/chat.js       POST /chat, render Markdown basico, escape XSS.
widget/form.js       Flujo de agenda.
widget/styles.js     CSS inyectado con variables por cliente.
widget/utils.js      Config, session id, fetchJson y timeouts.
```

Build:

```powershell
npm run build
```

Snippet esperado:

```html
<script
  src="https://app.vantelia.es/widget/widget.min.js"
  data-api="https://app.vantelia.es"
  data-client="CLIENTE_ID"
  data-position="right"></script>
```

No cambies nombres de atributos `data-*` ni estructura publica sin compatibilidad hacia atras.

## Web publica en Hostinger

Dominio: `https://www.vantelia.es`.

`hostinger_site/` contiene la web comercial estatica. Tiene `index.html`, `consultas/index.html`, `404.html`, `robots.txt`, `sitemap.xml`, `.htaccess` y assets.

Convenciones SEO:

- Canonical correcto por pagina.
- OG y Twitter Card presentes.
- JSON-LD cuando aplique: Organization, WebSite, ContactPage, FAQPage, Service, BreadcrumbList.
- `robots` con indexacion limpia.
- `sitemap.xml` solo con paginas canonicas indexables, sin anchors.
- Redirecciones legacy en `.htaccess`, evitando 404 innecesarios.

Al cambiar la web publica:

1. Edita `hostinger_site/`.
2. Replica cambios relevantes en `site_exports/vantelia_static_clean/`.
3. Actualiza sitemap/robots si cambia una URL indexable.
4. Comprueba enlaces absolutos a `https://www.vantelia.es` y widget a `https://app.vantelia.es`.

## UI admin, acceso y portal

- Mantener single-file SPA en `admin_ui/index.html`, `access_ui/index.html` y `app_ui/index.html`. La ruta `/portal` es solo un redirect estable (a `/dashboard`, que enruta admin->admin_ui y cliente->/app); no sirve UI propia.
- Priorizar interfaces densas, claras y operativas. No convertirlas en landing pages.
- Evitar dependencias externas nuevas salvo necesidad clara.
- Textos visibles en espanol, con tono profesional.
- Si un cambio requiere datos nuevos, coordinar modelo Pydantic, endpoint y consumo UI en la misma tarea.

## Booking, emails y recordatorios

El sistema soporta agenda interna por cliente. Antes de tocar booking, revisar:

- Validacion de disponibilidad.
- Zona horaria del cliente.
- Estados de cita y enlaces `manage_token`.
- Cancelacion, reprogramacion y timeline/auditoria.
- Emails transaccionales y recordatorios.
- Tests en `tests/test_api_smoke.py`.

Catalogo de servicios con duracion y precio: tabla `services` (PK `cliente_id+slug`; slug = id normalizado del nombre, compatible con `employees.service_ids_json`). Se siembra desde `info.txt` la primera vez (`_ensure_services_seeded`). El parser `_extract_services_from_info` extrae el precio de la web (lineas "Precio:"/"Tarifa:" → `_parse_price_to_cents`, soporta "45 €", "60,50", "1.250 €", "A consultar"=0) y la duracion si aparece ("Duracion: 45 min"/"1 h" → `_parse_duration_minutes_text`); si no hay duracion, **30 min por defecto**. El prompt de onboarding (`onboarding_utils.py`) pide el formato Servicio/Precio/Duracion/Detalle por servicio. Endpoints portal (sesion; admin con `?cliente_id=`): `GET/POST /auth/services`, `PATCH/DELETE /auth/services/{slug}`. `GET /servicios/{cliente_id}` (publico) y `/disponibilidad` devuelven `duration_minutes` + `price_cents`/`price_label`. La disponibilidad es por intervalos: un servicio de N min ocupa N min sobre el grid (`slot_minutes` = paso) en TODOS los canales (widget, portal, WhatsApp); helpers `_service_duration_minutes`, `_booked_intervals`, `_interval_overlaps`. La cita guarda `service_id` + `service_price_cents` (snapshot). El email de confirmacion muestra "Servicio · N min · precio". UI: pestana "Servicios" en el portal + selector con duracion/precio en Nueva cita y en el widget. Editar un servicio no cambia su slug (mantiene enlaces). Tras tocar servicios/duracion, `npm run build` para el widget.

Alta manual de cita desde el portal (walk-in / telefono): `POST /auth/bookings` (sesion portal; admin requiere `?cliente_id=`). Valida ventana + hueco libre del profesional, crea `confirmed` con `source='portal_manual'`, envia email de confirmacion si hay email. En la UI: boton "+ Nueva cita" y click en hueco vacio de la vista Dia (prefija fecha/hora/profesional).

Estados de cita: `pending_review`, `confirmed`, `cancelled`, `completed`, `no_show`. Tras pasar la hora, `_auto_complete_past_bookings` pasa confirmadas/pendientes a `completed` con `completed_source='auto'` (presunta asistencia). El staff confirma asistencia real en el portal (vista Día → detalle): `POST /auth/bookings/{id}/attendance` `{attended: bool}` marca `completed`/`no_show` con `completed_source='manual'`; es corregible (auto→no_show, etc.). El badge distingue auto vs confirmado manual. `_portal_stats_for_user` expone `completed`, `no_show` y `attendance_rate`; el portal muestra la tira en la pestaña Citas.

No enviar emails reales en pruebas. Usa entornos o credenciales dummy.

## WhatsApp

WhatsApp reutiliza la misma logica de chat/RAG y guardado de conversaciones. Puntos sensibles:

- Verificacion webhook con `WHATSAPP_VERIFY_TOKEN`.
- Validacion de firma con `WHATSAPP_APP_SECRET` obligatoria (rechaza 503 si vacio, 403 si firma invalida).
- Mapeo phone number id -> cliente con `WHATSAPP_PHONE_CLIENT_MAP` o config por cliente.
- Token global `WHATSAPP_ACCESS_TOKEN` o variable especifica por cliente.
- No responder si el cliente no esta habilitado o no se puede resolver con seguridad.

## Captacion / Outreach

Modulo separado para captar clientes B2B mediante email outbound multi-touch.

### Componentes

- `scripts/outreach_campaign.py`: CLI principal (import, preview, send, followup, suppress, stats). Estado en `storage/outreach/outreach.db`.
- `scripts/outreach_templates.py`: plantillas por stage (cold/fu1/fu2/breakup), copy por nicho, tracking helpers (HMAC tokens).
- `scripts/outreach_discover.py`: discovery via Google Places + extraccion de emails publicos de webs corporativas.
- `outreach/`: CSVs de prospects (no commitear datos reales).
- Panel web: pestaña "Captacion" en `admin_ui/index.html`. Sub-tabs: Dashboard, Prospects, Campañas, Discovery, Plantillas, Bajas.

### Endpoints admin (Bearer ADMIN_API_TOKEN o sesion admin del portal)

- `GET    /admin/outreach/stats`
- `GET    /admin/outreach/prospects` (filtros q, status, niche, city, source, stage, page, page_size)
- `GET    /admin/outreach/prospects/{email}` (timeline completo)
- `POST   /admin/outreach/prospects` (alta manual)
- `PATCH  /admin/outreach/prospects/{email}` (edicion parcial: status, notes, score, etc.)
- `DELETE /admin/outreach/prospects/{email}`
- `POST   /admin/outreach/import` (CSV crudo en body)
- `GET    /admin/outreach/export.csv`
- `POST   /admin/outreach/send` (lanza job background, devuelve job_id)
- `GET    /admin/outreach/jobs`, `GET /admin/outreach/jobs/{id}`
- `POST   /admin/outreach/suppress`, `DELETE /admin/outreach/suppress/{email}`, `GET /admin/outreach/suppressions`
- `GET    /admin/outreach/templates`, `PUT /admin/outreach/templates`
- `POST   /admin/outreach/discover` (Google Places, en background)
- `POST   /admin/outreach/replies` (marcar prospect como respondido)

### Endpoints publicos de tracking

- `GET /track/open/{token}.gif`: pixel 1x1 + log de open.
- `GET /track/click/{token}?u=URL`: redirect 302 + log de click. Solo permite redirect a hosts en `OUTREACH_TRACKING_ALLOWED_HOSTS`.

Tokens firmados HMAC-SHA256 con `OUTREACH_TRACKING_SECRET`. Tracking es opt-in: requiere `OUTREACH_TRACKING_ENABLED=true` ademas de `OUTREACH_TRACKING_SECRET` y `OUTREACH_TRACKING_BASE_URL`. Si falta cualquiera de las tres, el tracking se desactiva sin romper el envio.

### Variables de entorno

- `OUTREACH_DB_PATH`: ruta SQLite. Default `storage/outreach/outreach.db`.
- `OUTREACH_TRACKING_SECRET`: secreto HMAC. **Obligatorio** para activar tracking.
- `OUTREACH_TRACKING_BASE_URL`: URL publica de la API (ej. `https://app.vantelia.es`).
- `OUTREACH_TRACKING_ENABLED`: `true` para activar pixel + reescritura de links. **Sin esta var, tracking desactivado aunque secret y base_url esten set.**
- `OUTREACH_UNSUBSCRIBE_EMAIL`: buzon que recibe BAJA (default `baja@vantelia.es`).
- `OUTREACH_BCC`: bcc opcional para todos los envios.
- `OUTREACH_DOMAIN_DAILY_CAP`: tope diario por dominio destinatario (default 3).
- `OUTREACH_RESPECT_WINDOW`, `OUTREACH_START_HOUR`, `OUTREACH_END_HOUR`, `OUTREACH_SKIP_WEEKEND`: ventana laboral.
- `OUTREACH_MSGID_DOMAIN`: dominio del Message-ID generado.
- `GOOGLE_PLACES_API_KEY`: requerido para discovery automatico.
- `IMAP_HOST`/`IMAP_PORT`/`IMAP_USER`/`IMAP_PASSWORD`/`IMAP_FOLDER`/`IMAP_USE_SSL`: poller IMAP de respuestas. Cuando matchea (por `In-Reply-To` con `sends.message_id` o por remitente conocido) registra evento `reply`, marca `prospects.status='replied'` y los siguientes stages (`fu1/fu2/breakup`) se saltan automaticamente. Filtra autoresponders (Auto-Submitted, asuntos "Out of office"). Implementado en `scripts/outreach_imap.py` y arrancado por `_outreach_imap_worker` en `api.py`.
- `OUTREACH_IMAP_INTERVAL_MINUTES`: intervalo del poller (default 10).
- `OUTREACH_IMAP_LOOKBACK_DAYS`: ventana IMAP en cada pasada (default 14).

### Fase 4 (mayo 2026): Subjects A/B + proof line

- Subjects reescritos lowercase + curiosidad en `scripts/outreach_templates.py`. Pools separados A/B por stage en `SUBJECT_POOLS_AB`. Asignacion estable por hash(email|stage) → mismo prospect siempre recibe misma variante en ese stage.
- `pick_subject_with_variant(stage, p)` devuelve `(subject, "A"|"B")`. `pick_subject` se mantiene como compat shim.
- Tabla `sends` tiene columna `subject_variant` (migracion idempotente). El job de envio de campanas y el CLI rellenan la variante en cada insert.
- `GET /admin/outreach/ab-stats?stage=cold&days=30` devuelve por variante: enviados, opens unicos, clicks unicos, replies unicos + open/click/reply rate. Incluye top 3 subjects mas usados por variante.
- Panel Dashboard incluye widget "A/B subjects" con tabla y selector de stage. Marca en azul (mejor open rate) y verde (mejor reply rate).
- `OUTREACH_PROOF_LINE`: frase de credibilidad opcional inyectada en cold (ej: "Lo monte para Clinica Sonrisa, reciben 22 consultas/semana"). Vacio = sin proof. Sin tocar codigo, basta editar `.env`.

### Fase 1 (mayo 2026): Hot leads + reply detection

- `GET /admin/outreach/hot-leads?limit=&days=` devuelve prospects que abren/clican y aun no han respondido. Score = clicks_recent\*6 + opens_recent\*2 + clicks_total\*3 + opens_total. Excluye replied/client/lost/bajas.
- `POST /admin/outreach/imap/poll` fuerza una pasada manual del poller IMAP.
- Panel Dashboard de Captacion incluye widget "Hot leads" con CTA email/telefono y botón "Comprobar respuestas".
- `fetch_candidates` (`outreach_campaign.py`) y el job de envio de campanas (`api.py`) excluyen prospects con evento `reply` o status en `(replied, client, lost)`.

### Flujo operativo desde el panel

1. Captacion → Discovery: indicar sector y ciudad, lanzar busqueda. Revisar resultados, marcar `Importar directo` si confias o exportar CSV.
2. Captacion → Prospects: filtrar, editar manualmente, crear nuevos, importar CSV propio.
3. Captacion → Campañas: lanzar `cold` con `Dry-run` o `test-to`; cuando este OK, lanzar real.
4. Captacion → Plantillas: editar copy por stage si quieres pisar el default.
5. Captacion → Dashboard: monitorizar tasas open/reply. Si un prospect responde, abrir su drawer y marcar "respondido" o cambiar status.
6. Captacion → Bajas: gestionar lista de supresion. Cada vez que un destinatario responda BAJA, anadir aqui.

### Compliance

- Tratamiento bajo interes legitimo LSSI/RGPD: cada email lleva footer con razon social, finalidad y baja al instante.
- Cabeceras `List-Unsubscribe` + `List-Unsubscribe-Post: One-Click`.
- Discovery solo extrae emails publicamente listados en webs corporativas. Respeta robots.txt y aplica rate limit.
- No usar listas compradas. No suplantar identidad. No hacer scraping agresivo.
- Para no caer en spam, configurar SPF/DKIM/DMARC en `vantelia.es` antes de envios reales.

### Modo automático (captación pasiva)

El sistema busca prospects, filtra, importa, lanza cold y follow-ups solo. Usuario solo mira dashboard.

Tabla `autopilot_config` (id=1) con: `enabled`, `targets_json` (lista `[{"sector","city"}, ...]`), `daily_new_target`, `daily_cold_cap`, `auto_followups`, `last_discovery_at`, `last_cold_at`.

Endpoints:
- `GET /admin/outreach/autopilot-config` — config + stats (cold hoy, importados 24h)
- `PUT /admin/outreach/autopilot-config` — patch parcial (enabled, targets, daily_new_target, daily_cold_cap, auto_followups)
- `POST /admin/outreach/autopilot-tick` — fuerza ronda inmediata

Worker `_outreach_autonomous_worker` arranca en startup si `OUTREACH_AUTONOMOUS_ENABLED=true`. Cada `OUTREACH_AUTONOMOUS_TICK_MINUTES` (default 60) ejecuta:
1. **Discovery**: si pasaron `OUTREACH_AUTONOMOUS_DISCOVERY_HOURS` desde la última (default 6h), itera targets, filtra (sin email/cadenas/duplicados/bajas), importa con tag `autopilot`.
2. **Cold**: cuenta sends de hoy con stage=cold mode=send. Si < cap, lanza send job para hasta `min(cap-sent, daily_new_target)` prospects nuevos con source/tag `autopilot`.
3. **Follow-ups**: si `auto_followups=1`, dispara autopilot run (max=10).

Salvaguardas:
- Kill switch dual: env `OUTREACH_AUTONOMOUS_ENABLED` + `enabled` en DB
- Ventana laboral respetada (start/end hour, skip weekend)
- Sin `GOOGLE_PLACES_API_KEY` → skip discovery
- Sin SMTP → skip cold/followups
- Cadenas conocidas (vivanta, kivet, sanitas...) descartadas
- Errores loggean `[autopilot]` sin romper el thread

Panel admin: tab "Modo automático". Switch ON/OFF, editor de targets, configuración de cap/target, toggle auto-followups, stats en vivo, botón "Ejecutar ronda ahora".

### Comandos CLI utiles (alternativa al panel)

```powershell
python scripts/outreach_campaign.py import --csv outreach/prospects_torrejon.csv
python scripts/outreach_campaign.py send --stage cold --max 10 --send
python scripts/outreach_campaign.py followup --stage fu1 --after-days 4 --send
python scripts/outreach_campaign.py stats
python scripts/outreach_discover.py --sector "clinica dental" --ciudad "Torrejon" --max 30 --output outreach/dental.csv
```

## Captacion Instagram

Modulo paralelo a outreach por email. Envio en modo HIBRIDO COMPLIANT por defecto: NO se automatiza el envio. El sistema scrapea perfiles publicos, genera drafts de DM personalizados por prospect+stage y muestra una cola en el panel admin con boton "Enviar DM" que abre Instagram via `https://ig.me/m/{username}?text=...` y permite enviar manual con 1 clic. Tras volver al panel se marca como enviado.

Modo agresivo (Playwright + sesion IG) bajo flag `IG_AUTOSEND_ENABLED=false`. Activar implica violar ToS Meta y arriesgar bloqueo de la cuenta — usar cuenta secundaria.

### Componentes

- `scripts/instagram_templates.py`: copy por stage (cold/fu1/fu2/breakup) con variantes A/B estables, niche hook (dental, estetica, fisio, gimnasio, restaurante, hotel, etc.), CTA a `OUTREACH_CALENDAR_URL` con fallback a la landing publica `https://www.vantelia.es`.
- `scripts/instagram_discover.py`: Graph API (Business Discovery) si hay `IG_GRAPH_TOKEN`+`IG_BUSINESS_ACCOUNT_ID`. Fallback scrape publico read-only de `instagram.com/{user}/` con rate limit 1 req/2s. Sin login.
- `scripts/instagram_campaign.py`: CLI espejo de outreach_campaign (import, discover, preview, draft, send, followup, suppress, stats). Schema en `storage/instagram/instagram.db`.
- `scripts/instagram_replies.py`: poller Graph API para mensajes entrantes de cuenta business propia. Marca prospects como `replied`.

### Endpoints admin (Bearer ADMIN_API_TOKEN o sesion admin)

- `GET    /admin/instagram/stats`
- `GET    /admin/instagram/prospects` (filtros q, status, niche, city, source, page)
- `GET    /admin/instagram/prospects/{username}` (timeline)
- `POST   /admin/instagram/prospects`, `PATCH /admin/instagram/prospects/{username}`, `DELETE /admin/instagram/prospects/{username}`
- `POST   /admin/instagram/import` (CSV crudo), `GET /admin/instagram/export.csv`
- `POST   /admin/instagram/discover` (background job), `GET /admin/instagram/jobs`, `GET /admin/instagram/jobs/{id}`
- `POST   /admin/instagram/draft` (genera N drafts por stage)
- `GET    /admin/instagram/drafts` (cola pendiente con `deep_link` ig.me ya construido)
- `PATCH  /admin/instagram/drafts/{id}` (editar texto antes de enviar)
- `POST   /admin/instagram/drafts/{id}/mark-sent`, `POST /admin/instagram/drafts/{id}/skip`
- `POST   /admin/instagram/send` (412 si `IG_AUTOSEND_ENABLED=false`; opt-in Playwright)
- `POST   /admin/instagram/suppress`, `DELETE /admin/instagram/suppress/{username}`, `GET /admin/instagram/suppressions`
- `GET    /admin/instagram/templates`, `PUT /admin/instagram/templates` (overrides por stage)
- `GET    /admin/instagram/hot-leads`, `GET /admin/instagram/ab-stats?stage=cold&days=30`
- `GET/PUT /admin/instagram/autopilot-config`, `POST /admin/instagram/autopilot-tick`
- `POST   /admin/instagram/replies` (marcar respondido manual), `POST /admin/instagram/replies/poll`

### UI

Tab "Instagram" en sidebar admin. Sub-tabs: Dashboard, Drafts (cola 1-clic), Prospects, Discovery, Plantillas, Autopiloto, Bajas.

Drafts es el sub-tab clave: card por prospect con avatar, @username, bio, niche, score, textarea editable y boton "Enviar DM" que abre ig.me en nueva pestana. Al volver al panel, confirm dialog y POST mark-sent.

### Comandos CLI

```powershell
python scripts/instagram_campaign.py discover --usernames cuenta1,cuenta2 --niche "clinica dental" --city "Madrid"
python scripts/instagram_campaign.py preview --stage cold --limit 3
python scripts/instagram_campaign.py draft --stage cold --max 20
python scripts/instagram_campaign.py followup --stage fu1 --after-days 5 --send
python scripts/instagram_campaign.py suppress --username @cuenta --reason BAJA
python scripts/instagram_campaign.py stats
```

### Variables .env clave

`IG_DB_PATH`, `IG_GRAPH_TOKEN`, `IG_BUSINESS_ACCOUNT_ID`, `IG_AUTOSEND_ENABLED`, `IG_AUTONOMOUS_ENABLED`, `IG_AUTONOMOUS_TICK_MINUTES`, `IG_AUTONOMOUS_DISCOVERY_HOURS`, `IG_RESPECT_WINDOW`, `IG_START_HOUR`, `IG_END_HOUR`, `IG_SKIP_WEEKEND`, `IG_PUBLIC_RATE_LIMIT_SEC`, `IG_REPLIES_INTERVAL_MINUTES`.

### Autosend Playwright (opt-in agresivo)

`scripts/instagram_autosend.py` implementa el envio automatico real via Playwright + sesion persistente. **Solo activar con cuenta IG secundaria** — viola ToS Meta y puede provocar ban.

Setup:

```powershell
pip install playwright==1.47.0
python -m playwright install chromium
# Generar sesion (interactivo, requiere ver navegador):
python scripts/instagram_autosend.py login
# Verificar:
python scripts/instagram_autosend.py status
```

Env vars para activar el modo full-autonomo:

- `IG_AUTOSEND_ENABLED=true` — habilita endpoint `/admin/instagram/send` + CLI.
- `IG_AUTONOMOUS_AUTOSEND=true` — autopilot dispara autosend tras crear drafts (sin intervencion).
- `IG_SESSION_PATH` — JSON storage state (default `storage/instagram/session.json`).
- `IG_USERNAME`, `IG_PASSWORD` — solo para `login` interactivo.
- `IG_AUTOSEND_HEADLESS` — default `true`. Pon `false` para depurar.
- `IG_AUTOSEND_DAILY_CAP` — DMs reales/dia (default 20). Recomendado 10-20 cuenta nueva.
- `IG_AUTOSEND_MIN_DELAY_SEC` / `IG_AUTOSEND_MAX_DELAY_SEC` — delay entre DMs (default 45/180s).
- `IG_AUTOSEND_TYPING_MIN_MS` / `IG_AUTOSEND_TYPING_MAX_MS` — delay teclado humano (default 35/120ms).
- `IG_AUTOSEND_USER_AGENT` — UA opcional.

Drafts enviados → `mode='sent_auto'` (no `'sent'`). Fallos → `mode='skipped'` con `skip_reason`. Si sesion expira, autosend aborta el ciclo y deja drafts pendientes para reintento manual o tras nuevo `login`.

### Compliance

- Scrape publico solo lee bio/og:description, sin login, rate-limited.
- Graph API requiere cuenta business propia y permisos formales Meta.
- Listas de supresion honradas en discovery, drafts y autopilot.
- Sin firma comercial estilo email en los DMs (rapido = spam en IG). Solo opener + hook + link demo.

## Tests actuales

`tests/test_api_smoke.py` cubre:

- Healthcheck.
- CORS por cliente.
- Proteccion admin token.
- Login portal.
- Disponibilidad sin OpenAI.
- Paginas legales.
- Intent de cita en chat sin OpenAI.
- Webhook WhatsApp y almacenamiento de chats.

Si cambias contratos de respuesta, auth, cookies, booking o WhatsApp, actualiza o amplia estos tests.

## Documentacion util

- `README.md`: instalacion, endpoints y operacion general.
- `docs/Funcionalidades.md`: resumen funcional.
- `docs/MANUAL_ADMIN.md`: operacion del panel.
- `docs/MANUAL_GOOGLE_CALENDAR.md`: calendario.
- `docs/OPERACION_PRODUCCION.md`: checklist minima para vender/operar.
- `deploy/hostinger/DEPLOY.md`: guia VPS/Hostinger.
- `docs/legal/*.md`: textos legales servidos por `/legal/{documento}`.

## Checklist antes de cerrar una tarea

- El cambio esta en los archivos correctos y no toca secretos.
- Si hay build generado, `widget/widget.min.js` esta actualizado cuando cambia el widget.
- Si cambia la web publica, `site_exports/vantelia_static_clean/` queda sincronizado.
- Si cambia SEO, sitemap/canonical/robots siguen coherentes.
- Si cambia backend, `python -m pytest` pasa o se documenta por que no pudo ejecutarse.
- Si cambia Python, `python -m py_compile api.py auto_onboarding.py onboarding_utils.py` pasa.
- Si cambia JS del widget, `npm run build` pasa.
- No se han revertido cambios no relacionados del usuario.

## Notas de despliegue

- Produccion recomendada: `vantelia.es` para web publica y `app.vantelia.es` para API, panel y widget.
- `APP_BASE_URL` debe apuntar a `https://app.vantelia.es` en produccion.
- `PORTAL_COOKIE_DOMAIN=.vantelia.es` permite compartir sesion entre subdominios cuando aplica.
- `EXTRA_CORS_ORIGINS` debe incluir `https://vantelia.es`, `https://www.vantelia.es` y `https://app.vantelia.es`. Critico para el formulario de `/consultas/` que hace POST cross-origin a `app.vantelia.es`.
- Para escalar a varias instancias, el siguiente paso natural es mover SQLite a Postgres y externalizar indices/storage.
- `deploy/deploy.ps1` usa `%TEMP%` para generar el `.tar.gz` (no el directorio padre del proyecto, que puede ser `C:\` sin permisos de escritura).
- `site_exports/` esta excluido del empaquetado VPS — contiene rutas muy largas que rompen el cleanup en Windows. Solo sirve para snapshots manuales del sitio publico.
