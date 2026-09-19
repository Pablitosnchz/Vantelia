# Estado actual de Vantelia

## En curso — 2026-09-19 19:33 Europe/Madrid

- **Testigo:** Astra, coordinación de la estabilización autorizada por Pablo.
- **Tarea:** ejecutar el cierre autorizado por Pablo; fase 1 de autoridad persistida de pausa en implementación, auditoría de fronteras y contrato de medición en paralelo.
- **Rama:** coordinación astra/cierre-estable-19sep (E:/Vantelia-astra-cierre); implementación astra/pausa-atencion-19sep (E:/Vantelia-astra-pausa), ambas desde e43baca.
- **Siguiente:** verificar la autoridad con pruebas dirigidas y revisión independiente; después conectar admisión por versión y canales. Plan CIERRE_ESTABILIDAD_AUTONOMO_19SEP.md.
- **Espera a:** entregas de los agentes propios; Claude informado para no duplicar. No hay suite completa ni banco del modelo activo en este arranque.

- El bloque anterior sigue desplegado como `0cb61de`, revisado `19ad09e` y con
  3025 passed/1 skipped, humo 5/5. No repetirlo como si validase el bloque nuevo.
- Primera entrega nueva: backend/atencion.py + migración + tests de aislamiento,
  CAS, reinicio y errores; todavía sin interruptor público ni canales conectados.
- [Plan de cierre](CIERRE_ESTABILIDAD_AUTONOMO_19SEP.md): una autoridad de atención
  por tenant; preservar configuración/cuenta/acceso humano; cobro separado.
  D aparcado y sin nuevas operaciones de producción/push/despliegue.

- Claude registra el despliegue en `ef8f2b4`. Astra comprobó localmente que
  `5037515` está integrado y que `19ad09e..0cb61de` solo cambia documentación;
  conserva el registro de ambos agentes y `TIEMPOS_PACKS_ALICIA.md`.
- Comprobación en vivo comunicada por Claude: mechas medio/media melena → pack
  350 con las duraciones nuevas; extra largo → 395; mechas sin talla pregunta.
  Queda resuelta la discrepancia de la sonda anterior con el catálogo actualizado.
  Ese humo y esa sonda no equivalen al banco comparable completo de dos negocios.

- Veredicto recibido a las 17:00:54, contrastado con `E:/vp-rev-19ad09e`:
  detached en `19ad09ee1bc2f261e99902be20197a9f80448415`, árbol limpio.
  Suite y sonda de catálogo comunicadas por Claude; no repetidas por Astra.
  [Acta y límites](ACEPTACION_ESTABILIZACION_19SEP.md).
- El automático sí inició pytest a las 15:12 (PID 30080 observado entonces).
  A las 17:02 no quedaban pytest ni revisor activos; no se localizó su resultado.
  No se cuenta como aprobado ni se afirma que nunca arrancó. La evidencia final
  es la ejecución independiente de Claude, no una suma de ambas.
- La nota de Astra `20260919T150424537819-astra-1e7335` enlaza el veredicto y
  cierra solo la petición pendiente para evitar otra suite cuando vuelva la cuota.
  No crea una aprobación automática ni autoriza despliegue.
- Matiz no bloqueante: «mechas pelo largo» y «mechas cabello medio» ofrecen una
  elección en vez de aplicarla solas. Queda registrado, sin cambiar el candidato.
- Main avanzó solo en documentación a `9c3e3b8`: Claude registra tres duraciones
  de packs actualizadas por orden de Pablo (corto 230, medio 350, largo 430).
  La sonda inicial citaba medio 360; la comprobación posterior al despliegue
  acredita medio 350. Las otras diez duraciones siguen pendientes.

- Astra ejecuta [ESTABILIZACION_19SEP.md](ESTABILIZACION_19SEP.md) en
  `astra/estabilidad-19sep`, base `60993b7`, producto integrado hasta `1caa5af`.
- F4 corregido (`83e5c56`), 48 dirigidos verdes y revisión independiente OK
  acotado. F2 y teclado revisados; CRM/reparto OK con 66 dirigidos y 5 casos
  adicionales. Evidencia en [ACEPTACION_ESTABILIZACION_19SEP.md](ACEPTACION_ESTABILIZACION_19SEP.md).
- Se compararon dos entregas duplicadas de apuntes, `3c646b0` y `93416aa`, y se
  integró solo `93416aa` (mismo diseño, igualdad de talla y pruebas reales).
  Astra cerró repros adicionales de alias/técnica y separadores. La revisión
  exacta de `f2003ec` encontró después que «corto o medio» perdía una talla:
  cuatro casos rojos antes; `1caa5af` conserva todas las alternativas sin cambiar
  el criterio anterior de `talla_de`. Lectura independiente del diff corregido OK.
  Dirigidos finales: **41 passed**, 131.32s, incluidos shim y recordatorios.
  `e057f07` corrige otro doble de recordatorios que ocultaba un fallo del contador.
- Aislamiento ES/EN: 5 pruebas HTTP verdes (45.59s). La interrupción por memoria
  y los dos errores posteriores de fixture (email/HTTPS) están documentados.
  No se atribuyen a fallos del producto.
- La suite local de `f2003ec` fue interrumpida a las 14:56 al invalidarse el
  candidato por revisión; había alcanzado aproximadamente el 45%, sin resultado
  completo. Evidencia fuera del repo: `E:/Vantelia-astra-estabilidad-evidencia/`.
- No lanzar otra implementación ni suite completa de apuntes. Reparto del
  ejecutor en NORMAS_AGENTE_IA; acta todavía sin nuevos bancos del modelo real.
- Pausa de temporada: [diseño técnico](PAUSA_TEMPORADA_DISENO.md) integrado en
  `6a43942`; autoridad persistida y fronteras de canales aún sin implementar.
  Es trabajo interno pendiente, además de las dependencias externas.
  D aparcado; despliegue 0cb61de ejecutado por Claude, sin operaciones de Astra
  sobre producción.

**La memoria compartida entre los agentes que trabajan en este repo.** La lee
quien empieza una tarea y la actualiza quien la cierra. Lo que no esté aquí, el
otro agente no lo sabe: cada uno tiene su propia memoria y no se ven entre sí.

El relevo vigente está en «En curso» al principio. Los apartados fechados de
sesiones anteriores se conservan como histórico; no acreditan actividad actual.

Los dos agentes no comparten memoria. Lo que uno sabe del otro sale de este
fichero, de `git log` y del buzón de `scripts/sincronia.py` (peticiones de
revisión y avisos, que llegan solos a la sesión del otro): Pablo no hace de
mensajero.

## Cómo se trabaja ahora

- **Astra coordina e implementa la consolidación** (encargo vigente de Pablo).
- **Claude auxilia con revisiones, mediciones y piezas encargadas** en ramas propias. Despliegue solo por orden de Pablo.
- **Pablo decide.** Reglas completas en `AGENTS.md`.
- **¿Estáis sincronizados?** → https://app.vantelia.es/sincronia (semáforo, solo
  admin). Pablo no tiene que decir nada: los hooks de los dos agentes los ponen al
  día solos al empezar y con cada mensaje suyo, y el agente le cuenta lo nuevo.
- **Astra termina → Claude revisa solo.** Astra pide revisión, la tarea programada
  «Vantelia revisor» pasa los tests en una copia aparte y lanza la revisión de
  Claude, y la respuesta llega a la sesión de Astra, que se lo cuenta a Pablo.
  Pablo solo dice «despliega», a cualquiera de los dos.
- **Si a uno se le acaban los tokens**, el otro se pone al día solo y sigue en la
  MISMA rama.
- **No solo revisar: trabajan juntos.** Astra le pregunta a Claude
  (`--pedir-ayuda`) o le encarga trabajo en paralelo (`--encargar astra claude`,
  lo hace en su rama `claude/encargo-…`), y Claude a ella (`--encargar claude
  astra`). Todo llega solo a la sesión del otro.

## Seguimiento histórico — 16-sep-2026

### Comparación documental — 16-sep-2026 22:08 Europe/Madrid

- Astra: auditoría de prácticas publicadas por Rasa, Anthropic, Intercom y Langfuse
  frente al código local; [COMPARATIVA_IA_Y_PLAN_DE_BAJO_COSTE.md](COMPARATIVA_IA_Y_PLAN_DE_BAJO_COSTE.md).
- Se aprovechan trazas, estado CAS, banco y paso a persona existentes. Prioridad
  propuesta: reproducir salida no validada al agotar vueltas, contratos JSON y
  consumo completo; después piloto de selección estructurada de servicios.
- Solo investigación y planificación: riesgos de lectura estática pendientes de
  reproducción, sin tests nuevos, cambio de código o modelo real. Sin procesos de
  implementación ni despliegue iniciados. Repartir bloques con Claude antes de editar.

### Relevo vigente — 16-sep-2026 21:55 Europe/Madrid

- Despliegue confirmado por registro y buzón de Claude: `c110bd9`, código
  `30c5e15`, a las 21:35; health correcto y humo 5/5. OK de Astra emitido.
- La suite y los bancos de ese candidato terminaron; los relevos anteriores que
  los describen pendientes son históricos. Evidencia en REGISTRO_CONSOLIDACION.
- Pablo solicita plan técnico independiente de Alicia. Entrega de Astra:
  [PLAN_TECNICO_POSTDESPLIEGUE.md](PLAN_TECNICO_POSTDESPLIEGUE.md).
- Siguiente propuesto: contrato único de cambios de selección de servicios,
  reemplazando progresivamente decisiones por frases, antes de ampliar canales.
- Planificación terminada: no se ha iniciado implementación, prueba ni seguimiento
  automático en este bloque. Coordinar propietario con Claude antes de editar.

### Relevo de aceptación operativa — 16-sep-2026 20:10 Europe/Madrid

- Claude implementa y mide `30c5e15` en `claude/servicio-y-titular`, según su
  relevo de las 19:59. No se duplican sus suites ni bancos.
- Astra revisó `3820552` y `30c5e15`: OK acotado, 56 dirigidos verdes; no equivale
  a aceptación del candidato completo ni medición con modelo real.
- Entrega independiente en `astra/aceptacion-operativa-alicia`:
  [ACEPTACION_OPERATIVA_ALICIA.md](ACEPTACION_OPERATIVA_ALICIA.md), protocolo del
  bloque 5 y acta vacía. Ninguna prueba operativa se afirma ejecutada.
- Siguiente: resultados de Claude y completar acta. Meta requiere conexión y
  destinatarios/entorno autorizados. Excepciones aplazadas por Pablo según relevo.
- Sin cambios de código, pruebas nuevas en esta entrega, push ni despliegue.

### Relevo vigente — 16-sep-2026 11:20 Europe/Madrid

- **Testigo:** Astra, implementación del bloque 1 de CIERRE_ALICIA_16SEP.
- **Rama:** `astra/rechazo-persistente`, worktree E:/Vantelia-astra-cierre-alicia-16sep,
  base main `141f6e9`; regresiones causales en `9bade14` (2 rojos esperados).
- **Actividad real:** arreglo y dirigidos terminados; siguiente, suite completa del candidato.
  Reutiliza el estado existente; invalida ofertas anteriores sin borrar operaciones
  aceptadas ni propuestas de cancelación/reprogramación. Sin push ni despliegue.
- **Siguiente:** una suite completa del candidato estable y revisión de Claude del SHA exacto.
- **Espera a:** ninguna dependencia para este bloque. Claude confirma que no tiene procesos
  activos y revisará el candidato. WhatsApp de Alicia sin conectar según su relevo;
  datos/decisiones y Stripe pendientes en ALICIA_PENDIENTE.md. No bloquean este arreglo.

## En curso anterior (histórico, sustituido por el relevo del 16-sep)

Quien tiene el testigo lo actualiza cada vez que cambia (no solo al cerrar). La
página de sincronía lo enseña tal cual.

- **Testigo:** Claude, agente principal desde el 13-sep (decisión de Pablo). Astra tuvo cuota nueva el 13-sep por la mañana: cherry-pick de lo de Claude, 8ca6088 y 7740b45, todo integrado; sus copias de trabajo no se tocan.
- **Cierre (14-sep, 23:32):** plan de consolidación CERRADO con excepciones. Candidato final **b6226bd** (`claude/duracion-extensiones`): OK de Astra acumulado, suite 2782 passed / 1 skipped, modelo real sobre copia de producción snap8 con Alicia 43/43 y crítico 6/6 al primer intento, humo 5/5, portal 6/6 y metareview 15/16 (fallo real conocido). Incluye, además de lo de abajo, que la valoración exigida por el negocio no se suma al tratamiento al preguntar cuánto dura (prueba de Pablo por WhatsApp). Datos de Alicia ya en producción con copia previa: diagnóstico de extensiones 15 min y Q&A «¿Cuánto duran las extensiones?». **Desplegado en producción el 14-sep a las 23:36 (VERSION.json 629fabf, humo 5/5) y `main` subido**, por orden de Pablo. Siguiente: el seguimiento fuera del plan (tabla de la fase 4 en PLAN_CONSOLIDACION_IA) y vigilar el uso real de Alicia cuando conecte su WhatsApp.
- **Tarea (14-sep, 20:45):** cierre del plan de consolidación con excepciones (decisión de Pablo). Producción en **125725f** desde las 19:43 (vacaciones como día cerrado). Candidato de cierre **e230991** (`claude/cierre-fixes`, copia E:/vp-cierre): lo desplegado + cierre por vacaciones en chat, RAG y selector de WhatsApp (Astra; 1cdb3f9, 5c927dd) + arreglos de la revisión de Astra a cb87be4 y e11ac35 (fechas y cobro de la prueba gratis; conflicto al recuperar una cancelación). Fases 0–3 cerradas; fase 4 cerrada con excepciones (tabla en PLAN_CONSOLIDACION_IA); fase 5 en curso: medición sobre copia de producción snap7 con crítico 6/6 al primer intento, humo 5/5 (también sobre e230991), portal y reinicios 6/6 y metareview 15/16 (`horario-escrito-manda` da el horario de hoy: fallo real); faltan el banco de Alicia, la suite de e230991 y la revisión de Astra. Alicia está probando el chatbot por WhatsApp (código de demo YDCP9E): vigilancia en solo lectura y sin despliegues mientras prueba. Antes: e5c784f desplegado el 14-sep a las 17:43 (días gratis del plan y cancelaciones recuperables; `prueba` de 10 días puesta a Alicia) por orden de Pablo; antes, c8aaad8 a las 16:38 (VERSION.json 14e5a5d) y bec310f a las 07:22, con la exigencia de dos apellidos activa para Alicia. Mientras Alicia no conecte su WhatsApp, plan de arquitectura (todo desplegado en c8aaad8): Fase 3, avisos del editor de reglas (`68a8c68`), y avisos que ya no se quedan bloqueados (`1458540`, decisión de Pablo), corregidos en `549a1e3`, `0b12b3c` y `3e05b96` tras tres revisiones adversariales de Codex (respaldo fuera de la banda del recordatorio; ejecutor perdido o al límite de la gracia; el reenvío manual avisa antes de repetir un WhatsApp dudoso, también tras la confirmación de pago o si en medio se reenvió solo por email, o si una entrega anterior tapaba un dudoso posterior; decisión de Pablo). Fase 4: reprogramar por el flujo guiado de WhatsApp exige ya aceptar el cambio (`e44886b`, decisión de Pablo: solo el flujo de listas; el agente de Alicia no cambia). Reconciliación de operaciones perdidas integrada en `d14285d` (`5c88bc7` y `5a965e7` de Astra, `04fc97f` de Claude; suite de la rama 2687 passed, 1 skipped). Codex vuelve a funcionar con otra cuenta desde las 11:40.
- **Rama:** `astra/aceptacion-e44886b` en E:/Vantelia (relevo de Astra sobre `claude/candidato`; único árbol con credenciales para medir), código en **c8aaad8**. Medido el 14-sep con modelo real sobre copia de producción: banco de Alicia 43/43 y crítico 6/6 al primer intento, humo 5/5, portal y reinicios 6/6, metareview 15/16 (el fallo depende del día). Igual que lo anterior; desplegado el 14-sep a las 16:38 (VERSION.json 14e5a5d), con humo 5/5 y el crítico OK dentro del contenedor. Antecedente: `claude/candidato` código en 112b26c. Contiene `astra/condiciones-confirmadas` (7740b45, con el checkout Stripe 68c1fac) y `main` (bd7a6da, lo desplegado). Evidencia en 112b26c: suite **2541 passed, 1 skipped**; banco completo con modelo real **43/43, 42 al primer intento, 0 fallos**; `cambiar-la-hora-de-verdad` 6/6. Crítico `dice-que-si-y-acaba-en-cita` 6/6 al primer intento en e197dee y 6bed2f1 (antes 0/6). Humo 5/5 en 5e9f8d7. Detalle en REGISTRO_CONSOLIDACION.
- **Decisión de Alicia confirmada (13-sep):** a quien no sabe qué alisado quiere se le ofrece la cita «Diagnóstico y presupuesto». Se declara como regla de orientación, no se deduce de su Q&A. Creada en producción el 14-sep (`rule_eD_NnlJc1lQ`) y verificada con el caso crítico sobre una copia.
- **Siguiente (Claude, 14-sep 20:45):** resultados del banco de Alicia y de la suite de e230991, veredicto de Astra sobre e230991; borrar las copias con datos de clientas (snap7, cfg7, meta_rag, banco_n); marcar la fase 5 y el plan como cerrados con excepciones en PLAN_CONSOLIDACION_IA y ACEPTACION_CANDIDATO_IA; pedir a Pablo el despliegue de e230991 cuando Alicia termine de probar. Antes: fase 3 cerrada (reglas opuestas en dos negocios, 21/21 con modelo real); días gratis del plan y cancelaciones recuperables desplegados en `e5c784f` (SEPA activo en Stripe, prueba de 10 días puesta a Alicia, 129 €/mes con IVA incluido); Pablo le manda a Alicia el texto para conectar WhatsApp, la tarjeta en Meta, la suscripción y Stripe; revisión de Astra de `04fc97f` (encargo en su buzón); resto de la fase 4: reprogramar desde el agente, formularios, voz y widget con confirmación persistida, y reconciliar la cancelación con resultado desconocido. Vigilar las conversaciones reales de Alicia en cuanto lo use (frenos en `agent_turns`, citas creadas, dos apellidos). Nada se despliega sin orden de Pablo; pendientes menores (vacaciones dice «agenda completa»; `horario-escrito-manda` depende del día). Externo: WhatsApp de Alicia sin conectar (bloquea recordatorios).

Relevo anterior de Astra (histórico, sustituido por lo de arriba):

- **Testigo:** Astra.
- **Tarea:** integrar correcciones verificadas y cerrar el caso crítico de propuesta aceptada sin sustituir la decisión del negocio ni convertir dirigidos en aceptación global.
- **Rama:** astra/condiciones-confirmadas, E:/Vantelia-astra-condiciones, hija de 2cb8a029. E:/Vantelia-astra-formularios conserva intacto el candidato medido; no editar ni repetir pruebas allí.
- **Siguiente:** `8ca6088` conserva en el estado los huecos que WhatsApp sí envía y, con una propuesta aceptada y hora validada, lleva el nombre por `booking_name` hacia el resumen en vez de devolverlo al modelo. Dirigidos terminados sin fallos en caché; falta la suite exacta del SHA integrado. La medición real de Claude sobre `1fe7a3e` falló dos intentos del crítico porque no llegaba al resumen; una nueva medición real está en curso y no se ha duplicado. Registro: docs/REGISTRO_CONSOLIDACION.md.
- **Espera a:** resultado de la medición real iniciada por Claude y, después de congelar SHA, suite exacta y revisión. Banco comparable Alicia/otro, recordatorios, reconciliación operativa y resto de gestión no están aceptados. Sin despliegue.

QA visual exacta de de3d6d0 terminada: **exit 0**, 02:36:26–02:37:51 Europe/Madrid,
SHA y árbol limpios antes/después. Instrumento externo verifica 37 marcas de
15 min, tres interiores entre horas, alineación con la columna y horas visibles;
recorrido completo y duración persistida de 45 min. Capturas y resultado en
C:/Users/pabli/.codex/vantelia-coordination/portal-ledger.*. Google Fonts se
sustituyó por CSS vacío para impedir red externa: tipografía de sistema.

La captura reveló etiqueta de catálogo «20 min» sobre bloque/BD de 45 min.
23139ca corrige la etiqueta reutilizando cdDur y preserva precio/ausencia de
datos; regresión Node roja antes y verde después. Una nueva QA exacta sobre
2cb8a029 pasó el 13-sep 03:05:16–03:06:56 Europe/Madrid (exit 0, árbol/SHA
limpios antes/después): etiqueta «45 min» coincide con BD45 y conserva precio
18 €. También pasa geometría de 37 ticks/10 horas (8 visibles) y recorrido
completo. Artefactos portal-formularios.* externos; Fonts bloqueado con CSS
vacío y tipografía de sistema. Este resultado acredita el arreglo en 2cb8a029,
no en la captura anterior de de3d6d0. No se repite ninguna de esas QA verdes.

Arnés 2533fe9 revisado: `botones-explicitos-v1` exige una acción estructurada y un ID
realmente emitido por el builder productivo para esa clienta/tenant y propuesta
vigente. El texto libre nunca pulsa. 23 dirigidos verdes a las 02:49:33
(37,45 s); rojo causal del ID legacy y dos rojos de diccionario/cuarto botón
descartado antes del arreglo. Aceptación de transporte simulada, sin modelo ni
Meta reales; los informes de otra versión no se comparan. El caso crítico del
banco real todavía no acredita el efecto final en agenda; queda pendiente medir
antes/después con la misma versión del instrumento.

Ese límite de v1 se corrige en c9f19e6 (`botones-emitidos-v2`): captura transporte
normalizado sin API de propuesta/prefijos; ID explícito antiguo emitido llega al
producto, que debe rechazarlo. 28 controles verdes y dos positivos de agenda
verdes tras estabilizar la firma de producto (dos fallos transitorios no causales).
Consumidor banco: 16 verdes a las 03:16:27 tras dos rojos; incompatibilidad queda
NO MEDIDO con actividad parcial e intentos válidos previos, sin reintento extra.
Control aislado de builder/payload exactos 2235d25: un verde, sin API nueva ni
HTTP. Demuestra solo esa frontera, no producto completo ni mejora con modelo.

Cinco fixtures heredadas guardadas en 891a730 y revisadas OK: 38 passed a las 02:55:28, frente a siete
rojos y un control previamente verde. Usan huecos reales del tenant y mantienen
los validadores; el caso sin fianza exige además que exista resumen. No se
repitieron dirigidos durante la revisión; la suite de formularios se lanzó
después sobre 2cb8a029 y terminó con el fallo del instrumento indicado arriba.

Términos cambiantes reproducidos y cierre revisado en 6c3ad4f: 112 dirigidos verdes en
126,70 s. Preparado versionado compartido entre resumen/núcleo/guardado/checkout;
precio efectivo por centro y fianza recortada según regla existente, sin nuevo
recargo. Decisión online/offline ofrecida permanece fija aunque cambie Stripe;
capacidad viva se consulta para ejecutar pago. Recuperación precede revalidación,
importe/modo corruptos v1 y binding de cita modificado se rechazan antes de otro
checkout. El cambio queda separado del candidato medido anterior.
Límite pendiente: Stripe puede aceptar un checkout y perderse la respuesta o
la persistencia local; aún no hay idempotencia/reconciliación de ese resultado.
No repetirlo automáticamente ni convertir estos verdes en aceptación global.

Recuperación de checkout en 68c1fac: `booking_payments` guarda una clave de
idempotencia antes de la llamada a Stripe. Si Stripe acepta y se pierde el
guardado local, el siguiente intento reutiliza la misma clave y recupera la
misma sesión; la persistencia posterior compara esa clave. Una fila histórica
sin clave ni URL queda en 409 para reconciliación manual, sin crear un cobro
nuevo. 23 dirigidos de condiciones y dos regresiones de checkout/Bizum verdes;
no se hizo llamada Stripe real. Pendiente: reconciliación operativa de esas
filas antiguas o de respuestas que sigan siendo desconocidas tras el plazo del
proveedor.

Última suite exacta 2cb8a029 terminó a las **03:23:06.385 +02:00**, exit 1:
**2442 passed, 1 skipped, 1 failed**. Único rojo:
test_banco_sin_meta::test_instalar_captura_cierra_la_salida_de_payload.
Coordinación comunicó resultado de formularios-suite.result.json/.log; c9f19e6
elimina la delegación que causaba el rojo y el test aislado pasa con red externa
bloqueada. Aún no hay suite exacta del hijo ni medición de mejora/modelo/Meta.

Suite anterior de3d6d00e22e6f089055a1370c23fe9831205c8d terminada a las
**02:52:00.149448 +02:00**, exit 1: **2401 passed, 1 skipped, 1 failed**, sin
xfail. El único fallo exige incluir notice_deliveries en docs/ARQUITECTURA.md
(test_mapa_del_codigo_no_miente.py:125). Coordinación verificó resultado/log;
no se pidió revisión formal ni se declara verde. Se corrige el mapa en esta
rama hija, sin tocar el SHA congelado ni repetir la suite completa. Los verdes
dirigidos del hijo no son una suite completa. Corrección documental validada:
5 tests del mapa verdes (3,03 s), log externo mapa-notice-deliveries-verde.log.
Suite anterior: 2235d25, fin
13-sep **02:15:01 Europe/Madrid**, exit 1:
**2347 passed, 1 skipped, 1 xfailed y 2 fallos de cancelación**. Coordinación
verificó el resultado a las 02:16 en
C:/Users/pabli/.codex/vantelia-coordination/gestion-suite.result.json y su .log.
No sigue ejecutándose ni se pidió revisión automática de ese candidato.
Los dos rojos se reprodujeron a las 02:25:27: exigían cancelar al código/botón del
recordatorio sin aceptar propuesta. ca8e626 captura y acepta el ID real, mantiene
la cita confirmada hasta entonces y conserva las comprobaciones finales.
34 dirigidos verdes a las 02:27:09 (32,06 s), sin cambio de código productivo.
El verde de 7ab7775 pertenece al antecesor, en integrado-wa-suite.result.json.
El seguimiento cada 30 minutos está actualizado para retomar el último relevo y
anotar avances con hora. No implica actividad continua entre ejecuciones.

ff59b06 de astra/recordatorios-fiables ya está integrado. Su worktree se reutiliza
ahora en astra/entregas-recordatorios, sin modificar ni borrar aquella rama. Se ha
reproducido concurrencia de recordatorios (xfail estricto en 2235d25). El xfail se
retira únicamente en el hijo en desarrollo, donde la reclamación pasa dirigida;
esto no cambia el resultado del candidato anterior ni acredita una suite nueva.
El nuevo bloque no debe repetir envíos de resultado incierto ni introducir otra
autoridad conversacional. La generación debe cambiar al reprogramar, también si
la cita vuelve a su horario inicial; una fila de cita existente no acredita envío.

Validación dirigida nueva (selecciones solapadas): cancelación, último cierre 57
verdes, con regresiones rojas de cambio de cita, resultado perdido, menú y salto
al agente tras atención humana. Banco, último cierre 14 verdes, con guard de ruta,
persistencia por intento y casos no medidos. Recordatorios: 31 verdes y un xfail
de duplicación pendiente. QA navegador completa exit 0 sobre árbol de trabajo;
no es evidencia del modelo/Meta ni atribución a un SHA estable. Detalles y límites
en docs/ACEPTACION_CANDIDATO_IA.md. Estas selecciones preceden a la suite roja y
no sustituyen su resultado.

Trabajo posterior revisado o en revisión (selecciones solapadas): transporte
c1db689, 29 pruebas propias y 56 relacionadas verdes, aceptación HTTP distinta de
entrega al teléfono. Ledger: 66 dirigidas y 2 de plantilla previas, cierre final
de 16 verdes en 54,28 s (02:23:57) y revisión local OK. Aceptación y evento del
tope se guardan en una transacción; caída posterior recupera sin reenviar ni
perder el contador. Guardado en b5fa459; pendiente validar el candidato integrado.
Copia/informe 09aebfc: 6 rojas iniciales, 5 nuevas de sidecars/normalización y
27 dirigidas verdes finales, revisión independiente OK. Protege DB/WAL/SHM antes
de escribir y conserva el origen mediante apertura de solo lectura.

Límites del ledger: no reconcilia operativamente un resultado incierto, no reserva
el cupo global entre citas diferentes y no elimina la ventana de cambio tras la
última relectura y durante la red. El fallback interno de email sigue fuera de
esta pieza. Aceptación del proveedor no equivale a entrega al teléfono.

## Notas históricas (el bloque En curso prevalece)

QA visual independiente de 7ab7775 (13-sep 01:22): parcial, exit 1 por un supuesto
de fecha del instrumento. Tras corregir solo el arranque NLTK en el lanzador,
se recorren acceso, servicios/centros, Ventas, Informes y responsive; Nueva cita
espera huecos del domingo cerrado antes de avanzar al lunes. Arrastre y
persistencia de duración: NO MEDIDOS. No es un verde ni una regresión de producto
acreditada. Evidencia en ACEPTACION_CANDIDATO_IA.md y REGISTRO_CONSOLIDACION.md.





Sincronía: retiradas seis peticiones propias de revisión de antecesores verificados
(0b6043f, 550aafe, 6e040e1, 12d2614, 44dddf8, 530ae40) para evitar trabajo
duplicado. Son peticiones sustituidas, no aprobaciones. La revisión
de cf2066d llegó OK el 13-sep; el diagnóstico de demos sigue encargado y sin resultado.
No hay suite completa nueva en ejecución ni revisión solicitada del descendiente
de 4ed33c7: primero deben cerrarse esos fallos. El seguimiento autónomo sigue activo.
El trabajo local de WhatsApp se conserva en su rama propia; no sustituye el diagnóstico
de demos encargado a Claude ni afirma entregas de modelo/Meta reales.

Entrega anterior de Astra: 9b1bfea, creación recuperable de WhatsApp, rama limpia al
cerrar; 66 dirigidos de integración y 23 de cierre verdes (solapados), cuatro rojos
prearreglo y mutación roja de identidad. No se ha pedido revisión formal sin suite
completa. Sin push/despliegue. Contraste posterior de la respuesta de Claude: existe orientación declarada, pero
NO se ha retirado el atajo Q&A cuando falta esa política. El hallazgo sigue vigente
en el candidato actual; no dar esa sustitución por terminada. Sigue sin inventarse
la decisión particular de Alicia entre foto y diagnóstico.

Retirada Q&A implementada (13-sep): se elimina `_hay_que_cogerle_la_valoracion`
y su búsqueda que imponía diagnóstico. La nota solo ayuda a aclarar, sin consultar
Q&A/catálogo ni elegir un servicio. El recorrido declarado conserva propuesta y
aceptación. Tres regresiones de técnica/talla fallan antes del cambio; 102 pruebas
dirigidas verdes (oferta, aceptación, rechazo/obligatoriedad, catálogo, no elegir
por ella, shim). Las pruebas antiguas que imponían diagnóstico pasan a cubrir el
recorrido sin política; las de renuncia se mantienen en el núcleo compartido.
`pyflakes backend/agent.py` y diff limpios. No es una medición con modelo real ni
completa la migración del resto de autoridades. El comportamiento concreto para
Alicia sin elección de servicio sigue requiriendo política acordada.

cf2066d OK no implica integración: quedan mejoras menores de coste del sondeo de
cuenta, aviso visible de identidad desconocida y actualización documental al integrar.
Conservar su revisión y tratarlas sin bloquear el diagnóstico de demos.

Pendientes operativos que no deben perderse: estado de la plantilla de recordatorios
y prueba de envío real; confirmar situación actual con Claude. Última referencia
documental anterior de producción: `aab4d02`, no verificada de nuevo en esta revisión.
Los relatos de medición antiguos de más abajo son históricos; la referencia con
calendario reproducible se distingue arriba y no oculta los reintentos.

Por qué se integró antes de su revisión (Claude): sus 8 tests nuevos fallan 7
contra el código sin el arreglo y pasan con él; pytest completo en verde (2026);
el humo del caso contra una copia de producción no empeora (el fallo original es
poco frecuente: 1 de 4 despliegues el 11-sep). Su worktree tiene cambios sin
commit (`booking.py`, `voice.py` y el test) que no se han tocado.

Validación local de Astra: las tres regresiones iniciales fallaron sin el arreglo;
el control de reserva nueva pasó. Con el arreglo pasan los ocho casos específicos
(incluyen profesional, duración, exclusión propia, primer hueco automático y código
ajeno/inexistente), y una selección de 99 pruebas de voz, agente y compatibilidad.
Esto mide comportamiento determinista, no la tasa de fallos del modelo real.

## Lo último en producción

- **Agenda del panel**: la cita se lee entera (el día se pinta a 2,2 px/min, así
  que una de 15 min muestra nombre completo y servicio); selector de horas por
  franjas con scroll; estirar o acortar arrastrando cualquiera de los dos bordes,
  de 5 en 5, sin avisar a la clienta; el mostrador puede apuntar citas fuera de
  horario (la IA no).
- **Nombre y dos apellidos obligatorios** al crear cita o cliente desde el panel
  (400 desde el backend). Por WhatsApp se piden los apellidos UNA vez.
- **WhatsApp**: el freno de "cita sin pedir" decide por hechos, no por frases; la
  hora se comprueba ANTES de enseñar el resumen; los botones del aviso de cita
  duplicada ya no revientan en Meta; el resumen solo queda en el historial si
  Meta lo aceptó.
- **Asistente**: no elige la técnica por la clienta; un "sí" a la cita de
  valoración cuenta; no niega un servicio que existe cuando le dan el nombre
  exacto.
- **Captación**: se borró todo el código que automatizaba productos de Meta
  (DMs de Instagram y WhatsApp Web). No se vuelve a montar: ver `CLAUDE.md`.
- **Sincronía entre agentes** (11-sep, `7fb3823`): https://app.vantelia.es/sincronia
  enseña con un semáforo si Claude y Astra han visto lo último del otro, y lo que
  se dicen entre ellos.
- **Revisión automática** (11-sep, `dbdba26` + `83bbeb6`): cuando Astra pide
  revisión, la tarea programada «Vantelia revisor» pasa los tests en una copia
  aparte y lanza la revisión de Claude sin nadie delante. Probada de verdad con
  `claude -p`: revisión útil y veredicto bien leído.
- **Sin créditos** (11-sep, `3fd5e0b`): si uno se queda sin cuota lo sabe el otro
  solo (a Astra se le lee de su propia sesión de Codex, con la hora de vuelta) y
  sigue él; nada se pierde mientras tanto.
- **Reprogramar a la primera** (11-sep, `5d05457`, en producción `1268e4a`): al
  mover una cita solo se ofrecen horas de SU profesional y que el núcleo acepta
  (antes se ofrecían huecos de otra y el cambio se rechazaba). Lo encontró y
  arregló Astra; lo integró y desplegó Claude.
- **Mensaje ilegible por WhatsApp** (11-sep): el primer "hola" al +31 recién
  conectado llegó de Meta sin texto, y al modelo se le pasaba una instrucción por
  el hueco del texto de la clienta; quedaba en el historial como dicha por ella y
  al mensaje siguiente repetía "no puedo leer mensajes que no estén en formato de
  texto". Ahora se pide que lo repita con una frase fija (también el audio que no
  se oye) y abrir el chat por primera vez (`request_welcome`) cuenta como saludo.
  Los avisos de sistema de Meta (cambio de número) no se contestan.
- **«La primera que tengas» acaba en cita** (11-sep): el código elegía el primer
  hueco (a última hora, hoy a diez minutos vista) mientras el modelo le enseñaba
  horas de otro día, y el nombre no se anotaba hasta `crear_cita`: le repetía la
  lista y se quedaba sin cita. Ahora la hora del código sigue al día que ella lee,
  "me llamo X" se anota al momento (se cierra en ese turno), y el primer hueco de
  hoy deja una hora de margen. En 6 conversaciones contra copia de producción:
  5 reservan con el primer "sí"; en la otra el modelo mezcló el día que
  encabezaba su lista con la hora elegida, la herramienta lo frenó (ninguna cita
  mal cogida) y reservó al siguiente "sí". Para esa mezcla, guardarraíl
  (`reserva.dia_cambiado_con_la_hora_elegida`): si la llamada trae la hora elegida
  con otro día que ella no ha dicho, manda el día que se le propuso. Con él, otras
  6 conversaciones: las 6 al primer "sí" (la mezcla no se repitió; la cubre el
  test).
- **El asistente vuelve a la hora** (11-sep, decisión de Pablo): tras contestar el
  equipo desde WhatsApp Business se calla 1 h desde su último mensaje (antes 2 h;
  por negocio, `whatsapp.silencio_tras_responder_min`). Al volver, un "hola" no
  saca la bienvenida con el menú: lo coge el agente, que conserva lo hablado (su
  historial ya no se corta a la media hora si ha intervenido una persona).
- **"Corte de señora" es "Corte señora"** (11-sep): un "de" de más en el nombre
  que escribe el modelo ya no cambia el servicio. Antes no se encontraba y la
  cita se cogía de 15 min (el paso de la agenda) en vez de 20, con un nombre que
  no existe en el catálogo.
- **Recordatorios por WhatsApp fuera de la ventana de 24 h** (11-sep, `57f6d45`):
  Meta solo deja escribir texto libre 24 h desde el último mensaje de la clienta,
  así que un recordatorio del día antes casi siempre se perdía. Ahora sale como
  plantilla (`vantelia_recordatorio_cita`, transaccional) de la cuenta del propio
  negocio, con los mismos botones «Confirmo» y «Cancelar cita», que ya se
  procesan al pulsarlos. La plantilla la da de alta y consulta el worker; en la
  cuenta del +31 ya está creada y en revisión. Sin plantilla aprobada no sale por
  WhatsApp: el aviso sigue por el siguiente canal y el motivo queda anotado.
  Además, **las citas de demo ya no avisan ni llaman a nadie** (la cuenta de
  revisión de Meta tiene 191 con móviles inventados). Cada plantilla fuera de
  ventana la cobra Meta al negocio, que necesita método de pago allí.
- **Dos apellidos por WhatsApp** (11-sep, decisión de Pablo): a una clienta nueva
  se le piden nombre y dos apellidos antes del resumen (freno en `crear_cita` del
  agente y en el flujo con listas, que junta lo que va diciendo; a la tercera se le
  ofrece llamar). A una clienta conocida no se le pide nada.
- **No ofrece una hora que no existe** (12-sep, `e6be556`): tras enseñarle
  09:00-10:00, a un «a las 15» contestaba *«mañana a las 15:00 tengo disponible»*,
  ella decía que sí, y la mentira solo se descubría al crear la cita, tres turnos
  después (la cita imposible NUNCA nació: el hueco se comprueba al crearla). Ahora,
  si ofrece una hora que no está en los huecos que tenemos y no ha mirado la agenda
  en ese turno, se le obliga a mirarla. En las trazas se ve funcionando: contesta
  «las 15:00 no las tengo, tengo estas por la mañana» en el turno bueno.
- **Lo de Astra, verificado e integrado** (12-sep, `aab4d02`): el botón de mover
  cita ya no canta éxito cuando el núcleo rechaza el cambio; el pack de la cita no
  se convierte en el servicio suelto al moverla; a una clienta ya conocida no se le
  vuelven a pedir los apellidos; y una respuesta que Meta rechaza no queda en el
  historial como enviada. Comprobado antes de integrar: sus 5 tests fallan contra
  main sin sus arreglos, suite entera sobre su rama (2082) y sobre la fusión (2116).

## El crítico que no cierra (12-sep, medido de madrugada)

El caso `dice-que-si-y-acaba-en-cita` sigue siendo INTERMITENTE y es lo único rojo
del banco: **42 de 43** contra copia fresca de producción con la config viva.

Lo que se sabe, medido:

- Con el freno de la hora inventada: 4 de 9. La MENTIRA está tapada; lo que falla
  es el cierre. La conversación se atasca porque el servicio sigue sin concretarse
  («no lo tengo claro») y el modelo vuelve a preguntar la técnica en vez de cerrar.
- **El atajo que debería cortar eso lleva desde el 8-sep muerto.**
  `_hay_que_cogerle_la_valoracion` corta a la TERCERA pregunta y coge el
  diagnóstico, pero el contador (`veces_falta`) solo subía si faltaba el MISMO dato
  dos veces seguidas, y el modelo alterna (técnica, largo, técnica): se reiniciaba
  siempre. No saltó ni una vez en 12 conversaciones medidas. Hay un intento de
  arreglo en `claude/hora-sin-mirar` (`_veces_sin_concretar`), **sin validar**: con
  él tampoco llegó a saltar, así que la causa puede ser otra.
- Ampliar el freno de la hora (que frenara también sin huecos sobre la mesa):
  1 de 6. Descartado de momento.

**DOS TRAMPAS DEL INSTRUMENTO, las dos costaron conclusiones falsas esta noche:**

1. Medir desde un worktree NO vale: no tiene `.env`, así que no hay clave de
   OpenAI y todas las conversaciones fallan por lo mismo. Dio un 0 de 4 que no
   medía nada. Los worktrees valen para tests, no para el banco.
2. **El guion del caso dice «manana», y el resultado depende de qué día sea.**
   Medido en la madrugada del sábado al domingo: «mañana» cae en domingo, que el
   salón CIERRA, así que la conversación correcta ya no puede acabar en cita. Peor:
   algunas tiradas «pasaban» porque el modelo reservaba HOY llamándolo «mañana».
   Comparar medidas tomadas a un lado y otro de la medianoche es comparar días
   distintos. Si se toca este caso, medir de día y con «mañana» abierto.

Fragilidad aparte: `tests/test_estirar_la_cita.py` da 11 errores en un worktree
limpio (fixture que reserva y recibe 409) y pasa en `E:/Vantelia`. Depende de
estado local, no es hermético. No es de esta noche: pasa igual en `aab4d02`.

## Bloqueado por fuera del código

- **Coexistence: DESBLOQUEADO (11-sep).** Meta aprobó la revisión de la app y
  Pablo la publicó. El +31 97006546256 de Vantelia funciona en Coexistence (WA
  Business en su móvil + asistente a la vez) y contesta con el **asistente de
  Vantelia** (tenant `metareview`, "Clara"). Estuvo unas horas con el de Alicia y se
  deshizo a petición de Pablo: su pestaña WhatsApp está limpia para que conecte el
  suyo. Si alguien contesta desde WA Business, el asistente se calla 1 h desde su
  último mensaje en ese chat (vuelve solo, sin saludar de nuevo y sabiendo lo
  hablado; o «Devolver al asistente» en Conversaciones).
- **Avisos de cita de Alicia: hoy no sale ninguno.** En el bloque que usa el motor
  (`booking.message_template_channels`) tiene el email apagado y solo WhatsApp, y
  WhatsApp no está conectado. Cuando conecte su número empezarán las
  confirmaciones por WhatsApp; los recordatorios de 24 h casi nunca saldrán hasta
  que haya plantillas (`docs/PLAN_RECORDATORIOS_WHATSAPP.md`).
- El alta self-service de WhatsApp sigue limitada al tenant de pruebas
  `metareview` (variable `WHATSAPP_ES_TENANTS`). Conectar el número PROPIO de
  Alicia pasa por añadirla ahí (ver decisión 1).
- **Stripe de Alicia**: cuenta conectada pero `charges_enabled=0`,
  `payouts_enabled=0`, `details_submitted=0` (sin cambios desde el 27-ago). Los
  servicios con señal **se reservan sin cobrarla**. Se retoma después de Meta.

## Piloto de Alicia: comprobado en producción (11-sep)

Leído de la BD de producción, no de los documentos de agosto. Sustituye a las
"preguntas abiertas" de `docs/ALICIA_PENDIENTE.md` donde choquen.

- **Señal**: 53 servicios activos la llevan. **Ninguno de menos de 50 €** (hay 91
  activos por debajo, todos sin señal). La pregunta de agosto sigue igual: es
  decisión de Alicia, no un fallo.
- **Grey blending**: los sueltos de 75/90/105/120 min están desactivados; queda
  activo "Grey blending corto-med" (90 min, 48 €). Packs: corto 370 min, medio
  440, **largo 530, extra largo 495**. Que el largo dure más que el extra largo
  hay que preguntárselo a ella (en agosto ya se vio que el "largo" usa pasos de
  extra largo).
- **Recogidos**: existen y están activos (medio recogido 20 min, con postizo 30,
  recogido con postizo 40, pack maquillaje y recogido 170, pack maquillaje y
  medio recogido 215). No se han revisado los pasos internos de los packs.
- **Equipo**: Alicia tiene **0 servicios asignados a propósito**: lista vacía =
  los hace todos (`agenda._services_for_employee`), y así los servicios nuevos le
  entran solos. No "arreglarlo" poniéndole una lista. Lorena 190, Conchi 193,
  Lucía 108, Jose 108.
- Sin comprobar todavía: horario real de Lucía y Jose, y si Alicia ha probado la
  última versión.

## Decisiones pendientes de Pablo

1. **Alicia con su propio número: LISTO para que lo conecte** (11-sep, comprobado
   en producción). Le sale el botón «Conectar mi WhatsApp» en la pestaña WhatsApp
   de su portal (`WHATSAPP_ES_TENANTS=metareview,alicia_rincon_estilistas` en el
   `.env` del VPS). Al conectar, su configuración pasa sola al número nuevo. Es la
   prueba de que el alta vale para una empresa que no es la nuestra. Después,
   vigilar sus avisos (ver «Avisos de cita de Alicia» arriba) y el punto 2.
2. **Siguiente gran tarea: recordatorios por WhatsApp** (plantillas de Meta). Plan
   para ejecutar tal cual en `docs/PLAN_RECORDATORIOS_WHATSAPP.md`.
3. Decidido (11-sep): **dos apellidos obligatorios** en el panel y también por
   WhatsApp a las clientas nuevas; a las conocidas no se les pide nada.
4. **Anotado para más adelante** (Pablo, 11-sep: "con el resto ya seguiremos"):
   - `scripts/tiktok_autosend.py`: misma clase de riesgo que las automatizaciones
     de Meta que se borraron; ¿se retira?
   - Rotar `WHATSAPP_APP_SECRET` (se imprimió en claro el 9-sep): lo lleva Pablo.
   - Stripe de Alicia sin activar: Pablo se lo pide a ella.
   - Preguntar a Alicia: grey blending "largo" (530 min) dura más que el "extra
     largo" (495); horario real de Lucía y Jose.
   - El formulario de reserva dentro de WhatsApp (Flows) está en borrador y en la
     WABA de Vantelia: en números de otros negocios no sale (sigue por mensajes).
   - Aviso al negocio de un mensaje normal (hoy solo cuando piden persona) y push.
   - Esfuerzo de razonamiento de Astra (con `xhigh` gasta la cuota en una hora).
5. Hecho (11-sep): Pablo aprobó en Codex los hooks de Astra (`~/.codex/hooks.json`,
   desde la terminal: la app de escritorio no tiene `/hooks`).

## Frágil, a vigilar

- El humo da por bueno lo que llega a la agenda, no cómo llega: `corte-acaba-en-cita`
  "pasaba" 6 de 6 con la clienta viendo la lista de horas dos veces, gracias al
  "sí, confirmo" de sobra del guion. Arreglado el fallo (ver «Lo último»), el
  instrumento sigue sin verlo: leer las conversaciones, no solo el veredicto.
- En el catálogo de Alicia conviven "Corte señora" (20 min) y "Corte de señora"
  (15 min), y el asistente coge uno u otro. Preguntarle cuál vale.
- Cualquier sitio donde una lista de frases decide qué quiere decir la clienta.
- La frontera con Meta: un payload mal formado corta la conversación sin error
  visible para nadie; solo sale en los logs del servidor.
- Los fallos de estas semanas NO los encontraron los tests ni el banco: los
  encontró Pablo usando el producto como una clienta. Probar a mano la
  conversación entera sigue siendo imprescindible.


Corrección adicional del 13-sep (validada con pruebas dirigidas): mencionar diagnóstico para
rechazarlo activaba `_pide_la_valoracion`, que además borraba el servicio acumulado.
Se reutiliza el detector compartido de renuncia distinguiendo negativa explícita
de preferencia por reservar directamente. «Quiero diagnóstico directamente» sigue
siendo una petición. La obligatoriedad puede impedir contratar el tratamiento sin
valoración, pero no transforma una negativa en aceptación de cita. Cuatro pruebas
rojas antes del cambio; 77 dirigidos verdes, pyflakes de los módulos tocados y diff limpios. No se modifica
configuración de negocio ni se añade una lista de frases en el canal.


Relevo tras este bloque: retirada Q&A en d42e964 y negativa explícita en su
siguiente commit. No hay suite propia ejecutándose ni revisión formal solicitada.
Claude conserva su encargo; diagnóstico de demos sin entrega recibida al cerrar.
La siguiente puerta de validación del conjunto es resolver esos fallos y pasar
una suite completa, después revisión exacta y banco comparable. Quedan trabajo
independiente de reconciliación/outbox y migración de confirmaciones de gestión;
no confundir estos dos arreglos con haber terminado toda la arquitectura.


Integración 13-sep: 52acab5 une ee939c8 con el candidato moderno; no añade el segundo
validador de retirada ni vuelve a botones genéricos. Nuevo cierre del estado:
`anotar_resultado` invalida selección, duración, profesional, hora y resumen tras
rechazo de crear el servicio vigente. Conserva nombre/fecha y no borra una cita
terminada ni la selección al consultar otra alternativa. Prueba roja antes del
arreglo; 61 dirigidos verdes. Aviso WhatsApp con envío rechazado no se registra.
La nota de Claude sobre widget ya estaba cubierta por da0ca70 y se volvió a probar.

Cola depurada: retirados encargos propios 6bbb04 y 8a476e ya implementados en
antecesor da0ca70. No son aprobaciones. Diagnóstico 04d9a4 reasignado a Astra antes
de lanzarlo aquí; Claude conserva el calendario activo, sin interrumpir su proceso.


Demos, diagnóstico cerrado el 13-sep: el fichero aislado dio 21 verdes. Orden
reducido (demo inicial -> módulo de agenda que recarga backend -> cinco casos)
reprodujo EXACTAMENTE los cinco fallos, con dos controles verdes. No es horario ni
regresión demostrada del agente: la API de fixture de sesión apuntaba a módulos
antiguos, mientras importaciones locales desde outreach usaban el backend nuevo;
se mezclaban registros de demos y los monkeypatch no alcanzaban el constructor.
Fixture api_module local al módulo de demos crea un runtime coherente. El mismo
orden, con TODO el fichero de demos después, da 23 verdes. Solo se modifica el
instrumento; no se toca outreach ni se rebajan las comprobaciones. Suite completa
es la siguiente puerta, seguida de revisión exacta; las métricas reales no se dan
por medidas.

### Relevo vigente — 14-sep-2026 14:12 Europe/Madrid

- Testigo: Astra, por orden de Pablo mientras Claude no tiene créditos.
- Rama: astra/aceptacion-e44886b, descendiente de 61a3081, código e44886b.
- Suite de e44886b terminada: 2737 passed, 1 skipped, exit 0 (1429,37 s), verificada en bcssa0kh5.output. No repetir.
- En ejecución: crítico con modelo real sobre copia local temporal; informe en TEMP/astra-e448-critico.json. No acredita todavía equivalencia de datos con producción ni aceptación global.
- Siguiente: cerrar medición comparable y propuesta de despliegue. Ningún push ni despliegue autorizado en este relevo.

### Encargo Astra 14-sep 19:15: vacaciones en canales

Rama astra/cierre-canales en E:/Vantelia-astra-cierre-canales, rebasada sobre 6671362. RAG, contexto de chat y selector de fechas consultan el cierre compartido; tres regresiones rojas verificadas. Suite original c07202d: 2766 passed, 1 skipped, un fallo por expectativa antigua de completo en un cierre total; expectativa corregida conservando siguiente día. Testigo: Astra. Siguiente: dirigidos y suite del candidato actualizado; espera a revisión exacta de Claude tras verde. No desplegado.
