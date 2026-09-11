# Plan: recordatorios de cita por WhatsApp (plantillas de Meta)

**Estado (11-sep-2026, noche):** pasos 1-3 HECHOS (rama
`claude/recordatorios-whatsapp`): botón de plantilla en el webhook, plantilla con
envío fuera de ventana y email de respaldo, y alta + consulta de la aprobación
desde el worker de recordatorios (`wa_plantillas.refrescar_pendientes`; no hace
falta suscribirse a `message_template_status_update`). Además, las citas de demo
ya no entran en el reparto de recordatorios ni de llamadas. **Pendiente:** paso 4
(estado de la plantilla en el portal) y paso 5 (prueba real). Para las plantillas
fuera de ventana, el negocio necesita un **método de pago en Meta** (WhatsApp
Manager → pagos): sin él, Meta rechaza el envío y el aviso sigue por email.

Escrito para ejecutarlo tal cual (Claude o Astra): qué existe, qué falta, en qué
orden y cómo se prueba.

## Por qué hace falta

- Por WhatsApp solo se puede escribir **texto libre dentro de las 24 h** siguientes
  al último mensaje de la clienta (`inbox.window_open`). Un recordatorio 24 h antes
  de la cita cae casi siempre fuera de esa ventana: hace falta una **plantilla
  aprobada por Meta**. Hoy no soportamos plantillas.
- Por eso los avisos de Alicia van por email: el 11-sep se le quitó WhatsApp de
  `message_template_channels` (los dos bloques) y de `reminders.delivery_priority`,
  porque el +31 que la atiende no es su número.
- Con Coexistence cada negocio conecta SU número y SU cuenta de WhatsApp Business
  (WABA). **Las plantillas viven en la WABA de cada negocio**: hay que crearlas en
  cada una, con su token.

## Lo que ya existe (no rehacer)

- **Envío de avisos por WhatsApp**: `backend/booking.py`, función de avisos por
  WhatsApp (~líneas 930-992): confirmación con botón «Gestionar cita», recordatorio
  24 h / 2 h con botones `bkok_<id>` / `bkcancel_<id>`, y texto plano si Meta
  rechaza lo interactivo.
- **Respuesta a esos botones**: `whatsapp._wa_handle_reminder_reply` (comprueba el
  teléfono de la cita, confirma asistencia o cancela). Entra por `interactive_id`
  `bkok_…` / `bkcancel_…` en `_handle_whatsapp_message`.
- **Worker**: `booking._run_booking_reminders` → `_bookings_due_for_reminders` →
  `_send_booking_reminder_by_kind`; el canal sale de `reminders.delivery_priority` y
  de `message_template_channels`. Idempotente por `reminder_24h_sent_at` /
  `reminder_2h_sent_at`.
- **Ventana de 24 h**: `inbox.window_open(session_id)`, `inbox.last_inbound_at`.
- **Token y cuenta del negocio**: `messaging._whatsapp_access_token_for_client` (el
  de la WABA conectada por Embedded Signup manda sobre el global) y
  `client_whatsapp_accounts.waba_id`.
- **Envío genérico**: `messaging._send_whatsapp_payload`.

## Diseño

1. **Plantilla** `vantelia_recordatorio_cita`, idioma `es`, categoría **UTILITY**:
   cuerpo con variables (nombre, servicio, día en humano, hora, negocio) y dos
   botones QUICK_REPLY: «Confirmo» y «Cancelar cita». Texto neutro y
   transaccional: UTILITY se rechaza si suena a promoción. Sin enlaces acortados.
   (Fase 2, si hace falta: confirmación y cambio de cita fuera de ventana, por
   ejemplo una cita apuntada desde el panel.)
2. **Alta de plantillas por negocio**, módulo nuevo `backend/wa_plantillas.py`:
   - `asegurar(cliente_id)`: `GET /{waba_id}/message_templates?name=…`; si no
     existe, `POST` con los componentes. Guarda el estado en una tabla nueva
     `wa_templates` (cliente_id, name, language, status, meta_id, motivo_rechazo,
     updated_at).
   - Se llama al completar el alta (`routers/portal_app._completar_alta_whatsapp`),
     desde un botón del portal y, perezosamente, desde el worker si falta.
   - Aprobación: campo de webhook `message_template_status_update` (suscribir la
     app), que actualiza la tabla. De respaldo, consulta periódica en el worker.
3. **Envío** (en la función de avisos de `booking.py`):
   - Ventana abierta (`inbox.window_open`) → como hoy: botones interactivos, gratis.
   - Ventana cerrada y plantilla APPROVED → `_send_whatsapp_payload` con
     `type: "template"`, los parámetros del cuerpo y el `payload` de cada botón
     = `bkok_<id>` / `bkcancel_<id>`.
   - Sin plantilla aprobada → no se manda por WhatsApp y sigue el siguiente canal
     de `delivery_priority` (email). Nunca en silencio: audit
     `reminder_whatsapp_skipped` con el motivo.
4. **Respuesta al botón de una plantilla**: llega como mensaje de **`type:
   "button"`** con `button.payload` y `button.text`, **no** como `interactive`. Hoy
   ese tipo cae en `_wa_mensaje_ilegible` («no me ha llegado bien tu mensaje»). Hay
   que añadir la rama en `_handle_whatsapp_webhook`: `interactive_id =
   button.payload`, `incoming_text = button.text`, y que siga al manejador de
   siempre.
5. **Coste**: Meta cobra por mensaje de plantilla entregado; UTILITY dentro de la
   ventana es gratis y fuera cuesta céntimos. Paga la WABA del negocio (su tarjeta
   en Meta): hay que decírselo al cliente y ponerlo en la guía del alta. Tope
   opcional por negocio (`reminders.whatsapp_cap_dia`).
6. **Configuración por negocio**: no cambia de forma; deciden
   `message_template_channels.*.whatsapp` y `reminders.delivery_priority`. Cuando
   Alicia conecte SU número, volver a poner WhatsApp en sus canales.
7. **Portal**: en Recordatorios, estado de la plantilla (pendiente, aprobada,
   rechazada con motivo) y aviso de que los mensajes los paga el negocio.

## Cómo se prueba (antes de dar nada por bueno)

- **Unitarios**:
  - El payload de la plantilla, con sus parámetros y el payload de los botones.
  - La elección entre ventana abierta, plantilla o email.
  - La rama `type: "button"` del webhook, que hoy falla porque cae en lo ilegible.
  - `asegurar` con la Graph API simulada: plantilla que existe, que no existe y rechazada.
- **Reglas que no pueden romperse**:
  - El recordatorio no sale dos veces.
  - No sale por WhatsApp sin plantilla aprobada.
  - Si no puede salir por WhatsApp, acaba saliendo por email.
- **Prueba real**:
  - Primero con el número de demo (+1 803…, WABA de Vantelia): crear la plantilla, esperar la aprobación, mandar un recordatorio al móvil de Pablo y pulsar los dos botones.
  - Después, Alicia con su número.
- **Tests a vigilar**: `tests/test_recordatorio_cita_cancelada.py`,
  `tests/test_mensaje_ilegible_de_whatsapp.py`, `tests/test_inbox_takeover.py`.

## Trampas conocidas

- Plantilla en revisión o rechazada: el aviso no puede perderse (email).
- La plantilla es por WABA: la de demo y la de cada cliente son objetos distintos.
- En Coexistence el negocio tiene que abrir la app cada 14 días o Meta lo
  desconecta: el worker debe reconocer ese error, avisar al negocio por email y no
  reintentar en bucle.
- Solo `es` al principio.
- Todo por la Graph API oficial: nada de automatizar productos de Meta por
  navegador (regla de `CLAUDE.md`).

## Orden de trabajo

1. Rama `type: "button"` en el webhook, con su test. Es pequeña y segura, y se
   puede desplegar sola.
2. `wa_plantillas.asegurar` + tabla + suscripción al estado de las plantillas.
3. Envío con plantilla fuera de ventana, email de respaldo y audit.
4. Portal: estado de la plantilla.
5. Prueba real con el número de demo; después, Alicia con su número.
