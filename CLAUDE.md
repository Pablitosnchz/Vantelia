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
portal_ui/           SPA del portal cliente.
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

- Mantener single-file SPA en `admin_ui/index.html`, `access_ui/index.html` y `portal_ui/index.html`.
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

No enviar emails reales en pruebas. Usa entornos o credenciales dummy.

## WhatsApp

WhatsApp reutiliza la misma logica de chat/RAG y guardado de conversaciones. Puntos sensibles:

- Verificacion webhook con `WHATSAPP_VERIFY_TOKEN`.
- Validacion de firma con `WHATSAPP_APP_SECRET` si esta configurado.
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

Tokens firmados HMAC-SHA256 con `OUTREACH_TRACKING_SECRET`. Si secret vacio o `OUTREACH_TRACKING_DISABLED=true`, el tracking se desactiva sin romper el envio.

### Variables de entorno

- `OUTREACH_DB_PATH`: ruta SQLite. Default `storage/outreach/outreach.db`.
- `OUTREACH_TRACKING_SECRET`: secreto HMAC. **Obligatorio** para activar tracking.
- `OUTREACH_TRACKING_BASE_URL`: URL publica de la API (ej. `https://app.vantelia.es`).
- `OUTREACH_TRACKING_DISABLED`: `true` para desactivar pixel y reescritura de links.
- `OUTREACH_UNSUBSCRIBE_EMAIL`: buzon que recibe BAJA (default `baja@vantelia.es`).
- `OUTREACH_BCC`: bcc opcional para todos los envios.
- `OUTREACH_DOMAIN_DAILY_CAP`: tope diario por dominio destinatario (default 3).
- `OUTREACH_RESPECT_WINDOW`, `OUTREACH_START_HOUR`, `OUTREACH_END_HOUR`, `OUTREACH_SKIP_WEEKEND`: ventana laboral.
- `OUTREACH_MSGID_DOMAIN`: dominio del Message-ID generado.
- `GOOGLE_PLACES_API_KEY`: requerido para discovery automatico.
- `IMAP_HOST`/`IMAP_PORT`/`IMAP_USER`/`IMAP_PASSWORD`: fase 2 (autodeteccion respuestas, no implementado todavia).

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

### Comandos CLI utiles (alternativa al panel)

```powershell
python scripts/outreach_campaign.py import --csv outreach/prospects_torrejon.csv
python scripts/outreach_campaign.py send --stage cold --max 10 --send
python scripts/outreach_campaign.py followup --stage fu1 --after-days 4 --send
python scripts/outreach_campaign.py stats
python scripts/outreach_discover.py --sector "clinica dental" --ciudad "Torrejon" --max 30 --output outreach/dental.csv
```

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
