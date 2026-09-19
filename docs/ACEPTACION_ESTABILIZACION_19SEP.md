# Acta de estabilización — 19 septiembre 2026

Base `60993b7`. Candidato en `astra/estabilidad-19sep`; aún no aprobado para despliegue.
No se han modificado datos de producción ni iniciado conexiones/cobros.

## Evidencia completada

| Cambio o revisión | Evidencia | Resultado |
| --- | --- | --- |
| F4 contador de recordatorios, `83e5c56` | Antes: 2 rojos sin canales, 2 positivos verdes. Después: 48 dirigidos verdes (247.57s), incluyendo envíos, omisiones, reintentos, concurrencia y cambios de cita. Revisión independiente de código: OK acotado. | Corregido en candidato. Sin alterar audit/cierre de omitidos. |
| `b417618` teclado catálogo | Test adicional del manejador real con 301 servicios: 1 verde (4.03s); no elige invisible y el filtro alcanza último servicio. Fichero de portal también dentro de 48. | OK acotado, cobertura `eb74dc7`. |
| `0c0838c` fianza email | Lectura de diff y tests de fianza incluidos en 48: confirmed no pagada, pagada, sin depósito, cancelada. | OK acotado; no prueba cobro real Stripe. |
| `73f3302` CRM y `c484131` reparto | Revisor independiente: 66 existentes y 5 nuevos verdes; caso CRM tras limpieza verde. Código base `60993b7`. | OK acotado; cobertura integrada `ff45f3a`. |
| Supresión de aviso 2h, `d9ed572` | 1 dirigido verde; el doble devuelve ahora el contrato real de aceptación. | Conserva la regla de no recordar de nuevo a quien ya confirmó. |
| Aislamiento del portal ES/EN | 5 casos HTTP verdes (45.59s): respuestas por negocio, edición sobre conversaciones existentes y rechazo de lectura/edición/borrado ajenos. | Dos tenants ficticios, sin modelo ni Meta. No acredita pausa de temporada. |
| Apuntes, integración `7534f81` | Dos entregas comparadas: `3c646b0` y `93416aa`; se conserva la segunda, mismo diseño con igualdad de talla y pruebas del resolvedor real. Claude declara 20/20 y 5 mutaciones rojas. | Una implementación, no se suman ambas entregas como avances distintos. |
| Revisión adicional de apuntes | Media melena: 75 frente a 360; balayage descartado: 60 genéricos. Ambos rojos en base (26.47s) y en `93416aa` integrado (30.82s). Tras guardia compartida, 22 verdes (91.50s). | Reusa alias de `catalog_pick`, exige conservar lo escrito y retira el guardia que bastaba con compartir una palabra. |
| Nombres exactos con separadores | La revisión señaló paréntesis; paréntesis y guion: 2 rojos (26.39s). Texto y catálogo pasan ahora por el mismo separador. Dirigidos finales de apuntes y shim: 29 verdes (100.17s). | Revisión independiente de lectura sin nuevos hallazgos. |

No sumar ejecuciones solapadas como casos únicos ni atribuir suites de antecesores
al candidato nuevo. Los tiempos son de las ejecuciones informadas por las herramientas.
El contador de recordatorios acredita aceptación conocida (también recuperada de
una interrupción), no nuevas llamadas al transporte ni recepción de la clienta.

Incidencias de la validación: el primer proceso de aislamiento se interrumpió por
memoria insuficiente sin resultado. Dos ejecuciones posteriores tuvieron 5 errores
de preparación cada una: email `.invalid` rechazado por el esquema de login y
cookie Secure sobre HTTP. Se corrigió la fixture a `example.com` y HTTPS; no son
regresiones demostradas del producto ni se cuentan como casos medidos.

## Pendiente antes de aceptación técnica

- Congelar el candidato corregido con esta evidencia. El revisor automático
  ejecutará su única suite completa y la revisión exacta; Astra no la duplica.
- Procedimiento de pausa documentado: conjunto de silencio, facturación y
  reactivación aún no implementado/verificado. No se cierra por el verde de aislamiento.
- Diseño de la siguiente entrega: [PAUSA_TEMPORADA_DISENO.md](PAUSA_TEMPORADA_DISENO.md),
  `6a43942`. Autoridad persistida, admisión de envíos y cobro separado; sin código
  vivo ni pausa efectiva acreditada.
- Evaluar qué medición real comparable corresponde al cambio final: tabla separada
  Alicia/segundo negocio, primer intento/reintentos/fallos/no medidos/no aplica.
  Por ahora esta entrega no tiene nuevos resultados de modelo real.

| Modelo real del candidato nuevo | Primer intento | Tras reintento | Fallos | No medidos |
| --- | --- | --- | --- | --- |
| Alicia | No ejecutado | No ejecutado | No ejecutado | Banco completo |
| Segundo negocio | No ejecutado | No ejecutado | No ejecutado | Banco comparable completo |

El intérprete de apuntes y las reglas ES/EN de estos tests son deterministas: no
consumen modelo. No se relanzan bancos anteriores como si probaran el nuevo SHA,
ni se presenta esta tabla como aceptación del agente completo. La entrega no
cambia los prompts ni habilita el piloto D.

## Dependencias y límites externos

- Alicia: arranque noviembre, respuestas de catálogo aún pendientes; Stripe y
  WhatsApp sin conexión según último relevo. No se inventan datos ni políticas.
- Cap Rocat: documentación/respuestas y conexión pendientes; la pausa contractual
  no tiene un proceso conjunto verificado de silencio, cobro y reactivación.
- Meta: aceptación de transporte simulado no acredita entrega al teléfono. Prueba
  externa solo con entorno y destinatario autorizados, nunca clientas reales.
- Make: retirada ya documentada en producción; no repetir. D aparcado.

El estado será «candidato técnico verificado» únicamente con su evidencia y revisión;
«arranque operativo» exige además cumplir las dependencias del negocio y del canal.

## Revisión y corrección — 19-sep 15:10 Europe/Madrid

- Claude revisó por lectura el SHA exacto `f2003ec`: **CAMBIOS**. Reducir
  «corto o medio» a una talla ocultaba un pack de 360 min frente a un servicio
  corto de 75. F4 recibió OK acotado, con un doble de prueba adicional a corregir.
- Reproducción local: cuatro casos de tallas alternas rojos (38.57s).
  `1caa5af` conserva todas las tallas no solapadas usando el vocabulario existente;
  `talla_de` mantiene su selección anterior. Se comprueban también cinco vectores
  de compatibilidad y el texto sin coma, sin adivinar dónde acaba el nombre.
- Control de recordatorio: rojo con `failed == 1` cuando el doble devolvía `True`
  (ejecución conjunta: 1 failed, 8 passed, 58.03s). `e057f07` devuelve el contrato
  real y exige aceptación sin fallo. No cambia el transporte del producto.
- Validación conjunta final: **41 passed**, 131.32s, en apuntes, intérprete,
  shim, cita cancelada y contador. Revisión independiente del diff: OK por lectura;
  no sustituye la revisión exacta ni la suite completa del nuevo candidato.
- La suite de `f2003ec` empezó a las 14:39:41 y se detuvo a las 14:56:37 al
  invalidarse ese candidato. Aproximadamente 45%, sin fallos observados hasta
  entonces; **interrumpida, no aprobada**. Log y manifest en
  `E:/Vantelia-astra-estabilidad-evidencia/suite-f2003ec.{log,json}`.
- El modo rápido conserva los 30 minutos aceptados por Pablo: sin elegir una
  sugerencia puede guardar una nota con ese tiempo. No se presenta esta entrega
  como eliminación de ese riesgo operativo ni como nuevo resultado con modelo real.
