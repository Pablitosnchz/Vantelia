# Evidencia de aceptación del candidato IA

Estado: **c8aaad8 DESPLEGADO en producción el 14-sep a las 16:38 (VERSION.json 14e5a5d) por orden de Pablo** (sección siguiente); antes, bec310f a las 07:22, con dos apellidos activos para Alicia. Lo anterior se conserva como historial. Un resultado local verde no acredita mejora con el modelo
ni funcionamiento de Meta en un número conectado. Mantener este informe junto
al plan y al registro horario; no completar casillas por inferencia.

## Candidato de cierre del plan: 5c927dd / e230991, medición del 14-sep-2026, 20:17–20:54 (Claude)

Sobre lo desplegado (125725f): cierre por vacaciones en chat, RAG y selector de WhatsApp (Astra, revisado por Claude:
1cdb3f9 y 5c927dd) y, en e230991, los arreglos de la revisión de Astra a lo que ya estaba en producción (fechas y cobro
de la prueba gratis; conflicto al recuperar una cancelación). Copia de producción snap7 (14-sep 20:14, solo lectura,
770 citas, las 4 reglas de Alicia), config cfg7, solo la clave del modelo, código limpio (sucio=0 en backend, evals y
scripts). Copias borradas al acabar.

| Instrumento | Candidato | Referencia c8aaad8 |
| --- | --- | --- |
| Banco de Alicia (5c927dd) | 43/43 al primer intento; 0 tras reintento, 0 fallos, 0 no medidos, 1 no aplica | 43/43 |
| Crítico `dice-que-si-y-acaba-en-cita` ×6 (5c927dd) | 6/6 al primer intento; 0 tras reintento, 0 no medidos | 6/6 |
| Humo (5c927dd y e230991) | 5/5 y 5/5 | 5/5 |
| Portal y reinicios (5c927dd) | 6/6; 0 fallos, 0 no medidos | 6/6 |
| Metareview, segundo negocio (5c927dd) | 15/16 al primer intento; 1 reintento fallido, 0 no medidos, 28 no aplican | 15/16 |

El fallo de metareview es `horario-escrito-manda` con el criterio que ya no depende del día (`horario_semanal`):
contesta «Hoy estamos abiertos de 09:00 a 18:00, pero lamentablemente no tenemos disponibilidad para citas», sin el
horario de la semana. Fallo real de ese asistente, fuera del plan (tabla de la fase 4). Límites: una tirada por
instrumento salvo el crítico; no mide WhatsApp real con Meta ni recordatorios (número de Alicia sin conectar). e230991
solo cambia checkout, webhook de Stripe y la recuperación de una cancelación: medido con humo; su evidencia principal
son las pruebas rojas antes del arreglo. bef4193 (363e715 en `claude/cierre-plan`) añade solo una holgura de 10 min
antes de mandar `trial_end` a Stripe, también con test rojo previo. Pendiente al escribir esto: suite completa de
bef4193 y revisión de Astra (sin créditos hasta las 22:19).

## Candidato c8aaad8: medición del 14-sep-2026, 15:40–16:24 (Claude)

Candidato sobre lo desplegado (bec310f): Fase 3 (avisos del editor de reglas), avisos que no
se quedan bloqueados (tras cuatro rondas de revisión adversarial de Codex), reconciliación de
operaciones de creación perdidas (Astra, más 04fc97f), reenvío manual que avisa ante un
WhatsApp dudoso y reprogramar guiado por WhatsApp con aceptación. Medido con modelo real
sobre copia de producción (snap6, solo lectura, borrada al acabar) y código limpio.

| Instrumento | c8aaad8 | Referencia |
| --- | --- | --- |
| Banco de Alicia | 43/43 al primer intento, 0 fallos, 1 no aplica | 43/43 (ed94be1) |
| Crítico `dice-que-si-y-acaba-en-cita` | 6/6 al primer intento | 6/6 (ed94be1) |
| Humo | 5/5 | 5/5 (bec310f) |
| Portal y reinicios | 6/6, 0 sin medir | 6/6 (ed94be1) |
| Metareview (segundo negocio) | 15/16; fallo `horario-escrito-manda`, depende del día | 15/16 (bec310f), mismo fallo |

Sin reintentos en ninguna tirada de Alicia. No medido: WhatsApp real con Meta y recordatorios
reales (el WhatsApp de Alicia sigue sin conectar), y la revisión de Astra de 04fc97f.
Suite completa de c8aaad8: 2738 passed, 1 skipped, 0 fallos (15:40–16:29).
Desplegado por orden de Pablo (16:33–16:38, exit 0, VERSION.json 14e5a5d sin cambios sin commit):
humo en el servidor 5/5 y el crítico dentro del contenedor OK al primer intento.

## Remate tras el despliegue: 14-sep-2026 (Claude)

Producción sigue en 109b091 (código 0bca1eb). Rama `claude/candidato`, código **ed94be1**: siete
cambios más, todos con test rojo sin el arreglo, medidos con modelo real sobre copia nueva de
producción (`snap5`, 14-sep 02:17: 769 citas, 4 reglas de Alicia incluida la de orientación),
config viva `cfg5`, solo la clave del modelo, árbol limpio y SHA estable.

### Qué cambia

| Commit | Arreglo | Caso medido que lo motivó |
| --- | --- | --- |
| 74e2894 | Pack con `preferir_packs` aunque el extractor pegue la talla a la técnica; fechas ISO en humano | Humo 13-sep: «Mechas medio» (75 min) en vez del pack de 360; «para el 2026-09-15» en 3 de 6 críticos |
| 3f11dea | Freno de «cerrado» mira de qué día habla; cita de una oferta retirada no se coge | metareview (domingo cerrado); regla apagada tras ofrecer |
| 4533dee | Ventana de reserva con el reloj de la app | Suite roja sola desde el 14-sep (calendario de medidas) |
| f288ddf | «Qué me recomiendas» cuenta como duda | `recomienda-ante-un-problema`: alisado para la caída del pelo |
| 36b4d8d | `dijo_que_hay_cita_sin_haberla` no niega una cita viva a su hora | Reprogramar 13-sep |
| ed94be1 | Test de dos reprogramaciones simultáneas prueba la carrera de verdad | No probaba nada; rojo según el orden de la suite (traza del 14-sep: 409 al crear las citas iniciales, línea 150; mutación sin la re-comprobación: `[200, 'IntegrityError']`) |

### Medición de ed94be1

| Medición | Resultado |
| --- | --- |
| Suite completa | 2675 passed, 1 skipped, 0 fallos (24 min 38 s); el test de concurrencia corregido, verde dentro de la suite |
| Banco Alicia (44) | 43/43 al 1.er intento, 0 reintentos, 0 fallos (1 no aplica); `recomienda-ante-un-problema` ya contesta con el texto de Alicia («sin ver tu cabello…») |
| `dice-que-si-y-acaba-en-cita` ×6 | 6/6 al 1.er intento, mismo resumen en las 6; 0 respuestas con fecha ISO (antes del arreglo, 3 de 6) |
| Humo (5) | 5/5; `elegir-una-opcion-resuelve` crea el Pack mechas o balayage medio (6 h, antes 75 min en una tirada); cancelada y movida leídas en la copia |
| Cambios del portal y reinicios (6) | 6/6 al 1.er intento; regla apagada: tras «ya no está vigente» vuelve a preguntar la técnica, sin resumen del diagnóstico; reinicio a mitad: una cita viva a las 17:00 y sin negar la hora libre. Vacaciones: sigue diciendo «agenda completa» en vez de cerrado (pendiente de redacción) |
| metareview conversacional | 14 al 1.er intento, 2 fallos (ver abajo) |

### Arreglo posterior y medición de bec310f

bec310f: lo que el negocio no hace se dice igual lo extraiga el modelo como técnica o como familia (manicura en metareview). Test rojo sin el arreglo; 453 verdes en búsqueda de servicios.

| Medición | Resultado |
| --- | --- |
| metareview conversacional | 15/16 al 1.er intento; `servicio-que-no-existe` ya dice «no tenemos un servicio de manicura» (tool: «no hay ningún servicio de manicura», sin frenos); único fallo `horario-escrito-manda`, que depende del día de la medición |
| Humo (5) | 5/5; corte creado, pack de mechas completo (6 h), cancelada y movida leídas en la copia |
| Suite completa | 2678 passed, 1 skipped, 0 fallos (20 min 45 s) |

### Preguntas abiertas y dependencias externas

- `exigir_dos_apellidos` no está activo para Alicia en la config de producción (sí en el `config.json` del
  repo desde 550aafe). Se mide igual que producción. Decide Pablo.
- WhatsApp de Alicia sin conectar (sin cuenta ni plantilla en producción): los recordatorios por WhatsApp no
  pueden salir hasta que conecte su número.

### Fallos de metareview en ed94be1 (leídos en agent_turns)

- `horario-escrito-manda` (importante): medido un LUNES a las 02:48. Primer borrador «hoy cerrados», el freno de
  «cerrado» lo corrige (el lunes abre) y contesta «Hoy estamos abiertos de 09:00 a 18:00… mañana, martes 15». El
  caso exige la palabra «lunes»: ayer (domingo) pasaba en todas las versiones, producción incluida, porque decía
  «mañana, lunes». Depende del día en que se mide: pendiente del instrumento, no regresión.
- `servicio-que-no-existe` (importante), 2 de 2 intentos: a «me quiero hacer la manicura» pregunta qué tipo de
  manicura. `buscar_servicio` dio el genérico «no hay nada que encaje» (ayer: «no hay ningún servicio de manicura»
  con parecidos). Depende de si el extractor pone «manicura» como técnica o como familia: la comprobación de
  «nadie la hace» solo miraba la técnica. Ya estaba así en producción; arreglo en curso.

## Actualización 13-sep-2026, 17:55: dos revisiones, sus arreglos y medición del SHA final (Claude)

Candidato final: rama `claude/candidato`, código **0bca1eb**.
Sobre 112b26c: 24a4a51 (medidor de portal y reinicios), a329fe0 (hallazgo de Astra), c0bc746
(escenario de hora bloqueada), 1630583 (nombre de relleno), 2a794c2 (revisión independiente),
3167313 (freno que negaba horas libres), 413c170 (docs) y 0bca1eb (hallazgos de Astra). Condiciones: copia nueva de `snap4_conregla` (producción
13-sep 15:52 + regla de orientación de Alicia SOLO en la copia), config viva `cfg4`, modelo
`gpt-4o-mini`, solo se inyecta la clave del modelo, árbol limpio y SHA estable en cada tirada.

### Despliegue (14-sep-2026)

`deploy/deploy.ps1 -SkipLocalChecks` (suite completa ya verde sobre 0bca1eb) 01:16:59–01:20:03, exit 0: foto
previa de la BD, `/health` ok, acceso público OK, humo en el servidor 5/5, VERSION.json 109b091. Regla
`rule_eD_NnlJc1lQ` creada con copia de seguridad previa; `dice-que-si-y-acaba-en-cita` dentro del contenedor
sobre una copia: OK al primer intento con el resumen del diagnóstico a nombre de Ana Ruiz Perez.

### Revisiones antes de desplegar

- **Astra** (782a53f..45d7f85, 16:12): «PACK MECHAS LARGO» al reprogramar contaba como cambio de
  servicio y se auditaba una actualización sin cambio. Arreglado en a329fe0 (3 regresiones rojas
  sin el arreglo). Astra da el arreglo por bueno (17:16: «cubre Pack/nombre público/capitalización»).
- **Revisión independiente en frío** (subagente de solo lectura, 782a53f..1630583): VEREDICTO
  CAMBIOS. Cuatro defectos reproducidos ejecutándolos, arreglados en 2a794c2 (30 de 36 tests en
  rojo sin el arreglo; los otros 6 son controles):
  1. La hora tomaba el número del día: «el jueves 18 a las 11» daba las 18:00.
  2. `booking_name` guardaba conversación como nombre («perdona, mejor a las 16»).
  3. «sí, el jueves a las 17» aceptaba la oferta y perdía el día y la hora.
  4. El freno de cancelar bloqueaba cancelaciones legítimas («no puedo venir, quítamela»,
     «bórramela», el «sí» a «¿quieres que la cancele?»).
- **Leyendo las conversaciones de 2a794c2** (escenario de reinicio a mitad de reserva): el freno
  `ofrecio_una_hora_que_no_tiene` obligó a decir «a las 17:00 no tengo disponibilidad» con las
  17:00 libres, porque comparaba contra una MUESTRA de 8 huecos. Ya estaba en producción.
  Arreglado en 3167313 (test con el estado de los turnos medidos, rojo sin el arreglo; el control
  con la hora ocupada sigue frenando).

- **Astra sobre 2a794c2 y 3167313** (17:16): CAMBIOS. [CRÍTICO] `_le_pregunto_si_la_cancela`
  autorizaba cualquier «sí» si el último mensaje llevaba «?» y «cancelar» en otra frase («No puedo
  cancelar la cita pasada. ¿Quieres que te ayude con otra cosa?»). [IMPORTANTE] En `booking_name`,
  con el agente caído, la frase se guardaba como nombre. 3167313: sin hallazgo. Arreglados en
  0bca1eb: solo cuenta una pregunta que ofrezca anular, sin negarlo ni dar alternativa (13 frases
  comprobadas), con recorrido por la herramienta; con el agente caído se vuelve a pedir el nombre.

### Comparación de conversaciones completas

| Negocio y versión | Previstos | No aplican | No medidos | OK 1.er intento | OK tras reintento | Fallos finales | Artefacto |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Alicia, referencia (bd7a6da) | 44 | 1 | 0 | 41 | 1 | **1 crítico** | ref_banco.json |
| Alicia, candidato (112b26c) | 44 | 1 | 0 | 42 | 1 | 0 | banco_g.json |
| Alicia, candidato (2a794c2) | 44 | 1 | 0 | **43** | 0 | **0** | banco_h.json |
| Alicia, candidato (3167313, commit 413c170) | 44 | 1 | 0 | 42 | 1 | **0** | banco_i.json |
| Alicia, candidato final (0bca1eb) | 44 | 1 | 0 | **42** | 1 | **0** | banco_j.json |
| metareview conversacional, referencia (bd7a6da) | 44 | 28 | 0 | 16 | 0 | 0 | ref_meta_conv.json |
| metareview conversacional, candidato (2a794c2) | 44 | 28 | 0 | **16** | 0 | **0** | banco_meta_h.json |
| metareview conversacional, candidato (3167313, commit 413c170) | 44 | 28 | 0 | 15 | 1 | **0** | banco_meta_i.json |
| metareview conversacional, candidato final (0bca1eb) | 44 | 28 | 0 | **16** | 0 | **0** | banco_meta_j.json |

Otras mediciones:

| Medición | SHA | Resultado |
| --- | --- | --- |
| Suite completa | 2a794c2 | 2631 passed, 1 skipped (21 min 54 s) |
| Suite completa | 413c170 (código 3167313) | 2633 passed, 1 skipped (21 min 47 s) |
| Suite completa | 0bca1eb | 2641 passed, 1 skipped (22 min 7 s) |
| Humo (5 recorridos) | 2a794c2 | 5/5; citas creadas, cancelada y movida leídas en la copia; avisos sin canales |
| Humo (5 recorridos) | 413c170 | 5/5; citas de corte y pack mechas creadas, una cancelada y otra movida, leídas en la copia; avisos sin canales |
| Humo (5 recorridos) | 0bca1eb | 5/5; citas de corte y mechas creadas, una cancelada y otra movida, leídas en la copia; avisos sin canales |
| `dice-que-si-y-acaba-en-cita` ×6 | 2a794c2 | 6/6 al 1.er intento; resumen de Diagnóstico y presupuesto 15:00 a nombre de Ana Ruiz Perez en las 6 |
| `dice-que-si-y-acaba-en-cita` ×6 | 413c170 | 6/6 al 1.er intento; mismo resumen en las 6 (Diagnóstico y presupuesto, martes 15 a las 15:00, Ana Ruiz Perez); fecha «2026-09-15» en una respuesta intermedia en 2 de 6 |
| `dice-que-si-y-acaba-en-cita` ×6 | 0bca1eb | 6/6 al 1.er intento; mismo resumen en las 6; fecha «2026-09-15» en una respuesta intermedia en 3 de 6 |
| Cambios del portal y reinicios (6 escenarios) | 24a4a51 / c0bc746 / 2a794c2 | 6/6 (1 falso aprobado corregido) / escenario corregido OK / 6/6 |
| Cambios del portal y reinicios (6 escenarios) | 413c170 | 6/6; en el reinicio a mitad de reserva ya no se niega la hora libre (una cita viva a las 17:00); la única negativa es la del horario bloqueado |
| Cambios del portal y reinicios (6 escenarios) | 0bca1eb | 6/6; `regla-apagada-despues-de-ofrecer` al 2.º intento (el 1.º acabó en el resumen del diagnóstico retirado); una cita viva en los dos reinicios |

### Puertas de aceptación (cambios respecto a lo anterior)

| Recorrido | Evidencia | Pendiente |
| --- | --- | --- |
| Cambios del portal | Vacaciones tras ofrecer el día, hora bloqueada y servicio retirado con el resumen delante, regla apagada tras ofrecer: con modelo real, sin cita en lo retirado | Solo un día de calendario |
| Reinicio/repetición | Reinicio a mitad de reserva y con el resumen delante: una sola cita viva | — |
| Revisión | Astra (a329fe0 OK; 3167313 sin hallazgo; 2a794c2 con 2 cambios, arreglados en 0bca1eb) + revisión independiente (4 hallazgos arreglados) | — (Astra, 17:38: «REVISION 0bca1eb: OK», sin hallazgos nuevos; a329fe0 OK) |

### Pendiente de producto nuevo (además de la lista anterior)

- Una respuesta intermedia escribe la fecha como «2026-09-15» (crítico: 2 de 6 tiradas en 2a794c2, 2 de 6 en 413c170 y 3 de 6 en 0bca1eb).
- Con el día bloqueado por vacaciones contesta «la agenda está completa ese día» en vez de que está
  cerrado (sin cita; ofrece otro día).
- De la revisión independiente, sin arreglar: una nota del agente se sobrescribe en `agent.py`;
  posible callejón si con clienta conocida `_wa_resumen_para_confirmar` devuelve False tras pasar a
  `booking_confirm`.
- metareview (413c170): `horario-escrito-manda` necesitó reintento; el primer intento dijo
  «mañana» y no «lunes» (redacción). En ese caso salta `dijo_cerrado_estando_abierto` diciendo
  «hoy estamos cerrados» en domingo, que es verdad (`closed_weekdays: [6]`): freno en falso, igual
  en 2a794c2. Un intento dijo «para mañana ya no hay huecos» con el lunes abierto: sin verificar.
- Alicia (413c170): `recomienda-ante-un-problema` necesitó reintento; a «se me cae mucho el pelo»
  sugiere alisados y color o mechas (pendiente ya conocido, también en producción); en 0bca1eb igual, y el reintento propuso el diagnóstico de extensiones.
- **Riesgo serio, ya en producción (código de elección de servicio sin cambios desde bd7a6da):** en
  el humo `elegir-una-opcion-resuelve` («mechas», «lo tengo medio»), la MISMA llamada
  `buscar_servicio("mechas lo tengo medio mechas medio")` dio en 413c170 «Pack mechas o balayage
  medio» (360 min) y en 0bca1eb «Mechas medio» (75 min), con `preferir_packs` activo. La cita de
  0bca1eb se habría apartado con cinco horas de menos. Varía la extracción del modelo
  (`intents.extraer_datos_servicio`); el humo solo exige que haya cita. Leído en `agent_turns` y en
  la cita de cada copia.
- Regla apagada a mitad de conversación (0bca1eb, 1 de 2 intentos; con 24a4a51, 2a794c2 y 413c170
  pasó al primero): tras «Esta opción ya no está vigente», al dar el nombre el modelo volvió al
  diagnóstico y montó su resumen. Sin cita creada (la confirma ella). No lo toca 0bca1eb. Las
  herramientas de ese intento no se pueden leer: el medidor reutiliza la copia del escenario en el
  reintento (mejora pendiente del instrumento: una copia por intento).

## Informe de aceptación del candidato: 13-sep-2026 (Claude, agente principal)

Candidato: rama `claude/candidato`, código **112b26c** (+ instrumento 5f5e10c, ae7d9ff y 00a7726; docs).
Contiene `astra/condiciones-confirmadas` (7740b45, checkout Stripe 68c1fac) y `main` (bd7a6da,
lo desplegado). Referencia: **bd7a6da** (producción, VERSION.json del VPS), código extraído con
`git archive` (sin `site_exports`/`hostinger_site`) y medido con el MISMO instrumento del
candidato; solo se inyecta la clave del modelo (nunca en disco).

Condiciones comunes: modelo `gpt-4o-mini`; copia `snap3_conregla` (producción 13-sep 08:59 +
regla de orientación de Alicia declarada SOLO en la copia); config viva `cfg3`; calendario
resuelto (día abierto 2026-09-15); árbol limpio y SHA estable en todas las tiradas del candidato.
Informes JSON por tirada en el scratchpad de la sesión; copias de BD borradas tras leerlas.

### Comparación de conversaciones completas

| Negocio y versión | Previstos | No aplican | No medidos | OK 1.er intento | OK tras reintento | Fallos finales | Artefacto |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Alicia, referencia (bd7a6da) | 44 | 1 | 0 | 41 | 1 | **1 crítico** (recalificado) | ref_banco.json |
| Alicia, candidato (112b26c) | 44 | 1 | 0 | **42** | 1 | **0** | banco_g.json |
| Segundo negocio (metareview, conversacional en copia), referencia (bd7a6da) | 44 | 28 | 0 | 16 | 0 | 0 | ref_meta_conv.json |
| Segundo negocio (metareview, conversacional en copia), candidato (ae7d9ff) | 44 | 28 | 0 | **16** | 0 | **0** | meta_conv2.json |
| Segundo negocio (metareview, config real guiada), candidato (ae7d9ff) | 44 | 28 | 0 | 12 | 0 | 4 (ver abajo) | meta_guiado2.json |

Nota del instrumento (leída en la referencia): `dice-que-si-y-acaba-en-cita` solo exigía «Resumen
de tu cita». En la referencia el reintento aprobó con un resumen de «Acido lactico bio premium
corto, 1 h 30 min, fianza 50 €» a nombre de «clienta» (le eligió la técnica a quien no la tenía
clara y le inventó el nombre); el primer intento acabó pidiendo una foto. Criterio endurecido en
00a7726 (en la última respuesta no puede haber técnica ni «clienta») y recalificados sin volver a medir
todos los informes guardados: ninguna tirada del candidato cambia; la referencia pasa a fallo
crítico. `recomienda-ante-un-problema` necesita reintento en ambos. En el segundo negocio
(conversacional) referencia y candidato empatan en los 16 casos genéricos: la diferencia medible
está en el salón. La referencia de Alicia usó el instrumento de d8c5907, el mismo del banco del
candidato en 112b26c; la de metareview, el de ae7d9ff, el mismo de su medida del candidato.

Otras mediciones del candidato:

| Medición | SHA | Resultado |
| --- | --- | --- |
| Suite completa | 112b26c | 2541 passed, 1 skipped (22 min 47 s) |
| Humo (5 recorridos) | d8c5907 (código 112b26c) | 5/5 |
| `dice-que-si-y-acaba-en-cita` ×6 | e197dee y 6bed2f1 | 6/6 al 1.er intento en ambos (1fe7a3e: 0/6) |
| `cambiar-la-hora-de-verdad` ×6 | 6bed2f1 y 112b26c | 6/6 al 1.er intento; una cita viva movida, leído en las copias |
| Banco completo Alicia | 5e9f8d7 / 6bed2f1 / 112b26c | 41+2 / 41+2 / 42+1, 0 fallos |

Segundo negocio: `metareview` (tenant de la revisión de Meta; varios centros, sin reglas, sin
teléfono publicado, precios visibles, Q&A genérica). Es el único negocio con booking distinto de
Alicia; `van` es un clon antiguo del salón. Su config real es guiada (listas y botones): el banco
escribe texto libre y no pulsa botones, así que la medición representativa del agente se hizo con
`booking.estilo=conversacional` SOLO en una copia de la config. Sus datos RAG se copiaron del
servidor en solo lectura (información pública del negocio). 28 casos no aplican por pedir el
catálogo o las políticas del salón (condiciones `solo_si` sobre sus datos).

Guiado real, 4 fallos leídos: 3 son clientas que escriben en vez de pulsar (elegir centro,
confirmar la cancelación, pedir otro hueco): límite del instrumento y hueco real del modo guiado;
1 es contenido erróneo (a «me quiero hacer la manicura» responde «no podemos realizar servicios
como la manicura los domingos», como si la hicieran).

### Fallos encontrados y arreglados hoy (todos con test rojo sin el arreglo)

- Crítico del salón (quien no sabe qué alisado quiere): oferta repetida no contaba, «sí» escrito no
  aceptaba, «a las 15» sin huecos se perdía, el freno del precio frenaba la propia valoración, una
  pregunta de precio de otro día contaba, el nombre «me llamo…» se guardaba entero
  (3a899f8, 1fe7a3e, 197afb0, e197dee).
- **Cancelar una cita que nadie pidió anular** (la clienta se quedaba sin cita) — 6bed2f1.
- **«He reprogramado» sin mover nada** (misma fecha, hora y servicio escrito sin tildes) — 112b26c.
- Instrumento: el banco mide un segundo negocio sin perder la comparabilidad de Alicia (5f5e10c);
  sin datos RAG locales el banco no mide en vez de inventar fallos (ae7d9ff).

### Pendiente de producto (no arreglado, sin efecto en la agenda salvo que se diga)

- A «se me cae mucho el pelo» recomienda alisados/color (Alicia; también en producción).
- Recitar horas de un día que no ha elegido (`pregunta-el-dia-en-vez-de-recitar`, a veces).
- Modo guiado: respuestas escritas a listas/botones no se entienden (reserva, cancelar, mover).
- Chat genérico: la manicura inexistente se contesta como si se hiciera.
- Frenos que saltan sin motivo: `dijo_que_hay_cita_sin_haberla` con la cita existente; en
  metareview, al dar el nombre, «la sesión estándar no cubre lo que necesitas».
- Política: cancelar por teléfono verificado en el primer mensaje, sin preguntar cuál ni
  confirmar (metareview). Revisar si debe confirmar antes.
- Coste/latencia: `se_acabaron_las_vueltas` en los dos primeros turnos al reprogramar.
- `whatsapp._ya_se_le_dijo` mira 8 respuestas sin corte de tiempo (solo añade un remate).
- Copia de producción con 64 sesiones de teléfonos del banco del 22-ago: primeros intentos de
  mediciones anteriores pueden estar contaminados (desde e197dee lo de otro día no cuenta).

### Puertas de aceptación

| Recorrido | Evidencia de hoy | Pendiente |
| --- | --- | --- |
| Crear y aceptar explícitamente | Crítico 6/6; `reserva-completa-de-verdad` OK en Alicia y metareview (cita creada leída en la copia) | Confirmación con el botón real de Meta |
| Cancelar/reprogramar | Banco + 6/6 reprogramar; freno de cancelar sin pedir; reprogramar a lo mismo rechazado | Política de confirmar antes de cancelar |
| Cambios del portal | Tests deterministas | Cambio real a mitad de conversación con modelo: NO MEDIDO |
| Aislamiento de negocio | Mismo banco en dos negocios con políticas distintas | — |
| Reinicio/repetición | Tests de estado persistido | NO MEDIDO con modelo |
| Recordatorios | Plantilla `vantelia_recordatorio_cita` PENDIENTE en Meta | Envío real |
| Revisión | Astra revisó 8ca6088 (en su rama); Claude revisó 8ca6088 y corrigió el nombre | Revisión del SHA final por otro agente |

Límites: un día de calendario, una copia, un modelo; seis tiradas no fijan una tasa; WhatsApp real
de Meta no probado; el segundo negocio es un tenant de demostración medido en modo conversacional
en copia. El despliegue y la regla de orientación de Alicia en producción requieren orden de Pablo.

## Referencias

- Último candidato medido: 2cb8a029, suite roja (2442 passed, 1 skipped, 1 failed),
  fin 13-sep 03:23:06.385 +02:00. Único fallo:
  test_banco_sin_meta::test_instalar_captura_cierra_la_salida_de_payload,
  en contraste frente a c9f19e6. No se pidió revisión exacta nueva.
- Antecedente de3d6d0: 2401 passed, 1 skipped, 1 failed documental; c4d4f6a
  corrige arquitectura/mapa con 5 dirigidos, sin modificar la suite histórica.
- Antecesor local: 7ab7775, 2297 passed y 1 skipped; revisión pendiente.
- Hijo actual: astra/condiciones-confirmadas, arnés v2 c9f19e6 revisado; términos
  en 6c3ad4f con 112 dirigidos verdes (126,70 s) y revisión OK. 68c1fac añade
  recuperación de checkout con clave persistida; 23 dirigidos de condiciones y
  dos regresiones checkout/Bizum verdes. Sin suite nueva del hijo. Base formulario99fdaf1, UI23139ca,
  mapa c4d4f6a y fixtures891a730 medidos en 2cb8a029.
- Referencia anterior con modelo real: pendiente de identificar SHA y artefactos.
- Datos: solo copias saneadas autorizadas. No usar por defecto la BD del negocio.
- Mantener separados los casos no aplicables y los que no se pudieron medir.

## Comparación de conversaciones completas

| Negocio y versión | Previstos | No aplican | No medidos | OK primer intento | OK tras reintento | Fallos finales | Artefacto |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Alicia, referencia | pendiente | pendiente | pendiente | pendiente | pendiente | pendiente | no recibido |
| Alicia, candidato | pendiente | pendiente | pendiente | pendiente | pendiente | pendiente | no ejecutado |
| Segundo negocio, referencia | pendiente | pendiente | pendiente | pendiente | pendiente | pendiente | no identificado |
| Segundo negocio, candidato | pendiente | pendiente | pendiente | pendiente | pendiente | pendiente | no ejecutado |

El denominador del éxito inicial es `primer_intento_medido`. Si falla la
preparación del reintento, el primer fallo sigue contado aunque el caso completo
quede no medido. Publicar además el total previsto, los no aplicables y todos los
no medidos con motivo; nunca convertirlos en éxitos. Separar fallos
críticos/importantes/deseables y conservar cada intento,
también el fallido anterior a un reintento que pasa. El resultado final se apoya
en el efecto de agenda y estado, no solo en lo que redacta el asistente.

Para comparar, guardar SHA de producto e instrumento, modelo/configuración sin
credenciales, hash de copia y catálogo/configuración relevantes, fechas resueltas
y resultados completos por caso. Restaurar la misma copia inicial por tirada;
si cambian calendario, reglas o modelo, indicar que no son condiciones iguales.
Las políticas distintas entre negocios son deliberadas; deben permanecer iguales
entre el antes y el después de cada negocio.

Instrumento disponible en 44ac6de: `evaluar_asistente.py --guardar <informe.json>`
conserva intentos completos, resultados iniciales y reintentos, fechas y estado
incompleto. Comprueba escritura antes de preparar la BD y guarda atómicamente
después de cada intento/caso. SHA/árbol sucio y ficha resumida no sustituyen el
modelo exacto ni el hash de copia/configuración necesarios para comparar. El JSON
no anonimiza respuestas: usar únicamente datos de prueba saneados autorizados.

## Puertas de aceptación

| Recorrido | Prueba local | Evidencia real pendiente |
| --- | --- | --- |
| Crear y aceptar explícitamente | Cubierto en candidato 7ab7775 | Conversación y fila creada, primer intento y reintentos |
| Cancelar/reprogramar | ca8e626 cierra los dos tests de contrato de 2235d25: 34 dirigidos verdes; pendiente nueva suite | Efecto exacto, sin cita duplicada ni acción por respuesta ambigua |
| Cambios del portal | Invalidación/revalidación cubiertas localmente | Cambiar regla, servicio, horario o vacaciones durante conversación |
| Aislamiento de negocio | Pruebas deterministas por tenant | Mismo banco con segundo negocio y políticas diferentes |
| Reinicio/repetición | Estado y creación recuperable probados | Resto de gestión, entregas y resultado incierto |
| Recordatorios | Suite exacta de3d6d0 sin xfail y único rojo documental corregido en c4d4f6a; no es suite global verde | Plantilla, envío autorizado, cancelación/reprogramación, duplicación |
| Agenda visual | QA exacta 2cb8a029 exit0: etiqueta45=BD45, precio18, geometría de cuartos y recorrido completo; captura revisada | Tipografía externa no medida (Fonts bloqueado); no acredita cambios posteriores |
| Revisión | Solicitada sobre 7ab7775 | OK del SHA exacto del candidato final |

No se activa una regla de diagnóstico/foto para Alicia sin configuración acordada.
Ese bloqueo de producto se aísla; no autoriza a elegir un servicio por la clienta.
El despliegue y el push requieren una orden posterior de Pablo incluso si se
cumplen todas las puertas anteriores.

Trabajo del hijo aún sin aceptación global: transporte c1db689 revisado con 29
pruebas propias y 56 relacionadas (selecciones solapadas); no acredita entrega.
Ledger: 66 dirigidas y 2 de plantilla previas, 16 finales verdes y revisión local
OK en b5fa459; suite integrada de3d6d0 con único rojo documental. Aceptación y evento del tope se guardan
juntos; queda pendiente reconciliación, cupo entre citas distintas, ventana de
cambio durante la red y fallback interno de email. Protección de copia/informe
09aebfc revisada, 27 dirigidas verdes;
rechaza alias de DB/WAL/SHM antes de cualquier escritura. Guardar un ID de Meta o una
fila de cita no equivale a recibir el mensaje en el teléfono.

Los instrumentos tampoco cierran fase 5: 2533fe9 corrige el ID legacy y exige
acción explícita, con efecto de agenda sintético comprobado. Pero opciones()
depende de la API/estado de propuesta del producto y filtra botones emitidos
obsoletos antes de probar su rechazo productivo. Compatibilidad con una baseline
anterior sin esa API/protocolo **NO DEMOSTRADA**. Próxima rama: observar transporte
explícito y efectos, dejando al producto validar autorización; sin clicks
deducidos del texto. El caso crítico del banco que acepta «Resumen» o
«Confirmamos» sigue sin acreditar creación final real. No hay comparación real
antes/después; compartir versión del instrumento no basta para acreditarla.

Otro próximo bloque: propuesta/huella no sellan términos efectivos de
duración/precio/fianza/política. Cambio entre oferta y click identificado por
lectura; pendiente regresión antes y preparación compartida, sin doble cálculo.

La agenda ya implementa el eje y las marcas de quince minutos: coordinación
verificó `app_ui/index.html`, `CD_AXIS_STEP=15` (8479), ticks laterales
(8784–8786), líneas del cuerpo (8810) y CSS `.cd-tick`/`.hour` (812–813),
con escala común de 2,2 px/min. QA externa exacta de3d6d0 verificó 37 marcas,
tres cuartos interiores y alineación con horas/líneas (02:36:26–02:37:51, exit 0,
árbol limpio antes/después; portal-ledger.*). Fonts bloqueado con CSS vacío:
tipografía de sistema. Reveló etiqueta20 sobre bloque/BD45; UI23139ca la corrige
usando cdDur. Nueva QA exacta 2cb8a029, 03:05:16–03:06:56 Europe/Madrid,
exit 0 y SHA/árbol limpios antes/después: etiqueta45 coincide con BD45 y mantiene
precio18; geometría y recorrido completo pasan. Captura inspeccionada también
por coordinación. Evidencia portal-formularios.* externa, Fonts bloqueado con
CSS vacío. Sin modelo/Meta ni suite repetida. La captura anterior no acredita
el arreglo; esta ejecución nueva sí lo verifica. No repetir las QA verdes.

## Recorrido visual aislado: 13-sep, 01:22 Europe/Madrid

SHA antes/después: 7ab7775. Un primer intento terminó durante la importación de
API por una descarga redundante de NLTK; no abrió navegador. El único reintento
de arranque validó el recurso ya instalado, mantuvo deshabilitadas las descargas
y terminó con exit 1 en `scripts/qa_portal_browser.py:290`.

Pasaron los pasos anteriores: acceso, resumen, crear/editar servicio de retención,
dos centros, Ventas, Informes con filtros y gráficos, modal, responsive de 390 px,
abrir Nueva cita y autocompletado inicial. El guion espera franjas del día actual
antes de avanzar a la cita sembrada el lunes; ese día actual es domingo y el
tenant temporal cierra los domingos. El código del portal muestra el cierre.
No acredita regresión del producto ni aceptación visual completa. No se alcanzan
selección de hora, arrastre, persistencia de duración ni comprobación final de
errores de consola. No se relanzó para sustituir este fallo por un verde.

Artefactos fuera del repo: `C:/Users/pabli/.codex/vantelia-coordination/portal-7ab7775.log`
y `.result.json` (arranque), `portal-7ab7775.attempt2.log` y `.result.json` (navegador).
El lanzador `.run.py` conserva comando y aislamiento: entorno sin credenciales,
dotenv desactivado en ambos procesos, conexiones Python solo a loopback, tenant,
datos, almacenamiento y configuración temporales. No se tocaron producción ni
el código del candidato estable.

## Recordatorios: inspección inicial y reproducción posterior

El inventario siguiente conserva lo observado antes de ejecutar las regresiones;
la actualización posterior indica qué se reprodujo y qué sigue pendiente.

- **Importante — envío omitido más envío fallido se registra como enviado.**
  `backend/booking.py`, `_send_booking_reminder_by_kind`, condición
  `if sent_channels or skipped_channels` (línea 4222 en la rama de
  gestión). Caso: email y WhatsApp activos, cita sin email y WhatsApp devuelve
  False. Queda email omitido y WA fallido, pero se rellena `reminder_24h_sent_at`
  sin un envío y no se reintenta. Falta regresión determinista; los tests leídos
  de plantillas/cancelación previa no cubren esa combinación.
- **Importante — dos ejecutores o reinicio pueden repetir el aviso.**
  `backend/booking.py`, `_run_booking_reminders` (línea 5230), lee
  timestamps antes del I/O sin reclamar una operación de envío. Caso: worker
  automático y endpoint admin leen ambos `reminder_24h_sent_at` vacío; ambos
  envían antes de marcarlo. También hay ventana entre aceptación externa y
  persistencia local ante reinicio. Falta prueba con barrera/concurrencia y
  resultado externo desconocido. No se afirma que haya ocurrido en producción.

Actualización 13-sep 01:42 Europe/Madrid: **ambos casos reproducidos** en
astra/recordatorios-fiables, base 44ac6de. Tres regresiones fallan antes del arreglo
de contabilidad (rechazo, timeout y caller sin excepción). La corrección conserva
pendiente cuando ningún canal acepta y al menos uno falla; 31 pruebas verdes y
un xfail estricto, selección dirigida. Revisión local OK; ff59b06 integrado en
a83021c. Pendiente suite integrada y revisión de Claude.

El xfail reproduce dos ejecutores enviando antes de registrar la marca; **esa
carrera no está corregida**. Siguiente: reclamación duradera, recuperación y
resultado desconocido por canal. No acredita entrega de Meta ni ausencia global
de duplicación. Logs `recordatorios-falso-enviado-rojo.log` y `-verde.log` en la
carpeta externa de coordinación.

Actualización 14-sep-2026 (Claude, `1458540` en `claude/candidato`): la reclamación
duradera por canal (`notice_deliveries`) dejaba un aviso bloqueado PARA SIEMPRE en dos
casos: un fallo de email o SMS se guardaba como «desconocido» (el adaptador no distingue
rechazo de respuesta perdida) y un WhatsApp dudoso impedía también el respaldo por email.
Decisión de Pablo, «reintentar sin duplicar WhatsApp»: el fallo de email/SMS queda
«rechazado», se reintenta en la siguiente vuelta y pasa al siguiente canal; un WhatsApp
dudoso o un «enviando» colgado no se repiten por su canal, pero pasados 30 min sale el
siguiente. Riesgo aceptado: rara vez un email repetido. Evidencia: 5 regresiones rojas
antes del arreglo y 2 controles de frontera (29 min), suites de avisos 52 verdes, suite
completa 2702 passed y 1 skipped. Sigue sin medir con Meta real: WhatsApp de Alicia sin
conectar.

Revisión adversarial de Codex a `1458540` (14-sep, 12:00): dos fallos altos, confirmados con
test rojo y corregidos en `549a1e3`. (1) La banda del recordatorio (45 min) se acababa antes de
la gracia de 30 min y el respaldo no salía nunca; un aviso ya empezado conserva la banda 75 min
más. (2) Un ejecutor parado más de la gracia mandaba el WhatsApp después del email del
respaldo; ahora pierde su turno y se comprueba justo antes de enviar. Suite completa de
`549a1e3`: 2713 passed, 1 skipped. Una segunda revisión encontró la carrera al límite de la
gracia y el reenvío manual sin protección, corregidos en `0b12b3c`: el turno se renueva al
enviar y, por decisión de Pablo, el panel avisa y pregunta antes de reenviar un WhatsApp dudoso.
Suite de `0b12b3c`: 2719 passed, 1 skipped. Una tercera revisión vio que el aviso no saltaba tras
la confirmación de pago ni si en medio se reenviaba solo por email: corregido en `3e05b96`.
Suite de `3e05b96`: 2722 passed, 1 skipped. La última ronda (decisión de Pablo) vio que una
entrega anterior tapaba un WhatsApp automático dudoso posterior: corregido en `e44886b`.

## QA corregida de gestión: 13-sep, 01:27 Europe/Madrid

Una nueva ejecución justificada tras corregir la fecha del instrumento termina
**exit 0** (01:25:59–01:27:14). Base f317e06 antes/después, con cambios sin commit
y otras implementaciones en curso: **no es validación de un SHA exacto estable**.
Conservados `portal-gestion.before.patch` y `.after.patch`, además del `.log`,
`.result.json` y `.run.py` en la carpeta externa de coordinación. Los diffs
difieren por trabajo concurrente; no atribuir este verde a la totalidad del árbol.

Pasa la aserción nueva de que Nueva cita usa el día abierto sembrado. El guion
completo pasa acceso, servicios/centros, Ventas, Informes/filtros/gráficos,
responsive móvil, búsqueda de servicio, conservar hora al elegir servicio,
legibilidad de cita corta y arrastre sin abrir el panel. Comprueba respuesta de
guardado 200, mayor altura visual y duración real guardada **45 min** frente a
20 min iniciales; también termina sin los errores de consola capturados.
No se repite después del verde. El fallo previo del domingo se conserva.
No mide modelo, Meta, canales reales ni la aceptación de cancelación nueva.
