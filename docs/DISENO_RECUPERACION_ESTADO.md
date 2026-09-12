# Recuperación del estado: siguiente fase de consolidación

Diseño de Astra, 12-sep-2026. No está implementada la persistencia descrita aquí.
No sustituye la revisión del candidato ni las mediciones con el modelo real.

## Problema demostrado y límite actual

`reserva.cargar` y `guardar` solo conservan Estado en un diccionario de appstate.
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
