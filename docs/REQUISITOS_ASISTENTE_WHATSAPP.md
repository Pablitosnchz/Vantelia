# Requisitos del Asistente de WhatsApp — Vantelia

> Documento de requisitos funcional y técnico del asistente de WhatsApp multi-tenant.
> Tercero de la familia (`REQUISITOS_ASISTENTE_VOZ.md`, `REQUISITOS_ASISTENTE_CHAT.md`):
> describe **lo que el asistente debe hacer por WhatsApp**, marca **qué está implementado**
> y **qué debe incorporar**. Contrato de producto y guía.

**Estado del documento:** vivo · **Última revisión:** 2026-07-03
**Ámbito:** WhatsApp Cloud API (webhook, mensajes interactivos, plantillas de
recordatorio) sobre el mismo cerebro que el chat web.

**Leyenda de estado:**

- ✅ **Hecho** — implementado y en producción.
- 🟡 **Parcial** — existe pero incompleto o mejorable.
- 🔵 **Propuesto** — no existe aún; recomendación de este documento.

---

## 1. Visión

WhatsApp es **el canal más personal**: el cliente final escribe desde SU número, lo que
da dos superpoderes que ni el widget ni la voz tienen igual de baratos:

1. **Identidad implícita**: el número del remitente ya verifica al titular
   (`trusted_phone`) — cancelar/reprogramar su propia cita no requiere pedir teléfono.
2. **Interfaz nativa interactiva**: listas y botones de WhatsApp (selector de servicio,
   profesional, día, hora; botones Confirmar/Cancelar) — la reserva es un flujo guiado de
   toques, el equivalente al formulario del widget.

El resto es el MISMO recepcionista: mismo cerebro RAG, mismo catálogo, mismo horario,
misma agenda real, mismas políticas. Un negocio configura una vez y atiende igual en web,
teléfono y WhatsApp.

---

## 2. Arquitectura (resumen)

| Pieza | Código | Notas |
| --- | --- | --- |
| Webhook | `GET/POST /whatsapp/webhook[/{cliente_id}]` → `backend/whatsapp.py` | Verify token + firma `WHATSAPP_APP_SECRET` obligatoria (503 si vacía, 403 si inválida). |
| Resolución de tenant | `_resolve_whatsapp_client_id` | `phone_number_id` → cliente vía `WHATSAPP_PHONE_CLIENT_MAP` o config; sin resolución segura, no se responde. |
| Multi-centro | `_wa_location_id` | El número entrante atado a un centro (`locations.whatsapp_phone_number_id`) acota profesionales/disponibilidad/reserva. |
| Flujos interactivos | `WAFlowState` (`appstate.whatsapp_flows`) | Estado por (tenant, remitente): reserva paso a paso y gestión de cita. |
| Cerebro compartido | `chat._process_chat_message` | Texto libre → mismo orquestador que el widget (RAG + disponibilidad + pago + gestión), con `trusted_phone` y sesión `wa:<número>`. |
| Registro | `chat_sessions` con `origin='whatsapp:<número>'` | Visible en Conversaciones con filtro por canal. |

**Filosofía (igual que voz y chat):** fiabilidad en las herramientas deterministas
(agenda real, verificación, dedup); el LLM cubre información y venta. Los flujos
interactivos de WhatsApp son la capa nativa sobre las MISMAS funciones de negocio
(`booking._cancel_booking_by_code`, `_reschedule_booking_by_code`, creación real de cita).

---

## 3. Requisitos funcionales

### 3.1 Comportamiento y conversación

- ✅ **Menú principal interactivo** (lista nativa) al saludar o escribir "menu": agendar,
  ver disponibilidad, cancelar cita, cambiar cita, FAQs, servicios, recomendar, comparar,
  estimar. Las opciones de agenda solo si la reserva está activa.
- ✅ Se presenta en nombre del **negocio** (Apariencia → "Nombre del negocio", con
  fallback al nombre del bot) — misma identidad que chat y voz.
- ✅ "menu" **siempre rompe el flujo activo** y vuelve al menú (escape universal).
- ✅ Texto libre → **mismo cerebro que el chat web**: RAG con catálogo real + horario
  semanal real en el prompt, Q&A del panel, modos comerciales, derivación a humano.
- ✅ Formato nativo: negritas `*…*`, emojis moderados, mensajes cortos.
- ✅ **Dedup de mensajes** del webhook (id de mensaje) y respuesta solo a tenants
  habilitados con firma válida.

### 3.2 Conocimiento del negocio

- ✅ Igual que el chat (mismo prompt): **catálogo real de servicios** (nombre, duración,
  precio de la tabla `services`), **horario semanal real** (derivado de los profesionales
  públicos; días cerrados incluidos), multi-centro, datos en vivo (abierto/cerrado ahora),
  base documental RAG y Q&A del panel.
- ✅ Cambios en el portal (horarios, servicios, identidad) aplican en la siguiente
  conversación sin tocar código.

### 3.3 Agenda: reservar (flujo interactivo nativo)

- ✅ **Flujo guiado con listas y botones**: servicio → profesional (si hay varios) → día
  (solo días con hueco real) → hora (solo huecos reales) → nombre → email → notas
  (opcional) → resumen con botones **Confirmar/Cancelar**.
- ✅ La intención de reserva detectada por la IA en texto libre ("me gustaría pedir cita
  para un masaje") arranca **el mismo flujo guiado desde el servicio** — nunca salta al
  día con servicio vacío.
- ✅ El teléfono del cliente **no se pide**: es el remitente (verificado).
- ✅ La cita creada es **real e idéntica a cualquier canal**: `source='whatsapp'`,
  snapshot de precio, número de reserva `R-XXXXXX`, email de confirmación con enlace de
  gestión, y hereda todo el Seguimiento (recordatorios, llamada IA, reseña).
- ✅ Día/hora sin hueco → el picker reofrece fechas/horas disponibles reales.
- ✅ Selector de **centro** en el flujo cuando el número no está atado a un centro y el
  negocio tiene varios: primer paso del flujo guiado (lista de sedes con dirección); el
  centro elegido acota servicios (overlay por centro), profesionales, huecos y la cita
  creada (`WAFlowState.location_id` + `_wa_start_booking_flow`). El número atado a centro
  sigue teniendo prioridad (no se pregunta).

### 3.4 Agenda: disponibilidad

- ✅ Opción de menú "Ver disponibilidad" → resumen de próximos días con huecos reales.
- ✅ Texto libre ("¿tenéis hueco el lunes por la tarde?") → **misma respuesta determinista
  que el chat** (fechas, franjas, vacaciones, siguiente día con hueco, filtro por
  servicio). Sin fecha, asume hoy y lo dice explícitamente.

### 3.5 Agenda: gestionar cita (cancelar / reprogramar)

- ✅ **Flujo por pasos con estado** (`WAFlowState`): pide código si falta, verifica y
  ejecuta. El remitente verificado hace de credencial: si la cita es suya, **no se le
  pide teléfono ni email**; si no coincide, se pide el contacto de la reserva.
- ✅ Cancelación aplica la **política de cancelación/no-show** del negocio (mismo núcleo
  `_cancel_booking_by_code` que web/voz) y queda auditada.
- ✅ Reprogramación valida el hueco real; si la hora está ocupada/cerrada **ofrece
  alternativas reales del día** (texto compartido `booking._reschedule_failure_text`,
  igual que el chat), y confirma con la **fecha en humano** ("lunes 6 de julio"), nunca
  ISO crudo.
- ✅ Escape con "menu" en cualquier paso.

### 3.6 Recordatorios y confirmación

- ✅ Recordatorios 24 h/2 h por WhatsApp con botones **"✅ Confirmo" / "❌ Cancelar
  cita"** (`bkok_<id>` / `bkcancel_<id>`): el webhook verifica que el remitente coincide
  con el teléfono de la cita, marca `attendance_confirmed_by_customer` o cancela.
  Fallback a texto plano si la API rechaza el interactivo.
- ✅ Canal WhatsApp gateado por plan (Pro+) según la configuración de Seguimiento.

### 3.7 Cobro

- ✅ "Quiero pagar mi cita" → mismo flujo de enlace de pago que chat/voz
  (`_process_payment_request_message` vía cerebro compartido): identifica la cita por
  código o por el **número verificado del remitente**, importe según política del
  servicio, opt-in del negocio, auditoría.

### 3.8 Registro y trazabilidad

- ✅ Conversaciones en `chat_sessions`/`chat_messages` con `origin='whatsapp:<número>'`,
  visibles en el portal (pestaña Conversaciones, filtro canal WhatsApp).
- ✅ Acciones de cita auditadas en `booking_audit` con canal.

---

## 4. Requisitos no funcionales

- ✅ **Seguridad webhook**: verify token por tenant + firma HMAC obligatoria.
- ✅ **Aislamiento multi-tenant**: resolución estricta `phone_number_id` → cliente; sin
  mapeo no hay respuesta.
- ✅ Token global o por tenant (`whatsapp.access_token` / `WHATSAPP_ACCESS_TOKEN`).
- 🟡 **Ventana de 24 h de Meta**: fuera de la ventana solo caben plantillas aprobadas;
  los recordatorios usan plantilla/interactivo con fallback. Sin gestión explícita de
  errores de ventana por mensaje.
- 🔵 **Cola/reintentos de envío** ante errores transitorios de la Cloud API.

---

## 5. Reglas de negocio y restricciones

- El remitente verificado solo actúa sobre **sus** citas; para citas de terceros se exige
  el contacto de la reserva (mismo criterio que voz/chat).
- No responde si el tenant no está habilitado o la firma no valida.
- Nunca confirma una cita sin registro real (el flujo guiado crea la cita de verdad).
- No acepta servicios fuera del catálogo real.

---

## 6. Estado actual vs. objetivo (resumen ejecutivo)

**Ya cumplido:** webhook seguro multi-tenant, menú interactivo nativo, flujo de reserva
guiado completo (servicio→profesional→día→hora→datos→confirmación, con huecos reales),
gestión de citas por pasos con remitente verificado, política de cancelación, cerebro
compartido con el chat (catálogo + horario semanal real en el prompt, disponibilidad
determinista, pago, memoria de gestión en texto libre), recordatorios con botones,
multi-centro por número, registro completo. **Unificado hoy:** la intención de reserva
por texto libre arranca en el selector de servicio (antes saltaba al día sin servicio),
las confirmaciones de cambio hablan la fecha en humano, el fallo de reprogramación ofrece
alternativas reales (helper compartido con el chat) y el menú se presenta en nombre del
negocio (no del bot).

**Brechas priorizadas (propuesto):**

1. 🔵 Cola/reintentos de envío ante errores transitorios de la Cloud API.
2. 🟡 Gestión explícita de la ventana de 24 h (detección de error y plantilla puente).

---

## 7. Criterios de aceptación (ejemplos)

- **Reserva guiada:** "me gustaría pedir cita para un masaje" → selector de servicio →
  profesional → día → hora → nombre/email → resumen → Confirmar → cita real con
  `source='whatsapp'` y `R-XXXXXX`.
- **Cancelar la propia cita:** "cancelar cita R-123456" desde el número de la reserva →
  cancelada sin pedir teléfono; desde OTRO número → pide el contacto de la reserva.
- **Cambiar a hora ocupada:** ofrece 2–3 huecos reales del día; al confirmar dice
  "lunes 6 de julio", no "2026-07-06".
- **Recordatorio:** botón "✅ Confirmo" desde el teléfono de la cita → asistencia
  confirmada en el portal; desde otro número → rechazado.
- **Texto libre:** "¿cuánto cuesta el masaje?" → precio del catálogo real (igual que web).

---

## 8. QA obligatorio

```powershell
python -m pytest tests/test_api_smoke.py -k "whatsapp" -q   # webhook, flujos, firma, botones
python -m pytest -q                                          # suite completa
python scripts\qa_chat_realtime.py                           # cerebro compartido (10 escenarios)
```

El cerebro de texto libre es el mismo del chat: su QA con modelo real
(`qa_chat_realtime.py`) cubre también WhatsApp. Los flujos interactivos (pickers,
botones) se validan en smoke con `_handle_whatsapp_message` directo y envíos capturados.

---

## 9. Anexo técnico (referencia)

**Código:** `backend/whatsapp.py` (webhook, flujos interactivos, menú, recordatorios),
`backend/routers/whatsapp_webhooks.py` (rutas), `backend/messaging.py` (envío Cloud API),
`backend/chat.py` (cerebro compartido), `backend/booking.py` (núcleo de citas +
`_reschedule_failure_text` compartido). Estado de flujo: `appstate.WAFlowState`
(`whatsapp_flows`, por tenant+remitente).

**Config por tenant:** `whatsapp.enabled`, `phone_number_id`, token por tenant opcional;
mapeo global `WHATSAPP_PHONE_CLIENT_MAP`; centro por número en
`locations.whatsapp_phone_number_id`.

---

*Mantener sincronizado con los docs de voz y chat: catálogo, horario, verificación y
cobro son piezas compartidas entre los tres canales.*
