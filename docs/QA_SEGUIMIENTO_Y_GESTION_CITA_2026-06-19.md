# QA manual — Seguimiento del cliente y gestión de cita (2026-06-19)

Guía rápida para probar a mano, en un entorno aislado y **sin enviar mensajes
reales**, la escalera de Seguimiento y las acciones del detalle de cita
(reprogramar, llamar para confirmar, enviar confirmación, gestionar cita,
tarjetas regalo).

> Regla de oro: en pruebas, NO configures SMTP/WhatsApp/Twilio reales. Sin esa
> configuración el sistema **no** envía nada: cada acción te dirá con claridad
> qué falta. Para verificar el "camino feliz" usa los tests automáticos
> (`tests/test_api_smoke.py`), que simulan los proveedores.

## 1. Tests automáticos (recomendado)

Cubren cada paso sin tocar proveedores externos:

```powershell
python -m pytest tests/test_api_smoke.py -k "follow_up_ladder or send_confirmation or confirm_call or reschedule_changes or gift_card_assign" -q
```

- `test_follow_up_ladder_end_to_end`: en una sola pasada de `_run_booking_reminders`
  dispara recordatorio **24 h**, recordatorio **2 h** y **llamada de confirmación**
  (proveedor de voz simulado), cada uno sobre la cita correcta.
- `test_send_confirmation_validates_and_reports`: "Enviar confirmación" devuelve
  error claro sin email / sin correo configurado, y éxito (con audit) cuando el
  envío funciona.
- `test_confirm_call_dedup_and_validations` + `test_confirm_call_clear_error_without_voice_number`:
  "Llamar para confirmar" coloca la llamada, evita duplicados recientes y avisa
  si falta teléfono, voz o la cita no está activa.
- `test_reschedule_changes_employee_and_preserves_payment`: reprogramar cambia
  profesional y conserva pago + trazabilidad.
- `test_gift_card_assign_to_client_and_movements`: asignar tarjeta regalo a un
  cliente, dedup y movimientos.

El QA E2E aislado del portal también recorre estas zonas:

```powershell
python scripts/qa_e2e.py
```

## 2. Prueba manual en el panel (entorno local)

1. Arranca la API local: `uvicorn api:app --port 8000` y entra en `/app` con un
   usuario de plan Business.
2. **Crea una cita** (botón "+ Nueva cita") con un email y un teléfono de prueba.
3. Abre la cita en la vista **Día** → tarjeta de detalle.

### Escalera de Seguimiento (pestaña "Seguimiento")

- Revisa los pasos: **Confirmación → Recordatorio 24 h → Llamada IA →
  Recordatorio 2 h → Reseña**. Cada paso indica los canales activos y los que
  están bloqueados por plan (email siempre; WhatsApp = Pro; SMS y llamada =
  Business).
- Activa/define el enlace de reseñas en "Pide reseñas tras la cita".
- Los envíos automáticos los dispara el worker `_run_booking_reminders` según la
  hora de la cita; en pruebas verifica el comportamiento con los tests de arriba
  (no esperes al worker real).

### Acciones del detalle de cita (menú "⋯ Más")

- **✉ Enviar confirmación**: con email válido + correo configurado → "Confirmación
  enviada por email". Sin email o sin correo configurado → mensaje de error
  concreto (no un falso "enviado").
- **📞 Llamar para confirmar**: con número de voz Twilio configurado coloca una
  llamada real; sin configuración avisa ("El negocio no tiene número de voz…").
  Un segundo clic inmediato se rechaza ("llamada reciente").
- **🗂 Gestionar cita** (nuevo, in-app): abre un **modal centrado** con los datos
  de cita y cliente. Según permisos: editar datos, reprogramar/cambiar
  profesional, marcar asistencia, enviar confirmación, llamar, cancelar, ver
  ficha del cliente y **copiar el enlace público** para el cliente (ya no se abre
  en otra pestaña como interfaz interna).

### Reprogramar

- Botón **Reprogramar**: el drawer permite elegir **profesional** (solo los
  compatibles con el servicio), **fecha** y un **hueco real** (la lista solo
  muestra huecos libres del profesional). Al confirmar, la cita conserva su pago
  y queda registrada en el timeline (`booking_rescheduled`).

### Tarjetas regalo (ficha de cliente → "🎁 Tarjeta regalo")

- **Nueva tarjeta**: emite e importe y queda **asignada al cliente** (aparece en
  su ficha en "Bonos y saldo").
- **Asignar existente**: introduce el código `GC-XXXX-XXXX`. Si ya está a nombre
  de otra persona, te pide confirmar la reasignación.
- En la ficha, pulsa una tarjeta para ver **código, saldo, estado y movimientos**
  (emisión, asignaciones y canjes).

## 3. Permisos

Las acciones respetan el catálogo de permisos del portal:

- `agenda.attendance`: enviar confirmación, llamar para confirmar, marcar
  asistencia, pedir reseña.
- `agenda.cancel`: cancelar.
- `clients.edit`: editar datos de cliente/cita en el modal de gestión.
- `commerce.sell`: emitir/asignar/redimir tarjetas regalo y bonos.

El backend es la fuente de verdad: la UI solo oculta lo que el rol/permiso no
permite, pero el endpoint vuelve a validar.
