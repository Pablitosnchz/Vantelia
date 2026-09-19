# Pausa de temporada: diseño del siguiente bloque

19-sep-2026. Diseño inicial sobre `60993b7`, actualizado al cierre del 19-sep.
La autoridad persistida está implementada en `3fad6f2`, integrada en `b5fd11b`,
con revisión y 67 pruebas dirigidas aprobadas. Los canales aún no la consultan.
Complementa [la operación y su acta](PAUSA_TEMPORADA_OPERACION.md); no acredita
una pausa efectiva. Avance y puertas en [el plan de cierre](CIERRE_ESTABILIDAD_AUTONOMO_19SEP.md).

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

La admisión de envíos por sí sola no cierra la pausa durante una reserva. El chat
web actual hace la gestión antes de llamar al motor RAG; WhatsApp usa el
despachador de herramientas. Ambos desembocan en `_create_booking_core`,
`_cancel_booking_core` y `_update_booking_details`. El siguiente corte debe
propagar un contexto de turno interno y admitir la mutación antes del primer
efecto del núcleo, incluso reclamar la operación de creación. No basta impedir
el texto después de crear/cancelar/mover. El portal manual conserva su recorrido
autenticado; ningún campo del mensaje o argumento del modelo concede una excepción.

Si la pausa gana la admisión, no hay efecto; si la operación ya fue admitida,
conservar su resultado o incertidumbre, sin compensación ni repetición automática.
Una operación admitida no acredita entrega del aviso. La supresión conocida debe
atravesar los adaptadores sin convertirse en resultado desconocido ni en una
petición de repetir. Esta conexión y sus pruebas siguen pendientes. Antes de
cerrar chat, cubrir también sus enlaces/avisos de pago, retornos tempranos e
historial: no guardar como respuesta del asistente un cuerpo HTTP suprimido.

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

## Recordatorios 24 h / 2 h: conservar cuándo nació el aviso

Diseño del siguiente corte, todavía sin implementar. El selector actual usa una
banda: para inicio de cita S, adelanto H y gracia G=max(45 min, dos intervalos del
worker), abre en S−H−G y cierra en S−H. Solo un aviso ya intentado admite la
prórroga de 30 min+G. Extraer esos límites en un helper usado por el selector y
la captura: no introducir un segundo cálculo. Conservar sus extremos inclusivos
al traducirlos al vencimiento exclusivo del ticket.

Identidad del aviso: tenant, cita, reminder_generation y tipo. Guardar el primer
origen y los límites de esa identidad; consultar otra vez o reiniciar no los
renueva. Esa metadata no cuenta como intento ni permite enviar. Un ticket con
el límite máximo tampoco permite estrenar un aviso fuera de la banda inicial:
antes del claim y del envío sigue siendo necesario comprobar la elegibilidad.

El origen no puede ser `now` de cada pasada, ni la fecha de creación de toda la
cita. Tampoco basta S−H: en la apertura de la banda aún sería futuro. Persistir
cuándo nace cada generación de recordatorios al crear o cambiar la cita, y usar
max(apertura, nacimiento acreditado de generación). Así una reprogramación hecha
después de reactivar, ya dentro de la banda, es un evento nuevo. Las generaciones
antiguas sin fecha acreditada mantienen ese límite explícito: no rellenarlo con
la hora de la migración ni inferirlo de `updated_at` genérico.

Una supresión de atención es terminal para el aviso completo, sin marcar entrega,
fallo de proveedor ni abrir respaldo. Una respuesta desconocida del proveedor
conserva la decisión de Pablo de esperar 30 minutos antes de permitir el siguiente
canal; nunca repetir el mismo. Reutilizar reloj/propietario de notice_deliveries,
sin reiniciarlo con otro ticket. El contexto pertenece a cada aviso, no a todo el
bucle ni a sus llamadas de voz. Probar pausa dentro de banda, reactivación,
reprogramación posterior, reinicio, cambio de intervalo, límite exacto,
retención del worker, desconocido con gracia y dos tenants antes de integrar.

## WhatsApp: entrada, vinculación demo y Flow son fronteras distintas

Contrato acotado el 19-sep. WA0 `478d082` solo resuelve sin efectos; no acredita
atención ni congela el código. La futura aplicación debe verificar dentro de
la misma transacción el tenant/código esperado y el ticket, sin volver al
resolver legacy después de admitir un tenant distinto. La repetición del mismo
evento no puede repetir usos o reiniciar otra vez la conversación. El reset
real de demo vive en WhatsApp: una vinculación atómica no lo cubre por sí sola.

Resolver el negocio antes de descargar/transcribir audio o tratar `nfm_reply`.
Conservar la entrada para el equipo aunque no pueda automatizarse; estado de
plantillas, acuses y ecos humanos no se suprimen por ser parte del mismo lote.
Cada mensaje conserva su identidad opaca y fecha original de Meta; metadatos
ausentes, inválidos o futuros no se sustituyen por una fecha nueva que conceda
permiso. La pausa y su versión invalidan trabajo anterior aunque llegue después.

La [política de WhatsApp](https://whatsappbusiness.com/policy/) permite respuestas
libres dentro de las 24 horas desde el último mensaje del usuario. Es una ventana
de respuesta, no un TTL universal de plantillas. No trasladar los 120 segundos
del adaptador HTTP a WhatsApp: los 120 minutos del estado conversacional local
y las seis horas del token Flow también resuelven problemas diferentes. Si se
introduce un presupuesto de worker, fijarlo en la primera recepción sin renovarlo
en cada reentrega. No se ha verificado una duración exacta de reentregas de Meta.

Flows queda como subcorte explícito: el token debe estar ligado durablemente a
tenant, teléfono y versión de atención. Una reactivación no resucita un token
invalidado. Para un token que ha dejado de ser válido, el
[ejemplo oficial de Meta](https://github.com/WhatsApp/WhatsApp-Flows-Tools/blob/main/examples/endpoint/nodejs/basic/src/server.js#L57-L70)
devuelve HTTP 427 y el cuerpo cifrado `{"error_msg":"..."}`; no una pantalla
`SUCCESS`. Esto acredita el contrato de interfaz, no ausencia absoluta de
reintentos. Si la autoridad no puede comprobarse, falta definir y probar su
respuesta específica; no confundir incertidumbre con invalidez confirmada.

Los envíos finales y cada fragmento tienen admisión propia. Una supresión no se
convierte en `False`, fallo del proveedor ni disculpa automática por otro canal.
El reply humano requiere permiso del servidor vinculado a usuario, tenant,
conversación y destinatario; un flag del modelo o ausencia de contexto no lo
acredita. Automatismos sin contexto siguen pendientes de la fase 3.

## Voz: cerrar una sesión requiere una identidad conocida por el servidor

Auditoría de código y documentación oficial del 19-sep, sin llamadas a proveedores:
el widget actual recibe un secreto efímero y abre WebRTC directamente; descarta
el encabezado `Location`. Impedir otro secreto no cierra las sesiones abiertas:
la [caducidad del secreto](https://developers.openai.com/api/reference/resources/realtime/subresources/client_secrets/methods/create)
no determina la duración de las sesiones y el mismo secreto puede crear varias.

La adaptación propuesta conserva WebRTC: el navegador entrega su oferta SDP a
Vantelia y el servidor usa la [interfaz unificada de llamadas](https://developers.openai.com/api/docs/guides/voice-webrtc?api=realtime#connecting-using-the-unified-interface).
Vantelia captura el `call_id` de `Location`, lo vincula a tenant y versión, y solo
entonces devuelve la respuesta SDP. Un ID informado por el navegador no garantiza
el inventario completo de sesiones. Revalidar también al acabar la negociación;
si se pausó, no entregar la respuesta y solicitar el cierre de la llamada creada.

El [hangup de Realtime](https://developers.openai.com/api/reference/resources/realtime/subresources/calls/methods/hangup)
admite WebRTC y SIP, pero un 200 inicia el cierre: no acredita por sí solo silencio
instantáneo ni vaciado del audio que ya recibió el navegador. Registrar por separado
solicitud, aceptación y cierre comprobado. La
[conexión lateral del servidor](https://developers.openai.com/api/docs/guides/voice-server-controls?api=realtime)
permite supervisar una llamada conocida; todavía debe probarse la señal concluyente
de terminación con nuestro recorrido. No atribuir a Realtime los eventos de cierre
de otra API. Las sesiones antiguas cuyo ID no conocemos siguen siendo un límite
explícito, no una pausa verificada. Esta integración de voz sigue pendiente.

## Recepción durable de WhatsApp: siguiente corte, todavía sin conectar

Reutilizar `whatsapp_inbound_messages`. Su marca actual trunca el ID a 160
caracteres, no conserva fecha Meta ni contenido, y no acredita procesamiento
terminado. Las filas existentes siguen siendo marcas legacy, sin completar sus
datos con `now` o con el tenant resuelto hoy.

- Captura nueva: versión, clave SHA256 de hub e ID completos, ID original,
  huella y contenido canónico del mensaje individual, fecha Meta validada,
  resolución inicial inmutable y ticket. Primera recepción y fecha del evento
  son datos diferentes. El diario de operaciones no guarda contenido ni teléfonos.
- Firma sobre bytes originales primero. Buscar un replay antes de resolver el
  tenant actual; repetir la comprobación bajo `BEGIN IMMEDIATE`. Crear captura y
  ticket con la autoridad común en un único commit, sin binding, CRM, audio,
  Flow o modelo. El tenant original permite consultar el resultado conocido de WA1.
- Misma identidad con contenido distinto es conflicto. Marca legacy coincidente
  es una barrera conservadora, nunca permiso para reprocesar. Sin ID/hub válidos
  no inventar identidad. Fecha ausente, inválida o futura no autoriza automatizar;
  conservar el contenido identificable para tratamiento humano.
- Captura y reclamación del worker son contratos distintos. Un mensaje marcado
  antes de una caída no acredita que se haya atendido, ni autoriza repetir efectos.
  La vigencia técnica se fija una vez por política explícita del adaptador;
  no se deduce de las 24 horas de respuesta libre ni se renueva en cada entrega.
- Proyectar al inbox de forma idempotente y con la fecha Meta: si la proyección
  usa recepción local, falsearía la ventana de respuesta. Guardar payload por sí
  solo no acredita visibilidad en el panel. Estados/plantillas/ecos del lote siguen
  independientes de que una entrada conversacional resulte suprimida.

Diseño revisado; migración y adaptador aún no implementados. Al conectar, sustituir
el marcador anterior, no ejecutar dos mecanismos de captura en paralelo.

## Identidad de avisos antes de WhatsApp o voz multiherramientas

El agente permite cancelar A y crear B en un turno. Con contexto de atención, dos
emails distintos colisionarían hoy en `smtp_cliente/fragmento 0`. El recorrido
HTTP actual termina tras una gestión y no alcanza esa combinación; WhatsApp y voz
todavía no instalan el contexto. Corregir antes de conectar esos capturadores.

Usar identidad del aviso persistido (cita + generación + tipo; pago + tipo) en el
diario común. Dos avisos distintos pueden compartir canal y número de fragmento;
el mismo aviso conserva su identidad entre tickets. Mantener huella de bytes y
MIME estable, y revalidar cada emisión física. El ámbito interno solo transporta
identidad, sin permiso ni owner de otra operación. Conservar las decisiones del
registro de entregas y su respaldo tras incertidumbre; no improvisar contadores
ni confundir la admisión de la reserva con autorización de todos sus avisos.

Este corte se prepara en rama aparte mientras corre la suite del candidato HTTP.
No está integrado ni probado todavía.

## Primera entrega pequeña y cierre posterior

Límite confirmado por lectura del recorrido libre: su guardia de cancelación
comprueba la intención general, no una aceptación persistida por cita. «Cancela A»
y dos tools para A/B no acreditan que B esté autorizado. Cambiar la clave de
mutación a acción + booking_id permitiría esa ampliación; no se hará para resolver
una colisión. El recorrido guiado sí dispone de identidad de propuesta aceptada,
pero el libre no la transmite al núcleo. Antes de admitir varias mutaciones de la
misma clase, fijar una aceptación del servidor por tenant, conversación, sujeto,
acción y objetivo; la huella de payload detecta conflicto, no autoriza. Mientras
tanto se conserva el límite. Crear/mover en WhatsApp con remate_manual produce
propuestas; no se atribuyen a ese recorrido dos efectos físicos por las tools.

WA2a puede avanzar independientemente: captura y ticket durables con identidad,
origen y resolución originales, sin conectar aún el manejador vivo ni ampliar
la autorización de sus operaciones.

Primer commit completado: migración, autoridad persistida y transición por versión;
pruebas deterministas de aislamiento y reinicio. La lectura HTTP administrativa
se incorpora con la operación posterior, no se expuso en esta primera entrega.
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

La evidencia de la autoridad está en `E:/Vantelia-astra-pausa-evidencia/FASE1.md`.
No hay medición real de Meta, voz o Stripe para este bloque. Las referencias de
líneas son de la base leída: ajustar al candidato integrado antes de implementar.
