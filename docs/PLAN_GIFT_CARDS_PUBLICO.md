# Plan: compra pública de tarjetas regalo (inspirado en SimpleSpa, mejorado)

> Objetivo: que el cliente FINAL de un negocio (caso de arranque: The Nook Madrid) pueda
> comprar una tarjeta regalo online y que llegue por email al destinatario — como
> `thenook.simplespa.com/buygiftcards.php`, pero mejor y multi-tenant. Sin romper nada:
> la emisión de mostrador y la redención actuales quedan intactas.

**Estado:** F1+F2 IMPLEMENTADAS (2026-07-04); F3 pendiente · **Fecha:** 2026-07-04

---

## 1. Qué hace SimpleSpa hoy (analizado)

- Importe libre en un campo "Amount" (sin sugeridos).
- Datos: nombre/email del remitente, nombre/email del destinatario, mensaje (300 chars).
- Entrega: email inmediato tras la compra.
- Personalización: color de acento de la tarjeta; ocultar valor y caducidad.
- Certificados por servicio/tratamiento (soportado pero sin configurar: "No gift
  certificates are available at this time").
- Pago: carrito + checkout pidiendo dirección postal completa (mucha fricción).

## 2. Nuestras mejoras

| SimpleSpa | Vantelia |
| --- | --- |
| Solo importe libre | Importes sugeridos configurables (chips) + libre con min/max |
| Certificados por servicio sin usar | Tarjeta "por servicio" desde el catálogo REAL (`services`, precio/duración actuales) |
| Email inmediato solamente | Inmediato o **programado** (p. ej. el día del cumpleaños) |
| Carrito + dirección postal | Stripe Checkout directo (email y tarjeta, 0 fricción) |
| Inglés, marca SimpleSpa | Español, branding del tenant (color/nombre/logo), multi-tenant genérico |
| Sin consulta posterior | Reenvío del email + consulta de saldo por código (fase 3) |

## 3. Lo que YA tenemos (se reutiliza, no se duplica)

- **Tarjetas**: `gift_cards` (código `GC-XXXX-XXXX`, balance, estados, caducidad lazy) +
  ledger `gift_card_transactions` + emisión (`commerce._issue_gift_card`) + **redención en
  recepción y sobre citas** (`_redeem_gift_card_for_booking`) + UI del portal (Ventas →
  Tarjetas regalo, visual de gradiente + barra de saldo).
- **Rail de cobro público**: patrón POS/booking — `customer_payments` con `kind` +
  Stripe Checkout sobre la cuenta **Connect del negocio** y materialización idempotente en
  el webhook (`/stripe/connect/webhook` → `_finalize_pos_payment`). El de tarjetas será
  un `kind='gift_card'` con su `_finalize_gift_card_payment` gemelo.
- **Emails con branding** del tenant: `emailing._send_client_email` (Gmail OAuth o SMTP).
- **Página pública server-rendered** con branding: patrón `GET /booking/manage/{token}`.
- **Worker** periódico (`_booking_reminder_worker`) para los envíos programados.

## 4. Diseño (fase 1 — núcleo)

### Config por tenant (opt-in, default OFF)
`config['gift_cards_public']`: `enabled`, `suggested_amounts` (p. ej. [30,50,100]),
`min_cents`/`max_cents`, `validity_days` (default el actual de emisión), `intro_text`.
Toggle + campos en portal Ventas → Tarjetas regalo (perm `catalog.manage`).
Gating de venta: Stripe Connect conectado + `charges_enabled` (igual que POS).

### Página pública
- `GET /gift/{cliente_id}` — HTML con branding del tenant: chips de importes sugeridos +
  importe libre validado, por-servicio (fase 2), campos: tu nombre, tu email, nombre del
  destinatario, email del destinatario, mensaje (300), fecha de envío (hoy | programada).
  Rate limit por IP. 404 si el tenant no tiene la función activa.
- `POST /gift/{cliente_id}/checkout` — valida (importe dentro de min/max, emails,
  mensaje saneado), crea `customer_payments` con `kind='gift_card'` y `metadata_json`
  (comprador, destinatario, mensaje, `send_at`), devuelve URL de Stripe Checkout
  (line item "Tarjeta regalo {negocio}"). Success/cancel → páginas públicas del patrón
  existente con branding.

### Materialización (webhook Connect, idempotente)
Rama `kind='gift_card'` → `_finalize_gift_card_payment`:
1. `_issue_gift_card` con el importe pagado (+ metadata en columnas nuevas NULLABLE de
   `gift_cards`: `buyer_name/buyer_email/recipient_name/recipient_email/message/scheduled_send_at`
   — migración idempotente estilo `PRAGMA table_info` como las demás).
2. Si `send_at` vacío → email al destinatario YA (plantilla: gradiente + código grande +
   mensaje del comprador + "canjéala al reservar online, por teléfono o en recepción" +
   caducidad) + confirmación/recibo al comprador. Best-effort: la tarjeta queda emitida
   aunque el email falle (reenvío desde el portal ya existe como detalle de tarjeta).
3. Si `send_at` futuro → queda pendiente; el worker la envía ese día (sella
   `sent_at` para no duplicar, mismo patrón que review_request).
4. Auditoría: transacción `issue` ya existente + `customer_payment_events`.

### Descubrimiento
- Quick action en el menú del chat: "🎁 Tarjeta regalo" → abre `/gift/{cliente_id}`
  (solo si `gift_cards_public.enabled`). Widget ya renderiza quick_actions del backend.
- Bloque en el prompt (chat/voz): si está activo, el asistente sabe decir el enlace/que
  existe la opción — mismo criterio que el catálogo.

## 5. Fase 2 (personalización — paridad+ con SimpleSpa)

- Color de acento seleccionable (se guarda en la tarjeta y tiñe el email/página).
- Ocultar valor y/o caducidad en el email al destinatario (flags por compra).
- Tarjeta "por servicio": el comprador elige un servicio del catálogo (precio actual →
  importe de la tarjeta; el email nombra el servicio). Sin tocar la redención: sigue
  siendo saldo.
- Versión imprimible (CSS print de la página del destinatario con el código).

## 6. Fase 3 (post-venta)

- Página pública de saldo por código (rate-limited, sin datos personales).
- Canje online en el flujo de reserva del widget (aplicar código al pagar).
- Venta cruzada: voz/WhatsApp envían el enlace por SMS/WA (patrón `enviar_enlace_pago`).

## 7. Sin romper nada (contrato)

- La emisión de mostrador (`POST /auth/gift-cards`) y la redención NO cambian.
- Columnas nuevas en `gift_cards` NULLABLE con migración idempotente; ninguna columna
  existente cambia de semántica.
- Webhook Connect: rama nueva por `kind`; `pos` y booking intactos (tests actuales lo
  garantizan).
- Feature OFF por defecto; ningún tenant la ve hasta activarla.
- Tests nuevos mínimos F1: gating (404 sin opt-in / sin Stripe), checkout crea el
  payment con metadata, webhook emite tarjeta UNA vez (idempotencia), email best-effort,
  envío programado lo recoge el worker, min/max de importe.
- QA: `python -m pytest` completo + `scripts/qa_e2e.py`; para The Nook, compra real de
  1 € en su Stripe en modo test antes de anunciarla.

## 8. Requisito previo para The Nook

Conectar su **Stripe Connect** (pestaña Pagos del portal) — ya identificado como
pendiente del go-live. Sin `charges_enabled` la página mostrará "no disponible".

## 9. Estimación

- F1: 1 jornada (página + checkout + webhook + email + tests).
- F2: media jornada.
- F3: media jornada.
