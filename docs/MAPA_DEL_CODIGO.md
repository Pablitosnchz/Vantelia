# Mapa del código: dónde tocar cada cosa

Guía de navegación para llegar rápido al sitio correcto sin leerse el backend
entero. `docs/ARQUITECTURA.md` explica cómo está organizado el proyecto; esto
responde a otra pregunta: **"quiero cambiar X, ¿qué abro?"**.

Todas las rutas son `backend/` salvo que se diga otra cosa.

1. [Una cita, de principio a fin](#1-una-cita-de-principio-a-fin) — crear, cancelar, reprogramar
2. [Qué mensajes recibe el cliente](#2-qué-mensajes-recibe-el-cliente-y-desde-dónde) — y desde dónde
3. [Horarios, huecos y disponibilidad](#3-horarios-huecos-y-disponibilidad)
4. [Catálogo de servicios](#4-catálogo-de-servicios)
5. [Cobros](#5-cobros) — señal, retención, mostrador
6. [Qué responde el asistente, y en qué orden](#6-qué-responde-el-asistente-y-en-qué-orden)
7. [Config del tenant](#7-config-del-tenant)
8. [Cómo probar sin molestar a nadie](#8-cómo-probar-sin-molestar-a-nadie)
9. [Textos: cuándo llevan tilde y cuándo no](#9-textos-cuándo-llevan-tilde-y-cuándo-no)
10. [Higiene: antes de dar algo por terminado](#10-higiene-antes-de-dar-algo-por-terminado)

---

## 1. Una cita, de principio a fin

Los cuatro canales terminan en la MISMA función. Si añades un canal nuevo,
llámala; no reimplementes el pipeline.

| Qué pasa | Entrada del canal | Núcleo común |
| --- | --- | --- |
| Reservar por web/widget | `routers/public_booking.py` → `agendar` (`POST /agendar`) | `booking._create_booking_core` |
| Reservar por WhatsApp | `whatsapp._handle_whatsapp_message` → `_wa_create_booking` | idem |
| Reservar por voz | `voice._voice_dispatch_tool` | idem |
| Reservar desde el panel | `routers/portal_app.py` (`POST /auth/bookings`) | idem |
| Cancelar (cualquier canal) | — | `booking._cancel_booking_core` |
| Reprogramar / editar | — | `booking._update_booking_details` |
| Confirmar asistencia | — | `booking._mark_booking_confirmed_by_customer` |

El canal solo decide **su política de entrada** (qué profesional, qué textos) y
traduce los `HTTPException` a su medio.

**Trampa**: `_create_booking_core(send_confirmation=False)` lo usan WhatsApp y voz
porque confirman ellos en su propio canal. Si lo pones a True en esos, el cliente
recibe la confirmación dos veces.

---

## 2. Qué mensajes recibe el cliente, y desde dónde

Todo aviso de cita sale de **un solo punto**: `booking._send_booking_reminder_by_kind(booking_row, kind)`
con `kind` ∈ `pending_payment | confirmed | cancelled | rescheduled | reminder_24h | reminder_2h`.

```
_send_booking_reminder_by_kind
├── ¿el negocio tiene ese aviso activado?      _booking_email_enabled  (config booking.message_template_enabled)
├── ¿por qué canales?                          agenda._effective_followup_channels  (Seguimiento)
├── ¿esos canales llegan a ESTE cliente?       _channels_reaching_customer
└── por canal:
    ├── email     → _send_booking_email        → _booking_email_bodies   (texto + HTML)
    ├── whatsapp  → _send_booking_whatsapp_reminder   (todo en corto: WA_NOTICE_KINDS)
    │                 ├── confirmed/rescheduled → _whatsapp_notice_text + botón "Gestionar cita"
    │                 ├── cancelled             → _whatsapp_notice_text (sin botón: la cita ya no existe)
    │                 ├── reminder_24h/2h       → _whatsapp_notice_text + botones Confirmo/Cancelar
    │                 └── resto                 → _booking_message_text_for_channel (= el texto del email)
    └── sms       → _send_booking_sms_reminder → también el texto del email
```

**Para cambiar el texto de un aviso:**

- Email y SMS → `_booking_email_bodies`.
- WhatsApp (confirmada / cambiada / cancelada / los dos recordatorios) →
  `_whatsapp_notice_text`. La lista de los que cubre es `booking.WA_NOTICE_KINDS`.
- Plantilla que el negocio puede editar → `settings.DEFAULT_MESSAGE_TEMPLATES`
  y la pestaña Mensajes del panel (`MSG_TEMPLATES` en `app_ui/index.html`).
- Aviso propio de un servicio ("ven con el pelo lavado") → columna
  `services.booking_note`, leída por `booking.service_booking_note`.

**Regla de entrega** (`_channels_reaching_customer`): manda lo que el negocio
configure en Seguimiento; si con eso no se alcanza al cliente (p. ej. reservó por
WhatsApp y no dio email), se **añade** el canal por el que él escribió. Nunca se
apaga un canal elegido, para que el panel pueda explicar por qué no se entregó.

**Trampa**: un aviso por WhatsApp fuera de la ventana de 24 h de Meta necesita
plantilla aprobada, que no soportamos. El recordatorio de 24 h a un cliente sin
email normalmente NO llega.

---

## 3. Horarios, huecos y disponibilidad

| Pregunta | Función |
| --- | --- |
| ¿Qué huecos hay ese día? | `agenda._build_slots_for_day` (la usan todos los canales) |
| ¿Cuál es el horario semanal real? | `agenda._weekly_schedule_matrix` (fuente única de los prompts de chat y voz) |
| ¿Cabe este servicio en ese hueco? | `agenda._service_duration_minutes` + `_booked_intervals` |
| ¿Está bloqueado ese día? | tabla `agenda_blocks` (`employee_id` vacío = todo el equipo) |

El horario por día de la semana vive en `employees.weekly_hours_json` y en
`config['booking']['weekly_hours']`; resuelve `textnorm._weekday_hours`.

**Trampa**: el descanso del horario GENERAL cierra la agenda de todo el equipo.
Los descansos por profesional se suman al general.

---

## 4. Catálogo de servicios

- Tabla `services`, PK `(cliente_id, slug)`. El slug se mantiene al renombrar.
- Serializador único: `agenda._service_row_to_public` (de ahí salen panel,
  widget, central y WhatsApp). **Si añades una columna, tócalo ahí** y en
  `ServicePublic` / `ServicePayload` / `ServiceUpdatePayload` de `api_models.py`
  y en el alta/edición de `routers/public_booking.py`.
- `category` agrupa el catálogo. Vacía = sin agrupar, y entonces todas las
  pantallas se ven como antes.
- Importar el Excel de un salón: `scripts/importar_catalogo_excel.py`.

**Trampa grave**: `agenda._sync_services_from_info(..., deactivate_missing=True)`
DESACTIVA todo servicio que no aparezca en el `info.txt`. Solo debe usarse al dar
de alta un tenant nuevo. Se llamaba al guardar la ficha admin y borró el catálogo
de un cliente real (183 servicios → 8).

**Trampa**: `_extract_services_from_info(cliente_id)` lee el `info.txt` **del
disco**, no el texto que le pases. Y solo reconoce el bloque que empieza por
`SERVICIOS Y PRECIOS` con líneas `- Servicio:` / `- Precio:` / `- Duracion:`.

---

## 5. Cobros

| Qué | Dónde |
| --- | --- |
| ¿Este servicio exige pago? | `booking.resolve_payment_requirement` |
| Crear el checkout | `booking.create_booking_payment_checkout` |
| El pago entra | `booking.process_booking_payment_webhook` → `notify_booking_paid` |
| Estado de cobro de una cita | `backend/paystate.py` (fuente única: suma `booking_payments` + `customer_payments`) |
| Explicar señal / retención | `booking.payment_prompt_note`, `paystate.checkout_line` |
| Enlace corto de pago | `booking.build_booking_payment_url` → ruta `GET /p/{manage_token}` |

Hay **dos** sistemas de pago (`booking_payments` para la reserva y
`customer_payments` con `kind='pos'` para el mostrador). Mirar solo uno hace que
el saldo mienta: por eso existe `paystate`.

**Trampa**: sin Stripe operativo, `resolve_payment_requirement` devuelve "no
disponible" y la cita se confirma SIN pedir la señal, aunque el servicio la tenga
configurada.

**Trampa**: el checkout no enumera `payment_method_types` a propósito. Si alguien
los enumera, desaparece Bizum.

---

## 6. Qué responde el asistente, y en qué orden

`chat._process_chat_message`, de más literal a más libre:

1. Saludo puro → menú (`config['chat_menu']['enabled']`).
2. **Reglas por palabra clave** (`keywords.match_reply`, tabla `keyword_rules`).
3. **Q&A exactas** (`rag._match_qa_answer`, tabla `kb_qa`): casan por pregunta casi
   idéntica o por **etiqueta** (palabra completa, mínimo 5 caracteres, gana la más larga).
4. **Comprensión + reglas del negocio** (`intents.classify` + `rules.match`,
   opt-in `config['ai_intents']['enabled']`). Ver más abajo.
5. Disponibilidad, gestión de cita, pago.
6. RAG / IA.

**Regla de diseño**: lo que el negocio escribe a mano manda sobre nuestras
heurísticas. Las Q&A estaban DESPUÉS de la disponibilidad y "¿cuál es vuestro
horario?" devolvía los huecos libres de hoy.

### La capa 4: entender en vez de adivinar

**El problema medido**: la intención se adivinaba con expresiones regulares. De 19
formas naturales de pedir cita se reconocían **dos**. "me pones una cita?",
"resérvame el jueves" o "hazme un hueco" no abrían el formulario, y cada variante
nueva era un parche más. Con el modelo clasificando, medido contra un asistente
real en producción: **18 de 19** (14 abren el formulario, 4 contestan con huecos).

* `backend/intents.py` — qué quiere el cliente. `atajo_local()` resuelve gratis lo
  evidente; si no, una llamada a `gpt-4o-mini` devuelve `{intencion, familia,
  pregunta, confianza}`. Las **familias** salen del catálogo del propio tenant
  (`familias_del_tenant`), no de una lista fija. `pregunta` es cuál de **las Q&A
  del negocio** le están haciendo, aunque la escriba con otras palabras: eso
  convierte las etiquetas escritas a mano en algo que ya no hace falta mantener.
* `backend/rules.py` — qué hacer con eso. Tabla `business_rules`, gana la primera
  activa por `prioridad`. Una regla con `familias` solo vale para esos servicios.

**Lo que nunca puede pasar**: que entender deje a alguien sin respuesta. Si el
modelo falla, tarda o no llega al umbral (`CONFIANZA_MINIMA`), `classify` devuelve
`None` y el chat sigue exactamente por donde iba.

**Trampas ya pagadas**:

* Con una gestión a medias **no se clasifica**. Quien está cancelando y responde
  "el jueves a las 5" no está pidiendo una cita nueva; clasificarlo le abría el
  formulario y perdía el hilo.
* `familia` vacía no puede casar una regla que exige familia (`"" in "alisado"` es
  `True` en Python): un "¿cuánto cuesta?" a secas pedía la foto del alisado.
* Las intenciones que se ACTÚAN (reservar, cancelar, reprogramar) se saltan la
  Q&A parafraseada: el salón tenía una Q&A de "cómo reservar" y "me pones una
  cita?" acababa explicándole cómo hacerlo en vez de abrirle el formulario.
* La intención `disponibilidad` enruta a `_build_chat_availability_answer`. Sin
  eso, "¿puedo ir mañana?" caía en la IA genérica y contestaba el horario de
  apertura, no si quedaba hueco.
* Una regla de precios **sin familias** tapa el catálogo entero. Si el negocio ya
  tiene precios cerrados para corte o peinado, acota la regla a los servicios que
  de verdad necesitan valoración.
* El interruptor del panel lee `config_enabled` (lo que el negocio guardó), no
  `enabled_for` (que además exige clave de OpenAI): si no, se apagaba solo.

**Lo que el negocio configura sale de UNA funcion: `chat.decision_del_negocio`.**
Sus Q&A escritas, la comprension de intenciones, sus Q&A reconocidas con otras
palabras y sus reglas. La llaman el chat web y WhatsApp **en la misma posicion**:
despues de las palabras clave y antes de cualquier heuristica nuestra. El canal
solo traduce la decision a su medio (el widget devuelve `mostrar_formulario`,
WhatsApp arranca su flujo guiado).

**Probar en el widget NO demuestra nada sobre WhatsApp.** WhatsApp tiene su propio
recorrido y solo delegaba en el cerebro al final; todo lo que respondia antes se
comportaba distinto. Divergencias reales que costo encontrar:

* "horarios" devolvia los huecos del dia en WhatsApp y el horario redactado por
  el negocio en la web.
* Una regla del negocio sobre cancelar no llegaba a aplicarse: el disparador de
  WhatsApp iba primero.
* "quiero pedir cita" no lo reconocia: eran cinco frases exactas.
* El "Gracias a ti" faltaba en las ramas propias de WhatsApp.
* Se prometia "Te muestro el formulario" donde no hay formulario.

Al tocar cualquiera de esas capas, `tests/test_whatsapp_mismo_cerebro.py` compara
los dos canales con el webhook de verdad.

**Trampa**: una rama de WhatsApp que responde por su cuenta tiene que registrar la
conversacion (`_wa_registrar`) o el negocio pierde ese chat en el panel. Paso al
unificar el detector de reserva; lo vigila `test_whatsapp_webhook_uses_same_chat_storage`.

WhatsApp comparte cerebro pero tiene su propio flujo guiado en `whatsapp.py`.

**El cliente nunca puede quedarse encerrado en un paso.** Cada paso del flujo
guiado (`whatsapp.py`, ramas `if flow.flow == ...`) respondía "no he reconocido X"
y volvía. Una persona preguntando "¿puedo ir con niños?" en el paso de
profesional recibía cinco veces el mismo muro, y ni "hola" la sacaba: la guarda
`not flow.flow` protegía el flujo de todo. Las tres reglas de ahora:

1. Un saludo o "menu" **siempre** salen del flujo, haya el paso que haya.
2. Lo que no encaja en el paso pasa por `_wa_atender_duda_sin_perder_el_paso`:
   si parece una duda, se responde con el cerebro y **se retoma el paso**; si es
   un intento fallido de elegir (un número suelto, basura), el aviso corto.
3. Un paso a medias **caduca** (`WHATSAPP_FLOW_TTL_MINUTES`, 120 por defecto).
   Quien abandona y vuelve al día siguiente empieza limpio, y el diccionario de
   flujos deja de crecer sin fin.

Al añadir un paso nuevo, no escribas un `_send_whatsapp_text` con "no he
reconocido": usa el helper. Lo vigila `tests/test_wa_usuario_erratico.py`, que
simula usuarios que no siguen el guion.

**El menú lo decide el negocio, no nosotros.** Las opciones salen de
`chat.menu_entries` (→ "Preguntas sugeridas" del panel: 3 fijas + hasta 5
propias), y esa función es la fuente única del chat web y de WhatsApp. Cada canal
añadía las suyas por su cuenta: el mismo salón veía 3 opciones en su panel, 4 en
el chat y 6 en WhatsApp. Si añades una opción "útil" en un canal, rompes eso.
Una fila cuyo texto coincide con una acción conocida (`whatsapp._WA_MENU_ACCIONES`)
abre su flujo guiado; el resto viaja como texto a la IA.

**Trampa**: los títulos de fila de WhatsApp son **24 caracteres** y las
descripciones 72. Recortar por el final convertía "Keratina premium corto chico"
en "Keratina premium corto c" — igual que el recorte de "corto medio", y
confundible con "Keratina premium corto", que existía. `_wa_recortar_titulo`
recorta por el MEDIO (lo que distingue suele ir al final) y el nombre completo
viaja en la descripción. El **guion separa palabras** igual que el
espacio: sin eso, "Acido lactico bio premium-largo" y "…premium-medio" se veían
IDÉNTICOS en la lista (260 € y 205 €), porque la cola solo se conservaba si la
última palabra cabía en la mitad del ancho. Cuando dos nombres siguen chocando
(«extra largo» vs «extra extra largo»), la descripción lleva nombre completo,
duración y precio: es lo que permite distinguirlos.

**Trampa**: una lista de WhatsApp admite **10 filas**. Con catálogos grandes,
`_wa_send_service_picker` pregunta primero la categoría y pagina con "Ver más".
Cualquier selector nuevo tiene el mismo techo.

---

## 7. Config del tenant

- `config.json` es la fuente de verdad, pero **en runtime manda
  `appstate.CONFIG_CLIENTES`**. Escribir el fichero a mano desde otro proceso no
  sirve: el uvicorn vivo lo reescribe con su copia en memoria.
- Para cambiarla de verdad: la API (`PUT /admin/clientes/{id}` o los
  `/auth/app/...` del portal).
- **Secciones nuevas hay que registrarlas en `clients.CONFIG_EXTRA_SECTIONS`** o se
  descartan en silencio en cada arranque.

---

## 8. Cómo probar sin molestar a nadie

- Suite: `python -m pytest` (unos 10 min). **Que corre cada fichero y cual toca
  segun lo que cambies: `tests/README.md`.**
- Portal de un cliente sin su contraseña: `POST /admin/clientes/{id}/impersonate`
  con el token admin devuelve una cookie de sesión del portal.
- Flujo de WhatsApp sin enviar mensajes: sustituir
  `messaging._send_whatsapp_text` / `_send_whatsapp_list` / `_send_whatsapp_buttons` /
  `_send_whatsapp_cta_url` por capturas y llamar a `whatsapp._handle_whatsapp_message`.
- Panel real en producción: Playwright + la cookie de impersonación.

Los scripts de QA, que son a la vez el ejemplo de cómo se hace cada cosa:

| Script | Qué hace | Cuidado |
| --- | --- | --- |
| `scripts/qa_e2e.py` | Recorre el portal entero como un cliente real, en un entorno aislado | Sale con 1 si encuentra bugs |
| `scripts/qa_portal_browser.py` | El panel con Playwright | Necesita chromium |
| `scripts/qa_chat_realtime.py` | El chat contra el modelo de verdad | Cuesta céntimos |
| `scripts/qa_voice_realtime_*.py` | Voz contra Realtime | Gasta cuota; **siempre salen con 0**, hay que leer el `"ok"` del JSON |

---

## 9. Textos: cuándo llevan tilde y cuándo no

Dos clases de cadena en español que **se parecen y no se comportan igual**:

| Clase | Ejemplo | Tildes |
| --- | --- | --- |
| Texto que lee una persona | `"Guarda tu número de reserva"` | **sí** |
| Patrón que casa lo que ESCRIBE el cliente | `"pagar la senal"` en `_message_requests_payment` | **no** |

Los patrones se comparan contra el mensaje ya pasado por
`textnorm._strip_accents`, o sea sin tildes: un patrón acentuado no casa nunca,
y falla en silencio (sin error y sin log). Pasó de verdad al acentuar los textos
del asistente: se acentuó de paso la lista de frases de pago y quien pedía pagar
dejaba de recibir su enlace.

Lo vigila `tests/test_patrones_sin_tilde.py`: recorre el AST, busca funciones que
normalicen con `_strip_accents` y falla si alguno de sus literales de comparación
lleva tilde. Los textos de respuesta dentro de esas mismas funciones sí la llevan.

Caso aparte: `textnorm.DAY_LABELS_ES` (para mostrar) va **con** tilde;
`WEEKDAY_NAMES_ES` (para parsear) va **sin**.

**Para los prompts de voz (`voice.py`) no aplica**: esas cadenas son
instrucciones al modelo, no algo que nadie lea.

### Y el mojibake

Una tilde doblemente codificada (UTF-8 leído como latin-1 y vuelto a guardar) no
casa nada y se ve rota si se muestra. Estaba en cuatro patrones de intención
comercial, en un error del panel y en el manual de admin. Lo vigila el mismo
fichero de tests. La única excepción permitida es el comentario de
`voice._voice_date_phrase_key`, que ilustra lo que esa función repara en runtime
(los mensajes de WhatsApp llegan así a veces).

---

## 10. Higiene: antes de dar algo por terminado

```powershell
python -m pyflakes backend/ api.py    # imports y variables muertas
python -m pytest                      # ver tests/README.md
npm run build                         # solo si tocaste widget/
```

Tres cosas que `pyflakes` señala y **no** siempre son basura:

- **`backend/main.py`** importa módulos que "no usa": importarlos es lo que
  registra las rutas. El orden de esos imports es el orden de registro.
- **Re-exportaciones**: `outreach.py` e `instagram.py` importan nombres de
  `scripts/` que consumen sus routers (`from backend.outreach import ...`).
  Ambos bloques llevan un comentario avisando.
- **Variables que tapan un módulo**: un `for booking in rows:` deja el módulo
  `booking` inaccesible dentro del bucle. No falla hasta que alguien añade una
  línea que lo necesita. Nombra el local en español (`cita`, `fila`).

Y una que sí conviene mirar: **una variable asignada y nunca usada suele ser el
rastro de una cadena muerta**. `extra_message` (el motivo de cancelación) viajaba
por siete funciones hasta una que lo saneaba y lo tiraba, mientras la auditoría
seguía apuntando que se le había enviado al cliente.

## Nada construido y sin enchufar (26-ago-2026)

Cuatro veces en dos dias aparecio lo mismo: codigo escrito, probado a mano y
**desconectado**. No daba error -compilaba y los tests pasaban- y las cuatro se
encontraron por casualidad:

| Estaba escrito | Lo llamaba | Que costo |
| --- | --- | --- |
| `_work_intervals_of` (huecos de exposicion) | nadie | el panel pintaba los packs macizos: la tarde parecia ocupada |
| el campo `work_intervals` | declarado en el modelo equivocado | lo mismo |
| `_valoracion_en_lugar_del_tratamiento` | nadie | citas de 4 h a quien solo preguntaba el precio |
| `chat_model` / `temperature` del panel | nadie | quien pagaba un modelo mejor no lo tenia |

Lo vigila **`tests/test_nada_sin_enchufar.py`**: falla si una funcion del backend
no la llama nadie. No cuenta lo que llama el framework (endpoints, middlewares,
fixtures). Si te falla: o la enchufas donde iba, o la borras.

Ese mismo test comprueba que **solo hay UNA forma de normalizar texto**
(`textnorm.normalizar`); estaba copiada identica en `catalog_pick`, `intents` y
`rules`, que son tres sitios donde arreglar el mismo caso raro.

### Donde se decide cada cosa (una sola por fila)

| Decision | Quien la toma | Quien la llama |
| --- | --- | --- |
| Crear una cita | `booking._create_booking_core` | voz, WhatsApp, portal, widget |
| Cancelar | `booking._cancel_booking_core` | voz, admin, portal, publico |
| Que huecos hay | `agenda._public_slot_sets_for_day` | todos los canales |
| Que servicio es | `catalog_pick.elegir` | el agente |
| Que se contesta | `agent.responder` | chat y WhatsApp |

DEUDA CONOCIDA: los guardarrailes de conversacion (no repetirse, no dar por hecha
una cita, no inventarse una hora, el recargo, la valoracion) viven SOLO en
`agent.py`. La voz (`voice_engine.py`) no tiene ninguno.
