# Fase 2: propuestas de servicio y confirmación

Diseño de Astra, 12-sep-2026. Datos y transiciones implementados en `reserva`.
Integración en validación para alternativas de PRESUPUESTO con regla declarada
`ofrecer_cita`: agente y WhatsApp usan la misma transición del núcleo. No se ha
migrado la indecisión ni se ha aprobado una política nueva de Alicia.
Complementa docs/PLAN_CONSOLIDACION_IA.md y docs/NORMAS_AGENTE_IA.md.

## Evidencia y alcance

Avance actual:
- `booking.alternativa_de_precio_vigente` lee regla y servicio público del tenant
  y centro. Su huella incluye los datos actuales; no incorpora horarios duplicados.
- `booking.contestar_alternativa_de_precio` revalida antes de aceptar/rechazar;
  aceptar selecciona el servicio leído y descarta huecos del tratamiento anterior.
- Tool `responder_propuesta`, disponible solo con oferta enviada: interpreta la
  respuesta libre dentro de la llamada normal al modelo. Código valida identidad,
  estado y revisión. Una fecha permite consultar, no seleccionar ni crear.
- WhatsApp ofrece botones por id de propuesta; `_wa_enviar_propuesta_de_precio`
  acredita la aceptación de Meta. El modelo no puede crear mientras está pendiente.
- Se retiran de este recorrido la selección anticipada de WhatsApp, la instrucción
  de cambiar servicio y volver a crear, y la aceptación deducida del texto del bot.
- Web sin teléfono usa su session_id; no comparte la clave vacía con otras sesiones.
- Reinicios descartan propuestas en memoria: no se recupera aceptación de un texto.
  Persistencia entre procesos, confirmación provisional en un único acto y migración
  del resto de recorridos siguen pendientes. No atribuir estas garantías a todos
  los caminos antiguos ni declarar resuelto el caso crítico sin nueva medición.

La referencia [Anthropic: herramientas eficaces](https://www.anthropic.com/engineering/writing-tools-for-agents)
recomienda responsabilidades claras y medir herramientas con resultados verificables.
Aplicación aquí: una transición para texto y botón y una prueba que intenta crear
saltándose el esquema. El esquema orienta al modelo; el código frena la ejecución.

Lectura acotada del candidato:
- agent._acepta_la_valoracion: exige afirmación, palabra de diagnóstico y signo
  de interrogación en el último texto del asistente. La redacción decide la acción.
- agent._descripcion_para_buscar: mezcla servicio_texto con nuevas palabras;
  solo deja de arrastrar el tratamiento cuando reconoce la petición de valoración.
- whatsapp._wa_explicar_la_regla_del_precio: cambia servicio y servicio_exacto
  y borra hora/huecos ANTES de enviar y de que la clienta acepte.
- reserva.Estado y anotar_resultado ya centralizan datos: extender este estado,
  no añadir otro flujo paralelo. esperando_confirmacion se reserva para la
  confirmación final de una operación sobre agenda.

Caso de aceptación de Claude: alisado -> duda -> diagnóstico ofrecido -> mañana
cerrado -> martes a las 15 -> nombre -> resumen de diagnóstico; no volver a
preguntar keratina/ácido láctico y no crear ninguna cita antes del botón final.

## Contrato de datos propuesto (todavía no es una API existente)

Una propuesta de alternativa dentro de Estado:
- id único generado por código; ámbito del Estado por tenant + conversación.
- servicio_id estable del catálogo y nombre público para mostrar.
- origen: regla identificada o resultado de una tool, no texto libre del modelo.
- estado: preparada, ofrecida, aceptada, rechazada, invalidada.
- referencia al mensaje que la presentó y propósito de la pregunta pendiente.
- versión/huella relevante de la política y servicio al proponer.

El tratamiento solicitado se conserva como antecedente, separado de la propuesta.
El texto acumulado no puede sobrescribir una alternativa aceptada. No duplicar
horarios, disponibilidad o catálogo en el objeto de propuesta.

## Transiciones y dueño

| Hecho | Transición permitida | Dueño |
| --- | --- | --- |
| Regla/tool permite alternativa del catálogo | preparar propuesta, sin seleccionar ni crear | núcleo de decisión |
| Canal acepta el mensaje que la presenta | preparada -> ofrecida | confirmación del adaptador de salida |
| Envío rechazado | no marcar ofrecida; permitir reintento sin duplicar | adaptador + estado |
| Usuario acepta la propuesta vigente | ofrecida -> aceptada, resolver servicio actual | estado tras validar interpretación |
| Usuario rechaza | ofrecida -> rechazada; no volver a ofrecer por un contador viejo | estado |
| Usuario cambia de gestión/servicio o propuesta caduca | invalidar propuesta y confirmación anterior | estado |
| Portal retira servicio o cambia política aplicable | revalidar; invalidar si ya no procede | núcleo |
| Botón final de resumen vigente | validar agenda actual y ejecutar una vez | núcleo de agenda |

El modelo interpreta una respuesta libre como una intención candidata vinculada
a la propuesta vigente. El código valida contexto, pertenencia y acción permitida.
No acepta referencias a propuestas ajenas, caducadas o de otra gestión. Si no está
claro a qué contesta el usuario, pregunta; no deduce aceptación de palabras del bot.

Una fecha u hora sola NO demuestra aceptación. Con una única alternativa ofrecida
se puede CONSULTAR disponibilidad para ella, dejándola explícitamente provisional.
El resumen debe identificar el servicio propuesto; su confirmación puede aceptar
esa alternativa y autorizar la reserva en un mismo acto. No reservar antes, ni
imponer una pregunta de técnica del tratamiento anterior mientras se explora la
disponibilidad de diagnóstico. Si hay dos alternativas abiertas, aclarar primero.

## Migración acotada

1. Implementado: transiciones dentro de reserva y tests de estados; todavía no
   se activa un recorrido nuevo. Se reutiliza el almacén de conversaciones.
   La huella de configuración la aportará el llamador tras leer política/servicio;
   este paso prueba su comparación, no la integración con cambios del portal.
2. Hacer que la decisión de valoración devuelva una propuesta estructurada con
   servicio del tenant. El modelo solo presenta esa propuesta. No inventar una
   valoración porque exista una Q&A informativa parecida.
3. Migrar juntos el camino conversacional y _wa_explicar_la_regla_del_precio:
   salida aceptada registra ofrecida; salida fallida no altera selección.
4. Hacer que disponibilidad use el servicio seleccionado o la alternativa
   provisional identificada. El resumen usa la misma identidad y se revalida.
5. Retirar el análisis del texto previo de _acepta_la_valoracion y la sustitución
   prematura de servicio en WhatsApp para los caminos migrados. El contador de
   duda puede activar una propuesta permitida, nunca aceptarla por la clienta.
6. Revisar los tests antiguos que inspeccionan líneas de código y sustituirlos
   por el comportamiento cubierto; conservar todos los casos de negocio.

No cambiar cancelación/reprogramación ni el motor de recordatorios en esta fase.
Sí comprobar que el nuevo estado no interviene cuando se gestiona una cita existente.
Evitar un despliegue con autoridades vieja y nueva activas para la misma decisión.

## Batería mínima antes de integrar

- Mismo resultado con cualquier redacción de la oferta, con o sin interrogación.
- El caso completo aportado por Claude llega al resumen del diagnóstico.
- Rechazar diagnóstico no se convierte en aceptación tras decir fecha o nombre.
- Un sí a una pregunta informativa no selecciona servicio ni crea cita.
- Fecha sin aceptación permite consulta provisional, no creación.
- Fallo de envío no deja una propuesta ofrecida ni borra datos elegidos.
- Desactivar o editar el servicio desde el portal invalida una propuesta antigua.
- Cambiar a otro servicio/gestión deja sin efecto botones anteriores.
- Dos tenants y dos conversaciones no comparten propuesta ni selección.
- Repetir el botón de confirmación no duplica la reserva.
- Disponibilidad y resumen conservan identidad del pack, duración y profesional.

## Decisiones pendientes de cerrar con Claude

- Punto único donde los adaptadores confirman que la respuesta fue enviada;
  inventariar llamadas existentes antes de añadir parámetros nuevos al agente.
- Cobertura de identidad de conversación y persistencia entre workers: Estado
  actual reside en memoria. No prometer continuidad entre procesos sin resolverla.
- Cómo representar la regla de valoración desde Q&A/business_rules sin inferir
  una acción ejecutable a partir de una respuesta meramente informativa.
- Confirmar que la interpretación libre puede viajar en la llamada actual del
  modelo, sin un clasificador adicional por mensaje.

Claude revisa las piezas y aporta los datos de política que falten. El estado
base avanza en `astra/estado-propuestas` sin esperar las mediciones reales. No
afirma persistencia entre procesos, ejecución exactamente una vez ni integración
de canales: esos comportamientos requieren sus pruebas de extremo a extremo.
