# Requisitos: horario, descansos, bloqueos y calendario

Contrato de producto del sistema de horarios de Vantelia (portal cliente + asistentes).
Actualizado: agosto 2026 (horario por dia de la semana).

## 1. Modelo de datos

| Concepto | Donde vive | Alcance | Recurrencia |
| --- | --- | --- | --- |
| Horario general | `config.json` → `booking` (day_start/day_end, slot_minutes, timezone, closed_weekdays, break_windows) | Negocio; sincronizado con el empleado `is_default=1` ("Agenda general") | Semanal fija |
| Horario por profesional | Tabla `employees` (mismas columnas) | Un profesional | Semanal fija |
| Horario por DIA de la semana (`weekly_hours`) | `config.json` → `booking.weekly_hours` y columna `employees.weekly_hours_json` | Negocio o un profesional | Override por dia sobre la franja general |
| Descanso diario (break) | `break_windows` (lista `{start, end, reason}`) en config y/o en el empleado | Ver semantica abajo | Todos los dias laborables |
| Bloqueo de agenda | Tabla `agenda_blocks` (fecha o rango de fechas + horas; `employee_id=''` = general) | Negocio entero o un profesional | Puntual (vacaciones, festivos, ausencias, formacion) |

- Un bloqueo sin horas (00:00–23:59) = dia completo. Un rango de fechas crea una fila por dia (max 366).
- Los descansos NO tienen dia de la semana: aplican cada dia laborable. Para una excepcion puntual se usa un bloqueo.
- `weekly_hours` es un dict `{"0".. "6"}` (lunes=0) con `{closed, start, end}`. Los dias que NO aparecen usan `day_start`/`day_end` + `closed_weekdays`. Vacio `{}` = comportamiento clasico de una sola franja.

## 2. Semantica (reglas de negocio)

1. **Descanso general = cierre del negocio.** Un `break_window` del horario general (p. ej. parada de comida 14:30–16:00) cierra la agenda de **todo el equipo**, ademas de los descansos propios de cada profesional (`agenda._client_break_windows` + union en `_build_slots_for_day`). Para descansos escalonados por persona: dejar el general vacio y configurarlos por profesional.
2. **Descanso por profesional** solo afecta a ese profesional. Se SUMA al general, no lo sustituye.
3. **Bloqueo general (`employee_id=''`)** afecta a todos los profesionales (`_blocked_intervals` con `include_general=True`).
4. **Bloqueo por profesional** solo a el.
5. **El horario general (day_start/day_end/dias cerrados) NO pisa el de los profesionales**: cada profesional tiene su propio horario semanal; el general gobierna la "Agenda general" y sirve de plantilla al crear empleados nuevos (`_employee_defaults_for_client`). Excepcion: los descansos generales, que si aplican a todos (regla 1).
6. **Dia cerrado del negocio** (matriz semanal): un dia esta cerrado solo si NINGUN profesional activo trabaja ese dia (`agenda._weekly_schedule_matrix`).
7. **Horario distinto segun el dia** (`weekly_hours`, opt-in): resuelve los negocios que no abren la misma franja todos los dias (sabado corto, tarde larga solo dos dias). Fuente unica `textnorm._weekday_hours(schedule, weekday)`, consumida por `_build_slots_for_day` (todos los canales) y por `_weekly_schedule_matrix` (prompts de chat y voz), asi que la agenda y lo que cuenta el asistente no pueden divergir. El empleado `is_default=1` hereda el `weekly_hours` del negocio en cada arranque (`_ensure_default_employees_for_all_clients`). UI: bloque "Horario distinto segun el dia" en la pestana Horarios del portal, tanto para el horario general como por profesional.

## 3. Validacion al guardar (conflictos)

Guardar horario/descanso/bloqueo que pisa citas activas futuras devuelve **409** con la lista de citas (`schedule_booking_conflicts`); el portal abre el modal de conflictos (reprogramar / cancelar / ver dia) y reintenta el guardado al resolver.

- Descanso general → valida contra las citas de **todos** los profesionales (`_booking_conflicts_for_break_windows(employee_id="")`).
- Descanso/horario/dia cerrado de un profesional → valida contra sus citas.
- Bloqueo → valida contra las citas del alcance (general = todas, profesional = suyas).

## 4. Disponibilidad (fuente unica, todos los canales)

`agenda._build_slots_for_day` genera el grid del profesional (paso = slot_minutes; el servicio de N min debe caber entero) y excluye: fuera de day_start/day_end, dia cerrado, descansos del profesional + descansos generales, y horas pasadas. Encima, `_employee_slot_sets_for_day` / `_booking_slot_available` restan citas activas, bloqueos (propios + generales) y aforo por salas.

Consumidores (todos pasan por estas funciones — un descanso o bloqueo gatea SIEMPRE):

- Widget web y portal: `GET /disponibilidad`, `POST /agendar`, `POST /auth/bookings` (alta manual), reprogramaciones.
- Chat web: intent de disponibilidad (`_public_slot_sets_for_day`) + flujo de reserva.
- WhatsApp: pickers del flujo guiado (`_employee_slot_sets_for_day`).
- Voz (telefono y widget): tool `consultar_disponibilidad` + validacion en `crear_cita`/reprogramar (`_booking_slot_available`).
- Alternativas al fallar una reprogramacion (`booking._reschedule_failure_text`, compartido chat/WhatsApp): huecos REALES del profesional de la cita (descuenta citas y bloqueos, excluye la propia cita).

## 5. Conocimiento del asistente (prompt)

- Chat (`rag._build_system_prompt`) y voz (`voice._voice_schedule_block`) llevan el HORARIO SEMANAL REAL (matriz derivada de los profesionales) **+ linea "Cierre diario (motivo): de X a Y no se dan citas"** por cada descanso general.
- Los descansos POR profesional y los bloqueos puntuales NO van al prompt: los refleja la disponibilidad (la verdad de huecos siempre es la tool/endpoint, el prompt solo evita que el modelo ofrezca de palabra un tramo cerrado del negocio).

## 6. Visibilidad en el calendario del portal (pestana Citas)

| Vista | Descansos | Bloqueos | Dias cerrados |
| --- | --- | --- | --- |
| Dia (columnas por profesional) | Banda gris por columna: los del profesional + los generales (dedupe por tramo) | Banda con motivo: generales (todas las columnas) + del profesional | Columna entera "No disponible" |
| Semana/rango sin filtro de profesional | Los del horario general | Los generales | Segun horario general |
| Semana/rango con profesional filtrado | Los suyos + generales | Los suyos + generales | Los suyos |
| Mes | No se pintan (recurrencia diaria = ruido) | Tag con motivo en el dia (generales; con filtro de profesional tambien los suyos via `include_general`) | Celda "Cerrado" |

- Click en hueco vacio de la vista Dia prefija fecha/hora/profesional en "+ Nueva cita".
- Pestana Horarios: selector "Horario general" / profesional; editor de descansos (lista + añadir con motivo) y de bloqueos (rango fechas + horas + motivo). Con profesional seleccionado, los bloqueos generales aparecen con tag "Todo el negocio".

## 7. Endpoints

- `GET/POST /auth/schedule` — horario general (POST sincroniza el empleado default y valida conflictos).
- `GET/POST /auth/schedule/employee/{id}` — horario del profesional (el GET incluye bloqueos generales ademas de los suyos).
- `POST /auth/schedule/blocks` / `DELETE /auth/schedule/blocks/{id}` — bloqueos generales.
- `POST /auth/employees/{id}/blocks` / `DELETE /auth/employees/{id}/blocks/{block_id}` — bloqueos por profesional.
- `GET /auth/employees` — incluye horario, descansos y bloqueos propios de cada profesional (los usa la vista Dia).

## 8. QA minima al tocar horarios

```powershell
python -m pytest tests/test_booking_exhaustive.py -k "break or block or closed or general"
python -m pytest tests/test_api_smoke.py -k "schedule or reschedule"
```

Cobertura clave en `tests/test_booking_exhaustive.py`: dias cerrados, fuera de horario, bloqueos (dia completo/parcial/reserva rechazada), descansos por profesional (simples/multiples/servicio largo), **descanso general aplica a todo el equipo + 409 al guardar si pisa citas de cualquier profesional + bloqueos generales en el endpoint del profesional**.

## 9. Caso de referencia: Alicia Rincon Estilistas (ago 2026)

Peluqueria de Elche con horario distinto por dia: lunes y domingo cerrados, martes y miercoles 10:00-18:30, jueves y viernes 10:00-20:30 y sabado corto 09:00-14:00. Es el caso que motivo `weekly_hours`: con una sola franja, la agenda ofrecia huecos inexistentes (sabado por la tarde) y el asistente contaba un horario falso. Config en `config['aliciarincon']['booking']['weekly_hours']` + los 6 profesionales con el mismo override. Verificacion rapida: un servicio de 180 min no puede empezar despues de las 11:00 el sabado ni despues de las 15:30 el martes. Tests en `tests/test_weekly_hours.py`.

Caso previo (jul 2026, The Nook Madrid, tenant ya eliminado): la parada de comida del negocio 14:30-16:00 como descanso GENERAL cerraba la agenda de todo el equipo en todos los canales. La regla sigue vigente aunque el tenant no exista.
