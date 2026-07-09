# Requisitos del Asistente de Chat — Vantelia

> Documento de requisitos funcional y técnico del asistente de chat multi-tenant
> (widget web + WhatsApp + prueba del portal). Espejo del de voz
> (`REQUISITOS_ASISTENTE_VOZ.md`): describe **lo que el asistente debe hacer**, marca
> **qué está implementado hoy** y **qué debe incorporar**. Contrato de producto y guía.

**Estado del documento:** vivo · **Última revisión:** 2026-07-03
**Ámbito:** asistente de chat del widget embebible, WhatsApp Cloud API (mismo cerebro),
prueba del portal y demo pública.

**Leyenda de estado:**

- ✅ **Hecho** — implementado y en producción.
- 🟡 **Parcial** — existe pero incompleto o mejorable.
- 🔵 **Propuesto** — no existe aún; recomendación de este documento.

---

## 1. Visión

El asistente de chat es **el recepcionista escrito** del negocio: la misma recepcionista
que atiende por voz, pero en texto. Conoce el negocio (servicios, precios, horarios,
centros, FAQs), consulta la agenda **real** en el momento, agenda mediante **formulario
integrado** (el equivalente escrito a "crear la cita en la llamada"), gestiona citas
existentes (cancelar/reprogramar con verificación), cobra por enlace seguro y deriva a
humano cuando toca. Profesional e inteligente: responde con datos verificados, nunca
inventa, y cada respuesta acaba con un siguiente paso útil.

**Diferencias estructurales con la voz** (no son carencias, son el medio):

- No hay llamada que colgar: la conversación queda abierta; el cierre es un mensaje de
  despedida con siguiente paso.
- La reserva se completa con el **formulario** del widget (servicio → profesional → día →
  hora → datos), no dictando datos: menos errores de transcripción y validación en vivo.
- Puede usar **elementos visuales**: botones de acción rápida (quick actions), listas
  formateadas, negritas, enlaces.
- La escritura permite **pegar directamente** el número de reserva, email o teléfono.

Objetivo de negocio: **convertir visitas web en citas** y resolver dudas 24/7 sin fricción.

---

## 2. Arquitectura (resumen)

| Canal | Transporte | Entrada | Notas |
| --- | --- | --- | --- |
| **Widget web** | `POST /chat` | `widget/chat.js` + `widget/form.js` | Formulario de reserva integrado (sentinel `[MOSTRAR_FORMULARIO]`). |
| **WhatsApp** | Webhook Cloud API | `backend/whatsapp.py` → `_process_chat_message` | Mismo cerebro; `trusted_phone` = número verificado del remitente. |
| **Portal (prueba)** | `POST /chat` | app_ui pestaña IA | El negocio prueba su asistente. |
| **Demo** | `POST /chat` | `/demo/{cliente_id}` | Página de venta; mismo flujo. |

- **Cerebro:** `backend/chat.py` (`_process_chat_message`) = orquestador determinista
  (menú, disponibilidad, gestión de citas, pago, FAQ, límite de sesión) + motor RAG
  (`backend/rag.py`, llama-index sobre `data/<cliente>/info.txt` + system prompt
  `rag._build_system_prompt`) para la conversación libre.
- **Filosofía (igual que la voz):** *fiabilidad en las herramientas deterministas, no en
  encarrilar al modelo*. Disponibilidad, gestión de citas y pagos NO los responde el LLM:
  los responde el backend con datos reales; el LLM cubre información y venta.
- **Registro:** cada sesión se guarda en `chat_sessions`/`chat_messages` y aparece en
  **Conversaciones** del portal (canal `web` o `whatsapp`).

---

## 3. Requisitos funcionales

### 3.1 Comportamiento y conversación

- ✅ El asistente **debe presentarse como el asistente del negocio** (no de Vantelia), con
  la identidad de Apariencia: nombre del bot, nombre del negocio, mensaje de bienvenida.
- ✅ **Menú principal** al saludar o escribir "menú": opciones adaptadas al negocio
  (agendar solo si la reserva está activa) + quick actions pulsables.
- ✅ Tono **profesional, cercano y breve** (1–4 frases por defecto); listas con formato
  "· **Título:** detalle"; responde en el idioma del usuario (es/en/ca…).
- ✅ **No inventa**: precios, horarios, teléfonos y promociones solo de la base documental
  o de los bloques de contexto del sistema; si falta el dato, lo dice y deriva.
- ✅ **Deriva a humano** ante queja, urgencia o caso sensible (médico/legal/financiero),
  compartiendo teléfono/email verificados.
- ✅ Modos comerciales: diagnóstico, recomendador, estimador y comparador (detección de
  intención + instrucciones específicas).
- ✅ **Límite de sesión** (`MAX_MESSAGES_PER_SESSION`) con derivación amable.
- 🔵 **Cierre proactivo**: tras resolver ("¿te ayudo con algo más?") y despedida limpia si
  el usuario se despide — equivalente escrito del `finalizar_llamada` de voz.

### 3.2 Conocimiento del negocio

- ✅ **Base documental RAG** por cliente (`info.txt` + Q&A del panel): responde dirección,
  condiciones, equipo, políticas, procesos…
- ✅ **Q&A exactas del panel** tienen prioridad (match determinista antes que el LLM).
- ✅ **Catálogo REAL de servicios en el prompt** (nombre, duración, precio desde la tabla
  `services`, igual que la voz): enumerar/presupuestar usa el catálogo, no el `info.txt`
  (que puede quedar desactualizado); un servicio fuera del catálogo no se acepta como
  reservable y se ofrecen 2–3 reales. *(Compartido con voz: `booking._services_prompt_block`.)*
- ✅ **Horario del negocio en el prompt** derivado de los MISMOS profesionales públicos
  que usa la disponibilidad (envolvente real por día, "cerrado" solo si ningún profesional
  trabaja; fallback a `config['booking']`) — igual que `voice._voice_schedule_block`. El
  asistente sabe qué días se cierra y **no ofrece ni deja pedir cita en día cerrado**;
  cambios de horario desde el portal aplican en la siguiente conversación.
  *(Compartido con voz: `agenda._weekly_schedule_matrix`.)*
- ✅ **Multi-centro**: el prompt incluye el bloque CENTROS (`rag._locations_prompt_block`,
  solo si >1) y el formulario del widget permite elegir centro (`data-location` /
  selector); la disponibilidad y la cita quedan acotadas al centro.
- ✅ **Datos en vivo** en cada mensaje: fecha/hora local, abierto/cerrado ahora, descansos,
  días cerrados, contacto.

### 3.3 Agenda: disponibilidad

- ✅ La disponibilidad la responde **el backend con la agenda real**, no el LLM
  (`rag._build_chat_availability_answer`): mismo motor que widget/portal/voz (por
  empleado, servicio, duración, centro, bloqueos, festivos, aforo).
- ✅ Soporta **fecha concreta, rangos y franjas** ("mañana por la tarde", "esta semana"),
  filtro por servicio, "¿cuándo cerráis por vacaciones?", siguiente día con huecos si el
  pedido está cerrado/lleno.
- ✅ Si el día pedido no tiene huecos, ofrece **alternativas reales** (mismo día u otro
  día) y nunca promete horas sin verificar.
- ✅ Sin fecha concreta, asume **hoy** pero lo dice explícitamente en la respuesta (la
  etiqueta del día siempre acompaña a los huecos); una intención de **reserva** ("quiero
  cita para un masaje") nunca se responde como consulta de disponibilidad: abre el
  formulario.
- ✅ Cierra ofreciendo **abrir el formulario** para completar la reserva.

### 3.4 Agenda: crear cita (formulario)

- ✅ La reserva se completa con el **formulario integrado** del widget
  (`widget/form.js`): servicio (con duración y precio), profesional, centro si hay
  varios, día (solo días abiertos), hora (solo huecos reales), nombre, teléfono, email.
  El equivalente escrito de "crear la cita en la llamada": datos estructurados y
  validados, sin transcripciones erróneas.
- ✅ El asistente **abre el formulario** cuando detecta intención de reserva (sentinel
  `[MOSTRAR_FORMULARIO]` del LLM + detección determinista como red).
- ✅ La cita creada es **real e igual a cualquier canal**: `source='web'`, snapshot de
  precio, email de confirmación con nº de reserva + enlace de gestión, y hereda TODO el
  Seguimiento (recordatorios 24 h/2 h, llamada IA, reseña).
- ✅ Pago/preautorización en el propio flujo si el servicio lo exige (Stripe Checkout).
- 🔵 **Prefijar el formulario** desde la conversación: si el usuario ya dijo "masaje el
  lunes por la tarde", abrir el formulario con servicio/fecha preseleccionados.

### 3.5 Agenda: gestionar cita existente (cancelar / reprogramar)

- ✅ El asistente **cancela y reprograma** citas por chat con verificación: número de
  reserva (`R-XXXXXX`) + teléfono o email de la reserva (en WhatsApp, el número del
  remitente ya cuenta como verificado — `trusted_phone`).
- ✅ **Memoria conversacional de gestión**: el flujo funciona por pasos sin repetir datos.
  "Quiero cancelar mi cita" → pide el código → usuario manda "R-123456" → pide
  teléfono/email → usuario lo manda → cancela. Cada dato dicho queda recordado dentro de
  la sesión (código, intención, contacto); no se le vuelve a pedir lo que ya dio.
- ✅ Al reprogramar valida el hueco real (mismo motor que la disponibilidad); si la hora
  pedida está ocupada o cerrada, **ofrece alternativas reales** del mismo día o siguiente.
- ✅ La cancelación **aplica la política de cancelación/no-show** del negocio si está
  activa (sobre el pago ya autorizado; nunca cargos nuevos) — mismo núcleo que el resto
  de canales (`_cancel_booking_core`).
- ✅ Todo queda **auditado** en `booking_audit` y visible en el timeline de la cita.
- 🔵 OTP de 4 dígitos opcional para chat web (hoy el OTP es de voz; el chat verifica por
  teléfono/email — suficiente, mismo criterio que voz con OTP desactivado).

### 3.6 Cobro

- ✅ Intención de pago ("quiero pagar mi cita") → **enlace de pago Stripe** por el flujo de
  IA (`_process_payment_request_message`): identifica la cita por código o por el
  contacto verificado, importe según la política del servicio (nunca lo fija el cliente),
  opt-in del negocio, dedup y rate limit. Igual que la voz.

### 3.7 Interfaz del widget

- ✅ **Quick actions** pulsables (agendar, servicios, FAQs) en el menú.
- ✅ Render de **Markdown básico** con escape XSS; enlaces clicables.
- ✅ Botón de **voz opt-in** (si `voice.widget_enabled`): el mismo widget escala de chat a
  llamada.
- ✅ Identidad visual por tenant (color, icono, posición, bienvenida).
- ✅ Compatibilidad estable del snippet y los atributos `data-*`.
- ✅ Quick action de **gestión de cita** ("Cancelar o cambiar mi cita") en el menú cuando
  la reserva online está activa.

### 3.8 WhatsApp (mismo cerebro)

- ✅ Reusa `_process_chat_message` con `trusted_phone` (verificación implícita del
  remitente): gestión de citas sin pedir teléfono.
- ✅ Recordatorios con botones "✅ Confirmo" / "❌ Cancelar cita".
- ✅ Respuesta solo si el tenant está habilitado y la firma del webhook es válida.

### 3.9 Registro y trazabilidad

- ✅ Sesiones y mensajes en `chat_sessions`/`chat_messages`, con `intent` etiquetado
  (menu, availability, booking_cancel, booking_reschedule, payment…), visibles en
  **Conversaciones** del portal con filtro por canal.
- ✅ Leads capturados visibles en el panel.

---

## 4. Requisitos no funcionales

- ✅ **Aislamiento multi-tenant** (config + índice + agenda por cliente; CORS por origen).
- ✅ **Rate limit** por IP (`CHAT_RATE_LIMIT_PER_MINUTE`) y TTL de sesión.
- ✅ **Sin datos sensibles**: no pide tarjeta ni datos clínicos por chat; el pago va por
  enlace seguro.
- 🟡 **Latencia**: primer token < 3 s objetivo (RAG + LLM). Sin streaming hoy.
- 🔵 **Streaming de respuesta** en el widget para percepción de velocidad.

---

## 5. Reglas de negocio y restricciones

- El precio lo fija el negocio (catálogo/centro); el asistente nunca lo negocia.
- El asistente **no confirma citas por texto libre**: la cita nace del formulario (web) o
  del flujo estructurado (WhatsApp); nunca "te la apunto" sin registro real.
- No acepta servicios fuera del catálogo real.
- Cancelar/reprogramar exige verificación (código + contacto de la reserva).
- En demo, el flujo es el real contra el tenant de demo.

---

## 6. Estado actual vs. objetivo (resumen ejecutivo)

**Ya cumplido:** menú con quick actions, RAG multi-tenant con Q&A del panel,
disponibilidad real determinista (fechas, franjas, vacaciones, siguiente hueco),
formulario de reserva completo (servicio/duración/precio, profesional, centro, pago),
cancelación/reprogramación por código con verificación y política de cancelación, cobro
por enlace, WhatsApp con el mismo cerebro y teléfono verificado, registro completo en
Conversaciones, **horario real de empleados y catálogo de servicios en el prompt
(compartidos con voz)**, **memoria conversacional de gestión de citas**, **alternativas
reales al reprogramar sobre hueco ocupado**, y **quick action de gestión de cita**.

**Brechas priorizadas (propuesto):**

1. 🔵 Prefijar el formulario desde la conversación (servicio/fecha ya dichos).
2. 🔵 Streaming de respuesta en el widget.
3. 🔵 Cierre proactivo/despedida.
4. 🔵 OTP opcional para chat web.

---

## 7. Criterios de aceptación (ejemplos)

- **Servicios/precios:** "¿cuánto cuesta el masaje?" → precio y duración del catálogo
  real (tabla `services`), no del `info.txt`.
- **Día cerrado:** "¿tenéis hueco el domingo?" → "los domingos cerramos" + siguiente día
  con huecos reales. Nunca abre el formulario para un día cerrado.
- **Reserva:** "quiero cita para un masaje" → abre el formulario; la cita aparece en el
  portal con `source='web'` y llega el email con `R-XXXXXX`.
- **Cancelar en 3 mensajes:** "quiero cancelar mi cita" → "dime el número" → "R-123456"
  → "dime el teléfono o email" → "600111222" → cancelada en BD + auditoría. Sin repetir
  ningún dato.
- **Reprogramar a hora ocupada:** ofrece alternativas reales del día, no un error seco.
- **Servicio inexistente:** "quiero uñas de gel" (no está) → no lo acepta, ofrece 2–3
  servicios reales.
- **Pago:** "quiero pagar mi cita R-123456" → enlace de Stripe si el negocio tiene el
  cobro por IA activo.
- **Fuera de ámbito:** "¿quién ganó la liga?" → redirige con cortesía al ámbito del
  negocio.
- **Inglés:** "do you have any appointments tomorrow?" → responde en inglés con huecos
  reales.

---

## 8. QA obligatorio

### 8.1 Determinista (sin OpenAI, gratis, en CI)

```powershell
python -m pytest tests/test_api_smoke.py -k "chat or booking_management or availability" -q
python -m pytest  # suite completa
```

Cubre: menú, disponibilidad sin OpenAI, gestión por código (memoria incluida),
formulario, WhatsApp, prompts (horario + catálogo presentes).

### 8.2 Con modelo real (barato: gpt-4o-mini, tenant aislado)

```powershell
python scripts\qa_chat_realtime.py
```

Matriz mínima: información/precios desde catálogo, horario y día cerrado, disponibilidad
real, intención de reserva → formulario, cancelación multi-turno con memoria,
reprogramación con alternativas, servicio inexistente, pago, fuera de ámbito, inglés.
Mismo criterio que la voz: `"ok": true` en todos los escenarios; un escenario no cuenta
como aprobado si lo bloquea la cuota.

---

## 9. Anexo técnico (referencia)

**Código:** `backend/chat.py` (orquestador `_process_chat_message` + NLU ligera),
`backend/rag.py` (system prompt `_build_system_prompt`, disponibilidad
`_build_chat_availability_answer`, sesiones/registro), `backend/booking.py`
(`_process_booking_management_message` con memoria de sesión,
`_process_payment_request_message`, `_message_requests_booking_form`),
`backend/agenda.py` (`_weekly_schedule_matrix` — matriz semanal compartida chat/voz),
`widget/chat.js` (render), `widget/form.js` (formulario de reserva),
`backend/whatsapp.py` (webhook + flujos WA).

**Estado conversacional:** `appstate.CHAT_MANAGE_STATE` (por `session_id`: intención,
código, contacto; TTL corto). El LLM no gestiona citas: lo hace el backend.

**Identidad/bienvenida:** Apariencia (`nombre`, `empresa`, `bienvenida`) — compartida con
voz y WhatsApp; guardar invalida sesiones → aplica en la siguiente conversación.

---

*Mantener sincronizado con `REQUISITOS_ASISTENTE_VOZ.md` cuando cambien catálogo,
horario, verificación o cobro: son piezas compartidas entre canales.*
