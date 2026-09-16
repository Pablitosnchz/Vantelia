# Cierre operativo de Alicia — 16 de septiembre de 2026

Plan de Astra, 10:49 Europe/Madrid. Base main `61a5d8a`, código `311b58e`.
Objetivo: una versión aceptada para los recorridos reales de Alicia, con evidencia y
pendientes explícitos. No prometer ausencia absoluta de errores ni confundir cierre
de arquitectura con aceptación operativa. Este documento no autoriza despliegues.

## 0. Punto de partida verificado y coordinación

- Git y registro coinciden en código `311b58e`; el registro documenta su despliegue
  el 15-sep, humo 5/5 y suite 2833 passed / 1 skipped. No se ha consultado producción
  en esta planificación ni repetido esa suite.
- Ya entregado: agenda por pasos sin rayado «libre», ocultación visual de precios
  conservando importes para cobrar, profesionales según catálogo y un apellido para
  Alicia; confirmación de reprogramación y recuperación de operaciones.
- El banco registrado sobre `7a8e473` terminó 44/44, pero 43 al primer intento y
  uno tras reintento por insistencia en diagnóstico. No es un banco del código y
  configuración actuales: después cambiaron CRM y exigencia de apellidos.
- El rechazo de creación aún se comprueba por fecha del turno en
  `backend/whatsapp.py:2856`. La reproducción de la revisión anterior permitía
  intentar el resumen al recibir «no entiendo», sin nueva validación. Se debe
  convertir en regresión de recorrido antes de modificarlo.
- Datos pendientes según registro: alisados, packs «Maquillaje y recogido» y «Elumen
  largo», precios que se pueden dar. Confirmar su vigencia con Claude/Pablo; no
  inventar las respuestas ni modificar datos por inferencia.
- Conexión del número de Alicia y medición real de recordatorios: estado actual
  por confirmar. La prueba de chatbot/demo no acredita ese canal productivo.
- Astra coordina diseño e implementación; Claude revisa el SHA exacto y mide con
  modelo cuando esté disponible. Consultado por Sincronía su trabajo activo para
  no duplicarlo. Código, datos de prueba, banco y configuración tendrán huellas
  identificables en cada informe.

Fuentes: `REGISTRO_CONSOLIDACION.md`, entradas del 15-sep 17:57–19:12;
`NORMAS_AGENTE_IA.md`; `ACEPTACION_CANDIDATO_IA.md` (evidencia histórica, no vigente).

## 1. Cerrar el rechazo pendiente de creación — prioridad primera

En ejecución por Astra en `astra/rechazo-persistente`, base `141f6e9`.
Regresión causal `9bade14`: dos casos rojos en el código anterior (mensaje sin
aclaración tras rechazo). Arreglo y pruebas de emisor real, reinicio, aceptación
duplicada y concurrencia en verde. Pendientes suite completa, revisión y medición;
esta anotación no declara el bloque aceptado.

Implementar en el estado existente una condición de rechazo pendiente que sobreviva
a mensajes, reinicios y concurrencia. Reutilizar `reserva.anotar_resultado`,
`reserva.cargar/guardar` y su control de versión; el canal consulta esa condición.
Se levanta al resolver y revalidar la propuesta, o al abandonar explícitamente esa
gestión. Una fecha antigua, un saludo o la redacción del modelo no la levantan.
Conservar la recuperación legítima: aclarar el servicio debe permitir continuar.

Verificación: rechazo -> «no entiendo»/«gracias» -> ningún resumen ni escritura de
cita; rechazo -> aclaración válida -> resumen -> aceptación -> una cita. Repetir
con reinicio, mensajes duplicados y conflicto de estado. Usar
`tests/test_prueba_alicia_15sep.py`, pruebas de creación recuperable y estado como
patrón; probar el emisor real del resumen con proveedor simulado, además del stub.
Primero rojo causal, después verde. No crear un segundo filtro por frases ni usar
`creacion_rechazada_en` como única autorización temporal.

Referencias verificadas: `backend/reserva.py:335` serializa el estado y `:379`
lo guarda; `tests/test_estado_entre_procesos.py` permite comprobar reinicios reales.
Vaciar una caché dentro del medidor no sustituye esta prueba entre procesos.

## 2. Resolver qué servicio y para quién — cambios pequeños separados

Partir de `agent._lo_que_pide_ahora`, `_freno_de_varios_servicios`,
`reserva.Estado` y los selectores de catálogo existentes. Definir transiciones de
añadir, sustituir y aclarar con servicios identificados y evidencia del mensaje.
El modelo puede proponer la transición; el código valida alcance y catálogo. Si
no está claro, una pregunta concreta mantiene la propuesta pendiente. No ampliar
indefinidamente las listas de expresiones ni permitir dos autoridades simultáneas.

Casos de aceptación: mechas -> grey; «en vez de X quiero Y»; sustituir por corte y
secado; añadir con «también»; cambiar profesional sin borrar servicios; resolver
solo uno de los servicios previos. Retirar únicamente el mecanismo que quede
sustituido y protegido por regresiones. Revisar decisión de diseño antes de ampliar
el modelo de estado; no reescribir todo el agente para esta entrega.

Patrones existentes: `reserva.cambia_de_servicio` (`backend/reserva.py:1161`) y
`booking.contestar_alternativa_de_precio` (`backend/booking.py:7631`) ya manejan
cambio y revalidación de propuesta. Leerlos y reutilizar su responsabilidad antes
de crear otra transición. Pruebas: `test_alternativa_de_precio.py:60` y
`test_estado_de_la_reserva.py:541`; no aplicar una regla de precio a todo cambio.

Para el nombre, mantener separado interlocutor/titular de cita. Un nombre inventado,
una recomendación de otra persona o el nombre de una profesional no cambia titular.
«Es para mi hija» requiere identificar y confirmar a quién corresponde la reserva;
si no hay dato suficiente se pregunta, sin alterar el contacto conocido. Usar
`tests/test_prueba_alicia_15sep.py` y los controles de nombre existentes. Revisar
también el alcance de `311b58e`: mismo nombre sin teléfono no acredita identidad
universal; cualquier cambio de fusión de contactos requiere decisión explícita.

## 3. Congelar las reglas y datos de Alicia

Inventario pequeño, validado con fuente y fecha: servicios, profesionales,
duraciones y pasos, horarios, vacaciones, precios visibles, apellido y reglas de
diagnóstico. Las reglas ejecutables pertenecen a Q&A/configuración del tenant;
horarios, vacaciones y servicios siguen en sus secciones operativas. Reutilizar
`NORMAS_AGENTE_IA.md` y los tests del portal, no duplicar configuración en prompts.

Verificación: editar cada tipo de dato en una copia del portal y comprobar su
efecto en la siguiente consulta y al aceptar un resumen anterior. Añadir control
con otro negocio cuyas reglas sean distintas. No endurecer una regla de Alicia
globalmente ni convertir una respuesta informativa en restricción automática.
Las decisiones de Alicia que falten bloquean sus casos concretos; el resto avanza.
No declarar esos casos disponibles y validados hasta tener datos o acordar su
tratamiento manual con Pablo.

## 4. Un candidato estable y una aceptación comparable

Congelar SHA y configuración después de los bloques anteriores. Pruebas dirigidas
durante cada arreglo y una suite completa por candidato estable. Conservar logs y
revisión cruzada del SHA exacto. No repetir suites antiguas por rutina.

Claude medirá candidato y referencia con el mismo banco, calendario válido y copia
aislada de la misma configuración. Usar `scripts/evaluar_asistente.py` con
`--db-origen`, `--db-copia`, `--cliente`, `--caso` y `--guardar`; revisar aislamiento
antes de ejecutar. Reutilizar `scripts/medir_portal_y_reinicio.py` para su recorrido.
No leer secretos ni enviar mensajes reales desde el banco.

Puerta propuesta: todos los casos aplicables de Alicia sin fallos ni casos no
medidos; casos críticos de crear/cancelar/reprogramar, rechazo y cambio de servicio
seis veces al primer intento. Un fallo obliga a investigar, no a repetir hasta verde.
Publicar intentos iniciales, éxitos tras reintento, fallos y no medidos por separado,
con lectura de conversaciones críticas y comparación de citas reales en la copia.
Segundo negocio: medir igual, sin reglas de Alicia filtradas; el fallo conocido de
horario semanal debe corregirse o quedar explícito como excepción ajena a Alicia,
sin declarar validación universal del producto.

## 5. Prueba operativa, entrega y seguimiento limitado

Con autorización para el entorno y destinatarios de prueba, comprobar Meta real:
envío/recepción, botones, resumen, confirmación, repetición, timeout y recuperación.
Recordatorios: aceptación del proveedor, entrega cuando haya evidencia, cancelación
previa, cambio de hora, zona horaria y ausencia de duplicados; distinguir entregado,
rechazado y desconocido. Un número sin conectar impide cerrar esta puerta.

Patrones de pruebas: `test_entregas_recordatorios.py` y
`test_avisos_reintento_sin_duplicar.py`; cubren reclamaciones persistidas y ejecutores
tardíos. Su transporte simulado no demuestra entrega de Meta.

Pablo/Alicia prueban un recorrido corto: reserva habitual; cambio de opinión;
reprogramar; cancelar; modificar horario/vacaciones y comprobar disponibilidad;
revisar agenda por pasos, precios y cliente. Hacerlo con datos y números de prueba
acordados, sin escribir a clientas reales automáticamente.

Entrega: SHA, configuración validada, informe de aceptación, excepciones concretas,
responsable de soporte y procedimiento de vuelta atrás. Solo después de la orden
de Pablo se despliega; humo y comprobación de versión. Proponer 48 h de observación
del uso consentido con errores, duplicados, preguntas repetidas y tareas sin cerrar;
sin automatización ni mensajes nuevos hasta acordar el seguimiento.

## Reparto y siguiente acción

Astra: bloque 1 y diseño del 2, commits pequeños y relevo. Claude: revisión,
mediciones y datos saneados; sin implementar lo mismo en paralelo. Pablo/Alicia:
decisiones de catálogo pendientes y aceptación operativa. Primer entregable:
regresión del rechazo que persiste al siguiente mensaje; después se implementa.
Esta sesión deja el plan; no hay implementación ni pruebas de este plan ejecutándose.
