# Trabajo técnico tras el despliegue de Alicia

16-sep-2026 21:55 Europe/Madrid. Plan solicitado por Pablo: trabajo de nuestro
equipo sin depender de nuevas respuestas, catálogo o conexión de Alicia.
Planificación, no implementación iniciada ni autorización de despliegue.

Actualización tras comparación documental del 16-sep:
[COMPARATIVA_IA_Y_PLAN_DE_BAJO_COSTE.md](COMPARATIVA_IA_Y_PLAN_DE_BAJO_COSTE.md).
Antes del piloto de selección se priorizan verificar la salida al agotar vueltas,
contratos JSON y cobertura de consumo. No se necesita otra plataforma de trazas:
ya existen `Traza` y `resumen_del_dia`. Se conserva el alcance de los bloques de abajo.

## Referencia estable

Registro y buzón de Claude confirman despliegue de `c110bd9` a las 21:35, código
`30c5e15`, health correcto y humo 5/5. No se ha consultado producción de nuevo.
Evidencia previa sobre ese código: suite 2874 passed / 1 skipped, Alicia 45/45 al
primer intento, segundo negocio 16/16, críticos 36/36 y diagnóstico 10/10.
No repetir esas pruebas para planificar. No equivale a verificación Meta real.

## 1. Sustituir la decisión de añadir/quitar servicios por estado validado

Es la prioridad técnica: los últimos incidentes siguen viniendo de interpretar
«no quiero», «en vez de», «también» u ordinales en listas de expresiones.

- Primero fijar un contrato y casos de comportamiento: añadir, sustituir, quitar,
  matizar, consultar y aclarar; conservar lo no modificado. Usar los repros existentes.
- El modelo propone la operación y los servicios del catálogo a los que se refiere;
  el código comprueba identificadores, tenant, estado anterior y evidencia del turno.
  Un nombre de profesional, una pregunta de precio o un ordinal no son servicios.
- Si el alcance es ambiguo, mantener los servicios y preguntar. No borrar por una
  deducción dudosa ni convertir una propuesta del modelo en autorización para reservar.
- El estado conserva una única selección vigente. El resumen muestra lo que se
  reservará y, cuando cambie la selección, lo retirado. Confirmar autoriza exactamente
  ese resumen; el núcleo recalcula duración, profesionales y disponibilidad.
- Reutilizar `intents`, `reserva.Estado` y propuestas existentes; revisar primero
  `agent._lo_que_pide_ahora` y `booking` para no añadir una segunda autoridad.
  Retirar el mecanismo sustituido cuando el nuevo pase los mismos casos.

Primer entregable: contrato de transición, mapa de llamadas y regresiones con datos
sintéticos; después una implementación acotada solo a selección de servicios.
Comparar ambos comportamientos en copia, sin activar dos decisores en producción.
Cierre: no perder servicios ni bloquear sustituciones válidas en el banco acordado,
con reinicios y mensajes repetidos; revisión independiente y medición comparable.

## 2. Unificar validación en todas las entradas

Auditar agente, listas, formulario nativo y portal contra las mismas reglas del
núcleo. Empezar por el hallazgo documentado de apellidos y el rechazo persistente:
elegir un servicio no acredita haber resuelto un rechazo de otra causa.

Usar tenants sintéticos con requisitos opuestos, sin cambiar las reglas de Alicia.
Probar que una oferta queda invalidada si el portal cambia servicio, profesional,
horario, vacaciones o política, también justo antes de confirmar. Añadir únicamente
cobertura que falte; no duplicar lo ya verificado. Cierre: ninguna entrada evita una
regla obligatoria y ninguna configuración se filtra entre tenants.

## 3. Separar interlocutor, titular y ficha de contacto

Diseñar explícitamente quién habla y para quién es la cita. Una reserva para otra
persona no renombra al contacto; si falta el titular, pedirlo antes del resumen.
Partir de `reserva`, `crm._nombre_para_la_ficha` y los controles de nombre actuales.
Probar clienta conocida, nueva, nombre provisional y dos reservas para personas
distintas desde un teléfono. Sin fusión masiva ni modificación de contactos reales.
Los casos aplazados permanecen documentados hasta validar la solución; no cambian
retroactivamente el alcance aceptado del despliegue actual.

## 4. Fallos explicables y recuperación demostrable

Primero inventariar las trazas existentes (`agent_turns`, operaciones y entregas).
Completar solo lo que falte para relacionar: estado previo, propuesta, regla y su
versión, motivo de bloqueo, operación ejecutada y respuesta realmente enviada.
No copiar conversaciones, teléfonos ni secretos a nuevos logs.

Preparar un resumen reproducible de bucles, rechazos repetidos, operaciones sin
resultado y entregas desconocidas. Medir con contadores definidos y no interpretar
ausencia de error como éxito. Reutilizar los instrumentos de `COMO_SE_MIDE.md`.
Probar reinicios, concurrencia, confirmación duplicada, cancelación/reprogramación
antes del recordatorio y recuperación de un envío incierto, con transporte simulado.
Meta real puede probarse después con un tenant y número del equipo autorizados;
no es requisito para avanzar en los contratos ni se declara probado por simulación.

## Orden, reparto y puerta de entrega

1. Mantener la referencia desplegada y corregir el relevo documental desactualizado.
2. Diseñar y entregar selección de servicios (bloque 1), en una rama acotada.
3. Validaciones entre canales; después titular/contacto, en cambios separados.
4. Completar trazas y pruebas de recuperación donde el inventario detecte huecos.

Astra diseña y revisa; coordinar con Claude el propietario de cada implementación
antes de editar. Claude aporta implementación, revisión o medición según el reparto
vigente, sin dos agentes tocando el mismo bloque. Una mejora por candidato:
regresión causal, dirigidos, una suite estable, revisión del SHA exacto y banco con
la misma configuración/calendario que la referencia. Informar primer intento,
reintentos, fallos y no medidos. Conservar resultados desfavorables.

Este plan no crea procesos ni seguimiento automático. No introduce nuevas reglas
comerciales, no cambia producción y no requiere que Alicia complete ninguna tarea.
Un cambio de código se despliega solo con orden de Pablo y la puerta habitual.
