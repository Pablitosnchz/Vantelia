# Vantelia - Guia de contexto para agentes

## Resumen

Vantelia es una plataforma SaaS multi-tenant para asistentes IA embebibles en webs B2B del mercado espanol. El cliente instala un widget JavaScript, el widget habla con una API FastAPI, y la API responde con RAG, agenda inteligente, emails transaccionales y WhatsApp Cloud API.

La web comercial publica vive separada como sitio estatico en Hostinger. La aplicacion operativa vive en `app.vantelia.es`: API, panel admin, portal cliente y widget.

## Mapa del repositorio

```text
api.py               Shim de compatibilidad (~150 lineas): uvicorn api:app + proxy del namespace historico.
backend/             Implementacion real: modulos por dominio + main.py (app) + routers/ (endpoints). Ver docs/ARQUITECTURA.md.
api_models.py        Modelos Pydantic compartidos (requests/responses).
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
- El backend esta modularizado en `backend/` (refactor junio 2026). Entre modulos de backend el acceso es CUALIFICADO (`from backend import booking` + `booking.helper()`), nunca from-import de funciones: el proxy de `api.py` y los monkeypatch de tests dependen de ello. Clases y modelos Pydantic si pueden importarse por nombre. No toques el shim `api.py` ni el orden de import de routers en `backend/main.py` sin leer docs/ARQUITECTURA.md.
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

El backend vive en `backend/` (28 modulos de dominio + `backend/routers/` con 17 modulos de endpoints); `api.py` es solo el entrypoint de compatibilidad. Mapa completo, convenciones y "donde anadir cosas" en `docs/ARQUITECTURA.md`. Antes de editar, localiza el modulo del dominio con `rg`. Nota: el py_compile de CI/deploy cubre los entrypoints; `python -m pytest` importa todo backend/ (cobertura equivalente).

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
- `GET /auth/conversations` (historial unificado: chat web + WhatsApp + voz, etiquetado por `channel`, filtros `channel`/`q`) y `GET /auth/conversations/{kind}/{id}` (`kind`=chat|voice; voz devuelve transcripcion + `summary_text` + duracion). Mezcla `chat_sessions` (web vs `origin` `whatsapp:<num>`) con `voice_calls` (`transcript_json`). Helpers `rag._conversation_chat_dict`, `voice._list_voice_calls`/`_voice_conversation_dict`/`_voice_call_detail_dict`. UI: pestana "Chats" -> "Conversaciones" (filtros por canal + buscador + transcripcion; la voz muestra cabecera con duracion/resultado/resumen).
- `GET/POST /auth/ai-config`, `/auth/brain`, `/auth/schedule`
- Gestion de empleados, bloqueos, citas, usuarios y exportaciones bajo `/auth/*`.

Endpoints admin con token:

- `POST /admin/alta-express`
- `POST /admin/reindex/{cliente_id}`
- `GET /admin/stats`
- `POST /admin/clientes/{cliente_id}/demo-agenda` — genera una **demo completa** para enseñar al cliente: agenda (~1 mes de citas entre 3 profesionales `empdemo_*`, `source='demo_seed'`) **+ comercio** (centros `locdemo_*`, productos `proddemo_*`, bonos `pkgdemo_*`, tarjetas regalo `gcdemo_*`, ventas `saledemo_*` y package_purchases `ppdemo_*`). Idempotente: regenera limpiando lo anterior. No toca datos reales. Seeder en `demo_agenda._seed_demo_agenda` (+ `_seed_demo_commerce`).
- `DELETE /admin/clientes/{cliente_id}/demo-agenda` — borra **todos** los datos demo por prefijo de id (citas `demo_seed` + empleados `empdemo_*` + bloqueos/auditoria + centros/productos/bonos/gift cards/ventas demo). `demo_agenda._purge_demo_agenda` (+ `_purge_demo_commerce`).
- Endpoints de clientes, bookings y chats definidos cerca del bloque admin.

## Configuracion multi-tenant

**OJO — secciones extra del config (fix jul 2026):** `clients._normalize_client_config` (carga) y `_serialize_client_config` (guardado) son WHITELIST. Cualquier seccion nueva de config por tenant DEBE registrarse en `clients.CONFIG_EXTRA_SECTIONS` (hoy: `empresa`, `reminders`, `reviews`, `gift_cards_public`) o se descarta silenciosamente en cada arranque/guardado (bug real: Seguimiento/resenas/identidad volvian a defaults en runtime tras cada deploy aunque el JSON las tuviera).


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

**Voz en el widget (opt-in):** si el negocio activa `voice.widget_enabled` (config + plan Business; toggle "Voz en el widget web" en pestana Asistente de voz del portal), el widget muestra un boton de microfono que abre una llamada de voz (WebRTC directo a OpenAI Realtime) con tools REALES (reserva de verdad). `GET /cliente/{id}` expone `voice_widget_enabled`. Endpoints publicos: `POST /voice/widget/{cliente_id}/session`, `POST /voice/widget/{cliente_id}/tool` (ejecuta `_voice_dispatch_tool` real) y `POST /voice/widget/{cliente_id}/log` (al colgar, el widget envia la transcripcion -> inserta `voice_calls` `purpose='widget'` con resumen `_voice_summarize` -> aparece en Conversaciones). Gating en los tres: `_voice_widget_enabled` + `_enforce_allowed_origin` + rate limit. NO usar prefijo `/widget/...` (colisiona con el static mount). Front: `widget/voice.js` (overlay `.ia-v-*`, la llamada se monta DENTRO de `#ia-w-chat`, no a pantalla completa; acumula transcripcion y la registra al colgar), boton mic en `widget/ui.js`, CSS en `widget/styles.js`. Tras tocar el widget, `npm run build`.

**Motor de voz compartido (refactor jul 2026 — anti-duplicacion):** la logica determinista que encarrila al modelo (anti-silencio, nudges, confirmacion, dedup de reserva, fallback de fecha) NO se reescribe por canal. Hay DOS motores con UNA copia cada uno y la MISMA spec: (1) **navegador** — funciones puras en `widget/voice_core.js` (ESM); el widget las importa (esbuild las inlinea en `widget.min.js`) y `app_ui` (single-file SPA) las consume via `window.VanteliaVoiceCore`, cargado con `<script type="module" src="/widget/voice_core.js">`. El bucle CON ESTADO (watchdog, envio al datachannel) sigue en cada cliente. (2) **telefono/Twilio** — `backend/voice_engine.py`: la clase **`VoiceCallEngine`** posee el estado de la llamada y TODA la logica determinista (configuracion de sesion, `on_openai_event` = el antiguo cuerpo del bucle `openai_to_twilio`, `maybe_recover_silence` = watchdog, `force_*` = fallbacks de mutacion/reserva, `create_booking_deduped`, etc.). El puente `routers/voice_web.py` quedo **fino (~290 lineas, antes 1574)**: solo abre los WebSockets, reenvia audio Twilio↔OpenAI y delega cada decision en el motor via callbacks de transporte inyectados (`bind_transport(send_openai, send_twilio, clear_playback, truncate_interrupted)`); la clase NUNCA toca el WebSocket. Testeado de verdad en `tests/test_voice_engine.py` (unit de las funciones puras + **harness de integracion** que alimenta `on_openai_event` con un `FakeTransport` + `DispatchStub` y asierta lo emitido: crear cita→habla forzada, dedup de doble reserva, reprogramacion al haber hueco, reset de turno, confirmacion saliente). Contrato navegador↔Twilio en `test_browser_voice_bridge_matches_twilio_recovery_contract`; contrato del motor en `test_twilio_voice_bridge_cancels_silent_active_response`. Al tocar deteccion/frases/flujo, cambiar la fuente unica (voice_core.js o voice_engine.py), no el puente ni las copias.

**Cerebro flexible — "modelo al mando + tools como guardarrail" (jul 2026):** se retiro el scripting rigido que peleaba con el modelo. El prompt (`_voice_build_instructions`) es orientado a OBJETIVOS (no un guion de frases). El motor YA NO fuerza frases verbatim ("di exactamente esta frase"), ni dice "no te he entendido", ni ejecuta la cascada de `force_*` (cancelar/reprogramar/pedir servicio/centro/slot/verificacion) — todo eso se elimino. Lo que queda: (a) **correccion en las TOOLS** — dedup de reserva (`create_booking_deduped`), verificacion de identidad (las tools de cancelar/reprogramar exigen telefono/email o OTP), hueco libre (consultar_disponibilidad); (b) **tecnico** — barge-in (`truncate_interrupted`), latch de respuesta activa, cancelar respuesta muda; (c) **UN empujon INTERNO** cuando el modelo se queda mudo: `_nudge_continue` (Twilio) / `continueNudge` (navegador, texto en `voice_core.CONTINUE_NUDGE_TEXT`) inyecta un mensaje de sistema recordando el contexto y `response.create` con tool_choice libre — el modelo REFORMULA con sus palabras, nunca una frase fija de cara al cliente. Los resultados de tool se transmiten con guia NATURAL (mantener datos exactos), no verbatim. Regla: la fiabilidad se pone en las TOOLS, no en encarrilar el dialogo. Coste: si el modelo falla, no hay red que ponga la frase por el (se asume que gpt-realtime decide bien).

**Transferir a humano + colgar limpio + etiquetado (jul 2026):** tools `transferir_a_humano` (solo si el negocio configura `voice.transfer_number`, campo en portal Asistente de voz) y `finalizar_llamada` (siempre). Telefono: `voice._voice_transfer_call` reescribe el TwiML de la llamada viva a `<Say>+<Dial>` (Twilio cierra el Stream). Colgar limpio: el motor pone `state['should_end_call']`; el puente rompe el loop cuando la ultima frase ya se dijo (`response` cerrada + `turn_had_assistant_output`) -> finalize + `websocket.close()`. Watchdog: tras >3 recuperaciones sin respuesta, despedida + colgar. Navegador (WebRTC no desvia): `_voice_dispatch_tool` devuelve el numero para llamar; `finalizar_llamada` devuelve `end_call:true` y el front cuelga solo tras la despedida (widget/app_ui: al `response.done` con audio ya emitido, +3,5s; demo: timer 6s). El dispatch de demo (`_voice_dispatch_tool_demo`) responde honesto a `finalizar_llamada`/`transferir_a_humano`/`enviar_enlace_pago` (antes caian en "Funcion desconocida"). **Etiquetado de resultado**: `voice_calls.outcome` (reservada/confirmada/cancelada/reprogramada/transferida/sin_accion) sellado en el motor y guardado en `_voice_finalize_call`; `_voice_stats` anade `by_outcome`+`total` (`GET /admin/voice/calls`). Requiere validacion en llamada REAL (Twilio call-control no testeable en unit; los tests cubren la decision con stubs).
- **Avisos / bandeja (panel)**: `GET /auth/app/alerts` devuelve `{total, items[]}` con citas sin confirmar, retenciones por capturar (perm payments.capture), pagos fallidos (perm payments.refund) y stock bajo (perm catalog.manage). UI: campana en la topbar con badge + dropdown que navega a la pestaña. Tambien en la topbar: **busqueda global** (Ctrl+K, clientes + conversaciones) y, en Citas, vista **Semana** (rango 7 dias encuadrado a lunes). Clientes tiene **"+ Nuevo cliente"** (POST `/auth/app/contacts`). Cobros/reembolsos usan modal `promptAmount` (no `window.prompt`).

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

## Multi-local (centros), salas y pre-autorizacion de pago

Soporte multi-local generico por tenant (junio 2026, origen pliego The Nook; valido para cualquier negocio):

- **Centros**: tabla `locations` (centro default auto-creado por tenant en startup via `_ensure_default_locations_for_all_clients`, con backfill de employees/bookings/agenda_blocks heredados). Cada empleado pertenece a un centro (`employees.location_id`); el aislamiento de agenda entre centros es automatico porque el conflicto de cita es por empleado. `_store_booking` sella `bookings.location_id` desde el empleado (cubre todos los canales). Endpoints: `/auth/locations` CRUD, publico `GET /centros/{cliente_id}`; `location_id` query param en `/profesionales`, `/disponibilidad`, `/servicios` y body de `/agendar`. Widget: atributo opcional `data-location`. UI: bloque "Centros" en pestana Equipo del portal + selector de centro en el editor de empleado (solo visible con >1 centro).
- **Servicios por centro** (overlay): tabla `service_location_overrides` (is_available + price_cents/duration_minutes NULL=hereda del catalogo base). `_catalog_services(location_id=)`, `_service_duration_minutes` resuelve por el centro del empleado, `_service_price_cents_resolved` para el snapshot de precio. Endpoints: `GET /auth/services/{slug}/locations`, `PUT/DELETE /auth/services/{slug}/locations/{loc}`. UI: seccion "por centro" en el drawer de servicio.
- **Numero por centro**: `locations.whatsapp_phone_number_id` y `locations.voice_phone_number`; `agenda._location_for_channel()` resuelve el centro del numero entrante y WhatsApp (`_wa_location_id`) y voz (`_voice_call_location_id` -> `_voice_dispatch_tool(location_id=)`) acotan disponibilidad/reserva a ese centro. El system prompt del agente incluye bloque CENTROS (`rag._locations_prompt_block`, solo si >1 centro) y pide elegir centro antes de reservar.
- **Salas/recursos (aforo opt-in)**: tabla `resources` por centro + `bookings.resource_id`. Sin salas configuradas no hay limite por espacio; con N salas activas, max N citas solapadas en el centro (`_location_capacity_ok`, enganchado en `_booking_slot_available`, `_booking_slot_available_for_reschedule` y `_employee_slot_sets_for_day`). `_assign_free_resource` asigna sala best-effort al guardar. Endpoints `/auth/locations/{id}/resources` + `/auth/resources/{id}`. UI: lista de salas en el panel del centro.
- **Pre-autorizacion (retencion sin cobro)**: `services.payment_type='preauth'` -> checkout Stripe con `capture_method='manual'` (`booking_payments.capture_method`). El webhook marca `preauthorized` (cita confirmada, tarjeta retenida). Desde el panel (detalle de cita, vista Dia): `POST /auth/bookings/{id}/payment/capture` (total/parcial, p.ej. penalizacion no-show), `/release` (libera sin cobro) y `/refund` (total/parcial sobre pagos cobrados). Todo con auditoria en `booking_audit`. Limite Stripe: la retencion caduca ~7 dias.
- **Politica de cancelacion/no-show automatica (generica, opt-in)**: tabla `cancellation_policies` (PK cliente_id: `enabled`, `free_cancel_hours`, `late_cancel_fee_pct`, `no_show_fee_pct`, `auto_apply`, `policy_text`) + override por servicio (`services.cancel_free_hours/cancel_late_fee_pct/no_show_fee_pct`, NULL=hereda). Motor en `backend/booking.py`: `get/save_cancellation_policy`, `_resolve_cancellation_policy_for_booking`, `compute_cancellation_outcome(kind='cancel'|'no_show')` (dentro de la ventana de cortesia = sin penalizacion; fuera = `late_cancel_fee_pct`; no-show = `no_show_fee_pct`; base = `service_price_cents`), `apply_cancellation_policy` (idempotente). Al cancelar (portal `auth_cancel_booking` y `_cancel_booking_core` para voz/chat/WhatsApp/manage-link) o marcar no-show, si la politica esta activa y `auto_apply` se actua **solo sobre el pago ya autorizado**: captura la penalizacion de una retencion (libera el resto), o reembolsa la parte no penalizada de un pago cobrado. Nunca crea cargos nuevos. Auditoria `cancellation_policy_evaluated/applied/failed`. Default OFF. Endpoints: `GET/PUT /auth/app/cancellation-policy` (manager+), `GET /auth/bookings/{id}/cancellation-preview` (calcula cancelar-ahora vs no-show sin tocar Stripe). UI: bloque "Politica de cancelacion y no-show" en Cuenta + overrides en el drawer de servicio; el panel muestra penalizacion/reembolso en un dialogo de confirmacion (`confirmDialog`) antes de cancelar/no-show.

## Comercio del portal (productos, bonos, gift cards), informes y roles

Modulos `backend/commerce.py` y `backend/analytics.py` + router `backend/routers/portal_commerce.py` (junio 2026, estilo Fresha/Mindbody, generico por tenant):

- **Productos** (POS ligero): tabla `products` (stock opcional) + `product_sales`. CRUD `/auth/products`, venta `POST /auth/products/{id}/sell` (precio siempre del catalogo, nunca del request), listado `/auth/product-sales`. UI: pestana Ventas > Productos (drawer con bloque "Registrar venta"). La pestana **Ventas** esta redisenada estilo Fresha/Square (clases `.vsell-*`): KPIs por sub-seccion (ingresos hoy/ventas/stock bajo en Productos; catalogo/activos/sesiones pendientes en Bonos; activas/saldo en circulacion/emitidas en Tarjetas), grid de tarjetas de catalogo, filas de venta con icono, tarjetas regalo con **visual de gradiente** + barra de saldo, y estados vacios (`vEmpty`/`vKpi`). Tarjeta de producto trae accion rapida "📲 Cobrar" (QR) al hover (perm `commerce.sell`).
- **Cobro POS con Stripe (QR/enlace en mostrador + producto sobre la cita)**: a diferencia de `_sell_product` (registro manual de efectivo/datafono), aqui el cliente paga DE VERDAD con tarjeta via Stripe Checkout sobre la cuenta Connect del negocio. `commerce.create_pos_payment_link(items, booking_id, ...)` arma el checkout (lineas de producto + opcional el servicio de la cita), inserta `customer_payments` con `kind='pos'` + `line_items_json` (NO registra la venta aun), y devuelve enlace + **QR** (`commerce._qr_svg` via `segno`: devuelve un `<img>` PNG data-URI —raster, no SVG, porque el SVG de segno usa strokes que al escalar quedan ilegibles—; `border=4` quiet zone, fondo blanco horneado, `error="m"`; vacio si segno no esta). La venta se materializa en el webhook Connect (`/stripe/connect/webhook`) cuando el pago pasa a `paid`: `commerce._finalize_pos_payment(connection, payment, now)` (idempotente via `product_sales.customer_payment_id`) registra las ventas `payment_method='stripe'` descontando stock y, si hay `booking_id`, marca `bookings.payment_status='paid'` + audit `booking_paid_pos`. Endpoints (permiso `commerce.sell`): `POST /auth/pos/charge` (devuelve `payment_id`, `url`, `amount_cents`, `qr_svg`), `GET /auth/pos/charge/{id}` (poll de estado). UI: modal "Cobrar con tarjeta" (carrito editable -> QR + estado en vivo) — boton "📲 Cobrar con tarjeta (QR)" en el drawer de producto y "📲 Cobrar + producto (QR)" en el detalle de cita. `segno` en requirements (genera el QR del enlace).
- **Bonos** (paquetes de sesiones): tablas `packages` (items_json = [{service_slug, qty}], validity_days) y `package_purchases` (remaining_json, caducidad lazy). CRUD `/auth/packages`, venta `POST /auth/packages/{id}/sell` (requiere email o telefono del comprador), redencion `POST /auth/package-purchases/{id}/redeem {booking_id}` -> descuenta sesion del servicio de la cita y marca `payment_status='paid'` + audit `package_redeemed`. UI: Ventas > Bonos + boton "🎟 Bono" en el detalle de cita (busca bonos activos por email/telefono de la cita).
- **Compra PUBLICA de tarjetas regalo (jul 2026, opt-in `config['gift_cards_public']`, plan en docs/PLAN_GIFT_CARDS_PUBLICO.md)**: pagina `GET /gift/{cliente_id}` (branding del tenant, chips de importes sugeridos + libre con min/max, comprador/destinatario/mensaje 300c, envio inmediato o programado) + `POST /gift/{cliente_id}/checkout` -> `customer_payments kind='gift_card'` + Stripe Checkout (cuenta Connect, mismo rail que el POS). La tarjeta se emite en el webhook (`commerce._finalize_gift_card_payment`, idempotente via `gift_cards.customer_payment_id`) y el email al destinatario (gradiente + codigo grande, `_gift_card_email_bodies`) lo envia `_send_pending_gift_card_emails` (tras el webhook y en el worker de recordatorios; los programados esperan su fecha en `gift_cards.scheduled_send_at`, sella `sent_at`). Config portal: `GET/PUT /auth/app/gift-cards-public` (manager+) + tarjeta "Venta online" en Ventas>Tarjetas (toggle, importes, URL publica copiable; avisa si falta Stripe). Chat: quick action "🎁 Tarjeta regalo" + respuesta determinista con el enlace (`_message_requests_gift_card` + `commerce.gift_public_available` = enabled Y Stripe operativo). Gating de pagina/checkout: 404 sin opt-in o sin Stripe; rate limit por IP. F2: tarjeta POR SERVICIO (tab en la pagina; precio SIEMPRE del catalogo del servidor via `_gift_resolve_service`, se ignora el importe del cliente), color de acento por compra (`_gift_accent_or_empty`, hex validado, tinye el email), ocultar importe/caducidad (flags por compra; con servicio el titular ve el nombre del servicio, con hide_value "Una experiencia"), y copia imprimible al COMPRADOR (segundo email con nota). La emision de mostrador y la redencion NO cambian.
- **Tienda publica de bonos y productos (jul 2026, opt-in `config['shop_public']`, inspirada en SimpleSpa)**: pagina `GET /tienda/{cliente_id}` (branding del tenant; tabs Bonos y Productos; carrito con cantidades para productos, recogida en el centro — sin envios) + `POST /tienda/{cliente_id}/checkout/bono` y `/checkout/productos` -> `customer_payments` `kind='shop_package'`/`'shop_products'` + Stripe Checkout (cuenta Connect, mismo rail que POS/gift). La compra se materializa en el webhook Connect: `commerce._finalize_shop_package_payment` (crea `package_purchases` activo con snapshot de sesiones tomado al crear el checkout, idempotente via `package_purchases.customer_payment_id` — columna nueva) y `_finalize_shop_products_payment` (ventas `payment_method='stripe'` con nombre/email del comprador + descuenta stock, idempotente via `product_sales.customer_payment_id`); tras el commit, email de confirmacion al comprador (`_send_shop_confirmation_email`, best-effort, solo si la compra se creo en esa llamada). Precio SIEMPRE del catalogo del servidor (`_pos_resolve_lines` valida stock). Gating pagina/checkout: `shop_public_available` (opt-in por seccion + Stripe operativo + catalogo con items activos), 404 si no, rate limit por IP. Config portal: `GET/PUT /auth/app/shop-public` (manager+; `enabled_packages`, `enabled_products`, `intro_text`, `pickup_note`) + tarjetas "Venta online" en Ventas>Bonos y Ventas>Productos (toggle, URL publica copiable, avisos sin Stripe/sin catalogo). `shop_public` registrado en `clients.CONFIG_EXTRA_SECTIONS`. Tests en `tests/test_shop_public.py`. La pagina enlaza a `/gift/{id}` si la venta de tarjetas esta activa.
- **Tarjetas regalo**: tablas `gift_cards` (codigo `GC-XXXX-XXXX` unico por tenant, balance, estados active/redeemed/disabled/expired) + ledger `gift_card_transactions` (issue/redeem). Emision `POST /auth/gift-cards`, redencion `POST /auth/gift-cards/redeem {code, booking_id}`: descuenta min(saldo, importe); si cubre todo -> cita `paid` (audit `gift_card_redeemed`), si no -> parcial con `remaining_due_cents` (audit `gift_card_partial`, la cita NO queda paid). UI: Ventas > Tarjetas regalo + boton "🎁 Tarjeta regalo" en detalle de cita.
- **Ficha de cliente como hub de recepcion** (app_ui, sin backend nuevo): la pestana Clientes -> ficha (`openClientePanel`) agrega KPIs + bonos/saldo del cliente y lleva botones que reusan los endpoints de comercio prefijando el contacto: "🔁 Nueva cita" (`openNewBookingDrawer`), "🎟 Vender bono" (`sellBonoDialog` -> `/auth/packages/{id}/sell`), "🎁 Tarjeta regalo" (`issueGiftDialog` -> `/auth/gift-cards`) y "🛒 Cobrar / producto" (`openPosCharge` QR), todos gateados por `hasPerm('commerce.sell')`. El detalle de cita lleva "👤 Ver cliente" (`openClienteFromBooking`): resuelve el contacto por email/telefono (`/auth/app/contacts?q=`), salta a Clientes y abre su ficha. `vModal(html,{title})` es el helper de modal generico reutilizable.
- **Central de mostrador (jul 2026, estilo SimpleSpa/Fresha)**: Ventas -> subtab **Central** (por defecto) = POS operativo: catalogo izquierda (tabs Servicios/Productos/Bonos/Tarjetas, buscador `centralSearch`; servicio -> `openNewBookingDrawer` prefijado, producto -> ticket, bono -> `openPackagePanel`, tab Tarjetas lista las activas con saldo lazy `/auth/gift-cards?status=active`), ticket derecha (cliente con **autocomplete CRM** `/auth/app/contacts?q=` -> `centralSelectContact` rellena email/telefono y `loadCentralAssets` muestra bonos/tarjetas activos del cliente + boton "Ver ficha"; cobro del ticket via `openPosCharge` con `presetProducts`). Encima, **KPIs de HOY** de `GET /auth/app/central/summary` (perm `commerce.sell`, `analytics._central_summary`: citas hoy + cobradas, ingresos hoy con mismo criterio que Informes, bonos activos + sesiones vivas, saldo de tarjetas en circulacion; zona horaria del negocio). El subtab "Central online" consolida los enlaces publicos (central/tienda/gift) + apariencia. Pagina publica `GET /central/{cliente_id}` (`commerce._CENTRAL_PAGE_TEMPLATE`, redisenada jul 2026 estilo Fresha/Calendly): wizard 4 pasos (Servicio tarjetas con precio -> Centro/Profesional como cards con avatar via `/centros` + `/profesionales` filtrado por servicio -> Fecha con **date strip de 14 dias** + huecos agrupados Manana/Tarde/Noche via `/disponibilidad` con `location_id`/`employee_id` -> Cliente) -> `POST /agendar` -> panel de exito `showDone` (check SVG animado + pago/gestion). Extras UI: **rail "Tu reserva"** sticky que se rellena en vivo (`renderRail`, version movil `#bookingSummary`), hero con gradiente de marca animado + monograma + trust chips, skeletons de carga, barra de progreso, auto-avance al elegir servicio. OJO CSS: el panel de exito se estiliza por `#bookingDone` (NO `.done` — colisiona con `.step.done`). **Modo embed**: `?embed=1` sirve sin hero/laterales y fondo transparente para iframe en la web del negocio (`central_public_page_html(embed=)`); boton "Codigo para tu web" (copia el iframe) en Ventas>Central online. QA visual con Playwright: `scratchpad shot_central.py` (mock de APIs + screenshots del flujo). **Personalizacion (jul 2026)**: columna `image_url` en `services`/`products`/`packages` (migracion idempotente; saneado `textnorm._public_image_url` = solo http/https, 500c, sin comillas/espacios/control) — se edita en los drawers del portal (campo "Imagen (URL)" + preview `.imgprev`/`refreshImagePreview`) y se pinta en la central publica (service cards con `.choice-media`; catalogo mixto = placeholder con inicial para alturas uniformes), en `/tienda` (`.card-media`) y en el mostrador (`.central-thumb`). Hero de la central configurable en `config['shop_public']`: `hero_image_url` (foto con overlay; sin foto = gradiente animado del acento) + `hero_tagline` (frase de bienvenida) via `GET/PUT /auth/app/shop-public` — UI en Ventas>Central online>Apariencia ("Guardar apariencia"). Al elegir hora el wizard auto-avanza al paso Cliente y la nav es sticky. Tests de roundtrip en `test_central_customization_hero_and_images`. **Canje sobre la cita**: dialogos compartidos `cdRedeemPkgDialog` (elige bono, deshabilita los que no cubren el `service_id`) y `cdRedeemGiftDialog` (codigo + saldo en vivo), usados por la vista Dia y el modal Gestionar; `cdLoadAssetsHint` avisa proactivamente en el detalle de cita sin pagar si el cliente tiene bono que cubre el servicio o tarjeta con saldo (cache `window.__cdAssets`, se invalida al canjear). Tests del summary y de la pagina publica en `tests/test_shop_public.py`.
- **Informes** (`/auth/analytics/overview` + `/auth/analytics/export.csv`, rol manager+): KPIs con delta vs periodo anterior (ingresos, citas, ticket medio, asistencia, ocupacion por horario real de empleados, clientes nuevos), serie diaria, desgloses por servicio/profesional/centro/canal, filtro por centro y rango (max 1 ano). Ingresos = citas pagadas (por booking_date) + productos + bonos vendidos + gift cards emitidas (por fecha de venta; la redencion no suma). UI: pestana Informes con graficos SVG vanilla (linea con area, barras, donut, rankings).
- **Roles del portal** (`users.portal_role`: owner > manager > staff; default owner; el admin Vantelia siempre owner): guard `security._require_portal_min_role(user, rol)`. manager = catalogo (servicios/empleados/centros/bonos/productos), informes, overrides; owner = canales de envio, pagos Stripe Connect, refunds de customer_payments y equipo de acceso. Staff = agenda, chats y mostrador (vender/redimir). Gestion self-serve del equipo: `/auth/app/team` CRUD (solo owner; salvaguarda: siempre debe quedar >=1 owner activo). `/auth/me` expone `portal_role`; app_ui oculta tabs segun rol (`applyRoleVisibility`). UI: bloque "Equipo de acceso" en Cuenta.
- **Permisos granulares por accion** (estilo Square/Fresha/Mindbody): los roles son PRESETS de permisos; el owner afina permiso a permiso por usuario (allow/deny) sobre ese preset. Catalogo fijo en `security.PORTAL_PERMISSIONS` (agenda.create/cancel/attendance, payments.capture/refund, commerce.sell, catalog.manage, clients.edit, reports.view/export + owner_only: channels.manage/billing.manage/team.manage). Defaults por rol en `PORTAL_ROLE_DEFAULT_PERMISSIONS` (owner=todo, no editable; los permisos owner_only no se delegan). Override por usuario en tabla `user_permission_overrides` (sin fila = hereda el rol). Resolutores en `security.py`: `_role_default_permissions`, `_user_permission_overrides`, `_effective_permissions`, `_user_has_permission`, `_require_portal_permission(user, key)` (este sustituye a los `_require_portal_min_role` de las acciones del catalogo), `_set_user_permission_override`. Endpoints (solo owner): `GET/PUT /auth/app/team/{id}/permissions`, `GET /auth/app/permissions/catalog`. `/auth/me` expone `permissions` (claves efectivas). app_ui: `hasPerm(key)` + `window.PORTAL_PERMS` gatean tabs (`TAB_PERMISSION`), botones estaticos (`data-perm`) y acciones dinamicas (cd-detail). UI: boton "Permisos" por usuario en "Equipo de acceso" -> drawer con matriz por modulo (Por defecto / Permitir / Denegar). El backend es la fuente de verdad; la UI solo oculta.
- **Botones de confirmacion WhatsApp**: los recordatorios 24h/2h por WhatsApp llevan botones "✅ Confirmo" / "❌ Cancelar cita" (`bkok_<id>` / `bkcancel_<id>`); el webhook (`_wa_handle_reminder_reply`) verifica que el telefono coincide con el de la cita, registra `attendance_confirmed_by_customer` en audit o cancela la cita. Fallback a texto plano si la API rechaza el interactivo.
- **Llamadas de confirmacion por IA (saliente)**: el asistente puede LLAMAR al cliente para confirmar la cita. Núcleo `voice._voice_place_outbound_call(cliente_id, booking_row, base_url=, purpose='confirm')` (Twilio Calls API, `From`=`voice.twilio_phone_number`, `Twiml` inline `<Connect><Stream url=wss://…/voice/stream/{c}?mode=confirm&booking_id=&to=>`); registra `voice_calls` (`direction='outbound'`, `purpose`, `booking_id`) → la llamada aparece en Conversaciones. El puente (`routers/voice_web.py`) lee `mode/booking_id/to` del query string (modo saliente): instrucciones `voice._voice_outbound_confirm_instructions`, saludo `_voice_outbound_greeting`, `from_number`=teléfono del cliente (verificado), y tool `confirmar_cita` (solo saliente, `include_confirm=True`) → `booking._mark_booking_confirmed_by_customer`. Gating: plan Business + número Twilio. Manual: `POST /auth/bookings/{id}/confirm-call` (perm `agenda.attendance`); reenviar confirmación por canales configurados: `POST /auth/bookings/{id}/send-confirmation`. **Fallback automático opt-in**: config `reminders` (`call_fallback`, `quiet_start`/`quiet_end`, `daily_call_cap`) vía `GET/PUT /auth/app/reminders` (manager+); en `_run_booking_reminders`, al enviar el recordatorio 24h, si `call_fallback` y la cita no está confirmada y `booking._reminder_calls_ok_now` (quiet hours hora local + cap diario + número) → coloca la llamada (import tardío de `voice` para evitar circular). UI: pestaña Recordatorios (`page-mensajes`) con tarjeta "Llamadas de confirmación por IA" + botones "📞 Llamar para confirmar" / "✉ Enviar confirmación" en el detalle de cita. Coste por llamada (Twilio+OpenAI); quiet hours + cap obligatorios.
- **Petición de reseña post-cita (opt-in, estilo Fresha/Booksy)**: tras completar la cita, el sistema invita al cliente final a dejar una reseña en el enlace que configure el negocio (Google/Trustpilot/Tripadvisor/Yelp/Facebook/…). Config en `config['reviews']` (`enabled`, `link`, `platform`, `delay_hours`, `only_manual_attendance`, `message`, `channels`). Motor en `backend/booking.py`: `_reviews_config`, `_reviews_overview_dict`, `_review_email_bodies` (email con estrellas + botón a la URL), `_send_review_request` (email vía `emailing._send_client_email`, WhatsApp/SMS texto plano con `{enlace}` inline; idempotente: sella `bookings.review_request_sent_at` + audit `review_request_sent`), `_bookings_due_for_review` (status `completed`, `end_at <= now - delay_hours` y dentro de los últimos 14 días para no spamear histórico al activar; opcional solo `completed_source='manual'`), `_run_review_requests` (corre en `_booking_reminder_worker` tras los recordatorios). Canales gateados por plan igual que el resto (email siempre; WhatsApp Pro; SMS Business). Endpoints: `GET/PUT /auth/app/reviews` (manager+, devuelve config + canales + vista previa), `POST /auth/bookings/{id}/review-request` (envío manual, perm `agenda.attendance`). UI: aparece como **paso final de la escalera de Seguimiento** (`_follow_up_overview_dict` añade un step `key="review"`, "Pide una reseña", con `enabled`/`needs_setup` y canales por plan; el nodo muestra estado y un botón que salta a la tarjeta) + tarjeta "Pide reseñas tras la cita" debajo (interruptor maestro, enlace con validación + ayuda Google, plataforma autodetectada, retardo, canales, mensaje con `{empresa}/{nombre}/{servicio}/{enlace}` y vista previa en vivo del email) + acción "⭐ Pedir reseña" en el detalle de cita completada. El paso `review` NO se guarda en `message_template_channels` (el front lo excluye; se persiste vía `/auth/app/reviews`). Default OFF.

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

Cobro de citas: además del botón "💳 Cobrar" del detalle de cita (genera enlace Stripe Checkout sobre la cuenta Connect del negocio, [api.py](api.py) `_create_customer_payment_link`; `POST /auth/app/bookings/{id}/payment-link` devuelve `checkout_url` **+ `qr_svg`** y el panel muestra un diálogo con QR escaneable + copiar/abrir, igual que el cobro POS), la **IA puede enviar el enlace de pago** al cliente final en nombre del negocio. Opt-in por negocio (`client_payment_accounts.ai_send_enabled`, default false; toggle en pestaña Pagos del portal; `POST /auth/app/payments/ai-send`). Canal según `bookings.source`: `voice`→SMS, resto→email. Reglas: solo al contacto ya registrado en la cita, importe desde la política de pago del servicio (nunca lo fija el cliente), requiere Stripe conectado + `charges_enabled`, dedup de pago `paid`, rate limit 2/cita/hora, auditoría `ai_payment_link_sent` en `booking_audit`. Helper común `_ai_send_payment_link`; voz vía tool Realtime `enviar_enlace_pago` (`_voice_send_payment_link`); chat web/WhatsApp vía `_process_payment_request_message` (intención "pagar"; identifica la cita por nº de reserva o, sin código, por el teléfono verificado de WhatsApp o el email/teléfono que escriba el cliente vía `_latest_booking_for_contact`). Detalle en `docs/CRM_Y_PAGOS_MVP.md`.

Canales de envio multi-tenant: pestaña `Canales de envio`, endpoints `/auth/app/channels*` y tablas `client_channel_settings`, `client_oauth_connections`, `client_channel_oauth_states`, `client_channel_audit`. `_send_client_email` selecciona Gmail OAuth o SMTP Vantelia; `_send_client_sms` selecciona el remitente Twilio provisionado o el global. Gmail usa exclusivamente `openid email gmail.send`, PKCE, state firmado/de un solo uso y tokens Fernet cifrados con `OAUTH_TOKEN_ENCRYPTION_KEY`. Nunca guardes ni registres tokens en claro. Un Sender ID/número dedicado no puede enviar hasta tener `sms_sender_status='active'`.

No enviar emails reales en pruebas. Usa entornos o credenciales dummy.

## WhatsApp

WhatsApp reutiliza la misma logica de chat/RAG y guardado de conversaciones. Puntos sensibles:

- Verificacion webhook con `WHATSAPP_VERIFY_TOKEN`.
- Validacion de firma con `WHATSAPP_APP_SECRET` obligatoria (rechaza 503 si vacio, 403 si firma invalida).
- Mapeo phone number id -> cliente con `WHATSAPP_PHONE_CLIENT_MAP` o config por cliente.
- Token global `WHATSAPP_ACCESS_TOKEN` o variable especifica por cliente.
- No responder si el cliente no esta habilitado o no se puede resolver con seguridad.
- **Unificacion jul 2026** (requisitos en `docs/REQUISITOS_ASISTENTE_WHATSAPP.md`): la intencion de reserva por texto libre arranca el flujo guiado desde el SELECTOR DE SERVICIO (antes saltaba al dia con servicio vacio); las confirmaciones de cambio dicen la fecha en humano (`_wa_fecha_humana`); el fallo de reprogramacion ofrece alternativas reales via `booking._reschedule_failure_text` (helper COMPARTIDO con el chat); el menu se presenta en nombre del negocio (Apariencia `empresa`, fallback `nombre`), igual que chat/voz. OJO: `rag.AVAILABILITY_INTENT_PATTERNS` ya NO usa "para" como marcador ("cita para un masaje" = reserva → formulario/flujo, no consulta de disponibilidad).

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

## Captacion WhatsApp

Cold outbound por WhatsApp Web automatizado con TU numero (Playwright), NO via WhatsApp Cloud API ni Graph. Reutiliza los telefonos de los prospects de Captacion email (`outreach.db` tabla `prospects.phone`, extraidos por Google Places en su dia) — **no hace discovery propio**. Single-touch: un unico mensaje por telefono, dedup permanente.

### Componentes

- `scripts/whatsapp_outreach.py`: capa de datos. DB `storage/whatsapp/whatsapp.db` (env `WA_DB_PATH`). Tabla `wa_messages` (PK `phone` normalizado E.164 sin '+'; dedup) + `wa_settings` (plantilla del mensaje). `normalize_phone` (default ES +34), `fetch_prospect_phones` (lee outreach.db, excluye ya-contactados/bajas/clientes), `enqueue`, `mark_sent/skipped`, `stats`, `recent`, `get/set_message_template`, `render_message` (placeholders `{business_name}/{city}/{niche}`).
- `scripts/whatsapp_autosend.py`: Playwright WhatsApp Web. Sesion = **user data dir persistente** (`launch_persistent_context`, env `WA_SESSION_DIR`), no cookies. `start_login_session` abre WA Web headless y captura el QR a PNG (`WA_QR_PATH`) hasta que el user lo escanea (dispositivo vinculado). `session_info` (ligero, lee marker), `verify_session` (lanza navegador real), `clear_session`, `_send_one` (navega a `web.whatsapp.com/send?phone=&text=`, detecta numero invalido, pulsa enviar/Enter), `autosend_messages` (cap `WA_AUTOSEND_DAILY_CAP`, delays humanos `WA_AUTOSEND_MIN/MAX_DELAY_SEC`).

### Endpoints admin (Bearer ADMIN_API_TOKEN o sesion admin)

- `GET  /admin/whatsapp/stats` — enviados hoy/total, en cola, disponibles, session, autosend_enabled.
- `GET  /admin/whatsapp/recent` — ultimos envios con estado.
- `GET/PUT /admin/whatsapp/message` — plantilla del mensaje.
- `POST /admin/whatsapp/send` `{count, dry_run}` — encola N telefonos nuevos (dedup) y lanza job background que envia via Playwright + marca sent/skipped. 412 si `WA_AUTOSEND_ENABLED=false` o WhatsApp no conectado (salvo dry_run).
- `GET  /admin/whatsapp/session` — estado sesion + login_running/status.
- `POST /admin/whatsapp/connect` — arranca login en hilo de fondo (genera QR).
- `GET  /admin/whatsapp/qr` — PNG del QR (404 si aun no listo).
- `POST /admin/whatsapp/disconnect`, `POST /admin/whatsapp/test`.

### UI

Tab "WhatsApp" en sidebar admin (`data-view="whatsapp"`, modulo JS `whatsappModule`, init `window.__waInit`). Sub-tabs: **Enviar** (stats + input num negocios + boton ENVIAR + actividad reciente), **Mensaje** (textarea editable + placeholders), **Configuracion** (conectar via QR escaneable, probar/desconectar sesion).

### Variables .env

`WA_AUTOSEND_ENABLED` (default false, gate del envio real), `WA_DB_PATH`, `WA_SESSION_DIR`, `WA_QR_PATH`, `WA_AUTOSEND_HEADLESS`, `WA_AUTOSEND_DAILY_CAP` (20), `WA_AUTOSEND_MIN/MAX_DELAY_SEC` (60/240).

### Compliance / riesgo

Automatizar WhatsApp Web viola ToS Meta y puede provocar bloqueo del numero. Usar numero secundario. Single-touch + delays + cap diario para minimizar. Requiere Playwright+Chromium (ya en Dockerfile).

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
- Gestion de citas por chat con MEMORIA conversacional (cancelar en 3 mensajes sin repetir datos), caso ambiguo "cancelar o cambiar", alternativas reales al reprogramar sobre hueco ocupado, y bloques HORARIO SEMANAL REAL + CATALOGO en el prompt del chat.

Si cambias contratos de respuesta, auth, cookies, booking o WhatsApp, actualiza o amplia estos tests.

**Subida de nivel (auditoria jul 2026):** (1) `chat._message_is_pure_greeting` — un saludo solo gana si es PURO; "Hola, quiero cancelar mi cita R-1234" procesa la intencion (chat y WhatsApp; antes el menu la secuestraba). (2) El bloque DATOS_EN_VIVO del chat (estado abierto/cerrado y horas de hoy) sale de `agenda._weekly_schedule_matrix`, no de config crudo (ya no puede contradecir al bloque HORARIO del mismo prompt); los pickers de WhatsApp usan la misma matriz (`_wa_closed_weekdays`). (3) WhatsApp multi-centro con numero generico pregunta el CENTRO como primer paso del flujo (`_wa_start_booking_flow` + paso `booking_location`; el centro acota servicios/profesionales/huecos/cita). (4) Las llamadas de voz del navegador etiquetan `outcome` (front acumula por tools; `/log` valida y persiste). (5) `voice_engine.new_call_state` quedo limpio de ~23 flags del scripting retirado; helpers muertos (`_voice_stall_needs_nudge`, `_voice_claims_closed_day`) y 6 exports sin uso de voice_core.js eliminados. (6) Indices nuevos: `bookings(cliente_id, booking_code)` y `bookings(manage_token)` (el enlace de gestion era un SCAN completo). DEUDA CONOCIDA: el harness QA de voz (CallHarness) aun emula el puente antiguo `_force_*`; migrarlo a `VoiceCallEngine` cuando haya cuota Realtime para validar.

**Asistente de chat (jul 2026, espejo del de voz — requisitos en `docs/REQUISITOS_ASISTENTE_CHAT.md`):** el prompt del chat (`rag._build_system_prompt`) lleva el **HORARIO SEMANAL REAL** (fuente unica `agenda._weekly_schedule_matrix`, derivada de los profesionales publicos con fallback a config['booking']; la MISMA que usa `voice._voice_schedule_block`) y el **CATALOGO REAL de servicios** (`booking._service_catalog_lines`, fuente unica compartida con `voice._voice_service_catalog`). La gestion de citas del chat (`booking._process_booking_management_message`) tiene **memoria conversacional** (`appstate.chat_manage_state`, TTL 15 min, por `session_id`): intencion/codigo/contacto/fecha/hora dichos en mensajes anteriores no se vuelven a pedir; "cancelar o cambiar" ambiguo pregunta cual; al reprogramar sobre hueco ocupado ofrece alternativas reales (`agenda._available_slots_for_day`). Menu con quick action "Cancelar o cambiar mi cita". QA con modelo real (gpt-4o-mini, centimos): `python scripts/qa_chat_realtime.py` (tenant aislado, 10 escenarios: menu, dia cerrado, disponibilidad, formulario, cancelacion con memoria, precio desde catalogo, servicio inexistente, horario, fuera de ambito, ingles; exit 0 siempre — leer `"ok"` raiz del JSON).

## Documentacion util

- `README.md`: instalacion, endpoints y operacion general.
- `docs/Funcionalidades.md`: resumen funcional.
- `docs/MANUAL_ADMIN.md`: operacion del panel.
- `docs/PLAN_ESCALA_AGENCIA_IA.md`: sistema operativo comercial de 90 dias.
- `docs/SEGUIMIENTO_PLAN_ESCALA.md`: rutina para registrar y revisar la ejecucion.
- `docs/REQUISITOS_ASISTENTE_VOZ.md`: contrato de producto del asistente de voz + QA Realtime obligatorio.
- `docs/REQUISITOS_ASISTENTE_CHAT.md`: contrato de producto del asistente de chat (widget) + QA.
- `docs/REQUISITOS_ASISTENTE_WHATSAPP.md`: contrato de producto del asistente de WhatsApp (flujos interactivos + cerebro compartido) + QA.
- `docs/REQUISITOS_HORARIO_CALENDARIO.md`: contrato de horarios/descansos/bloqueos y su visibilidad en calendario y asistentes. Regla clave (jul 2026): el descanso del horario GENERAL (parada de comida) cierra la agenda de TODO el equipo (`agenda._client_break_windows` en union dentro de `_build_slots_for_day`; conflicto de guardado contra las citas de todos; banda en todas las columnas de la vista Dia; linea "Cierre diario" en los prompts de chat y voz). Los descansos por profesional se SUMAN al general. `GET /auth/schedule/employee/{id}` lista tambien los bloqueos generales.
- `docs/MANUAL_GOOGLE_CALENDAR.md`: calendario.
- `docs/OPERACION_PRODUCCION.md`: checklist minima para vender/operar.
- `deploy/hostinger/DEPLOY.md`: guia VPS/Hostinger.
- `docs/legal/*.md`: textos legales servidos por `/legal/{documento}`.

## Seguimiento del plan de escala

Cuando el usuario pregunte por crecimiento, ventas, seguimiento del plan o
prioridades comerciales, contrastar `docs/PLAN_ESCALA_AGENCIA_IA.md` con las
tablas SQLite `growth_daily`, `growth_opportunities`, `growth_opportunity_audit`,
`growth_weekly_reviews` y `growth_plan_tasks` (o `GET /admin/growth/overview`).
No asumir actividad no registrada. La operacion diaria se hace desde la seccion
**Plan de escala** del panel admin; `scripts/scale_tracker.py` queda como respaldo.

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
