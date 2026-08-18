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
4. Disponibilidad, gestión de cita, pago.
5. RAG / IA.

**Regla de diseño**: lo que el negocio escribe a mano manda sobre nuestras
heurísticas. Las Q&A estaban DESPUÉS de la disponibilidad y "¿cuál es vuestro
horario?" devolvía los huecos libres de hoy.

WhatsApp comparte cerebro pero tiene su propio flujo guiado en `whatsapp.py`.

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
