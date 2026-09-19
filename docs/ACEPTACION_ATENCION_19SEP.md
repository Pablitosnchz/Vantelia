# Aceptación del bloque de atención: todavía abierta

Seguimiento del candidato `astra/cierre-estable-19sep`, desde `e43baca`.
El código desplegado comunicado sigue siendo `0cb61de`; esta rama no se ha
publicado ni desplegado. La suite anterior de 3025 aprobados/1 omitido y humo
5/5 acredita aquel producto, no este bloque. Última actualización: 19-sep,
21:40 Europe/Madrid.

## Entregas comprobadas

| Entrega | Código revisado | Evidencia dirigida | Alcance |
| --- | --- | --- | --- |
| Autoridad persistida | `3fad6f2` | 67 aprobados; mutación CAS 2 fallos → 2 aprobados | Estado por tenant, versión, aislamiento, errores y auditoría |
| Tickets y admisión | `6458b5` | 112 aprobados; causal de igualdad temporal y mutación de permiso | Frontera transaccional, dueño único, resultado conocido/incierto |
| Núcleos de reserva | `f6c16e1` | 108 aprobados de integración y 78 finales afectados; 16 causales y mutación 3 → 3 | Crear/cancelar/mover con contexto interno; no todas las entradas lo instalan aún |
| Contexto en hilos | `6b66632` | 4 fallos antes → 4 aprobados | Aislamiento del contexto entre tareas e hilos reutilizados |
| Instrumento cita única | `e8a8b6` | 13 aprobados; causales, incluida consulta SQLite | Exige una cita nueva activa por identidad; no confunde pago pendiente con cobro |
| Widget | `fdf60e3` | 6 fallos/1 aprobado antes → 7 aprobados; build correcto | Estado HTTP 409/503 fuera del historial, sin falsa respuesta ni reintento |
| CI widget | `80c52e0` | `npm run test:widget`: 7 aprobados | Las regresiones Node se ejecutan antes del build en CI |

Todas las filas tienen revisión independiente o de Astra sobre código de otro
implementador. No se suman las tandas como casos únicos: hay pruebas compartidas.
Las actas brutas están fuera del repo en las carpetas de evidencia enlazadas desde
ESTADO_ACTUAL y REGISTRO_CONSOLIDACION; no incluyen conversaciones ni secretos.

## En curso, sin atribuir aceptación

- Pago: revisión independiente final OK de cinco archivos congelados; 129
  dirigidos previos y 21 finales/44.83s. Incluye el rechazo conocido cuando
  Connect no permite cobrar, y la prioridad manual restaurada sin cambiar su
  fixture. Falta registrar el commit e integración. La huella acredita intención
  y datos del pago, no una petición Stripe completa congelada; desconocido no
  permite repetición ni acredita reconciliación automática.
- Chat: 17 dirigidos ASGI/memoria/shim aprobados antes de la revisión. Pendientes
  los causales de petición en espera durante pausa/reactivación, sesión de otro
  tenant, intención del mensaje y ausencia de asiento en la frontera. Todavía
  sin revisión final, integración ni validación de todos sus avisos.
- Avisos: la supresión conocida antes de un POST debe ser terminal y no cuenta
  como fallo del proveedor, entrega ni permiso de probar otro canal. Carrera
  entre claim y pausa en prueba; resultado de red perdido sigue siendo incierto.
- WhatsApp, Flow, automatismos sin contexto, voz, operación administrativa y
  facturación separada siguen el plan. No hay control público que prometa una
  pausa completa mientras falten esas fronteras.

## Puertas que faltan

1. Integrar piezas revisadas y comprobar conflictos sobre el código resultante.
2. Completar las fronteras del alcance operativo y sus casos deterministas.
3. Congelar candidato exacto, ejecutar una suite completa y revisar ese código;
   ninguna suite completa nueva ha empezado todavía.
4. Medir referencia y candidato con el mismo instrumento, calendario, catálogo,
   configuración y modelo para Alicia y un segundo negocio. No existe todavía
   un artefacto saneado actual autorizado: Claude lo confirmó; Astra no leyó ni
   copió storage/producción para suplirlo.
5. Pruebas de entrega y operación reales con cuentas/destinatarios autorizados;
   dobles de Meta, Stripe o ASGI no prueban lectura del teléfono/navegador ni
   silencio de una sesión de voz ya abierta.

## Resultados con modelo de este candidato

| Negocio | Primer intento | Tras reintento | Fallos | No medidos | No aplicables |
| --- | --- | --- | --- | --- | --- |
| Alicia | — | — | — | Campaña sin iniciar; conjunto y copia por fijar | Por clasificar |
| Segundo negocio | — | — | — | Campaña sin iniciar; conjunto y copia por fijar | Por clasificar |

Los guiones significan ausencia de medición, no cero fallos. No se arrastran los
45/45 de otro catálogo/SHA a esta entrega. El contrato reproducible está en
[MEDICION_CIERRE_COMPARABLE.md](MEDICION_CIERRE_COMPARABLE.md). Este documento no
autoriza push, despliegue ni operaciones sobre cuentas de clientes.
