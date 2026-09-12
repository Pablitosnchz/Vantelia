# Plan de consolidación: portal, políticas y conversación

Encargo de Pablo, 12-sep-2026. Astra coordina; Claude revisa y mide el modelo.
Contrato obligatorio: `NORMAS_AGENTE_IA.md`. No está completado este plan.

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

## Fase 5 — aceptación del candidato

Pruebas dirigidas por fase, regresiones rojas sin arreglo, suite completa sobre
el candidato estabilizado y revisión de Claude. Medir conversaciones completas
de Alicia y un segundo negocio con configuración distinta; publicar ejecuciones,
fallos, reintentos y limitaciones. No equiparar un resumen con una cita creada.
Separar dependencias externas (Meta, conexión del número, datos que confirma Alicia).

No declarar versión final ni desplegar por iniciativa propia. Guardar en
`ESTADO_ACTUAL.md` fase, rama, evidencia, siguiente paso y responsable. No consultar
repetidamente procesos en curso ni ampliar una fase antes de cerrar sus pruebas.
