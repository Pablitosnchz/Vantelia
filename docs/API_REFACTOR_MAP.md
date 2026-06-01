# API Refactor Map

`api.py` sigue siendo el punto de entrada de FastAPI (`uvicorn api:app`), pero la primera fase ya separa los modelos compartidos en `api_models.py`.

## Estado Actual

- `api_models.py`: modelos Pydantic usados por endpoints publicos, portal/app, billing, admin y booking.
- `api.py`: app FastAPI, configuracion, base de datos, helpers, workers, routers inline y dominios grandes todavia mezclados.
- Bloques externos ya claramente delimitados dentro de `api.py`: Outreach, Instagram y TikTok.

## Dominios Principales

- Config/runtime: carga de `.env`, rutas, `CONFIG_CLIENTES`, validacion y persistencia de `config.json`.
- Database/core: `_init_database`, helpers `db_*`, sincronizacion de clientes y suscripciones.
- Auth/portal: usuarios, sesiones, Google OAuth, reset de password, cookies y permisos.
- Plans/billing: planes, cuotas, Stripe checkout, portal de facturacion y webhooks.
- Onboarding/self-serve: wizard, provision de cliente, claim de demos y entrenamiento inicial.
- Booking/agenda: disponibilidad, empleados, horarios, bloqueos, emails, auditoria, reprogramacion y cancelacion.
- Chat/widget: config publica, sesiones de chat, prompt, disponibilidad conversacional y endpoint `/chat`.
- App UI API: `/auth/app/*` para overview, appearance, leads, Q&A, knowledge, tune, WhatsApp, livechat y billing.
- Portal/admin: gestion de clientes, usuarios, stats, bookings, chats e impersonacion.
- Public web/demo: demo pages, consultas, legal, favicon y healthcheck.
- WhatsApp: webhook, flujos conversacionales y booking por WhatsApp.
- Growth tools: Outreach, Instagram y TikTok con sus propios modelos, DBs, workers y endpoints.

## Fases Recomendadas

1. Modelos compartidos: hecho en `api_models.py`.
2. Config y planes: extraer constantes, normalizacion de clientes, limites de plan y helpers de subscription a modulos pequenos.
3. Auth y sesiones: mover helpers de usuario/sesion/cookies y endpoints de acceso a un router `auth`.
4. Booking: mover agenda, empleados, disponibilidad, emails y endpoints de gestion a un paquete `booking`.
5. Chat/widget: mover prompt, FAQ/Q&A, disponibilidad conversacional y endpoints publicos de widget.
6. App/portal/admin: separar routers por superficie (`app`, `portal`, `admin`) usando dependencias compartidas.
7. Growth tools: extraer Outreach, Instagram y TikTok como routers autocontenidos, uno por fase.

## Guardrails

- Mantener `api.py` como compatibilidad de entrada hasta el final.
- Extraer primero codigo mecanico sin cambiar firmas ni rutas.
- Ejecutar `python -m py_compile api.py api_models.py` tras cada fase.
- Ejecutar `pytest tests/test_api_smoke.py` antes de cerrar cada fase.
- No eliminar codigo muerto sin prueba por busqueda exacta y tests.
