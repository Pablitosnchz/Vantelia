# Recuperación del estado: siguiente fase de consolidación

Diseño de Astra, 12-sep-2026. Primera implementación en astra/persistencia-conversacion; quedan puertas de operación por cerrar.
No sustituye la revisión del candidato ni las mediciones con el modelo real.

## Implementado en el candidato de persistencia

Estado se lee de SQLite, no del diccionario del worker. La clave separa tenant,
canal e identidad. Teléfonos sin prefijo son del adaptador actual de WhatsApp;
web:/whatsapp:/voice:/turno: separan explícitamente los espacios. El núcleo de voz
y el widget tienen recorridos distintos y no se afirma su migración completa.

Cada snapshot lleva formato, revisión y vencimiento. Guardar compara revisión;
olvidar deja una lápida para impedir que un escritor antiguo lo resucite. Aceptar
una alternativa publica su respuesta y selección juntas antes de devolver éxito.
Hay pruebas con intérpretes distintos y una aceptación/rechazo sobre la misma
versión: solo uno gana. Esto no ejecuta ni duplica una cita.

El agente guarda los hechos validados antes de esperar al modelo. WhatsApp guarda
la oferta preparada antes de enviar, y el acuse después. Los datos malformados,
caducados o de otro formato no recuperan autorización. Se elimina el fallback
que aceptaba una valoración a partir de la pregunta antigua del bot.

Límite importante: los resultados de una operación de reserva aún no comparten
una transacción/idempotencia con ese snapshot. La ventana de caída después de
crear y antes de guardar el resultado necesita la siguiente fase; no se presenta
como exactamente una vez ni como versión final para Alicia.

## Problema demostrado y límite actual

Antes de este candidato, `reserva.cargar` y `guardar` conservaban Estado solo en un diccionario de appstate.
Reiniciar o cambiar de worker pierde selección, propuesta, rechazo y acuse.
`agent._acepta_la_valoracion` protege las propuestas presentes, pero sin ellas
conserva una inferencia histórica a partir de la pregunta del bot. Esa inferencia
no acredita envío, vigencia ni autorización. Los tests de botones que rechazan
un id desconocido no prueban que la respuesta libre tras reiniciar sea segura.

También se ha localizado una aceptación presente que se reutilizaba sin volver
a comprobar caducidad ni la revisión de política y servicio. Se corrige esa
revalidación en el núcleo compartido; no se presenta como recuperación completa.

## Contrato de la siguiente implementación

- Persistir hechos de conversación con clave compuesta tenant + identidad de
  conversación + canal. Usar los identificadores reales de cada adaptador;
  documentar primero la correspondencia entre teléfono, sesión web y sesión voz.
- Guardar versión de formato, versión de concurrencia, vencimiento y los datos
  operativos de Estado; no serializar objetos SDK ni reconstruir autorización
  leyendo el texto visible del historial.
- Lectura/escritura en SQLite existente con transacción y versión esperada. Una
  escritura antigua no puede resucitar una oferta rechazada o ya aceptada por
  otro worker. Ante conflicto se recarga y se pide una respuesta sobre el estado
  vigente; no se ejecuta la operación con el estado perdido.
- Persistir una propuesta preparada antes de enviar; registrar ofrecida después
  del acuse. Un timeout de Meta es resultado desconocido, no aceptación del usuario.
- Aceptar modifica selección; ejecutar reserva sigue siendo otra transición con
  clave de idempotencia y validación actual de agenda. Una transacción local no
  promete exactamente una vez frente a una API externa.
- Estado ausente/caducado/corrupto exige oferta nueva o confirmación explícita.
  Retirar en el mismo cambio la inferencia histórica del recorrido migrado.
- Migración sin reinterpretar conversaciones antiguas. Conservar solo lo necesario
  durante la vigencia; limpieza acotada por vencimiento, sin nuevos datos personales.

## Pruebas que deben cerrar la fase

| Caso | Resultado exigido |
| --- | --- |
| Oferta enviada, nuevo proceso, respuesta | Recupera identidad y revisión; no infiere una oferta distinta |
| Preparada sin acuse, nuevo proceso, sí | No acepta ni selecciona |
| Rechazada, nuevo proceso, sí | No resucita la alternativa |
| Dos workers aceptan/rechazan la misma versión | Una transición gana; la otra detecta conflicto |
| Regla/servicio cambia entre envío y respuesta | Invalida y solicita oferta vigente |
| Commit local y fallo de WhatsApp | No registra un mensaje como entregado; resultado trazable |
| Reserva creada y proceso muere antes de responder | Recupera el resultado de la misma operación, no crea otra |
| Mismo teléfono en dos tenants / dos sesiones web | No comparte hechos ni autorización |
| Estado antiguo, ausente o malformado | Recuperación segura y ninguna ejecución deducida del historial |

Orden: prueba roja entre procesos reales sobre DB temporal; repositorio de estado
con concurrencia; adaptación de canales; retirada del fallback; suite estable;
banco Alicia y segundo negocio; revisión exacta. No basta vaciar un diccionario
para simular todos los fallos anteriores.

## Mantenimiento y rutas de implementación

`conversation_state.py` contiene lectura, escritura comparada y limpieza SQLite;
`reserva.py` mantiene el contrato y serializa hechos tipados. El esquema se crea
idempotentemente en `db._init_database`. La limpieza borra hasta 200 filas vencidas
con margen de una sesión adicional; los escritores cuya carga caducó no publican.
La baja del tenant limpia todas sus filas. Una versión de formato desconocida
no recupera permisos ni puede ser sobrescrita por este escritor.

La suite nueva se reparte en test_estado_entre_procesos, test_snapshot_conversacion,
test_historial_sin_autorizacion y test_whatsapp_estado_persistido. Las fixtures
antiguas que envejecían objetos por referencia ahora avanzan el reloj; no se ha
eliminado la prueba de que una conversación caducada deja de valer.
