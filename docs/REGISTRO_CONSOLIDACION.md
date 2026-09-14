# Registro de consolidación de Vantelia

Horas locales Europe/Madrid. Cada entrada distingue hechos verificados, trabajo
activo y esperas. No es un registro de producción ni acredita aceptación final.
No guardar conversaciones, teléfonos, credenciales o datos personales.

## 2026-09-13 01:15 +02:00 — inicio de continuación nocturna

- Pablo autoriza continuar autónomamente el plan y registrar avances con hora.
- Candidato 7ab7775: suite finalizada con 2297 passed, 1 skipped, duración 18 min 55 s; fin 13-sep 01:04 Europe/Madrid; revisión
  solicitada automáticamente. Evidencia: `integrado-wa-suite.result.json` y
  `integrado-wa-suite.log` en C:/Users/pabli/.codex/vantelia-coordination/.
- Claude está sin cuota hasta las 04:00; revisión y calendario esperan. Avisado
  por Sincronía del reparto para evitar duplicados. No implica revisión aprobada.
- Nueva rama astra/gestion-confirmada en E:/Vantelia-astra-gestion; se conserva
  astra/whatsapp-recuperable intacta y no se tocan cambios ajenos.
- En ejecución: agente auxiliar implementa confirmación persistida de cancelación
  WhatsApp; otro inventaría evidencia de banco y requisitos de QA aislada.
- Seguimiento existente actualizado cada 30 minutos para retomar este registro;
  no duplica tareas activas ni consulta repetidamente las suites.
- Pendiente: resto de gestión/canales, recordatorios, entregas y reconciliación,
  banco comparable Alicia/otro, revisión exacta y aceptación real. Sin push ni
  despliegue; no se inventa la política particular de foto/diagnóstico de Alicia.

## 2026-09-13 01:18 +02:00 — referencia real y siguiente prueba

- Auditoría de artefactos saneados: los 42/43 y 43/43 históricos no contienen
  juntos SHA, configuración, calendario y ambos intentos; no se adoptan como
  referencia comparable. No se localizó copia saneada autorizada ni segundo tenant.
- El banco sobrescribe el primer fallo al reintentar. Se encarga conservar ambos
  intentos en salida JSON opcional y verificar el corte existente de envíos externos,
  sin modificar calendario ni criterios de evaluación que trabaja Claude.
- QA de navegador aislada preparada: dependencias verificadas, tenant temporal y
  comunicaciones desactivadas. Se ejecutará una vez sobre 7ab7775; aún sin resultado.
- Caso de cancelación identificado: un recordatorio contiene el id estable de la
  cita; si el portal la mueve, el botón antiguo puede cancelar la nueva fecha sin
  mostrarla. La propuesta nueva mostrará la cita actual y vinculará la aceptación
  al snapshot consultado. No es una regla particular del negocio.

## 2026-09-13 01:22 +02:00 — QA visual parcial sobre 7ab7775

- Primer arranque 01:19:21–01:19:34, exit 1: llama_index intentaba descargar
  punkt_tab ya instalado al buscar el recurso antiguo punkt. Sin navegador.
- Único reintento autorizado de arranque: 01:20:59–01:22:46, exit 1, SHA intacto.
  El lanzador externo resuelve únicamente esa comprobación con el recurso local;
  dotenv y conexiones Python externas siguen desactivados.
- Pasan acceso, resumen, servicio de retención y centros, Ventas, Informes,
  filtros/gráficos/modal, responsive y apertura de Nueva cita con autocompletado.
- Falla el instrumento al esperar franjas del domingo cerrado antes de avanzar
  al lunes. No se mide selección de hora, arrastre ni persistencia de duración.
  No se cambió código ni se repitió el escenario tras el fallo del navegador.
- Evidencia y límites completos en ACEPTACION_CANDIDATO_IA.md; logs y resultados
  `portal-7ab7775*` en la carpeta externa de coordinación. Pendiente corregir
  explícitamente la fecha del instrumento y validar el recorrido restante.

## 2026-09-13 01:26 +0200 - revision independiente del banco

- Primera entrega: 3 regresiones rojas y 1 control verde contra originales; 20 dirigidos verdes con el cambio. No es una medicion real.
- Revision detecta que no poder preparar una cita fixture se contaba como fallo del asistente sin conversar. Se corrige como NO MEDIDO, separado de conversaciones que fallan.
- Se pide validar destino del informe antes de gastar modelo y guardar evidencia parcial atomicamente por caso. El manifiesto sigue siendo resumido; no acredita por si solo comparabilidad total ni anonimiza respuestas.
- QA del portal: arreglo del dia revisado por otro agente, nueva ejecucion aislada en marcha sobre rama gestion con cambios sin commit, registrada en portal-gestion.*. No se presenta como validacion de un SHA limpio.

## 2026-09-13 01:27 +02:00 — QA corregida, recorrido completo verde

- Revisado el cambio mínimo: avanzar al día abierto sembrado antes de Nueva
  cita y comprobar su fecha; no desactiva cierres ni elimina comprobaciones.
- Nueva ejecución autorizada en gestión: 01:25:59–01:27:14, exit 0. Base f317e06
  con árbol sucio y concurrente, no candidato exacto. Evidencia `portal-gestion*`.
- Pasa todo el guion; cita arrastrada de 20 a 45 min con altura y persistencia
  comprobadas. Se conserva el fallo anterior; no se repite este verde.
- Inventariados dos casos de recordatorios aún NO REPRODUCIDOS: omitido+fallido
  que marca enviado y duplicación entre ejecutores/reinicio. Detalle en aceptación.

## 2026-09-13 01:38 +0200 - commits y trabajo independiente

- e49f29d guarda correccion del domingo en QA; 44ac6de guarda banco revisado con checkpoints por intento y precondiciones NO MEDIDO. Ultimo cierre del informe: 10 pruebas verdes, tras 25 de informe/calendario (selecciones solapadas).
- Cancelacion: 5 regresiones iniciales, 4 de resultado desconocido, mutacion de precondicion y 2 de perdida por menu fallan antes del arreglo. 86, 13 y 69 dirigidos verdes en grupos solapados; ultima revision detecta bypass tras intervencion humana, en correccion. Todavia sin suite completa nueva.
- Auxiliar inicia reproduccion/arreglo de recordatorio marcado enviado cuando email se omite y WhatsApp falla, en worktree separado astra/recordatorios-fiables base44ac6de. Concurrencia queda pendiente, no resuelta por este arreglo.
- Claude avisado por Sincronia; referencia real y copia saneada/configuracion de dos negocios solicitadas formalmente, esperan su disponibilidad.

## 2026-09-13 01:44 +0200 - recordatorios reproducidos

- 3 regresiones rojas demuestran marca de enviado sin aceptacion cuando email se omite y WA falla. Corregido en worktree independiente; 31 pruebas verdes y 1 xfail estricto, revision/integracion pendientes.
- Xfail reproduce dos ejecutores enviando antes de escribir timestamp. No esta arreglado; exige registro duradero por aviso/canal y tratamiento de resultado desconocido.
- No ha habido ninguna entrega Meta ni conversacion de modelo real; el objetivo de mejora comparada sigue pendiente.

## 2026-09-13 01:52 +0200 - candidato integrado para suite

- Cancelación 9ede4f9: último hallazgo de saludo tras atención humana cerrado, 1 rojo previo + control verde, 57 dirigidos verdes y revisión independiente OK.
- ff59b06 de recordatorios revisado e integrado mediante merge limpio a83021c. La carrera entre ejecutores permanece como xfail explícito.
- Banco revisado en 44ac6de y guarda de rutas f4ad515; QA guardada en e49f29d. Sin push ni despliegue.
- Se prepara una sola suite completa mediante validar-gestion.py; el SHA exacto, horas y resultado quedarán en gestion-suite.result.json, junto al .log, en C:/Users/pabli/.codex/vantelia-coordination/. Solo se pide revisión automática tras verde y árbol intacto. Este registro previo no afirma que la suite haya terminado.
- Siguiente trabajo independiente: reclamar recordatorios por generación/aviso/canal antes de enviar, preservar aceptaciones y tratar incertidumbre. El candidato de gestión se conservará estable para validar.

## 2026-09-13 01:56 +0200 - suite activa y siguiente fase

- Suite única lanzada sobre 2235d25452189a2dfcaf9bb4956f5adb8415261d limpio, en E:/Vantelia-astra-gestion; sesión 20917. Resultado/horas en gestion-suite.result.json y log externo. No consultado periódicamente; no se afirma todavía verde.
- Worktree de recordatorios actualizado limpiamente a rama astra/entregas-recordatorios, hija de 2235d25. Auxiliar diseña registro por generación/aviso/canal; otro contrasta resultados Meta con la interfaz existente. No se escriben reglas del negocio en los canales.
- Tras nueva suite verde y solicitud de revisión exacta, el lanzador sustituirá solamente nuestra petición pendiente del antecesor 7ab7775 verificado, para evitar repetir validaciones. Sustitución no equivale a aprobación.
- Banco real/copia saneada/segundo negocio y revisión de Claude esperan. No hay push, despliegue ni mensajes a clientas.

## 2026-09-13 02:16 +0200 - suite roja y revisión del hijo

- Coordinación verifica gestion-suite.result.json: 2235d25 terminó a las 02:15:01,
  exit 1, 2347 passed, 1 skipped, 1 xfailed y dos fallos de cancelación. No se pidió
  revisión automática y no se repite esta suite mientras se estabiliza el hijo.
- Transporte c1db689 revisado: 29 pruebas propias verdes y 56 relacionadas,
  selecciones solapadas. Resultado incierto no habilita fallback, se conservan
  IDs parciales y aceptación tras cerrar el cliente. No acredita entrega real al teléfono.
- Ledger y copia/informe están sin commit. Ledger: 66 dirigidas y 2 de plantilla
  verdes antes del hallazgo de pérdida de auditoría/tope tras guardar aceptación;
  evidencia_real lo cierra. Guard: 6 rojas previas y 21/8 verdes antes de extender
  protección a sidecars del informe y normalizar rutas con ~; gestion_implementacion
  lo cierra. La revisión final de ambos sigue pendiente, sin suite nueva del hijo.
- Xfail de duplicación retirado solo en las pruebas del hijo en desarrollo; no
  se atribuye ese cambio ni sus verdes a 2235d25.
- Siguiente bloque de instrumentos: humo/simulador consultan el helper tras
  añadir el turno de la clienta y conservan confirm_yes sin identidad; el caso
  crítico del banco solo verifica texto Resumen/Confirmamos, no cita ni botón.
  Reproducción pura del orden encargada, sin modelo; no se editan casos calendario.
- Agenda: coordinación verificó eje y cuartos ya implementados en app_ui/index.html
  (`CD_AXIS_STEP=15`, escala común 2,2 px/min). Falta aserción geométrica específica
  en el siguiente QA del SHA exacto; no se rehace diseño ni se repite suite ahora.

## 2026-09-13 02:20 +0200 - protección del banco cerrada

- 09aebfc guarda solo script del banco y test de copia segura. Revisión independiente
  OK; 27 dirigidas verdes finales, tras 6 rojas iniciales y 5 nuevas de sidecars/~.
- Normalización compartida para copia, aislamiento e informe; compara identidad de
  archivo y protege DB/WAL/SHM antes de borrar o escribir. Origen de solo lectura
  abierto antes de limpiar el destino, sin crear una BD vacía si desaparece.
- Ledger aún sin commit: se está cerrando aceptación y evento del tope en una
  misma transacción. validar-entregas.py se prepara externamente, todavía sin
  ejecutar. Los dos fallos de cancelación de 2235d25 siguen pendientes de cierre.

## 2026-09-13 02:23:57 +0200 - ledger revisado, cierre dirigido verde

- 16 pruebas dirigidas verdes en 54,28 s tras un rojo válido del caso de pérdida
  de auditoría (02:21:37, contador 0 en lugar de 1). Revisión independiente OK.
- CAS de aceptación y evento que alimenta el tope comparten transacción. Caída
  tras commit conserva contador e identidad, recuperación sin nuevo POST. El
  nombre auditado es el de la plantilla realmente enviada, tomado del payload.
- Sigue sin commit ni suite integrada nueva. No se amplía a reconciliación de
  incertidumbre, cupo entre citas distintas, ventana durante I/O ni fallback email.
- El autor pasa a reproducir los dos fallos de cancelación de la suite 2235d25;
  el candidato siguiente todavía no se declara estable para validación completa.
- Después del cierre, b5fa459 guarda solo los seis archivos del ledger. Transporte
  c1db689 y guard 09aebfc ya estaban guardados y revisados. Pendiente contrato de
  cancelación, relevo final y suite exacta del candidato siguiente.

## 2026-09-13 02:27:09 +0200 - contrato de cancelación cerrado

- Los dos fallos de 2235d25 se reprodujeron a las 02:25:27 con el mismo error.
  Ambos tests esperaban cancelar tras código o botón del recordatorio. Ahora
  verifican cita confirmada tras oferta y aceptan el cancel_yes:<id> realmente
  emitido antes de comprobar cancelación; se mantienen los controles de identidad.
- 34 dirigidos verdes en 32,06 s (dos tests y contrato de cancelación), revisión
  independiente OK. ca8e626 guarda exclusivamente los dos tests; no cambia producto.
- Transporte c1db689, guard 09aebfc y ledger b5fa459 revisados. Preparada una suite
  exacta del próximo SHA limpio con validar-entregas.py; ledger-suite.result.json
  y .log conservarán identidad/horas/resultado. Aún no está iniciada.
- Siguiente trabajo independiente: rama hija de formularios y harness con IDs
  vigentes, manteniendo intacto el candidato que se mida. No se cierra fase 5 ni
  se afirma medición real del modelo/Meta. Sin push, despliegue o revisión nueva.

## 2026-09-13 02:29:58 +0200 - suite exacta activa y rama de formularios

- Inicio real 2026-09-13T02:29:58.587437+02:00, SHA limpio
  de3d6d00e22e6f089055a1370c23fe9831205c8d, sesión 35696, validar-entregas.py en
  E:/Vantelia-astra-recordatorios. Coordinación leyó solo metadata inicial de
  ledger-suite.result.json; no se consulta otra vez hasta cerrar el bloque.
- astra/formularios-confirmados en E:/Vantelia-astra-formularios parte de ese SHA
  para el trabajo independiente. gestion_implementacion: formularios a propuesta
  compartida, identidad tenant/teléfono y replay sin crear directamente.
  evidencia_real: captura de botones reales y orden de turnos en instrumentos;
  Astra: revisión y relevo. No se toca el árbol que está ejecutando la suite.
- El arnés no debe deducir consentimiento ni fabricar IDs; tampoco se crea otra
  autoridad de reserva en el formulario. Los diseños están en contraste, aún
  sin evidencia verde nueva ni implementación declarada terminada.
- Banco real comparable de dos negocios, foto/diagnóstico y QA exacta de geometría
  siguen pendientes. Eje/cuartos ya existen; falta su verificación visual exacta.
  Sin cambio de casos calendario, push, despliegue ni envío a clientas.

## 2026-09-13 02:37:51 +0200 - QA visual exacta y discrepancia de etiqueta

- Una ejecución externa sobre de3d6d00e22e6f089055a1370c23fe9831205c8d,
  02:36:26–02:37:51, exit 0, árbol limpio e idéntico antes/después. Aislamiento
  temporal, dotenv desactivado, Python y Chromium sin red externa; Google Fonts
  recibe CSS vacío local, con tipografía de sistema. No se toca el candidato.
- 37 ticks, 10 horas (8 visibles), una columna: 15 min/33 px entre ticks,
  tres interiores por hora y alineación con líneas dentro de 1 px. El recorrido
  completo conserva duración de 45 min al arrastrar y termina sin errores capturados.
- Evidencia externa portal-ledger: .result.json, .geometry.json, .log,
  .agenda.png y .cuartos.png. SHA256 del instrumento en disco:
  20f3716cce7aa01fe9e7d5148d27b5c3d422dea05669154ffbc048a7b44cdff7.
  El hash preliminar dcb773… era texto LF antes de escribir CRLF; el artefacto
  ejecutado y su resultado conservan el hash anterior completo.
- La captura muestra etiqueta 20 min aunque bloque y BD son 45. Después se
  corrigió en 23139ca: cdServiceMeta reutiliza cdDur sin fallback de slot para
  datos ausentes; el dibujo mantiene su fallback y el precio se conserva.
  Prueba Node sobre funciones reales: roja 20 frente a 45, verde tras arreglo,
  controles de catálogo, precio, datos ausentes/fechas inválidas y fallback.
- La QA del repo ahora compara el token exacto de duración con la BD para que
  145 no pase como 45. No se ejecutó de nuevo navegador ni suite tras el cambio;
  la captura antigua no acredita la etiqueta corregida.

## 2026-09-13 02:49:33 +0200 - instrumento de botones explícitos revisado

- 23 dirigidos verdes en 37,45 s. El ID legacy produjo antes cero citas frente
  a una esperada; la captura previa falló con botones en diccionario y ofrecía
  un cuarto botón descartado por el producto (dos rojos a las 02:47:36).
- La captura reutiliza el builder real y registra el payload normalizado. El
  transporte falso tipado se instala solo durante esa llamada y se restaura;
  el spy de HTTP verifica ausencia de salida. La captura repetida conserva las
  referencias originales y no contamina la anterior.
- `botones-explicitos-v1`: entrada textual sigue siendo texto. La acción
  estructurada exige botón emitido al tenant/destinatario y propuesta ofrecida
  con el mismo ID; no fabrica consentimiento. Humo y simulador usan este
  contrato, sin cambiar los casos calendario. No se comparan porcentajes de
  informes históricos de otra versión. Revisión independiente OK; coordinación
  autoriza guardar únicamente los cinco archivos del instrumento.
- La prueba sintética verifica efecto en agenda sin modelo/Meta. El banco real
  crítico sigue pendiente de medir efecto final con la misma versión antes y
  después; este verde dirigido no cierra fase 5 ni acredita transporte real.
- Revisión de formulario: preparación compartida extraída del núcleo y
  profesional/centro consultados quedan fijados antes del resumen; no se
  reasigna al pulsar si se ocupa después. Espera al cierre dirigido del autor.
  Riesgo preexistente siguiente, identificado por lectura y sin ejecución:
  snapshot/huella no incluyen términos económicos ni duración, mientras el
  núcleo vuelve a resolver catálogo/política. Probar cambio de condiciones
  entre oferta y botón y cerrar el contrato en la preparación compartida.

## 2026-09-13 02:52:25 +0200 - relevo del cierre dirigido de formulario

- Coordinación confirma 66 passed en 92,44 s y revisión independiente OK del
  formulario. El autor está guardando producto/tests; no se anticipa su SHA.
  Token ligado a tenant/teléfono, replay y propuesta compartida, disponibilidad
  consultada en el núcleo y profesional/centro fijados antes del resumen.
- Arnés guardado en 2533fe9. Cinco fixtures heredadas siguen en adaptación por
  evidencia_real para usar agenda válida tras la revalidación común; después
  se revisará ese diff sin repetir sus dirigidos.
- La suite del hijo aún no se ha iniciado. La rama congelada de entregas queda
  intacta y coordinación consultará su resultado al cerrar producto, sin sondeos
  periódicos. Términos económicos cambiantes siguen como próximo bloque con
  regresión antes del arreglo. No hay modelo/Meta reales ni fase 5 cerrada.

## 2026-09-13 02:52:00 +0200 - resultado exacto de entregas verificado al cierre

- Coordinación comunica cierre de de3d6d0 a las 02:52:00.149448 +02:00:
  exit 1, 2401 passed, 1 skipped, 1 failed, sin xfail. Único rojo documental:
  test_mapa_del_codigo_no_miente.py:125 detecta que ARQUITECTURA no nombra
  notice_deliveries. Evidencia: ledger-suite.result.json y .log externos.
- Se añade el módulo a arquitectura y el recorrido de reclamación al mapa en
  la rama hija. El candidato congelado no se modifica; no se relanza suite
  completa ni se solicita revisión formal. Este resultado no es verde.
- Formulario guardado en 99fdaf1; cinco fixtures heredadas siguen pendientes.
  La suite del hijo no está iniciada. Se validará únicamente el test del mapa
  para cerrar esta omisión documental.

## 2026-09-13 02:55:11 +0200 - omisión del mapa corregida

- Dirigido tests/test_mapa_del_codigo_no_miente.py: 5 passed en 3,03 s,
  una advertencia del manejador de excepciones de Trio. Log externo
  mapa-notice-deliveries-verde.log; dotenv desactivado y sin caché de pytest.
  El rojo previo está en la suite exacta de3d6d0; no se repitió esa suite.
- Documentación preparada para relevo: arquitectura/módulo, mapa/recorrido,
  QA exacta y corrección UI separadas, arnés 2533fe9 y formulario 99fdaf1 con
  sus dirigidos. Las fixtures heredadas y la suite del hijo siguen pendientes;
  no se declara aprobación formal, medición real ni despliegue.

## 2026-09-13 - revisión de fixtures y límite de comparación del arnés

- Autor confirma 38 passed a las 02:55:28 en cinco archivos; siete rojos previos
  y un control antes verde. Revisión independiente OK: agenda real con servicio
  en vez de fechas caducadas, configuración sintética completa y mismos guards.
  El caso sin fianza exige resumen presente para no pasar por rechazo temprano.
- Brecha comprobada por lectura, pendiente de cambio: CapturaEnvios.opciones
  requiere la API de propuesta persistida y filtra estado ofrecida/IDs actuales.
  Un botón que se emitió pero ya es inválido nunca llega al producto. Esta
  versión no demuestra rechazo productivo de acciones obsoletas ni comparación
  con una baseline sin esa API/protocolo. No se presenta como compatible.
- Próxima fase del instrumento: transportar acciones explícitas emitidas y
  comprobar después el resultado y autorización del producto, sin convertir
  texto en click. No se modifica ahora ni bloquea la adaptación de fixtures.

## 2026-09-13 02:59:43 +0200 - candidato de formularios preparado para congelar

- 891a730 guarda las cinco fixtures revisadas, con 38 dirigidos verdes. El
  candidato incorpora formulario 99fdaf1, arnés 2533fe9, UI23139ca y mapa c4d4f6a;
  las selecciones dirigidas se solapan y no equivalen a nueva suite completa.
- Relevo final en ESTADO/PLAN/ACEPTACION/REGISTRO y cobertura en tests/README.
  Runner externo preparado, suite del hijo todavía NO iniciada. Coordinación
  congelará este SHA limpio antes de una única ejecución exacta.
- Siguiente rama hija: términos efectivos aceptados (regresión antes) y arnés
  que observe acciones explícitas/efectos sin anticipar la autorización del
  producto. Compatibilidad con baseline antigua no demostrada. QA de etiqueta
  corregida aún pendiente; no repetir la QA de3d6d0 ni atribuirle el arreglo.
- No revisión formal nueva, modelo/Meta reales, push o despliegue. Se conserva
  el rojo documental de la suite exacta de entregas como resultado histórico,
  junto al dirigido verde que corrige el mapa en este hijo.

## 2026-09-13 03:00:44.987 +0200 - suite de formularios activa y rama de condiciones

- Una lectura de metadata de formularios-suite.result.json confirma inicio
  Unix 1789261244.9869745 (hora del encabezado redondeada a ms), head
  2cb8a029e70ac28b1ffdbee6eb750b6304909946. Suite en sesión 56124 sobre
  E:/Vantelia-astra-formularios congelado. No se consulta progreso ni resultado
  hasta el cierre del bloque; no se modifica ese árbol.
- Nueva rama astra/condiciones-confirmadas en E:/Vantelia-astra-condiciones.
  gestion_implementacion: preparado versionado de términos efectivos, resumen,
  cotejo antes de ejecutar, recuperación primero y guardado/checkout sin
  redefinir la condición aceptada. Sin impuestos/recargos nuevos ni Stripe real.
- evidencia_real: instrumento observa botones emitidos y efectos; el producto
  valida estado/autorización. Demostrar compatibilidad de transporte/IDs previos
  sin HTTP, sin atribuir todavía comparación histórica ni éxito real.
- Astra revisa ambos diseños/diffs y mantiene este relevo. Todavía no hay nuevos
  verdes ni implementación aceptada en esta rama. QA exacta de etiqueta 2cb8a029
  se puede preparar con aislamiento previo; no se ha ejecutado ni se repite de3d6d0.

## 2026-09-13 03:06:56 +0200 - QA exacta de etiqueta y geometría terminada

- Una ejecución justificada por UI23139ca sobre el candidato limpio
  2cb8a029e70ac28b1ffdbee6eb750b6304909946: 03:05:16.492–03:06:56.229 +02:00,
  exit 0, mismo SHA/árbol limpio antes y después. No se consulta la suite.
- Aserción nueva compara token exacto «45 min» de etiqueta con duración BD45.
  Captura inspeccionada: «Corte señora · 45 min · 18 €». Se mantienen recorrido
  completo, 37 ticks cada 15 min/33 px, tres interiores por hora, alineación y
  diez horas (ocho visibles), sin errores capturados.
- Artefactos externos portal-formularios: .result.json, .log, .geometry.json,
  .agenda.png, .cuartos.png. SHA256 del instrumento ejecutado en disco:
  260a58b8407d5b57efac534c748eca93c040f51b9daad21ba19919b41bdce4e1.
  Fuente exacta git verificada, datos/config temporales, dotenv desactivado,
  Python/Chromium solo loopback. Dos peticiones Google Fonts impedidas con CSS
  vacío; tipografía de sistema. Sin modelo/Meta ni otros servicios reales.
- Esta evidencia nueva sí valida etiqueta corregida; no se atribuye a la QA
  anterior ni se repite ninguna QA verde. Términos/arnés de la nueva rama siguen
  en implementación; no hay suite final consultada ni aceptación global.

## 2026-09-13 09:10–11:15 +0200 - Claude toma el relevo como principal

Decisión de Pablo: Astra no disponible una semana (sin créditos hasta 19-sep
11:24). Claude continúa sobre el candidato descendiente, en E:/Vantelia (único
árbol con credenciales para medir con modelo real). Copias de Astra intactas.

- Candidato: `astra/condiciones-confirmadas` 6c3ad4f contiene todas sus ramas;
  rama de trabajo `claude/candidato`.
- Suite completa 6c3ad4f: 3 fallos / 2470. Arreglados en be6bec9 (servicio
  retirado al confirmar sin nombre ni selector; doble de test desfasado con
  `minutos=`/`terms=`). Suite completa be6bec9: **2473 passed, 1 skipped**.
- Banco sobre be6bec9: **0/41, falso**: "no such table: conversation_states".
  La copia de producción va una versión por detrás y los instrumentos no migran
  (el servidor sí, en `backend/main.py`). El humo del despliegue habría caído
  igual. 782a53f migra la copia en `evals/arnes` (compartido por banco y humo);
  test rojo sin el arreglo. Banco sobre 782a53f: **42/43**, 0 no medidos.
- Único rojo: `dice-que-si-y-acaba-en-cita`, fallo en los dos intentos. Leído en
  agent_turns: pregunta seis veces keratina/ácido láctico. Causa: el atajo
  deducido de Q&A se retiró (bien) y Alicia no tenía regla de orientación.
- Decisión de Pablo/Alicia (confirmada): quien no sabe qué alisado quiere →
  cita «Diagnóstico y presupuesto». Regla probada SOLO en copia.
- Con la regla, tres capas de bucle arregladas en 762800a: oferta repetida cada
  turno, propuesta no reconocida por `servicio_origen` acumulado, y entrada
  "propuesta" ausente en `_COMO_PEDIRLO`. 142 dirigidos verdes.
- Trampa detectada: regla con familia «alisado» no casa con «Keratina premium
  largo» (familias_pedidas → keratina). `regla_de_precio_para` ya lo resuelve
  con `_categoria_del_servicio`; `regla_de_orientacion_para` no. Siguiente.
- En curso: 6 tiradas del crítico con regla en copia sobre 762800a, separando
  primer intento / reintento / fallo. Sin despliegue ni cambios en producción.

## 2026-09-13 11:07–11:45 +0200 - el crítico sigue 0/6: causa localizada

- 6 tiradas sobre 762800a con la regla en copia: **0/6**, las 12 conversaciones
  fallan. Leídas en agent_turns: la oferta ya no se repite, pero el modelo nunca
  llama a `responder_propuesta`; solo `buscar_servicio` con falta=técnica.
- Descartado con lectura y datos: estado viejo en el canal (se recarga tras el
  agente), claves distintas (ambos usan teléfono/whatsapp), revalidación que no
  conozca orientación (la conoce), excepción tragada (no hay freno `revento`).
- Sonda turno a turno sin filtrar avisos (probe2): la propuesta es None en todos
  los turnos. En el turno 4 la rama SÍ entra y consulta la regla con
  "no lo tengo claro el 2026-09-15 a las 15": falta «alisado». El primer mensaje
  lo atendió el flujo de WhatsApp, no el agente, y `servicio_texto` empieza en el
  segundo; la `descripcion` del modelo sí lo lleva.
- 0442452: la regla de orientación casa también por categoría (trampa de
  familias), igual que la de precio. 25 verdes, dos rojos sin el arreglo.
- Arreglo en curso (sin commit): `agent._texto_de_la_duda` junta la descripción
  que buscó el modelo con lo acumulado. 116 dirigidos verdes; sonda con el arreglo
  y test rojo sin él pendientes.

## 2026-09-13 11:45–11:59 +0200 - la oferta sale; el «sí» escrito no la aceptaba

Rama `claude/candidato`. Sin despliegue ni cambios en producción.

- 38f931f: `agent._texto_de_la_duda` (descripción que buscó el modelo + lo
  acumulado). Test del recorrido con `responder` y doble de regla que solo casa
  si el texto dice «alisado»: rojo sin el arreglo.
- Sonda turno a turno con 38f931f sobre copia con la regla: turno 4 la regla
  casa, propuesta `ofrecida`, botones enviados. Turno 5 la clienta ESCRIBE «si»:
  nadie la acepta y el turno 6 vuelve a preguntar la técnica. El modelo tiene
  `responder_propuesta` y no la usa.
- Además: `_COMO_PEDIRLO["propuesta"]` (762800a) era código muerto; el agente
  solo inyecta `reserva.instruccion_de_cierre`, que no tenía esa rama.
- 3a899f8: botón y texto por un solo camino (`whatsapp._wa_contestar_propuesta`
  sobre `booking.contestar_alternativa_de_precio`). Un sí sin pega, normalizado
  sin tildes, se acepta por código SOLO si el último mensaje del asistente en la
  sesión fue la oferta (`intent = oferta_propuesta`); «sí, pero…», «no» o un sí a
  otra pregunta siguen en el agente. Rama "propuesta" enchufada en
  `instruccion_de_cierre`. Primer intento del test cazó un fallo propio: «Sí»
  con tilde no casaba (el resumen normaliza antes de llamar).
- Evidencia: `tests/test_si_escrito_acepta_la_oferta.py` 8 verdes; con el
  arreglo neutralizado, 4 rojos (los tres «sí» y la guía). 79 dirigidos verdes
  (propuestas, alternativa de precio, servicio retirado, mismo cerebro, duda,
  orientación por categoría). pyflakes limpio en backend.
- En curso: 6 tiradas del crítico sobre 3a899f8 (copia snap3_conregla, config
  viva cfg3, desde E:/Vantelia), separando primer intento / reintento / fallo y
  leyendo conversaciones.
## 2026-09-13 11:45 +0200 - términos, arnés y checkout retomados

- La suite congelada 2cb8a029 ya había terminado a las 03:23:06.385 +02:00 con
  2442 passed, 1 skipped y un único rojo de `test_banco_sin_meta`. El contraste
  dirigido de c9f19e6 pasa a las 03:30:44 con red externa bloqueada: la captura
  v2 no llama al payload original, así que el producto conserva la autorización.
  Esto no convierte la suite histórica en verde ni acredita modelo/Meta reales.
- 6c3ad4f guarda términos efectivos aceptados: 112 dirigidos verdes en 126,70 s
  y revisión independiente OK. Mantiene precio/fianza/decisión de pago sellados;
  no resuelve respuestas desconocidas de Stripe.
- 68c1fac persiste la clave de idempotencia de checkout antes de red y exige que
  respuesta y guardado local compartan esa clave. Se simuló caída local tras una
  respuesta Stripe: el reintento recibe la misma sesión sin una segunda creación.
  Una fila histórica sin clave ni URL devuelve 409 para reconciliación manual.
  `tests/test_condiciones_aceptadas.py`: 23 passed en 80,95 s; dos regresiones de
  checkout/Bizum verdes en 21,59 s. Sin llamada Stripe real, push o despliegue.
- Siguiente: congelar un SHA limpio con estos cambios y ejecutar una sola suite
  exacta; después, revisión exacta y banco real comparable. Siguen pendientes
  reconciliación operativa, recordatorios completos y evidencia Alicia/otro tenant.

## 2026-09-13 12:58 +0200 - relevo determinista tras propuesta aceptada

- La medición real de Claude sobre `1fe7a3e` fue reproducible pero roja en sus
  dos intentos: la alternativa de diagnóstico se aceptaba, pero no alcanzaba
  «Resumen de tu cita»/«Confirmamos». No se presenta como mejora ni como caso
  cerrado.
- Causa localizada en el canal: al no conservar la hora inicial para el servicio
  alternativo, WhatsApp enviaba huecos reales sin persistirlos; el nombre volvía
  al modelo sin opciones trazables. `8ca6088` guarda sólo los huecos enviados y,
  cuando fecha y hora ya están validadas, usa el paso existente `booking_name`
  antes del resumen. No inventa una hora ni una regla de Alicia.
- Regresiones dirigidas de propuesta, «sí» escrito y reserva conversacional
  finalizaron sin fallos en la caché de pytest; dos controles nuevos específicos
  del cambio también terminaron sin fallos. Falta una suite completa exacta, por
  lo que este commit no es candidato aceptado.
- Claude inició una medición real nueva del mismo caso sobre copia aislada; no se
  relanza ni se consulta repetidamente. Rama `astra/condiciones-confirmadas`
  subida con `8ca6088`; sin despliegue.

## 2026-09-13 12:00–13:30 +0200 - el crítico llega al resumen al primer intento (Claude)

Rama `claude/candidato`. Sin despliegue ni cambios en producción. Todas las series:
copia `snap3_conregla` (producción 13-sep 08:59 + regla de orientación de Alicia
declarada SOLO en la copia), config viva `cfg3`, desde E:/Vantelia, árbol limpio,
caso `dice-que-si-y-acaba-en-cita`, calendario resuelto al 2026-09-15. Cada fallo se
leyó en chat_messages/agent_turns antes de tocar código.

| SHA medido | Tiradas | OK 1.er intento | OK tras reintento | Fallo | Muro leído |
| --- | --- | --- | --- | --- | --- |
| 3a899f8 | 1 (parada) | 0 | 0 | 1 | el agente repetía la oferta con sus palabras; su «si» iba al modelo |
| 1fe7a3e | 6 | 0 | 1 | 5 | «a las 15» sin huecos no se anotaba; tras aceptar, horas otra vez |
| 197afb0 | 6 | 0 | 6 | 0 | 1.er intento: freno del precio sobre la propia valoración |
| e197dee | 6 | **6** | 0 | 0 | — resumen correcto en las 6: Ana Ruiz Perez, Diagnóstico y presupuesto, 15:00 |

- 1fe7a3e: `_wa_vuelve_a_ofrecer` y `booking.conservar_la_hora_dicha` (canal y
  `responder_propuesta`). Sus tests partían con la hora puesta a mano, estado que la
  conversación real no alcanza.
- 197afb0: `Estado.hora_sin_hueco`, resuelto al aceptar con `_hora_coloquial` contra los
  huecos del servicio aceptado. Tests construidos con los mensajes medidos.
- Astra, con cuota nueva: cherry-pick de lo anterior en `astra/condiciones-confirmadas`
  (para no perder 68c1fac), 8ca6088 (huecos enviados al estado; nombre por
  `booking_name` tras aceptar) y 7740b45 (docs). Coordinado por buzón.
- Fusiones en `claude/candidato`: 1b19d12 (68c1fac, 4703830), aa9638a (main: bd7a6da,
  02bd1a7, 5a23f21, lo desplegado) y la de 8ca6088/7740b45, sin conflictos de código.
  87 verdes en zonas fusionadas; pyflakes igual que main.
- e197dee: la valoración no se frena a sí misma (`es_servicio_de_valoracion`; la regla
  «Color y mechas» casaba con «Diagnóstico y presupuesto» por su categoría «Trabajos de
  color»); «en esta conversación» con el corte por silencio compartido
  (`agent._filas_de_esta_conversacion`; antes 30 mensajes del teléfono sin tiempo, y el
  del primer intento arrastraba 17 preguntas de precio del 22-ago); `booking_name` con
  `nombre_que_dice` (hallazgo de revisión de 8ca6088: guardaba «me llamo Ana Ruiz
  Perez»). 10 tests, 7 rojos sin los arreglos y 3 controles; 234 verdes relacionados.
- Evidencia por arreglo: rojo sin él (neutralizado) y verde con él en 1fe7a3e (6),
  3a899f8 (4), 197afb0 (3) y e197dee (7). Informes JSON por tirada en el scratchpad de la
  sesión; las copias de BD de las series se borran por llevar datos de clientas.
- Límites: un solo caso y un solo día de calendario; seis tiradas no fijan una tasa. La
  copia de producción guarda 64 sesiones de teléfonos del banco del 22-ago: los
  primeros intentos de mediciones anteriores pueden estar contaminados.
  `whatsapp._ya_se_le_dijo` sigue mirando 8 respuestas sin tiempo (solo añade un remate).
- Siguiente: suite completa, banco completo y humo sobre el SHA con este registro;
  después segundo negocio, informe de aceptación y orden de despliegue de Pablo.

## 2026-09-13 13:30–14:50 +0200 - suite, banco y humo del candidato; dos fallos que tocaban la agenda (Claude)

Rama `claude/candidato`. Sin despliegue ni cambios en producción. Mediciones con modelo
real: copia `snap3_conregla` (producción 13-sep 08:59 + regla de orientación de Alicia SOLO
en la copia), config viva `cfg3`, desde E:/Vantelia, árbol limpio y SHA estable de principio
a fin en todas.

| Medición | SHA | Resultado |
| --- | --- | --- |
| Suite completa | 5e9f8d7 | **2529 passed, 1 skipped**, exit 0, 25 min 14 s (13:31:41–13:57:03) |
| Humo (5 recorridos) | 5e9f8d7 | **5/5** llegan al final (cita, opción, precio→diagnóstico, cancelar, reprogramar) |
| Banco completo | 5e9f8d7 | 44 previstos, 1 no aplica, 43 medidos: **41 OK 1.er intento, 2 tras reintento, 0 fallos** |
| `cambiar-la-hora-de-verdad` ×6 | 6bed2f1 | **6/6 al 1.er intento**; una cita viva movida al 22-sep 18:30 |
| `dice-que-si-y-acaba-en-cita` ×6 | 6bed2f1 | **6/6 al 1.er intento**; resumen Ana Ruiz Perez / Diagnóstico y presupuesto / 15:00 |
| Banco completo | 6bed2f1 | 43 medidos: **41 OK 1.er intento, 2 tras reintento, 0 fallos** |
| `cambiar-la-hora-de-verdad` ×6 | 112b26c | **6/6 al 1.er intento**; una cita viva movida al 22-sep 18:30 en las 6 (leído en las copias) |
| Banco completo | 112b26c | 43 medidos: **42 OK 1.er intento, 1 tras reintento, 0 fallos** (12:26:42–12:45:31 UTC) |
| Suite completa | 112b26c | **2541 passed, 1 skipped**, exit 0, 22 min 47 s (14:26:44–14:49:37) |

- No aplica en Alicia: `precio-cerrado-si-se-dice` (no da precios por mensaje).
- Todos los primeros intentos fallidos se leyeron. Dos tocaban la agenda y se arreglaron:
  - 5e9f8d7, `cambiar-la-hora-de-verdad`: **la clienta perdió la cita**. Ya movida, dijo «vale,
    la primera opcion que me has dicho» y el modelo llamó a `cancelar_cita` para «crear otra»:
    cancelación ejecutada, creación frenada; en la copia, cancelada y ninguna otra. Crear sin
    pedir tenía freno; cancelar sin pedir, no. **6bed2f1**: `cancelar_cita` solo si ella lo pide
    en esta conversación (`reserva.pide_anular`) o el canal declara `intencion=cancelar`; si no,
    error a la tool y freno `cancelar_sin_pedirlo`. 1 rojo sin el freno, 7 controles; 211 verdes.
  - 6bed2f1, `cambiar-la-hora-de-verdad`: **«he reprogramado» sin mover nada**. Tras un rechazo
    por misma fecha y hora, el modelo repitió la llamada con `servicio` (el mismo, sin tildes) y
    la tool dio ok: la auditoría anotó `booking_updated` sin cambio. El control solo se aplicaba
    sin `servicio`. **112b26c**: el servicio cuenta como cambio solo si
    `booking._service_for_existing_booking` devuelve otro. 3 rojos sin el arreglo, 1 control;
    135 verdes. Con modelo real, en 4 de las 6 tiradas de 112b26c el modelo volvió a intentar
    la misma hora y la tool lo rechazó.
- Primeros intentos fallidos sin efecto en la agenda (pendientes de producto, no arreglados):
  - `recomienda-ante-un-problema` (5e9f8d7, 6bed2f1): a «se me cae mucho el pelo» sugiere
    alisados; en el reintento, color o mechas. Mala recomendación en los dos.
  - `pregunta-el-dia-en-vez-de-recitar` (112b26c): recita las horas del 15 sin preguntar el día.
- En 6bed2f1 el freno de cancelar no se ejecutó con modelo real (el modelo no intentó cancelar);
  lo cubre el test.
- Observado sin fallo: en reprogramar salta `se_acabaron_las_vueltas` en los dos primeros
  turnos y, al final, `dijo_que_hay_cita_sin_haberla`/`dijo_haberlo_hecho_sin_hacerlo` con la
  cita existente (posible falso positivo del freno).
- Copias de BD de todas las series y bancos borradas (datos de clientas); informes JSON en el
  scratchpad de la sesión.
- Siguiente: segundo negocio (metareview), cambio del portal a mitad de conversación, informe
  de aceptación y orden de despliegue de Pablo.

## 2026-09-13 14:50–15:35 +0200 - referencia de producción, segundo negocio e informe de aceptación (Claude)

- Referencia: código de bd7a6da extraído con `git archive` (sin `site_exports`/`hostinger_site`,
  rutas demasiado largas para un worktree) con el instrumento del candidato encima; solo se inyecta
  la clave del modelo desde E:/Vantelia/.env. Alicia: 43 medidos, 41 OK 1.er intento, 1 tras
  reintento, **1 fallo crítico** tras recalificar (el reintento aprobaba un resumen de ácido
  láctico a nombre de «clienta»). Candidato 112b26c: 42 + 1, 0 fallos.
- Una prueba de importación de `backend.main` en la referencia tocó `storage/vantelia.db` local
  (mtime 14:58:33; sin filas nuevas en `locations`): el arranque corre antes de redirigir la BD. No
  se repitió; el banco redirige la BD antes de importar la app.
- Segundo negocio `metareview`: sus datos RAG solo estaban en el servidor (copiados en solo lectura
  a una carpeta temporal). Primer intento contó 12 «fallos» por «No hay datos configurados»: el
  banco ahora no mide sin datos (ae7d9ff). Casos del salón condicionados a los datos del negocio y
  `{un_servicio}` en los genéricos, idénticos para Alicia (5f5e10c). Conversacional (en copia):
  referencia 16/16 y candidato 16/16. Guiado real: 12/16; 3 fallos por escribir en vez de pulsar
  listas/botones y 1 respuesta errónea (manicura).
- Criterio del crítico endurecido (00a7726). Informe completo en ACEPTACION_CANDIDATO_IA (13-sep).
- Siguiente: limpieza de copias con datos de clientas y orden de despliegue de Pablo.

## 2026-09-13 15:35–16:51 +0200 - cambios del portal y reinicios, dos revisiones y sus arreglos (Claude)

- 24a4a51: `scripts/medir_portal_y_reinicio.py`, seis escenarios con modelo real (vacaciones
  tras ofrecer el día, hora bloqueada y servicio retirado con el resumen delante, regla apagada
  tras ofrecer, reinicio a mitad de reserva y con el resumen delante). Cada intento sobre copia
  nueva de snap4_conregla (producción 13-sep 15:52 + regla de orientación solo en la copia),
  config cfg4. Tirada 15:55–16:13: 6/6 OK.
- Leídas las conversaciones: «hora bloqueada con el resumen delante» aprobaba en falso (se
  bloqueaban las 17:00 y el resumen estaba en las 18:00). c0bc746 bloquea la hora del resumen;
  ese escenario otra vez 16:27–16:28: OK. El juez tiene test con ese caso.
- En esa tirada salió un resumen a nombre de «Cliente»: el freno de apellidos iba antes que el de
  nombres de relleno y «me llamo Ana Ruiz Perez» no lo sustituía. Arreglado en 1630583
  (`tests/test_nombre_de_relleno_no_es_su_nombre.py`).
- Revisión de Astra sobre 782a53f..45d7f85 (buzón, 16:12): «PACK MECHAS LARGO» contaba como
  cambio de servicio al reprogramar y se auditaba una actualización sin cambio. Arreglado en
  a329fe0: 3 regresiones rojas sin el arreglo, 149 verdes. Pedido su veredicto sobre a329fe0;
  sin respuesta a las 16:51.
- Revisión independiente en frío (subagente de solo lectura) de 782a53f..1630583: VEREDICTO
  CAMBIOS. Reproducidos ejecutando:
  1. `_hora_coloquial` tomaba el número del día: «el jueves 18 a las 11», con huecos a las 11 y
     a las 18, daba las 18:00. Al aceptar el diagnóstico se guardaba una hora que no dijo.
  2. `booking_name` guardaba cualquier texto como nombre («perdona, mejor a las 16»).
  3. «sí, el jueves a las 17» aceptaba la oferta como un sí a secas y perdía día y hora.
  4. El freno `cancelar_sin_pedirlo` bloqueaba cancelaciones legítimas («no puedo venir,
     quítamela», «bórramela», el «sí» a «¿quieres que la cancele?»).
  Menores: `hora_sin_hueco` no se soltaba al cambiar de servicio ni al empezar otra gestión
  (arreglado). Anotados sin arreglar: una nota del agente se sobrescribe en `agent.py`;
  posible callejón si con clienta conocida `_wa_resumen_para_confirmar` devuelve False tras
  pasar a `booking_confirm`; `_ya_se_le_dijo` mira 8 mensajes sin corte por tiempo.
- 2a794c2 arregla 1–4 y los menores marcados. `tests/test_revision_independiente_13sep.py`:
  30 de 36 en rojo sin el arreglo (los 6 restantes son controles); 124 verdes en las suites
  relacionadas; pyflakes limpio.
- Re-medición en curso sobre 2a794c2 con árbol limpio (cambia el núcleo de la hora): banco de
  Alicia, crítico `dice-que-si-y-acaba-en-cita` ×6, humo, los seis escenarios de portal y
  reinicio, metareview conversacional (datos RAG traídos otra vez del servidor en solo lectura)
  y suite completa.
- Siguiente: leer resultados y conversaciones, actualizar el informe de aceptación y contar a
  Pablo los hallazgos serios antes de desplegar.

## 2026-09-13 16:51–17:50 +0200 - medición de 2a794c2, freno de hora, revisión de Astra y SHA final (Claude)

- Medición de 2a794c2 (árbol limpio, copia nueva de snap4_conregla, cfg4, solo la clave del modelo):
  banco Alicia 43/43 al primer intento; metareview conversacional 16/16; crítico
  `dice-que-si-y-acaba-en-cita` 6/6 al primer intento; humo 5/5 con los efectos leídos en la
  copia; portal y reinicios 6/6; suite 2631 passed, 1 skipped.
- Leyendo las conversaciones (reinicio a mitad de reserva): el freno `ofrecio_una_hora_que_no_tiene`
  obligó a decir «a las 17:00 no tengo disponibilidad» con las 17:00 libres (la cita se creó a esa
  hora sin conflicto). Comparaba contra la muestra de 8 huecos. Ya en producción. 3167313: antes de
  frenar mira la agenda real del día con margen. Test con el estado de los turnos medidos, rojo sin
  el arreglo; control con la hora ocupada.
- Medición de 413c170 (código 3167313): banco Alicia 42 + 1 reintento (`recomienda-ante-un-problema`,
  pendiente conocido); metareview 15 + 1 (`horario-escrito-manda`, redacción); crítico 6/6; humo 5/5;
  portal 6/6 (sin la negativa falsa); suite 2633 passed, 1 skipped.
- Revisión de Astra sobre 2a794c2 y 3167313 (17:16): CAMBIOS. [CRÍTICO] el «sí» autorizaba a cancelar
  si «cancelar» aparecía en otra frase del último mensaje; [IMPORTANTE] con el agente caído,
  `booking_name` guardaba la frase como nombre. 3167313 sin hallazgo; a329fe0 OK. Arreglados en
  0bca1eb (6 rojos sin el arreglo, 2 controles, 120 verdes). Astra (17:38): «REVISION 0bca1eb: OK».
- Riesgo serio YA en producción (código sin cambios desde bd7a6da): con `preferir_packs`, la misma
  llamada `buscar_servicio("mechas lo tengo medio mechas medio")` dio el pack de 360 min en una
  tirada y «Mechas medio» (75 min) en otra. Varía la extracción del modelo; el humo solo exige cita.
- Medición de 0bca1eb (SHA final, árbol limpio en todas las tiradas): banco Alicia 42 + 1 reintento
  (`recomienda-ante-un-problema`), 0 fallos; metareview 16/16; crítico 6/6 al primer intento; humo
  5/5 (efectos leídos en la copia); portal y reinicios 6/6, `regla-apagada-despues-de-ofrecer` al
  segundo intento (el primero acabó en el resumen del diagnóstico retirado, sin cita); suite 2641
  passed, 1 skipped.
- Siguiente: informe de aceptación, contar a Pablo los hallazgos y pedir la orden de despliegue.

## 2026-09-14 01:15–01:30 +0200 - despliegue del candidato 0bca1eb y regla de orientación de Alicia (Claude)

- Orden de Pablo (14-sep, 01:13): «si crees que es óptimo para funcionar ya en el negocio de alicia
  despliégalo y continúa con el resto de pasos».
- Antes: producción en bd7a6da (VERSION.json del 12-sep), contenedor sano, `/health` 200. Local en
  `claude/candidato` 109b091 (código 0bca1eb), árbol limpio, `py_compile` de los puntos de entrada OK.
  Despliegue con `-SkipLocalChecks`: la suite completa ya pasó sobre 0bca1eb (2641 passed, 1 skipped) y
  109b091 solo añade docs.
- Despliegue: 01:16:59–01:20:03, exit 0. Foto previa `pre-deploy-20260913-231725.db`; imagen nueva, `/health` ok, acceso público OK, humo en el servidor 5/5. VERSION.json: 109b091 sin árbol sucio. La intención `orientacion` existe en el código desplegado.
- Regla de orientación en producción (copia de seguridad previa `/srv/vantelia-backups/pre-regla-orientacion-20260913-232052.db`): creada `rule_eD_NnlJc1lQ` («Alisado: no sabe cual -> diagnostico», intención `orientacion`, familias alisado/alisados/keratina/acido lactico/lactico, `ofrecer_cita`, prioridad 15, playbook `derivar_a_valoracion`), mismos campos que la medida en copia; las otras tres reglas de Alicia, intactas.
- Verificación sin escribir a nadie (caso crítico dentro del contenedor, sobre una copia en /tmp borrada
  al acabar): `dice-que-si-y-acaba-en-cita` OK al primer intento: ofrece el diagnóstico con el texto de la regla, conserva «a las 15» y acaba en el resumen de Diagnóstico y presupuesto, martes 15 a las 15:00, a nombre de Ana Ruiz Perez. Copia e informe borrados; en `/tmp` del servidor quedaba `snap2.db` del 9-sep (copia SQLite de producción de una medición anterior): borrada; el contenedor, limpio.
- Limpieza: borradas las copias de BD de cada tirada, el snapshot de producción y su config, la copia
  local del 3-sep y las copias viejas de `storage/mediciones` (27-ago y 10-sep), con permiso de Pablo.
- Astra sin créditos hasta el 13-oct.
- Siguiente: vigilar las conversaciones reales de Alicia desde el despliegue (frenos, citas creadas); hacer determinista la elección del pack con `preferir_packs` (mechas en 75 min en vez de 360); que una oferta retirada desde el portal no vuelva a ofrecerse y una copia por intento en el medidor; fechas siempre en humano; recomendación ante caída del pelo; frenos en falso; plantilla de recordatorio de Meta; integrar en `main` y subirlo..

## 2026-09-14 01:30–02:18 +0200 - remate tras el despliegue: seis arreglos más (Claude)

- Orden de Pablo (14-sep): subir `main` a GitHub (hecho: 5b7be4d..5c1b5f4) y seguir rematando lo
  pendiente y el plan de arquitectura; todavía no se instala en el negocio.
- Arreglos, todos con test rojo sin el arreglo y controles:
  - 74e2894 **pack con `preferir_packs`**: con `tecnica: "mechas medio"` extraída por el modelo se elegía
    «Mechas medio» (75 min) en vez del pack de 360 (humo del 13-sep, mismo turno con resultado distinto).
    Reproducido en test; la talla se quita de la técnica antes de filtrar. Y **fechas ISO** de la respuesta
    («2026-09-15») salen en humano, sin tocar enlaces ni códigos.
  - 3f11dea **freno `dijo_cerrado_estando_abierto`** mira de qué día habla (metareview, domingo: «hoy estamos
    cerrados» era verdad). **Oferta retirada**: `crear_cita` del servicio de una propuesta invalidada se
    rechaza si ella no lo pide por su nombre (escenario de regla apagada del 13-sep).
  - 4533dee **reloj de la ventana de reserva**: `_validate_booking_window` usaba `datetime.now` y rechazaba como
    pasada la fecha elegida con el reloj de la prueba; `test_calendario_de_las_medidas[12]` empezó a fallar
    solo el 14-sep y el despliegue corre la suite.
  - f288ddf **«qué me recomiendas»** cuenta como duda al elegir: se aplica lo que el negocio tiene escrito
    (caso `recomienda-ante-un-problema`: a la caída del pelo se le proponía un alisado).
  - 36b4d8d **freno `dijo_que_hay_cita_sin_haberla`** no niega una cita viva de su teléfono a esa hora
    (reprogramar del 13-sep).
- Inventario de los 26 frenos del agente en la fase 4 del plan (caso, hecho que consultan, dueño final).
- `test_reserva_concurrente` (dos reprogramaciones al mismo hueco) falló una vez bajo carga en una tanda de 60
  ficheros y pasó 4/4 a solas con y sin el cambio: sensible a la carga, anotado.
- Pregunta abierta para Pablo: en la config de PRODUCCIÓN Alicia no tiene `exigir_dos_apellidos` (el
  `config.json` del repo sí, desde 550aafe); se mide y funciona como producción. No se cambia sin su orden.
- Recordatorios por WhatsApp de Alicia, mirado en el snapshot de producción: `whatsapp.enabled` en false, sin cuenta en
  `client_whatsapp_accounts` y sin plantilla en `wa_templates`. La plantilla `vantelia_recordatorio_cita` no
  se puede dar de alta hasta que su número esté conectado: dependencia externa (Alicia + Meta), no de código.
- Snapshot nuevo de producción (769 citas, 4 reglas de Alicia) y config traídos en solo lectura para medir; se
  borran al acabar.
- Siguiente: suite completa sobre 36b4d8d; medición con modelo real (crítico, banco Alicia, humo, portal,
  metareview); después, contar resultados a Pablo y proponer despliegue.

## 2026-09-14 02:18–03:16 +0200 - test de concurrencia, medición de ed94be1 y manicura (Claude)

- Suite completa sobre 36b4d8d: 2674 passed, 1 failed (`test_reserva_concurrente`, dos reprogramaciones al mismo
  hueco). Leído: el test NO probaba nada (construía el cambio con `BookingReschedulePayload`, sin `nombre` ni
  `servicio`, y sin `source`: los dos hilos acababan siempre en excepción) y fallaba al CREAR las citas iniciales
  (409, traza línea 150) según el orden de la suite. ed94be1 lo rehace: mismo profesional, `BookingUpdatePayload`,
  exige 200 + 409 y una cita en destino. Mutación comprobada: sin la re-comprobación con el lock falla por la
  carrera (`[200, 'IntegrityError']`).
- Medición de ed94be1 (copia nueva `snap5` de producción de las 02:17, `cfg5`, árbol limpio): suite 2675 passed,
  1 skipped, 0 fallos; banco Alicia 43/43 al primer intento (`recomienda-ante-un-problema` ya contesta con el
  texto de Alicia); crítico 6/6 al primer intento y 0 fechas ISO (antes 3 de 6); humo 5/5 con el pack de mechas
  completo; portal y reinicios 6/6 al primer intento (regla apagada: ya no resume el diagnóstico retirado).
- metareview sobre ed94be1: 14 OK y 2 fallos. `horario-escrito-manda` depende del día de la medición (un lunes no
  dice «lunes»; ayer, domingo, pasaba en todas las versiones): instrumento. `servicio-que-no-existe`, 2 de 2: la
  comprobación «nadie hace esa técnica» solo miraba la técnica y el extractor apuntó «manicura» como familia.
  bec310f la mira también en la familia (test rojo sin el arreglo; 453 verdes).
- Borradas las copias de BD de cada tirada; se conservan `snap5`, `cfg5` y los datos de metareview para volver a
  medir bec310f, y se borran después.
- Siguiente: metareview, humo y suite sobre bec310f; cerrar docs, limpiar y contar a Pablo.
- Medición de bec310f (árbol limpio): metareview 15/16 al primer intento, `servicio-que-no-existe` ya dice que no hay manicura
  (único fallo `horario-escrito-manda`, dependiente del día); humo 5/5 con el pack completo; suite 2678 passed,
  1 skipped, 0 fallos. Borrados el snapshot `snap5`, su config, los datos de metareview y todas las copias de
  medición: no queda ninguna copia con datos de clientas en la sesión.
- Siguiente: contar a Pablo; despliegue de bec310f cuando él lo ordene. Los commits de esta noche NO se han subido a
  GitHub (`main` sigue en lo desplegado, 5c1b5f4).

## 2026-09-14 05:15–07:24 +0200 - despliegue de bec310f y dos apellidos para Alicia (Claude)

- Orden de Pablo (14-sep): «adelante» al despliegue de bec310f, a subir los commits a GitHub y a activar la
  exigencia de dos apellidos para Alicia en producción.
- Antes: producción en 109b091 (código 0bca1eb), `/health` 200. Local en 2360b1c (código bec310f), árbol limpio,
  `py_compile` OK; suite completa ya verde sobre bec310f (2678 passed, 1 skipped); lo posterior es solo docs.
- `exigir_dos_apellidos: true` para `alicia_rincon_estilistas` en `/srv/vantelia/config.json`, con copia previa
  `/srv/vantelia-backups/config-pre-dos-apellidos-20260914-051931.json`; los otros 27 negocios, idénticos (huella
  comprobada). Coincide con la decisión de Pablo del 11-sep y con el `config.json` del repo (550aafe); se puede
  desactivar desde Q&A del portal.
- Despliegue: `deploy.ps1 -SkipLocalChecks` 07:19:48–07:22:42, exit 0. Foto previa `pre-deploy-20260914-052015.db`, imagen anterior `vantelia:prev`, `/health` 200, humo en el servidor 5/5. VERSION.json 2360b1c sin árbol sucio.
- Verificación tras desplegar: `exige_dos_apellidos(alicia)` True en el fichero y en la app viva; regla «Alisado: no sabe cual -> diagnostico» presente; `dice-que-si-y-acaba-en-cita` dentro del contenedor sobre una copia en /tmp: OK al primer intento, ya pide «tu nombre y tus dos apellidos» y acaba en el resumen del diagnóstico a nombre de Ana Ruiz Perez (copia e informe borrados, `/tmp` limpio).
- GitHub: `main` avanzado sin fusión a 2360b1c y subido (5c1b5f4..2360b1c), sin ficheros sensibles.
- Siguiente: vigilar las conversaciones reales de Alicia en cuanto lo use; fase 4 del plan con el inventario de
  frenos; pendientes menores (vacaciones dice «agenda completa»; `horario-escrito-manda` depende del día);
  WhatsApp de Alicia sin conectar (bloquea recordatorios).

## 2026-09-14 10:41 +0200 - recuperación de creación sin resultado (Astra)

- Rama `astra/reconciliar-pendientes`, base `main` `f4da10e`. Una operación de creación interna sin fila de cita deja de bloquearse indefinidamente solo si tiene al menos 15 minutos y no hay `webhook_url`, `webhook_env` resuelto ni `WEBHOOK_DEFAULT`. Con webhook, reciente o de otro tenant queda pendiente como antes.
- La liberación se registra en `booking_operation_audit` sin datos personales. WhatsApp no ejecuta de nuevo: informa de que no se registró y publica otro resumen, que exige una confirmación nueva.
- Evidencia: 19 pruebas dirigidas verdes en 32,16 s (`test_operacion_creacion_recuperable.py`, `test_whatsapp_creacion_recuperable.py`), incluidas operación antigua, webhook URL/env, reciente, aislamiento tenant y reinicio del flujo. La prueba de liberación falla de forma causal con `OPERATION_PENDING` al desactivar temporalmente la condición. La regresión de liberación falló al desactivar temporalmente la condición, antes de restaurarla.
- Siguiente: commit pequeño y revisión de Claude; no despliegue.

## 2026-09-14 11:02 +0200 - cierre de carrera al liberar una creación (Astra)

- La revisión de `5c88bc7` reprodujo que una `ConversationStateConflict` tras borrar la operación dejaba la propuesta aceptada apuntando a una clave ya liberada. `_wa_reabrir_creacion_liberada` recarga y reintenta el CAS una vez, sin sobrescribir una propuesta distinta; si sigue en conflicto responde en vez de silenciar el turno.
- También cubre una caída entre guardar la clave en conversación y reclamarla: solo una propuesta aceptada de 15 minutos o más, con operación ausente, vuelve a publicar resumen. Antes del margen sigue `OPERATION_PENDING`, para no competir con otro worker que aún podría crear la cita.
- Evidencia: 21 dirigidas verdes en 45,18 s. Regresiones nuevas cubren conflicto y ausencia reciente/antigua; la de conflicto falla al retirar el reintento. Siguiente: commit y segunda revisión de Claude; sin despliegue.

## 2026-09-14 10:37–11:30 +0200 - Fase 3, avisos sin bloqueo y revisión de la reconciliación (Claude)

- Ramas: `claude/candidato` 68a8c68 (Fase 3) y 1458540 (avisos); `claude/reconciliar-pendientes` 04fc97f,
  hija de 1c70f0a de Astra. Nada subido ni desplegado.
- 10:37, 68a8c68: la API rechaza reglas sin intenciones, con intención desconocida o sin texto en una acción que
  contesta; el listado del portal trae `avisos` por regla (tapada, empate de prioridad, familia fuera del catálogo,
  ofrecer cita sin valoración). Tests `tests/test_avisos_de_reglas.py`.
- Avisos, decisión de Pablo («Reintentar sin duplicar WhatsApp»): 1458540. Tests nuevos: 5 rojos antes del arreglo
  y 2 controles de 29 min que pasan antes y después; suites de avisos 52 verdes; suite completa sobre el árbol con
  68a8c68 y el arreglo: 2702 passed, 1 skipped (25:27).
- 10:43, 5c88bc7 de Astra (liberar operaciones internas perdidas). Revisión a las 10:56: 48 dirigidos verdes en el
  SHA exacto; mutación: con `booking_operations.py` del padre fallan sus 3 tests nuevos. Repro rojo: si falla el
  guardado del estado tras liberar, la clienta queda sin respuesta y después atrapada en «Aún no puedo verificar».
  Veredicto CAMBIOS, en el buzón.
- 11:03, 5a965e7 de Astra: 51 verdes con mi repro del conflicto. Nuevo repro rojo: con el resumen enviado hace
  20 min, un doble toque mientras se crea la cita recibe «La solicitud anterior no llegó a registrarse» y un
  resumen nuevo, además de «Cita confirmada» (1 cita). 04fc97f mide el margen desde la aceptación
  (`operacion.vinculada`): test rojo sin el arreglo, 74 dirigidos verdes. Suite completa de 04fc97f: 2687 passed, 1 skipped (23:06).
- Plugin `codex-plugin-cc` instalado a petición de Pablo (ámbito local; en VS Code se llama a su script). La
  revisión adversarial de los avisos NO se hizo: `gpt-6-astra` no se admite con cuenta ChatGPT, y con
  `gpt-5.6-terra` la cuenta llegó al límite hasta el 14-oct a las 10:26 (Astra ya iba al 94 % a las 11:06). El
  «No material findings» de ese intento no es una revisión. `.claude/settings.local.json` (trackeado) queda
  modificado sin commit con `enabledPlugins`, pendiente de Pablo.
- Siguiente: suite de 04fc97f, integrarla en el candidato y fase 4 (cancelación/reprogramación, formularios, voz,
  widget con confirmación persistida).
