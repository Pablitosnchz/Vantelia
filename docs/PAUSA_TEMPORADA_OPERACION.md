# Pausa de temporada: borrador de operación y acta

19-sep-2026. Base examinada: `60993b7`. Operador previsto: Claude.
**BORRADOR TÉCNICO. NO EJECUTADO. Pausa completa: NO IMPLEMENTADA / NO VERIFICADA.**
No cambia el contrato ni acredita el estado del hotel, Stripe o Meta. Este documento
prepara una operación futura; no autoriza acceso o cambios en producción.

## Qué existe y qué falta

| Elemento | Código observado | Límite operativo |
| --- | --- | --- |
| Apagar WhatsApp conservando su cuenta local | `POST /auth/app/whatsapp`, `enabled:false`, modifica el interruptor sin llamar a `wa_onboarding.disconnect`. La resolución de entrada comprueba ese interruptor. | Existe en código. Silencio real y posterior reactivación con Meta: **NO VERIFICADOS**. No detiene cobro ni otros canales. |
| Desconectar WhatsApp | `DELETE /auth/app/whatsapp/connect` llama a `wa_onboarding.disconnect`, que borra la fila de `client_whatsapp_accounts`. | No usar como sustituto de la pausa que conserva la conexión. Volver a encender el interruptor no recupera esa fila. |
| Apagar Citas | `POST /auth/app/appearance`, `booking_enabled:false`, modifica `booking.enabled`. | No silencia saludos, respuestas por palabra clave ni el resto de atención. No detiene cobro. |
| Facturación | `/auth/app/billing/portal` abre Stripe; los webhooks reflejan estados de suscripción. | No se ha identificado un flujo local de pausa de cobro y servicio, ni fechas de temporada, ni reconciliación de reactivación. **NO IMPLEMENTADO** como operación conjunta. |
| Estado de suscripción | El chat comprueba ciertos estados; `paused` no está entre los bloqueados. | Cambiar un estado local no acredita suspensión de cobro ni silencio de todos los canales. |
| Voz y chat web | Voz tiene interruptores propios; el chat web mantiene su entrada `/chat`. | No hay un interruptor global de pausa acreditado para todos los canales. Silencio completo: **NO VERIFICADO**. |

Referencias: [portal_app.py](../backend/routers/portal_app.py),
[whatsapp.py](../backend/whatsapp.py), [wa_onboarding.py](../backend/wa_onboarding.py),
[public_booking.py](../backend/routers/public_booking.py),
[billing.py](../backend/billing.py) y [db.py](../backend/db.py).

Riesgo pendiente de reproducción: un tenant legacy podría conservar respuestas
de WhatsApp con la suscripción cancelada si mantiene el plan y el canal activo.
Se ha observado la diferencia entre guardias en lectura estática; no se ha
reproducido y no se usa como mecanismo de pausa.

## Preparación del operador

1. Registrar solicitud, tenant exacto, inicio y fin en Europe/Madrid, operador y
   autorización de la operación. Usar las condiciones ya acordadas; resolver
   configuración y comprobaciones rutinarias con la evidencia disponible.
2. Inventariar los canales realmente activos y sus entradas: número propio,
   código de demo si sigue operativo, widget/chat web, voz y comunicaciones
   automáticas pendientes. El inventario no supone que el hotel use todos ellos.
3. Identificar la fuente real del cobro: suscripción y calendario de Stripe o
   proceso de facturación manual. Registrar referencias sin secretos. Comprobar
   si existen facturas abiertas, próximos cargos o automatismos que puedan seguir
   emitiendo cuota; no inferirlo del estado mostrado por Vantelia.
4. Preparar copia recuperable del tenant y relación de IDs/contadores: cuenta de
   WhatsApp, configuración, reglas ES/EN, Q&A, catálogo y agenda si existen,
   usuarios y conversaciones. Mantener los datos personales en el soporte
   autorizado; el acta solo contiene referencias y resultados.
5. Ensayar en una copia aislada, con salidas interceptadas. Identificar un control
   probado por cada canal activo y para la facturación. Si un control falta,
   registrar **NO IMPLEMENTADO**; si existe pero no se ha comprobado, registrar
   **NO VERIFICADO**. No marcar la pausa completa mientras quede alguno pendiente.

## Entrada en pausa, pendiente de ejecución

1. Aplicar y comprobar la suspensión de cuota en su fuente real, registrando la
   fecha efectiva y la siguiente emisión prevista. Una pantalla local o dejar
   un recibo impagado no demuestra que no se emita cuota. Cualquier resultado
   desconocido del proveedor se reconcilia antes de repetir una acción de cobro.
2. Aplicar los controles ensayados para cada canal. En WhatsApp, conservar cuenta
   y número: el interruptor de atención es distinto de desconectar. Registrar
   sus valores anteriores para la reactivación. No sustituir esta operación por
   apagar Citas, borrar reglas o alterar el estado de facturación.
3. Comprobar ausencia de respuestas con destinatarios y entorno autorizados:
   saludo, regla conocida ES/EN, consulta sin regla y conversación ya iniciada.
   Verificar también envíos pendientes/automáticos que puedan hablar durante la
   pausa. Para cada caso guardar entrada, canal, intervalo observado, trazas y
   ausencia de entrega. Un timeout aislado no acredita silencio.
4. Confirmar que el equipo conserva su acceso y, cuando corresponda, puede
   atender desde la aplicación del hotel. Verificar que Vantelia no responde
   por encima. Operación real con Meta: **NO VERIFICADA** en esta entrega.
5. Comparar IDs y configuración con la copia previa: cuenta conectada conservada,
   reglas y contenidos intactos, sin cambios en otro tenant. Registrar cualquier
   diferencia intencionada y su motivo. Comprobar tras recarga/reinicio controlado
   que los interruptores persisten.
6. Cerrar el acta solo con evidencia de cobro, silencio y conservación. Si una
   parte falla, indicar estado parcial y siguiente acción del operador; no
   comunicar «pausa activada». Evitar reactivar cobros o respuestas como vuelta
   atrás automática: reconciliar el estado efectivo antes de otra transición.

## Reactivación, pendiente de ejecución

1. Confirmar el fin registrado y reconciliar cambios ocurridos durante la pausa.
   Comparar con la copia previa sin restaurarla encima de datos posteriores.
2. Recuperar únicamente los canales y valores que estaban activos, conservando
   IDs, cuenta del número, reglas y contenido. Comprobar persistencia tras una
   recarga. Si la cuenta ya no existe, registrar incidencia; no afirmar que basta
   con encender el interruptor.
3. Verificar respuestas ES/EN del tenant con sus textos vigentes y un control en
   otro negocio. Probar conversación nueva y existente, y entrega real cuando el
   entorno lo permita. No reenviar mensajes acumulados sin una operación definida.
4. Restablecer la facturación acordada sin crear una puesta en marcha nueva.
   Reconciliar la suscripción existente, fecha e importe de la siguiente cuota y
   evitar duplicados. Conservar referencias de la confirmación del proveedor.
5. Cerrar la reactivación solo tras acreditar atención, conservación y facturación.
   Si falta una prueba, consignar **NO VERIFICADO** y el siguiente paso concreto.

## Acta para completar en la operación real

| Dato / comprobación | Resultado actual | Evidencia y fecha |
| --- | --- | --- |
| Tenant, operador, autorización, inicio y fin | PENDIENTE | — |
| SHA desplegado y ensayo en copia | PENDIENTE | — |
| Inventario de canales y envíos pendientes | NO VERIFICADO | — |
| Fuente de cobro y ausencia de cuota durante la pausa | NO VERIFICADO | — |
| Copia recuperable e inventario previo | NO VERIFICADO | — |
| Silencio WhatsApp y atención del equipo | NO VERIFICADO | — |
| Silencio resto de canales activos y automatismos | NO VERIFICADO | — |
| Cuenta/número, reglas, datos y otro tenant conservados | NO VERIFICADO | — |
| Persistencia tras recarga/reinicio | NO VERIFICADO | — |
| Pausa completa | NO IMPLEMENTADA / NO VERIFICADA | — |
| Reactivación con los mismos datos y respuestas ES/EN | NO VERIFICADO | — |
| Cuota restablecida, sin doble suscripción ni nueva puesta en marcha | NO VERIFICADO | — |
| Reactivación completa | NO VERIFICADA | — |

Las pruebas deterministas de aislamiento ES/EN acompañan este borrador; no prueban
la pausa, el cobro, la conservación de la conexión con Meta ni la reactivación real.

Validación de esta entrega: `git diff --check` terminó sin errores. El dirigido
`tests/test_palabras_clave_aislamiento_portal.py` se interrumpió el 19-sep-2026 a
las 14:05:12 Europe/Madrid por saturación de memoria del equipo, sin resultado.
Se identificó y detuvo solo su proceso (PID 30168). No se ejecutaron mutaciones,
suite completa, modelo real ni operaciones externas. **Pruebas pendientes de
ejecución serializada sobre el candidato integrado; esta entrega no acredita verde.**
