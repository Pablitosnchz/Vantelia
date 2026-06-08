# Vantelia 2.0

Sistema SaaS de chatbox embebible multiempresa pensado para instalarlo en webs corporativas con una experiencia de venta, citas y operativa mucho mas profesional.

## Que incluye

- Backend FastAPI con RAG por cliente.
- Widget embebible por `script` con UI responsive.
- Modos comerciales de IA: diagnostico inteligente, recomendador, estimador y comparador de opciones.
- Guardado de conversaciones por cliente con endpoints admin y portal.
- Flujo de solicitud de cita con disponibilidad real y persistencia en SQLite.
- Correos transaccionales de cita, enlaces de gestion, cancelacion/reprogramacion y recordatorios.
- Control de origen por cliente, portal con login por sesiones y endpoints admin protegidos por token o sesion.
- Portal cliente con vistas de proximas/historicas y acciones de cancelacion o reprogramacion.
- CRM ligero con ficha unica, estados comerciales e historial consolidado.
- Cambio de contrasena dentro del portal y recuperacion por correo.
- Identidad visual compartida en admin, portal, demo y paginas de gestion de cita.
- `auto_onboarding.py` para generar y guardar `info.txt` dentro de `data/`.

## Instalacion

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
npm install
copy .env.example .env
```

Revisa despues:

- `config.json`: clientes, dominios autorizados, branding, color y booking.
- `data/<cliente>/info.txt`: base documental del RAG.
- `.env`: claves, webhook y limites operativos.

## Arranque

```powershell
npm run build
uvicorn api:app --host 0.0.0.0 --port 8000
```

Onboarding opcional:

```powershell
streamlit run auto_onboarding.py
```

## Snippet de instalacion

```html
<script
  src="https://tu-dominio.com/widget/widget.min.js"
  data-api="https://tu-dominio.com"
  data-client="Clinica_Saga"
  data-position="right"
></script>
```

## Endpoints principales

- `GET /health`
- `GET /legal/privacidad`
- `GET /legal/terminos`
- `GET /legal/cookies`
- `GET /legal/ia`
- `GET /acceso`
- `GET /portal`
- `GET /cliente/{cliente_id}`
- `POST /auth/login`
- `POST /auth/logout`
- `POST /auth/password/change`
- `POST /auth/password/forgot`
- `POST /auth/password/reset`
- `GET /auth/chats`
- `GET /auth/chats/{session_id}`
- `GET /auth/app/contacts`
- `GET /auth/app/contacts/export.csv`
- `POST /auth/app/contacts`
- `GET /auth/app/contacts/{contact_id}`
- `PUT /auth/app/contacts/{contact_id}`
- `GET /auth/app/payments/connect/status`
- `POST /auth/app/payments/connect/start`
- `GET /auth/app/payments`
- `POST /auth/app/bookings/{booking_id}/payment-link`
- `POST /auth/app/payments/{payment_id}/refund`
- `GET /auth/app/channels`
- `POST /auth/app/channels/email/google/connect`
- `GET /auth/app/channels/email/google/callback`
- `POST /auth/app/channels/email/google/disconnect`
- `POST /auth/app/channels/email/test`
- `POST /auth/app/channels/sms/settings`
- `POST /auth/app/channels/sms/test`
- `POST /chat`
- `GET /disponibilidad`
- `POST /agendar`
- `GET /booking/manage/{manage_token}`
- `POST /booking/manage/{manage_token}/cancel`
- `POST /booking/manage/{manage_token}/reschedule`
- `GET /servicios/{cliente_id}`
- `GET /whatsapp/webhook`
- `POST /whatsapp/webhook`
- `GET /whatsapp/webhook/{cliente_id}`
- `POST /whatsapp/webhook/{cliente_id}`
- `POST /stripe/connect/webhook`

## Endpoints admin

Requieren `Authorization: Bearer <ADMIN_API_TOKEN>` o sesion admin del portal.

- `GET /dashboard`
- `POST /admin/alta-express`
- `POST /admin/reindex/{cliente_id}`
- `GET /admin/stats`
- `GET /admin/clientes`
- `GET /admin/clientes/{cliente_id}`
- `PUT /admin/clientes/{cliente_id}`
- `GET /admin/bookings`
- `GET /admin/chats`
- `GET /admin/chats/{session_id}`
- `POST /admin/bookings/{booking_id}/cancel`
- `POST /admin/bookings/{booking_id}/reschedule`
- `POST /admin/bookings/{booking_id}/resend-email`
- `POST /admin/bookings/reminders/run`

## Panel admin rapido

1. Configura `ADMIN_API_TOKEN` y, para acceso profesional, `PORTAL_ADMIN_EMAIL` y `PORTAL_ADMIN_PASSWORD` en `.env`.
2. Arranca la API y abre `http://localhost:8000/acceso`.
3. Inicia sesion y desde ahi entra al dashboard o al portal cliente.
4. Usa `Alta express desde web corporativa` para scrapear la web del cliente.
5. Pulsa `Generar y guardar cliente en un clic` para crear cliente, guardar `info.txt`, reindexar y dejar el snippet listo.
6. Abre la demo compartible del cliente en `/demo/{cliente_id}` para validarla antes de instalar.

El alta express usa la `OPENAI_API_KEY` configurada en el backend para generar el cerebro del cliente.

Manual recomendado para operacion diaria:

- [Resumen de Funcionalidades](/e:/Vantelia/docs/Funcionalidades.md:1)
- [Manual de Administracion](/e:/Vantelia/docs/MANUAL_ADMIN.md:1)
- [Operacion minima antes de vender agresivamente](/e:/Vantelia/docs/OPERACION_PRODUCCION.md:1)

Comprobaciones minimas antes de desplegar:

```powershell
python -m pytest
npm run build
python -m py_compile api.py auto_onboarding.py onboarding_utils.py
```

Backup local:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\backup.ps1
```

## Notas de despliegue

- Usa HTTPS y define `allowed_origins` por cliente.
- Si quieres compartir sesion entre `vantelia.es` y `app.vantelia.es`, define `PORTAL_COOKIE_DOMAIN=.vantelia.es`.
- No subas `.env`, bases de datos ni stores locales al repo.
- Si alguna clave o webhook estuvo expuesto anteriormente, rotalo antes de produccion.
- Para escalar a varias instancias, el siguiente paso natural es mover reservas a Postgres y externalizar storage de indices.
- Booking real soportado por cliente:
  `internal` para flujo manual.
- Para correos y enlaces de gestion, configura tambien `APP_BASE_URL` y SMTP en `.env`.
- WhatsApp Cloud API reutiliza la misma IA, RAG y guardado de conversaciones que el widget. Activa el canal por cliente desde Admin > IA > WhatsApp y configura en Meta el webhook `https://app.vantelia.es/whatsapp/webhook` o `https://app.vantelia.es/whatsapp/webhook/{cliente_id}`.
- Para WhatsApp, define `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_ACCESS_TOKEN` y opcionalmente `WHATSAPP_APP_SECRET`. Si cada cliente usa un token distinto, guarda el nombre de la variable de entorno en el campo `Env token acceso`.
- Si vas a enviar desde `info@vantelia.es` y responder desde `soporte@vantelia.es`, deja listos `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`, `SMTP_REPLY_TO` y `PORTAL_SUPPORT_EMAIL`.

### Canales de envio por negocio

Por defecto los emails y SMS usan la infraestructura de Vantelia. En **Canales de envio**, cada negocio puede conectar Gmail mediante OAuth para enviar realmente desde su cuenta, o solicitar un Sender ID SMS comercial. Nunca se piden contrasenas de Gmail ni tokens Twilio al cliente final.

Para Gmail crea una aplicacion OAuth web en Google Cloud, habilita Gmail API, configura la pantalla de consentimiento y registra exactamente `GOOGLE_GMAIL_REDIRECT_URL`. Solicita solo `openid`, `email` y `https://www.googleapis.com/auth/gmail.send`. Antes de produccion, completa la verificacion de Google para el scope sensible.

Configura `GOOGLE_GMAIL_CLIENT_ID`, `GOOGLE_GMAIL_CLIENT_SECRET`, `GOOGLE_GMAIL_REDIRECT_URL` y una clave Fernet estable en `OAUTH_TOKEN_ENCRYPTION_KEY`. Si esa clave cambia, las conexiones guardadas dejan de poder descifrarse.

Los Sender ID alfanumericos se guardan inicialmente como `pending_registration` y no pueden enviar hasta que soporte los registre y active con Twilio. Para Espana, completa el registro regulatorio del Sender ID antes de usarlo. La tabla `client_channel_settings` deja preparados SID/token cifrados para provisionar una subcuenta Twilio aislada por negocio.
- Si quieres recordatorios automaticos, ajusta `REMINDER_RUN_INTERVAL_MINUTES`, `REMINDER_24H_HOURS` y `REMINDER_2H_HOURS`.
- Para cerrar citas ya pasadas sin borrarlas, ajusta `BOOKING_AUTO_COMPLETE_HOURS`.
- Para el enlace de recuperacion de contrasena, ajusta `PASSWORD_RESET_TOKEN_HOURS`.

## Hostinger y `vantelia.es`

La ruta recomendada para este stack es:

- `vantelia.es`: tu web comercial actual
- `app.vantelia.es`: API, panel admin y widget

Hostinger indica que Python necesita acceso root y que en hosting Web y Cloud la alternativa es un VPS, asi que para este proyecto lo apropiado es Hostinger VPS.

He dejado una guia lista en [deploy/hostinger/DEPLOY.md](/e:/Vantelia/deploy/hostinger/DEPLOY.md:1) y un compose en [deploy/hostinger/docker-compose.yml](/e:/Vantelia/deploy/hostinger/docker-compose.yml:1).
