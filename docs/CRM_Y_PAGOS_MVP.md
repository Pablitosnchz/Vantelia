# CRM ligero y pagos de clientes finales

## 1. Auditoria de capacidades reutilizables

Vantelia ya dispone de agenda multiempresa, servicios, profesionales,
disponibilidad, leads, conversaciones, widget web, WhatsApp, voz, portal
cliente, recordatorios y Stripe para su propia facturacion SaaS.

La Fase 1 reutiliza esos registros como actividad y añade una identidad
consolidada. No sustituye ni elimina `bot_leads`, `bookings`, `chat_sessions`
o `voice_calls`.

## 2. Fase 1 implementada: CRM ligero

Tablas:

- `crm_contacts`: ficha unica por empresa.
- `crm_contact_links`: vinculos idempotentes con leads, citas, chats y llamadas.
- `crm_contact_audit`: historial de cambios y automatismos.

La deduplicacion usa primero email normalizado y despues telefono normalizado,
siempre dentro del mismo `cliente_id`. No fusiona automaticamente solo por
nombre.

Estados: `nuevo`, `interesado`, `cita_pendiente`, `confirmado`, `cliente` y
`perdido`.

Automatismos:

- Reservas, leads, WhatsApp y voz crean o actualizan contactos.
- Leads enlazan tambien su sesion de chat cuando existe.
- Una cita realizada convierte el contacto en `cliente`.
- Al abrir Contactos se enlazan de forma idempotente datos historicos.

API del portal:

- `GET /auth/app/contacts`
- `GET /auth/app/contacts/export.csv`
- `POST /auth/app/contacts`
- `GET /auth/app/contacts/{contact_id}`
- `PUT /auth/app/contacts/{contact_id}`

### Listado preparado para volumen

El listado usa paginacion real en servidor y no carga notas, actividad ni
auditoria hasta abrir una ficha. Los contadores de leads, citas, chats y
llamadas se calculan en una unica agregacion por pagina, evitando consultas
N+1.

Filtros disponibles:

- Busqueda normalizada por nombre, email y telefono.
- Estado, etiqueta, responsable y canal de origen.
- Proxima accion pendiente, vencida, futura o ausente.
- Rango de ultima actividad.
- Orden por actividad, creacion, nombre o proxima accion.

La interfaz aplica debounce, cancela peticiones obsoletas, mantiene los filtros
al abrir fichas y permite exportar CSV respetando esos mismos filtros.

## 3. Fase 2 implementada: Stripe Connect

La facturacion SaaS actual mantiene sus claves y tablas. Los pagos de clientes
finales se aislaran mediante Stripe Connect.

Tablas implementadas:

- `client_payment_accounts`: cuenta Connect y estado de onboarding por empresa.
- `service_payment_policies`: sin pago, pago completo o señal fija/porcentaje.
- `customer_payments`: pago asociado a contacto, servicio y cita.
- `customer_payment_events`: eventos Stripe unicos para idempotencia.

Estados de pago: `pending`, `paid`, `failed`, `refunded` y
`partially_refunded`.

Endpoints implementados:

- `POST /auth/app/payments/connect/start`
- `GET /auth/app/payments/connect/status`
- `PUT /auth/app/services/{service_id}/payment-policy`
- `POST /auth/app/bookings/{booking_id}/payment-link`
- `GET /auth/app/payments`
- `POST /auth/app/payments/{payment_id}/refund`
- `POST /stripe/connect/webhook`

El webhook resolvera la cuenta Connect, verificara la firma, guardara el evento
de forma idempotente y despues actualizara pago, cita y contacto. Vantelia no
almacenara datos de tarjeta.

Cada servicio permite configurar `none`, `full`, `deposit_fixed` o
`deposit_percent`. Los enlaces de Checkout se crean directamente en la cuenta
conectada de la empresa y nunca en la cuenta SaaS de Vantelia.

El portal incluye conexion OAuth Standard, politicas por servicio, historial,
creacion de enlaces y solicitud de reembolsos. Stripe notifica el resultado
mediante un webhook Connect separado e idempotente.

Variables necesarias:

- `STRIPE_CONNECT_CLIENT_ID` (opcional; activa OAuth para cuentas Standard existentes)
- `STRIPE_CONNECT_WEBHOOK_SECRET`
- `STRIPE_CONNECT_RETURN_URL`
- `STRIPE_CONNECT_REFRESH_URL`

En Stripe debe registrarse `STRIPE_CONNECT_RETURN_URL` como redirect OAuth y
`https://app.vantelia.es/stripe/connect/webhook` como endpoint Connect.

Si `STRIPE_CONNECT_CLIENT_ID` queda vacio, Vantelia usa Stripe Connect Onboarding
con Account Links. Este es el flujo recomendado para plataformas nuevas y no
requiere copiar un `ca_...` desde el Dashboard.

## 3 bis. Envio de enlaces de pago por la IA (web, WhatsApp y voz)

La IA puede enviar al cliente final el enlace de pago de su cita, en nombre del
negocio. Opt-in por negocio (`client_payment_accounts.ai_send_enabled`, default
false) + Stripe conectado con cobros activos.

Canal de envio segun el origen de la cita (`bookings.source`):

- `voice` -> SMS (Twilio) al telefono de la cita.
- resto (`vantelia_widget`, `whatsapp`, `web`, `portal_manual`...) -> email al
  email de la cita.

Reglas de seguridad:

- Solo se envia al contacto YA registrado en la cita, nunca a un destinatario
  que el cliente final dicte.
- El importe sale de la politica de pago del servicio (none/full/deposit). Si la
  politica es `none` o no hay precio, no se cobra: la IA lo dice y no inventa.
- Requiere Stripe conectado + `charges_enabled`.
- Dedup: si la cita ya tiene un pago `paid`, no reenvia (409).
- Rate limit: maximo 2 enlaces por cita en la ultima hora.
- Cada envio queda auditado en `booking_audit` como `ai_payment_link_sent`.

Implementacion:

- Core compartido `_create_customer_payment_link(cliente_id, booking, base_url,
  override_cents)` (reutilizado por el boton manual del portal y por la IA).
- `_ai_send_payment_link(cliente_id, booking)` async: valida reglas, genera el
  link y lo envia por el canal que toca. Nunca lanza.
- Voz: tool Realtime `enviar_enlace_pago` + `_voice_send_payment_link` (resuelve
  la cita por numero de reserva verificado contra el telefono de la llamada, o
  por la ultima cita del telefono).
- Chat web/WhatsApp: intencion de pago en `_process_chat_message`
  (`_process_payment_request_message`). Identifica la cita por numero de reserva
  o, sin codigo, por el telefono verificado del canal (WhatsApp) o el email/
  telefono que el cliente escriba (`_latest_booking_for_contact`). Envia por
  email y muestra el enlace en el hilo. Solo pide el codigo si no logra
  identificar al cliente.
- Endpoint portal: `POST /auth/app/payments/ai-send` `{enabled}` (toggle). El
  estado viaja en `GET /auth/app/payments/connect/status` (`ai_send_enabled`).
- UI: toggle en la pestana Pagos del portal.

## 4. Riesgos y decisiones pendientes

- Definir si Vantelia cobrara comision mediante application fees.
- Definir cancelaciones, devoluciones y no asistencia por empresa.
- Decidir si una cita bloquea hueco mientras el pago esta pendiente.
- Elegir Connect Standard o Express. Para el MVP se recomienda Standard.
- Migrar a PostgreSQL antes de escalar pagos y alta concurrencia.
- Resolver manualmente conflictos donde email y telefono pertenecen a fichas distintas.
- Verificar identidad antes de acciones sensibles del asistente.

## 5. Plan incremental

1. Fase 1: CRM ligero, automatismos, portal, auditoria y tests. Implementada.
2. Fase 2A: onboarding Stripe Connect y politicas de pago por servicio. Implementada.
3. Fase 2B: checkout, webhooks idempotentes y confirmacion de cita. Implementada.
4. Fase 2C: reembolsos y politicas de cancelacion. Reembolsos implementados; politicas avanzadas pendientes.
5. Fase 3: herramientas seguras para el asistente y escalado humano.
6. Migracion a PostgreSQL y workers externos antes de volumen elevado.
## 5. Canales de envio por negocio

Los correos de citas, recordatorios y enlaces de pago pasan por `_send_client_email`. Por defecto utiliza el SMTP de Vantelia; si el negocio conecta Gmail, utiliza Gmail API y el correo aparece enviado desde su cuenta. El cliente puede permitir o impedir el fallback a Vantelia.

La conexion Gmail es independiente del login con Google. Usa OAuth offline, PKCE, un estado firmado de un solo uso asociado al usuario/negocio y exclusivamente los scopes `openid`, `email` y `gmail.send`. Access y refresh tokens se almacenan cifrados con Fernet.

Los SMS pasan por `_send_client_sms`. Los modos soportados son `vantelia_default`, `twilio_alphanumeric_sender` y `twilio_dedicated_number`. Un remitente solicitado por el cliente queda `pending_registration`; solo soporte puede provisionarlo y activarlo. No se permite suplantar un numero escrito libremente.

Configuracion necesaria:

```env
GOOGLE_GMAIL_CLIENT_ID=
GOOGLE_GMAIL_CLIENT_SECRET=
GOOGLE_GMAIL_REDIRECT_URL=https://app.vantelia.es/auth/app/channels/email/google/callback
OAUTH_TOKEN_ENCRYPTION_KEY=
```

Pasos manuales de produccion:

1. Habilitar Gmail API, configurar la pantalla OAuth y verificar el scope `gmail.send`.
2. Registrar exactamente la redirect URI de produccion.
3. Mantener estable y protegida `OAUTH_TOKEN_ENCRYPTION_KEY`.
4. Registrar los Sender ID españoles con Twilio antes de marcarlos como `active`.
5. Para números dedicados, provisionar una subcuenta Twilio por negocio y guardar sus credenciales cifradas.
