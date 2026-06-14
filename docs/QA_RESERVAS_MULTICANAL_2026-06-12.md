# QA funcional completa - 13 de junio de 2026

Especificacion funcional de referencia:
[`REQUISITOS_FUNCIONALES_VANTELIA_2026-06-13.md`](./REQUISITOS_FUNCIONALES_VANTELIA_2026-06-13.md).

## Alcance

Auditoria ejecutada sobre entornos temporales aislados. No se modificaron clientes,
citas ni centros reales y no se enviaron correos, WhatsApp, llamadas ni cobros reales.

Se genero un cliente de prueba con:

- Dos centros.
- Tres profesionales.
- Servicios de 45 y 15 minutos.
- Precios y disponibilidad distintos por centro.
- Una sala para comprobar aforo.
- Agenda de 09:00 a 12:00 con rejilla de 15 minutos.

## Caso principal solicitado

Preparacion:

- Existe una cita de 15 minutos a las 10:30.
- Se consulta o intenta reservar a las 10:00.

Resultado comprobado:

| Canal | Servicio 45 min a las 10:00 | Servicio 15 min a las 10:00 |
|---|---|---|
| Disponibilidad web/widget | No disponible | Disponible |
| Chat web | No ofrece 10:00 | Ofrece 10:00 |
| WhatsApp | No ofrece 10:00 | Ofrece 10:00 |
| Voz | No ofrece/rechaza 10:00 | Ofrece y permite reservar |
| Reserva web | HTTP 409 | Reserva creada |

Tambien se comprobo:

- 15 min a las 10:15: permitido, termina justo al empezar la cita de 10:30.
- 15 min a las 10:30: rechazado.
- 45 min a las 10:45: permitido, empieza justo al terminar la cita existente.
- Hora fuera de rejilla, 11:05: rechazada.

## Multi-centro

- El precio efectivo del centro se guarda en la cita, no el precio base.
- Un servicio desactivado en un centro deja de aparecer como disponible.
- Una peticion directa manipulada para reservar ese servicio se rechaza.
- Las asignaciones de servicios creados desde el panel se conservan correctamente.
- Numero de WhatsApp/voz y centro siguen resolviendose por las pruebas existentes.

## Salas y aforo

- Con una sala, dos profesionales no pueden crear citas solapadas en el mismo centro.
- Una cita adyacente que empieza cuando termina la anterior si se permite.
- Cancelar una cita libera inmediatamente profesional, horario y sala.

## Otros casos humanos cubiertos por la suite

- Dia cerrado, descansos y bloqueos parciales/totales.
- Fecha pasada y fecha fuera del limite de antelacion.
- Doble reserva y carrera de ocupacion.
- Cancelacion idempotente.
- Reprogramacion a hueco ocupado.
- Dos profesionales en el mismo horario.
- Servicios con distintas duraciones.
- Reserva manual, widget, WhatsApp y voz.
- Firma invalida de webhook WhatsApp.
- Asistencia, no-show, timeline y gestion del cliente.
- Overrides de servicio, preautorizacion, captura, liberacion y reembolso.
- Renombrado/alta duplicada de servicios y herencia al borrar un override.
- Proteccion al desactivar o borrar centros, profesionales y salas con dependencias.
- Proteccion al recortar horarios o cerrar dias que contienen citas futuras.
- Bonos caducados o usados en otro servicio; gift cards inexistentes, desactivadas o caducadas.
- Informes filtrables por centro, servicio y rango personalizado; CSV respeta los mismos filtros.

## Recorrido manual real de navegador

Se creo `scripts/qa_portal_browser.py`, que levanta un cliente temporal y usa
Chromium/Playwright como un propietario real:

- Inicia sesion en `/acceso`.
- Abre Servicios y pulsa `+ Nuevo servicio`.
- Crea un servicio de 45 minutos, selecciona pago requerido y `Retencion`.
- Guarda, vuelve a abrirlo con `Editar` y comprueba dos filas de centro.
- Verifica que el tipo de cobro guardado sigue siendo `preauth`.
- Abre Ventas e Informes.
- Filtra Informes por servicio y rango de fechas personalizado.
- Comprueba tooltips, ampliacion de graficos y navegacion movil sin desbordamiento.
- Falla ante cualquier error de consola o respuesta incorrecta.

Resultado: PASS en escritorio y viewport movil.

## Matriz completa del pliego

| Requisito | Casos comprobados |
|---|---|
| Reservas multicanal | Web/widget, portal, chat web, WhatsApp y voz; disponibilidad y reserva real; duraciones 15/45 min |
| Registro automatico CRM | Alta desde reserva, busqueda, actividad, deduplicacion por telefono y aislamiento entre clientes |
| Personal y salas | Asignacion de profesional/centro/sala, aforo por centro, centros independientes, cancelacion libera sala |
| Stripe y gift cards | Retencion, captura total/parcial, liberacion, reembolso, tarjeta parcial/total, rechazo de doble pago |
| Servicios/productos/bonos | CRUD, override por centro, stock agotado, bono vendido/redimido/agotado, servicio no disponible |
| Recordatorios | Email/WhatsApp/SMS simultaneos simulados, botones confirmar/cancelar, canal no configurado |
| Cancelacion/reembolsos | Cancelacion idempotente, reprogramacion, hueco ocupado, refund total/parcial |
| Auditoria | Creacion, cancelacion, bono, gift card, notificacion, asistencia/no-show y pagos |
| Panel admin | Empleados, centros, salas, bloqueos, horarios, agenda, citas y timeline |
| Informes | KPIs, SVG/portal, CSV y filtro por centro con ingresos separados |
| Roles | Owner/manager/staff, tabs visibles, endpoints protegidos, ultimo owner y gestion de salas |
| Multi-tenant | Contactos, centros, pagos, canales y datos de negocio aislados |

## Casos limite y negativos

- Fecha pasada, dia cerrado, fuera de horario, fuera de rejilla y limite de antelacion.
- Descansos multiples, bloqueos parciales/totales y servicio largo antes de descanso.
- Solapes, doble reserva, carrera de ocupacion, limites exactos adyacentes y aforo agotado.
- Dos centros al mismo horario permitidos; una sala en el mismo centro limita dos profesionales.
- Servicio desactivado por centro y peticion directa manipulada rechazados.
- Servicio globalmente inactivo, nombre duplicado y reset de override a precio/duracion heredados.
- No se puede desactivar/borrar un centro con profesionales asignados, ni una sala o
  profesional con citas futuras activas.
- No se puede recortar el inicio/fin de jornada, cerrar el dia o crear un descanso
  que deje una cita futura fuera del horario; tras cancelar la cita, el cambio se permite.
- Stock, saldo y sesiones agotados; codigo gift card incorrecto; cita ya pagada no admite segundo pago.
- Bono aplicado al servicio equivocado o caducado; gift card desactivada o caducada.
- Usuario staff puede operar agenda/mostrador, pero no catalogo, salas, informes ni equipo de acceso.
- Firma WhatsApp invalida, token de gestion invalido y telefono WhatsApp que no coincide.
- Canales externos no configurados no bloquean la cita y quedan registrados como fallo/omitidos.

## Fallos encontrados y corregidos

1. El chat web consultaba disponibilidad generica aunque el mensaje mencionase un
   servicio. Ahora detecta el servicio activo mencionado y calcula los huecos con
   su duracion real.
2. Web/widget y portal guardaban el precio base del servicio en la cita. Ahora
   guardan el precio efectivo del centro.
3. Las asignaciones de servicios creados desde el panel se normalizaban contra
   `info.txt`, por lo que podian convertirse accidentalmente en "todos los
   servicios". Ahora se normalizan contra el catalogo persistido.
4. La disponibilidad con profesional explicito no rechazaba un servicio conocido
   pero no disponible para ese profesional/centro. Ahora devuelve error.
5. El script `scripts/qa_e2e.py` heredaba SMTP local. Ahora fuerza correo saliente
   desactivado durante la auditoria aislada.
6. Un usuario `staff` podia crear, editar y borrar salas mediante llamadas directas.
   Ahora las mutaciones de salas exigen rol `manager`.
7. El filtro CRM por etiqueta dependia de `json_each` y fallaba en SQLite sin JSON1.
   Ahora mantiene coincidencia exacta sin depender de esa extension opcional.
8. Los enlaces de pago enviados por IA usaban `asyncio.to_thread`, no disponible en
   Python 3.8. Ahora usan un helper compatible y vuelven a funcionar.
9. Se podia renombrar un servicio con el nombre de otro, generando referencias
   ambiguas. Ahora el panel rechaza el duplicado con HTTP 409.
10. Se podia desactivar un centro que aun tenia profesionales asignados, o
    desactivar/borrar una sala con citas futuras. Ahora esas operaciones se
    bloquean hasta resolver sus dependencias.
11. Cambiar horas desde Horario o Editar profesional podia dejar citas futuras
    fuera de jornada; el editor general tambien podia cerrar su dia. Las tres
    rutas ahora detectan y muestran las citas afectadas antes de guardar.

## Evidencia ejecutada

```text
python -m pytest tests/test_reservas_multicanal_e2e.py -q
3 passed

python -m pytest tests/test_booking_exhaustive.py tests/test_reservas_multicanal_e2e.py -q
42 passed

python -m pytest tests/test_pliego_acceptance_e2e.py -q
2 passed

python -m pytest tests/test_admin_edge_cases_e2e.py -q
5 passed

python scripts/qa_portal_browser.py
PASS: login, nuevo servicio, Retencion, editar, centros, Ventas e Informes

python scripts/qa_e2e.py
66 PASS, 0 WARN, 0 BUG

python -m pytest -q
285 passed, 0 failed

npm run build:widget
OK

Validacion JavaScript del portal con Node
OK

py_compile + git diff --check
OK
```

## Limites de esta auditoria

- WhatsApp y voz se prueban atravesando su logica real de canal, pero los
  proveedores externos Meta/Twilio se simulan para no enviar mensajes ni llamadas.
- Stripe se prueba con dobles del SDK; no se realiza ningun cargo real.
- OpenAI no se invoca en la suite aislada. La disponibilidad determinista que
  alimenta las respuestas del chat, WhatsApp y voz si se ejecuta realmente.
- Chromium valida interaccion real del portal, pero no se hizo comparacion visual
  pixel a pixel ni una matriz de navegadores/dispositivos.
- "Todas las casuisticas" no puede significar combinaciones infinitas; se cubren
  caminos felices, errores, limites, permisos, aislamiento y fallos de proveedor
  razonablemente previsibles, ademas de toda la suite automatizada existente.
