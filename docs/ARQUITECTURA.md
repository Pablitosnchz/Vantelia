# Arquitectura del backend de Vantelia

Resultado del refactor `refactor/estable-v1` (junio 2026): el monolito
`api.py` (33.170 líneas) se dividió en un paquete `backend/` por dominios y
`backend/routers/` por secciones de endpoints, manteniendo idéntico el
comportamiento observable (misma tabla de rutas, mismos contratos, mismo
esquema SQLite, mismo snippet de widget).

> **¿Este documento o el otro?** Aquí está **cómo está organizado** el proyecto
> (capas, módulos, convenciones, dónde crear cosas nuevas). Si lo que quieres es
> **cambiar algo concreto** —un mensaje al cliente, el flujo de reserva, un
> cobro— abre antes [`MAPA_DEL_CODIGO.md`](MAPA_DEL_CODIGO.md), que va por
> flujos y avisa de las trampas conocidas.

## Capas (la dependencia solo apunta hacia abajo)

```text
api.py                      Shim de compatibilidad (~150 líneas). uvicorn api:app.
└─ backend/main.py          Crea la app FastAPI, middlewares, mounts, eventos
   │                        startup/shutdown e importa los routers EN ORDEN.
   ├─ backend/routers/      19 módulos de endpoints (decoran app directamente).
   ├─ Dominios de negocio   chat, whatsapp, booking, demo_agenda, voice,
   │                        onboarding, billing, portal, crm, growth,
   │                        outreach, instagram, tiktok, wa_capture
   ├─ Servicios             agenda, rag, security, emailing, messaging,
   │                        stripe_gateway, clients
   ├─ Infraestructura       db (esquema SQLite + conexión), appstate (estado
   │                        mutable + locks), timeutils, textnorm
   └─ backend/settings.py   Env vars, rutas, planes (lee .env al importar)
```

`api_models.py` (Pydantic) y `onboarding_utils.py` quedan en la raíz como
módulos transversales.

## Mapa de módulos

| Módulo | Contenido |
| --- | --- |
| `backend/settings.py` | Constantes de entorno, rutas, logger, planes self-serve, plantillas por defecto. Se relee al reimportar `api` (las fixtures de tests dependen de ello). |
| `backend/appstate.py` | Estado mutable compartido: `CONFIG_CLIENTES`, `sesiones`, `indices` RAG, `whatsapp_flows`, `rate_limit_buckets`, `state_lock`, threads/stops de workers. Módulo hoja (solo stdlib). Se llama `appstate` porque `state` colisiona con locals del flujo OAuth. |
| `backend/timeutils.py` | `_utc_now` (punto único de "ahora": los tests lo parchean para time-travel), conversiones ISO/UTC. |
| `backend/textnorm.py` | Normalización de textos/orígenes/URLs/horarios/fechas-ES, parsers de precio y duración, extractores de email/teléfono/fecha. |
| `backend/db.py` | `_init_database` (~65 tablas + migraciones; el mapa de qué guarda cada una está en su docstring), `_get_db_connection` (Row + timeout), helpers `db_*` de clientes/suscripciones. Las DBs de captación (outreach/IG/TikTok/WA) viven en sus dominios. |
| `backend/clients.py` | Config multi-tenant: carga/normaliza/serializa `config.json`, validación runtime, sync con la tabla `clientes`, persistencia, planes (`_plan_limits`). Cargar este módulo puebla `appstate.CONFIG_CLIENTES`. |
| `backend/security.py` | Usuarios, sesiones del portal, cookies, impersonación, tokens de reset, OAuth states, Fernet de canal, guards `Depends` (`_require_*`), rate limit. |
| `backend/emailing.py` | SMTP Vantelia + Gmail OAuth por cliente (`_send_client_email`), emails transaccionales, estados del canal Gmail. |
| `backend/messaging.py` | Primitivas Twilio SMS y WhatsApp Cloud API (`_send_whatsapp_*`), validación de firma Twilio. |
| `backend/stripe_gateway.py` | Único módulo que importa el SDK `stripe` (los tests lo parchean con fakes vía el proxy), precios por plan, Connect v2. |
| `backend/agenda.py` | Empleados, servicios (seed desde info.txt), horarios, bloqueos y el motor de disponibilidad por intervalos. |
| `backend/rag.py` | llama-index por cliente, info.txt IO, prompt de sistema, Q&A, sesiones/mensajes de chat, NLU de disponibilidad. |
| `backend/crm.py` | CRM ligero: contactos unificados, normalización, auditoría, leads. |
| `backend/booking.py` | Ciclo de vida de citas completo + pagos de cita (políticas, checkout Connect, webhooks, enlace de pago por IA) + worker de recordatorios. |
| `backend/demo_agenda.py` | Tenants demo con TTL, página demo, seed/purga de agenda de ejemplo. |
| `backend/chat.py` | `_process_chat_message`: orquestador del chat multi-canal. |
| `backend/whatsapp.py` | Webhook Cloud API y flujo conversacional de agendado. (`api.whatsapp_flows` sigue siendo el dict de estado de appstate.) |
| `backend/onboarding.py` | Provisioning self-serve de clientes. |
| `backend/billing.py` | Suscripciones: checkout, sync Stripe, planes públicos. |
| `backend/portal.py` | Payloads/serialización del panel admin y portal, stats, analytics. |
| `backend/outreach.py`, `instagram.py`, `tiktok.py`, `wa_capture.py` | Captación B2B (los try/except de imports de `scripts/` viven aquí; flags `*_AVAILABLE`). `wa_capture` se llama así porque `wa_outreach` es el alias histórico del módulo de scripts. |
| `backend/voice.py` | Voz sobre OpenAI Realtime, por teléfono (Twilio) y por navegador (WebRTC): instrucciones, tools de cita y su despacho, OTP, llamadas salientes, cierre y etiquetado. |
| `backend/growth.py` | Plan de escala (métricas growth_*). |
| `backend/commerce.py` | Productos, bonos y tarjetas regalo + las páginas públicas del negocio (`/central`, `/tienda`, `/gift`, wallets). Nada se materializa al crear el checkout: lo hacen los `_finalize_*_payment` desde el webhook. |
| `backend/paystate.py` | Estado de cobro de una cita. **Fuente única**: suma `booking_payments` (la reserva) y `customer_payments` con `kind='pos'` (el mostrador). Mirar solo uno hace que el saldo mienta. |
| `backend/analytics.py` | Informes del portal: KPIs con delta, series, desgloses y el resumen de mostrador. |
| `backend/keywords.py` | Respuestas deterministas por palabra clave, opt-in por tenant. Va ANTES que las Q&A y que la IA. |
| `backend/intents.py` | Qué quiere el cliente: clasifica el mensaje con el modelo (atajo local gratis primero) y reconoce cuál de las Q&A del negocio le están haciendo, aunque lo escriba con otras palabras. Opt-in `config['ai_intents']`. |
| `backend/playbooks.py` | Situaciones tipicas de un negocio como PLANTILLAS (no dar precio sin ver, pedir foto, derivar a valoracion, pasar a una persona...). El negocio las activa desde el portal y se convierten en filas de `business_rules`: se acabo el script por cliente. |
| `backend/catalog_pick.py` | Elegir el servicio que pide el cliente mirando el catálogo real: filtra por familia, técnica, largo, para quién y edad, y dice qué falta por preguntar. Determinista y testeable: el modelo no decide aquí. |
| `backend/agent.py` | Coger cita conversando (`booking.estilo = conversacional`): el modelo lleva el diálogo con TOOLS (`buscar_servicio`, `consultar_disponibilidad`, `crear_cita`) que le impiden inventarse un servicio, un hueco o una cita. Reusa el despachador de la voz. |
| `backend/rules.py` | Reglas del propio negocio (cuando quiera X, haz Y): tabla `business_rules`, gana la primera activa por prioridad. Decide QUÉ hacer con la intención que da `intents`. |
| `backend/inbox.py` | Intervención humana sobre una conversación de WhatsApp: mientras alguien la atiende, el asistente se calla (`bot_is_muted`) y se respeta la ventana de 24 h de Meta. |
| `backend/voice_engine.py` | `VoiceCallEngine`: el estado y TODA la lógica determinista de una llamada. El puente (`routers/voice_web.py`) solo mueve audio y delega. |
| `backend/wa_flows.py` | Reserva como formulario dentro de WhatsApp (WhatsApp Flows): endpoint cifrado, `flow_token` firmado. Apagado por defecto. |
| `backend/wa_onboarding.py` | Alta self-service del WhatsApp del negocio (Embedded Signup + Coexistence), con sus credenciales cifradas. |
| `backend/wa_demo.py` | Número de WhatsApp compartido para enseñar demos, con códigos de ruta por tenant. |
| `backend/channel_requests.py` | Solicitudes asistidas de aprovisionamiento de canales. |
| `backend/main.py` | App + middlewares + mounts + init de runtime + eventos. Importa los routers al final: **el orden de import = orden de registro de rutas**. |
| `backend/routers/*` | Endpoints por sección contigua del monolito original (decoran `app` directamente, sin APIRouter, para preservar el orden first-match de FastAPI). |

## Convención de acceso (importante al escribir código nuevo)

Entre módulos de backend, el acceso es **cualificado**: `from backend import
booking` y luego `booking._store_booking(...)` — nunca `from backend.booking
import _store_booking`. Así, parchear `api.simbolo` (lo que hacen los tests
vía el proxy) o `backend.modulo.simbolo` afecta a TODOS los llamadores.
Excepciones: clases, dataclasses y modelos Pydantic pueden importarse por
nombre.

Cuidado con locals que pisan nombres de módulo (`booking`, `chat`,
`settings`...): si una función necesita el módulo y tiene un local con ese
nombre, renombra el local (`booking_row`, `channel_settings`...).

## El shim api.py

`api.py` mantiene el contrato histórico del monolito:

- `uvicorn api:app` intacto (Dockerfile/CI/deploy sin cambios).
- Reimportar `api` con otro entorno purga `backend.*` y relee `.env`
  (las fixtures de tests hacen `sys.modules.pop("api")` + import).
- Proxy de namespace plano: `api.simbolo` lee EN VIVO del módulo home;
  `monkeypatch.setattr(api, ...)` parchea el módulo home; `dir(api)` lo
  expone todo (`scripts/qa_e2e.py` lo recorre).
- `tests/test_shim_compat.py` son las guardias de este contrato (escanea
  los nombres que tests y qa_e2e consumen y verifica el forwarding).

## Dónde añadir cosas

- **Endpoint nuevo**: en el router de su sección (`backend/routers/...`),
  decorando `app`. Si abre sección nueva, crear módulo router e importarlo
  al final de `backend/main.py` (el orden importa si hay rutas solapadas).
- **Lógica de dominio**: en su módulo de `backend/` con acceso cualificado.
- **Modelo de payload/respuesta**: en `api_models.py`.
- **Estado mutable compartido**: en `appstate.py`, siempre accedido como
  `appstate.X` y mutado bajo `appstate.state_lock`.
- **Tests nuevos**: usar `vantelia_env_factory`/`api_module`/`client` de
  `tests/conftest.py` (no duplicar el bloque de env).

## Verificación

```powershell
python -m pytest -q                  # suite completa (~10 min, 780+ tests)
python scripts/qa_e2e.py             # E2E aislado del portal (exit 0)
python -m py_compile api.py auto_onboarding.py onboarding_utils.py
npm run build                        # widget reproducible (lo exige CI)
```

Histórico del refactor y decisiones: `docs/AUDITORIA_REFACTOR.md` (sustituye
al antiguo `docs/API_REFACTOR_MAP.md`).
