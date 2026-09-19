# Pausa de temporada: diseño del siguiente bloque

19-sep-2026. Propuesta, sin implementación ni ejecución. Lecturas sobre `60993b7`.
Complementa [la operación y su acta](PAUSA_TEMPORADA_OPERACION.md); no cambia el contrato.
El candidato en validación no se modifica con esta nota.

## Una autoridad para la atención automática

Proponer `backend/atencion.py` como único dueño de decidir si el tenant puede
iniciar atención automática. Persistir en SQLite una fila por `cliente_id`:
`estado` (activa/pausada), `version`, fecha efectiva, motivo y actor del cambio.
La ausencia de fila conserva el comportamiento activo actual; un error de lectura
no se interpreta como permiso para enviar y deja diagnóstico para el operador.
Las escrituras comparan la versión esperada y registran la transición, evitando
que un operador o un trabajo viejo deshaga una pausa más reciente.

La configuración general sigue en sus fuentes actuales. No copiar reglas, número,
credenciales ni indicadores de canal a esta tabla, ni sobrescribirlos para pausar.
No usar `subscription.status`, `booking.enabled` o cada canal como autoridad paralela.
Leer el estado persistido en cada frontera: `clients._get_client_config` mantiene
en memoria la configuración ordinaria (`clients.py:623`), insuficiente por sí sola
para que dos workers observen inmediatamente una transición.

## Fronteras concretas que deben consultar esa autoridad

| Entrada o salida actual | Trabajo necesario |
| --- | --- |
| `/chat`, `routers/public_booking.py:270`, y `chat._process_chat_message:861` | Frenar antes del modelo, reglas y consumo; comprobar otra vez al devolver una respuesta generada durante la pausa. Adaptar el widget al estado, sin respuesta automática ni falsa entrega. |
| `whatsapp._handle_whatsapp_webhook:4938`, ambas rutas de `routers/whatsapp_webhooks.py` y `/whatsapp/flow:46` | Resolver primero el tenant, incluido el número de demo, y bloquear mensajes, fotos, audios, botones y Flows antes de procesarlos. Mantener verificación, estados de entrega y ecos del equipo. |
| `messaging._post_whatsapp_message:166` | Última frontera compartida de texto y payload; `_send_whatsapp_text:361` la llama directamente, no pasa por `_send_whatsapp_payload`. Comprobar la versión vigente antes de cada fragmento. |
| `routers/portal_app.py:510`, `/auth/inbox/{conv_id}/reply` | Preservar respuesta humana autenticada y acceso a conversaciones. El origen humano debe proceder del endpoint autorizado, no de un campo libre del cliente o del modelo. |
| `routers/voice_web.py:35,99`; `voice._mint_voice_session:274` | Cubrir llamada entrante, stream y sesiones WebRTC de widget/demo/panel. Impedir sesiones nuevas; las ya abiertas necesitan cierre/revocación comprobable, no basta con bloquear el siguiente alta. |
| `voice._voice_place_outbound_call:477` | Impedir llamadas automáticas antes de Twilio, también las solicitadas por recordatorios. |
| `booking._send_booking_reminder_by_kind:4393`, `_run_booking_reminders:5732` | Cubrir recordatorios y avisos de confirmación/cambio/cancelación por WhatsApp, email, SMS y llamada, incluidos respaldo y reenvío automático. |
| `booking._run_ai_rebooking_pass:328`, `_run_review_requests:5646` | Cubrir recuperación de clientas y peticiones de reseña; verificar también los disparos de prueba y los avisos originados en un webhook de pago. |

La pausa no deshabilita usuarios, catálogo, agenda manual, lectura del portal ni
la conexión de WhatsApp. Conservar `client_whatsapp_accounts`; `disconnect` la borra
(`wa_onboarding.py:269`) y queda fuera de esta transición.
Los envíos manuales conservan autorización y trazabilidad propias. No permitir que
`respect_enabled=False` u otro indicador técnico eluda la decisión de atención.

## Trabajo ya iniciado y reinicios

Comprobar antes de trabajar evita coste; comprobar antes de enviar evita respuestas
preparadas con un estado viejo. Registrar cada admisión de envío y su versión de
atención de forma transaccional; una pausa cierra nuevas admisiones.
Si ya había una petición en tránsito, la pausa queda pendiente de verificación
hasta conocer su resultado; no prometer silencio retroactivo del proveedor.
Reutilizar el diario de entregas de `notice_deliveries.py:65` para los avisos y
conservar resultados aceptados, rechazados o desconocidos. Una supresión no cuenta como
entrega, fallo de transporte ni autorización para intentar otro canal.
Reactivar no reproduce el histórico: los trabajos pendientes se revalidan contra
su vigencia y generación; no reenviar mensajes vencidos de los meses de cierre.
No mantener una transacción SQLite abierta durante una llamada de red.

## Facturación: resultado independiente, visible

Separar «atención pausada» de «cuota suspendida». Persistir una operación de cobro
con tenant, referencia del proveedor/proceso manual, intención, fecha efectiva y
resultado conocido o desconocido, sin secretos. No crear una segunda suscripción.
El portal actual abre Stripe (`portal_app.py:2751`); sus webhooks sincronizan estado
(`billing_web.py:418,471`), pero no acreditan por sí solos ausencia de cuota.
Antes de repetir un cambio cuyo resultado se perdió, reconciliar la referencia
existente. Un resultado desconocido nunca se convierte en éxito por timeout.
Apagar atención no cambia Stripe. Reactivar atención tampoco prueba que la cuota
se haya restablecido sin duplicados ni una puesta en marcha nueva.
Mostrar la pausa completa solo cuando atención y cobro tengan evidencia conocida;
conservar el acceso del equipo aunque la operación de cobro siga por reconciliar.

## Primera entrega pequeña y cierre posterior

Primer commit: migración, autoridad persistida, transición por versión y lectura
administrativa autenticada; pruebas deterministas de aislamiento y reinicio.
Sin interruptor público de pausa efectiva mientras faltan las fronteras anteriores.
Después, conectar chat/WhatsApp y sus envíos, conservando las respuestas humanas;
cerrar voz y automatismos aplicables antes de habilitar la operación de temporada.
Facturación se incorpora como operación reconciliable separada; no hace falta
automatizar fechas o Stripe para demostrar primero la autoridad de atención.

## Pruebas que permiten aceptar el bloque

- Dos tenants: pausar uno frena sus respuestas y consumo; el otro mantiene ES/EN.
- Reactivar conserva IDs, conexión, reglas y conversaciones; refleja ediciones
  hechas por el equipo durante la pausa, sin restaurar una copia antigua.
- Reiniciar y consultar desde otro worker conserva la pausa y rechaza versiones viejas.
- Pausar entre interpretación y envío suprime la salida; petición ya en tránsito
  queda pendiente/desconocida hasta reconciliar. Reintentos no duplican entregas.
- Cada frontera de la tabla se prueba con transporte interceptado; el equipo
  sigue entrando y respondiendo, y un tenant ajeno no puede cambiar el estado.
- Cobro conocido, rechazo y respuesta perdida mantienen estados diferenciados;
  apagar atención no marca cuota suspendida, ni reactivar crea otro cobro inicial.

Esta nota no ejecuta pytest ni mide Meta, voz o Stripe. Las referencias son de la
base leída: ajustar números al candidato integrado antes de implementar.
