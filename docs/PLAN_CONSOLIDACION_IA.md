# Plan de consolidación: portal, políticas y conversación

Encargo de Pablo, 12-sep-2026. Astra coordina; Claude revisa y mide el modelo.
Contrato obligatorio: `NORMAS_AGENTE_IA.md`. No está completado este plan.

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
