# Requisitos: horario, descansos, bloqueos y calendario

Contrato de producto del sistema de horarios de Vantelia (portal cliente + asistentes).
Actualizado: julio 2026 (overlay de descanso general).

## 1. Modelo de datos

| Concepto | Donde vive | Alcance | Recurrencia |
| --- | --- | --- | --- |
| Horario general | `config.json` → `booking` (day_start/day_end, slot_minutes, timezone, closed_weekdays, break_windows) | Negocio; sincronizado con el empleado `is_default=1` ("Agenda general") | Semanal fija |
| Horario por profesional | Tabla `employees` (mismas columnas) | Un profesional | Semanal fija |
| Descanso diario (break) | `break_windows` (lista `{start, end, reason}`) en config y/o en el empleado | Ver semantica abajo | Todos los dias laborables |
| Bloqueo de agenda | Tabla `agenda_blocks` (fecha o rango de fechas + horas; `employee_id=''` = general) | Negocio entero o un profesional | Puntual (vacaciones, festivos, ausencias, formacion) |

- Un bloqueo sin horas (00:00–23:59) = dia completo. Un rango de fechas crea una fila por dia (max 366).
- Los descansos NO tienen dia de la semana: aplican cada dia laborable. Para una excepcion puntual se usa un bloqueo.

## 2. Semantica (reglas de negocio)

1. **Descanso general = cierre del negocio.** Un `break_window` del horario general (p. ej. parada de comida 14:30–16:00) cierra la agenda de **todo el equipo**, ademas de los descansos propios de cada profesional (`agenda._client_break_windows` + union en `_build_slots_for_day`). Para descansos escalonados por persona: dejar el general vacio y configurarlos por profesional.
2. **Descanso por profesional** solo afecta a ese profesional. Se SUMA al general, no lo sustituye.
3. **Bloqueo general (`employee_id=''`)** afecta a todos los profesionales (`_blocked_intervals` con `include_general=True`).
4. **Bloqueo por profesional** solo a el.
5. **El horario general (day_start/day_end/dias cerrados) NO pisa el de los profesionales**: cada profesional tiene su propio horario semanal; el general gobierna la "Agenda general" y sirve de plantilla al crear empleados nuevos (`_employee_defaults_for_client`). Excepcion: los descansos generales, que si aplican a todos (regla 1).
6. **Dia cerrado del negocio** (matriz semanal): un dia esta cerrado solo si NINGUN profesional activo trabaja ese dia (`agenda._weekly_schedule_matrix`).

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

## 9. Caso de referencia: The Nook Madrid (jul 2026)

Parada de comida del negocio 14:30–16:00 configurada como descanso GENERAL (`config['thenook']['booking']['break_windows']` + agenda default sincronizada). Efecto: banda "Comida" en las columnas de los 8 profesionales de los 3 centros, sin huecos 14:30–15:30 en ningun canal, y chat/voz avisan del cierre de mediodia. Requiere deploy de config + codigo en el VPS para produccion.
