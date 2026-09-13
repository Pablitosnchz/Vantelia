# Evidencia de aceptación del candidato IA

Estado: **evidencia completa del 13-sep; pendiente de orden de despliegue de Pablo** (sección siguiente). Lo anterior se conserva como historial. Un resultado local verde no acredita mejora con el modelo
ni funcionamiento de Meta en un número conectado. Mantener este informe junto
al plan y al registro horario; no completar casillas por inferencia.

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
