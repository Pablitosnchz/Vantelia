# Aceptación del bloque de atención: todavía abierta

Seguimiento del candidato `astra/cierre-estable-19sep`, desde `e43baca`.
El código desplegado comunicado sigue siendo `0cb61de`; esta rama no se ha
publicado ni desplegado. La suite anterior de 3025 aprobados/1 omitido y humo
5/5 acredita aquel producto, no este bloque. Última actualización: 19-sep,
23:31 Europe/Madrid.

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
| Operaciones de pago | `997d2ef` | 129 dirigidos previos y 21 finales/44.83s; causales de Connect y prioridad manual | Misma autoridad y diario, registro de resultado antes de avisos; éstos siguen por integrar |

Todas las filas tienen revisión independiente o de Astra sobre código de otro
implementador. No se suman las tandas como casos únicos: hay pruebas compartidas.
Las actas brutas están fuera del repo en las carpetas de evidencia enlazadas desde
ESTADO_ACTUAL y REGISTRO_CONSOLIDACION; no incluyen conversaciones ni secretos.

## En curso, sin atribuir aceptación

- Pago: `997d2ef` integrado y combinado con chat/avisos hasta `83bed95`. Incluye el
  rechazo conocido cuando Connect no permite cobrar y la prioridad manual
  restaurada sin cambiar su fixture. `56c3f3b` conserva el pay_ conocido cuando
  se suprime su aviso, sin nueva entrega ni Checkout. La huella acredita intención
  y datos del pago, no una petición Stripe completa congelada; desconocido no
  permite repetición ni acredita reconciliación automática.
- Chat y transportes `fc8f58e`: revisión final OK sobre 15 hashes/14 logs/acta;
  causales HTTP, Gmail, referencia de reserva y Meta parcial corregidos. Mutación
  final de SMTP/SMS/Meta: 3 fallos → 3 aprobados, restauración exacta. Supresión
  de aviso tras claim queda omitida, sin fallback; parcial conserva IDs e incertidumbre.
- Combinación final con pago `56c3f3b`: revisión OK de cinco archivos, acta y cuatro
  logs; 2 fallos causales del puente corregidos y 63 dirigidos/70.71s aprobados.
  Una contaminación entre tests por reload parcial se sustituyó por intérprete
  nuevo con DB temporal, sin cambiar producto: prueba lectura/guardia persistida,
  no reinicio E2E del servidor. Los padres siguen exigiendo Checkout/efecto único.
- WhatsApp, Flow, automatismos sin contexto, voz, operación administrativa y
  facturación separada siguen el plan. No hay control público que prometa una
  pausa completa mientras falten esas fronteras.
- WA0 `478d082` integrado en `23f16b3`: consulta demo inmutable sin cambios de
  rutas/usos. Dos fallos causales al reintroducir la escritura, 36 dirigidos
  aprobados/24.75s y dos hashes cotejados. No conecta atención: requiere todavía
  aplicador atómico ligado al tenant y ticket, con deduplicación del evento.
- WA1 `fd833b4` integrado en `f4ffd2c`: 172 dirigidos/161.86s, incluidos tres
  replays en intérprete nuevo. Sin capturador vivo ni atribución de efecto a un
  replay conocido. Los avisos múltiples siguen en validación separada.
- Widget `00d628a`: 16 pruebas Node y build; repro causal original de Chrome
  pasa sin cambiar el script. Cubre pausa durante la carga y recuperación del
  centro B sin reutilizar catálogo A. Entorno local interceptado, sin proveedor.
- `2ec42a5` corrige ambos hallazgos de la suite: persistencia real antes de
  interacción comercial y eliminación de wrapper sin consumidores. 45 dirigidos;
  mutaciones de orden/omisión rojas y restauración comprobada.

- WA2 `c465be1` (Claude): frontera de entrada de WhatsApp conectada. 7 dirigidos
  y 7 mutaciones causales rojas -quitar la puerta, no guardar la entrada,
  transcribir el audio, tomar el error de lectura por permiso, bloquear los ecos,
  abrir el formulario, comerse el ping de Meta-. Subconjunto whatsapp/flows/inbox/
  atencion: 669 aprobados. No acredita entrega real de Meta: transporte interceptado.
  El token de Flow sigue sin ligarse durablemente a la version de atencion.
- Fase 3 (Claude), voz y automatismos: telefono entrante, puente revalidado al
  conectar, voz del widget (sesion y cada tool), llamadas salientes -tambien las
  del boton del panel-, recordatorios, resenas, rebooking por IA y avisos de
  ciclo de vida. 10 dirigidos y 10 mutaciones causales rojas, incluida la que
  cachea el permiso por pasada en vez de preguntarlo por aviso. La supresion no
  marca entrega: se comprueba que al reactivar el aviso pendiente sale. Suite
  completa del arbol congelado: 3310 passed, 1 skipped, 1 failed (el vigilante de
  ARQUITECTURA.md por los cuatro modulos nuevos, ya documentados). Sin proveedor:
  Twilio, Realtime y SMTP van interceptados, asi que no acredita el silencio de
  una sesion de voz ya abierta ni una entrega real. Los avisos todavia no
  instalan turno; la identidad por aviso sigue pendiente.

- Fase 4 (Claude), la operacion: `GET/PUT /auth/app/attention` con permiso
  `channels.manage` y version CAS, tarjeta en Cuenta, aviso permanente fuera de
  esa pestana y lectura administrativa `GET /admin/attention` que solo lista.
  9 dirigidos y 5 mutaciones causales rojas. La prueba central no mira el 200:
  pulsa la pausa desde el panel, comprueba que `/chat` pasa a 409, reactiva y
  comprueba que vuelve a contestar. Se comprueba ademas que la pausa no toca
  plan, suscripcion ni el diario de otros canales.
  AVISO METODOLOGICO: la mutacion que quitaba la guarda de `atencion_chat`
  quedo VERDE -el chat tiene dos guardas y quitar una no cambia nada
  observable-. Se sustituyo por romper la LECTURA de la autoridad (un tenant
  pausado se lee activa), que si tumba la prueba. Una mutacion sobre una guarda
  suelta no acredita nada cuando hay defensa en profundidad.
  Suite completa del arbol congelado: 3320 passed, 1 skipped, 0 failed,
  2251.58s. Sin proveedor ni medicion con modelo.

- Identidad por aviso (Astra, `a3df1ee`, rescatada de su copia sin commitear)
  y worker conectado (Claude, `ec3a58d`): cada recordatorio con su turno, dos
  momentos de pausa con consecuencias distintas (antes = no se anota y sale al
  reactivar; durante = `omitido/atencion_suprimida`, terminal). 19 dirigidos de
  Astra + 5 del worker; 4 mutaciones causales rojas. DOS de las pruebas del worker
  nacieron mal -enganchaban la pausa y el retraso en una funcion que el worker
  consulta ANTES de capturar el turno- y lo delato la mutacion de la vigencia, que
  quedo en verde hasta moverlas dentro del envio. Suite completa: 3342 passed,
  1 skipped, 2 failed (vigilantes de reglas que leian una funcion partida en dos,
  reapuntados en `c9bc7ff` y comprobados con mutacion). `qa_e2e` 94/94.
  El ticket nace con `event_at` = ahora y no con el origen del aviso: decision
  de Pablo del 21-sep (el recordatorio cuya ventana coincide con la reactivacion
  sale), asi que la migracion del origen de Astra no se integra.

- Flow ligado a la version (Claude, `0657fa5`): token con la version de
  atencion firmada; se comprueba en pantallas y en envio final. 4 dirigidos y 6
  mutaciones rojas. La del envio final se rehizo: sin preparar el estado del
  formulario otra barrera lo frenaba y su rojo venia del texto; preparado como lo
  deja el envio real, sin la comprobacion un formulario de antes de la pausa
  prepara una cita. Suite completa del arbol final: 3348 passed, 1 skipped,
  0 failed. `qa_e2e` 94/94. Sin Meta real.

## Puertas que faltan

1. Integrar piezas revisadas y comprobar conflictos sobre el código resultante.
2. Completar las fronteras del alcance operativo y sus casos deterministas.
3. Congelar candidato exacto, ejecutar una suite completa y revisar ese código;
   `dff4b72` terminó su única suite el 19-sep a las 23:08:19.078 Europe/Madrid:
   3267 passed, 1 skipped y 2 failed, 2317.92s. Árbol y SHA iguales antes/después.
   Fallan el doble antiguo de persistencia en demo_conversion y el vigilante de
   código sin consumidores por un wrapper ya sustituido. Se corrigen con dirigidos;
   no hay aceptación global ni repetición de completa por cada pieza. WA1 y
   widget se integraron después; R0/avisos aún no. Log/metadata/acta preservados.
4. Medir referencia y candidato con el mismo instrumento, calendario, catálogo,
   configuración y modelo para Alicia y un segundo negocio. No existe todavía
   un artefacto saneado actual autorizado: Claude lo confirmó; Astra no leyó ni
   copió storage/producción para suplirlo. El banco actual entra directamente en
   `_handle_whatsapp_message`: no valida el capturador del webhook ni `/chat`.
   Contrato de cobertura y campañas adicionales en MEDICION_CIERRE_COMPARABLE.md.
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
