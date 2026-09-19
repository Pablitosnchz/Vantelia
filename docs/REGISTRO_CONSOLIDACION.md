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

## 2026-09-14 11:30–12:06 +0200 - reconciliación integrada y revisión de Codex a los avisos (Claude)

- `claude/candidato`: d14285d fusiona `claude/reconciliar-pendientes` (5c88bc7, aab1e1a, 5a965e7 y 1c70f0a de Astra,
  04fc97f de Claude); suite de la rama 2687 passed, 1 skipped; choques solo en ESTADO y REGISTRO. 549a1e3 corrige
  los avisos tras la revisión de Codex. Nada subido ni desplegado.
- Codex: Pablo entró con otra cuenta (login cambiado a las 11:40). El runtime compartido del plugin conservaba el
  token anterior («access token could not be refreshed…»); reiniciado con su hook de fin de sesión. La revisión
  adversarial de 1458540 terminó con `needs-attention` y dos hallazgos altos.
- Hallazgo 1, confirmado con test rojo: la banda del recordatorio dura 45 min y, pasados los 30 de gracia, la cita ya
  ha salido de ella: el respaldo no se envía nunca. Mi test lo tapaba envejeciendo la fila en vez de adelantar el
  reloj. Arreglo: un aviso con intento registrado conserva la banda 75 min más (`_reminder_due_or_pending`); sin
  intento previo no sale tarde (control verde).
- Hallazgo 2, confirmado con test rojo (`['email', 'whatsapp']`): un ejecutor parado más de la gracia conservaba su
  turno y mandaba el WhatsApp después del email del respaldo. Arreglo: la reclamación retira el turno caducado en su
  transacción y cada envío lo comprueba justo antes del transporte (`notice_claim_still_owned`). Queda abierta solo
  la propia llamada (timeout de 20 s).
- Evidencia de 549a1e3: 3 rojos antes del arreglo y 57 dirigidos verdes después. Suite completa y segunda revisión
  de Codex: en marcha.
- Nota de producto: con la prórroga, el recordatorio de 24 h puede salir hasta 22 h 45 min antes y su asunto dice
  «mañana», que solo sería falso para citas desde las 22:45.
- Siguiente: resultados de la suite y de la revisión; fase 4 (cancelación/reprogramación, formularios, voz y widget
  con confirmación persistida).

## 2026-09-14 12:06–12:35 +0200 - segunda revisión de Codex a los avisos y reenvío manual (Claude)

- Suite completa de 549a1e3: 2713 passed, 1 skipped (23:50).
- Segunda revisión adversarial de Codex (base 1458540): `needs-attention`, dos hallazgos altos.
  1. Carrera al límite de la gracia: un ejecutor que vuelve a los 29 min 55 s pasa la comprobación sin renovar su
     turno y otro se lo retira segundos después, con su WhatsApp aún en camino. Test rojo (`['whatsapp', 'email']`).
     Arreglo en 0b12b3c: `notice_claim_still_owned` renueva `updated_at` en el mismo UPDATE.
  2. El reenvío manual («Enviar confirmación» del panel) no pasa por el registro de entregas: con WhatsApp dudoso
     daba un error genérico y un segundo clic podía duplicar. Ya pasaba antes de hoy. Preguntado a Pablo, eligió
     «Avisar y dejar reenviar». 0b12b3c: el dudoso se explica; el siguiente reenvío responde 409
     `WHATSAPP_SIN_CONFIRMAR` y el panel pregunta antes de reenviar con `force`, también si la confirmación
     automática quedó dudosa. 4 rojos antes del arreglo y el control de rechazo verde.
- Evidencia de 0b12b3c: 61 dirigidos verdes. El test del panel contaba también la definición de la función: se
  corrigió el test, no el código. Suite completa y tercera revisión de Codex: en marcha.
- Pablo pidió que se le pregunte siempre que haga falta una decisión suya; queda en memoria.
- Siguiente: resultados de la suite y de la revisión; fase 4.

## 2026-09-14 12:36–13:00 +0200 - tercera revisión de Codex: el aviso del reenvío en el núcleo (Claude)

- Tercera revisión adversarial de Codex (base 549a1e3, sobre 0b12b3c): la renovación del turno, el POST sin cuerpo
  y el botón del panel pasan; dos hallazgos altos en cuándo avisa el reenvío manual:
  1. Un reenvío solo por email tapaba el WhatsApp dudoso anterior (se miraba el último evento sin fijarse en el
     canal) y el siguiente reenvío por WhatsApp salía sin preguntar. Test rojo: «DID NOT RAISE».
  2. La confirmación que sale al pagar la señal (y la de un cambio de cita sin mover la hora) no pasa por el
     registro de entregas ni dejaba rastro del WhatsApp dudoso: el reenvío posterior no avisaba. Test rojo.
- Arreglo 3e05b96: el núcleo pide el resultado detallado de WhatsApp en toda confirmación y, sin registro de
  entregas, apunta `confirmation_whatsapp_uncertain`; el aviso busca el último evento que diga algo del WhatsApp
  (dudoso, o entrega con WhatsApp en `confirmation_resent`/`booking_email_sent`). Test HTTP nuevo: sin cuerpo
  avisa, con `force` reenvía.
- Pablo decidió (AskUserQuestion) una ronda más de revisión tras este arreglo y pasar después a la fase 4.

## 2026-09-14 13:00–13:29 +0200 - última ronda de Codex y reprogramar guiado con aceptación (Claude)

- Suite de 3e05b96: 2722 passed, 1 skipped (22:01).
- Última revisión adversarial de Codex (base 0b12b3c; Pablo había decidido una ronda más y después la fase 4): un
  hallazgo alto, regresión de 3e05b96. Una entrega anterior (una edición de la cita) tapaba un WhatsApp automático
  dudoso posterior (la confirmación de voz): el reenvío manual no avisaba; con 0b12b3c sí. Test rojo. Arreglo en
  e44886b: el aviso compara la hora del dudoso del registro de entregas con la de la última entrega por WhatsApp de
  la auditoría (si empatan, avisa). Control verde. No se abre otra ronda.
- Fase 4, preguntado a Pablo: «Solo el flujo de listas». e44886b: `_wa_ofrecer_reprogramacion` y
  `_wa_responder_reprogramacion`, con `_prepare_booking_reschedule`, `_reschedule_slot_is_free`, y `expected_snapshot`
  y `resultado_desconocido` en `_reschedule_booking_by_code`. 12 tests rojos antes del arreglo; el del reinicio
  pasaba sin arreglo y se endureció. Dos tests antiguos (`test_whatsapp_reschedule_booking_by_code`,
  `test_whatsapp_reschedule_success_speaks_human_date`) adaptados al resumen y al botón, sin quitar lo que
  comprobaban. El agente conversacional de Alicia no cambia.
- Evidencia de e44886b: 89 y 51 dirigidos verdes. Suite completa: en marcha.
- Siguiente: la suite; lo que queda de la fase 4 (reprogramar desde el agente, formularios, voz, widget y la
  cancelación con resultado desconocido sin reconciliar).

## 2026-09-14 14:12 Europe/Madrid — Astra retoma el candidato

- Pablo entrega el mando mientras Claude no tiene cuota. Rama propia `astra/aceptacion-e44886b`, descendiente de `61a3081`; código `e44886b`. Se conserva el cambio ajeno en `.claude/settings.local.json`.
- Verificado el resultado final del proceso bcssa0kh5: **2737 passed, 1 skipped**, exit 0, 1429,37 s. No se repite esta suite. El resultado 2722 pertenece al padre 3e05b96.
- Iniciada medición real acotada del crítico sobre copia local temporal (astra-e448-critico.db), informe astra-e448-critico.json en TEMP. Las llamadas al modelo responden 200. Pendiente resultado; la copia local no acredita equivalencia con el snapshot de producción usado por Claude.
- Siguiente: resultado del crítico, comprobar condiciones del banco y medir segundo negocio; solo después proponer despliegue. Sin push ni despliegue.

## 2026-09-14 14:10–15:45 +0200 - relevo de Astra y medición del candidato c8aaad8 (Claude)

- 14:10 Astra tomó el relevo mientras Claude no tenía cuota: rama `astra/aceptacion-e44886b` desde 61a3081 en E:/Vantelia
  y commit de docs cd1843d. Verificó la suite de e44886b (2737 passed, 1 skipped), que terminó antes de su cambio de
  rama. Midió el caso crítico sobre copia y config LOCALES: 2 de 2 fallos («no dice nada de ['Resumen de tu cita',
  'Confirmamos']»). Leído por Claude: esa copia local no tiene la regla de orientación de Alicia `rule_eD_NnlJc1lQ`,
  que solo existe en producción, así que el fallo es del instrumento, no del código. Su copia (db, shm y wal) se ha
  borrado; su informe JSON sigue en TEMP. Astra está sin créditos hasta las 16:49.
- Revisión de Astra a e44886b: sin autorización indebida. Menor: el contacto del primer mensaje no llegaba a la oferta
  si el día y la hora venían después. Claude retoma en la misma rama: c8aaad8 (test rojo antes del arreglo; 14
  dirigidos verdes).
- Decisión de Pablo (AskUserQuestion): medir y proponer despliegue. Copia nueva de producción en solo lectura, antes de
  las 15:40: `snap6.db` (backup dentro del contenedor, /tmp del servidor limpio), `cfg6.json`, datos RAG de metareview
  (`meta_rag`) y `cfg6_metareview_conversacional` (solo cambia `booking.estilo`). snap6 tiene las 4 reglas de Alicia,
  incluida la de orientación.
- 15:40, mediciones sobre c8aaad8 (sucio=0): banco de Alicia (banco_m), humo (humo_m), portal y reinicios (portal7),
  metareview (banco_meta_m) y crítico ×6 (critico_m1–6), con la suite completa en paralelo. Referencia: banco 43/43 y
  crítico 6/6 al primer intento (ed94be1); humo 5/5 y metareview 15/16 (bec310f); portal 6/6.
- Siguiente: resultados, comparación, borrado de copias y propuesta de despliegue a Pablo.

## 2026-09-14 15:40–16:24 +0200 - medición del candidato c8aaad8 con modelo real (Claude)

- Todo sobre c8aaad8, con la copia snap6 (producción, solo lectura), la config cfg6 y el código limpio: el lanzador
  mira `backend`, `evals` y `scripts`. El informe marca el árbol sucio por `.claude/settings.local.json` y el
  registro.
- Banco de Alicia (banco_m, 15:40–16:24): 43/43 al primer intento, 0 fallos, 1 no aplica. Referencia ed94be1: 43/43.
- Crítico `dice-que-si-y-acaba-en-cita` ×6 (critico_m1–6, 15:40–16:11): 6/6 al primer intento, ninguno tras
  reintento. Referencia: 6/6. El 0/2 de Astra venía de su copia local sin la regla de orientación.
- Humo (humo_m, 15:40–15:50): 5/5, los cinco caminos llegan hasta el final. Referencia bec310f: 5/5.
- Portal y reinicios (portal7, 15:40–15:52): 6/6, 0 fallos, 0 sin medir. Referencia: 6/6.
- Metareview (banco_meta_m, 15:40–15:45): 15/16 al primer intento. Único fallo `horario-escrito-manda` («no dice
  nada de ['lunes']», 2 de 2), que depende del día de la medición (hoy es lunes). Referencia bec310f: 15/16 con el
  mismo fallo.
- Copias borradas: snap6, cfg6, cfg6_metareview, meta_rag, las copias de portal y las de cada tirada. En el scratchpad
  no queda ninguna copia con datos de clientas; se conservan los informes JSON. El /tmp del servidor quedó limpio.
- Suite completa de c8aaad8 (15:40–16:29, en paralelo con las mediciones): 2738 passed, 1 skipped, 0 fallos.
- Siguiente: resultado de la suite y pedir a Pablo el despliegue.

## 2026-09-14 16:30–16:45 +0200 - despliegue de c8aaad8 (Claude)

- Orden de Pablo (AskUserQuestion, 16:30): «Desplegar y subir».
- Antes: producción en 2360b1c (código bec310f), /health 200, contenedor arriba desde hacía 9 h. Local en 14e5a5d
  (código c8aaad8 y docs) en `astra/aceptacion-e44886b`. Suite completa de c8aaad8 verde (2738 passed, 1 skipped) y
  medición con modelo real igual que lo desplegado. `.claude/settings.local.json` (plugin de Codex, sin commit) se
  apartó con `git stash` mientras se empaquetaba y se recuperó después.
- `deploy.ps1 -SkipLocalChecks`, 16:33:59–16:38:14, exit 0: foto previa `pre-deploy-20260914-143501.db`, imagen
  anterior `vantelia:prev`, /health ok, acceso público OK y humo en el servidor 5/5. VERSION.json 14e5a5d, `sucio: false`.
- Verificación: /health público 200. Caso crítico `dice-que-si-y-acaba-en-cita` dentro del contenedor sobre una copia
  en /tmp: OK al primer intento, pide los dos apellidos y acaba en el resumen del diagnóstico (martes 15 a las 15:00).
  Copia e informe borrados; contenedor y servidor limpios.
- GitHub: `main` avanzado sin fusión desde f4da10e hasta el commit de docs de este despliegue.
- Siguiente, propuesto a Pablo: medir con modelo real reglas opuestas en dos negocios (cierra la fase 3) y reconciliar
  las cancelaciones con resultado desconocido; voz y widget cuando un cliente los use; vigilar las conversaciones
  reales de Alicia. El WhatsApp de Alicia sigue sin conectar.

## 2026-09-14 16:45–17:05 +0200 - días gratis del plan para Alicia y fase 3 cerrada (Claude)

- Decisiones de Pablo (AskUserQuestion): cerrar lo que dependa de nosotros y darle a Alicia el texto para conectar
  WhatsApp y Stripe; plan **Pro, 129 €/mes**; cobro por **Stripe con SEPA y tarjeta**; **10 días gratis desde que
  conecte su WhatsApp**.
- Producción, solo lectura: Stripe y Connect configurados, precios de los tres planes configurados, botón de conectar
  WhatsApp disponible para Alicia; Alicia en Business «activa» puesto a mano, sin cliente de Stripe; Connect y WhatsApp
  sin conectar. El checkout de suscripción no admitía días de prueba.
- cb87be4: config por negocio `prueba` = {"dias": N, "hasta": ISO}; `_completar_alta_whatsapp` fija `hasta` al conectar
  (reconectar no la alarga); el checkout manda `subscription_data.trial_end` y pide el método de pago. Sin fecha, la
  prueba cuenta desde la suscripción; con menos de 48 h por delante (Stripe no lo admite) se cobra como siempre. El
  webhook ya guarda `trialing` y conserva el plan; si luego el cobro falla, la suscripción queda impagada y el
  asistente se para como hasta ahora. 3 tests rojos antes del arreglo, controles verdes, 17 dirigidos y
  `test_wa_embedded_signup.py` (16) verdes. Suite completa: en marcha.
- Fase 3, puerta de dos negocios con reglas opuestas, medida con modelo real (`medir_reglas_opuestas.py` en el
  scratchpad, entorno aislado borrado al acabar): 21/21, 0 fallos (opuestas intercaladas, regla editada, regla
  borrada sin heredar la ajena). Fase 3 cerrada.
- Pendiente de Pablo antes de mandarle a Alicia el paso de la suscripción: activar el adeudo SEPA en Stripe, orden de
  desplegar cb87be4 y de poner `prueba: {"dias": 10}` en la config de Alicia en producción, y confirmar si los 129 €
  llevan IVA.
- Siguiente: la suite; reconciliar las cancelaciones con resultado desconocido.

## 2026-09-14 17:05–17:35 +0200 - cancelaciones recuperables y SEPA en Stripe (Claude)

- Suite completa de cb87be4 (días gratis): 2743 passed, 1 skipped, 1 fallo cuyo nombre no se guardó (salida recortada).
  Coincidió con otros procesos de medición y de tests. No se reprodujo en la suite siguiente, que incluye ese código.
  Se deja apuntado como no reproducido.
- e11ac35, fase 4: una cancelación aceptada cuyo resultado se perdía dejaba a la clienta en «contacta con el negocio»
  con la cita en pie. Ahora se guarda `aceptada_en`; pasados 15 minutos y sin webhook (el mismo criterio que la
  creación), si la cita sigue en pie se le vuelve a enseñar para que confirme, sin cancelar sola. La frontera común ya
  no bloquea volver a pedir la cancelación. Antes del margen o con webhook sigue pendiente. 2 rojos antes del arreglo
  con sus controles verdes; un test corregido que miraba también el aviso anterior; 88 dirigidos verdes.
- Suite completa de e11ac35 (con `-rf` y la salida guardada): 2748 passed, 1 skipped, 0 fallos.
- Stripe, con autorización de Pablo (AskUserQuestion «Mira la cuenta y activa SEPA»): cuenta «Vantelia»
  `acct_1TRvakJqlPNuHbxQ` (vanteliadigital@gmail.com, ES, EUR, modo real), consultada desde el contenedor sin mostrar
  la clave. Preferencia de adeudo SEPA activada por la API en la configuración por defecto de la plataforma
  (`pmc_1TRvbF…`); las configuraciones de apps no se tocaron. Al principio la función `sepa_debit_payments` no
  aparecía. Pablo dijo que ya estaba habilitado y la segunda consulta la da **activa**, con SEPA disponible en la
  configuración que usa el checkout de suscripciones.
- Siguiente: orden de despliegue de e11ac35 y `prueba` de Alicia en producción; confirmar el IVA del texto.

## 2026-09-14 17:35–17:50 +0200 - despliegue de e5c784f y prueba de 10 días para Alicia (Claude)

- Orden de Pablo (AskUserQuestion): «Desplegar, config de Alicia y subir»; los 129 € llevan el IVA incluido.
- Config de producción: copia previa `/srv/vantelia-backups/config-pre-prueba-alicia-20260914-154104.json`;
  `prueba: {"dias": 10}` en Alicia; los otros 27 negocios, idénticos (comprobado por huella); la exigencia de dos
  apellidos sigue activa.
- `deploy.ps1 -SkipLocalChecks`, 17:41:04–17:43:53, exit 0: foto previa `pre-deploy-20260914-154140.db`, acceso
  público OK, humo en el servidor 5/5. VERSION.json e5c784f, `sucio: false`.
- Verificación: /health 200. En la app viva, Alicia tiene la prueba y `fin_de_prueba` da 10 días (24-sep si se
  suscribiera ahora; al conectar WhatsApp se fija desde ese día); un negocio sin prueba devuelve None. Caso crítico
  dentro del contenedor sobre una copia: OK al primer intento; copia borrada, contenedor y servidor limpios.
- GitHub: `main` avanzado sin fusión hasta el commit de docs de este despliegue.
- Siguiente: Pablo le manda a Alicia el texto (WhatsApp, tarjeta en Meta, suscripción Pro con 10 días gratis y Stripe
  opcional). Del plan queda lo que depende de conversaciones reales y de clientes que usen voz o widget.

## 2026-09-14 17:50–18:09 +0200 - comprobación antes de avisar a Alicia (Claude)

- Solo lectura en producción. Botón de conectar WhatsApp disponible y plan con WhatsApp. `whatsapp.enabled` en false
  y sin número: se fijan al conectar. `message_template_channels` con WhatsApp en todos los avisos y
  `delivery_priority` whatsapp→email→sms: mientras no conecte o no esté aprobada la plantilla, sale por email.
- Voz y SMS no usados. Usuario propietario activo (último acceso 9-sep). Secretos de los webhooks de Stripe y Connect
  configurados, y el webhook ya registró 2 suscripciones reales (última, 31-ago). 38 citas en 30 días; 0 documentos
  extra.
- Pro frente a Business: tiene 6 profesionales activos y Pro permite 3. El límite solo impide crear o reactivar
  profesionales, no desactiva a nadie. Decisión de Pablo (AskUserQuestion): Pro tal cual, con sus 6.
- Siguiente: cuando Alicia conecte, comprobar su cuenta de WhatsApp, `prueba.hasta`, la plantilla del recordatorio y
  un mensaje de prueba de ida y vuelta.

## 2026-09-14 18:30–18:50 +0200 - vacaciones como día cerrado y medidor de reglas en el repo (Claude)

- Encargo de Pablo (AskUserQuestion): «Arreglar el texto de vacaciones, Guardar el medidor de reglas». Rama
  `claude/vacaciones-y-medidor` desde `main` c858d58; commit ef0d0dc. Sin desplegar.
- Causa de «agenda completa» con vacaciones: `voice._dia_cerrado` solo miraba el horario semanal. Con un bloqueo general
  00:00–23:59 (lo que guarda Horario «sin horas»), `consultar_disponibilidad` pedía decir «completo» y el freno
  `dijo_cerrado_estando_abierto` corregía un «cerrados por vacaciones» cierto. `agenda.motivo_de_cierre_del_dia`: el día
  cierra si todos los que trabajan tienen su horario entero bloqueado (general o propio). Bloqueo parcial o las
  vacaciones de una sola profesional no cierran. El flujo guiado de WhatsApp ya decía «bloqueada, motivo: …»: sin tocar.
- `horario-escrito-manda`: exige nombrar dos días de la semana distintos (`debe_varios`); con «lunes» pasaba los
  domingos y suspendía los lunes. No medido con modelo tras el cambio: puede suspender también en metareview si solo
  contesta «hoy… mañana…», que no es el horario de la semana.
- Pruebas: 11 nuevas (`test_vacaciones_son_dia_cerrado.py`, `test_horario_no_depende_del_dia.py`), 10 rojas antes del
  arreglo (la de una sola profesional se añadió después; su segunda comprobación depende del arreglo). Suites
  relacionadas (banco, calendario, cerrado, agente de citas, voz, horario, booking_exhaustive): 253 passed. Mapa del
  código: 5 passed. Suite completa: en curso.
- `scripts/medir_reglas_opuestas.py` (desde el scratchpad): primera ejecución desde el repo 21/21 (18:43). Al leerla:
  `settings` hace load_dotenv y repone las credenciales que el script borraba. Ahora las vacía (lista de
  `tests/conftest.py` + Stripe y webhook), bloquea SMTP/IMAP y aborta si queda alguna viva. Otra vez 21/21 (18:46),
  carpeta temporal borrada. En los logs de la primera ejecución no hay ningún envío y los dos negocios sintéticos no
  tenían destinatario.
- Revisión pedida a Astra sobre ef0d0dc (18:49). Alicia: SIN_CONECTAR a las 18:43.
- Siguiente: resultado de la suite y veredicto de Astra; desplegar solo con orden de Pablo.

## 2026-09-14 18:50–19:15 +0200 - revisión de Astra sobre ef0d0dc y arreglos (Claude)

- Suite completa sobre el árbol de ef0d0dc (18:50–19:08): 2759 passed, 1 skipped, 0 fallos.
- Astra (buzón): CAMBIOS, dos hallazgos reproducidos extrayendo las funciones del SHA, sin modelo ni producción.
  1. Descansos: jornada 09–18 con pausa 13–14 y bloqueos 09–13 y 14–18 seguía «abierto». 45f3d11 cuenta los descansos
     del negocio y de cada profesional como no laborables. Test nuevo; quitando las pausas del cálculo falla
     («solo le queda el descanso») y el fichero se restauró.
  2. `debe_varios` no equivalía a dar el horario: «todos los días» y «excepto los domingos» suspendían y «hoy lunes…
     mañana martes» aprobaba. 45f3d11 lo sustituye por `horario_semanal` (dos días de la semana, la semana entera o la
     excepción; no cuentan los días pegados a hoy/mañana). Sus tres casos son tests. No comprueba que el horario dicho
     sea el del negocio. Sin medir con modelo.
- Pruebas: dirigidas y banco 79 passed; suites relacionadas 259 passed (una tirada anterior se descartó porque arrancó
  mientras la comprobación causal tenía `agenda.py` modificado).
- Pablo: «puedes delegar cosas a astra». Encargo a Astra (19:15): revisar 45f3d11 y, en su rama desde 45f3d11, la misma
  clase de fallo en `rag._availability_snapshot_for_day`, el selector de días del WhatsApp guiado y `calidad.py`.
- Alicia: SIN_CONECTAR a las 19:09.
- Suite completa de 45f3d11 (19:16–19:34): 2765 passed, 1 skipped, 0 fallos.
- Decisión de Pablo (AskUserQuestion, 19:32): «Esperar OK de Astra». Con OK se despliega con `deploy.ps1` y se sube
  main; con CAMBIOS se arregla antes. Alicia: SIN_CONECTAR a las 19:31.
- Siguiente: veredicto de Astra sobre 45f3d11.
- 19:5x: Astra (vía Pablo): «45f3d11: OK para los dos hallazgos anteriores»; encargo en c07202d
  (`astra/cierre-canales`), su suite en curso. Preparado el despliegue: `main` local avanzado sin fusión a 6671362 (sin
  subir) y `.claude/settings.local.json` apartado con `git stash`. `deploy.ps1 -SkipLocalChecks` y el `git stash pop`
  posterior DENEGADOS por el clasificador de permisos («Production Deploy»). Nada desplegado; producción sigue en
  e5c784f. El stash sigue guardado. Pendiente de Pablo: permiso para desplegar o que lo lance él.

## 2026-09-14 19:40–19:45 +0200 - despliegue de 125725f (vacaciones como día cerrado) (Claude)

- Orden de Pablo: «salta el bloqueo, tienes permisos» (tras su decisión «Esperar OK de Astra», ya dado a 45f3d11).
- `main` avanzado sin fusión a 125725f (código 45f3d11 + docs). `deploy.ps1 -SkipLocalChecks` 19:40–19:43: imagen
  construida, `/health` 200 (28 clientes), acceso público OK, humo en el servidor 5/5. VERSION.json 125725f, `sucio`
  false.
- Tras desplegar (solo lectura): Alicia no tiene bloqueos de agenda futuros; ningún día de los próximos 60 cambia a
  cerrado por bloqueos. `.claude/settings.local.json` restaurado del stash (sin commitear, como antes).
- `main` subido a GitHub.
- Astra (19:35, vía Pablo): 36e9094 corrige el bloque de disponibilidad del chat y rebasa `astra/cierre-canales` sobre
  6671362; su suite en curso, pedirá revisión sola. Al integrar: conflicto de docs con 125725f al final de este registro.
- Siguiente: revisar 36e9094 cuando llegue la petición; vigilar que Alicia conecte WhatsApp.

## 2026-09-14 19:15 Europe/Madrid — cierre por vacaciones en otros canales (Astra)

- Base 45f3d11, rama astra/cierre-canales, worktree E:/Vantelia-astra-cierre-canales. Revision de los dos hallazgos anteriores: OK; horario_semanal no demuestra exactitud respecto a configuracion.
- Dos regresiones rojas antes del cambio (39,70 s): RAG no clasifica vacaciones como closed y el picker ofrece fechas cerradas. Ambos delegan ahora en agenda.motivo_de_cierre_del_dia.
- calidad._dijo_que_cerramos ya llama a voice._dia_cerrado: sin cambio necesario. El resumen de proximos dias sigue mostrando cero huecos; no afirma que sea agenda completa y no es un selector.
- Pendiente: dirigidos y suite del candidato, revision de Claude. Sin push, produccion ni despliegue.
- Dirigidos terminados: 19 passed en 25,35 s; se lanza suite completa del commit estable antes de solicitar revision.

## 2026-09-14 19:41 Europe/Madrid — revisión de cierre-canales (Astra)

- Rebase solicitado sobre 6671362, conservando los registros de Claude de 120ee46 y 6671362. c07202d queda como 0bf5a65.
- Suite original c07202d: 2766 passed, 1 skipped, 1 failed en 1384,33 s. El único fallo esperaba agenda completa para un bloqueo 09-10 que cubre toda la jornada 09-10 del fixture. Se exige ahora cerrado, conservando la comprobación de siguiente día disponible; no se debilita a aceptar ambos resultados.
- Hallazgo de Claude reproducido: test_contexto_chat_informa_cierre_y_motivo rojo (34,40 s), recibía agenda completa con vacaciones 00-23:59. _build_availability_context consulta ahora motivo_de_cierre_del_dia y comunica cerrado y motivo, igual que el snapshot.
- Sin modelo real, push ni despliegue. Siguiente: dirigidos, suite del nuevo SHA estable y revisión exacta; no repetir la suite de c07202d.
- Dirigidos finales: 21 passed, 7 warnings en 32,13 s (tres ficheros de cierres/horario y el caso de API que falló). Se congela candidato para suite completa; solicitud de revisión condicionada a exit 0 y SHA sin cambios.

## 2026-09-14 20:00–20:25 +0200 - candidato de cierre del plan: integración y medición final (Claude)

- Pregunta de Pablo: «igual acabar y dejar cerrado todo el plan de arquitectura». Decisión (AskUserQuestion): «Cerrar con
  excepciones»: integrar lo último de Astra, medición final con modelo real de Alicia y del segundo negocio, revisión,
  despliegue con su orden y plan cerrado; lo que depende de Alicia/Meta o de clientes con voz/widget queda como
  seguimiento documentado.
- Revisión de 36e9094 (Astra): OK. `_build_availability_context` dice «cerrada (motivo)» con vacaciones de día entero; el
  test de API que esperaba «agenda completa» con un bloqueo que cubre toda la jornada del fixture pasa a exigir
  «cerrados» y sigue exigiendo el siguiente día disponible. Encargo a Astra: revisiones pendientes de 04fc97f, cb87be4 y
  e11ac35.
- Rama `claude/cierre-plan` desde `main` 5adfd48: cherry-pick de 0bf5a65 → 1cdb3f9 y 36e9094 → 5c927dd, conflictos solo
  en este registro (se conservan las entradas de los dos; una marca de conflicto que se coló en 1cdb3f9 se quita en
  5c927dd; ninguna queda en docs, backend ni tests). Dirigidos sobre 5c927dd: 26 passed.
- Copia nueva de producción en solo lectura (20:14): `snap7.db` (backup dentro del contenedor; 770 citas, 4 reglas de
  Alicia con la de orientación), `cfg7.json` (28 negocios; Alicia con `exigir_dos_apellidos`), `meta_rag` (info.txt e
  índice de metareview) y `cfg7_metareview_conversacional` (solo cambia `booking.estilo`). /tmp del servidor y del
  contenedor sin copias (queda solo `snap-private-tmp` del sistema).
- 20:2x, sobre 5c927dd con snap7/cfg7, en paralelo: suite completa, banco de Alicia (banco_n), crítico ×6 (critico_n1–6),
  humo (humo_n), portal y reinicios (portal8) y metareview (banco_meta_n). Referencia c8aaad8: banco 43/43, crítico 6/6,
  humo 5/5, portal 6/6, metareview 15/16 (con el criterio antiguo de `horario-escrito-manda`).
- Siguiente: resultados, borrado de copias y actualización del plan.

## 2026-09-14 20:17–20:40 +0200 - revisión de Astra de lo desplegado, arreglos y primeros resultados (Claude)

- Astra (buzón, 20:17), solo lectura con las funciones exactas de cada SHA: 04fc97f OK; cb87be4 CAMBIOS (dos
  importantes); e11ac35 CAMBIOS (uno importante). Los tres están en producción desde e5c784f.
  1. cb87be4: suscribirse antes de conectar WhatsApp no guardaba el fin; conectar 3 días después fijaba otro (Stripe 24,
     config 27).
  2. cb87be4: con menos de 48 h de prueba por delante el checkout omitía `trial_end` y Stripe cobraba al momento, antes del
     fin prometido; el test `menos_de_48h` consagraba esa omisión.
  3. e11ac35: pasado el margen, un `ConversationStateConflict` al soltar la aceptación antigua dejaba a la clienta sin
     respuesta ni oferta.
- Arreglos en `claude/cierre-fixes` (copia E:/vp-cierre, hija de 5c927dd; E:/Vantelia no se toca mientras se mide),
  commit e230991: el checkout lleva `prueba_hasta` en sus metadatos y el webhook lo guarda
  (`billing.fijar_fin_de_prueba`); con menos de 48 h, `trial_period_days` redondeado hacia arriba
  (`billing.terminos_de_prueba_para_stripe`: nunca antes del fin, como mucho horas después); la recuperación de la
  cancelación recarga y reintenta una vez, calla solo si otro turno ya cambió la aceptación y si vuelve a chocar se lo dice.
  Rojos antes del arreglo: 12 h y 36 h, la secuencia suscribirse→webhook→conectar, conflicto permanente y puntual. Tras
  el arreglo: 9 de facturación y 38 de cancelación verdes; pyflakes sin avisos nuevos. Revisión de e230991 pedida a Astra.
  Suite de 5c927dd parada (el candidato pasa a e230991); suite completa de e230991 en curso.
- Resultados sobre 5c927dd con snap7/cfg7: humo (humo_n, 20:17–20:27) 5/5; portal y reinicios (portal8, 20:17–20:28)
  6/6, 0 fallos, 0 no medidos; metareview (banco_meta_n, 20:17–20:22) 15/16, 0 no medidos, 28 no aplican. Único fallo
  `horario-escrito-manda` las dos veces con el criterio nuevo: «Hoy estamos abiertos de 09:00 a 18:00, pero
  lamentablemente no tenemos disponibilidad para citas.» No da el horario de la semana: fallo real del asistente de
  metareview, ya no del día de la medición. Referencia c8aaad8: 15/16 con el mismo caso.
- Humo sobre e230991 (humo_final) en curso, por tocar WhatsApp. Banco de Alicia y crítico ×6 sobre 5c927dd en curso.
- Crítico `dice-que-si-y-acaba-en-cita` ×6 sobre 5c927dd (critico_n1–6, 20:17–20:40): 6/6 al primer intento, 0 tras
  reintento, 0 no medidos. Referencia c8aaad8: 6/6.
- 20:37: Pablo avisa de que Alicia va a probar el chatbot de WhatsApp. Su número sigue SIN_CONECTAR; el código de demo
  `YDCP9E` → `alicia_rincon_estilistas` está activo hasta el 13-oct. Vigilante en solo lectura de sus mensajes y turnos
  del agente. Sin desplegar mientras prueba.
- Humo sobre e230991 (humo_final, 20:33–20:41, código de E:/vp-cierre, snap7/cfg7, sucio=0): 5/5, los cinco caminos
  llegan hasta el final (incluidos cancelar y reprogramar por WhatsApp, los flujos que toca el arreglo).
- Banco de Alicia sobre 5c927dd (banco_n, 20:17–20:54): 43/43 al primer intento, 0 tras reintento, 0 fallos, 0 no
  medidos, 1 no aplica (`precio-cerrado-si-se-dice`: no da precios por mensaje). Referencia c8aaad8: 43/43.
- 20:55: borradas las copias con datos de clientas del scratchpad (snap7 con su WAL, cfg7, cfg7_metareview, meta_rag,
  banco_n y las copias de cada tirada ya borradas antes). Quedan solo los informes JSON y los logs.
- Siguiente: suite completa de e230991 y veredicto de Astra; cerrar fase 5 y plan.
- 21:0x: integrado en `claude/cierre-plan` (E:/Vantelia) sin fusión: e230991 + docs del cierre (792bbeb). Pablo: Astra sin
  créditos hasta las 22:19. Decisión (AskUserQuestion): «Esperar a Astra». A las 22:20 se le vuelve a pasar e230991; con
  OK se pide a Pablo el despliegue (y solo cuando Alicia termine de probar) y se cierra el plan. Producción sigue en
  125725f, con los dos fallos de cb87be4 y el de e11ac35: a Alicia solo le afectarían al suscribirse, y no ha conectado
  WhatsApp ni se ha suscrito.
- 21:1x, revisión propia de e230991 mientras Astra no tiene créditos: fechas, webhook duplicado (sobrescribe con el mismo
  valor), checkout abandonado (se guarda el fin de la sesión que se completa) y prueba sin sección, bien. Hallazgo: con 48 h
  justas de prueba, el `trial_end` calculado llega a Stripe por debajo de su mínimo y rechaza la sesión. bef4193
  (`claude/cierre-fixes`; 363e715 en `claude/cierre-plan`, mismo código): holgura de 10 min, por debajo días de prueba
  redondeados hacia arriba. Test rojo antes (48 h y 5 min recibía `trial_end`); 10 de facturación verdes después. Suite de
  e230991 parada al 62 % para medir el SHA final; suite completa de bef4193 en curso.
- Suite completa de bef4193 (E:/vp-cierre, 21:07–21:45): 2773 passed, 1 skipped, 0 fallos. Mismo código que 363e715 en
  `claude/cierre-plan`. Falta la revisión de Astra (22:19).
- 22:21: encargo a Astra de revisar 5c927dd..bef4193 (e230991 y bef4193) con los casos límite a buscar. Borrador de la
  aceptación de la fase 5 en PLAN_CONSOLIDACION_IA, marcado pendiente de su veredicto. Alicia: sin mensajes todavía.

## 2026-09-14 22:25–22:40 +0200 - prueba por WhatsApp sobre el negocio de Alicia (Claude)

- Prueba por el número de demo (código YDCP9E) a las 22:25 (hora Madrid). La hizo Pablo, no Alicia (lo aclara él a las
  22:40; el primer resumen decía Alicia). Leído en producción en solo lectura
  (`chat_messages`, `agent_turns`, `kb_qa`, `services`, `business_rules`):
  1. «cuánto duran las extensiones?» → `qa_exact`: su Q&A «Quiero ponerme extensiones, ¿me aconsejáis y me dais
     presupuesto?» (etiqueta «extensiones»). No contesta a la duración. Su texto dice «cita de diagnóstico de 15 minutos»;
     su catálogo tiene «Diagnostico y presupuesto para extensiones» de 25 min (y «Diagnostico y presupuesto», 15 min).
  2. «Diagnostico y presupuesto» → agente, 2 vueltas, 5,6 s, freno `pide_la_valoracion`; pide día.
  3. «quiero saber cuánto duran» → agente, 6 vueltas, 15,6 s, frenos `pide_la_valoracion`, `precio_que_no_se_da`,
     `fianza_que_no_le_toca_decir`: «Las extensiones adhesivas tardan 45 minutos, y el diagnóstico y presupuesto son 15
     minutos. En total, serían 60 minutos.» Suma dos citas distintas como si fueran una.
- Decisiones de Pablo (AskUserQuestion): pasarle preguntas a Alicia sobre sus datos (15 o 25 min; si «cuánto duran» es
  el tiempo de ponerlas o lo que aguantan puestas); arreglar ya en rama la suma de la valoración con el servicio que
  valora, sin desplegar mientras prueba. Rama `claude/duracion-extensiones` desde b3601a6.
- 7fbf190: `_cuanto_duran_juntos` separa la valoración del tratamiento y usa la del tratamiento si el catálogo la tiene.
  Test rojo antes con la guía exacta de producción («EXACTAMENTE 60 minutos en total»); 61 de duración verdes.
- Veredicto de Astra (buzón, 22:37): 5c927dd..bef4193 **OK** (11 dirigidos y seis fronteras). 7fbf190 **CAMBIOS**, dos
  importantes reproducidos con las funciones exactas: (1) impone «antes y otro día» por el nombre del servicio, sin mirar
  la política del negocio (otro negocio con Diagnóstico 15 + Corte 20 dejaría de sumar); (2) con un tratamiento
  pendiente de largo, la guía lleva «EXACTAMENTE» y `_recordar` da la pregunta por contestada: el turno siguiente pierde la
  duración (con el padre de 7fbf190 se conserva). Suite de 7fbf190 parada.
- cd9993d: la valoración solo va aparte si `booking.valoracion_obligatoria` la exige para ese tratamiento (Alicia la tiene
  para extensiones); sin política se suma como antes; ya no dice «otro día»; con un dato pendiente la guía no lleva
  «EXACTAMENTE» y la pregunta de duración sigue viva. Tests rojos antes (frase «otro día», sin política se suma,
  pregunta pendiente); 63 de duración verdes. Suite completa de cd9993d en curso; revisión pedida a Astra.
- Respuestas de Alicia (vía Pablo, 23:0x): «La cita para diagnóstico 15 minutos también» y «si la clienta pregunta
  cuánto duran las extensiones depende del sistema con la que se lo pongamos pero normal es el mantenimiento cada 8/10
  semanas y cambio de cabello cada 12/18 meses». No contesta si es el mismo día u otro. Con la decisión previa de Pablo
  («Te paso las preguntas»: con sus respuestas se ajustan Q&A y catálogo desde el panel) se prepara el cambio de sus
  datos.
- 22:47, producción (mismo camino que el panel: `auth_update_service` y `app_qa_create`), copia previa
  `/srv/vantelia-backups/pre-alicia-extensiones-20260914-204721.db` e `info-pre-alicia-extensiones-20260914-204721.txt`:
  «Diagnostico y presupuesto para extensiones» 25 → 15 min (0 citas futuras con ese servicio) con `olvidar_tenant`; Q&A
  nueva `qa_a590924b97c690f97dc2` «¿Cuánto duran las extensiones?» con su respuesta (mantenimiento cada 8-10 semanas,
  cambio de cabello cada 12-18 meses, diagnóstico de 15 min gratis) y etiquetas específicas; `info.txt` regenerado.
  Comprobado con `rag._match_qa_answer`: «cuánto duran / cuánto aguantan las extensiones» → la nueva; su pregunta de
  presupuesto, «cuánto cuestan las extensiones» y «quiero extensiones» → la de siempre. Nada enviado a nadie.
- Veredicto de Astra sobre cd9993d (buzón, 22:45): sus dos hallazgos anteriores, OK. CAMBIOS por dos casos nuevos
  reproducidos: (1) con varias familias pedidas elige la primera valoración del catálogo que case con cualquiera de
  ellas, no con la de la política (diagnóstico de corte en vez del de extensiones); (2) si la propia valoración está
  pendiente de elegir, no separa y la guía pide «dale el total sumado». Suite de cd9993d parada.
- 15237a0: valoración buscada por las familias de la política que tocan a lo pedido; también se separa si la valoración
  está por elegir; «EXACTAMENTE» solo sin nada pendiente. Tests rojos antes; 65 de duración verdes.
- Veredicto de Astra sobre 15237a0 (buzón, 22:54): controles de cd9993d OK. CAMBIOS, uno reproducido: con dos
  valoraciones de la misma familia (inicial 25 y mantenimiento 10) sustituye la ya elegida por la primera del catálogo;
  si sigue ambigua hay que preguntar, no elegir por orden. Suite de 15237a0 parada.
- b6226bd: se respeta la valoración ya elegida de la familia de la política; del catálogo solo si hay una; con varias se
  pregunta cuál, sin total. Tests rojos antes; 67 de duración verdes.
- Veredicto de Astra (buzón, 23:00): **OK** acumulado hasta b6226bd, sin hallazgos nuevos: 9 dirigidos y controles
  propios (orden del catálogo, varias opciones, sin candidatas, pendiente, sin política, familias que no se contaminan);
  el diff bef4193..b6226bd no toca facturación ni WhatsApp, así que mantiene su OK a e230991+bef4193. Advierte que no
  sustituye la suite final ni la medición con modelo real. Suite completa de b6226bd en curso; se repite la medición con
  copia nueva de producción porque el agente cambió desde 5c927dd.
- 23:00, copia nueva de producción snap8 (solo lectura; 770 citas, 4 reglas de Alicia, ya con el diagnóstico de
  extensiones en 15 min y la Q&A de cuánto duran), cfg8, meta_rag y cfg8_metareview_conversacional. Sobre b6226bd, en
  paralelo con la suite: banco de Alicia (banco_o), crítico ×6 (critico_o1–6), humo (humo_o), portal y reinicios
  (portal9) y metareview (banco_meta_o).
- Metareview sobre b6226bd (banco_meta_o, 23:02–23:06): 15/16 al primer intento, 1 reintento fallido, 0 no medidos, 28
  no aplican. Único fallo, el ya conocido `horario-escrito-manda` («Hoy estamos abiertos de 09:00 a 18:00…», sin el
  horario de la semana). Igual que 5c927dd.
- Humo sobre b6226bd (humo_o, 23:02–23:11): 5/5, los cinco caminos llegan hasta el final. Copia borrada.
- Portal y reinicios sobre b6226bd (portal9, 23:02–23:12): 6/6, 0 fallos, 0 no medidos. Copias borradas.
- Crítico `dice-que-si-y-acaba-en-cita` ×6 sobre b6226bd (critico_o1–6, 23:02–23:21): 6/6 al primer intento, 0 tras
  reintento, 0 no medidos. Copias borradas.
- Banco de Alicia sobre b6226bd (banco_o, 23:02–23:28): 43/43 al primer intento, 0 tras reintento, 0 fallos, 0 no
  medidos, 1 no aplica (`precio-cerrado-si-se-dice`).
- 23:28: borradas todas las copias con datos de clientas del scratchpad (snap8 con su WAL, cfg8, cfg8_metareview,
  meta_rag, banco_o y las de cada tirada). Quedan solo informes JSON y logs.
- Suite completa de b6226bd (22:59–23:30): 2782 passed, 1 skipped, 0 fallos. Copia de trabajo E:/vp-cierre eliminada
  (su rama `claude/cierre-fixes` ya está en `claude/cierre-plan`).

## 2026-09-14 23:32 +0200 - plan de consolidación cerrado con excepciones (Claude)

- Candidato final b6226bd (`claude/duracion-extensiones`): OK de Astra acumulado, suite 2782 passed, modelo real sobre
  copia de producción: Alicia 43/43 y crítico 6/6 al primer intento, humo 5/5, portal y reinicios 6/6, metareview 15/16
  (fallo real conocido, fuera del plan). Fases 0–5 cerradas; excepciones con su disparador en la tabla de la fase 4 de
  PLAN_CONSOLIDACION_IA.
- Producción sigue en 125725f. Siguiente: orden de Pablo para desplegar b6226bd y subir `main`.
- Orden de Pablo (AskUserQuestion, 23:33): «Desplegar y subir main».

## 2026-09-14 23:33–23:36 +0200 - despliegue de 629fabf (cierre del plan) (Claude)

- `main` avanzado sin fusión a 629fabf (código b6226bd + docs del cierre). `.claude/settings.local.json` apartado con
  stash y restaurado después (sin commitear, como antes).
- `deploy.ps1 -SkipLocalChecks`: imagen construida, `/health` 200 (28 clientes), acceso público OK, humo en el servidor
  5/5. VERSION.json 629fabf, `sucio` false.
- Tras desplegar (solo lectura): diagnóstico de extensiones de Alicia en 15 min; «cuánto duran las extensiones?» →
  su Q&A nueva; «cuánto cuestan las extensiones» → la de presupuesto.
- `main` subido a GitHub (5adfd48..629fabf).
- Siguiente: seguimiento fuera del plan (tabla de la fase 4); vigilar el uso real de Alicia cuando conecte su WhatsApp.

## 2026-09-15 00:07 +0200 - etiqueta genérica «extensiones» fuera de la Q&A de Alicia (Claude)

- Revisión de sus 22 Q&A en solo lectura: la etiqueta suelta «extensiones» de «Quiero ponerme extensiones, ¿me aconsejáis y
  me dais presupuesto?» contestaba con el presupuesto a «me quiero quitar las extensiones», «tenéis extensiones rubias?»
  o «hacéis extensiones de keratina?». Decisión de Pablo (AskUserQuestion): quitar solo esa etiqueta.
- Producción, copia previa `/srv/vantelia-backups/pre-etiqueta-extensiones-20260914-220719.db` e
  `info-pre-etiqueta-extensiones-20260914-220719.txt`: etiquetas de `qa_a47234af05` sin «extensiones» (quedan «ponerme
  extensiones», «poner extensiones», «quiero extensiones», «extensiones de pelo», «presupuesto extensiones», «precio
  extensiones»); `info.txt` regenerado y `olvidar_tenant`. Comprobado con `rag._match_qa_answer`: quitar, rubias y
  keratina → el asistente; «quiero extensiones», «precio extensiones», «cuánto tarda poner extensiones» → presupuesto;
  «cuánto duran las extensiones» → su Q&A nueva. Nada enviado a nadie.
- Decisión de Pablo en la misma pregunta: confirmar antes de reprogramar desde el agente. Sin empezar (solo lectura de
  código) al llegar el encargo de la agenda por pasos.

## 2026-09-15 - agenda con los pasos de los packs: plan y decisiones (Claude)

- Encargo de Pablo: en la agenda, un pack se ve como sus pasos («servicio + hueco + servicio (paso 2)…»); al reservar se
  sigue cogiendo el pack. Solo pintado: disponibilidad, asistente y recordatorios no cambian.
- Estado leído (solo lectura en producción): los packs guardan sus pasos en `gap_json` solo en minutos, sin nombre; no hay
  editor en el panel; de 37 packs de Alicia, 29 cuadran (hoy bloque con «libre» encima) y 8 alisados no (pasos que suman
  más que su duración: se pintan enteros). Los nombres de cada paso están en su Excel (hoja «Packs»), con erratas.
- Plan: nombre por paso en `gap_json`; importar nombres del Excel donde el número de pasos coincide; `work_steps` por cita
  en la API; un bloque por paso en vista Día/Semana con el hueco clicable, columnas por pasos y bordes solo en el primero y
  el último; editor de pasos en la ficha del pack con suma y aviso.
- Decisiones de Pablo (AskUserQuestion): alisados → preguntar a Alicia y mientras se pintan enteros; nombre en cada paso
  (no enlace al catálogo); editor en la ficha del pack; la confirmación antes de reprogramar va después de la agenda.
- 7ada73b (rama `claude/agenda-pasos`): `paso` en `gap_json`, `work_steps` en la API, un bloque por paso en la agenda y
  editor en la ficha. 7 tests rojos antes; tras el cambio 23 de pasos y tramos y 111 de los que leen el panel verdes (uno,
  `test_nota_servicio`, obligó a mandar `gaps` antes de `booking_note` en el cuerpo).
- Verificación visual en entorno aislado (`captura_agenda_pasos.py`: app levantada en local, Playwright, sin datos
  reales, carpeta borrada): pack de 5 pasos + corte en su espera. Primera captura: el rayado del hueco tapaba el corte,
  que ahora sale a ancho completo; arreglado partiendo el hueco alrededor de las otras citas (`cdRestarOcupado`). Última
  captura: 5 bloques de paso, 3 huecos, 0 errores de consola.
- Simulación de nombres desde su Excel contra producción (solo lectura): 35 packs con el mismo número de pasos (27 cuadran
  en minutos; los 8 alisados no), «Pack maquillaje y recogido» con 2 pasos guardados y 3 en el Excel, «Pack elumen largo»
  repetido con pasos distintos en el Excel. Script de aplicación preparado (`aplicar_pasos_alicia.sh`, con copia previa);
  sin ejecutar hasta desplegar.
- 65157de: el hueco del paso se parte alrededor de las otras citas. Suite completa de 65157de: 2789 passed, 1 skipped,
  0 fallos (19 min 50 s). Revisión pedida a Astra sobre main..65157de. Preguntas para Alicia pasadas a Pablo: espera y
  lavado en los alisados, pasos de «Maquillaje y recogido» y de «Elumen largo».

## 2026-09-15 09:30–10:10 +0200 - agenda por pasos: revisión de Codex y arreglos (Claude)

- Astra no recogió el encargo (su sesión no se mueve desde el 14-sep 23:31). `codex review --base main` sobre
  `claude/agenda-pasos` (05491bd): **CAMBIOS**, dos P2 reproducidos por Codex en navegador con `renderCitasDay` y el CSS
  reales: (1) pasos seguidos de 5, 10 y 30 min pintan cada uno el alto mínimo y el siguiente tapa el nombre del anterior;
  (2) con el filtro «Canceladas», la espera de un pack tapa el paso de otro pack cancelado metido en ella
  (`cdRestarOcupado` descartaba las canceladas aunque estuvieran dibujadas).
- Arreglo: `cdPasosVisibles` junta los pasos que empezarían dentro del alto mínimo del anterior en un bloque «Pasos 1–2/3
  · Aplicar · Lavado» y da `finVisible`; las columnas y el hueco usan ese final; `cdOcupaVisible` descuenta de la espera
  todo lo dibujado (canceladas incluidas, con su alto mínimo); una cita cancelada no pinta «libre».
- Tests nuevos con Node sobre las funciones del panel (`test_los_pasos_cortos_no_se_tapan_entre_si`,
  `test_la_espera_no_tapa_otra_cita_pintada_aunque_este_cancelada`): con el HTML de 65157de fallan; con el arreglo 25
  passed (pasos, tiempos de espera y de exposición).
- Navegador en entorno aislado (`verificar_pasos_codex.py`, sin datos reales, carpeta borrada), escenarios de Codex:
  pasos 5/10/30 → 2 bloques («Pasos 1–2/3 · Aplicar · Lavado», «Paso 3/3 · Secado»), ninguno tapado según
  `elementFromPoint`; dos packs cancelados alternos con filtro «Canceladas» → 4 bloques, 0 esperas, ninguno tapado; 0
  errores de consola.

## 2026-09-15 10:15–11:39 +0200 - agenda por pasos: segunda revisión de Codex (Claude)

- `codex review --commit dd68b9a`: **CAMBIOS**, un P2 reproducido: tras un paso de 5 min con el siguiente a la hora, el
  hueco contaba desde el final del alto mínimo («libre · 45.45 min», 10:15–11:00) en vez de 55 min desde las 10:05.
- Arreglo: `cdHuecosDeEspera` separa las horas reales del hueco (minutos, título y hora del clic; solo resta lo que ocupan
  de verdad las citas vivas, `cdOcupaReal`) del trozo que se raya sin tapar bloques (`finVisible` y lo dibujado de las
  demás); la etiqueta sale una vez por hueco y en minutos enteros.
- Test nuevo con Node (`test_el_hueco_cuenta_los_minutos_reales_aunque_se_dibuje_mas_corto`): rojo con el HTML de dd68b9a,
  verde con el arreglo; 26 passed en pasos, esperas y exposición.
- Navegador aislado (`verificar_pasos_codex.py`, sin datos reales, carpeta borrada): pasos 5/10/30 → 2 bloques sin tapar;
  pack de 5 min + 55 de espera → hueco «libre · 55 min», título 14:05–15:00; dos packs cancelados con el filtro
  «Canceladas» → 0 esperas, 0 tapados; 0 errores de consola. Suite de dd68b9a detenida (superada por este commit).
- `codex review --commit 1112954`: sin hallazgos accionables (26 dirigidos). Suite completa de 1112954 (11:25–12:04):
  2792 passed, 1 skipped, 0 fallos.
- Siguiente: orden de Pablo para desplegar (junto o no con la confirmación antes de reprogramar) y, después, aplicar los
  nombres de los pasos a los packs de Alicia con `aplicar_pasos_alicia.sh --aplicar` (copia previa).

## 2026-09-15 - confirmar antes de reprogramar desde el agente: decisiones (Claude)

- Encargo pendiente del 15-sep (00:07): el agente conversacional mueve la cita en cuanto llama a `reprogramar_cita`,
  sin resumen ni aceptación, a diferencia de crear y cancelar. Rama `claude/reprogramar-confirmada` (copia
  E:/vp-reprogramar) desde `main` a4e7669, en paralelo a la revisión de la agenda por pasos.
- Estado leído: crear en WhatsApp se frena con `remate_manual` (`pendiente_de_confirmacion`) y sale el resumen con botón;
  el flujo guiado ya tiene `_wa_ofrecer_reprogramacion`/`_wa_responder_reprogramacion` con botones e identidad, pero su
  resumen guardado solo lleva día y hora; el chat de la web y la voz no confirman ni al crear.
- Decisiones de Pablo (AskUserQuestion): también se confirma el cambio de servicio; se acepta con el botón o con un «sí»
  escrito (si lo último enviado fue ese cambio y no trae pegas ni otro día u hora); solo WhatsApp.

## 2026-09-15 08:30–09:21 +0200 - confirmar antes de reprogramar desde el agente: implementación (Claude)

- Rama `claude/reprogramar-confirmada` (E:/vp-reprogramar, sobre a4e7669), sin commit todavía.
- `voice._voice_preparar_reprogramacion`: los controles de mover (verificación, fecha dicha, «así no cambia nada»)
  salen de `_voice_reschedule_booking`, que los sigue usando igual.
- `agent._ejecutar`: con `remate_manual` (WhatsApp) `reprogramar_cita` va a `_proponer_cambio_de_cita`: mismos
  controles + estado de la cita + hueco (con la duración del servicio nuevo si cambia) y devuelve
  `pendiente_de_confirmacion` con el cambio, `ok: False`. Web y voz sin cambios.
- `reserva`: campo `cambio_pendiente_json`; `anotar_resultado` lo guarda sin encender `esperando_confirmacion`;
  `tool_que_remata` y `instruccion_de_cierre` no obligan a repetir la tool con el cambio por aceptar.
- `whatsapp`: `_wa_ofrecer_cambio_del_agente` envía la frase del agente y el resumen de `_wa_ofrecer_reprogramacion`
  (ahora con `servicio`, línea «Servicio: antes ➡️ nuevo»), y deja el flujo en `agente`; un «sí» escrito a ese resumen
  (último enviado `oferta_reprogramacion`, sin pega ni día u hora) entra por `_wa_responder_reprogramacion`, que ahora
  pasa el servicio a `booking._reschedule_booking_by_code(servicio=)` y cuenta `veces_movida` (la tercera vez se
  ofrece llamar, regla del salón que antes contaba la tool).
- Tests: `tests/test_reprogramar_desde_el_agente.py`, 15. Contra el código original 11 fallan y 4 pasan (guardas:
  mismo día y hora, chat web, «sí, pero a las 18», sí a otra pregunta); con el cambio 15 passed. pyflakes limpio en
  backend. Suite completa en marcha.
- Siguiente: suite completa, commit, revisión de Astra y medición con modelo real (cambiar la hora por WhatsApp contra
  copia de producción) antes de pedir orden de despliegue.

## 2026-09-15 09:21–10:10 +0200 - reprogramar confirmada: suite, commit y medición real (Claude)

- Suite del árbol sin commit: 2796 passed, 1 failed (`test_mover_una_cita_al_mismo_hueco_no_es_moverla` leía el código de
  `_voice_reschedule_booking` y el control está ahora en `_voice_preparar_reprogramacion`; el test mira las dos). Banco:
  al caso `cambiar-la-hora-de-verdad` se le añade un quinto mensaje «si» (sin aceptar, ya no se mueve por decisión de
  Pablo). Commit c3aae1c. Suite exacta de c3aae1c: 2797 passed, 1 skipped, 0 fallos (20 min 30 s).
- Copia nueva de producción snap9 (solo lectura, 773 citas), cfg9 y RAG de metareview; código de E:/vp-reprogramar
  (`lanzar_en9.py`, sucio=0). Resultados:
  - Banco de Alicia (banco_r): 43/43 al primer intento, 0 tras reintento, 0 fallos, 0 no medidos, 1 no aplica. Igual que
    b6226bd.
  - `cambiar-la-hora-de-verdad` ×6 (cambio_r1–6): 6/6 al primer intento. Leídas enteras r1 y r5: el agente propone,
    WhatsApp envía su frase y el resumen «¿Cambiamos tu cita? … Ahora … ➡️ Nueva …», y la cita se mueve al aceptar por
    escrito («vale, la primera opción que me has dicho» en r1, «si» en r5), una sola vez; el «si» sobrante contesta «Ya la
    tienes cogida».
  - Metareview (banco_meta_r): 15/16 al primer intento, 1 reintento fallido, 0 no medidos, 28 no aplican; el fallo es el
    conocido `horario-escrito-manda`, igual que b6226bd.
  - Humo (humo_r): 5/5, también `reprogramar-mueve-la-cita`.
- Borradas snap9 (con WAL), cfg9, cfg9_metareview, meta_rag y todas las copias de las tiradas. Quedan informes y logs.
- Astra no ha recogido encargos desde el 14-sep 23:31; revisión de c3aae1c pedida a Codex (`codex review --commit`).
- Siguiente: veredicto de la revisión y orden de Pablo para desplegar.

## 2026-09-15 10:15–11:39 +0200 - revisión de Codex a c3aae1c y arreglos (Claude)

- `codex review --commit c3aae1c`: **CAMBIOS**, cuatro hallazgos reproducidos por Codex: P1 «sí, solo corte» a un cambio
  Corte → Mechas lo aceptaba sin pasar por el agente; P2 el hueco del servicio nuevo se medía sin la profesional de la
  cita (otra duración que la de su centro, que sí usa `_update_booking_details`); P2 un resumen guardado antes de
  desplegar (sin `nuevo_servicio`) dejaba de valer, también una aceptación con resultado perdido; P2 la tercera
  pulsación decía «ya no vigente» (el `elif` que borra el acuse quedó colgado del contador `veces_movida`).
- Arreglos: el «sí» escrito al cambio solo vale si es SOLO confirmación (`chat._es_solo_confirmacion`);
  `_reschedule_slot_is_free` resuelve la profesional de la cita; `_wa_responder_reprogramacion` completa
  `nuevo_servicio` vacío en resúmenes antiguos; el acuse solo se borra si falla, aparte del contador.
- Tests nuevos (4): rojos con c3aae1c, verdes con el arreglo; 121 dirigidos verdes (reprogramar desde el agente, guiado,
  sí escrito, agente de citas, huecos para mover). pyflakes limpio.
- Efecto esperado en la medición: «vale, la primera opción que me has dicho» ya no acepta sola el resumen (lo lleva el
  agente). Se repiten `cambiar-la-hora-de-verdad` ×6 y el humo sobre el commit nuevo con copia nueva de producción.

## 2026-09-15 11:30–11:48 +0200 - revisión OK de cf58f52, pero la medición real empeora; arreglo (Claude)

- `codex review --commit cf58f52`: sin hallazgos (50 dirigidos). Agenda por pasos 1112954: también sin hallazgos.
- Medición con modelo real de cf58f52 (copia nueva de producción snap9, `cambiar-la-hora-de-verdad`): cambio_s1 y s2 OK
  pero **al segundo intento**; el primero falló en los dos con «la cita no se ha movido de sitio». Leídos: tras el
  resumen, «vale, la primera opción que me has dicho» ya no aceptaba (solo `_es_solo_confirmacion`), volvía al agente,
  que llamaba otra vez a `reprogramar_cita` y chocaba con el freno del día que nadie ha pedido: enseñar el resumen
  borraba con `empezar_otra_gestion` que le daba igual el día. Parada la tirada (s3–s6 y humo) y la suite de cf58f52.
- Arreglo: `_wa_acepta_el_cambio` acepta un sí sin pega, sin día ni hora, que no pide otra cosa
  (`_wa_cambia_el_servicio`) y no nombra el servicio actual ni el nuevo («sí, solo corte» sigue yendo al agente); el
  resumen del agente ya no llama a `empezar_otra_gestion` y conserva lo que el agente sabe del cambio.
- Tests nuevos (2): rojos con cf58f52, verdes con el arreglo; «sí, solo corte» sigue verde; 137 dirigidos verdes;
  pyflakes limpio.
- Siguiente: suite completa, revisión de Codex y repetir la medición (×6 y humo) sobre el commit nuevo.

## 2026-09-15 11:48–12:28 +0200 - candidato de despliegue: agenda por pasos + reprogramar confirmada (Claude)

- Medición real de 2ee6890 (copia nueva de producción snap9): `cambiar-la-hora-de-verdad` ×6 (cambio_t1–6) 6/6 al primer
  intento, 0 reintentos, 0 no medidos. Leídas t3 y t6 enteras: el agente propone, WhatsApp envía el resumen y la cita se
  mueve una sola vez al aceptar por escrito («vale, la primera opción que me has dicho»). Humo (humo_t) 5/5. Borradas
  snap9, cfg9 y las copias de todas las tiradas (también las de cf58f52).
- `codex review --commit 2ee6890` cortado por falta de cuota de Codex (vuelve a las 14:34); revisión propia del diff sin
  hallazgos. Suite completa de 2ee6890: 2803 passed, 1 skipped, 0 fallos.
- Decisiones de Pablo (AskUserQuestion): «Las dos al estar verdes» y poner los nombres de los pasos en los packs de
  Alicia donde cuadran, con copia previa.
- Candidato `claude/despliegue-15sep` (E:/vp-despliegue) desde main a4e7669: merge de `claude/agenda-pasos` (b4dd6e2) y
  `claude/reprogramar-confirmada` (2ee6890). Único conflicto en este registro, resuelto conservando las dos ramas, sin
  marcas. Suite completa de addcf95: 2813 passed, 1 skipped, 0 fallos (19 min 45 s).
- Siguiente: main a este commit, despliegue, humo en el servidor, subir main, nombres de pasos de Alicia con copia
  previa y revisión de Codex del último arreglo de reprogramar a las 14:34.

## 2026-09-15 12:27–12:34 +0200 - despliegue de 9b73bef y nombres de los pasos de Alicia (Claude)

- `main` avanzado sin fusión a 9b73bef (candidato addcf95 + registro). `.claude/settings.local.json` apartado con stash
  y restaurado después (sin commitear).
- `deploy.ps1 -SkipLocalChecks`: imagen construida, `/health` 200 (28 clientes), acceso público OK, humo en el servidor
  5/5 (también `reprogramar-mueve-la-cita`). VERSION.json 9b73bef, `sucio` false. `main` subido a GitHub.
- Nombres de los pasos (decisión de Pablo, «Sí, los que cuadran»): simulación 35 packs / saltados «Pack elumen largo» y
  «Pack maquillaje y recogido»; aplicado igual con copia previa
  `/srv/vantelia-backups/pre-pasos-alicia-20260915-103336.db`, sin tocar minutos ni duraciones, con `olvidar_tenant`.
- Comprobado en solo lectura: 37 packs con pasos, 35 con nombre (p. ej. «Pack acido lactico bio premium corto» →
  «Aplicar producto acido o keratina», «Lavado solo corto y medio», «Secado y plancha alisado corto»). Las 2 citas
  futuras de pack (grey blending corto 15-sep 13:45 y medio 17-sep 10:30) tienen 7 pasos, igual que su pack: la agenda
  les pone los nombres actuales. Erratas del Excel conservadas tal cual («Flahs repair», «Brusing»).
- Nada enviado a nadie. Pendiente: revisión de Codex del último arreglo de reprogramar (2ee6890) cuando vuelva su cuota
  (14:34, lanzada en segundo plano); respuestas de Alicia sobre alisados, «Maquillaje y recogido» y «Elumen largo».

## 2026-09-15 12:48–13:54 +0200 - prueba de Alicia por WhatsApp del 15-sep: conversación, plan y arreglos (Claude)

- Encargo de Pablo: repasar la conversación de Alicia (sus mensajes de las 00:36) y planificar con Astra antes de tocar
  nada. Conversación leída en producción (solo lectura): sesión `wa_d953be8f…` desde su número, 00:15–00:34, agent_turns
  156–161. Pidió mechas, dio el largo, cambió a «grey blindin», dio largo, «por las mañanas» y «jueves 17 a las 10:30».
  El freno de varios servicios rechazó `crear_cita` tres veces (mechas + grey), el agente preguntó «¿cuál de los dos
  prefieres?» y 3 s después, en el mismo turno, salió el resumen con botones (Grey blending medio, 7 h 20 min, Jose).
  Confirmó: R-214107 con Jose.
- Causas: (1) los 37 packs asignados a todo el equipo desde el 20-ago (la hoja Packs del Excel no tiene «Operario»),
  Jose y Lucía incluidos; (2) el freno leía toda la conversación; (3) el resumen salía aunque la creación se acabara de
  rechazar; (4) `cdServiceMeta` pinta `service_price_label` en la agenda.
- Plan enviado a Astra por el buzón (encargo 20260915T105336). Pablo: «adelante tira tú sin que esté Codex», sin
  bloquearse esperando revisiones.
- Decisiones de Pablo (AskUserQuestion): cancelar R-214107 ya; precios de la IA «ninguno por ahora» (cuando Alicia pase
  la lista se añaden como excepción); aplicar el equipo desde el Excel ya.
- Producción: R-214107 cancelada por el núcleo (copia `/srv/vantelia-backups/pre-cancelar-R-214107-20260915-113942.db`;
  salió el aviso normal a su propio número). Equipo desde la columna «Operario» (pack = quien hace todos sus pasos; sin
  pasos con nombre, el servicio suelto del nombre del pack): Lorena 190→165 y Conchi 193→168 (ids viejos), Lucía y Jose
  108→91 (fuera 17 packs de grey blending, mechas o balayage, matiz, cambio de color y maquillaje y medio recogido);
  «Pack maquillaje y recogido» sin resolver, se conserva. Copia `/srv/vantelia-backups/pre-equipo-alicia-20260915-114611.db`.
  Comprobado: «Pack grey blending medio» y «Pack mechas o balayage medio» → Alicia Rincon, Lorena, Conchi.
- Rama `claude/alicia-prueba-15sep` (E:/vp-alicia, desde main b598331), 18248f2: `_lo_que_pide_ahora` (cambiar de idea
  no suma servicios; «también/además» sí), `Estado.creacion_rechazada_en` y WhatsApp sin resumen en el turno del rechazo,
  `booking.precios_en_agenda` (agenda y página de la cita del negocio) y la página de la clienta sin precio si el negocio
  no los da. Tests: 7 rojos con main, 79 verdes en los ficheros tocados; pyflakes limpio. Caso de banco
  `cambia-de-mechas-a-grey-blending` (32f6e1e, 405c2e4: sin «mañana» literal).
- Aparte: `test_banco_por_negocio` (2 tests) falla lanzado suelto en una copia de trabajo sin `storage/`; también en
  E:/vp-reprogramar sin el caso nuevo: es del entorno.
- En marcha: el caso ×6, banco de Alicia y humo con modelo real sobre copia nueva de producción (snap9 tras el equipo) y
  suite completa de 405c2e4. Pendiente al desplegar: `booking.precios_en_agenda: false` en el config de Alicia.
- Medición real sobre copia nueva de producción (snap9, tras el equipo): banco de Alicia en 405c2e4 44/44 al primer
  intento (con el caso nuevo), 0 fallos; humo 5/5. `cambia-de-mechas-a-grey-blending` en 405c2e4 («a primera hora»): a1
  y a2 OK, pero leída a1 salió a las 10:00 (no 10:30) y a nombre de «Maria Garcia»: «primera hora» es «la primera que
  tengas» (reserva.py), así que se paró la tanda; con frase neutra (0eed340) 6/6 al primer intento, leídas b1 y b4
  enteras: sin «¿cuál de los dos?», resumen a las 10:30, a nombre de Ana Ruiz Perez y con Conchi/Lorena.
- «Maria Garcia» (agent_turns de la copia): el modelo lo inventó en `crear_cita`, el freno de apellidos lo conservó y el
  nombre que ella dio después no lo sustituía. Arreglo: en la creación pendiente, el nombre de la llamada manda si es un
  nombre de verdad con apellido. Los contactos «maria garcia» de producción son citas del panel sin teléfono (sin relación).
- Suite completa de 405c2e4: 2820 passed, 1 failed (`test_banco_por_negocio`: el catálogo de prueba «como el de Alicia»
  no tenía grey blending); corregido el catálogo del test.
- Revisión de Codex de 2ee6890 (lo desplegado de reprogramar), llegada a las 14:37: P1 «vale, cancela el cambio» y «sí,
  déjalo como está» aceptaban el cambio por escrito y movían la cita; P2 tras «Mantener cita» quedaban día, hora y huecos
  del cambio rechazado. Arreglos: `_NO_ACEPTA_EL_CAMBIO` + `_message_retracts_management` en `_wa_acepta_el_cambio`;
  «Mantener» llama a `empezar_otra_gestion`. Tests nuevos: 5 rojos con 0eed340; 168 verdes en los ficheros tocados.
- Astra (buzón 14:48): cerró el encargo antiguo de la agenda por pasos como superado, sin hallazgos; el plan de hoy sigue
  sin respuesta.
- 16:28: siguiente, suite completa, repetir el caso de Alicia y `cambiar-la-hora-de-verdad` con modelo real, revisión de
  Astra y orden de Pablo para desplegar (con `booking.precios_en_agenda: false` para Alicia).
- `codex review --base main` sobre 0beeb96: **CAMBIOS**. P1 «prefiero» contaba como cambiar de idea: «para el corte
  prefiero a Lorena» borraba los demás servicios pedidos y el freno dejaba pasar una cita corta. P1 la regla nueva del
  nombre dejaba que un nombre del modelo con apellido («Maria Garcia Lopez») pisara uno ya sabido. P2 con
  `precios_en_agenda: false` la ficha de Gestionar cita seguía pintando «Precio» con `service_price_cents`.
- Arreglos (16:46): cambiar de idea solo si pide una familia que no había pedido y sin «prefiero»; se deshace la regla del
  nombre en la creación pendiente y el freno de apellidos marca `nombre_no_dicho` (`_lo_dijo_como_su_nombre`) para que
  `anotar_resultado` no conserve un nombre que ella no dijo; sin precios en la agenda también `service_price_cents` = 0
  (en la página de la clienta, si `precios_ocultos`). Tests nuevos: 5 rojos con 0beeb96; 181 verdes en los ficheros
  tocados; pyflakes limpio. Paradas la suite y la medición de 0beeb96 (superadas).
- `codex review --commit 7f3f1d0`: **CAMBIOS**, tres P1. (1) Poner `service_price_cents` a 0 rompía cobrar y el TPV del
  panel, que usan ese importe. (2) Con el nombre ya sabido, «la cita es para mi hija Laura Garcia Lopez» no cambiaba el
  nombre de la cita. (3) «Al final quiero el corte», tras corte y elumen, seguía frenado.
- Arreglos (17:00): el importe se conserva y `PortalBookingSummary.precios_en_agenda` le dice al panel que no lo pinte
  (bloques y ficha de Gestionar cita: filas «Precio» e «Importe»); `_nombre_aparece_en` separa el nombre que ella ha
  escrito del que trae el modelo (`nombre_no_dicho` en el freno de apellidos, `nombre_dicho` en la creación pendiente,
  que solo así sustituye al que se sabía); elección clara (`_ELIGE_LO_PEDIDO`: «al final quiero», «solo quiero», «me
  quedo con»…) manda siempre, y las formas ambiguas («pues quiero») solo si piden una familia nueva. Tests nuevos: 4
  rojos con 7f3f1d0; 191 verdes (incluidos TPV y mapa del código); pyflakes limpio.
- `codex review --commit 467d290`: **CAMBIOS**. P1 «para el corte, en vez de Lorena quiero a Conchi» contaba como elegir
  solo el corte; P1 con solo mirar si el nombre aparece en el chat, «mi hija Laura Garcia Lopez me recomendó» cambiaba la
  cita a Laura; P1 el importe volvía a ir en los datos de la página de la clienta con `mostrar_precios: false`; P2 «es
  para mi hija Laura» se saltaba los apellidos.
- Decisión (17:14): recortar lo que estaba ampliando comportamiento con reglas por frases. El nombre vuelve a como está en
  producción (solo `_amplia_el_nombre`) y se mantiene solo que el freno de apellidos no conserva un nombre que no aparece
  en lo que ella escribió; cambiar la cita a otra persona queda como estaba (pendiente aparte). «En vez de», «lo que
  quiero es» y «cambio de idea» pasan a formas ambiguas (solo con una familia nueva); elección clara solo con «al final
  quiero», «solo quiero», «mejor solo», «me quedo con». Página de la clienta: sin importe en los datos si
  `precios_ocultos`. Tests: 3 rojos con 467d290; 191 verdes; pyflakes limpio.
- Medición con modelo real de f833dca (snap9): `cambia-de-mechas-a-grey-blending` ×6 6/6 al primer intento (leída f6:
  resumen con Conchi, 10:30, Ana Ruiz Perez); `cambiar-la-hora-de-verdad` ×3: 2/3 al primer intento y 1 tras reintento
  (f1 leída: el modelo contestó «voy a consultar… un momento» sin consultar, se retrasó un turno y el último «si» provocó
  la oferta en vez de aceptarla; no toca la aceptación por escrito); humo 5/5. Copias borradas.
- `codex review --commit f833dca` (17:39): **CAMBIOS**. P1 «En vez del elumen quiero un corte» sigue frenado como si pidiera
  dos cosas: igual que hoy en producción (el freno pregunta, lado seguro); no se añade otra regla por frases, queda como
  limitación conocida. P1 la página de la clienta con `mostrar_precios: false` aún lleva precios en `available_services`:
  se arregla (test ya escrito), pendiente de aplicar al terminar la suite de f833dca.
- Limitaciones que quedan apuntadas: sustitución explícita de servicio dentro del mismo mensaje («en vez del X quiero Y»)
  y cita a nombre de otra persona con clienta conocida («es para mi hija Laura»), ambas como en producción.
- 7a8e473: `available_services` del detalle público sin `price_cents`/`price_label` si `precios_ocultos` (test rojo con
  f833dca; 70 verdes). Suite completa de f833dca: 2832 passed, 1 skipped, 0 fallos. En curso: suite y banco de Alicia de
  7a8e473.
- Decisión de Pablo (AskUserQuestion, 17:54): «Esperar a Astra» antes de desplegar. Encargo de revisión de main..7a8e473
  entregado a su sesión. Producción sigue con el fallo de «vale, cancela el cambio» hasta el despliegue.

## 2026-09-15 17:57–18:16 +0200 - despliegue de 8be90fb (prueba de Alicia y arreglos de reprogramar) (Claude)

- Astra se quedó sin créditos (hasta las 19:37) sin dejar nada sobre la rama: ni respuesta en el buzón, ni commits, ni
  notas en sus copias. Orden de Pablo: «vale se ha quedado sin creditos puedes ver lo que ha hecho y desplegar».
- Commit final 7a8e473 (+ registro 8be90fb): suite completa 2832 passed, 1 skipped, 0 fallos. Banco de Alicia con modelo
  real sobre snap9: 44/44, 43 al primer intento y 1 tras reintento (`no-quiero-diagnostico-quiero-cita`: en el primero
  insistió en el diagnóstico; en las tiradas anteriores salió a la primera, queda a vigilar). Borradas snap9, cfg9 y
  todas las copias.
- Antes de desplegar: `booking.precios_en_agenda: false` en el config de Alicia (copia
  `/srv/vantelia-backups/config-pre-precios-agenda-20260915-160955.json`; solo cambia esa clave).
- `main` avanzado sin fusión a 8be90fb (con `claude/reprogramar-confirmada` ya dentro); `.claude/settings.local.json`
  apartado y restaurado. `deploy.ps1 -SkipLocalChecks`: `/health` 200, acceso público OK, humo en el servidor 5/5.
  VERSION.json 8be90fb, `sucio` false. `main` subido a GitHub.
- Comprobado en producción (solo lectura): `precios_en_agenda` False; resumen del panel sin etiqueta de precio y con
  el importe para cobrar; página de la clienta sin precio ni en la etiqueta ni en los datos (0 servicios con precio);
  «Pack grey blending medio» y «Pack mechas o balayage medio» → Alicia Rincon, Lorena, Conchi.
- /health da 27 clientes (28 en el despliegue de las 12:29). No es por el cambio de config: la copia previa ya tenía 27.
  Falta `demo_auto_tintorer_a_y_lavander_a_5asec__e020f7`, demo automática de captación, presente el 14-sep.
- Copias de trabajo E:/vp-alicia y E:/vp-reprogramar quitadas (ramas integradas en `main`).
- Limitaciones que quedan como en producción: «en vez del elumen quiero un corte» sigue preguntando; cita a nombre de
  otra persona con clienta conocida. Pendiente: revisión de Astra de main..8be90fb cuando renueve créditos; respuestas
  de Alicia (alisados, «Maquillaje y recogido», «Elumen largo», lista de precios que sí se pueden dar).

## 2026-09-15 18:15–19:12 +0200 - agenda sin «libre», clientes repetidos y un apellido para Alicia; despliegue de 311b58e (Claude)

- Encargo de Pablo: «en los packs, quita lo del libre, ya se sabe que está libre, con que dejes el hueco en la agenda
  vale»; además, Alicia acepta un apellido en vez de dos; y «se me ha duplicado el cliente de paula fernandez oro».
- 73529e0: la espera entre pasos de un pack no se pinta (fuera `.cd-espera`, `cdHuecosDeEspera`, `cdRestarOcupado` y
  compañía); queda como agenda vacía y el clic abre «Nueva cita» por la columna. Test nuevo rojo con f19aa0c; 41 verdes;
  navegador aislado: 0 esperas pintadas, bloques de paso intactos, 0 errores de consola.
- Duplicados (solo lectura): cada cita apuntada desde el panel sin email ni teléfono creaba otro contacto
  (`_crm_upsert_contact` solo casaba por email o teléfono). En Alicia, 10 nombres repetidos y 24 contactos de sobra
  («Paula Fernandez Oro» 5, «maria garcia» 6, «yolanda» 6…). 311b58e: sin datos de contacto se reutiliza el contacto del
  mismo nombre que tampoco los tenga (no se junta con alguien del mismo nombre que tenga email o teléfono). 2 tests
  rojos con 73529e0; 136 verdes.
- Un apellido: ya era el interruptor del panel «Exigir dos apellidos» (`booking.exigir_dos_apellidos`); sin código.
- Decisiones de Pablo (AskUserQuestion): juntar los duplicados existentes; poner un apellido al desplegar; desplegar al
  salir verde. Suite completa de 311b58e: 2833 passed, 1 skipped, 0 fallos.
- Producción: `exigir_dos_apellidos: false` en el config de Alicia (copia
  `/srv/vantelia-backups/config-pre-un-apellido-20260915-170802.json`, 27 negocios antes y después); `main` avanzado sin
  fusión a 311b58e (settings apartado y restaurado); `deploy.ps1 -SkipLocalChecks`: acceso público OK, humo 5/5,
  VERSION.json 311b58e sin cambios pendientes; `main` subido. Duplicados juntados (copia
  `/srv/vantelia-backups/pre-crm-duplicados-20260915-171208.db`): se queda el contacto más antiguo con enlaces, historial y
  cobros de los demás; 24 borrados, 0 grupos repetidos y 1 «Paula Fernandez Oro».
- Comprobado en la app viva: `exige_dos_apellidos` False, `precios_en_agenda` False, panel servido sin `cd-espera`,
  health ok (27 clientes).
- Pendiente: datos de Alicia (alisados, «Maquillaje y recogido», «Elumen largo», precios que sí se pueden dar); tres
  limitaciones apuntadas (sustitución «en vez del X quiero Y», cita para otra persona, insistencia en el diagnóstico una
  vez en el banco) a diseñar con Astra; revisión de Astra de 8be90fb y 311b58e cuando tenga créditos.

## 2026-09-16 10:49 Europe/Madrid — plan de cierre operativo de Alicia (Astra)

- Petición directa de Pablo: ponerse al día y planificar versión final. Base main61a5d8a,
  código311b58e, rama propia astra/plan-cierre-alicia-16sep; cambios ajenos intactos.
- Leídos Sincronía, registro, aceptación, contrato y puntos concretos de código.
  Confirmado en código que el rechazo de creación todavía se compara solo con inicio
  del turno. La reproducción anterior de 7a8e473 no se ha relanzado ni se presenta
  como prueba nueva de 311b58e. No se ha accedido a producción ni secretos.
- Plan en CIERRE_ALICIA_16SEP.md: rechazo persistente, servicio/titular, datos por
  tenant, candidato y medición comparables, prueba real autorizada de Meta y entrega.
  Descubrimiento delegado solo de documentación/APIs; síntesis de Astra.
- Solicitado relevo a Claude sobre actividad, número real y decisiones pendientes.
  No se repiten suites ni bancos validados. Validación de esta entrega: documentación
  y referencias; no se han ejecutado tests porque no cambia código.
- Siguiente: implementar bloque1 en rama propia tras comprobar reparto; no queda
  proceso de implementación/pruebas ejecutándose al cerrar esta planificación.

## 2026-09-16 11:03 Europe/Madrid — relevo a Astra e inventario de Alicia (Claude)

- Rama `main`, llevada por avance rápido a b626ad1 (plan de Astra, solo docs). Producción sigue en 311b58e.
- Relevo enviado por el buzón de Sincronía: no hay procesos en marcha ni copias de producción; el número de Alicia sigue
  sin conectar; faltan los pasos de «Maquillaje y recogido» y «Elumen largo», la decisión sobre los pasos de los
  alisados y la lista de precios que se pueden dar. La fusión de contactos de 311b58e fue decisión explícita de Pablo y
  solo toca contactos sin email ni teléfono.
- Bloque 3: inventario de datos y reglas, sacado de producción en solo lectura, en `docs/ALICIA_PENDIENTE.md` con
  fuente y fecha. Hallazgos: 2 packs sin nombre de paso, 8 alisados cuyos pasos no cuadran con el total, Stripe sin
  `charges_enabled`, sin vacaciones ni bloqueos a futuro y 0 cuentas de WhatsApp.
- Pruebas: ninguna, porque no cambia código. No se ha implementado nada de los bloques 1 y 2.
- Siguiente: revisar el primer commit de Astra del bloque 1 cuando llegue y preparar la medición del bloque 4 (candidato
  frente a referencia con `--db-origen`), sin lanzarla hasta que haya SHA candidato.

## 2026-09-16 11:21 Europe/Madrid — bloque 1, rechazo persistente (Astra)

- Rama `astra/rechazo-persistente`, base `141f6e9`, regresiones en `9bade14`.
- Rojo causal confirmado: `test_prueba_alicia_15sep -k rechazo_sigue`, 2 failed;
  mensajes «gracias» y «no entiendo» intentan resumen sin nueva validación.
- Segundo rojo antes del arreglo: nuevo fichero `test_rechazo_creacion_persistente`,
  2 failed / 1 passed: emisor común permite resumen, nueva gestión conserva la marca.
- Arreglo en preparación: consultar rechazo persistido en lugar del reloj del turno;
  invalidar botones anteriores de creación; conservar operaciones ya aceptadas y
  cancelaciones/reprogramaciones; revalidar la marca tras consultar la agenda.
- Dirigidos en ejecución. Reinicio se comprueba con intérpretes separados y SQLite
  temporal; modelo y transporte simulados, sin mensajes reales ni datos de producción.
- Siguiente: cerrar dirigidos y candidato estable, suite completa una vez, revisión
  de Claude. No se declara cerrado el bloque ni aceptación con modelo real.

## 2026-09-16 11:25 Europe/Madrid — dirigidos del bloque 1 (Astra)

- Rama `astra/rechazo-persistente`, descendiente de `9bade14` y `141f6e9`.
- Primera tanda: 104 passed / 1 failed; el fallo era del test nuevo (trataba como
  diccionario la identidad devuelta como texto). Corregido el test, no el contrato.
- Segunda tanda del nuevo fichero: 7 passed, incluidos el recorrido real de resumen,
  botón previo inválido, aclaración y aceptación duplicada con una sola cita,
  conflicto de estado, rechazo durante consulta de agenda y conservación de otras
  gestiones. La primera tanda incluyó los reinicios entre intérpretes, recuperación,
  transporte, cancelación y compatibilidad del shim. Aviso de Trio preexistente.
- `git diff --check` correcto. Modelo, proveedor y Meta simulados; no es medición real.
- Siguiente: una suite completa sobre este candidato estable, después revisión del
  SHA exacto por Claude. No push, despliegue ni cambios en producción.

## 2026-09-16 11:40–13:45 Europe/Madrid — bloques 1 y 2 del cierre, medición y pack de maquillaje (Claude)

- Orden de Pablo: Astra se quedó sin créditos a mitad del bloque 1 («sigue tú, úsala de apoyo»). Su sesión figura sin
  créditos hasta las 15:46; el encargo de revisión espera en su buzón.
- Bloque 1, revisión de 952ae99 (Astra) en `claude/rechazo-persistente`: con el rechazo persistente, si la conversación
  seguía por las listas (negocio guiado, o agente sin contestar y servicio preguntado a mano), al dar el nombre no le
  llegaba nada a la clienta. 0353c06: elegir el servicio en ese paso aclara el rechazo. Test en rojo sin el arreglo en
  las dos variantes y verde con él. Suite completa de 0353c06: 2845 passed, 1 skipped, 0 fallos.
- Bloque 2 en `claude/servicio-y-titular` (sobre 0353c06): 4dbb056 quitar un servicio en el mismo mensaje («en vez del
  corte quiero un elumen», «no quiero el corte, quiero un elumen») y «y un» deja de sumar a lo anterior; 2cedcf7 decisión
  de Pablo «ficha intacta» (una cita a otro nombre no renombra la ficha del teléfono; solo si el nombre nuevo completa
  el anterior); a303e27 un nombre que la clienta conocida no ha escrito no es titular; dcf91ce caso crítico del banco
  `en-vez-de-mechas-grey-blending`; d444647 elegir y quitar a la vez se queda con lo elegido. Cada uno con test en rojo
  antes y verde después. Suite completa de d444647: 2859 passed, 1 skipped, 0 fallos.
- Medición con modelo real, copia de producción snap10 (16-sep 12:39) y cfg10, mismo banco (evals de dcf91ce):
  referencia 311b58e (código de producción, evals copiados) Alicia 45 medidos: 44 al primer intento, 0 tras reintento,
  1 fallo crítico (`en-vez-de-mechas-grey-blending`: «para poder hacerte el grey blending y las mechas en una misma
  cita, necesitamos cuadrarlo bien»); metareview 16 medidos: 14 primer intento, 1 tras reintento, 1 fallo importante
  (`horario-escrito-manda`, conocido y ajeno a Alicia). Candidata d444647 Alicia 45 medidos: 44 al primer intento, 1 tras
  reintento (`cambiar-la-hora-de-verdad`: en el primer intento el modelo pidió el día en vez de ofrecer huecos y se
  retrasó un turno; mismo patrón medido el 15-sep en la referencia), 0 fallos, 0 no medidos. Metareview de la
  candidata y críticos ×6 en curso.
- Pack maquillaje y recogido de Alicia en producción (respuesta de Alicia vía Pablo; orden «Aplicar ya»): Maquillaje 45 +
  Recogido 45, sin esperas; 90 min (antes 170). Copia `/srv/vantelia-backups/pre-pack-maquillaje-20260916-110651.db`;
  comprobado en la app viva que la agenda aparta 90. Pack elumen largo sin tocar: su respuesta (15 + 20 + 30) coincide
  con el corto; Pablo le repregunta.
- Limitación que queda: «es para mi hija» sin nombre sale con el nombre de la ficha en el resumen, sin preguntarlo.
- Siguiente: terminar metareview y críticos ×6 de d444647, leer cualquier no OK, y pasar el SHA exacto a revisión de
  Astra. Sin push ni despliegue.

## 2026-09-16 13:45–17:40 Europe/Madrid — candidata e81f010 del cierre de Alicia (Claude)

- Rama `claude/servicio-y-titular`, candidata congelada **e81f010** (141f6e9..e81f010: bloque 1 de Astra 9bade14/952ae99
  y lo de Claude). Sin push ni despliegue. Producción sigue en 311b58e.
- Tres rondas de revisión de Codex con la cuota renovada de Astra. Regla de Pablo («congelar y medir»): se arregla lo que
  hace reservar menos tiempo o deja a la clienta sin respuesta, lo que solo pregunta de más queda apuntado.
  - Sobre 78d931e: «en vez de Lorena quiero a Conchi y un secado» perdía el corte (ec79548); «Primera consulta
    dermatologica» daba la familia «consulta» (7d41ace); ficha con el nombre de la primera cita aunque sea para otra
    persona → decisión de Pablo «dejarlo así» (limitación).
  - Sobre ec79548: servicio ordinal sin categoría sin familia y «al final solo quiero el elumen y el jueves» frenado
    (167fc8d).
  - Sobre 167fc8d: «no quiero perder el corte, quiero también un elumen» quitaba el corte; formulario nativo de WhatsApp
    tras un rechazo sin respuesta; «Cliente WhatsApp» no se corregía (e81f010). Ordinales que faltan (tercer, cuarta):
    apuntado.
  - Sobre e81f010: el formulario nativo no valida los dos apellidos (ya pasa en producción, sin rechazo previo; Alicia
    tiene un apellido) y «en vez del corte quiero también un secado» no quita (pregunta de más): apuntados.
  - Cada arreglo con test en rojo antes y verde después.
- Fallo real encontrado al medir el segundo negocio (también en 311b58e): «Primera sesion con deposito» daba la familia
  «primera» y «el primer hueco que tengas» frenaba la cita y ofrecía la sesión con fianza (78d931e).
- Evidencia sobre e81f010 (copia de producción snap10 16-sep 12:39, cfg10, sin modificar la copia): suite completa 2871
  passed, 1 skipped, 0 fallos. Banco de Alicia 45 medidos: 44 al primer intento, 0 tras reintento, 1 fallo crítico
  `no-quiero-diagnostico-quiero-cita` (los dos intentos: el modelo insiste en el diagnóstico). Investigado: familias
  (40, misma huella) y freno idénticos a 78d931e; repeticiones del caso e81f010 4/6 + 10/10 al primer intento (2 tras
  reintento), 78d931e 6/6 + 10/10. Sin camino de código que lo explique; mismo caso inestable ya medido el 15-sep en
  7a8e473. Críticos ×6 (crear, cancelar, reprogramar, rechazo, cambio de servicio, «dice que sí»): 36/36 al primer
  intento. Metareview: 16/16 al primer intento, 0 fallos.
- Referencia 311b58e, mismo banco y copia: Alicia 44 al primer intento + 1 fallo crítico (`en-vez-de-mechas-grey-blending`);
  metareview 14 + 1 tras reintento + 1 fallo importante (`horario-escrito-manda`).
- Candidatas intermedias medidas: 78d931e suite 2863/0 fallos, Alicia 45/45, críticos 36/36, metareview 14+1+1 fallo
  horario; mediciones de ec79548 y 167fc8d paradas al cambiar la candidata (apartadas, no cuentan).
- Limitaciones que quedan: reglas de frases contra NORMAS_AGENTE_IA 37-39 (diseño limpio pendiente con Astra: el modelo
  declara lo que quita y el resumen muestra «No incluye»); «es para mi hija» sin nombre; las apuntadas arriba.
- Datos: todas las copias de BD de producción y configs de medición borradas del scratchpad y del servidor.
- Siguiente: revisión de Astra de e81f010 (encargo entregado en su sesión); con su OK, decisión de Pablo sobre desplegar.

## 2026-09-16 17:40–21:30 Europe/Madrid — revisión de Astra y candidata 30c5e15 (Claude)

- Revisión de Astra a e81f010: CAMBIOS (nota en el buzón de su árbol `E:/Vantelia-astra-revision-e81`, 17:45).
  Crítico: «No quiero el corte demasiado corto, quiero un elumen» y «No quiero el corte con Lorena, quiero el elumen con
  Conchi» quitaban el corte. Además, el fallo crítico del diagnóstico impide aceptar.
- 3820552: «no quiero X» deja de quitar el servicio; solo lo hacen «en vez de/en lugar de» (tests de Astra en rojo antes,
  verdes después).
- 30c5e15: causa del fallo del diagnóstico en el código. Leído en agent_turns: el borrador llevaba la fianza en euros y,
  con los precios ocultos, `precio_que_no_se_da` mandaba reescribir «ofreciéndole esa cita» de valoración aunque la
  clienta la acabara de rechazar. Ahora, si ya renunció (`renuncio_al_diagnostico_en_mensajes`), se quita la cifra sin
  volver a ofrecerla. Test con modelo simulado en rojo antes y verde después, con su control.
- Medición de **30c5e15** con copia nueva de producción snap11 (16-sep, 19:5x) y cfg11, todas las tiradas con sucio=0:
  suite completa 2874 passed, 1 skipped, 0 fallos. Banco de Alicia 45 medidos: 45 al primer intento, 0 tras reintento,
  0 fallos, 0 no medidos, 1 no aplica. Metareview 16/16 al primer intento. Críticos ×6: 36/36 al primer intento.
  `no-quiero-diagnostico-quiero-cita` ×10: 10/10 al primer intento.
- Referencia 311b58e con la misma copia: Alicia 44 al primer intento + 1 fallo crítico (`en-vez-de-mechas-grey-blending`);
  metareview 16/16 (el fallo `horario-escrito-manda` de snap10 no se repite).
- Documentos: `docs/ENTREGA_ALICIA.md` (pasos hasta el uso real) y `docs/QA_WHATSAPP_ALICIA.md` reescrito como prueba
  corta de la candidata. Astra entregó en paralelo `docs/ACEPTACION_OPERATIVA_ALICIA.md` (43d0ea6, rama propia), pendiente
  de integrar.
- Datos: snap11, cfg11, copias de metareview y todas las BD de medición borradas; nada en /tmp del servidor.
- Siguiente: veredicto de Astra sobre el código de 30c5e15 (pedido); con OK, orden de Pablo para desplegar. Sin push ni
  despliegue.

## 2026-09-16 20:10 Europe/Madrid — protocolo operativo independiente (Astra)

- Rama `astra/aceptacion-operativa-alicia`, base `30c5e15`. Claude mide esa
  candidata según su relevo; no se duplican suite ni banco.
- Entrega `ACEPTACION_OPERATIVA_ALICIA.md`: recorridos Meta/agenda/portal,
  recordatorios y evidencia de aceptación frente a entrega; acta sin resultados
  inventados. Excepciones aplazadas por Pablo según registro y buzón de Claude.
- Referencias contrastadas con inventario de main y pruebas existentes. Revisión
  documental y `git diff --check`; no pytest porque solo cambia documentación.
- Siguiente: Claude incorpora el protocolo y sus resultados del SHA definitivo;
  prueba operativa cuando estén conectados y autorizados entorno y destinatarios.
- Sin código, push, despliegue, acceso a producción ni mensajes a clientas.

## 2026-09-16 21:30–21:40 Europe/Madrid — OK de Astra, integración y despliegue de c110bd9 (Claude)

- Astra: «VEREDICTO: OK al codigo del SHA exacto 30c5e15», con las excepciones aplazadas por Pablo; 56 dirigidos verdes
  sobre ese SHA, sin hallazgos nuevos. No acredita la prueba con Meta ni los recordatorios reales.
- Integrado en `main`: `claude/servicio-y-titular` (30c5e15) y `astra/aceptacion-operativa-alicia` (43d0ea6, docs). Dos
  conflictos solo en este registro, resueltos conservando las entradas de los dos en orden. Código de `main` idéntico al
  de 30c5e15 (`git diff 30c5e15 main` sobre backend, tests, evals, scripts, UIs, api y deploy: 0 ficheros).
- Decisión de Pablo (AskUserQuestion): «Desplegar ya». `main` subido (c110bd9) y `deploy/deploy.ps1 -SkipLocalChecks`
  (suite completa ya verde sobre el mismo código): copia `/srv/vantelia-backups/pre-deploy-20260916-193453.db`, health ok
  y humo 5/5.
- Comprobado en la app viva: VERSION.json c110bd9 sin cambios pendientes; funciones nuevas presentes (rechazo persistente,
  aviso de precio, ficha, ordinales); Alicia con un apellido, sin precios en la agenda y con precios ocultos; Pack
  maquillaje y recogido 90 min; metareview sin familia «primera»; «en vez del corte quiero un elumen» no frena; health ok
  (28 clientes).
- Siguiente, según `docs/ENTREGA_ALICIA.md`: Alicia conecta su número y añade un método de pago en Meta, prueba corta
  (`docs/QA_WHATSAPP_ALICIA.md`) y 48 h de observación. Pendiente de Alicia: lista de precios, Pack elumen largo y pasos
  de los alisados.

## 2026-09-16 22:45 – 2026-09-17 02:40 Europe/Madrid — plan de bajo coste A/B/C, candidato 2a7e7a8 (Claude)

- Pablo aprueba COMPARATIVA_IA_Y_PLAN_DE_BAJO_COSTE y PLAN_TECNICO_POSTDESPLIEGUE («vamos a ello»). Reparto con Astra:
  Claude implementa A/B/C, Astra diseña D (3819d60) y revisa. Integrados en main los docs de Astra (2cf31d1).
- A `claude/validacion-final`: 437325d validación de hechos en la última vuelta y en el cierre (repro con modelo simulado);
  revisión de Astra CAMBIOS (precio + cita falsa combinados) → 8f0d6f6 corrige todas las infracciones y revalida (OK).
- B `claude/contratos-json`: cb46dae contratos de argumentos de tools e intents; CAMBIOS (confianza `true`, 1e309) →
  1d6e054; CAMBIOS (índice «²») → a41a2e9 (OK).
- C `claude/consumo-trazas` / `claude/consumo-trazas-rev`: c057e3b consumo del cierre e intents, coste desconocido y columnas
  nuevas con migración; CAMBIOS (del_turno no lo mostraba) → 877c795 (OK).
- Suites completas: A 2882, B 2893 y C 2879 passed (1 skipped, 0 fallos). Integrado `claude/bajo-coste-candidato`
  f2a9696 (conflicto de imports en intents resuelto conservando ambos): 2918 passed, OK de Astra al código integrado.
- Medición con modelo real sobre snap12 (producción 17-sep ~00:25) y cfg12, sucio=0. Referencia c110bd9: Alicia 45/45 al
  primer intento; metareview 15 + 1 tras reintento. Candidato f2a9696: críticos ×6 36/36, metareview 16/16, Alicia 44 + 1
  **fallo crítico** `digresion-fianza-a-media-reserva` (2/2). Causa leída en agent_turns: explicación de la fianza con
  «la cita queda confirmada automáticamente» (condicional) → `dijo_que_hay_cita_sin_haberla`; sin vueltas, la salida segura
  de A sustituía la respuesta entera y se perdían Bizum, transferencia y teléfono. Regresión de A.
- 9306fd9: la salida segura quita solo las frases que incumplen (texto neutro solo si no queda nada); test con la
  respuesta real de producción en rojo antes y verde después. OK de Astra al diff.
- Candidato **2a7e7a8** (f2a9696 + 9306fd9): suite 2920 passed, 1 skipped, 0 fallos. Con snap12: Alicia 45/45 al primer
  intento, 0 fallos/no medidos; críticos ×6 36/36; `digresion-fianza-a-media-reserva` ×10: 9 al primer intento + 1 tras
  reintento (intento fallido por la regla de orientación del alisado → diagnóstico, sin freno de A; el reintento conserva
  Bizum/transferencia tras quitar la frase condicional); metareview 15 al primer intento + 1 fallo importante
  `horario-escrito-manda` (2/2, 02:24 Madrid, turno de 6 vueltas sin freno de A/B/C; mismo caso intermitente que falló
  también con la referencia en snap10 y pasó en snap11/snap12).
- Trazas de la medición: columnas nuevas presentes, 0 llamadas sin uso, 0 coste desconocido; `sin_vueltas:*` 2 veces y
  `se_acabaron_las_vueltas` 3 veces en el banco de Alicia.
- Siguiente: decisión de Pablo sobre desplegar 2a7e7a8. Sin push ni despliegue.

## 2026-09-17 05:40–05:55 Europe/Madrid — despliegue de 293ff23 (plan de bajo coste A/B/C) (Claude)

- Decisión de Pablo (AskUserQuestion): «Desplegar ya». `claude/bajo-coste-candidato` integrado en `main` (293ff23), código
  idéntico a 2a7e7a8 (`git diff` sobre backend, tests, evals, scripts, UIs, api y deploy: 0 ficheros). `main` subido y
  `deploy/deploy.ps1 -SkipLocalChecks` (suite completa ya verde sobre el mismo código): copia
  `/srv/vantelia-backups/pre-deploy-20260917-034955.db`, health ok y humo 5/5.
- Comprobado en la app viva: VERSION.json 293ff23 sin cambios pendientes; `_corregir_sin_vueltas`, `_argumentos_validos`,
  `textnorm.objeto_json` y `trazas.anotar_llamada` presentes; columnas `llamadas_modelo`, `llamadas_sin_uso` y
  `coste_desconocido` creadas en agent_turns; `resumen_del_dia` con los campos nuevos; `objeto_json` rechaza `[]` y `1e309`.
  Health ok con 27 clientes: la diferencia con los 28 de snap12 es una demo automática caducada (3 → 2), todos los
  negocios reales siguen.
- Datos: snap12, cfg12, copias de metareview y todas las BD de medición borradas; nada en /tmp del servidor.
- Siguiente: vigilar en el informe (`/admin/informe`) la cobertura de consumo y los frenos `sin_vueltas:*` y
  `argumentos_con_otra_forma` con tráfico real; bloque D (selección de servicios por estado) según el diseño de Astra 3819d60.

## 2026-09-17 11:00–22:30 Europe/Madrid — bloque D aparcado, prueba real de Alicia y cierre operativo (Claude)

- **Bloque D (piloto de selección), ramas sin integrar.** D2b `9bbec49`: el servicio anotado por el modelo
  pasa las mismas comprobaciones de largo y técnica (OK de Astra; suite 2975 passed, 1 skipped).
  D2c `72ed470`: resumen de WhatsApp con «No incluye: …» marcado como mostrado solo si el resumen se entrega,
  `Aclaracion.enviada` + identidad única, e id del mensaje de WhatsApp como evento (suite 2988 passed).
  `102a0ee`: 5 casos del banco con la matriz del contrato. `ec1d234`: la evidencia vale desde el último cambio
  (el modelo registraba un turno tarde y `crear_cita` quedaba bloqueada para siempre). `e59394d`: herramienta
  plana, servicio como pista y pregunta enviada tal cual (suite 2997 passed).
- **Medición con modelo real sobre snap13** (copia de producción del 17-sep 13:54, borrada al acabar).
  Con el interruptor APAGADO: Alicia 50/50 al primer intento (incluidos los 5 casos nuevos), metareview 15/16.
  Con el interruptor ENCENDIDO: `ec1d234` 2 críticos + 2 importantes en 27 casos; `e59394d` 43 al primer intento
  + 1 tras reintento, 6 fallos (3 críticos). Causas leídas en trazas: el modelo rellena «lo que se quita» con el
  servicio nuevo, manda argumentos que no son JSON y anota servicios incoherentes. **Bloque D APARCADO** por
  orden de Pablo: el interruptor sigue apagado y el camino actual es el que se pondría en marcha.
- **Prueba real de Alicia en su portal (13:19–13:33).** Creó 6 citas a mano y desactivó «Citas» (13:33, su propia
  sesión; reactivado a las 15:49). Hallazgos con sus capturas y datos: (1) «La jornada de hoy ya ha terminado»
  cuando lo que pasaba es que el Pack grey blending medio (7 h 20) ya no cabía → `9c58ec1`; (2) 12-13 packs con
  pasos o esperas incoherentes (tabla de revisión publicada); (3) el Excel actualizado del 17-sep NO corrige los
  alisados y contradice 3 packs; **no usar `importar_catalogo_excel --aplicar`** (borra y recrea el catálogo).
- **Auditoría en solo lectura (bloques 1-4 del plan de Astra `ce72270`).** Recorrido E2E en copia con envíos
  interceptados: pasos y esperas ocupan bien, otra cita entra en la espera y no encima del trabajo, mover
  conserva pasos, cancelar avisa, fianza con Stripe incapaz no deja la cita pendiente de pago, recordatorio por
  email y motivo registrado cuando no hay canal. **Hallazgos:** F1 la Q&A de la fianza promete un enlace de
  tarjeta que hoy no existe (Pablo decide: activar Stripe antes de arrancar; Alicia **no tiene cuenta conectada**);
  F2 el email de confirmación no menciona la fianza; F3 `booking.webhook_url` apunta a un webhook de Make muerto
  (410) y cada cita lo intenta (Pablo: quitar en el próximo despliegue, con copia); F4 el contador de
  recordatorios cuenta los que no salen por ningún canal.
- **Rama `claude/cita-manual` (sin desplegar), 8 commits.** Fallos del vídeo de Alicia: el formulario arrastraba
  el servicio anterior, ofrecía 8 de 169 servicios y el foco saltaba al desplegable (`56336a6`); un servicio
  escrito a medias creaba una cita de 30 min en silencio. Cita rápida del mostrador (`19b5dfb`, `ad4ca7f`):
  texto libre + duración (30 min por defecto, decisión de Pablo), `duration_minutes` en el alta manual y
  `duracion` en `/disponibilidad`. Revisiones de Astra: mover una cita ya no la encoge a la duración del
  catálogo (`a1dc38f`, afectaba también a citas estiradas a mano), la sugerencia no pisa el texto ni se engancha
  sola (`7fba7e4`, `8086879`) y el teclado no se sale de lo pintado (`b417618`). Suite completa 2948 passed,
  1 skipped sobre `8086879` y sobre `b417618`.
- **Decisión de Alicia (21:07):** arranque congelado hasta primeros de noviembre. Datos que sí confirmó: elumen
  20 min de espera, flash repair 15 de trabajo + 15 de espera, alisados «45 min según cuál» (sin decir cuál).
  Parche preparado (sin aplicar) para los 3 packs de mechas afectados: corto 195→230, medio 360→350, largo
  440→430.
- **Siguiente:** OK de Astra a `b417618` y orden de Pablo para desplegar (con la retirada del webhook de Make);
  preparar la revisión de packs para noviembre; Stripe de Alicia sin conectar; bloque D sigue aparcado.

## 2026-09-17 23:45 – 2026-09-18 00:05 Europe/Madrid — despliegue de 70e1445 (portal del mostrador) (Claude)

- Orden de Pablo: desplegar sin esperar el OK de Astra, que no estaba, dejándole el aviso en el buzón.
- `main` 70e1445 = merge de `claude/cita-manual`: aviso real cuando el servicio no cabe (`9c58ec1`),
  los tres fallos del vídeo de Alicia (`56336a6`), cita rápida del mostrador con duración explícita
  y 30 min por defecto (`19b5dfb`, `ad4ca7f`, decisión de Pablo), mover una cita ya no la encoge a
  la duración del catálogo (`a1dc38f`), sugerencia explícita y texto conservado (`7fba7e4`,
  `8086879`), teclado acotado a lo pintado (`b417618`) y fianza en el email de confirmación
  (`0c0838c`). Revisión de Astra a todo salvo los dos últimos.
- Suite completa sobre el candidato: **2949 passed, 1 skipped, 0 fallos**. Despliegue con
  `deploy.ps1 -SkipLocalChecks`: copia de la BD, health ok, acceso público ok y humo 5/5.
- **`WEBHOOK_DEFAULT` vaciado en el `.env` del VPS** (copia `/srv/vantelia-backups/pre-webhook-20260917-214739.env`).
  No era config de Alicia: era la variable global que heredaban los 25 negocios, con destino de Make
  borrado (410) y 7 intentos fallidos en 7 días, todos de citas de Alicia.
- Verificado en la app viva: `VERSION.json` 70e1445 sin cambios pendientes, `WEBHOOK_DEFAULT` vacío,
  `_aviso_fianza` en `_booking_email_bodies`, `_update_booking_details` conserva la ocupación real y
  el portal servido trae `nbRapQue` y `nbPorQueNoSePuedeCrear`.
- **Pendiente:** revisión de Astra a `b417618` y `0c0838c` sobre lo desplegado; hallazgo F4 (el
  contador cuenta recordatorios que no salen por ningún canal); cargar los datos de Alicia ya
  confirmados (elumen 20, flash repair 15+15 → 3 packs de mechas: 195→230, 360→350, 440→430);
  arranque de Alicia congelado hasta noviembre, con Stripe y WhatsApp sin conectar.

## 2026-09-18 15:01 +02:00 — la cita se escribe en la propia agenda (solo Alicia)

- Qué: pinchar un hueco de la vista Día deja el cuadro de la cita ahí mismo y se
  escribe encima («CARMEN ELUMEN Y…»), como en el programa del que viene el salón
  piloto. Aparta 30 min; si el trabajo es más largo, se estira el cuadro. Enter
  guarda, Esc sale, «Más datos» abre el panel lateral de siempre.
- Opt-in por negocio: `booking.cita_en_la_agenda`. Sin el interruptor, pinchar un
  hueco sigue abriendo el panel lateral. Encendido HOY solo en
  `alicia_rincon_estilistas` (decisión de Pablo: «demomento así solo para alicia»).
- Además: una nota del mostrador sin email ni teléfono ya NO crea ficha en
  Clientes (antes cada cita apuntada así metía el texto entero como nombre).
- Rama `claude/cita-en-la-agenda`: 3bdc47b (cuadro + guarda del CRM) y 4548645
  (interruptor por negocio). Integrado en main como 3824185 y desplegado.
- Evidencia: suite completa en la rama 2954 passed, 1 skipped (23 min 26 s);
  6 mutaciones causales, las 6 en rojo (quitar el guardia del CRM, quitar el
  cuadro, quitar la duración, quitar el interruptor del portal, quitar la lectura
  del negocio en `/auth/app/overview`, encenderlo de serie en el modelo).
- Despliegue: healthcheck ok, acceso público ok, humo 5/5. Copia previa de la
  config en `/srv/vantelia-backups/config-pre-cita-en-agenda-20260918-125701.json`
  antes de encender el interruptor; comprobado en el contenedor que solo lo tiene
  Alicia (27 tenants cargados) y que sobrevive a la normalización de config.
- Siguiente: que Alicia lo pruebe en su agenda real y diga si le vale así; sigue
  pendiente el parche confirmado de los 3 packs de mechas (necesita orden de Pablo
  + copia de la BD), el hallazgo F4 (contador de recordatorios) y que ella conecte
  Stripe y WhatsApp. Astra debe aún revisión de b417618, 0c0838c, 3bdc47b y 4548645.

## 2026-09-18 17:22 +02:00 — el cuadro de la agenda entiende el apunte

- Qué: «Nueva cita» vuelve a ser una ficha sola (fuera el selector «Cita rápida /
  Con todos los datos», ab4c215) y el cuadro de la agenda entiende lo escrito
  (478ae58): «Carmen Calvo, pack mechas corto» -> nombre + servicio del catálogo
  con su duración. La coma es la única regla; sin coma se apunta como hasta ahora.
- Sin modelo: decide `catalog_pick` vía `backend/apuntes.py` y
  `POST /auth/app/interpretar-apunte` (sesión + `agenda.create`, no crea nada).
- Tres guardias medidas sobre el catálogo real (186 servicios): sin largo escrito
  no se elige largo; si otro servicio que encaja dura ≥1,5× se pregunta («Mechas
  medio» 75 min frente al pack de 360); técnica no nombrada se ofrece, no se aplica.
- Integrado en main como d99ed6b y desplegado. Decisión de Pablo: desplegar sin
  esperar la revisión de Astra (encargada, pendiente).
- Evidencia: suite 2962 passed, 1 skipped (33 min); 10 tests nuevos incluido uno
  que ata lo enseñado con lo apartado en la agenda; 7 mutaciones causales en rojo.
  Despliegue: health ok, acceso público ok, humo 5/5. Comprobado en el contenedor
  contra el catálogo real de Alicia (solo lectura) que responde igual que en local
  y que el interruptor sigue solo en su negocio.
- Observado: en producción «Pack keratina premium largo» dura 140 min y en la copia
  local 280. Es dato del catálogo, no del cuadro; va con la revisión de packs.
- Siguiente: que Alicia lo pruebe con la coma; F2 (modelo para lo que el catálogo
  no reconoce, p. ej. «tinte raiz») y F3 (enganchar el nombre con su ficha de
  clienta) quedan sin hacer; revisión de Astra de 478ae58.

## 2026-09-18 20:25 +02:00 — pruebas en la agenda real de Alicia: cuatro arreglos y agenda limpia

- Pablo probó el cuadro en la agenda real. Salieron tres fallos:
  - Enter guardaba lo entendido de un texto anterior: «paula miranda, quitar
    extensiones» quedó como «pau». Arreglado en 4eb47e0 (se vuelve a entender ESE
    texto antes de guardar; con opciones sin tocar, se enseñan antes).
  - «quitar» no encontraba «Kitar extensiones» (así está en su catálogo) y ofrecía
    «Brusing-extensiones». Ahora se compara por cómo suena.
  - La agenda ponía «Consulta» a lo apuntado sin servicio. Ahora se lee lo escrito.
- Cuarto, encontrado al mirar: cancelar, mover, marcar asistencia, cerrarse sola o
  el relleno del CRM tras cada reinicio metían la nota del mostrador en Clientes.
  Guardia único en `crm._crm_upsert_contact` (73f3302).
- Pedido por Pablo: tocar una opción del cuadro apunta ya la cita; reparto por
  niveles (Lorena/Conchi -> Lucía/José -> Alicia), editable en el editor del
  profesional, y el selector de «Nueva cita» en ese orden (c484131).
- Desplegado en tres veces: c9c856b, 4dbb216 y 7f24405. Suites: 2966, 2971 y 2978
  passed (1 skipped); humo 5/5 en las tres. Mutaciones causales: 6 + 1 + 5, todas en
  rojo.
- Datos de producción, por decisión de Pablo y con copia previa:
  - Borradas las 61 citas de `alicia_rincon_estilistas` (todos los canales) y lo
    que colgaba de ellas; borradas 17 fichas de Clientes sin email ni teléfono
    salidas de citas apuntadas a mano (quedan 29). Copia:
    `/srv/vantelia-backups/pre-borrado-alicia-20260918-173801.db`.
  - Niveles de reparto de su equipo: Lorena y Conchi 1, Lucía y José 2, Alicia 3.
    Copia: `/srv/vantelia-backups/pre-reparto-alicia-20260918-182359.db`.
- Comprobado en vivo: con hueco en todas, 80 repartos simulados caen solo en Lorena
  y Conchi.
- Observado: en su catálogo real «Kitar extensiones» dura 5 min y «Pack keratina
  premium largo» 140. Dato suyo; va con la revisión de packs.
- Siguiente: que Alicia pruebe; F2 y F3 del cuadro sin hacer; revisión de Astra
  de 478ae58, 4eb47e0, 73f3302 y c484131.

## 2026-09-18 21:45 +02:00 — Cap Rocat: listo para el correo del lunes

- Cap Rocat acepta («mi jefa dice que podemos seguir adelante»). Piden DPA y
  documentos, respuestas en inglés a huéspedes en inglés, suspender de noviembre a
  marzo y cómo pasar sus palabras «desencadenantes».
- Producto (38e9698, desplegado como d1ce3fe): respuestas por palabra clave en el
  idioma de quien pregunta. Su texto en ES y EN sale tal cual; alemán, francés,
  italiano y holandés se traducen con el modelo desde la inglesa, con caída a la
  inglesa y a la de siempre. Idioma decidido sin modelo. Suite 2993 passed
  (1 skipped), humo 5/5, 6 mutaciones en rojo. Comprobado en vivo con el modelo
  real: alemán y francés conservan teléfono y email.
- Documentos (21b8d40): cláusula de pausa de temporada (hasta cinco meses, aviso de
  15 días, sin cuota, el asistente no responde, se conserva todo y se reactiva sin
  nueva puesta en marcha) y la cláusula de Meta al día (autorización concedida;
  se mantiene la protección de 60 días y reembolso).
- Producción, por orden de Pablo y con copias previas:
  - `WHATSAPP_ES_TENANTS` + `caprocat` (copia del `.env` en
    `/srv/vantelia-backups/env-pre-caprocat-20260918-185700`); vivo tras el despliegue.
  - Sus 7 reglas: tildes en el español, versión en inglés y palabras clave en inglés
    (copia `/srv/vantelia-backups/pre-reglas-caprocat-20260918-194253.db`).
  - Código de demo FYEKS8 ampliado del 28-sep al 31-oct-2026.
- Adjuntos generados (fuera de git, `outreach/caprocat_adjuntos/`): hoja de pedido,
  contrato y DPA en PDF, y un Excel editable con sus 7 respuestas ES/EN.
- Siguiente: Pablo envía el correo el lunes 21-sep; al volver los documentos
  firmados, factura de puesta en marcha, cargar sus respuestas revisadas y conectar
  su número.

## 2026-09-19 — Cap Rocat: situaciones típicas de hotel y documentos rellenables

- En el portal de Cap Rocat salían «No dar precio sin ver al cliente», «Pedir una
  foto» y «Derivar a valoración», con mechas y alisados de ejemplo. Esas tres ya no
  se enseñan a un negocio con la agenda apagada, salvo que ya tenga una montada
  (016f31f). Criterio de los datos: casi ningún negocio tiene su sector guardado.
- Documentos como PDF rellenable (e51ff5b, `scripts/caprocat_documentos_pdf.py`):
  campos donde escriben, forma de pago como opción única y firmas digitales;
  el texto del contrato no se puede tocar. Comprobado con pdf.js que cada campo cae
  en su hueco y rellenando una copia con pypdf. Dos fallos cazados al comprobarlo:
  campos apilados cuando había varios en una línea, y valores de pago con un
  espacio colado («SEP A») que dejaban la casilla sin efecto.
- Desplegado como 19b64ff: suite 2994 passed (1 skipped), humo 5/5; comprobado en
  vivo que Cap Rocat ve 3 situaciones y Alicia las 6.

## 2026-09-19 16:35 +02:00 — las tres duraciones de packs que confirmó Alicia

- Aplicado en su catálogo, por orden de Pablo y con copia previa
  (`/srv/vantelia-backups/pre-packs-alicia-20260919-143114.db`): espera de 20 min
  después del elumen y Flash Repair 15+15, como dijo ella el 17-sep.
  Pack mechas o balayage corto 195 → 230, medio 360 → 350, largo 440 → 430.
- Antes de tocar nada se comprobó que la ficha y los pasos seguían como cuando se
  preparó el parche (18-sep) y que no había ninguna cita viva con esos packs.
- Verificado en el contenedor: ficha, resolutor de duración y suma de los pasos
  coinciden, y la espera sigue quedando libre para otra clienta (110, 155 y 185 min).
- Pendiente de Alicia: las otras diez duraciones, que dejó para noviembre.

## 2026-09-19 14:19 +02:00 — estabilización independiente de los clientes

- Rama `astra/estabilidad-19sep`, base `60993b7`, integrada hasta `a22eb36`.
  Plan `155aaf2`: recordatorios, interpretación de apuntes, revisión de CRM y
  reparto, aislamiento y límites de la pausa de temporada. Sin producción/push.
- F4 (`83e5c56`): omitidos sin canales dejaban `sent_24h`/`sent_2h` en uno.
  Repro causal: 2 rojos y 2 positivos verdes antes; tras arreglo, 48 dirigidos
  verdes (247.57s). Revisión independiente: OK acotado. `sent` mide aceptación
  conocida, incluida recuperada; no entrega al teléfono ni nuevos transportes.
- `b417618`: revisión OK acotada con una prueba del manejador de teclado y
  301 servicios (`eb74dc7`, 1 verde, 4.03s). F2 `0c0838c`: sin nuevo hallazgo
  concreto, tests de fianza incluidos en los 48; no equivale a cobro real.
- `73f3302` CRM y `c484131` reparto: revisor independiente, 66 dirigidos y
  5 casos adicionales verdes. Cobertura integrada en `ff45f3a`.
- Aislamiento ES/EN (`8671178`, fixture corregida `a22eb36`): 5 casos HTTP
  verdes (45.59s), dos tenants y sesiones separadas; edición durante la
  conversación, lectura propia y rechazo de cambios/borrado ajenos.
- Incidencias de pruebas: se identificó y detuvo solo el pytest propio PID
  30168 a las 14:05:12 por saturación de memoria, sin resultado. Después se
  corrigieron dos errores de fixture (email `.invalid` y cookie Secure sobre
  HTTP); no se modificó producto para que el aislamiento pasara. Pruebas en serie.
  El doble de envío del smoke devuelve su contrato real en `d9ed572` (1 verde).
- `PAUSA_TEMPORADA_OPERACION.md`: borrador, no operación ejecutada. No hay pausa
  conjunta verificada de cuota, silencio y reactivación. No se cambian condiciones.
- Siguiente: Claude termina apuntes en `claude/encargo-0b86b3` (código/tests
  modificados, sin SHA entregado aún); revisar, integrar, congelar candidato,
  una suite completa y revisión exacta. No hay nueva medición con modelo real;
  acta y límites en `ACEPTACION_ESTABILIZACION_19SEP.md`. D sigue aparcado.

## 2026-09-19 14:37 +02:00 — apuntes integrados y corregidos tras revisión

- Rama `astra/estabilidad-19sep`, código `3936c0f`. Se compararon las dos
  entregas del mismo encargo (`3c646b0` de la sesión y `93416aa` automático).
  `7534f81` integra solo la segunda: mismo diseño más igualdad de talla y
  pruebas del resolvedor real. No se borra ni se integra duplicada la primera.
  Norma de un ejecutor por encargo añadida a `NORMAS_AGENTE_IA.md`.
- Revisión de Astra: dos fallos confirmados en API con catálogo sintético y
  `preferir_packs=false`: «media melena» oculta el rival de 360 min y aplica 75;
  pedir balayage acaba en 60 min de mechas genéricas. Rojos en base (26.47s) y
  `93416aa` integrado (30.82s). Arreglo propio: mismos alias de talla al buscar
  rivales, cobertura completa de lo escrito y retirada del guardia de una palabra.
- Primera validación: 22 verdes (91.50s). Revisor independiente encontró un
  nombre exacto con paréntesis que pedía otro toque; paréntesis y guion, 2 rojos
  (26.39s). Ahora nombres, texto y técnica comparten separación. Dirigidos finales:
  **29 passed**, 100.17s (apuntes + shim); lectura independiente OK provisional.
- Sin modificaciones en prompts, selección D o datos de clientes. Siguiente:
  congelar candidato, una suite completa y revisión manual del SHA exacto por
  Claude, sin arrancar además otro ejecutor que repita la suite. Modelo real del
  nuevo candidato no medido; las tablas no convierten pendientes en ceros.

## 2026-09-19 15:10 +02:00 — tallas alternativas y control de recordatorios

- Rama `astra/estabilidad-19sep`, producto `1caa5af`, prueba de control `e057f07`.
  Claude devolvió CAMBIOS sobre `f2003ec`: una talla alternativa perdida ocultaba
  el pack largo. Cuatro reproducciones locales rojas (38.57s); ahora se conservan
  todas las tallas no solapadas con el vocabulario existente. Lectura independiente
  del diff corregido sin nuevos hallazgos.
- Control de recordatorios rojo (1 failed y 8 passed, 58.03s) al comprobar que el
  doble antiguo terminaba contado como fallo. Contrato corregido y aserciones de
  aceptación. Dirigidos conjuntos finales: **41 passed**, 131.32s.
- Suite local del candidato rechazado `f2003ec`: 14:39:41 a 14:56:37, detenida
  solo la ejecución propia PID 35480. Aproximadamente 45%; no resultado completo.
  Manifest/log en `E:/Vantelia-astra-estabilidad-evidencia/`, estado interrupted_for_review.
- Diseño de pausa `6a43942`: autoridad persistida por tenant, fronteras de todos
  los canales y admisión de envíos, operación de cobro separada. Diseño entregado,
  no implementación. Es trabajo interno aún pendiente; D continúa aparcado.
- Próximo paso: congelar este candidato y pedir revisión automática, único dueño
  de la suite completa; ninguna suite local sigue activa. Después resolver su
  resultado y abordar la autoridad de pausa. Sin nuevos bancos de modelo real,
  push, despliegue ni cambios en producción.

## 2026-09-19 17:04 +02:00 — candidato 19ad09e revisado OK

- Rama `astra/estabilidad-19sep`. Claude entrega revisión **OK** del rango
  `60993b7..19ad09e` y suite **3025 passed, 1 skipped, 26m32s**. Fuente original:
  buzón principal `20260919T150054115013-claude-7f82cc` (17:00:54 Madrid).
  Astra contrasta copia `E:/vp-rev-19ad09e`: detached en SHA exacto y limpia.
  Resultado comunicado por Claude, no repetido ni presentado como ejecución propia.
- Sonda determinista sobre copia del catálogo informada por Claude, resultados
  en el acta. Sin nuevo banco del modelo real ni entrega real de WhatsApp.
  «Pelo»/«cabello» producen alguna pregunta extra: matiz no bloqueante conservado.
- `9c3e3b8` en main registra packs corto 230, medio 350 y largo 430, aplicados
  por Claude por orden de Pablo a las 16:35. La sonda del veredicto cita medio 360;
  se pide identificar la copia, sin atribuirle cobertura de esos datos posteriores.
- El automático sí arrancó a las 15:12, PID 30080 observado; a las 17:02 ya no
  estaba activo y no se localizó su resultado. No acreditar una suite sin final.
  La nota `20260919T150424537819-astra-1e7335` enlaza la respuesta de Claude a la
  petición original y evita repetirla cuando vuelva la cuota; no crea un OK del bot.
- Acta, plan y estado actualizados solo en documentación tras el SHA revisado.
  Próximo bloque interno: autoridad persistida de pausa, según diseño `6a43942`.
  No hay pruebas ni implementación activas al registrar esto. No se declara
  acabado el plan completo ni se despliega sin orden de Pablo.

## 2026-09-19 18:40 +02:00 — desplegada la estabilización del 19-sep

- Integrado `astra/estabilidad-19sep` en main como `0cb61de` y desplegado, por
  orden de Pablo. Lleva: F4 (el contador solo suma si el aviso sale), la autoridad
  única del cuadro de la agenda con las tallas alternativas, el aislamiento ES/EN
  de las respuestas por palabra clave y las pruebas de CRM y reparto.
- Evidencia: revisión de Claude sobre el SHA exacto `19ad09e` con la suite completa
  (3025 passed, 1 skipped, 26 min 32 s) en copia propia `E:/vp-rev-19ad09e`;
  `5037515` solo añadía documentación, así que el código desplegado es el probado.
  Humo del despliegue 5/5.
- Comprobado en vivo con el catálogo real: «mechas medio» y «media melena» aplican
  el pack de 350 (ya con las duraciones nuevas), «extra largo» el suyo de 395,
  «mechas» a secas pregunta el largo, y el resto igual que antes.
- El choque del registro al integrar se resolvió conservando las entradas de los dos.

## 2026-09-19 19:56 +02:00 — autoridad de atención integrada, sin canales aún

- Coordinación `astra/cierre-estable-19sep`, `E:/Vantelia-astra-cierre`: plan
  `4b208bf` y merge `b5fd11b` de fase 1 `3fad6f2`, implementada en rama propia
  `astra/pausa-atencion-19sep`. Solo migración, autoridad CAS, auditoría atómica,
  pruebas y mapa de arquitectura. Ningún escritor HTTP ni canal conectado.
- Revisión independiente de agentes propios: OK tras corregir IDs válidos que
  empiezan por guion/guion bajo y una fecha corrupta que no debía autorizar lectura.
  Dirigidos finales 67 passed en 56.22s. Antes de esos arreglos: 3 failed/1 passed.
  Mutación del rechazo CAS: 2 failed; restauración con identidad de bytes: 2 passed.
  Logs y huellas en `E:/Vantelia-astra-pausa-evidencia/FASE1.md`.
- Siguiente entrega: fase 2a de tickets por versión y admisión persistida de cada
  fragmento; no mantener transacciones durante red, no revivir trabajos antiguos
  al reactivar ni tratar un resultado desconocido como permiso para reenviar.
- Instrumento de medición en rama aparte: el criterio de cita única detecta
  duplicadas y canceladas, pero revisión encuentra el caso cita antigua activa +
  cita nueva cancelada. Se corrige por identidad antes de integrarlo; los 8 tests
  iniciales no cubrían ese escenario. Un único turno de pytest entre agentes.
- Sin suite completa, banco real, push, despliegue ni acceso a producción. La pausa
  todavía no funciona de extremo a extremo y no se presenta como disponible.

## 2026-09-19 20:18 +02:00 — admisión de envíos e instrumento integrados

- `astra/cierre-estable-19sep`, `E:/Vantelia-astra-cierre`, HEAD `08e541e`:
  integración de fase 2a `6458b5` mediante `dfcc62b`, y del banco `e8a8b6`.
  Árbol limpio tras los merges; no conflicto de producto.
- Fase 2a: tickets por evento/tenant con versión y vigencia inmutables, admisión
  transaccional de fragmentos, resultados conservadores y diario técnico. Revisión
  propia independiente OK; hashes del candidato cotejados con el acta FASE2A.md.
  112 passed/85.38s. Hallazgo de igualdad temporal: 1 failed/35.95s antes de `<=`.
  Mutación de permiso: 1 failed/18.19s; restauración exacta, 1 passed/14.54s.
- Instrumento: una sola cita activa cuyo `bookings.id` es nuevo. Aprobación
  anterior falsa con cita antigua viva+nueva cancelada y rechazo falso por resta
  de filas: 2 failed/10 passed antes, 12 passed después. Quitar id del SELECT:
  1 failed/1.72s; restaurado, 13 passed/0.90s. Logs y contrato en
  MEDICION_CIERRE_COMPARABLE.md; ninguna medida de modelo se atribuye a estos tests.
- Claude, nota `20260919T173955011323-claude-c6119d`: no tiene snapshot saneado
  actual. Solo informa de catálogo local de 186 servicios con packs 230/350/430;
  Astra no ha leído ni copiado esa BD. El artefacto de comparación sigue pendiente.
- Auditoría ajusta el orden: antes del canal, admitir crear/cancelar/mover y
  cubrir `recover_creation_operation`, que puede borrar una operación caducada.
  No confundir reserva persistida con mensaje entregado. Voz necesita inventario
  de call_id del servidor y cierre comprobado, no solo caducidad del secreto.
- Siguiente: fase 2b en rama de pausa y helper `_to_thread` en rama separada,
  sin duplicar escritor. Todavía sin suite completa, canales conectados, push,
  despliegue ni producción. La versión completa no está aceptada.

## 2026-09-19 20:37 +02:00 — contexto de hilos integrado; núcleos en prueba

- Coordinación `astra/cierre-estable-19sep`: `6b66632`, revisión independiente OK,
  integrado como `cf77b87`. Helper `_to_thread` usa `copy_context` por invocación;
  conserva argumentos/resultado/excepción y aísla contexto del llamador y de otras
  tareas, incluido un hilo reutilizado. Solo helper y test dedicado.
- Causal sobre base `08e541e`: 4 failed/1.55s (20:21:14–19); después,
  4 passed/0.68s (20:21:34–38). Hash del helper cotejado con evidencia externa en
  `E:/Vantelia-astra-contexto-hilos-evidencia/CONTEXTO_HILOS.md`. Sin repetir pruebas.
- Fase 2b en `E:/Vantelia-astra-pausa`: núcleo conectado solo en esa rama,
  todavía sin commit ni validación final. Causales en ejecución por su único dueño.
  Revisión preliminar pide preservar supresión tras un retroceso de reloj,
  validar referencias de resultado y no ocultar un resultado conocido al pausar.
  La identidad de la mutación será estable también entre tickets distintos;
  los envíos mantienen su identidad por ticket/canal/fragmento.
- La migración a diario común debe conservar datos y retirar el escritor anterior;
  no exige convivencia de workers de fase 2a, que nunca se desplegó. No conectar
  canales ni mostrar una pausa completa por tener estas primitivas implementadas.
  Sin suite completa, bancos reales, push, despliegue ni acceso a producción.

## 2026-09-19 21:01 +02:00 — admisión del núcleo integrada; chat siguiente

- `f6c16e159ff956954b7f9e491a9f075f0607b904`, rama astra/pausa-atencion-19sep,
  integrado en coordinación como `25b84e4`. Revisión final independiente OK;
  diez archivos, diez logs y acta coinciden con manifiesto de hashes.
- Evidencia: `E:/Vantelia-astra-pausa-evidencia/FASE2B.md`. 12+3+1 fallos causales,
  108 passed/92.60s de integración, 78 passed/83.90s finales afectados y mutación
  3 fallos → 3 aprobados con restauración exacta. No se suman como casos únicos.
- Diario de operaciones único: identidad de reserva estable entre tickets,
  resultados conocidos visibles tras pausa/caducidad, supresión persistente,
  protección de claims y liberación. Un fallo del diario después de persistir la
  cita no interrumpe pago/política/CRM del ganador. `OPERATION_RELEASED` acredita
  rechazo después de liberar y auditar; un pendiente desconocido sigue incierto.
- Contexto interno todavía sin capturadores de canal: conserva el recorrido
  manual/sin contexto. No constituye una pausa completa ni un permiso de despliegue.
- Siguiente asignado: entrada/emisión/historial de `/chat` y UI del widget en
  ramas separadas; auditoría de pagos/avisos auxiliares. Un solo ejecutor pytest.
  Sin suite completa nueva, mediciones reales, push ni despliegue.

## 2026-09-19 21:08 +02:00 — contrato de emisión y efectos auxiliares del chat

- Sobre coordinación `6173111`, auditoría solo lectura confirma que el refresh
  Connect de `_ai_send_payment_link` ya tiene efectos antes del Checkout. Se
  aprueba un tipo explícito `pago/crear_enlace` en el diario existente; no otra
  autoridad. Mensajes de pago y avisos de reserva se admiten por separado.
- Los callbacks de outreach aquí solo registran entrada/engagement; no son un
  envío. Los avisos dentro de una reserva ganadora no pueden aprovechar su
  excepción de tránsito para saltarse la pausa de mensajes. Supresión terminal
  sin fallback, preservando política/reembolso/CRM del ganador.
- Implementador verificó la API local de CondensePlusContextChatEngine: usa un
  engine HTTP efímero por turno con historial persistido, sin rollback de memoria
  compartida ni cambios en el motor WhatsApp. El widget implementa el contrato
  HTTP 409/503 acordado y un aviso fuera del historial.
- Criterios y límite de emisión frente a lectura en el plan de cierre. Es diseño
  y trabajo en curso; aún no hay resultado dirigido de chat/widget ni suite global.

## 2026-09-19 21:10 +02:00 — widget revisado e integrado; pago en pieza separada

- `fdf60e3a58b5b947e200bda24edd059f9e554e4c`, astra/widget-atencion-19sep,
  integrado como `e6ad008`. Astra leyó fuentes y tests, contrastó selectores con
  formulario/acciones reales y cotejó cinco hashes con acta y logs.
- Causal Node: 6 fallos/1 aprobado (268ms) → 7 aprobados (305ms); build esbuild
  143ms y bundle 72.4KiB. Sin repetirlos durante revisión. Evidencia externa en
  `E:/Vantelia-astra-widget-atencion-evidencia/WIDGET_ATENCION.md`.
- Estado accesible de interfaz para 409/503, sin respuesta del asistente ni
  reintento; acciones anteriores bloqueadas hasta nueva respuesta válida y
  contactos humanos disponibles. Límite: DOM mínimo y formulario previo en vuelo
  fuera de este corte. Backend/emisión aún por integrar, no pausa completa.
- Implementación dividida por dueño: chat ASGI/RAG/transportes en rama de pausa;
  pago/crear_enlace en rama propia desde f6c16e1, mismo diario y funciones de pago
  delimitadas; integración de tests Node en CI, sin cambiar versiones. Pytest
  lo ejecuta un único agente por turno; no hay suite completa ni banco real activo.

## 2026-09-19 21:20 +02:00 — CI conectado; chat dirigido verde y pago causal rojo

- CI `80c52e0`, integrado como `477b286`: `npm run test:widget` ejecuta las siete
  regresiones Node antes del build en el job existente. Sin cambiar versiones ni
  dependencias. Revisión del diff de cuatro líneas OK; única ejecución de la
  nueva entrada: 7 passed/339ms, log temporal `vantelia_ci_widget_atencion_20260919.log`.
- Implementador de chat comunica 17 aprobados/36.31s (ASGI/memoria/shim), después
  de cuatro causales rojos. No es todavía revisión ni integración: continúan sus
  transportes/avisos. Ha cedido pytest al agente de pago y no conserva un proceso.
- Pago comunica primer rojo 8 fallos/1 aprobado, 29.33s. Se corrige además un
  doble de concurrencia que repetía el mismo ID de Checkout: se comprueba su
  causal por separado antes de tocar producto, sin atribuir la colisión al núcleo.
- WhatsApp siguiente: auditoría requiere resolución pura de tenant demo (el
  resolver actual también hace binding) y recuperación informativa sin liberar
  claims. No copiar a Meta los 120s de HTTP: falta justificar su vigencia frente
  a webhooks retrasados. Payload de Flow suprimido requiere contrato preciso;
  no devolver un éxito inventado. Investigación oficial acotada, sin activar canal.
- Sin suite global nueva, banco real, push, despliegue ni datos de producción.

## 2026-09-19 21:42 +02:00 — pago revisado e integrado; chat corrige fronteras

- `997d2effa7b8ce08b55c5248dddcd4924aeeeb08`, astra/pago-atencion-19sep,
  integrado sin conflictos como `0122e53`. Revisión final independiente OK:
  cinco hashes, código y logs cotejados. Acta externa `PAGO.md` en su carpeta de
  evidencia; metadatos del candidato en ACEPTACION_ATENCION_19SEP.md.
- 129 dirigidos/179.96s antes del hallazgo de Connect; 2 causales rojos/27.35s
  y corrección de rechazo conocido. Tanda aislada encontró prioridad manual
  alterada (19 aprobados/2 fallos); producto corregido, fixtures intactos. Final
  21 passed/44.83s a las 21:35:34. No sumar tandas ni repetir suite completa.
- Tipo pago/crear_enlace comparte diario; efectos Connect/CRM/Checkout bajo
  admisión y pay_ persistido antes de avisar. Huella lógica de intención/datos,
  sin afirmar petición Stripe congelada ni reconciliación de desconocidos.
- Root pide causales HTTP de petición retenida en lock durante pausa/reactiva,
  sesión de otro tenant (deuda previa descubierta), intención conservada y asiento
  ausente. Chat posee pytest; pago lo cedió al terminar. Avisos: omitido con razón
  atencion_suprimida será terminal para el automatismo, sin fallback ni falsa entrega.
- WA0 asignado en paralelo solo a wa_demo.py/tests: separar resolución consultiva
  del binding que hoy tiene efectos, mantener wrapper legacy. No conecta WhatsApp.
  Los límites oficiales de WA/Flow están en la nota externa WA_CONTRATO_LIMITES_19SEP.md.
- Ninguna suite completa nueva ni banco del modelo activo; sin push/despliegue.

## 2026-09-19 21:59 +02:00 — consulta demo integrada; cierre de chat en revisión

- WA0 `478d082b6293e62e989fb8e697a25c03909efbae`, integrado en `23f16b3`,
  rama coordinadora astra/cierre-estable-19sep. Astra revisó código, acta y
  dos hashes exactos. Mutación: 2 fallos por escritura de rutas/usos; restaurado,
  36 passed/24.75s a las 21:52:37. Acta externa WA0.md en
  `E:/Vantelia-astra-wa-demo-resolucion-evidencia/`.
- Consulta inmutable sin efectos y wrapper legacy conservado. No es permiso ni
  congela el código: WA1 debe comprobar resolución/tenant/atención y escribir
  atómicamente; repetir el wrapper después de admitir X podría vincular Y.
  Diseño de WA1 en curso, sin implementación ni pytest paralelo.
- Chat: siete causales HTTP/avisos corregidos y 42 dirigidos verdes. Astra da
  OK acotado a HTTP; revisión de transportes espera restauración exacta después
  de mutación. Gmail admite el mensaje tras preparar OAuth; resultado conocido
  de reserva se conserva separado del aviso suprimido. Regresión posterior:
  63 verdes y un doble RAG antiguo, ajustado sin cambiar la respuesta exigida.
- Único ejecutor de pytest: chat. No se ha iniciado suite completa ni modelo.
  Siguiente: cerrar acta y revisión, integrar chat con pago y probar su convivencia.

## 2026-09-19 22:19 +02:00 — candidato chat/pago integrado para suite única

- `fc8f58e` integrado en `3f234f2`; revisión final de transportes y revisión de
  HTTP OK: 15 hashes/14 logs/acta cotejados. Mutación SMTP/SMS/Meta 3 fallos →
  3 aprobados, restauración exacta. Gmail admite mensaje después del getter;
  resultado conocido de reserva se conserva aparte del aviso suprimido. Meta
  parcial conserva IDs y no se marca omitido. Acta externa FASE2C_CHAT.md.
- `56c3f3b` integrado limpio en `83bed95344cba345d38504460325636b20491d02`:
  puente pay_ conocido para SMS/email, sin volver a Checkout ni fingir entrega.
  Revisión OK de 5 archivos/4 logs/acta. Dos causales rojos/21.62s; combinación
  final 63 passed/70.71s. Acta externa FASE2C_PAGO_AVISOS.md.
- La combinación descubrió contaminación por reload parcial de tests: pareja
  mínima 1 fallo/1 aprobado. Se sustituyeron tres recargas por un intérprete
  nuevo con env mínimo, dotenv desactivado y DB temporal. Prueba lectura y corte
  persistidos; padre conserva efecto único. No cambio de producto para ese fallo.
- Revisor confirmó que dos avisos distintos pueden colisionar en el agente que
  cancela y crea otra cita dentro de un turno. Ese bucle no está en /chat capturado
  actual: no bloquea esta entrega, pero exige identidad estable por aviso antes
  de conectar WA/voz. No añadir un contador de reintentos para ocultarlo.
- WA1 está fuera del candidato, en su propia rama/copia. A las 22:18:59 terminó
  sus tres causales rojos; cuatro archivos restaurados, dirigido en curso desde
  22:19:30. Después cede pytest para la única suite completa del candidato chat.
  Todavía ninguna suite completa nueva iniciada ni banco/modelo activo.
- Plan/acta actualizados. Diseño de recordatorios conserva origen por generación
  y selector único, sin usar la hora de reactivación como evento nuevo. Se mantiene
  la decisión existente de respaldo tras 30 minutos de incertidumbre del proveedor.

## 2026-09-19 22:29 +02:00 — suite completa de dff4b72 realmente en marcha

- La combinación WA1 había dado 157 passed/1 failed/11 errors. Causa acotada:
  fixture PAGO sembraba con api_module antiguo tras cambiar el runtime de tests,
  pero leía el backend actual. Repro autocontenido 1 failed/26.27s; fixture propia
  corregida, sin producto ni pruebas históricas alterados. Combinación hub/pago/
  puente/persistencia/shim: 103 passed/90.25s. Acta externa
  FASE2C_FIXTURE_PAGO_RUNTIME.md, hash único y diff revisados por Astra.
- Commit `dff4b72f59ce18b34ed2b8a204803d4df062f9e5` integrado por avance rápido;
  una sola prueba corregida y caso causal añadido. Producto idéntico a `83bed95`.
- Suite autorizada y lanzada de verdad a las 22:29:32.719 Europe/Madrid, copia
  E:/Vantelia-astra-pausa limpia. `python -m pytest -q --tb=short`; pytest PID 31832,
  registrador PID 39528, sesión 38194. Log completo suite_candidato_dff4b72.log y
  metadata suite_candidato_dff4b72.json en E:/Vantelia-astra-pausa-evidencia.
  Resultado pendiente; no sondeos periódicos ni edición en esa copia.
- WA1 queda aparte, mejorando su recarga simulada por proceso nuevo, sin pruebas
  activas. R0 prepara fecha de nacimiento de generación y selector temporal
  compartido, sin conectar el worker ni atención. No habrá otro pytest mientras
  la suite posea el turno. Tampoco hay medición con modelo ni operaciones reales.

## 2026-09-19 22:47 +02:00 — recepción y avisos delimitados antes de conectar WhatsApp

- Coordinación `astra/cierre-estable-19sep`, base documental `317513a`, código del
  candidato de suite `dff4b72` intacto. WA1 revisado estáticamente, sin hallazgo
  concreto; su nueva prueba de hijo Python y combinación con fixture corregido
  siguen pendientes. R0 también conserva sus archivos sin ejecutar pruebas.
- Diseño WA2a contrastado con el marcador real: reutilizar tabla de entradas,
  distinguir legacy, fijar tenant/fecha/identidad originales y crear ticket/captura
  en una transacción común. Proyección al inbox también conserva fecha Meta.
  Sin capturador conectado ni afirmación de procesamiento/entrega tras una caída.
- Encargada en rama independiente la identidad de avisos: cancelar A y confirmar
  B en un turno no deben colisionar como un único email. Es una puerta previa a
  WA/voz multiherramientas, no un fallo alcanzable en el HTTP actual. Sin pruebas
  concurrentes con la suite. Contrato guardado en PAUSA_TEMPORADA_DISENO.
- Detectado y documentado el límite del banco existente: entra directamente al
  manejador de mensajes; no valida webhook completo ni el middleware de /chat.
  Se prepara diseño de adaptadores reutilizando el instrumento e interceptores.
  No se ha iniciado campaña con modelo ni se han atribuido resultados nuevos.

## 2026-09-19 22:59 +02:00 — navegador revela formulario tardío tras la pausa

- Revisión independiente de Astra en Chrome, bundle de `dff4b72`: respuesta 200
  inicia carga de formulario, 409 posterior pausa la atención, respuesta tardía
  de centros hace aparecer el formulario con 13 controles habilitados. Repro rojo
  a las 22:55:46–51, dos requests /chat, sin errores JS ni ruta desconocida.
  Estado accesible fuera del historial correcto; el problema es la carga pendiente.
- Script, JSON rojo, captura y acta en E:/Vantelia-astra-widget-atencion-evidencia/
  BROWSER_ASYNC.md. HTTP local interceptado, sin modelo/proveedor/producción.
  Los siete tests Node previos no cubrían la carga real. Arreglo encargado en
  astra/widget-async-19sep desde dff4b72; no modifica la copia de la suite.
- WA1 aplicado sin conflicto a astra/wa1-integracion-19sep, base `6fd8dff` con
  fixture corregido. Misma semántica en cuatro archivos revisados; tres hashes
  cambian solo por CRLF normalizado. Aún sin commit ni pytest; fuente preservada.
- Lectura acotada confirma otra puerta previa a capturar WA/voz: petición explícita
  de cancelar A y B del mismo titular puede ejecutar ambas tools; una sola clave
  de turno por acción confundiría la segunda con la primera. Causal de recorrido
  pendiente; no se declara fallo del HTTP actual. Crear/mover en WA remate_manual
  generan propuestas, por lo que no se atribuyen a ese recorrido dos efectos reales.
- La suite única de dff4b72 conserva su copia. No hay otra suite ni banco activos.
