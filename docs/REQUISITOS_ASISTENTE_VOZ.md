# Requisitos del Asistente de Voz — Vantelia

> Documento de requisitos funcional y técnico del asistente de voz multi-tenant.
> Describe **lo que el asistente debe hacer**, marca **qué está implementado hoy** y
> **qué debería incorporar**. Sirve como contrato de producto y guía de roadmap.

**Estado del documento:** vivo · **Última revisión:** 2026-06-26
**Ámbito:** asistente de voz por teléfono (Twilio) y por web (widget WebRTC), su panel
de configuración en el portal y las llamadas salientes de confirmación.

**Leyenda de estado:**

- ✅ **Hecho** — implementado y en producción.
- 🟡 **Parcial** — existe pero incompleto o mejorable.
- 🔵 **Propuesto** — no existe aún; recomendación de este documento.

---

## 1. Visión

El asistente de voz es **una recepcionista de IA** que atiende llamadas y conversaciones
de voz del cliente final en nombre del negocio. Habla español de España de forma natural,
conoce el negocio (servicios, centros, horarios, FAQs), gestiona la agenda en tiempo real
(consultar, crear, reprogramar, cancelar), verifica identidad cuando toca, cobra mediante
enlace seguro y puede **llamar de forma saliente** para confirmar citas. Todo, sin que el
llamante perciba que habla con una máquina.

Objetivo de negocio: **reducir llamadas perdidas y ausencias (no-shows)**, atender 24/7 y
liberar al personal de recepción.

---

## 2. Arquitectura (resumen)

| Canal | Transporte | Entrada | Notas |
| --- | --- | --- | --- |
| **Teléfono** | Twilio Media Streams ↔ OpenAI Realtime (puente WS) | `POST /voice/{cliente_id}` (TwiML) · `WS /voice/stream/{cliente_id}` | Voz real entrante/saliente con tools reales. |
| **Widget web** | WebRTC directo navegador ↔ OpenAI Realtime | `POST /voice/widget/{cliente_id}/session` · `/tool` · `/log` | Opt-in (`voice.widget_enabled`). Botón de micro en el widget. |
| **Portal (prueba)** | WebRTC | `POST /auth/app/voice/session` · `/tool` · `/log` | El negocio prueba su propio asistente desde el panel. |
| **Demo** | WebRTC | `POST /demo/{cliente_id}/voice/session` · `/tool` | **Solo lectura**: no crea ni modifica datos reales. |

- **Modelo:** OpenAI Realtime (audio bidireccional + function calling).
- **Gating:** requiere `voice.enabled` + **plan Business**. El teléfono requiere además un
  **número Twilio** del negocio; el widget requiere `voice.widget_enabled`.
- **Herramientas (function calling) hoy:** `consultar_disponibilidad`, `crear_cita`,
  `consultar_cita`, `cancelar_cita`, `reprogramar_cita`, `enviar_codigo_verificacion`,
  `verificar_codigo`, `enviar_enlace_pago` (si el negocio activa cobro por IA) y
  `confirmar_cita` (solo en llamadas salientes de confirmación).
- **Registro:** cada llamada/sesión se guarda en `voice_calls` con transcripción y resumen,
  y aparece en **Conversaciones** del portal.

---

## 3. Requisitos funcionales

### 3.1 Comportamiento de recepcionista y conversación

- ✅ El asistente **debe comportarse como un recepcionista humano** del negocio: cordial,
  cercano, profesional, una idea por turno.
- ✅ El asistente **debe hablar como una persona**, con muletillas naturales y moderadas
  ("vale", "perfecto", "un momento"), frases cortas y sin sonar robótico.
- ✅ El asistente **debe saludar una sola vez** al inicio y no volver a presentarse.
- ✅ El asistente (entrante) **debe arrancar con el mismo mensaje de bienvenida** que el chat web
  y WhatsApp (Apariencia → "Mensaje de bienvenida"), dicho **palabra por palabra, sin cambiar
  ningún nombre propio**. La llamada **saliente** de confirmación usa su propio guion, no la
  bienvenida.
- ✅ **Identidad configurable en Apariencia**: el asistente se presenta con el **nombre del bot**
  (campo "Nombre del bot") y representa al **negocio** (campo "Nombre del negocio"; si se deja
  vacío, el negocio toma el nombre del bot). No confunde su propio nombre con el del negocio.
- ✅ Cambiar en Apariencia el nombre del bot, el del negocio o la bienvenida **se aplica en la
  siguiente conversación** (chat, WhatsApp y voz; una llamada en curso no cambia a mitad).
- ✅ El asistente **nunca debe revelar que es una IA**, ni mencionar herramientas internas,
  modelos, códigos de sistema ni etiquetas técnicas.
- ✅ El asistente **debe dar la información por trozos** (2–3 opciones) y preguntar si seguir,
  en vez de soltar listas largas de un tirón.
- ✅ El asistente **no debe narrar pasos internos** ("voy a proceder…") ni repetir la misma
  frase dos veces seguidas.
- 🔵 El asistente **debería poder transferir a un humano** (desviar la llamada a un número del
  negocio) cuando el llamante lo pida o detecte un caso fuera de su alcance.
- 🔵 El asistente **debería despedirse y colgar limpiamente** tras un cierre claro o un
  silencio prolongado, en vez de esperar indefinidamente.

### 3.2 Idioma

- ✅ El asistente **debe hablar siempre en español de España**.
- ✅ El asistente **debe transcribir la voz del cliente como español** (idioma fijado en la
  transcripción) para no confundir "sí" con "see" ni mezclar otros idiomas.
- 🔵 El asistente **debería soportar otros idiomas configurables por tenant** (p. ej. catalán,
  inglés para negocios turísticos), detectando o fijando idioma por número/centro.

### 3.3 Conocimiento del negocio

- ✅ El asistente **debe conocer todos los servicios del cliente** tal y como están en la
  sección **Servicios** del portal (catálogo real: nombre, duración, precio).
- ✅ El asistente **debe enumerar y reservar solo servicios reales** del catálogo; si piden uno
  que no existe, no debe aceptarlo como sinónimo, debe ofrecer alternativas reales.
- ✅ El asistente **debe responder dudas generales** (dirección, horarios, condiciones, FAQs)
  desde la base de conocimiento del negocio (RAG por `info.txt`).
- ✅ En negocios **multi-centro**, el asistente **debe pedir el centro** antes de mirar
  disponibilidad y **pasarlo a las herramientas** (parámetro `centro` en `consultar_disponibilidad`
  y `crear_cita`, obligatorio solo si hay >1 centro): la disponibilidad y la reserva quedan
  **acotadas a ese centro**, la cita **se crea en él** y el precio se resuelve por centro. Si el
  número entrante está asignado a un centro, se asume ese sin preguntar.
- 🟡 El asistente **debería reflejar cambios del catálogo al instante**. Hoy el prompt se
  construye al iniciar la sesión; un cambio a mitad de llamada no se refleja hasta la siguiente.

### 3.4 Agenda: disponibilidad

- ✅ El asistente **debe estar perfectamente sincronizado con el calendario** y saber en tiempo
  real si hay hueco o no (`consultar_disponibilidad`), usando la misma lógica que el widget y
  el portal (por empleado, servicio, duración y centro).
- ✅ El asistente **debe respetar la ventana de reserva** (antelación máxima/mínima), el horario
  del negocio, los bloqueos de agenda y el aforo por salas/recursos.
- ✅ El asistente **debe ofrecer 2–3 horas concretas** y dejar que el llamante elija, pero
  **dejando claro que hay más disponibles** cuando las haya (nombrando la franja: "y también por
  la tarde", "y tengo más horas ese día"), sin dar a entender que solo quedan esas tres. Si el
  cliente pide una franja ("por la tarde", "a partir de las cinco") o más opciones, ofrece huecos
  de esa franja a partir de la lista real.
- ✅ El asistente **debe decir las horas en lenguaje natural** ("las once de la mañana", "las
  cinco y media"), **nunca** "once cero cero" ni "09:00".
- ✅ El asistente **solo puede ofrecer, aceptar o confirmar una hora que `consultar_disponibilidad`
  acabe de devolver como libre**. La lista de huecos es la **única** fuente de horas reservables. Si
  el cliente pide una hora concreta que no está en la última lista (o de otro día), **debe volver a
  consultar disponibilidad antes de aceptarla** y **nunca** prometer ("sí, sin problema") una hora
  sin verificarla. No se inventa ni propone horas que no haya devuelto la herramienta.

### 3.5 Agenda: crear cita

- ✅ El asistente **debe ser capaz de crear citas** reales por voz (`crear_cita`,
  `source='voice'`), con cita confirmada de verdad.
- ✅ El asistente **debe confirmar en voz alta antes de reservar**: nombre, teléfono, servicio,
  centro, día y hora.
- ✅ El asistente **debe pedir y repetir el teléfono** (9 dígitos ES) y no confirmar si no lo ha
  cogido bien; el email es opcional por teléfono.
- ✅ El asistente **debe crear la cita de inmediato** en cuanto el cliente confirma (un "un
  momento" como mucho), sin alargarse ni repetir el proceso. Objetivo: **≤ 10 s**.
- ✅ El asistente **debe dar el número de reserva** (formato `R-XXXXXX`) dígito a dígito y la
  **fecha y hora habladas** ("mañana a las once", "el 26 de junio").
- ✅ El asistente **envía la confirmación por los canales del negocio (email/SMS/WhatsApp)** al
  crear la cita —con número de reserva y enlace de gestión—, igual que una reserva web, y lo
  anuncia en voz ("te envío la confirmación por mensaje"). Respeta los canales y el plan
  configurados en Seguimiento; es best-effort (la cita queda creada aunque el envío falle). El
  envío va **en segundo plano** para no añadir latencia: el asistente confirma de viva voz al
  instante y el SMS/email sale después.
- ✅ **`crear_cita` es la única confirmación válida**: hasta que no devuelve `ok`, la cita no está
  hecha y no se da por reservada. El backend valida el hueco en el momento de crear (fuente de
  verdad): si la hora se ocupó entre tanto, `crear_cita` **devuelve alternativas reales del mismo
  día** (con su `mensaje_voz`) para que el asistente las ofrezca sin inventar, en vez de un error
  ciego. Así nunca se confirma al cliente una hora que luego resulta no estar libre.

### 3.6 Agenda: reprogramar y cancelar

- ✅ El asistente **debe ser capaz de reprogramar citas** (`reprogramar_cita`) y **cancelar**
  (`cancelar_cita`), localizando la cita por número de reserva (`consultar_cita`).
- ✅ El asistente **debe verificar identidad antes de cambiar o cancelar** (ver 3.7).
- ✅ Al cancelar/reprogramar, el asistente **debe aplicar la política de cancelación/no-show**
  del negocio si está activa (captura/retención/reembolso sobre el pago ya autorizado, nunca
  cargos nuevos).


### 3.7 Verificación de identidad

- ✅ Antes de reprogramar o cancelar, el asistente **debe verificar al titular**. Según el modo
  de contacto y la configuración del negocio:
  - **Código de 4 dígitos** (`enviar_codigo_verificacion` + `verificar_codigo`) por **SMS o
    email**, según el contacto registrado en la cita. El asistente **nunca lee el código**.
  - **Por teléfono/email**: si el negocio desactiva el OTP (sección Seguimiento), o si el código
    no llega, el asistente **debe verificar pidiendo el teléfono o el email** con el que se hizo
    la reserva y continuar solo si coincide.
- ✅ Estas acciones **solo funcionan si el teléfono que llama coincide** con el de la reserva; en
  caso contrario el asistente debe pedir el dato de contacto y reintentar.
- ✅ La verificación por código **debe ser configurable** (on/off y canales) desde el portal.

### 3.8 Llamadas salientes de confirmación

- ✅ El asistente **debe ser capaz de llamar al cliente para confirmar una cita**
  (`confirmar_cita`, llamada saliente Twilio).
- ✅ Para confirmar, el asistente **no debe enviar código de 4 dígitos** ni pedir número de
  reserva: el teléfono ya está verificado por ser una llamada a su propio número. Solo pregunta
  si le sigue viniendo bien y marca la confirmación.
- ✅ En la llamada saliente, si el cliente quiere cancelar o cambiar, el asistente **debe poder
  hacerlo** sin pedir código (ya verificado).
- ✅ El negocio **debe poder lanzar la llamada manualmente** desde el detalle de la cita y
  **reenviar la confirmación** por los canales configurados.
- 🟡 El asistente **debería detectar buzón de voz/contestador** en salientes y no "hablar al
  vacío" (colgar o dejar un mensaje breve). Hoy no se detecta de forma fiable.

### 3.9 Llamada de confirmación automática por IA

- ✅ El sistema **debe llamar automáticamente** al cliente para confirmar (opt-in, interruptor
  "Llamada de confirmación por IA" en Seguimiento) **unas horas antes de la cita** —configurable,
  por defecto 5 h (`call_hours_before`, rango 1–24)— como **último escalón** del seguimiento,
  **independiente** de los recordatorios 24 h/2 h.
- ✅ La llamada **solo se coloca si el cliente aún no ha confirmado** por ningún canal, y **nunca
  dos veces** para la misma cita (sin duplicados).
- ✅ El sistema **debe respetar las horas de silencio** (`quiet_start`/`quiet_end`, hora local del
  negocio; por defecto 21:00–09:00) y un **tope diario de llamadas** (`daily_call_cap`, por
  defecto 30).
- ✅ El fallback **debe respetar el gating** (plan Business + número Twilio + credenciales) y
  **registrarse como llamada** (`direction='outbound'`, `purpose='confirm'`) en Conversaciones.
- ✅ Sus parámetros (activar, horas antes, horas de silencio, tope/día) **deben ser configurables**
  desde el portal (Seguimiento → "Llamada de confirmación por IA"). La fuente de verdad es
  `follow_up` (`GET/PUT /auth/app/follow-up`); `reminders` queda como alias de compatibilidad.
- ✅ El negocio **debe poder probar esta fase** ("▶ Probar esta fase") y lanzar una llamada manual
  desde el detalle de la cita (`POST /auth/bookings/{id}/confirm-call`).
- 🔵 El asistente **debería reintentar** una saliente no contestada un nº limitado de veces, con
  separación temporal, antes de rendirse.

### 3.10 Cobro

- ✅ El asistente **debe poder enviar un enlace de pago seguro** al cliente
  (`enviar_enlace_pago`, SMS) cuando el negocio activa el cobro por IA, con el importe fijado por
  el negocio (nunca por el cliente). **Nunca pide datos bancarios por voz** ni lee la URL.
- 🔵 El asistente **debería poder tomar señal/pre-autorización** en la propia reserva por voz
  cuando el servicio lo exige (hoy el flujo preauth vive en web/portal).

### 3.11 Fechas, horas y números hablados

- ✅ El asistente **debe decir fechas en lenguaje natural** ("hoy", "mañana", "el viernes 26 de
  junio"), **nunca** en formato `2026-06-26`.
- ✅ El asistente **debe decir horas, precios y números de forma natural** y deletrear el código
  de reserva dígito a dígito.

### 3.12 Interrupciones, ruido y turno de palabra

- ✅ El asistente **debe permitir que le interrumpan** (barge-in) como en una llamada real y
  retomar sin repetir desde el principio.
- ✅ El asistente **no debe cortarse por ruidos, toses o monosílabos** accidentales, ni
  responder a silencio o a su propio eco.
- ✅ El asistente **debe poder ajustar** sensibilidad de fin de turno y reducción de ruido por
  tenant (`server_vad`/`semantic_vad`, umbral, silencio, `near/far_field`).
- ✅ Tras ejecutar una herramienta (consultar/crear/cancelar…), el asistente **debe decir el
  resultado de inmediato**, sin quedarse mudo a la espera de que el cliente vuelva a hablar. (El
  `response.create` del resultado se lanza al cerrarse el turno de la herramienta —`response.done`—
  para no chocar con la "respuesta activa" del Realtime, que antes dejaba al asistente callado.)

### 3.13 Registro y trazabilidad

- ✅ Toda llamada/sesión **debe registrarse** (`voice_calls`: dirección, propósito, duración,
  transcripción y resumen) y ser visible en **Conversaciones** del portal.
- ✅ Cada acción sobre la cita (crear/cancelar/reprogramar/confirmar/pago) **debe quedar
  auditada** en `booking_audit`.
- 🔵 El asistente **debería etiquetar el resultado** de cada llamada (reservada / confirmada /
  cancelada / sin acción / no contesta) para informes.

---

## 4. Requisitos no funcionales

- 🟡 **Latencia de conversación:** respuesta natural tras el turno del cliente (objetivo
  ≈ < 1,2 s) y **creación de cita ≤ 10 s** extremo a extremo. Ajustable vía VAD.
- ✅ **Aislamiento multi-tenant:** el asistente solo accede a datos, catálogo, agenda y centros
  del cliente correspondiente; el número/centro entrante acota el contexto.
- ✅ **Seguridad de identidad:** mutaciones (cancelar/reprogramar) solo tras verificación; el
  código nunca se lee en voz alta.
- ✅ **Gating por plan:** voz solo en plan Business; teléfono requiere número provisionado.
- 🟡 **Coste controlado:** cada minuto tiene coste (Twilio + OpenAI). Las salientes tienen tope
  diario y horas de silencio; debería existir un **tope/alerta de gasto** por tenant.
- 🔵 **Resiliencia:** ante fallo del modelo/proveedor, el asistente debería degradar con gracia
  (mensaje y, si procede, recoger datos para devolver la llamada) en lugar de cortar en seco.
- 🔵 **Observabilidad:** métricas agregadas (duración media, tasa de reserva, abandono, errores
  de tool) en el panel.

---

## 5. Reglas de negocio y restricciones

- El **precio y el importe a cobrar los fija el negocio** según el servicio/centro; el cliente
  nunca los decide.
- El asistente **no inventa huecos ni confirma citas** sin que la herramienta correspondiente
  devuelva éxito.
- El asistente **no acepta servicios fuera del catálogo** real.
- En **demo**, el asistente es de **solo lectura**: nunca crea ni altera datos reales.
- Las salientes respetan **horas de silencio** y **tope diario**.

---

## 6. Estado actual vs. objetivo (resumen ejecutivo)

**Ya cumplido (núcleo sólido):** crear/consultar/reprogramar/cancelar citas, sincronización
real con agenda y catálogo, **multi-centro real por voz** (pregunta el centro, lo pasa a las
herramientas y acota disponibilidad/reserva/precio a ese centro), verificación OTP configurable +
por teléfono/email, llamadas salientes de confirmación sin OTP, fallback a llamada con horas de
silencio y tope, **confirmación al crear la cita** (en segundo plano) con nº de reserva + enlace,
cobro por enlace, habla natural con fechas/horas en español, **saludo e identidad desde Apariencia**
(bienvenida verbatim + nombre del bot / nombre del negocio), idioma de transcripción fijado, el
asistente **habla el resultado de la herramienta de inmediato** (sin quedarse mudo), registro en
Conversaciones con transcripción y resumen.

**Brechas priorizadas (propuesto):**

1. 🔵 **Transferencia a humano** y cierre/colgado limpio.
2. 🟡 **Detección de buzón de voz** en salientes + 🔵 reintentos controlados.
3. 🔵 **Aviso de grabación/RGPD** y política de retención de transcripciones.
4. 🔵 **Métricas y etiquetado de resultado** de llamada en el panel.
5. 🔵 **Lista de espera** cuando no hay hueco.
6. 🟡 **Tope/alerta de gasto** por tenant.
7. 🔵 **Idioma configurable** por tenant/centro.
8. 🟡 **Reflejar cambios de catálogo/identidad a mitad de llamada** (hoy aplican en la siguiente).

---

## 7. Criterios de aceptación (ejemplos)

- **Crear cita:** llamante pide masaje para mañana → el asistente pide centro, ofrece 2–3 horas
  habladas, confirma datos, crea la cita en ≤ 10 s y dice "mañana a las once de la mañana,
  código R-…". La cita aparece confirmada en el portal con `source='voice'`.
- **Reprogramar:** llamante da su número de reserva → el asistente lo localiza, envía código por
  el canal registrado, valida, busca hueco y reprograma; queda auditado.
- **Confirmación saliente:** el asistente llama, saluda de parte del negocio, pregunta si le
  viene bien, el cliente dice "sí" → marca confirmada **sin** pedir código ni número de reserva.
- **Idioma:** el cliente dice "sí" → se transcribe "sí" (no "see") y el flujo continúa.
- **Servicio inexistente:** piden un servicio que no está en el catálogo → el asistente no lo
  acepta y ofrece alternativas reales.

---

## 8. Anexo técnico (referencia)

**Configuración por tenant (`config.json` → `voice`):** `enabled`, `widget_enabled`,
`twilio_phone_number`, `vad_type` (`server_vad`/`semantic_vad`), `vad_eagerness`,
`vad_silence_ms`, `vad_threshold`, `vad_prefix_padding_ms`, `noise_reduction`
(`near_field`/`far_field`). OTP de voz: Seguimiento → `voice_otp_channels`. Llamada de
confirmación por IA (fuente de verdad `follow_up`, vía `GET/PUT /auth/app/follow-up`):
`call_enabled` (alias `call_fallback`), `call_hours_before`, `quiet_start`/`quiet_end`,
`daily_call_cap`. `_reminders_config` es un alias de lectura de estos mismos campos.

**Identidad y saludo (Apariencia, `GET/PUT /auth/app/appearance`):** `nombre` (nombre del bot),
`empresa` (nombre del negocio; vacío = usa `nombre`), `bienvenida` (saludo entrante, compartido con
chat/WhatsApp). El system prompt (`rag._build_system_prompt`) separa bot vs negocio. Guardar
invalida sesiones → aplica en la siguiente conversación.

**Multi-centro:** las tools `consultar_disponibilidad` y `crear_cita` aceptan `centro` (obligatorio
si >1 centro); `voice._voice_resolve_location_id` lo resuelve a `location_id`. El centro del número
entrante (si está asignado) tiene prioridad.

**Endpoints principales:**

- Teléfono: `POST /voice/{cliente_id}` (TwiML), `POST /voice/status/{cliente_id}`,
  `WS /voice/stream/{cliente_id}`.
- Widget: `POST /voice/widget/{cliente_id}/session` · `/tool` · `/log`.
- Portal: `GET/POST /auth/app/voice`, `POST /auth/app/voice/session` · `/tool` · `/log`,
  `POST /auth/bookings/{id}/confirm-call`, `POST /auth/bookings/{id}/send-confirmation`,
  `GET/PUT /auth/app/reminders`.
- Demo (solo lectura): `POST /demo/{cliente_id}/voice/session` · `/tool`.
- Admin: `POST /admin/clientes/{cliente_id}/voice`, `GET /admin/voice/calls`,
  `GET /admin/voice/calls/{call_sid}`.

**Código de referencia:** `backend/voice.py` (núcleo: instrucciones, tools, dispatch, salientes,
helpers de habla), `backend/routers/voice_web.py` (puente Twilio + WS), `backend/routers/
portal_app.py` (config y acciones de portal), `backend/routers/ui_pages.py` (widget/demo).

---

*Mantener este documento sincronizado cuando cambien las herramientas de voz, el gating por
plan o los flujos de verificación, salientes y cobro.*
