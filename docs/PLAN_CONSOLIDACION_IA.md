# Plan de consolidación: portal, políticas y conversación

Encargo de Pablo, 12-sep-2026. Astra coordina; Claude revisa y mide el modelo.
Contrato obligatorio: `NORMAS_AGENTE_IA.md`. No está completado este plan.

## Candidato nocturno integrado (13-sep)

Situación vigente: 2cb8a029 terminó suite exacta a las 03:23:06.385 +02:00,
exit 1, 2442 passed, 1 skipped, 1 failed. Único rojo en
test_banco_sin_meta::test_instalar_captura_cierra_la_salida_de_payload. El
arnés v2 c9f19e6 elimina la delegación que lo causaba y el dirigido pasa con
red bloqueada; falta medir una nueva suite exacta del hijo.
En astra/condiciones-confirmadas, 6c3ad4f sella términos con 112 dirigidos
verdes (126,70 s) y revisión de código OK. 68c1fac persiste una clave de
idempotencia antes de crear checkout: tras respuesta Stripe perdida se reutiliza
la misma sesión; formato histórico sin clave queda para reconciliación manual.
23 dirigidos de condiciones y dos de checkout/Bizum verdes, sin Stripe real.
Arnés v2: 28 controles, dos positivos de agenda posteriores a firma estable,
16 del consumidor banco; compatibilidad solo builder/payload de 2235d25 probada
aisladamente, no baseline completa ni medición de mejora con modelo real.

Antecedente: de3d6d0 terminó suite exacta a las 02:52:00.149448 +02:00,
exit 1, 2401 passed, 1 skipped, 1 failed, sin xfail. Único rojo: arquitectura
omite notice_deliveries; c4d4f6a lo documenta con 5 dirigidos verdes, sin repetir
suite congelada. No se pidió revisión formal. El hijo astra/formularios-confirmados
incluye formulario 99fdaf1 (66 dirigidos), arnés 2533fe9 (23 dirigidos), UI 23139ca
y mapa revisados. Cinco fixtures heredadas guardadas en 891a730 tienen 38 dirigidos
y revisión OK. Ese hijo se midió como 2cb8a029 con el resultado indicado arriba;
su árbol permanece intacto. El trabajo nuevo vive en condiciones-confirmadas.

Código integrado en a83021c y medido con relevo en 2235d25: suite terminada el
13-sep a las 02:15:01 Europe/Madrid, exit 1, 2347 passed, 1 skipped, 1 xfailed y
dos fallos de cancelación. No se pidió revisión automática. Las cifras dirigidas
que siguen son antecedentes y no convierten esa suite en verde:

- 9ede4f9 migra cancelación guiada y de botones WhatsApp a propuesta persistida,
  aceptación con identidad y snapshot validado por el núcleo. Resultado desconocido
  se conserva al volver al menú; una protección común precede los desvíos al agente.
  Último cierre dirigido: 57 verdes; revisión local independiente OK.
- 44ac6de/f4ad515 guardan evidencia del banco por intento, incluso si se interrumpe
  un reintento; precondiciones no medidas y denominadores separados. Destino
  comprobado antes de medir; no puede reemplazar la BD origen/copia. No proporciona
  por sí solo configuración completa, modelo ni copia saneada comparable.
- e49f29d corrige dependencia del domingo en QA del portal. Recorrido completo
  verde, incluida duración visual y persistida; árbol concurrente, no SHA exacto.
- ff59b06 evita marcar enviado si email se omite y WhatsApp falla sin aceptación.
  31 dirigidos verdes, un xfail estricto de duplicación entre ejecutores pendiente.

No se cierra fase 4: registro duradero y generación están en b5fa459, formulario
nativo en 99fdaf1 y recuperación de checkout en 68c1fac; faltan validación
integrada del hijo, reconciliación operativa y gestión conversacional/otros canales.
La recuperación de cancelación sigue limitada al TTL y no hace atómico el proveedor
con la BD. Fase 5 exige revisión de Claude del candidato exacto y banco real
comparable de Alicia y otro negocio. La decisión foto/diagnóstico permanece aislada.
Siguiente entrega independiente: términos efectivos aceptados y corrección del
límite de medida del arnés, en otra rama mientras se valida este candidato.

En astra/entregas-recordatorios, transporte c1db689 y seguridad de copia/informe
09aebfc revisados (27 dirigidas finales para DB/WAL/SHM y alias). Ledger b5fa459
revisado, 16 dirigidas finales verdes: aceptación y auditoría que
alimenta el tope ahora comparten transacción. El xfail se retiró solo
en este hijo para sus regresiones dirigidas, no en el candidato 2235d25 medido.

No incluye reconciliación operativa de incertidumbre, exclusión del cupo entre
citas diferentes ni el fallback interno de email. La última relectura no vuelve
atómico un cambio de cita durante la red. Son límites pendientes, no nuevas
garantías derivadas de la reclamación por aviso.

Antes de fase 5, terminar instrumentos sin cambiar casos de calendario:
2533fe9 usa acción explícita e ID emitido por builder real, pero filtra la oferta
por API/estado actual antes de entregar el click al producto. Eso impide medir
su rechazo de botones obsoletos y no demuestra compatibilidad con una baseline
anterior sin API/UUID. Próxima rama: transportar acciones explícitas emitidas y
observar efectos, dejando al producto validar estado/autorización. No deducir
consentimiento del texto. El banco crítico que acepta «Resumen» o «Confirmamos»
sigue sin medir creación final real; no hay comparación nueva ni recibos Meta.

En esa rama, reproducir cambio de duración/precio/fianza/política entre oferta
y aceptación. Sellar términos efectivos desde preparación compartida y evitar
que el guardado vuelva a calcularlos; recuperación de operación ya aceptada
debe conservar identidad y condiciones. De momento solo existe evidencia por
trazado, no regresión ejecutada ni arreglo de esta brecha preexistente.

Agenda: geometría verificada en QA exacta de3d6d0, 37 ticks cada 15 min/33 px,
alineados con líneas y horas visibles; tipografía de sistema por bloqueo de
Google Fonts. La captura reveló etiqueta 20 min frente a bloque/BD 45; UI23139ca
corrige con cdDur y prueba Node roja/verde. QA exacta 2cb8a029 terminada a las
03:06:56 Europe/Madrid, exit0, SHA/árbol limpio antes/después: etiqueta45=BD45,
precio18, cuartos/horas y recorrido completo, captura revisada por coordinación.
Artefactos portal-formularios.*; Fonts vacío por aislamiento, sin modelo/Meta.
No atribuir ese arreglo a la captura antigua ni repetir ninguna QA verde.

## Corte verificable: 13-sep, 01:15 Europe/Madrid

7ab7775: suite completa terminada, **2297 passed, 1 skipped**, duración 18 min 55 s; fin 13-sep 01:04 Europe/Madrid;
revisión exacta solicitada automáticamente, pendiente por cuota de Claude.
Se conserva en su worktree. Avance nuevo en astra/gestion-confirmada.
Los resultados parciales y esperas de secciones anteriores son históricos.

| Fase | Situación del candidato 7ab7775 | Puerta que falta |
| --- | --- | --- |
| 0 Referencia | Instrumentos de calendario integrados; evidencia real por inventariar | Referencia completa comparable y trazable |
| 1 Portal | Invalidación por tenant y revalidación operativa probadas localmente | Aceptación real y recorrido visual autenticado |
| 2 Estado | Propuestas, aceptación, persistencia y CAS implementados | Extender gestión y canales sin autoridades paralelas |
| 3 Políticas | Editor Q&A y orientación explícita; rescate Q&A retirado | Decisión particular foto/diagnóstico aislada; contraste de dos negocios |
| 4 Canales | Creación por resumen WhatsApp recuperable y servicio retirado | Cancelación/reprogramación, formularios, entregas y reconciliación |
| 5 Aceptación | Suite completa verde sobre SHA exacto | Revisión, banco real, recordatorios y prueba de mejora |

Siguiente rebanada: confirmación de cancelación WhatsApp con identidad de la
propuesta, aceptación persistida, revalidación y respuestas solo tras resultado
comprobado. No modifica políticas de Alicia. Después se decidirá el siguiente
bloque según regresiones y revisión, sin esperar a Claude para tareas independientes.
Registro de cambios y pruebas con hora: `REGISTRO_CONSOLIDACION.md`.

QA visual 13-sep 01:22 sobre 7ab7775: recorrido parcial, exit 1. El instrumento
espera franjas en domingo cerrado antes de avanzar al lunes; la agenda restante
(selección de hora, arrastre y duración persistida) queda NO MEDIDA. Acceso,
servicios, centros, Ventas, Informes y responsive sí se recorrieron. Corregir la
fecha explícita del instrumento antes de una nueva ejecución; no usar este
resultado para cerrar fase 1 o aceptación. Detalle en ACEPTACION_CANDIDATO_IA.md.

## Integración y desbloqueo de suite (13-sep)

Entrega ee939c8 integrada en 52acab5 sin duplicar validadores: continuidad WhatsApp
con servicio retirado y alternativas de voz, 57 dirigidos verdes. 2e3db40 impide
que el estado vuelva a ordenar crear ese servicio después del rechazo, 61 dirigidos
verdes (grupos solapados) y regresión roja previa. Widget y reprogramación ya estaban
cubiertos en da0ca70 y se volvieron a validar.

Los cinco fallos de demos fueron reproducidos por orden de fixtures: API de sesión
antigua frente a backend recargado por un módulo anterior. Fichero aislado: 21 verdes;
orden reducido: cinco rojos exactos y dos controles verdes. Fixture local al módulo:
23 verdes repitiendo el orden con todo el fichero. No se modifica producción ni se
elimina ninguna aserción. Se lanza una suite completa estable; revisión exacta solo
tras éxito. Consultar el resultado real en ESTADO_ACTUAL y su registro de ejecución.

## Estado integrado al 13-sep: WhatsApp recupera la creación

Candidato descendiente de 4ed33c7 en `astra/whatsapp-recuperable`. Incorpora las
correcciones de la revisión c22cc42, persistencia, identidad del resumen y enlace
con el registro de operaciones del núcleo. Los apartados posteriores documentan
hitos históricos; sus suites y solicitudes de revisión no aprueban este candidato.

WhatsApp conserva clave y huella de la petición (incluida la profesional resuelta)
antes de ejecutar. Tras perder la respuesta, consulta el resultado real sin buscar
otro hueco ni repetir creación, proveedor, bono o notificaciones accesorias. Un
resultado desconocido queda pendiente de comprobación; no acredita cita creada.
El resumen cambiado durante una consulta invalida la ejecución antigua. Un fallo
de envío no marca terminada la confirmación. Se distingue cita confirmada,
cancelada y pendiente de pago; esta última sigue sin recibir número de reserva.

Validación dirigida inicial: cuatro regresiones rojas antes del enlace; 66 pruebas
de integración verdes. Cierre y mutación registrados en ESTADO_ACTUAL. Falta la
suite completa después de resolver los cinco fallos de demos encargados a Claude,
revisión del SHA exacto y banco real comparable Alicia/otro negocio. Las seis
revisiones de antecesores retiradas por sustitución no equivalen a aprobaciones.

Límites de esta fase: recuperación vinculada a la vida del estado persistido;
no hay reconciliación automática con el proveedor ni bandeja de salida duradera
para pagos y entregas accesorias. Una caída antes de reclamar la operación no se
reejecuta automáticamente. Formularios nativos, cancelación y reprogramación aún
necesitan migrar sus confirmaciones; no se afirma idempotencia global entre canales.
Recordatorios reales y decisión de foto/diagnóstico continúan pendientes.

## Retirada del rescate Q&A (13-sep, validación dirigida)

Se elimina `_hay_que_cogerle_la_valoracion` y su segunda búsqueda que sustituía el
servicio cuando faltaba una política de orientación. La nota de aclaración deja
de consultar Q&A/catálogo, de imponer una técnica y de prometer cambios posteriores
en la cita. Su texto es general para cualquier negocio. La oferta configurada
sigue pasando por la propuesta y la aceptación compartidas; una Q&A informativa
no selecciona la valoración. No se activa ninguna regla particular para Alicia.

Antes del cambio fallan tres recorridos deterministas reales de `responder` con
Q&A sin política (duda de técnica/talla). Las pruebas antiguas que exigían imponer
valoración a la tercera pregunta se sustituyen por esos recorridos, conservando
las de petición directa, aceptación y rechazo/obligatoriedad. Se retiran pruebas
que solo comprobaban el nombre del helper dentro del código fuente. Validación:
102 dirigidos verdes en d42e964; no acredita mejora medida con modelo real.

Sin política ni elección de la clienta, el servicio sigue pendiente. La salida
concreta para Alicia (foto, diagnóstico u otra) requiere una regla acordada; el
código no puede decidirla para que el banco cierre artificialmente la cita.

## Persistencia del estado (candidato de Astra)

Rama astra/persistencia-conversacion, basada en 44dddf8. SQLite conserva Estado
por tenant/canal/identidad con formato, caducidad y versión de escritura. Se
publican juntas aceptación y selección; otra versión pierde la carrera y recarga.
WhatsApp guarda antes del envío y después del acuse, y recupera el modo del agente
al perder su caché visual. Una gestión terminada no se reabre. Se retira la
aceptación deducida de una pregunta antigua del bot, además del diccionario como
fuente autoritativa. Snapshots/lápidas caducados tienen limpieza acotada y borrar
un tenant limpia sus filas sin tocar al vecino.

Evidencia: tres recuperaciones entre procesos y tres respuestas ambiguas rojas
antes del cambio. La carrera aceptación/rechazo falla al retirar la comparación
de revisión. 181 dirigidos de integración, 52 de cierre y 17 de primitivas aisladas verdes
(grupos con solapamiento). El descendiente integrado 530ae40 terminó con 2256
correctos y 1 omitido; revisión exacta pedida automáticamente.
Referencia 12d2614: 2226 correctos y 1 omitido. 44dddf8 terminó con 2231 correctos, 1 omitido y revisión exacta pedida.

Siguiente puerta: operación de agenda con identidad persistida y resultado
recuperable. Hoy una caída entre crear la cita y guardar Estado no está resuelta
por esta fase. Tampoco se afirma haber migrado todo WAFlowState, voz o widget,
ni eliminado los demás correctores. No sustituye el banco real multinegocio.

## Revalidación y recuperación (en curso)

Base de agenda/recordatorios 6e040e1: suite 2221 correctos y 1 omitido, revisión
exacta en cola. Orientación 12d2614 en suite completa. Rama hija de recuperación:
se revalida también una aceptación anterior antes de reutilizarla; tres pruebas
fallaron sin la corrección (caducidad, cambio de política y cambio de catálogo).
La validación vive en booking y se comparte con la transición de aceptación y el envío de la oferta por WhatsApp. Cuarto caso rojo: se enviaban botones de una propuesta ya caducada. 64 dirigidos verdes y, tras adaptar el envío, otros 19 verdes de los recorridos afectados. Suite completa y revisión exacta pendientes.

La persistencia no está resuelta: diseño y puertas concretas en
`DISENO_RECUPERACION_ESTADO.md`. No confundir la revalidación de un objeto presente
con recuperar una conversación tras reiniciar ni con resolver carreras de workers.

## Candidato de orientación declarada (12-sep, Astra)

Base integrada: 6e040e1, que incorpora servicios retirados, calendario de medidas,
apellidos por tenant, eje de agenda de quince minutos y estado de recordatorios.
La orientación usa una intención configurable en Q&A y las transiciones de
propuesta existentes. Sustituye el rescate inferido y la nota de repetición solo
cuando existe esta política explícita. No se habilita ni se inventa para Alicia.

60 pruebas dirigidas verdes: oferta sin selección, aceptación tras envío,
repetición con el mismo id, caducidad, cambio de regla y política de foto.
Regresiones demostradas: repetir creaba otro id antes del arreglo; desactivar la
vía nueva vuelve a seleccionar diagnóstico. Esto no mide al modelo real.
Pendiente suite completa y revisión del candidato exacto. Estado aún en memoria:
esta fase no acredita continuidad ni exclusión mutua entre workers.

## Actualización tras asumir los encargos de Claude

Astra ha implementado las piezas pendientes de servicio retirado en creación y
reprogramación y el cierre del calendario/métricas. Recorridos reales de WhatsApp,
voz y endpoint widget probados, sin sustituir núcleo ni resolución de profesional.
Pendiente suite completa y revisión del SHA integrado, después medición real.
Estos arreglos no completan la encapsulación de políticas ni la recuperación
tras reinicios; no se presenta el candidato como final para Alicia.

## Estado comprobado al retomar (12-sep)

El objetivo sigue pendiente: no hay candidato final aprobado ni evidencia de
fiabilidad suficiente al primer intento. Astra coordina e implementa; Claude
revisa, mide y resuelve encargos aislados. No desplegar sin Pablo.

- Base 6eb8ae5: suite 2152/1 omitido; revisión CAMBIOS. Corregidos aviso de reglas
  inactivas y renuncia compartida (24ff8de). Se cierran progreso por candidatos,
  lecturas por turno y limpieza de Q&A. Falta servicio retirado ANTES de resolver
  profesional, encargado a Claude con pruebas de recorridos reales.
- Propuestas c22cc42: suite 2185/1 omitido. Base corregida integrada hasta 37a0a49;
  nueva validación tras incorporar lo anterior y cambio a servicio retirado al
  reprogramar. El prototipo separa propuesta/aceptación/ejecución para presupuesto;
  aún no sustituye todos los correctores ni garantiza recuperación entre procesos.
- Calendario: e8d6896 corrige ida/vuelta de fechas y ocupación de fixtures;
  37a0a49 convierte rechazo de horizonte en NO MEDIDO. Guiones y denominadores
  encargados a Claude, sin entrega registrada al retomar.
- Sincronía cf2066d: suite 2138/1 omitido, revisión pendiente. CLI de cuenta actual
  comprobado sin registrar PII; no afirmar cambio real entre ambas cuentas.
- Medición 570a201: control 4/6 tiradas, 1/6 al primero, 4/11 conversaciones;
  tratamiento 6/6, 0/6 al primero, 6/12 conversaciones. No acredita cierre fiable.
- Pendiente: políticas restantes de Alicia, retirada de autoridades duplicadas,
  reinicios/reentregas/fallos de proveedor, recordatorios (plantilla y envío real),
  banco comparable de Alicia y otro negocio y revisión del SHA integrado final.

Las cifras de fases históricas de abajo describen sus candidatos originales;
este bloque evita interpretarlas como aprobación del candidato actual.

## Dirección y criterios de operación (12-sep, encargo actualizado de Pablo)

Astra diseña e implementa las fases. Claude queda de auxiliar para mediciones
con el modelo real, revisión, datos saneados y despliegue cuando Pablo lo ordene.
Solo implementa piezas que Astra le encargue explícitamente. Este reparto
sustituye los responsables provisionales indicados más abajo.

Contraste con referencias públicas de ingeniería, consultadas el 12-sep-2026:

- [Anthropic: Building effective agents](https://www.anthropic.com/engineering/building-effective-agents):
  recomienda empezar con patrones simples y aumentar complejidad si mejora los
  resultados medidos. Aplicación a Vantelia: un flujo de gestión compartido;
  ningún nuevo agente corrector por defecto. La flexibilidad está en interpretar
  mensajes; la autorización y ejecución tienen contratos explícitos.
- [Anthropic: Demystifying evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
  y [OpenAI: Agent evals](https://developers.openai.com/api/docs/guides/agent-evals):
  evaluar recorridos y resultados reproducibles. Aplicación: conservar resultado
  de herramientas y estado final, además del texto; distinguir éxito inicial,
  éxito tras reintento y fallo. Una respuesta convincente no acredita una cita.

Estas son decisiones de diseño para nuestro producto, no una certificación ni
una afirmación sobre la arquitectura privada de otras empresas.

Puertas adicionales para dar por operativo el candidato (pendientes de ejecutar):

| Propiedad | Evidencia requerida |
| --- | --- |
| Autorización | Un sí ambiguo, una Q&A informativa o un mensaje no enviado no autorizan cambiar servicio ni crear cita. |
| Reinicios | Al perder estado, recuperar hechos persistidos o pedir confirmación; nunca ejecutar una aceptación deducida de texto antiguo. |
| Repetición y concurrencia | Reentrega del mismo evento y confirmaciones simultáneas no duplican citas ni recordatorios; dos clientes compitiendo por el mismo hueco respetan la capacidad. |
| Cambios del portal | Cambiar horario, vacaciones, servicio o regla entre oferta y confirmación obliga a revalidar; el otro tenant permanece aislado. |
| Fallos externos | Timeout y rechazo de Meta o de una tool no producen éxito falso; distinguir envío aceptado de entrega al destinatario. |
| Recuperación | Tras ambigüedad persistente o fallo, conservar los datos válidos y ofrecer una salida útil; derivación a persona solo con mecanismo real de atención. |
| Operación | Trazas saneadas de transición, regla aplicada, resultado de tool y envío permiten explicar un fallo sin registrar secretos ni datos personales nuevos. |

Medición: referencia y candidato con los mismos casos, calendario resuelto,
configuración y modelo; registrar SHAs, intentos y denominadores. Comparar
creación/cancelación/reprogramación realmente persistida, violaciones de reglas,
abandono/bucles, coste por conversación y latencia. Publicar por separado Alicia
y un segundo negocio. No fijar un porcentaje de fiabilidad con seis ejemplos;
las limitaciones de muestra deben acompañar al resultado.

Cada fase retira el mecanismo que sustituye, añade regresiones de comportamiento
y termina en revisión. No introducir frameworks, llamadas extra al modelo ni una
migración de proveedor sin un problema concreto y una comparación que lo justifique.

## Fase 0 — descubrimiento y referencia (realizada, con huecos explícitos)

Fuentes consultadas: `MAPA_DEL_CODIGO.md` (horarios y decisión del negocio),
`COMO_PIENSA_EL_ASISTENTE.md`, `CAZA_DE_FALLOS.md`, endpoints y cachés siguientes.

APIs existentes que se deben reutilizar:

| Dato | Edición existente | Lectura y patrón |
| --- | --- | --- |
| Q&A | `portal_content.py:204`, `/auth/app/qa` CRUD | `kb_qa`, `rag._maybe_regenerate_info_with_qa`, `intents.preguntas_del_tenant` |
| Políticas | `portal_content.py:520`, `/auth/app/business-rules` CRUD/config | `rules.guardar`, `rules.listar`, `rules.match`, `chat.decision_del_negocio` |
| Horarios | `/auth/schedule`, `/auth/schedule/employee/{employee_id}` | `agenda._update_client_schedule`, `_weekly_schedule_matrix` |
| Vacaciones/bloqueos | `/auth/schedule/blocks` y variante por empleado | `agenda._create_agenda_blocks`, `_blocked_intervals` |
| Servicios | `/auth/services` POST/PATCH/DELETE y listado existente | tabla `services`, `agenda._service_row_to_public`, `_catalog_services` |

No reutilizar `/auth/app/services` como editor estructurado: escribe texto y
desactiva el catálogo antes de sincronizar. No inventar otro CRUD ni otro motor.

Hallazgos comprobados: `intents` cachea familias, preguntas y clasificaciones;
las claves de clasificación no llevan una revisión de configuración. El editor
de reglas ya existe en Q&A (`loadBusinessRules`), pero se oculta cuando está
desactivado y vacío. Falta probar la frescura tras escritura, especialmente entre
workers, y el comportamiento de una propuesta de cita anterior al cambio.

Referencia: `570a201` corrige duda literal y contador; 54 tests dirigidos verdes.
La suite completa tuvo 2114 correctos, 1 omitido y 11 errores al preparar citas
en domingo. La fixture corregida pasa esos 11 casos; falta nueva ejecución total.
Claude tiene pendiente comparación 6+6 con modelo real; no confundir con tests.

## Fase 1 — cambios del portal visibles al agente

Integración en curso: entrega `e6e7ee3`, `e77b074`, `2063655` de Claude integrada.
La revisión de Astra reprodujo una colisión del sello agregado para texto de
igual longitud en el mismo segundo desde otro worker. Se sustituye por SHA-256
del contenido ordenado que consumen las cachés, incluido orden del catálogo.
Coste: leer esas columnas por tenant para comprobar frescura; se conserva la
caché de extracción/clasificación del modelo. No se añade esquema ni TTL de gracia.
51 pruebas dirigidas verdes; suite completa y revisión pendientes.

Responsable propuesto: Claude, rama aislada acordada por sincronía.
Reutilizar CRUD y cachés anteriores. Reproducir primero editar/borrar Q&A y
activar/desactivar/renombrar un servicio después de una consulta cacheada.
Diseñar invalidación o revisión por tenant que funcione entre procesos; no basta
vaciar un diccionario del worker que recibe el POST. Las lecturas de agenda deben
seguir consultando horarios/bloqueos actuales, sin duplicarlos en Q&A.

Aceptación: edición desde API del portal -> siguiente consulta usa datos nuevos;
el otro tenant conserva los suyos. Revalidar antes de ejecutar si una propuesta
se hizo antes de unas vacaciones o de desactivar el servicio. Pruebas negativas
sin acceso cruzado. Conservar permisos y política del mostrador.

**Cerrada (14-sep-2026, Claude).** Las cachés de `intents` comprueban una huella SHA-256 del contenido que
consumen, leída de la BD que comparten los procesos (`intents.py`, `olvidar_tenant`;
`tests/test_cambios_del_panel_se_ven_al_momento.py`). Con modelo real, `scripts/medir_portal_y_reinicio.py`
(vacaciones después de ofrecer el día, hora bloqueada y servicio retirado con el resumen delante, regla apagada
después de ofrecer, reinicio a mitad de reserva y con el resumen delante): 6/6 y 0 no medidos en c8aaad8 y en 5c927dd,
sobre copias de producción. Unas vacaciones de día entero son un día cerrado en el agente, la voz, el chat y el
selector de WhatsApp (ef0d0dc, 45f3d11, 1cdb3f9, 5c927dd).

## Fase 2 — propuestas y aceptación como estado

Responsable: Astra; Claude aporta auditoría y revisión del recorrido actual.
Partir de `reserva.Estado`, `anotar_resultado`, `agent._pide_la_valoracion` y
`_acepta_la_valoracion`. Definir una propuesta explícita de servicio/alternativa
con su origen y estado (ofrecida, aceptada, rechazada), separada de la reserva
confirmada. Las tools proponen hechos; el modelo los verbaliza. Migrar el caso
diagnóstico antes de extender a otros recorridos y retirar correctores reemplazados.

Aceptación: diagnóstico ofrecido -> acepta/busca día para esa propuesta -> no
vuelve a pedir técnica del alisado; rechazar conserva la negativa; cambiar de
servicio abandona la propuesta anterior; no se crea nada sin confirmación.
Probar también una pregunta informativa o un «sí» ambiguo que NO acepta una cita.
No añadir listas de frases de salida como nueva autoridad.

**Cerrada (14-sep-2026, Claude).** La propuesta de servicio y la confirmación de reserva viven en el estado persistido
de la conversación (`reserva`), con identidad y versión; el botón o el «sí» solo aceptan la propuesta vigente
(`tests/test_propuesta_de_servicio.py`, `tests/test_agente_propuestas.py`, `tests/test_estado_de_la_reserva.py`,
`tests/test_estado_entre_procesos.py`). Con modelo real sobre copias de producción: el caso crítico
`dice-que-si-y-acaba-en-cita` (no sabe qué alisado quiere → diagnóstico a su nombre) 6/6 al primer intento en ed94be1,
c8aaad8 y 5c927dd, antes 0/6.

## Fase 3 — políticas visibles y aisladas en Q&A

Responsable a acordar tras fase 1. Reutilizar `AppBusinessRulePayload` y el editor
de reglas de `app_ui/index.html`; hacerlo accesible también cuando todavía no
hay reglas, con explicación de alcance y acciones admitidas. Mantener información
y restricciones diferenciadas dentro de Q&A, sin pedir al cliente código interno.
Completar encapsulación pendiente de apellidos de `astra/alicia-final` y auditar
tono/respuestas fijas. No incorporar todos esos cambios sin revisarlos.

Aceptación: crear, editar, desactivar y borrar reglas desde Q&A cambia el próximo
comportamiento pertinente; indicar configuración inválida/conflictiva; dos tenants
con reglas opuestas no se contaminan. Horarios y catálogo siguen en sus secciones.

Avance 14-sep-2026 (Claude, `68a8c68`, «indicar configuración inválida/conflictiva»):
la API rechaza con 400 lo que hace imposible una regla (sin intenciones, que casaría
con cualquier mensaje; intención que no existe; acción que contesta sin texto). Antes
solo lo pedía el formulario. Y el listado del portal trae `avisos` por regla, que el
editor pinta debajo de cada una: tapada por otra de más prioridad que cubre los mismos
casos, misma prioridad con casos que se pisan, familia que no está en el catálogo (una
técnica que aparece en el nombre de un servicio no avisa), texto vacío y «ofrecer cita»
sin servicio de valoración. Tests: `tests/test_avisos_de_reglas.py`, 17 casos. Puerta
«dos tenants con reglas opuestas no se contaminan» medida con modelo real el 14-sep-2026:
dos negocios sintéticos en entorno aislado, A contesta él mismo y B pasa a una persona,
preguntas de precio intercaladas, luego la regla de A editada y la de B borrada: 21/21, 0
fallos. La clasificación se cachea por negocio y la regla se relee en cada consulta.
**Fase 3 cerrada.**

## Fase 4 — consolidación de canales y retirada de duplicados

Siguiente candidato: astra/confirmacion-reserva, hija de 530ae40. El resumen de
WhatsApp se guarda antes de enviarlo, solo se ofrece tras el acuse, se recupera
al perder el worker y sus botones llevan identidad. La aceptación se publica con
versión antes de ejecutar; las opciones antiguas no autorizan datos nuevos.
Queda conectar esa identidad al resultado de la creación, además de migrar los
formularios nativos y las confirmaciones de gestión de citas existentes.

Avance local 12-sep: `53f40c7` persiste Estado con versión y aceptación explícita;
su suite terminó con 2248 correctos, 1 omitido y 2 fallos de mapa/código muerto,
corregidos en 96e10b8 con 10 dirigidos verdes. El descendiente integrado requiere
su propia suite y revisión. La siguiente rama
`astra/operaciones-recuperables` prepara una identidad duradera de creación en
el núcleo. Sigue pendiente conectarla a confirmaciones persistidas y a la
recuperación de WhatsApp; una primitiva opcional no cierra esta fase.

Inventariar cada interceptor con el caso que protege y su dueño final. Mover la
decisión al estado, política o núcleo según contrato y eliminar el camino antiguo
en entregas pequeñas. Reusar `_create_booking_core` y `_update_booking_details`.
Mantener la adaptación de WhatsApp, widget y voz; no mantener dos autoridades
ejecutándose a la vez. Trazas de transición/resultado, sin nuevos datos personales.

Aceptación: crear/cancelar/reprogramar y fallos del proveedor no producen éxitos
falsos, dobles citas ni historias de mensajes no enviados. Horarios, duraciones y
ocupación coinciden entre oferta y escritura. Revisar recordatorios existentes
con Claude, incluyendo aceptación del proveedor y prevención de duplicados.

### Inventario de frenos del agente (fase 4, 14-sep-2026)

Cada freno de `backend/agent.py` (`traza.freno`, visible en `agent_turns.frenos_json`)
con el caso que protege y dónde debería vivir su decisión cuando se consolide. «Estado»
= lo decide `reserva.Estado`/propuesta; «núcleo» = una tool o `booking` lo impide al
escribir; «salida» = comprueba lo que va a leer la clienta contra un hecho (agenda,
catálogo, política). Un freno de salida que ya tiene su hecho en el núcleo es candidato a
retirarse cuando el núcleo lo cubra en todos los canales; ninguno se retira sin su caso
medido.

| Freno | Protege | Hecho que consulta | Dueño final | Revisado hoy |
| --- | --- | --- | --- | --- |
| `pide_la_valoracion` | Aceptar la valoración ofrecida sin repreguntar técnica | propuesta del estado | estado | — |
| `afirmo_sin_mirar_la_agenda` | «El jueves estamos cerrados» sin consultar | consulta de agenda en el turno | salida | — |
| `ofrecio_una_hora_que_no_tiene` | Ofrecer una hora inexistente | huecos + agenda real del día | salida → núcleo | 3167313: muestra ≠ todo lo libre |
| `lo_anuncio_sin_hacerlo` | «Un momento, lo miro» sin mirar | consulta en el turno | salida | — |
| `dijo_cerrado_estando_abierto` | Decir cerrado un día que abre sin hueco | horario del día referido | salida | 3f11dea: mira de qué día habla |
| `precio_que_no_se_da` | Dar precios que el negocio oculta | política del negocio | política | — |
| `duracion_que_no_pidio` | Soltar duraciones no preguntadas | lo que ha preguntado | salida | — |
| `le_repitio_su_muletilla` | Repetirle su frase como si fuera servicio | catálogo | salida | — |
| `vendio_sobre_una_queja` | Vender otro tratamiento ante una queja | intención queja | política | — |
| `insistio_tras_dejarlo` | Seguir pidiendo datos cuando lo deja | lo que ha dicho | estado | — |
| `eligio_por_ella` | Recomendar técnica cuando el negocio dice que no | Q&A escrita del negocio | política | f288ddf: «qué me recomiendas» |
| `fianza_que_no_le_toca_decir` | Cifras de fianza de valoración | política del servicio | política | — |
| `nego_lo_que_no_sabe` | «No tenemos promociones» sin saberlo | Q&A del negocio | salida | — |
| `se_repetia` | Repetir la misma respuesta | historial | salida | — |
| `dijo_que_hay_cita_sin_haberla` | Afirmar una cita confirmada que no existe | agenda (citas vivas) | salida → núcleo | 36b4d8d: su cita viva no se niega |
| `hora_que_no_es_la_suya` | Confirmarle otra hora que la de su cita | agenda (citas vivas) | salida | — |
| `dijo_haberlo_hecho_sin_hacerlo` | «Acabo de reservar/cancelar» sin tool | mutación en el turno | salida | — |
| `daba_por_viva_una_cita_cancelada` | Dar por viva una cita anulada | estado `cancelada` | estado | — |
| `daba_la_cita_por_hecha` | «Te he reservado» sin cita | estado + mutación | salida | — |
| `cita_de_una_oferta_retirada` | Cita del servicio de una oferta retirada | propuesta `invalidada` | estado | 3f11dea (nuevo) |
| `dia_de_la_hora_elegida` | Hora del código en otro día | estado `hora_del_codigo` | estado | — |
| `cancelar_sin_pedirlo` | Cancelar sin petición | lo que escribió + pregunta de anular | núcleo | 2a794c2, 0bca1eb |
| `cita_duplicada` | Coger dos citas seguidas | citas creadas en el turno | núcleo | — |
| `cita_sin_pedirla` | Crear cita a quien solo preguntaba | intención + lo que escribió | estado | — |
| `se_acabaron_las_vueltas` | Quedarse sin respuesta | contador de vueltas | técnico | — |
| `revento` | Fallo del proveedor del modelo silencioso | excepción del cliente OpenAI | técnico | — |

Frenos en falso detectados con modelo real el 13-sep y ya arreglados: `ofrecio_una_hora_que_no_tiene`,
`dijo_cerrado_estando_abierto`, `dijo_que_hay_cita_sin_haberla`. Siguiente paso de la fase 4: medir la tasa de
cada freno en conversaciones reales de Alicia (`agent_turns.frenos_json`) y retirar o mover al núcleo los que no
protejan un caso vivo.

### Entregas de avisos y operaciones perdidas (fase 4, 14-sep-2026)

- **Avisos** (`1458540`, `claude/candidato`): la reclamación por canal dejaba un aviso
  bloqueado para siempre ante un fallo de email o SMS (se guardaba «desconocido») y un
  WhatsApp dudoso impedía también el respaldo. Decisión de Pablo: el fallo de email/SMS
  queda «rechazado», se reintenta en la siguiente vuelta y pasa al siguiente canal; un
  WhatsApp dudoso o un envío colgado nunca se repiten por su canal, pero pasados 30 min
  (`notice_deliveries.GRACIA_AVISO_DUDOSO_MIN`) sale el siguiente. Riesgo aceptado: rara vez
  un email repetido. La revisión adversarial de Codex encontró dos fallos altos (el respaldo
  no salía porque la cita dejaba la banda del recordatorio; un ejecutor perdido conservaba su
  turno y duplicaba), corregidos en `549a1e3` con test rojo previo. Una segunda revisión encontró
  la carrera al límite de la gracia y el reenvío manual sin protección: `0b12b3c` renueva el turno
  al enviar y, por decisión de Pablo, el panel avisa y pregunta antes de reenviar un WhatsApp
  dudoso; `3e05b96` extiende ese aviso a la confirmación que sale al pagar y a un reenvío solo
  por email en medio. Sin medir con Meta real.
- **Operaciones de creación perdidas**: `OPERATION_PENDING` no se reconciliaba nunca y la
  clienta quedaba atrapada en «Aún no puedo verificar… contacta con el negocio». Encargo a
  Astra: `5c88bc7` libera tras 15 min una operación interna sin cita y sin webhook (auditada
  en `booking_operation_audit` sin datos de la clienta) y WhatsApp pide una confirmación
  nueva. Revisión de Claude: CAMBIOS, atasco reproducido si falla el guardado del estado tras
  liberar. `5a965e7` lo corrige y reabre también una clave ausente pasado el margen. Segunda
  revisión: CAMBIOS, el margen contaba desde la creación del resumen y un doble toque tardío
  le decía «no llegó a registrarse» mientras se creaba su cita (repro). `04fc97f` (Claude;
  Astra sin cuota) lo cuenta desde la aceptación. Rama `claude/reconciliar-pendientes`:
  suite completa 2687 passed, 1 skipped; integrada en el candidato (`d14285d`); falta la
  revisión de Astra de `04fc97f`. Con `WEBHOOK_DEFAULT` puesto en el servidor no se libera nada (no comprobado en
  producción).
- Reprogramar por el flujo guiado de WhatsApp exige ya aceptar el cambio concreto (`e44886b`),
  igual que la cancelación: resumen «Ahora / Nueva» con identidad, cita revalidada contra el
  resumen, hueco comprobado antes de ofrecer y resultado perdido que deja volver a pulsar.
  Decisión de Pablo: solo el flujo de listas; el agente conversacional no cambia.
- Cancelación con resultado desconocido (`e11ac35`): pasados 15 min desde la aceptación y sin
  webhook, si la cita sigue en pie se le vuelve a enseñar para que confirme; nunca se cancela
  sola, y antes del margen o con webhook sigue pendiente. Mismo criterio que la creación.
- Sigue abierto en esta fase: reprogramar desde el agente (Pablo decidió no tocarlo por ahora),
  voz y widget sin confirmación persistida (esperan a un cliente que los use) y retirar frenos
  del agente con conversaciones reales.

**Cerrada con excepciones (decisión de Pablo del 14-sep-2026, «Cerrar con excepciones»).** Hecho en los canales que usa
Alicia: crear, cancelar y reprogramar por el flujo guiado de WhatsApp exigen aceptar la propuesta concreta, con
identidad y estado persistidos; las operaciones de creación y de cancelación sin resultado se recuperan pasado el margen
sin repetir la acción ni dejar a nadie sin respuesta (e230991: conflicto al recuperar la cancelación); los avisos no se
bloquean ni se duplican; el cobro de la prueba gratis no empieza antes del fin prometido y Stripe y la config guardan la
misma fecha (e230991); unas vacaciones de día entero son un día cerrado en todos los canales. Revisiones cruzadas de
Astra y de Codex con reproducción en cada entrega.

Quedan FUERA del plan, como seguimiento con su dueño y su disparador:

| Pendiente | Por qué no se cierra ahora | Se retoma cuando |
| --- | --- | --- |
| Reprogramar desde el agente conversacional con propuesta aceptada | Decisión de Pablo: no tocar la conversación de Alicia | Pablo lo pida |
| Voz y widget con confirmación persistida | Ningún cliente los usa | Un cliente active voz o widget con reservas |
| Retirar o mover frenos del agente | Sin conversaciones reales con las que medir su tasa (`agent_turns.frenos_json`) | Alicia lleve unos días usándolo |
| WhatsApp y recordatorios con Meta real | El número de Alicia sigue sin conectar | Alicia conecte su WhatsApp |
| `horario-escrito-manda` en metareview | Contesta el horario de hoy, no el de la semana (fallo real, 15/16) | Se toque el agente de metareview |

## Fase 5 — aceptación del candidato

Pruebas dirigidas por fase, regresiones rojas sin arreglo, suite completa sobre
el candidato estabilizado y revisión de Claude. Medir conversaciones completas
de Alicia y un segundo negocio con configuración distinta; publicar ejecuciones,
fallos, reintentos y limitaciones. No equiparar un resumen con una cita creada.
Separar dependencias externas (Meta, conexión del número, datos que confirma Alicia).

No declarar versión final ni desplegar por iniciativa propia. Guardar en
`ESTADO_ACTUAL.md` fase, rama, evidencia, siguiente paso y responsable. No consultar
repetidamente procesos en curso ni ampliar una fase antes de cerrar sus pruebas.
