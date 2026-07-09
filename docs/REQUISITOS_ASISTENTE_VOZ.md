# Requisitos del Asistente de Voz — Vantelia

> Documento de requisitos funcional y técnico del asistente de voz multi-tenant.
> Describe **lo que el asistente debe hacer**, marca **qué está implementado hoy** y
> **qué debería incorporar**. Sirve como contrato de producto y guía de roadmap.

**Estado del documento:** vivo · **Última revisión:** 2026-07-03
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
  `verificar_codigo`, `enviar_enlace_pago` (si el negocio activa cobro por IA),
  `confirmar_cita` (solo en llamadas salientes de confirmación), `finalizar_llamada`
  (colgar limpio, siempre disponible) y `transferir_a_humano` (solo si el negocio
  configura `voice.transfer_number`).
- **Motor determinista compartido (refactor jul 2026):** la lógica que encarrila al modelo
  vive en UNA copia por runtime con la MISMA spec: `backend/voice_engine.py`
  (clase `VoiceCallEngine`, teléfono/Twilio; el puente `routers/voice_web.py` queda fino y
  solo transporta) y `widget/voice_core.js` (funciones puras del navegador, consumidas por
  el widget vía import y por `app_ui` vía `window.VanteliaVoiceCore`). Testeado sin red en
  `tests/test_voice_engine.py` (harness con transporte falso).
- **Registro:** cada llamada/sesión se guarda en `voice_calls` con transcripción y resumen,
  y aparece en **Conversaciones** del portal.

---

## 3. Requisitos funcionales

### 3.1 Comportamiento de recepcionista y conversación

- ✅ El asistente **debe comportarse como un recepcionista humano** del negocio: cordial,
  cercano, profesional, una idea por turno.
- ✅ El asistente **debe hablar como una persona**, con muletillas naturales y moderadas
  ("vale", "perfecto"), frases cortas y sin sonar robótico. En flujos con herramientas
  (agenda, cita, pago, cancelación) **no usa frases de espera** como "un momento" antes
  de ejecutar: primero actúa, luego habla con el resultado.
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
- ✅ En voz **no debe usar instrucciones propias del chat**: nada de "escribe menú",
  "pulsa una opción" ni "volver al menú principal". Debe cerrar con una pregunta hablada.
- ✅ El asistente **debe dar la información por trozos** (2–3 opciones) y preguntar si seguir,
  en vez de soltar listas largas de un tirón.
- ✅ El asistente **no debe narrar pasos internos** ("voy a proceder…") ni repetir la misma
  frase dos veces seguidas.
- ✅ El asistente **puede transferir a un humano** cuando el llamante lo pide o el asunto queda
  fuera de su alcance: tool `transferir_a_humano` (solo si el negocio configura
  `voice.transfer_number` en la pestaña Asistente de voz). En teléfono desvía la llamada de
  verdad (`voice._voice_transfer_call` reescribe el TwiML vivo a `<Say>+<Dial>`); en navegador
  (WebRTC no puede desviar) dicta el número para llamar. Sin número configurado, toma nota y
  dice que el equipo llamará.
- ✅ El asistente **se despide y cuelga limpiamente**: tool `finalizar_llamada` (siempre
  disponible). En teléfono el motor marca `should_end_call` y el puente cierra el WebSocket
  cuando la última frase ya se dijo; en navegador (widget y prueba del portal) el front cuelga
  solo tras la despedida (`end_call` en el resultado de la tool). Ante silencio prolongado
  (>3 recuperaciones del watchdog sin respuesta), despedida cordial y colgado automático.

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
- ✅ Al preguntar el centro **debe usar un español correcto y natural**: "¿En qué centro quieres
  la cita?" o "¿En cuál de nuestros centros prefieres?". **Nunca** "en qué de nuestros centros"
  (es agramatical). Nombra 2–3 centros como mucho, no la lista entera de un tirón.
- ✅ El asistente **debe conocer el horario del negocio** (días y horas de apertura, días cerrados)
  e incluirlo en su contexto: sabe, por ejemplo, que los domingos cierra. **No debe ofrecer ni
  confirmar una cita en un día cerrado**; si el cliente pide uno, lo dice con tacto y ofrece el día
  abierto más cercano. El bloque HORARIO (`voice._voice_schedule_block`) se **deriva de los mismos
  profesionales públicos que usa `consultar_disponibilidad`** (`agenda._list_public_employee_rows` +
  `_employee_schedule_from_row`): un día está "cerrado" solo si **ningún** profesional activo trabaja
  ese día, y las horas mostradas son la envolvente real de la agenda. Así el horario hablado **nunca
  contradice la disponibilidad** y **cualquier cambio de horario (cerrar un día, cambiar las horas de
  un empleado) se refleja en la siguiente conversación** sin tocar código. Si el negocio no tiene
  profesionales, cae al horario base de `config['booking']`. La verdad de huecos sigue siendo
  `consultar_disponibilidad` (refleja además festivos, vacaciones y bloqueos de agenda).
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
- ✅ **Disponibilidad al instante, sin preámbulos**: consultar la agenda es instantáneo, así que el
  asistente **no debe anunciar que va a mirar** ("un momento", "un segundo", "voy a comprobar", "déjame
  que consulte"): llama a `consultar_disponibilidad`/`consultar_cita` **directamente, sin hablar antes**,
  y dice **solo el resultado** (si hay hueco o no, y las horas). Hablar antes de llamar a la herramienta
  cierra el turno y deja la llamada **en silencio** hasta que el cliente insiste — justo lo que hay que
  evitar. El prompt lo prohíbe explícitamente y, como red, si el modelo anuncia y se calla sin ejecutar,
  el sistema lo empuja a llamar a la herramienta (ver 3.12).
- ✅ El asistente **solo puede ofrecer, aceptar o confirmar una hora que `consultar_disponibilidad`
  acabe de devolver como libre**. La lista de huecos es la **única** fuente de horas reservables. Si
  el cliente pide una hora concreta que no está en la última lista (o de otro día), **debe volver a
  consultar disponibilidad antes de aceptarla** y **nunca** prometer ("sí, sin problema") una hora
  sin verificarla. No se inventa ni propone horas que no haya devuelto la herramienta.
- ✅ El asistente **necesita un día concreto antes de hablar de disponibilidad**: **nunca** debe decir
  que hay o no hay huecos (ni "no veo huecos ese día") sin que el cliente le haya dado un día concreto
  **y** haber llamado a `consultar_disponibilidad` para ese día. Si aún no tiene el día, lo pregunta
  ("¿qué día te viene bien?"); **no asume** que el cliente quiere hoy o mañana ni propone horas a ciegas.
- ✅ **Fechas habladas blindadas**: cuando el cliente diga una fecha en lenguaje natural
  ("lunes", "mañana", "12 de julio"), el asistente debe pasar a las herramientas tanto
  `fecha` (`YYYY-MM-DD`) como `fecha_texto` (la frase literal del cliente). El backend
  resuelve `fecha_texto` en la zona horaria del negocio y corrige la fecha ISO si el
  modelo se equivoca (por ejemplo, si convierte "lunes" en martes), antes de consultar
  disponibilidad o crear la cita. La fecha confirmada al cliente y la fecha guardada
  en la BD nunca pueden contradecir la frase de fecha que dijo el llamante.

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
- ✅ La cita creada por voz **hereda automáticamente todo el Seguimiento** del negocio, igual que una
  reserva web: **recordatorios 24 h / 2 h**, **llamada de confirmación por IA** (si está activa) y
  **petición de reseña** tras completarse. Los workers de recordatorios/reseña operan sobre **todas**
  las citas confirmadas sin filtrar por canal (`booking._bookings_due_for_reminders` /
  `_bookings_due_for_review` filtran por estado y fecha, no por `source`). El asistente **no** los
  envía a mano (no es una herramienta conversacional): el sistema los manda solo. No prometas un
  recordatorio que el negocio no tenga configurado.
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
  para no chocar con la "respuesta activa" del Realtime, que antes dejaba al asistente callado.) Este
  *latch* (esperar al `response.done` antes de pedir el `response.create` del resultado) está aplicado
  en **los tres canales**: puente de teléfono (`routers/voice_web.py`), widget (`widget/voice.js`) y
  **prueba del portal** (`app_ui/index.html`). El de la prueba del portal era el único que aún lanzaba
  el `response.create` de inmediato y dejaba al asistente mudo tras crear la cita (el cliente tenía que
  preguntar "¿la has creado?"); ya está corregido.
- ✅ El asistente **nunca debe anunciar una acción y callarse**: no puede terminar su turno diciendo
  "voy a crear la cita", "un momento" o "ahora la creo" **sin** llamar a la herramienta en ese mismo
  turno. O ejecuta la herramienta ya, o no lo anuncia. El cliente no debe tener que preguntar si la
  cita se ha creado.
- ✅ Si el asistente ya leyó los datos de la cita y preguntó "¿confirmas?" / "¿es correcto?", una
  respuesta afirmativa del cliente ("sí", "correcto", "vale", "adelante") **autoriza la reserva**:
  el prompt le indica que con ese "sí" basta para llamar a `crear_cita` sin volver a pedir
  confirmación ni quedarse en silencio. La red contra la doble creación no está en el diálogo sino
  en la tool: `create_booking_deduped` (firma teléfono/servicio/centro/fecha/hora por llamada)
  ignora una segunda creación idéntica dentro de la misma llamada.
- ✅ **Cerebro flexible — "modelo al mando + tools como guardarraíl" (jul 2026)**: se retiró el
  scripting determinista que peleaba con el modelo (cascada de `force_*`, frases verbatim,
  "no te he entendido" fijo, detección de anuncio-sin-tool). El prompt es orientado a objetivos y
  prohíbe las frases de espera; la **fiabilidad vive en las tools**: dedup de reserva, verificación
  de identidad en cancelar/reprogramar, y `consultar_disponibilidad` como única fuente de horas.
  Lo determinista que queda es técnico: barge-in, latch de respuesta activa, cancelación de
  respuesta muda y UN empujón interno anti-silencio.
- ✅ **Contrato anti-silencio (los tres canales)**: watchdog de ~1,7 s tras saludo, turno del cliente o
  resultado de herramienta. Si el modelo se queda mudo (sin respuesta activa, sin audio/texto), el
  sistema inyecta **un empujón INTERNO** (`_nudge_continue` en el motor Twilio; `continueNudge` en
  navegador, texto compartido `voice_core.CONTINUE_NUDGE_TEXT`): un mensaje de sistema que recuerda
  el contexto + `response.create` con tool_choice libre. El modelo **reformula con sus palabras**
  (puede hablar o llamar a la herramienta que toque); nunca se le impone una frase fija de cara al
  cliente. Tras **>3 recuperaciones** sin respuesta: despedida cordial y colgado limpio.
- ✅ **Habla obligada tras tool mutante**: tras `crear_cita`, `cancelar_cita`, `reprogramar_cita`,
  `confirmar_cita`, `enviar_codigo_verificacion`, `enviar_enlace_pago`, `consultar_*`,
  `finalizar_llamada` o `transferir_a_humano` con mensaje, si el modelo se queda mudo el sistema
  fuerza que diga el resultado (`speak_forced_tool_result`): guía NATURAL —"di el resultado con tus
  palabras manteniendo exactos horas, fechas, precios y número de reserva"—, no verbatim. La llamada
  no depende de que el cliente diga "contesta" para oír el resultado final.
- ✅ **Paridad teléfono/navegador**: el mismo contrato de tools, latch post-tool, `needs_service`,
  `needs_location`, empujón interno anti-silencio y colgado limpio tras `finalizar_llamada` debe
  existir en Twilio (motor `backend/voice_engine.py` + puente `backend/routers/voice_web.py`),
  widget público (`widget/voice.js` sobre `widget/voice_core.js`) y prueba del portal
  (`app_ui/index.html` vía `window.VanteliaVoiceCore`). Una mejora de voz no se considera completa
  si solo funciona en uno de los canales.
- ✅ **Respuesta activa muda / STT incoherente**: si Realtime deja una respuesta activa sin emitir audio,
  el puente no la corta en el margen corto del watchdog; espera una ventana de gracia (`ACTIVE_RESPONSE_GRACE_MS`
  en navegador y `active_response_grace_seconds` en Twilio) y solo entonces la cancela como emergencia y deja
  que el watchdog dé el empujón interno. Si la transcripción del cliente es claramente basura o incoherente para una respuesta
  ("Subtítulos realizados por la comunidad de Amara", "Y alas", "Diosos mios"), el asistente no debe interpretarla
  como intención real: pide repetir en una frase breve y continúa sincronizado con la agenda.
- ✅ **Una sola voz activa sin cortes**: ninguna recuperación anti-silencio puede lanzar una respuesta nueva encima
  de otra respuesta activa. Si la respuesta activa lleva demasiado tiempo muda, primero se envía `response.cancel`,
  se vacía el audio pendiente de Twilio si lo hay y se espera `response.done` (o un timeout corto controlado) antes
  de forzar otra frase. El widget y la prueba del panel mantienen la misma compuerta con `responseCancelPending`.

### 3.13 Registro y trazabilidad

- ✅ Toda llamada/sesión **debe registrarse** (`voice_calls`: dirección, propósito, duración,
  transcripción y resumen) y ser visible en **Conversaciones** del portal.
- ✅ Cada acción sobre la cita (crear/cancelar/reprogramar/confirmar/pago) **debe quedar
  auditada** en `booking_audit`.
- ✅ El asistente **etiqueta el resultado** de cada llamada telefónica para informes:
  `voice_calls.outcome` (reservada / confirmada / cancelada / reprogramada / transferida /
  vacío = sin acción), sellado por el motor según avanza la llamada y guardado en
  `_voice_finalize_call`. `GET /admin/voice/calls` expone `by_outcome` + `total` en stats.

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
**Seguimiento automático heredado** (recordatorios 24 h/2 h, llamada de confirmación y reseña sobre la
cita de voz, sin acción del asistente), cobro por enlace, habla natural con fechas/horas en español,
**saludo e identidad desde Apariencia**
(bienvenida verbatim + nombre del bot / nombre del negocio), idioma de transcripción fijado,
**conocimiento del horario** del negocio (días/horas de apertura y días cerrados; no ofrece días
cerrados) y exige día concreto + herramienta antes de hablar de disponibilidad, el asistente **habla el
resultado de la herramienta de inmediato** (sin quedarse mudo, en los tres canales incluida la prueba
del portal) y **no anuncia acciones sin ejecutarlas**, **transferencia a humano** (desvío real por
teléfono, número dictado en navegador) y **colgado limpio** (`finalizar_llamada` en los tres canales +
despedida automática tras silencio prolongado), **etiquetado de resultado** de llamada
(`voice_calls.outcome` + `by_outcome` en stats), **cerebro flexible** (modelo al mando, fiabilidad en
las tools: dedup de reserva, verificación, disponibilidad como única fuente de horas), **motor
determinista en una sola copia por runtime** (`backend/voice_engine.py` testeado en
`tests/test_voice_engine.py`; `widget/voice_core.js` compartido widget/portal), registro en
Conversaciones con transcripción y resumen.

**Brechas priorizadas (propuesto):**

1. 🟡 **Detección de buzón de voz** en salientes + 🔵 reintentos controlados.
2. 🔵 **Aviso de grabación/RGPD** y política de retención de transcripciones.
3. 🔵 **Lista de espera** cuando no hay hueco.
4. 🟡 **Tope/alerta de gasto** por tenant.
5. 🔵 **Idioma configurable** por tenant/centro.
6. 🟡 **Reflejar cambios de catálogo/identidad a mitad de llamada** (hoy aplican en la siguiente).
7. ✅ ~~Outcome también en llamadas de navegador~~ — hecho: el front (widget y prueba del
   portal) acumula el resultado según las tools ejecutadas y `/log` lo persiste validado
   (`voice_calls.outcome`), con paridad con el motor de teléfono.
8. 🟡 **Harness QA sobre el motor real**: `scripts/qa_voice_realtime_calls.py` (CallHarness)
   aún emula el puente antiguo (cascada `_force_*` retirada del motor). Pendiente rehacerlo
   sobre `VoiceCallEngine` (adaptador de eventos texto→audio + transporte real); requiere
   cuota Realtime para validar la migración.

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

## 8. QA Realtime obligatorio

Esta sección es la guía operativa para validar el asistente aunque no se tenga contexto previo de
la conversación de desarrollo. Las pruebas usan OpenAI Realtime en modo texto contra un tenant
temporal (`qa_voice_calls`) y tools reales sobre una base aislada en `temp`; no modifican producción.

### 8.1 Prerrequisitos

- `OPENAI_API_KEY` configurada y red disponible.
- Ejecutar desde la raíz del repo (`E:\Vantelia` en Windows).
- No lanzar estas pruebas en paralelo entre sí: cada script crea su propio entorno temporal, pero
  Realtime tiene variabilidad y es más fácil diagnosticar de uno en uno.

### 8.2 Comandos mínimos antes de desplegar

```powershell
python -m py_compile backend\voice.py backend\voice_engine.py backend\routers\voice_web.py backend\booking.py scripts\qa_voice_realtime_calls.py scripts\qa_voice_realtime_silence.py scripts\qa_voice_realtime_deep.py scripts\qa_voice_realtime_schedule.py
python -m pytest tests/test_voice_engine.py tests/test_api_smoke.py::test_mark_booking_confirmed_by_customer tests/test_api_smoke.py::test_voice_otp_lets_owner_verify_from_another_phone tests/test_api_smoke.py::test_voice_booking_tool_creates_real_booking -q
python scripts\qa_voice_realtime_silence.py
python scripts\qa_voice_realtime_calls.py
python scripts\qa_voice_realtime_deep.py
python scripts\qa_voice_realtime_schedule.py
```

Para cambios importantes en voz, repetir la profunda al menos dos veces:

```powershell
1..2 | ForEach-Object { python scripts\qa_voice_realtime_deep.py }
```

Antes de desplegar producción, el despliegue debe seguir pasando la suite completa:

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\deploy.ps1
```

### 8.3 Matriz que debe cubrir `scripts\qa_voice_realtime_calls.py`

- **Información general:** pregunta centros y precio/duración de masaje. No debe crear cita.
- **Reserva lunes a la una en Sede Centro:** debe llamar `consultar_disponibilidad`, corregir
  "lunes" a la fecha real del próximo lunes, crear con `crear_cita`, guardar `source='voice'` y
  hablar el código.
- **Domingo cerrado:** debe consultar y responder "cerrados" sin crear cita.
- **Fuera de horario:** debe responder "estamos cerrados" o equivalente y proponer horas reales.
- **Bloqueo/vacaciones:** debe mencionar el bloqueo real y no crear cita.
- **Servicio inexistente:** no acepta el servicio inventado; ofrece servicios reales del catálogo.
- **Hora ocupada:** no promete la hora; ofrece alternativas devueltas por la herramienta.
- **Cancelación con teléfono:** consulta cita, verifica teléfono/email si hace falta, cancela y
  deja la reserva en `status='cancelled'`.

### 8.4 Matriz que debe cubrir `scripts\qa_voice_realtime_deep.py`

- **Reserva completa:** disponibilidad → datos → confirmación del cliente → `crear_cita` →
  frase final hablada con "queda confirmada/reservada" y código `R-XXXXXX`.
- **Cancelación:** código de reserva → `consultar_cita` → verificación por teléfono/email →
  `cancelar_cita` → frase final hablada ("he cancelado la cita").
- **Reprogramación:** código → `consultar_cita` → nueva fecha/hora → `consultar_disponibilidad`
  → `reprogramar_cita` → BD actualizada y frase final hablada.
- **Llamada saliente de confirmación:** saludo saliente, cliente dice "sí" → marca `confirmed_at`
  y habla "queda confirmada" sin pedir código ni número de reserva.

### 8.5 Matriz que debe cubrir `scripts\qa_voice_realtime_schedule.py`

- **Cierres cambiados en Horarios:** si el cliente cierra lunes y miercoles desde el portal, la
  siguiente llamada debe responder "cerrados" o equivalente y no crear cita.
- **Domingos reabiertos:** si el cliente abre domingo desde el portal, la siguiente llamada debe
  consultar la fecha real y decir que hay hueco si la agenda esta libre.
- **Rango horario cambiado:** si Horarios pasa a abrir solo de 12:00 a 14:00, una peticion a las
  10:00 debe responder que esta cerrado o sin hueco, y una peticion a las 12:00 debe responder que
  hay hueco.
- **Bloqueo nuevo:** si el cliente crea un bloqueo desde Horarios para un profesional/sede, la
  siguiente llamada debe mencionar el bloqueo o motivo real, proponer alternativas y no crear cita.
- **Sincronizacion inmediata:** los cambios se aplican via endpoints del portal antes de llamar; el
  asistente debe respetarlos en la siguiente sesion sin reiniciar ni cambiar codigo.

### 8.6 Matriz que debe cubrir `scripts\qa_voice_realtime_silence.py`

- **Frase ambigua:** si el cliente dice algo sin contexto, el asistente responde en el turno y pide
  aclaración; no se queda mudo.
- **Reserva completa:** disponibilidad, datos y confirmación producen respuesta hablada en cada turno,
  incluida la frase final con código tras `crear_cita`.
- **Bloqueo de agenda:** ante un bloqueo nuevo de Horarios, responde el motivo/bloqueo y alternativas,
  no solo registra el resultado interno.
- **Servicio inexistente:** ofrece servicios reales del catálogo sin aceptar el inventado ni quedarse
  esperando.
- **Cancelación:** consulta y cancela; si el cliente insiste después, responde contextual ("ya está
  cancelada") en vez de un genérico sin sentido.
- **Métrica anti-silencio:** cualquier recuperación del watchdog debe quedar por debajo del umbral de
  tolerancia del script (`<= 2,2 s`, margen técnico sobre el objetivo funcional de 2 s).

### 8.7 Criterios de aprobado

- Cada resultado JSON debe tener `"ok": true` en todos los escenarios.
- `tool_calls` debe mostrar las herramientas esperadas; una cita no se considera creada,
  cancelada, reprogramada o confirmada si la tool/BD no lo confirma.
- No puede haber turnos de usuario sin respuesta nueva del asistente ni recuperaciones del watchdog
  por encima de 2,2 s en QA.
- No puede aparecer una frase de espera prohibida como "voy a comprobar", "un momento" o
  "voy a reservar" seguida de silencio o sin tool.
- Tras cada tool mutante (`crear_cita`, `cancelar_cita`, `reprogramar_cita`, `confirmar_cita`)
  debe haber una frase final hablada. Si una pasada aislada muestra variabilidad de transcripción
  pero la acción se ejecuta, repetir la profunda; si se repite, es bug y hay que reforzar el puente,
  no solo el prompt.
- En `qa_voice_realtime_schedule.py`, las frases de cerrado, hueco y bloqueo deben aparecer en la
  respuesta del asistente, no solo en el resultado interno de la herramienta.
- Si el script devuelve `OPENAI_API_KEY no configurada`, la prueba queda bloqueada, no aprobada.
- Si OpenAI devuelve `rate_limit_exceeded`, la prueba queda bloqueada por cuota y debe repetirse; no
  cuenta como aprobada funcional.

---

## 9. Anexo técnico (referencia)

**Configuración por tenant (`config.json` → `voice`):** `enabled`, `widget_enabled`,
`twilio_phone_number`, `transfer_number` (número para `transferir_a_humano`; vacío = la tool
no se ofrece), `vad_type` (`server_vad`/`semantic_vad`), `vad_eagerness`,
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
helpers de habla; `_voice_schedule_block` = bloque HORARIO del prompt),
`backend/voice_engine.py` (motor determinista de la llamada telefónica: clase `VoiceCallEngine`
con estado, anti-silencio, dedup de reserva, transferencia, colgado y etiquetado de outcome;
testeado en `tests/test_voice_engine.py` con transporte falso), `backend/routers/voice_web.py`
(puente fino Twilio + WS: solo transporta y delega en el motor), `backend/routers/portal_app.py`
(config y acciones de portal), `backend/routers/ui_pages.py` (widget/demo). Navegador:
`widget/voice_core.js` (funciones puras compartidas: unintelligible, guía de resultado de tool,
`CONTINUE_NUDGE_TEXT`), `widget/voice.js` (widget embebido) y la prueba del portal en
`app_ui/index.html` (consume `window.VanteliaVoiceCore`).

---

*Mantener este documento sincronizado cuando cambien las herramientas de voz, el gating por
plan o los flujos de verificación, salientes y cobro.*
